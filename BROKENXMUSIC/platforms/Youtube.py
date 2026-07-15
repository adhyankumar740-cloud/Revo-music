"""© 2026 BROKEN X NETWORK | All Rights Reserved"""
# 2024 - 2026 ©️ BROKEN X NETWORK | ALL RIGHTS RESERVED 
# MADE WITH ❤️ BY MR BROKEN
# FOR UPDATES JOIN TG: @BROKENXNETWORK1 & @ABOUTBROKENX

import asyncio
import os
import re
import json
import time
from typing import Union
import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from youtube_search import YoutubeSearch

from ..utils.database import is_on_off
from ..utils.formatters import time_to_seconds
from BROKENXMUSIC import app
import random
import logging
import aiohttp
from BROKENXMUSIC import LOGGER
from urllib.parse import urlparse


try:
    from BROKENXMUSIC import config
except ImportError:
    class config:
        YOUTUBE_IMG_URL = "https://telegra.ph/file/8ba38eca9318beb6dcede.jpg"

from brokenxapi import BrokenXAPI

API_KEY = os.getenv("API_KEY", "PUT_YOUR_BROKENXAPI_KEY_HERE") #GET THIS FROM TG: https://t.me/BROKENXNETWORK1 or https://t.me/AboutBrokenX

# How long we'll wait on the external BrokenXAPI download/convert call before
# giving up. Without this, a slow/hung upstream response hangs the whole
# request until the platform's own gateway timeout (Render/Koyeb) kills it -
# which shows up as an unexplained timeout with no useful error in our logs.
BROKENXAPI_TIMEOUT = int(os.getenv("BROKENXAPI_TIMEOUT", 25))

# How long we'll wait for the downloaded file to actually land on disk after
# msg.download() is kicked off.
TELEGRAM_FILE_WAIT_TIMEOUT = int(os.getenv("TELEGRAM_FILE_WAIT_TIMEOUT", 60))

# app.get_messages() and msg.download() were the two calls with NO timeout at
# all - if the assistant account had trouble reaching the channel (network
# hiccup, flood wait, etc.) these could hang indefinitely with zero log
# output, which is exactly what we saw: BROKENXAPI_TIMEOUT never fired, but
# the outer 45s resolve timeout did. Bounding these individually means we'll
# now get a clear log line naming the actual slow step instead of a generic
# timeout after the fact.
GET_MESSAGES_TIMEOUT = int(os.getenv("GET_MESSAGES_TIMEOUT", 15))
MSG_DOWNLOAD_TIMEOUT = int(os.getenv("MSG_DOWNLOAD_TIMEOUT", 20))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STREAMING PATH (Android app relay)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Group-VC playback (download_song/get_telegram_file below) NEEDS a full
# local file on disk because pytgcalls streams from a file path. The relay
# for the Android app doesn't - it just proxies bytes over HTTP - so instead
# of blocking /resolve on a full server-side download-then-wait-for-disk
# cycle (which is what kept timing out), we only resolve WHERE the file
# lives on Telegram here. The actual bytes are fetched chunk-by-chunk,
# lazily, only when the client hits /stream - via Pyrogram's stream_media().
# This means /resolve returns almost immediately regardless of file size,
# and playback can start before the whole file has even been fetched.

async def _confirm_telegram_message(channel_name: str, message_id: int, video_id: str, logger) -> bool:
    """Shared has-the-media-actually-landed check, used both for a fresh
    BrokenXAPI telegram_url and for re-confirming a cache hit below."""
    msg = await get_cached_message(channel_name, message_id, video_id)
    return msg is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MESSAGE CACHE (shared between /resolve's confirm step and /stream)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /resolve already fetches this exact Message via get_messages() to confirm
# the media landed. Without this cache, /stream fetched the SAME message
# again a moment later - a second Telegram round-trip for information we
# already had. Reusing it here removes that duplicate call on every play,
# not just the first one.
_message_cache: dict[tuple[str, int], tuple[object, float]] = {}


async def get_cached_message(channel_name: str, message_id: int, video_id: str = ""):
    key = (channel_name, message_id)
    cached = _message_cache.get(key)
    if cached:
        msg, ts = cached
        if time.monotonic() - ts <= RESOLVE_CACHE_TTL:
            return msg
        _message_cache.pop(key, None)

    logger = LOGGER("BrokenXAPI")
    try:
        msg = await asyncio.wait_for(
            app.get_messages(channel_name, message_id), timeout=GET_MESSAGES_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.error(
            f"⏱️ [STREAM] get_messages() hung for {GET_MESSAGES_TIMEOUT}s on "
            f"{channel_name}/{message_id} for {video_id}"
        )
        return None

    if msg and any([msg.audio, msg.voice, msg.document, msg.video]):
        _message_cache[key] = (msg, time.monotonic())
        return msg
    return None


async def resolve_telegram_location(telegram_url: str, video_id: str):
    """Look up the (channel, message_id) for a BrokenXAPI telegram_url
    WITHOUT downloading anything. Returns (None, None) on any failure."""
    logger = LOGGER("BrokenAPI/Youtube.py")

    parsed = urlparse(telegram_url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        logger.error(f"❌ [STREAM] Invalid Telegram link format: {telegram_url}")
        return None, None

    channel_name = parts[0]
    message_id = int(parts[1])

    if not await _confirm_telegram_message(channel_name, message_id, video_id, logger):
        logger.error(f"❌ [STREAM] No usable media at {channel_name}/{message_id} for {video_id}")
        return None, None

    logger.info(f"✅ [STREAM] Located {video_id} at {channel_name}/{message_id}")
    return channel_name, message_id


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESOLVE CACHE + PREFETCH (cuts the "first play buffers a lot" delay)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# The slow part of a first-time /resolve is the BrokenXAPI api.download()
# call itself - THAT is what actually pulls the video from YouTube, converts
# it, and uploads it to the Telegram channel. Once that's done once, we
# already know exactly where the file lives, so:
#   1. we cache (video_id -> channel_name, message_id) after every
#      successful resolve, and skip straight past BrokenXAPI on a hit
#      (just re-confirming the Telegram message is still there, which is
#      fast - one get_messages() call instead of a full download+upload).
#   2. app.py's /search calls prefetch_video() on the top results in the
#      background, so the BrokenXAPI download for a brand new song starts
#      while the user is still looking at the results list, not after they
#      tap play.
RESOLVE_CACHE_TTL = int(os.getenv("RESOLVE_CACHE_TTL", 21600))  # 6h
_resolve_cache: dict[str, tuple[str, int, float]] = {}


def _cache_get(video_id: str):
    entry = _resolve_cache.get(video_id)
    if not entry:
        return None, None
    channel_name, message_id, ts = entry
    if time.monotonic() - ts > RESOLVE_CACHE_TTL:
        _resolve_cache.pop(video_id, None)
        return None, None
    return channel_name, message_id


def _cache_put(video_id: str, channel_name: str, message_id: int):
    _resolve_cache[video_id] = (channel_name, message_id, time.monotonic())


async def resolve_song_stream_location(link: str):
    """Same BrokenXAPI call as download_song(), but stops right after
    finding the Telegram message - no download, no disk write."""
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    logger = LOGGER("BrokenXAPI")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [STREAM] Invalid video ID: {video_id}")
        return None, None

    cached_channel, cached_message_id = _cache_get(video_id)
    if cached_channel:
        if await _confirm_telegram_message(cached_channel, cached_message_id, video_id, logger):
            logger.info(f"⚡ [STREAM] Cache hit for {video_id} at {cached_channel}/{cached_message_id}")
            return cached_channel, cached_message_id
        _resolve_cache.pop(video_id, None)  # stale - fall through to a full resolve

    try:
        async with BrokenXAPI(api_key=API_KEY) as api:
            data = await asyncio.wait_for(
                api.download(video_id, "audio"), timeout=BROKENXAPI_TIMEOUT
            )

        if not data or "telegram_url" not in data:
            logger.error(f"❌ [STREAM] Invalid SDK response: {data}")
            return None, None

        channel_name, message_id = await resolve_telegram_location(data["telegram_url"], video_id)
        if channel_name:
            _cache_put(video_id, channel_name, message_id)
        return channel_name, message_id

    except asyncio.TimeoutError:
        logger.error(f"⏱️ [STREAM] BrokenXAPI did not respond within {BROKENXAPI_TIMEOUT}s for {video_id}")
        return None, None
    except Exception as e:
        logger.error(f"❌ [STREAM] Exception: {e}")
        return None, None


_prefetching: set[str] = set()


async def prefetch_video(video_id: str):
    """Fire-and-forget warm-up called from /search. Kicks off the exact
    same resolve a real /resolve request would do, so a brand new video's
    BrokenXAPI download+convert+upload happens while the user is still
    browsing search results instead of after they tap play."""
    if video_id in _prefetching or _cache_get(video_id)[0]:
        return
    _prefetching.add(video_id)
    logger = LOGGER("BrokenXAPI")
    try:
        await resolve_song_stream_location(video_id)
    except Exception as e:
        logger.error(f"❌ [PREFETCH] {video_id}: {e}")
    finally:
        _prefetching.discard(video_id)


async def get_telegram_file(telegram_url: str, video_id: str, file_type: str) -> str:
    logger = LOGGER("BrokenAPI/Youtube.py")
    try:
        extension = ".m4a" if file_type == "audio" else ".mp4"
        file_path = os.path.join("downloads", f"{video_id}{extension}")

        if os.path.exists(file_path):
            logger.info(f"📂 [LOCAL] File exists: {video_id}")
            return file_path

        parsed = urlparse(telegram_url)
        parts = parsed.path.strip("/").split("/")

        if len(parts) < 2:
            logger.error(f"❌ Invalid Telegram link format: {telegram_url}")
            return None

        channel_name = parts[0]
        message_id = int(parts[1])

        logger.info(f"📨 [TELEGRAM] Fetching message {message_id} from {channel_name} for {video_id}")
        try:
            msg = await asyncio.wait_for(
                app.get_messages(channel_name, message_id), timeout=GET_MESSAGES_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(
                f"⏱️ [TELEGRAM] get_messages() hung for {GET_MESSAGES_TIMEOUT}s on {channel_name}/{message_id} "
                f"for {video_id} - assistant account likely can't reach this channel (no access / flood wait / network issue)"
            )
            return None

        if msg is None:
            logger.error(f"❌ [TELEGRAM] get_messages returned None for {channel_name}/{message_id} - wrong channel/message id, or bot has no access to it")
            return None

        has_media = any([msg.audio, msg.voice, msg.document, msg.video])
        logger.info(
            f"📎 [TELEGRAM] Message fetched for {video_id} - has_media={has_media} "
            f"(audio={bool(msg.audio)}, voice={bool(msg.voice)}, document={bool(msg.document)}, video={bool(msg.video)})"
        )

        if not has_media:
            logger.error(f"❌ [TELEGRAM] Message {channel_name}/{message_id} has no file yet for {video_id} - BrokenXAPI probably hadn't finished uploading it when we checked")
            return None

        os.makedirs("downloads", exist_ok=True)
        try:
            download_result = await asyncio.wait_for(
                msg.download(file_name=file_path), timeout=MSG_DOWNLOAD_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"⏱️ [TELEGRAM] msg.download() hung for {MSG_DOWNLOAD_TIMEOUT}s for {video_id}")
            return None
        logger.info(f"📥 [TELEGRAM] download() for {video_id} returned: {download_result}")

        # Pyrogram's msg.download() already blocks until the file is fully
        # written and returns the actual saved path - it does NOT return
        # early. Trust that return value directly instead of re-polling
        # os.path.exists() on our own expected file_path: if Pyrogram saved
        # it under a slightly different name/path than we assumed, the old
        # polling loop would spin for the full timeout and fail even though
        # the download had already succeeded.
        if download_result and os.path.exists(download_result):
            logger.info(f"✅ [TELEGRAM] Downloaded: {video_id} -> {download_result}")
            return download_result

        if os.path.exists(file_path):
            logger.info(f"✅ [TELEGRAM] Downloaded: {video_id}")
            return file_path
        else:
            logger.error(f"❌ [TELEGRAM] Timeout: {video_id} - download() returned {download_result!r} but no file ever showed up at {file_path}")
            return None

    except Exception as e:
        logger.error(f"❌ [TELEGRAM] Failed to download {video_id}: {e}")
        return None


async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    logger = LOGGER("BrokenXAPI")
    logger.info(f"🎵 [AUDIO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [AUDIO] Invalid video ID: {video_id}")
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{video_id}.webm")

    if os.path.exists(file_path):
        logger.info(f"🎵 [LOCAL] File exists: {video_id}")
        return file_path

    try:
        async with BrokenXAPI(api_key=API_KEY) as api:
            data = await asyncio.wait_for(
                api.download(video_id, "audio"), timeout=BROKENXAPI_TIMEOUT
            )

        if not data or "telegram_url" not in data:
            logger.error(f"❌ [AUDIO] Invalid SDK response: {data}")
            return None

        return await get_telegram_file(data["telegram_url"], video_id, "audio")

    except asyncio.TimeoutError:
        logger.error(f"⏱️ [AUDIO] BrokenXAPI did not respond within {BROKENXAPI_TIMEOUT}s for {video_id}")
        return None
    except Exception as e:
        logger.error(f"❌ [AUDIO] Exception: {e}")
        return None


async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link
    logger = LOGGER("BrokenXAPI")
    logger.info(f"🎥 [VIDEO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [VIDEO] Invalid video ID: {video_id}")
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{video_id}.mkv")

    if os.path.exists(file_path):
        logger.info(f"🎥 [LOCAL] File exists: {video_id}")
        return file_path

    try:
        async with BrokenXAPI(api_key=API_KEY) as api:
            data = await api.download(video_id, "video")

        if not data or "telegram_url" not in data:
            logger.error(f"❌ [VIDEO] Invalid SDK response: {data}")
            return None

        return await get_telegram_file(data["telegram_url"], video_id, "video")

    except Exception as e:
        logger.error(f"❌ [VIDEO] Exception: {e}")
        return None


async def check_file_size(link):
    async def get_format_info(link):
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f'Error:\n{stderr.decode()}')
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if 'filesize' in format:
                total_size += format['filesize']
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None

    formats = info.get('formats', [])
    if not formats:
        print("No formats found.")
        return None

    total_size = parse_size(formats)
    return total_size


async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        return text[entity.offset: entity.offset + entity.length]
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
            
        # Updated to use YoutubeSearch
        try:
            results = YoutubeSearch(link, max_results=1).to_dict()
            if not results:
                return None, None, None, None, None
            
            result = results[0]
            title = result.get("title", "Unknown")
            duration_min = result.get("duration", "00:00")
            thumbnail = result.get("thumbnails", [""])[0]
            vidid = result.get("id")
            duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
            
            return title, duration_min, duration_sec, thumbnail, vidid
        except:
            return None, None, None, None, None

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = YoutubeSearch(link, max_results=1).to_dict()
            if results:
                return results[0].get("title")
        except:
            return None

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = YoutubeSearch(link, max_results=1).to_dict()
            if results:
                return results[0].get("duration")
        except:
            return None

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = YoutubeSearch(link, max_results=1).to_dict()
            if results:
                return results[0].get("thumbnails", [""])[0]
        except:
            return None

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
            else:
                return 0, "Video download failed"
        except Exception as e:
            return 0, f"Video download error: {e}"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        playlist = await shell_cmd(
            f"yt-dlp -i --get-id --flat-playlist --playlist-end {limit} --skip-download {link}"
        )
        try:
            result = [key for key in playlist.split("\n") if key]
        except:
            result = []
        return result

    # --- UPDATED TRACK METHOD USING youtube_search ---
    async def track(self, link: str, videoid: Union[bool, str] = None):
        logger = LOGGER("BrokenXAPI") 
        try:
            if videoid:
                link = self.base + link

            if "&" in link:
                link = link.split("&")[0]

            
            results = YoutubeSearch(link, max_results=1).to_dict()
            
            print(f"YoutubeSearch Results: {results}")

            if not results:
                logger.error(f"❌ No results found for: {link}")
                return None, None

            
            result = results[0]

            title = result.get("title", "Unknown Title")
            duration_min = result.get("duration", "00:00")
            vidid = result.get("id")
            
            
            url_suffix = result.get("url_suffix", "")
            yturl = f"https://www.youtube.com{url_suffix}"

            
            thumbnails = result.get("thumbnails", [])
            if thumbnails and isinstance(thumbnails, list):
                thumbnail = thumbnails[0].split("?")[0]
            elif isinstance(thumbnails, str):
                thumbnail = thumbnails
            else:
                thumbnail = config.YOUTUBE_IMG_URL

            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "thumb": thumbnail,
            }

            return track_details, vidid

        except Exception as e:
            LOGGER("BrokenAPI/Youtube.py").error(f"❌ Track fetch failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    if "dash" not in str(format["format"]).lower():
                        formats_available.append(
                            {
                                "format": format["format"],
                                "filesize": format.get("filesize"),
                                "format_id": format["format_id"],
                                "ext": format["ext"],
                                "format_note": format["format_note"],
                                "yturl": link,
                            }
                        )
                except:
                    continue
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        
        
        try:
            results = YoutubeSearch(link, max_results=10).to_dict()
            
            if not results or len(results) <= query_type:
                return None, None, None, None

            item = results[query_type]
            
            title = item.get("title")
            duration_min = item.get("duration")
            vidid = item.get("id")
            
            thumbnails = item.get("thumbnails", [])
            if thumbnails and isinstance(thumbnails, list):
                thumbnail = thumbnails[0].split("?")[0]
            else:
                thumbnail = ""
                
            return title, duration_min, thumbnail, vidid
        except Exception as e:
            print(f"Slider Error: {e}")
            return None, None, None, None

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link

        try:
            if video:
                downloaded_file = await download_video(link)
                if downloaded_file:
                    return downloaded_file, True
                else:
                    return None, False
            else:
                downloaded_file = await download_song(link)
                if downloaded_file:
                    return downloaded_file, True
                else:
                    return None, False

        except Exception as e:
            logger = LOGGER("BrokenAPI/Youtube.py")
            logger.error(f"❌ Download failed: {e}")
            return None, False
