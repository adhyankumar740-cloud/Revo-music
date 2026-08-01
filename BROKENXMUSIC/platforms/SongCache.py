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

import asyncio
import itertools
import os
import re
import time

import config
from pymongo import UpdateOne
from pyrogram.errors import FloodWait, PeerIdInvalid
from BROKENXMUSIC import LOGGER, app
from BROKENXMUSIC.core.mongo import mongodb
from BROKENXMUSIC.core.userbot import assistants
from BROKENXMUSIC.utils import local_cache
from BROKENXMUSIC.utils.database import get_client
from BROKENXMUSIC.utils.formatters import seconds_to_min

logger = LOGGER("SongCache")

songcachedb = mongodb.songcache
songcache_progressdb = mongodb.songcache_progress

# Round-robin cursor over the LIVE-request assistant pool (i.e. assistants
# minus whichever one is reserved for /indexcache via
# SONG_CACHE_INDEX_ASSISTANT). Previously every live request always grabbed
# assistants[0] — with 2+ assistants configured that left every other
# account completely idle for actual playback while indexing hogs the
# first one. A simple cycling counter spreads live requests across all of
# them instead.
_live_pool_cycle = None


def _live_pool():
    # Exclude both the /indexcache-reserved assistant AND the dedicated
    # playback assistant (config.DEDICATED_PLAY_ASSISTANT) from the pool
    # used for SongCache file fetches — that keeps the playback account's
    # connection free for voice-chat joins/streaming only. Whatever's left
    # (assistant 2, 3, 4... in a typical setup) round-robins the fetch work,
    # so with 3+ assistants those fetches actually run in parallel across
    # more than one account instead of all queueing on a single one.
    reserved = {config.SONG_CACHE_INDEX_ASSISTANT, config.DEDICATED_PLAY_ASSISTANT}
    reserved.discard(None)
    pool = [a for a in assistants if a not in reserved]
    return pool or list(assistants)


def _next_live_assistant():
    global _live_pool_cycle
    pool = _live_pool()
    if not pool:
        return None
    # Rebuild the cycle if the assistant pool has changed (assistant
    # started after this module was first used, etc).
    if not hasattr(_next_live_assistant, "_pool_snapshot") or _next_live_assistant._pool_snapshot != pool:
        _next_live_assistant._pool_snapshot = pool
        _next_live_assistant._cycle = itertools.cycle(pool)
    return next(_next_live_assistant._cycle)


async def _default_client_no():
    """Next assistant number from the round-robin live pool, or None if no
    assistant is running."""
    return _next_live_assistant()


async def _warm_peer_cache(client):
    """Reactive fallback only — assistants already warm their dialog cache
    once at startup (see core/userbot.py). This just covers the edge case
    of a channel the assistant joined *after* that startup warm-up, so a
    get_messages/get_chat_history call can still hit PEER_ID_INVALID
    mid-session; re-walking get_dialogs() picks up anything new."""
    try:
        async for _ in client.get_dialogs():
            pass
    except Exception as e:
        logger.error(f"[SongCache] Dialog warm-up failed: {e}")


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



# Same idea as Youtube.py's _NOISE_PATTERNS — strip the boilerplate that
# tends to differ between "how the user typed the query" and "how the
# source video/audio was actually titled" (channel spam, quality tags,
# featured-artist junk, etc). Applied BEFORE the alnum collapse below so a
# match doesn't hinge on the requester's guess of that boilerplate.
_NOISE_PATTERNS = [
    r"\(.*?\)",
    r"\[.*?\]",
    r"\|.*",
    r"[-–—:]\s*full\s+(video\s+)?song.*",
    r"\bofficial\s+(music\s+)?video\b",
    r"\bofficial\s+audio\b",
    r"\bfull\s+video\s+song\b",
    r"\bfull\s+video\b",
    r"\bfull\s+song\b",
    r"\bwith\s+lyrics?\b",
    r"\blyric\s+video\b",
    r"\blyrics?\b",
    r"\bvideo\s+song\b",
    r"\baudio\s+song\b",
    r"\b(hd|4k|8k|1080p|720p)\b",
]


def normalize(title: str) -> str:
    """Collapse a title down to a bare comparable form: strip noisy
    boilerplate (quality tags, "| Movie Name", "(Official Video)", ...),
    lowercase, then keep only alphanumerics and spaces. 'Arijit Singh -
    Tum Hi Ho (Official Video) 4K' and 'tum hi ho' both normalize to
    'tum hi ho' / 'arijit singh tum hi ho'."""
    q = (title or "")
    for pat in _NOISE_PATTERNS:
        q = re.sub(pat, "", q, flags=re.IGNORECASE)
    q = q.lower()
    q = re.sub(r"[^a-z0-9]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


async def _refresh_file_id(client, entry):
    """file_id's embedded file_reference goes stale over time. Re-fetch the
    original message (we kept channel_id/message_id for exactly this) to
    pull a live one."""
    channel_id = entry.get("channel_id")
    message_id = entry.get("message_id")
    if not channel_id or not message_id:
        logger.error(
            f"[SongCache] Entry {entry.get('normalized')!r} has no "
            f"channel_id/message_id (legacy row?) — cannot refresh, will "
            f"fall back to its stored file_id."
        )
        return None
    try:
        msg = await client.get_messages(channel_id, message_id)
    except PeerIdInvalid:
        # Channel joined after the assistant's startup dialog warm-up —
        # re-warm once and retry before giving up.
        await _warm_peer_cache(client)
        try:
            msg = await client.get_messages(channel_id, message_id)
        except Exception as e:
            logger.error(f"[SongCache] Could not refetch origin message for refresh: {e}")
            return None
    except Exception as e:
        logger.error(f"[SongCache] Could not refetch origin message for refresh: {e}")
        return None
    if not msg:
        return None
    audio = msg.audio or msg.voice or (
        msg.document if (msg.document and "audio" in (msg.document.mime_type or "")) else None
    )
    return audio.file_id if audio else None


class SongCacheAPI:
    def __init__(self):
        self.source_channels = config.SONG_CACHE_SOURCE_CHANNELS
        self.cache_channel = config.SONG_CACHE_CHANNEL
        self.enabled = config.ENABLE_SONG_CACHE
        self._indexes_ready = False

    async def ensure_indexes(self):
        """Create the Mongo indexes the cache actually depends on for
        speed. Without a unique index on `normalized`, every lookup
        (the hot path, hit on almost every /play) does a full collection
        scan — fine at a few hundred rows, painfully slow once a channel
        with thousands of tracks has been indexed. Safe to call every
        startup: create_index is a no-op if the index already exists.
        """
        if self._indexes_ready:
            return
        try:
            await songcachedb.create_index("normalized", unique=True, background=True)
            await songcache_progressdb.create_index("channel", unique=True, background=True)
            # Text index powers the fuzzy fallback in search() below. At
            # 10k+ rows a regex $all scan (the old fallback) becomes a full
            # collection scan on every miss — this makes it an indexed
            # lookup instead, and default_language="none" turns off
            # English stopword/stemming so short real words in titles
            # aren't silently dropped.
            await songcachedb.create_index(
                [("normalized", "text")], default_language="none", background=True
            )
            self._indexes_ready = True
            logger.info("[SongCache] Mongo indexes ready (normalized unique + text, channel).")
        except Exception as e:
            logger.error(f"[SongCache] Could not create indexes: {e}")

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

        # Fuzzy fallback: an indexed $text search instead of a regex $all
        # scan. At 10k+ rows the old regex approach scanned every document
        # on every miss (slow, and prone to actually missing a real match
        # if normalization wasn't byte-identical). $text uses the text
        # index created in ensure_indexes(), ranks by relevance, and still
        # matches "tum hi ho" against a stored "arijit singh tum hi ho"
        # regardless of word order.
        words = [w for w in norm.split() if len(w) > 2]
        if not words:
            return None
        try:
            cursor = songcachedb.find(
                {"$text": {"$search": " ".join(words)}},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).limit(1)
            entry = await cursor.to_list(length=1)
            entry = entry[0] if entry else None
        except Exception as e:
            # Text index missing/not built yet (e.g. right after an
            # upgrade, before ensure_indexes() has run) — fall back to the
            # old regex scan rather than returning nothing.
            logger.error(f"[SongCache] Text search failed, falling back to regex: {e}")
            entry = await songcachedb.find_one(
                {"normalized": {"$all": [re.compile(re.escape(w)) for w in words]}}
            )
        if entry:
            logger.info(f"[SongCache] Fuzzy cache hit: {norm!r} -> {entry.get('normalized')!r}")
        return entry

    async def fetch_file(self, entry, save_dir=None):
        """Download the cached track locally via its file_id (fast — pure
        Telegram CDN transfer, no scraping). Returns (track_details, filepath)
        matching TgScrapAPI.download()'s return shape, or (None, None)."""
        norm = entry.get("normalized", "track")

        # Tier 0: local disk. If this exact song was played on this server
        # before, it's already sitting on disk — no Telegram call at all.
        local_hit = await local_cache.get(norm)
        if local_hit:
            track_details = {
                "title": entry.get("title") or norm.title(),
                "duration_min": entry.get("duration_min") or "Unknown",
                "filepath": local_hit,
            }
            return track_details, local_hit

        save_dir = save_dir or os.path.join(os.getcwd(), "tg-scrap", "downloads")
        os.makedirs(save_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", norm).strip("_") or "track"
        filepath = os.path.join(save_dir, f"{safe_name}_{int(time.time())}.mp3")

        client, _ = await _resolve_client(entry.get("client_source"))

        file_id = entry.get("file_id")
        if not file_id:
            logger.error(f"[SongCache] No usable file_id for {entry.get('normalized')!r}")
            return None, None

        # Try the stored file_id straight away — it's valid the vast
        # majority of the time, so this keeps the common case down to a
        # single network call (download) instead of always paying for an
        # extra get_messages round-trip "just in case". Only refresh and
        # retry once if the first attempt actually fails.
        try:
            result = await client.download_media(file_id, file_name=filepath)
        except Exception as e:
            logger.info(
                f"[SongCache] Stored file_id failed for "
                f"{entry.get('normalized')!r} ({e}) — refreshing and "
                f"retrying once."
            )
            fresh_file_id = await _refresh_file_id(client, entry)
            if not fresh_file_id:
                logger.error(
                    f"[SongCache] fetch_file failed for {entry.get('normalized')!r}: {e}"
                )
                try:
                    await songcachedb.delete_one({"_id": entry["_id"]})
                    logger.info(
                        f"[SongCache] Removed unrecoverable entry "
                        f"{entry.get('normalized')!r} from cache index."
                    )
                except Exception:
                    pass
                return None, None

            file_id = fresh_file_id
            try:
                result = await client.download_media(file_id, file_name=filepath)
            except Exception as e2:
                logger.error(
                    f"[SongCache] fetch_file failed even after refresh for "
                    f"{entry.get('normalized')!r}: {e2}"
                )
                try:
                    await songcachedb.delete_one({"_id": entry["_id"]})
                    logger.info(
                        f"[SongCache] Removed unrecoverable entry "
                        f"{entry.get('normalized')!r} from cache index."
                    )
                except Exception:
                    pass
                return None, None

        # Keep the DB entry current for anything else that reads file_id directly.
        if file_id != entry.get("file_id"):
            try:
                await songcachedb.update_one({"_id": entry["_id"]}, {"$set": {"file_id": file_id}})
            except Exception:
                pass

        if not result or not os.path.exists(filepath):
            return None, None

        # The file_id can refresh cleanly while the underlying message's
        # audio is itself gone/corrupt (e.g. the cache-channel message was
        # deleted or never had real audio). A near-empty file downloads
        # "successfully" but pytgcalls/ffmpeg will reject it with
        # NoAudioSourceFound. Catch that here instead of handing a dead
        # file to the voice chat.
        MIN_VALID_AUDIO_BYTES = 8192
        try:
            size = os.path.getsize(filepath)
        except OSError:
            size = 0
        if size < MIN_VALID_AUDIO_BYTES:
            logger.error(
                f"[SongCache] Downloaded file for {entry.get('normalized')!r} "
                f"is only {size} bytes — treating as corrupt, purging cache entry."
            )
            try:
                os.remove(filepath)
            except Exception:
                pass
            try:
                await songcachedb.delete_one({"_id": entry["_id"]})
                logger.info(
                    f"[SongCache] Removed corrupt entry "
                    f"{entry.get('normalized')!r} from cache index."
                )
            except Exception:
                pass
            return None, None

        # Seed the local disk cache so the NEXT request for this exact song
        # skips Telegram entirely (see local_cache.get() above).
        try:
            await local_cache.put(norm, filepath)
        except Exception as e:
            logger.error(f"[SongCache] local_cache.put failed for {norm!r}: {e}")

        track_details = {
            "title": entry.get("title") or entry.get("normalized", "").title(),
            "duration_min": entry.get("duration_min") or "Unknown",
            "filepath": filepath,
        }
        return track_details, filepath

    async def stream_or_fetch(self, entry, save_dir=None, fifo_open_timeout=20):
        """Like fetch_file, but instead of waiting for the whole track to
        land on disk before playback can start, it pipes Telegram's chunks
        into a named pipe (FIFO) as they arrive — ffmpeg (via pytgcalls)
        reads from that FIFO exactly like it would a regular file, so audio
        starts as soon as the first chunk is in, not after the full
        download finishes.

        Returns (track_details, fifo_path) on success. On ANY failure along
        the way (file_id dead even after refresh, mkfifo unsupported,
        nobody opens the FIFO in time, ...) it transparently falls back to
        the plain fetch_file() full-download path, so playback never
        breaks — it just loses the head-start."""
        norm = entry.get("normalized", "track")

        # Tier 0: already on local disk from a previous play — this beats
        # even the FIFO head-start, since there's no pipe/Telegram chunking
        # at all, just handing back a plain file.
        local_hit = await local_cache.get(norm)
        if local_hit:
            track_details = {
                "title": entry.get("title") or norm.title(),
                "duration_min": entry.get("duration_min") or "Unknown",
                "filepath": local_hit,
            }
            return track_details, local_hit

        client, _ = await _resolve_client(entry.get("client_source"))
        file_id = entry.get("file_id")
        if not file_id:
            return await self.fetch_file(entry, save_dir=save_dir)

        async def _open_gen(fid):
            """Pull the first chunk to prove this file_id actually works
            before we commit to a FIFO — a mid-stream failure is much
            harder to recover from than a failure right here."""
            try:
                gen = client.stream_media(fid)
                chunk = await gen.__anext__()
                return gen, chunk
            except StopAsyncIteration:
                # A generator that ends before yielding a single byte is
                # not a usable stream (real audio always has a first
                # chunk) — it's indistinguishable in effect from a hard
                # failure and must not be treated as success, or an empty
                # FIFO gets handed to pytgcalls and, worse, an empty file
                # ends up promoted into the local cache.
                return None, RuntimeError("stream yielded zero chunks")
            except Exception as e:
                return None, e

        gen, first_chunk = await _open_gen(file_id)
        if gen is None:
            # First attempt failed (likely FILE_REFERENCE_EXPIRED) — refresh
            # once and retry, same as fetch_file does.
            logger.info(
                f"[SongCache] Stream probe failed for {norm!r} "
                f"({first_chunk}) — refreshing and retrying once."
            )
            fresh_file_id = await _refresh_file_id(client, entry)
            if fresh_file_id:
                gen, first_chunk = await _open_gen(fresh_file_id)
                if gen is not None:
                    file_id = fresh_file_id
                    # Keep the closure's entry dict current too — _pump()'s
                    # self-heal path below reads entry["file_id"] directly,
                    # and without this it would retry the same already-dead
                    # id (and pay for a second refresh) instead of reusing
                    # the good one we just fetched.
                    entry["file_id"] = fresh_file_id

        if gen is None:
            logger.error(
                f"[SongCache] Streaming unavailable for {norm!r} even after "
                f"refresh — falling back to full download."
            )
            return await self.fetch_file(entry, save_dir=save_dir)

        save_dir = save_dir or os.path.join(os.getcwd(), "tg-scrap", "downloads")
        os.makedirs(save_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", norm).strip("_") or "track"
        fifo_path = os.path.join(save_dir, f"{safe_name}_{int(time.time())}.fifo")

        try:
            os.mkfifo(fifo_path)
        except Exception as e:
            logger.error(
                f"[SongCache] mkfifo failed for {norm!r} ({e}) — falling "
                f"back to full download."
            )
            return await self.fetch_file(entry, save_dir=save_dir)

        async def _pump():
            fd = None
            tee_path = fifo_path + ".tee"
            tee_fh = None
            try:
                tee_fh = open(tee_path, "wb")
            except Exception:
                tee_fh = None  # tee is a nice-to-have; never block playback on it

            try:
                # Blocks (in a worker thread, not the event loop) until
                # pytgcalls/ffmpeg opens the other end for reading. Timeout
                # guards against leaking a stuck thread if playback never
                # actually starts (e.g. the voice chat join failed).
                fd = await asyncio.wait_for(
                    asyncio.to_thread(os.open, fifo_path, os.O_WRONLY),
                    timeout=fifo_open_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"[SongCache] Nobody read the FIFO for {norm!r} within "
                    f"{fifo_open_timeout}s — abandoning stream."
                )
            except Exception as e:
                logger.error(f"[SongCache] FIFO open failed for {norm!r}: {e}")

            completed = False
            bytes_written = 0
            if fd is not None:
                try:
                    if first_chunk:
                        await asyncio.to_thread(os.write, fd, first_chunk)
                        if tee_fh:
                            await asyncio.to_thread(tee_fh.write, first_chunk)
                        bytes_written += len(first_chunk)
                    async for chunk in gen:
                        await asyncio.to_thread(os.write, fd, chunk)
                        if tee_fh:
                            await asyncio.to_thread(tee_fh.write, chunk)
                        bytes_written += len(chunk)
                    completed = True
                except Exception as e:
                    logger.error(
                        f"[SongCache] Streaming into FIFO failed for {norm!r}: {e}"
                    )
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass

            # A generator that "completes" after writing zero (or barely
            # any) bytes isn't a real success — it's what a mid-stream
            # FILE_REFERENCE_EXPIRED (or a probe that immediately hit
            # StopAsyncIteration) looks like from here. Never let that get
            # promoted to the local cache: local_cache.put() itself now
            # also guards on size, but skip the useless copy attempt and
            # log clearly why playback for this request is failing.
            if completed and bytes_written < local_cache.MIN_VALID_AUDIO_BYTES:
                logger.error(
                    f"[SongCache] Stream for {norm!r} 'completed' but only "
                    f"wrote {bytes_written} bytes — treating as failed "
                    f"(likely a stale file_id) and not caching it."
                )
                completed = False

            # Self-heal for NEXT time: a mid-stream break (Broken pipe, etc)
            # with very little written usually means the file_id died partway
            # through, not a clean end-of-track. This playback attempt is
            # already lost, but kick off a full download in the background so
            # it lands in local_cache — the next request for this exact song
            # gets an instant Tier-0 hit instead of hitting the same failure
            # again. Best-effort only: never let this raise into the pump.
            if not completed and bytes_written < local_cache.MIN_VALID_AUDIO_BYTES:
                logger.info(
                    f"[SongCache] Stream for {norm!r} broke early "
                    f"({bytes_written} bytes) — fetching full file in the "
                    f"background so the next request for it doesn't repeat "
                    f"this failure."
                )
                async def _heal():
                    try:
                        await self.fetch_file(entry, save_dir=save_dir)
                    except Exception as e:
                        logger.error(f"[SongCache] Background self-heal fetch failed for {norm!r}: {e}")
                asyncio.create_task(_heal())

            if tee_fh:
                try:
                    tee_fh.close()
                except Exception:
                    pass
                if completed:
                    try:
                        await local_cache.put(norm, tee_path)
                    except Exception as e:
                        logger.error(f"[SongCache] local_cache.put (tee) failed for {norm!r}: {e}")
                try:
                    os.remove(tee_path)
                except Exception:
                    pass

            try:
                os.remove(fifo_path)
            except Exception:
                pass

        asyncio.create_task(_pump())

        if file_id != entry.get("file_id"):
            try:
                await songcachedb.update_one({"_id": entry["_id"]}, {"$set": {"file_id": file_id}})
            except Exception:
                pass

        track_details = {
            "title": entry.get("title") or norm.title(),
            "duration_min": entry.get("duration_min") or "Unknown",
            "filepath": fifo_path,
        }
        return track_details, fifo_path

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
            # The picked assistant may not have resolved this peer yet
            # (freshly started, or joined the cache channel after its
            # startup dialog warm-up) — Telegram then rejects the raw
            # chat_id with CHAT_ID_INVALID/PEER_ID_INVALID. Same fix as
            # _refresh_file_id: re-walk get_dialogs() once to populate the
            # peer cache, then retry a single time before giving up.
            logger.error(
                f"[SongCache] Upload to cache channel failed for {title!r} "
                f"(retrying after peer warm-up): {e}"
            )
            await _warm_peer_cache(client)
            try:
                msg = await client.send_audio(
                    self.cache_channel,
                    local_filepath,
                    title=title,
                    caption=title,
                )
            except Exception as e2:
                logger.error(
                    f"[SongCache] Upload to cache channel failed for {title!r} "
                    f"even after peer warm-up: {e2}"
                )
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

        # Prefer the assistant reserved via SONG_CACHE_INDEX_ASSISTANT (if
        # configured and actually running) so a long indexing run never
        # competes with live /play requests on the same account. Falls
        # back to whatever the round-robin live pool would pick otherwise.
        reserved = config.SONG_CACHE_INDEX_ASSISTANT
        if reserved and reserved in assistants:
            client, client_no = await _resolve_client(reserved)
            logger.info(f"[SongCache] Using dedicated index assistant #{reserved}.")
        else:
            client, client_no = await _resolve_client()
        if client is app:
            logger.error(
                "[SongCache] No assistant is running — indexing with the bot account. "
                "If the bot isn't a member of your source channels this will index 0 tracks; "
                "add an assistant (STRING1..5) to those channels instead, or add the bot itself."
            )

        # 0 = explicit "no limit" (old behaviour). None = use the configured
        # default cap so one run can't silently churn through an entire huge
        # channel's history (and rack up long, hard-to-notice FloodWaits).
        if limit_per_channel is None:
            limit_per_channel = config.SONG_CACHE_INDEX_LIMIT

        total_indexed = 0
        for channel in self.source_channels:
            channel_count = 0
            seen = 0
            started_at = time.time()
            last_heartbeat = started_at
            oldest_id_seen = None

            # Resume from where the previous run left off (older messages),
            # instead of always re-scanning the newest N messages again.
            progress = await songcache_progressdb.find_one({"channel": str(channel)})
            offset_id = (progress or {}).get("last_message_id", 0)
            done_before = bool((progress or {}).get("done"))

            if done_before:
                logger.info(
                    f"[SongCache] {channel}: already fully scanned in a "
                    f"previous run, skipping. Delete its songcache_progress "
                    f"entry to rescan from the top."
                )
                continue

            logger.info(
                f"[SongCache] Starting scan of {channel} "
                f"(limit={limit_per_channel or 'none'}, resuming before "
                f"message_id={offset_id or 'latest'}) ..."
            )
            pending_ops = []
            BATCH_SIZE = 100

            async def _flush(ops):
                if not ops:
                    return 0
                try:
                    result = await songcachedb.bulk_write(ops, ordered=False)
                    return result.upserted_count
                except Exception as e:
                    logger.error(f"[SongCache] Bulk DB write failed ({len(ops)} ops): {e}")
                    return 0

            try:
                history_iter = client.get_chat_history(
                    channel, limit=limit_per_channel or 0, offset_id=offset_id
                ).__aiter__()
                consecutive_errors = 0
                while True:
                    try:
                        msg = await history_iter.__anext__()
                        consecutive_errors = 0
                    except StopAsyncIteration:
                        break
                    except FloodWait as e:
                        # This is the big one at 10k+ message scales: Telegram
                        # WILL rate-limit a long history scan. The old code
                        # let this bubble up to the outer except and simply
                        # gave up on the rest of THIS channel (progress saved,
                        # but everything from here to the end had to wait for
                        # a whole extra /indexcache run). Sleep it out and
                        # keep going from the exact same spot instead.
                        wait_for = e.value + 2
                        logger.info(
                            f"[SongCache] {channel}: FloodWait, sleeping "
                            f"{wait_for}s then resuming this channel's scan "
                            f"(not abandoning it)..."
                        )
                        await asyncio.sleep(wait_for)
                        continue
                    except Exception as e:
                        # Transient network/API hiccup — brief backoff and
                        # retry, but don't loop forever on a truly broken
                        # channel (e.g. assistant got kicked mid-scan).
                        consecutive_errors += 1
                        if consecutive_errors >= 5:
                            logger.error(
                                f"[SongCache] {channel}: {consecutive_errors} "
                                f"consecutive errors, giving up on this run: {e}"
                            )
                            raise
                        logger.error(
                            f"[SongCache] {channel}: transient error, "
                            f"retrying in 3s: {e}"
                        )
                        await asyncio.sleep(3)
                        continue

                    seen += 1
                    oldest_id_seen = msg.id
                    now = time.time()
                    if seen % 200 == 0 or (now - last_heartbeat) >= 30:
                        elapsed = int(now - started_at)
                        logger.info(
                            f"[SongCache] ...{channel}: scanned {seen} messages so far "
                            f"({channel_count} audio indexed, {elapsed}s elapsed)"
                        )
                        last_heartbeat = now

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
                        logger.info(
                            f"[SongCache] Skipped msg_id={msg.id} in {channel}: "
                            f"audio has no performer/title tag, no filename, and no "
                            f"caption — nothing to search it by. Add a caption to "
                            f"index it."
                        )
                        continue

                    norm = normalize(title)
                    if not norm:
                        continue

                    duration_min = "Unknown"
                    try:
                        duration_min = seconds_to_min(getattr(audio, "duration", 0) or 0)
                    except Exception:
                        pass

                    pending_ops.append(
                        UpdateOne(
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
                    )

                    if len(pending_ops) >= BATCH_SIZE:
                        channel_count += await _flush(pending_ops)
                        pending_ops = []

                channel_count += await _flush(pending_ops)
                pending_ops = []
            except Exception as e:
                channel_count += await _flush(pending_ops)
                logger.error(f"[SongCache] Failed indexing channel {channel}: {e}")
                continue

            # Figure out whether we reached the actual end of the channel's
            # history (fewer messages returned than we asked for -> nothing
            # older is left) vs just hit our per-run limit_per_channel cap.
            reached_end = bool(limit_per_channel) and seen < limit_per_channel
            try:
                if reached_end or not limit_per_channel:
                    await songcache_progressdb.update_one(
                        {"channel": str(channel)},
                        {"$set": {"channel": str(channel), "done": True, "updated_at": time.time()}},
                        upsert=True,
                    )
                elif oldest_id_seen:
                    await songcache_progressdb.update_one(
                        {"channel": str(channel)},
                        {
                            "$set": {
                                "channel": str(channel),
                                "last_message_id": oldest_id_seen,
                                "done": False,
                                "updated_at": time.time(),
                            }
                        },
                        upsert=True,
                    )
            except Exception as e:
                logger.error(f"[SongCache] Could not save scan progress for {channel}: {e}")

            logger.info(
                f"[SongCache] Indexed {channel_count} tracks from {channel} "
                f"({seen} messages scanned, {int(time.time() - started_at)}s"
                f"{', reached end of channel history' if reached_end or not limit_per_channel else ''})"
            )
            total_indexed += channel_count

        logger.info(f"[SongCache] Indexing complete. {total_indexed} tracks total.")
        return total_indexed
