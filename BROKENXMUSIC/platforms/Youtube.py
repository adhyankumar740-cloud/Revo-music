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


def _hf_headers() -> dict:
    key = getattr(config, "HF_RESOLVER_API_KEY", "")
    return {"x-api-key": key} if key else {}


def _hf_base() -> str:
    return getattr(config, "HF_RESOLVER_URL", "")


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


async def _get_stream_url_ytdlp(video_id: str):
    """
    LIVE STREAMING fast-path: resolve a direct, ffmpeg-playable audio URL
    straight from YouTube's CDN — no file is downloaded or written to disk
    at all. pytgcalls/ffmpeg then reads and decodes that URL live as the
    group call plays it, exactly like this bot's existing M3U8/"index link"
    direct-URL playback already does (see _build_stream / join_call).

    yt-dlp itself no longer runs on Render at all for this path — it has
    been fully offloaded to an external HF Space running yt-dlp, which
    resolves in ~2-4s vs ~15-20s locally on Render's free CPU. This keeps
    Render lightweight (no yt-dlp/deno/JS-challenge-solving weight) and
    fast. If HF_RESOLVER_URL isn't configured or the Space is unreachable,
    this returns None and the caller falls back to whatever non-yt-dlp
    playback path it already has (e.g. TgScrap) — there is intentionally
    no local yt-dlp fallback anymore.
    """
    logger = LOGGER("YtDlpDirect/Youtube.py")

    hf_resolver_url = getattr(config, "HF_RESOLVER_URL", "")
    if not hf_resolver_url:
        logger.warning("⚠️ [YTDLP-DIRECT] HF_RESOLVER_URL not set — yt-dlp streaming disabled on Render")
        return None

    hf_timeout = getattr(config, "HF_RESOLVER_TIMEOUT", 8)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=hf_timeout)
        ) as session:
            async with session.get(
                f"{hf_resolver_url}/api/resolve", params={"v": video_id}, headers=_hf_headers()
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok") and data.get("stream_url"):
                        logger.info(
                            f"✅ [YTDLP-DIRECT] resolved via hf-space/{data.get('tier')} "
                            f"in {data.get('elapsed')}s: {video_id}"
                        )
                        return data["stream_url"]
                    logger.error(f"❌ [YTDLP-DIRECT] hf-space returned no url ({video_id}): {data.get('error')}")
                else:
                    logger.error(f"❌ [YTDLP-DIRECT] hf-space HTTP {resp.status} ({video_id})")
    except Exception as e:
        logger.error(f"❌ [YTDLP-DIRECT] hf-space unreachable/timeout ({video_id}): {e}")
    return None


# --- Downloads (audio + video) now go entirely through the HF Space's
# /api/download endpoint — it runs yt-dlp server-side and streams the
# resulting file back over plain HTTP; we just save that stream to disk.
# No yt-dlp import happens on Render for this at all anymore.
def _find_downloaded(video_id: str, kind: str = "audio"):
    """Return whichever downloads/{kind}_{video_id}.* file exists, any ext."""
    import glob
    matches = glob.glob(os.path.join("downloads", f"{kind}_{video_id}.*"))
    matches = [m for m in matches if not m.endswith((".part", ".ytdl", ".temp"))]
    return matches[0] if matches else None


async def _hf_download(video_id: str, kind: str, format_id: str = None) -> str:
    """Streams a file from the HF Space's /api/download endpoint straight
    to local disk (downloads/{kind}_{video_id}.<ext from filename>).
    Returns the local path, or None on any failure."""
    logger = LOGGER("YtDlpDirect/Youtube.py")

    hf_resolver_url = _hf_base()
    if not hf_resolver_url:
        logger.warning(f"⚠️ [HF-DOWNLOAD] HF_RESOLVER_URL not set — {kind} download unavailable")
        return None

    existing = _find_downloaded(video_id, kind)
    if existing:
        return existing

    os.makedirs("downloads", exist_ok=True)
    dl_timeout = getattr(config, "HF_RESOLVER_DOWNLOAD_TIMEOUT", 60)
    params = {"v": video_id, "type": kind}
    if format_id:
        params["format"] = format_id

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=dl_timeout)
        ) as session:
            async with session.get(
                f"{hf_resolver_url}/api/download", params=params, headers=_hf_headers()
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"❌ [HF-DOWNLOAD] HTTP {resp.status} for {video_id}: {body[:200]}")
                    return None

                # Extract extension from the Content-Disposition filename
                # the Space sends (e.g. "audio_<id>.m4a" / "video_<id>.mp4").
                cd = resp.headers.get("Content-Disposition", "")
                ext = "m4a" if kind == "audio" else "mp4"
                if "filename=" in cd:
                    fname = cd.split("filename=")[-1].strip('"; ')
                    if "." in fname:
                        ext = fname.rsplit(".", 1)[-1]

                dest = os.path.join("downloads", f"{kind}_{video_id}.{ext}")
                tmp_dest = dest + ".part"
                with open(tmp_dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 256):
                        f.write(chunk)
                os.replace(tmp_dest, dest)
                logger.info(f"✅ [HF-DOWNLOAD] {kind} download complete: {video_id}")
                return dest
    except Exception as e:
        logger.error(f"❌ [HF-DOWNLOAD] failed ({kind}, {video_id}): {e}")
        return None


async def _download_audio_ytdlp(video_id: str) -> str:
    return await _hf_download(video_id, "audio")


async def download_song(link: str, title: str = None) -> str:
    """
    Audio downloads: local disk cache first (plain files, no Mongo/Telegram
    round-trip), then yt-dlp direct (fast path), then Tg-Scrap as the last
    resort. Any successful download is handed back for playback IMMEDIATELY
    — caching it for next time happens in a background task afterwards, so
    it never adds latency to the current play.

    `title`, if the caller already has it (e.g. from the search results
    used to build the "Now Playing" message), skips the redundant
    _get_title() YouTube search that would otherwise re-fetch the exact
    same title info this function's caller usually already looked up.
    """
    video_id = _extract_video_id(link)
    logger = LOGGER("TgScrap/Youtube.py")
    logger.info(f"🎵 [AUDIO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [AUDIO] Invalid video ID: {video_id}")
        return None

    os.makedirs("downloads", exist_ok=True)

    # Cache check #1 — by video_id, BEFORE any network call.
    from BROKENXMUSIC.utils import local_cache
    try:
        cached_path = await local_cache.get(video_id)
        if cached_path:
            logger.info(f"✅ [AUDIO] Local disk cache hit (by video_id, no lookup needed): {video_id}")
            return cached_path
    except Exception as e:
        logger.error(f"❌ [AUDIO] Local cache (video_id) lookup failed: {e}")

    if title:
        raw_title = title
        logger.info(f"🔎 [AUDIO] Using caller-supplied title (skipped search): '{raw_title}'")
    else:
        raw_title = await _get_title(video_id)
    query = _clean_query(raw_title)
    logger.info(f"🔎 [AUDIO] Raw title: '{raw_title}' -> cleaned query: '{query}'")

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
                if key != video_id:
                    await local_cache.put(video_id, path)
            except Exception as e:
                logger.error(f"❌ [AUDIO] Background local cache save failed for {key!r}: {e}")
        asyncio.create_task(_do())

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

    if getattr(config, "ENABLE_YTDLP_DIRECT_AUDIO", False):
        try:
            stream_url = await _get_stream_url_ytdlp(video_id)
            if stream_url:
                logger.info(f"✅ [AUDIO] live-stream hit (no download wait): {video_id}")

                async def _bg_download_and_cache():
                    try:
                        path = await _download_audio_ytdlp(video_id)
                        if path and os.path.exists(path):
                            _cache_in_background(query, path)
                    except Exception as e:
                        logger.error(f"❌ [AUDIO] Background full download failed for {video_id}: {e}")

                asyncio.create_task(_bg_download_and_cache())
                return stream_url
        except Exception as e:
            logger.error(f"❌ [AUDIO] live-stream resolve failed, falling back to download: {e}")

    if getattr(config, "ENABLE_YTDLP_DIRECT_AUDIO", False):
        try:
            ytdlp_path = await _download_audio_ytdlp(video_id)
            if ytdlp_path and os.path.exists(ytdlp_path):
                logger.info(f"✅ [AUDIO] yt-dlp direct hit: {video_id}")
                _cache_in_background(query, ytdlp_path)
                return ytdlp_path
        except Exception as e:
            logger.error(f"❌ [AUDIO] yt-dlp direct fast path failed, falling back to TgScrap: {e}")

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
    Video downloads now go entirely through the HF Space's /api/download
    endpoint (kind='video') instead of running yt-dlp locally on Render.
    """
    video_id = _extract_video_id(link)
    logger = LOGGER("YtDlp/Youtube.py")
    logger.info(f"🎥 [VIDEO] Starting download for: {video_id}")

    if not video_id or len(video_id) < 3:
        logger.error(f"❌ [VIDEO] Invalid video ID: {video_id}")
        return None

    result = await _hf_download(video_id, "video")
    if result:
        logger.info(f"✅ [VIDEO] download complete: {video_id}")
    else:
        logger.error(f"❌ [VIDEO] download failed: {video_id}")
    return result


async def check_file_size(link):
    """Total filesize across all formats, now sourced from the HF Space's
    /api/formats endpoint instead of shelling out to a local `yt-dlp` CLI
    binary (which no longer exists on Render at all)."""
    hf_resolver_url = _hf_base()
    if not hf_resolver_url:
        LOGGER("YtDlp/Youtube.py").warning("⚠️ [FILESIZE] HF_RESOLVER_URL not set")
        return None

    video_id = _extract_video_id(link)
    hf_timeout = getattr(config, "HF_RESOLVER_TIMEOUT", 8)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=hf_timeout)
        ) as session:
            async with session.get(
                f"{hf_resolver_url}/api/formats", params={"v": video_id}, headers=_hf_headers()
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("ok"):
                    return data.get("total_size")
                return None
    except Exception as e:
        LOGGER("YtDlp/Youtube.py").error(f"❌ [FILESIZE] hf-space failed: {e}")
        return None


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

        hf_resolver_url = _hf_base()
        if not hf_resolver_url:
            LOGGER("YtDlp/Youtube.py").warning("⚠️ [PLAYLIST] HF_RESOLVER_URL not set")
            return []

        hf_timeout = getattr(config, "HF_RESOLVER_TIMEOUT", 8)
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=hf_timeout)
            ) as session:
                async with session.get(
                    f"{hf_resolver_url}/api/playlist",
                    params={"url": link, "limit": limit},
                    headers=_hf_headers(),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    if data.get("ok"):
                        return data.get("ids", [])
                    return []
        except Exception as e:
            LOGGER("YtDlp/Youtube.py").error(f"❌ [PLAYLIST] hf-space failed: {e}")
            return []

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
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        hf_resolver_url = _hf_base()
        if not hf_resolver_url:
            LOGGER("YtDlp/Youtube.py").warning("⚠️ [FORMATS] HF_RESOLVER_URL not set")
            return [], link

        video_id = _extract_video_id(link)
        hf_timeout = getattr(config, "HF_RESOLVER_TIMEOUT", 8)
        formats_available = []
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=hf_timeout)
            ) as session:
                async with session.get(
                    f"{hf_resolver_url}/api/formats", params={"v": video_id}, headers=_hf_headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            for f in data.get("formats", []):
                                formats_available.append({
                                    "format": f.get("format"),
                                    "filesize": f.get("filesize"),
                                    "format_id": f.get("format_id"),
                                    "ext": f.get("ext"),
                                    "format_note": f.get("format_note"),
                                    "yturl": link,
                                })
        except Exception as e:
            LOGGER("YtDlp/Youtube.py").error(f"❌ [FORMATS] hf-space failed: {e}")
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
                downloaded_file = await download_song(link, title=title if isinstance(title, str) else None)
                if downloaded_file:
                    return downloaded_file, True
                else:
                    return None, False

        except Exception as e:
            logger = LOGGER("BrokenAPI/Youtube.py")
            logger.error(f"❌ Download failed: {e}")
            return None, False
