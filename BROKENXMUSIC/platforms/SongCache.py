"""
Song Cache: turns your own Telegram channels into a fast local library.

Lookup order (see play.py):
  1. Check this cache (your 3-4 source channels + the auto-growing cache channel)
     — a hit means grabbing the file straight from Telegram via file_id, no
     vkmusic_bot round-trip at all.
  2. Miss -> fall back to TgScrap (vkmusic_bot). On success, the downloaded
     file gets uploaded to SONG_CACHE_CHANNEL and indexed here, so the next
     request for the same song is a cache hit.
"""

import os
import re
import time

import config
from BROKENXMUSIC import LOGGER, app
from BROKENXMUSIC.core.mongo import mongodb
from BROKENXMUSIC.core.userbot import assistants
from BROKENXMUSIC.utils.database import get_client
from BROKENXMUSIC.utils.formatters import seconds_to_min

logger = LOGGER("SongCache")

songcachedb = mongodb.songcache


async def _default_client_no():
    """First running assistant number, or None if only the bot is available."""
    return assistants[0] if assistants else None


async def _resolve_client(client_no=None):
    """Client that should own the source/cache channels. Assistants (real
    user accounts) commonly sit in channels the bot itself was never added
    to, so prefer them. `client_no` pins a lookup to whichever account
    actually produced a given file_id; leave it None to just grab whatever
    assistant is currently running."""
    no = client_no if client_no is not None else await _default_client_no()
    if no is not None:
        try:
            client = await get_client(no)
            if client:
                return client, no
        except Exception:
            pass
    return app, None


def normalize(title: str) -> str:
    """Collapse a title down to a bare comparable form: lowercase, only
    alphanumerics and spaces. 'Arijit Singh - Tum Hi Ho!' and 'tum hi ho'
    both normalize to 'tum hi ho', 'arijit singh tum hi ho' etc."""
    q = (title or "").lower()
    q = re.sub(r"[^a-z0-9]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


class SongCacheAPI:
    def __init__(self):
        self.source_channels = config.SONG_CACHE_SOURCE_CHANNELS
        self.cache_channel = config.SONG_CACHE_CHANNEL
        self.enabled = config.ENABLE_SONG_CACHE

    async def search(self, query: str):
        """Look up a normalized query in the DB index. Returns the stored
        doc (with file_id) or None."""
        if not self.enabled:
            return None
        norm = normalize(query)
        if not norm:
            return None

        entry = await songcachedb.find_one({"normalized": norm})
        if entry:
            logger.info(f"[SongCache] Exact cache hit: {norm!r}")
            return entry

        # Loose fallback: word-subset match. Cheap and good enough for
        # "tum hi ho" matching an index entry "arijit singh tum hi ho".
        words = [w for w in norm.split() if len(w) > 2]
        if not words:
            return None
        pattern = ".*".join(re.escape(w) for w in words)
        entry = await songcachedb.find_one({"normalized": {"$regex": pattern}})
        if entry:
            logger.info(f"[SongCache] Fuzzy cache hit: {norm!r} -> {entry.get('normalized')!r}")
        return entry

    async def fetch_file(self, entry, save_dir=None):
        """Download the cached track locally via its file_id (fast — pure
        Telegram CDN transfer, no scraping). Returns (track_details, filepath)
        matching TgScrapAPI.download()'s return shape, or (None, None)."""
        save_dir = save_dir or os.path.join(os.getcwd(), "tg-scrap", "downloads")
        os.makedirs(save_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", entry.get("normalized", "track")).strip("_") or "track"
        filepath = os.path.join(save_dir, f"{safe_name}_{int(time.time())}.mp3")

        client, _ = await _resolve_client(entry.get("client_source"))
        try:
            result = await client.download_media(entry["file_id"], file_name=filepath)
        except Exception as e:
            logger.error(f"[SongCache] fetch_file failed for {entry.get('normalized')!r}: {e}")
            return None, None

        if not result or not os.path.exists(filepath):
            return None, None

        track_details = {
            "title": entry.get("title") or entry.get("normalized", "").title(),
            "duration_min": entry.get("duration_min") or "Unknown",
            "filepath": filepath,
        }
        return track_details, filepath

    async def save_to_cache(self, query: str, local_filepath: str, title: str, duration_min):
        """Upload a freshly TgScrap-downloaded file to the cache channel and
        index it, so future requests for this song are served instantly."""
        if not self.enabled or not self.cache_channel:
            return False
        norm = normalize(query)
        if not norm:
            return False

        client, client_no = await _resolve_client()
        try:
            msg = await client.send_audio(
                self.cache_channel,
                local_filepath,
                title=title,
                caption=title,
            )
        except Exception as e:
            logger.error(f"[SongCache] Upload to cache channel failed for {title!r}: {e}")
            return False

        file_id = getattr(msg.audio, "file_id", None) or getattr(msg.voice, "file_id", None)
        if not file_id:
            return False

        try:
            await songcachedb.update_one(
                {"normalized": norm},
                {
                    "$set": {
                        "normalized": norm,
                        "title": title,
                        "duration_min": duration_min,
                        "file_id": file_id,
                        "channel_id": self.cache_channel,
                        "message_id": msg.id,
                        "client_source": client_no,
                        "added_at": time.time(),
                    }
                },
                upsert=True,
            )
        except Exception as e:
            logger.error(f"[SongCache] DB write failed for {title!r}: {e}")
            return False

        logger.info(f"[SongCache] Cached new track: {title!r} -> {norm!r}")
        return True

    async def index_channels(self, limit_per_channel=None):
        """One-time (or periodic) scan of your existing source channels,
        building the search index from each audio's performer/title tags or
        filename/caption. Safe to re-run — existing entries aren't overwritten."""
        if not self.source_channels:
            logger.error("[SongCache] No SONG_CACHE_SOURCE_CHANNELS configured.")
            return 0

        client, client_no = await _resolve_client()
        if client is app:
            logger.error(
                "[SongCache] No assistant is running — indexing with the bot account. "
                "If the bot isn't a member of your source channels this will index 0 tracks; "
                "add an assistant (STRING1..5) to those channels instead, or add the bot itself."
            )

        total_indexed = 0
        for channel in self.source_channels:
            channel_count = 0
            try:
                async for msg in client.get_chat_history(channel, limit=limit_per_channel):
                    audio = msg.audio or msg.voice or (
                        msg.document if (msg.document and "audio" in (msg.document.mime_type or "")) else None
                    )
                    if not audio:
                        continue

                    title = None
                    if msg.audio:
                        performer = (msg.audio.performer or "").strip()
                        track_title = (msg.audio.title or "").strip()
                        if performer or track_title:
                            title = f"{performer} - {track_title}".strip(" -")
                    if not title:
                        title = getattr(audio, "file_name", None) or (msg.caption or "").strip()
                    if not title:
                        continue

                    norm = normalize(title)
                    if not norm:
                        continue

                    duration_min = "Unknown"
                    try:
                        duration_min = seconds_to_min(getattr(audio, "duration", 0) or 0)
                    except Exception:
                        pass

                    try:
                        await songcachedb.update_one(
                            {"normalized": norm},
                            {
                                "$setOnInsert": {
                                    "normalized": norm,
                                    "title": title,
                                    "duration_min": duration_min,
                                    "file_id": audio.file_id,
                                    "channel_id": channel,
                                    "message_id": msg.id,
                                    "client_source": client_no,
                                    "added_at": time.time(),
                                }
                            },
                            upsert=True,
                        )
                        channel_count += 1
                    except Exception as e:
                        logger.error(f"[SongCache] DB write failed while indexing {title!r}: {e}")
            except Exception as e:
                logger.error(f"[SongCache] Failed indexing channel {channel}: {e}")
                continue

            logger.info(f"[SongCache] Indexed {channel_count} tracks from {channel}")
            total_indexed += channel_count

        logger.info(f"[SongCache] Indexing complete. {total_indexed} tracks total.")
        return total_indexed
