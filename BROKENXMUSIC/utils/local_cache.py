"""
Local disk LRU cache.

SongCache (Mongo + Telegram file_id) already avoids the VK-scrape bot for
songs that live in your source/cache channels — but every play still
means a Telegram download, chunk by chunk. If the SAME song gets replayed
on this server (very common — same 5-10 popular songs get requested over
and over in busy chats), this layer skips Telegram entirely on repeats:
the very first play seeds a local copy, every play after that is a plain
filesystem read.

Deliberately simple: a JSON index file + plain files on disk, guarded by
one asyncio.Lock. No extra DB collection, no extra service. Oldest-used
entries are evicted once the folder passes config.LOCAL_CACHE_MAX_MB.

Note (Render free tier): this folder lives on the app's ephemeral disk,
so it's wiped on every restart/redeploy — that's fine, it's a bonus layer,
not your source of truth (Mongo + your Telegram channels are).
"""

import asyncio
import json
import os
import shutil
import time

import config
from BROKENXMUSIC import LOGGER

logger = LOGGER("LocalCache")

CACHE_DIR = os.path.join(os.getcwd(), "tg-scrap", "downloads", "local_cache")
INDEX_PATH = os.path.join(CACHE_DIR, "_index.json")

# A "successful" download/stream that's actually empty or truncated (e.g.
# FILE_REFERENCE_EXPIRED mid-stream, or a probe that returned zero chunks)
# must never be promoted into the local cache — Tier 0 hits skip Telegram
# entirely, so a corrupt file cached here breaks that song's playback
# permanently until manually evicted, not just for this one request.
MIN_VALID_AUDIO_BYTES = 8192

_lock = asyncio.Lock()
_index = None  # lazy-loaded


def _load_index():
    global _index
    if _index is not None:
        return _index
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r") as f:
                _index = json.load(f)
        except Exception as e:
            logger.error(f"[LocalCache] Corrupt index, starting fresh: {e}")
            _index = {}
    else:
        _index = {}
    return _index


def _save_index_sync(idx):
    try:
        tmp = INDEX_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(idx, f)
        os.replace(tmp, INDEX_PATH)
    except Exception as e:
        logger.error(f"[LocalCache] Could not persist index: {e}")


def _safe_name(key: str) -> str:
    name = "".join(c if c.isalnum() else "_" for c in key)[:120].strip("_")
    return name or "track"


def _evict_if_needed(idx):
    cap_bytes = config.LOCAL_CACHE_MAX_MB * 1024 * 1024
    total = sum(e.get("size", 0) for e in idx.values())
    if total <= cap_bytes:
        return
    for key, entry in sorted(idx.items(), key=lambda kv: kv[1].get("last_used", 0)):
        if total <= cap_bytes:
            break
        path = entry.get("path")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        total -= entry.get("size", 0)
        idx.pop(key, None)
        logger.info(
            f"[LocalCache] Evicted {key!r} (LRU) to stay under "
            f"{config.LOCAL_CACHE_MAX_MB}MB cap."
        )


async def get(key: str):
    """Return a local filepath for `key` if it's cached and still on disk,
    else None. Bumps its last_used timestamp on hit."""
    if not config.LOCAL_CACHE_ENABLED or not key:
        return None
    async with _lock:
        idx = _load_index()
        entry = idx.get(key)
        if not entry:
            return None
        path = entry.get("path")
        if not path or not await asyncio.to_thread(os.path.exists, path):
            idx.pop(key, None)
            await asyncio.to_thread(_save_index_sync, dict(idx))
            return None
        entry["last_used"] = time.time()
        await asyncio.to_thread(_save_index_sync, dict(idx))
        logger.info(f"[LocalCache] Disk hit: {key!r} — skipping Telegram entirely.")
        return path


async def put(key: str, src_path: str):
    """Copy src_path into the persistent local cache dir under `key` and
    register it, evicting LRU entries if the cap is exceeded. Safe to call
    even if src_path IS already the cache path (no-op copy)."""
    if not config.LOCAL_CACHE_ENABLED or not key or not src_path:
        return
    try:
        if not await asyncio.to_thread(os.path.exists, src_path):
            return
        src_size = await asyncio.to_thread(os.path.getsize, src_path)
    except Exception:
        return

    # Never promote an empty/truncated source (corrupt download, aborted
    # stream, expired file reference that yielded zero real chunks) into
    # the trusted disk cache — a bad file here silently breaks that song
    # for every future play, forever, since Tier 0 hits skip Telegram
    # entirely and there's no other validation downstream of a cache hit.
    if src_size < MIN_VALID_AUDIO_BYTES:
        logger.error(
            f"[LocalCache] Refusing to cache {key!r}: source is only "
            f"{src_size} bytes (< {MIN_VALID_AUDIO_BYTES}) — looks corrupt/empty."
        )
        return

    async with _lock:
        idx = _load_index()
        os.makedirs(CACHE_DIR, exist_ok=True)
        _, src_ext = os.path.splitext(src_path)
        dest = os.path.join(CACHE_DIR, f"{_safe_name(key)}{src_ext or '.mp3'}")
        try:
            if os.path.abspath(src_path) != os.path.abspath(dest):
                await asyncio.to_thread(shutil.copyfile, src_path, dest)
            size = await asyncio.to_thread(os.path.getsize, dest)
        except Exception as e:
            logger.error(f"[LocalCache] Could not store {key!r}: {e}")
            return

        if size < MIN_VALID_AUDIO_BYTES:
            logger.error(
                f"[LocalCache] Refusing to cache {key!r}: copied file is only "
                f"{size} bytes — looks corrupt/empty."
            )
            try:
                await asyncio.to_thread(os.remove, dest)
            except Exception:
                pass
            return

        idx[key] = {"path": dest, "size": size, "last_used": time.time()}
        _evict_if_needed(idx)
        await asyncio.to_thread(_save_index_sync, dict(idx))
        logger.info(f"[LocalCache] Cached {key!r} on disk ({size // 1024} KB).")
