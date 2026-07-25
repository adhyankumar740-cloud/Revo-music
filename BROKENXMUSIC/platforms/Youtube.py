"""© 2026 BROKEN X NETWORK | All Rights Reserved"""
# 2024 - 2026 ©️ BROKEN X NETWORK | ALL RIGHTS RESERVED 
# MADE WITH ❤️ BY MR BROKEN
# FOR UPDATES JOIN TG: @BROKENXNETWORK1 & @ABOUTBROKENX

import asyncio
import os
import re
import json
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


try:
    from BROKENXMUSIC import config
except ImportError:
    class config:
        YOUTUBE_IMG_URL = "https://telegra.ph/file/8ba38eca9318beb6dcede.jpg"

# Local (sibling) import — safe at module load time, unlike importing the
# already-instantiated `TgScrap` object from the BROKENXMUSIC package,
# which doesn't exist yet while platforms/__init__ is still loading.
from .TgScrap import TgScrapAPI

_tgscrap = TgScrapAPI()


def _extract_video_id(link: str) -> str:
    return link.split("v=")[-1].split("&")[0] if "v=" in link else link


async def _get_title(video_id: str) -> str:
    """Best-effort title lookup, used only to build a search query for TgScrap."""
    try:
        results = YoutubeSearch(f"https://www.youtube.com/watch?v={video_id}", max_results=1).to_dict()
        if results:
            return results[0].get("title") or video_id
    except Exception:
        pass
    return video_id


# YouTube titles are usually cluttered with stuff like "Full Song With Lyrics |
# Actor, Actress" which the VK-Music Telegram bot's search can't match. Strip
# that noise down to just the song name before using it as a search query.
_NOISE_PATTERNS = [
    r"\(.*?\)",
    r"\[.*?\]",
    r"\|.*",
    r"[-–—:]\s*full\s+(video\s+)?song.*",
    r"\bofficial\s+(music\s+)?video\b",
    r"\bofficial\s+audio\b",
    r"\bfull\s+video\s+song\b",
    r"\bfull\s+song\b",
    r"\bwith\s+lyrics?\b",
    r"\blyric\s+video\b",
    r"\blyrics?\b",
    r"\bvideo\s+song\b",
    r"\baudio\s+song\b",
    r"\b(hd|4k|8k|1080p|720p)\b",
]


def _clean_query(title: str) -> str:
    q = title
    for pat in _NOISE_PATTERNS:
        q = re.sub(pat, "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s{2,}", " ", q).strip(" -|:\u2013\u2014\"'\u2018\u2019\u201c\u201d")
    return q or title


async def download_song(link: str) -> str:
    """
    Audio downloads check the Song Cache (your own channels) first, then
    fall back to Tg-Scrap (VK-Music-style Telegram bot, driven by our own
    userbot) instead of the old BrokenXAPI service.
    """
    video_id = _extract_video_id(link)
    logger = LOGGER("TgScrap/Youtube.py")
    logger.info(f"🎵 [AUDIO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [AUDIO] Invalid video ID: {video_id}")
        return None

    os.makedirs("downloads", exist_ok=True)

    raw_title = await _get_title(video_id)
    query = _clean_query(raw_title)
    logger.info(f"🔎 [AUDIO] Raw title: '{raw_title}' -> cleaned query: '{query}'")

    # Song Cache: check our own channels first — instant, no vkmusic_bot
    # round-trip at all.
    if config.ENABLE_SONG_CACHE:
        from BROKENXMUSIC import SongCache
        try:
            cache_hit = await SongCache.search(query) or await SongCache.search(raw_title)
            if cache_hit:
                track_details, filepath = await SongCache.fetch_file(cache_hit)
                if filepath and os.path.exists(filepath):
                    logger.info(f"✅ [AUDIO] Song Cache hit: {query!r}")
                    return filepath
        except Exception as e:
            logger.error(f"❌ [AUDIO] Song Cache lookup failed: {e}")

    try:
        track_details, filepath = await _tgscrap.download(query)
    except Exception as e:
        logger.error(f"❌ [AUDIO] TgScrap exception (cleaned query): {e}")
        track_details, filepath = None, None

    if (not filepath or not os.path.exists(filepath)) and query != raw_title:
        logger.info(f"↩️ [AUDIO] Cleaned query failed, retrying with raw title: '{raw_title}'")
        try:
            track_details, filepath = await _tgscrap.download(raw_title)
        except Exception as e:
            logger.error(f"❌ [AUDIO] TgScrap exception (raw title): {e}")
            return None

    if not filepath or not os.path.exists(filepath):
        logger.error(f"❌ [AUDIO] TgScrap failed for: {query}")
        return None

    logger.info(f"✅ [AUDIO] TgScrap download complete: {query}")

    # Grow the cache so the next request for this song is instant.
    if config.ENABLE_SONG_CACHE and config.SONG_CACHE_CHANNEL:
        from BROKENXMUSIC import SongCache
        try:
            await SongCache.save_to_cache(query, filepath, track_details["title"], track_details["duration_min"])
        except Exception as e:
            logger.error(f"❌ [AUDIO] Song Cache save failed: {e}")

    return filepath


async def download_video(link: str) -> str:
    """
    Tg-Scrap (VK Music bot) only serves audio, so video downloads still
    go through yt-dlp directly (plain, no cookies configured).
    """
    video_id = _extract_video_id(link)
    logger = LOGGER("YtDlp/Youtube.py")
    logger.info(f"🎥 [VIDEO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [VIDEO] Invalid video ID: {video_id}")
        return None

    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{video_id}.mp4")

    if os.path.exists(file_path):
        logger.info(f"🎥 [LOCAL] File exists: {video_id}")
        return file_path

    url = f"https://www.youtube.com/watch?v={video_id}"
    ytdl_opts = {
        "format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": file_path.replace(".mp4", ".%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }

    try:
        loop = asyncio.get_event_loop()

        def _run():
            with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                ydl.download([url])

        await loop.run_in_executor(None, _run)

        if os.path.exists(file_path):
            logger.info(f"✅ [VIDEO] yt-dlp download complete: {video_id}")
            return file_path

        logger.error(f"❌ [VIDEO] File not found after download: {video_id}")
        return None

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
        logger = LOGGER("YoutubeSearch/Youtube.py") 
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
