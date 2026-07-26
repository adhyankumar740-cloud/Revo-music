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


import config

# Local (sibling) import — safe at module load time, unlike importing the
# already-instantiated `TgScrap` object from the BROKENXMUSIC package,
# which doesn't exist yet while platforms/__init__ is still loading.
from .TgScrap import TgScrapAPI

_tgscrap = TgScrapAPI()


def _extract_video_id(link: str) -> str:
    return link.split("v=")[-1].split("&")[0] if "v=" in link else link


# YoutubeSearch does blocking HTTP scraping under the hood (plain `requests`,
# no asyncio). Calling it directly inside an `async def` freezes the ENTIRE
# bot's event loop for however long that HTTP round-trip takes — every group,
# every voice chat, every other user's command stalls too. Always dispatch it
# to a worker thread instead, and cache identical lookups briefly so repeated
# requests (a song replayed, several chats requesting the same track) don't
# re-hit YouTube at all.
_search_cache: dict = {}
_SEARCH_CACHE_TTL = 300  # seconds


async def _search_youtube(query: str, max_results: int = 1):
    import time as _time

    cache_key = (query, max_results)
    cached = _search_cache.get(cache_key)
    if cached and (_time.time() - cached[0]) < _SEARCH_CACHE_TTL:
        return cached[1]

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: YoutubeSearch(query, max_results=max_results).to_dict()
    )
    _search_cache[cache_key] = (_time.time(), results)
    # Hot-path perf cache, not a correctness-critical store — just drop
    # everything once it gets big instead of tracking per-key expiry.
    if len(_search_cache) > 500:
        _search_cache.clear()
    return results


async def _get_title(video_id: str) -> str:
    """Best-effort title lookup, used only to build a search query for TgScrap."""
    try:
        results = await _search_youtube(f"https://www.youtube.com/watch?v={video_id}", 1)
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


# --- OPTIONAL: direct yt-dlp (+cookies) fast path -------------------------
# Self-contained on purpose: if this misbehaves, set config.ENABLE_YTDLP_DIRECT_AUDIO
# back to False (or delete this whole block + its one call-site below) and
# everything reverts to the original SongCache -> TgScrap flow untouched.
async def _download_audio_ytdlp(video_id: str) -> str:
    logger = LOGGER("YtDlpDirect/Youtube.py")
    file_path = os.path.join("downloads", f"{video_id}.mp3")

    if os.path.exists(file_path):
        return file_path

    url = f"https://www.youtube.com/watch?v={video_id}"
    ytdl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join("downloads", f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # Required so yt-dlp can fetch its JS challenge-solver script (runs
        # via the Deno runtime installed in the Dockerfile). Without this,
        # Deno is present but unused and YouTube only returns image formats.
        "remote_components": ["ejs:github"],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
    }

    cookies_path = getattr(config, "YTDLP_COOKIES_FILE", "").strip()
    if cookies_path and os.path.exists(cookies_path):
        ytdl_opts["cookiefile"] = cookies_path
    elif cookies_path:
        logger.warning(f"⚠️ [YTDLP-DIRECT] cookies file not found at '{cookies_path}', continuing without it")

    try:
        loop = asyncio.get_event_loop()

        def _run():
            import yt_dlp
            with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                ydl.download([url])

        await loop.run_in_executor(None, _run)

        if os.path.exists(file_path):
            logger.info(f"✅ [YTDLP-DIRECT] download complete: {video_id}")
            return file_path

        logger.error(f"❌ [YTDLP-DIRECT] file not found after download: {video_id}")
        return None
    except Exception as e:
        logger.error(f"❌ [YTDLP-DIRECT] failed ({video_id}): {e}")
        return None
# --- end optional block ----------------------------------------------------


async def download_song(link: str) -> str:
    """
    Audio downloads: local disk cache first (plain files, no Mongo/Telegram
    round-trip), then yt-dlp direct (fast path), then Tg-Scrap as the last
    resort. Any successful download is handed back for playback IMMEDIATELY
    — caching it for next time happens in a background task afterwards, so
    it never adds latency to the current play.
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

    # Plain local disk cache — no Mongo, no Telegram, just a filesystem
    # read. Checked first regardless of the (now-optional, off-by-default)
    # SongCache system below.
    from BROKENXMUSIC.utils import local_cache
    try:
        cached_path = await local_cache.get(query) or await local_cache.get(raw_title)
        if cached_path:
            logger.info(f"✅ [AUDIO] Local disk cache hit: {query!r}")
            return cached_path
    except Exception as e:
        logger.error(f"❌ [AUDIO] Local cache lookup failed: {e}")

    def _cache_in_background(key: str, path: str):
        """Fire-and-forget: never let caching delay handing the file back."""
        async def _do():
            try:
                await local_cache.put(key, path)
            except Exception as e:
                logger.error(f"❌ [AUDIO] Background local cache save failed for {key!r}: {e}")
        asyncio.create_task(_do())

    # Optional legacy path: Mongo+Telegram channel cache. OFF by default
    # now (config.ENABLE_SONG_CACHE=False) — set it True again to restore
    # the old behaviour, nothing else to change.
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

    # Primary path: yt-dlp + cookies (fast — a couple of seconds).
    if getattr(config, "ENABLE_YTDLP_DIRECT_AUDIO", False):
        try:
            ytdlp_path = await _download_audio_ytdlp(video_id)
            if ytdlp_path and os.path.exists(ytdlp_path):
                logger.info(f"✅ [AUDIO] yt-dlp direct hit: {video_id}")
                _cache_in_background(query, ytdlp_path)
                return ytdlp_path
        except Exception as e:
            logger.error(f"❌ [AUDIO] yt-dlp direct fast path failed, falling back to TgScrap: {e}")

    # Last resort: TgScrap (VK-Music-style bot scrape via userbot).
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
    _cache_in_background(query, filepath)
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
            import yt_dlp  # lazy: audio-only playback (the common case) never needs this

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
            results = await _search_youtube(link, 1)
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
            results = await _search_youtube(link, 1)
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
            results = await _search_youtube(link, 1)
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
            results = await _search_youtube(link, 1)
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

            
            results = await _search_youtube(link, 1)
            
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
        import yt_dlp  # lazy: only the /formats/quality-picker path needs this

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
            results = await _search_youtube(link, 10)
            
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
