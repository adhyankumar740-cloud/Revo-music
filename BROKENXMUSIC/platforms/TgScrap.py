import asyncio
import json
import os
import re
import time

from pyrogram import enums

import config
from BROKENXMUSIC.utils.formatters import check_duration, seconds_to_min

# Downloaded songs are saved here (same folder tg-scrap's own scripts use,
# kept for consistency even though tg-scrap's Node process isn't involved
# in this flow anymore).
TG_SCRAP_DOWNLOADS = os.path.join(os.getcwd(), "tg-scrap", "downloads")

# Warmed-up index of SONG_CACHE_SOURCE_CHANNELS gets cached here so a restart doesn't
# have to re-scan Telegram before lookups are instant again.
TG_SCRAP_INDEX_FILE = os.path.join(os.getcwd(), "tg-scrap", "own_channel_index.json")


class TgScrapAPI:
    """
    Resolves a song request in two stages, using the music bot's OWN
    assistant account (the same Pyrogram userbot that joins voice chats):

      1. Search the user's own archived channels (config.SONG_CACHE_SOURCE_CHANNELS)
         via Telegram's server-side search. This is the multi-year personal
         library — always tried first since it's instant and needs no
         third-party bot.
      2. Only if nothing is found there, fall back to scraping a
         VK-Music-style Telegram bot (config.VK_MUSIC_BOT).

    No separate Node.js process, no second Telegram session, no HTTP
    round-trip — fastest possible path either way.
    """

    def __init__(self):
        self.bot_username = config.VK_MUSIC_BOT
        self.menu_timeout = config.TG_SCRAP_MENU_TIMEOUT
        self.audio_timeout = config.TG_SCRAP_TIMEOUT
        self.own_channels = getattr(config, "SONG_CACHE_SOURCE_CHANNELS", [])
        self.own_search_limit = getattr(config, "OWN_CHANNEL_SEARCH_LIMIT", 5)
        self.index_ttl_hours = getattr(config, "MY_MUSIC_INDEX_TTL_HOURS", 24)

        # In-memory warm-up index: normalized_key -> [{chat_id, message_id, title}, ...]
        self._index = {}
        self._index_built_at = 0
        self._warmup_lock = asyncio.Lock()

    def _get_assistant(self):
        # Local import to avoid circular imports at module load time.
        from BROKENXMUSIC import userbot

        for client in (userbot.one, userbot.two, userbot.three, userbot.four, userbot.five):
            if client and getattr(client, "is_connected", False):
                return client
        return None

    async def _wait_for(self, client, chat_id, timeout, condition, poll_interval=1.5):
        seen_ids = set()
        try:
            async for msg in client.get_chat_history(chat_id, limit=5):
                seen_ids.add(msg.id)
        except Exception:
            pass

        start = time.time()
        while time.time() - start < timeout:
            await asyncio.sleep(poll_interval)
            try:
                async for msg in client.get_chat_history(chat_id, limit=5):
                    if msg.id in seen_ids:
                        continue
                    seen_ids.add(msg.id)
                    if condition(msg):
                        return msg
            except Exception:
                continue
        return None

    @staticmethod
    def _normalize_chat(chat):
        """SONG_CACHE_SOURCE_CHANNELS entries may be usernames or numeric ids (as strings)."""
        try:
            return int(chat)
        except (TypeError, ValueError):
            return chat

    @staticmethod
    def _normalize_text(s):
        s = (s or "").lower()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    # ---------------------------------------------------------------
    # Warm-up: build (or load) the index ONCE so play-time lookups are
    # a plain dict/list scan — no live Telegram search per song request.
    # ---------------------------------------------------------------

    def _load_index_cache(self):
        try:
            with open(TG_SCRAP_INDEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        built_at = data.get("built_at", 0)
        if self.index_ttl_hours and (time.time() - built_at) > self.index_ttl_hours * 3600:
            return False  # stale, needs a rebuild

        index = data.get("index")
        if not index:
            return False

        self._index = index
        self._index_built_at = built_at
        return True

    def _save_index_cache(self):
        try:
            os.makedirs(os.path.dirname(TG_SCRAP_INDEX_FILE), exist_ok=True)
            with open(TG_SCRAP_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump({"built_at": self._index_built_at, "index": self._index}, f, ensure_ascii=False)
        except Exception:
            pass

    async def warm_up(self, force_refresh: bool = False):
        """
        Scans every channel in config.SONG_CACHE_SOURCE_CHANNELS ONCE and builds an
        in-memory (+ on-disk cached) index of every audio file in them, so
        that download_from_own_db() never has to call Telegram search at
        play time — it just looks the song up in this index.

        Call this once at bot startup (and optionally on a schedule). Safe
        to call multiple times; a fresh-enough cache/index is reused.
        """
        if not self.own_channels:
            return

        async with self._warmup_lock:
            if not force_refresh and self._index:
                return  # already warm in this process
            if not force_refresh and self._load_index_cache():
                return  # fresh cache loaded from disk

            assistant = self._get_assistant()
            if not assistant:
                return

            index = {}
            for chat in self.own_channels:
                chat_id = self._normalize_chat(chat)
                try:
                    async for msg in assistant.search_messages(chat_id, filter=enums.MessagesFilter.AUDIO):
                        audio = msg.audio or msg.document
                        if not audio:
                            continue
                        title = getattr(audio, "title", None) or getattr(audio, "file_name", None) or ""
                        performer = getattr(audio, "performer", None) or ""
                        label = f"{performer} {title}".strip() or title
                        key = self._normalize_text(label)
                        if not key:
                            continue
                        index.setdefault(key, []).append({
                            "chat_id": chat_id,
                            "message_id": msg.id,
                            "title": label,
                        })
                except Exception:
                    continue  # skip channels we can't read, keep warming the rest

            self._index = index
            self._index_built_at = time.time()
            self._save_index_cache()

    def _lookup_index(self, query: str, limit: int = None):
        """Instant in-memory token-overlap match against the warmed-up index."""
        limit = limit or self.own_search_limit
        key = self._normalize_text(query)
        if not key or not self._index:
            return []

        q_tokens = set(key.split())
        scored = []
        for idx_key, entries in self._index.items():
            idx_tokens = set(idx_key.split())
            if not idx_tokens:
                continue
            overlap = len(q_tokens & idx_tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(q_tokens), 1)
            scored.append((score, entries))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, entries in scored[:limit]:
            results.extend(entries)
        return results

    async def _save_audio_message(self, assistant, audio_msg, query):
        os.makedirs(TG_SCRAP_DOWNLOADS, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "track"
        file_name = f"{safe_name}_{int(time.time())}.mp3"
        filepath = os.path.join(TG_SCRAP_DOWNLOADS, file_name)

        try:
            await assistant.download_media(audio_msg, file_name=filepath)
        except Exception:
            return None

        if not os.path.exists(filepath):
            return None
        return filepath

    async def _build_track_details(self, filepath, query, audio_msg=None):
        try:
            dur_sec = await asyncio.get_event_loop().run_in_executor(
                None, check_duration, filepath
            )
            duration_min = seconds_to_min(dur_sec)
        except Exception:
            duration_min = "Unknown"

        title = query.title()
        if audio_msg is not None:
            audio_obj = audio_msg.audio or audio_msg.document
            title = getattr(audio_obj, "title", None) or getattr(audio_obj, "file_name", None) or title

        return {
            "title": title,
            "duration_min": duration_min,
            "filepath": filepath,
        }

    async def download_from_own_db(self, query: str):
        """
        Stage 1: instant lookup against the warmed-up index of the user's
        own archived channels (see warm_up()). No live Telegram search here
        — just a dict/list scan, then a single get_messages() fetch for the
        best match. Returns (track_details, filepath) on a hit, or
        (None, None) if nothing matched (or no channels configured / index
        not warm yet) so the caller can fall back to the VK Music bot.
        """
        if not self.own_channels:
            return None, None

        if not self._index:
            # Not warmed up yet (e.g. bot just started) — build it once now
            # so this and every future request after it are instant.
            await self.warm_up()
        if not self._index:
            return None, None

        assistant = self._get_assistant()
        if not assistant:
            return None, None

        for entry in self._lookup_index(query):
            try:
                msg = await assistant.get_messages(entry["chat_id"], entry["message_id"])
            except Exception:
                continue
            if not msg or not (msg.audio or msg.document):
                continue  # e.g. original message was deleted since warm-up

            filepath = await self._save_audio_message(assistant, msg, query)
            if not filepath:
                continue

            track_details = await self._build_track_details(filepath, query, msg)
            return track_details, filepath

        return None, None

    async def download_from_vkmusic(self, query: str):
        """
        Stage 2 (fallback): scrape the VK-Music-style Telegram bot.
        Returns (track_details, filepath) on success, or (None, None) if
        the bot didn't reply / no audio came back in time.
        """
        assistant = self._get_assistant()
        if not assistant:
            return None, None

        try:
            await assistant.send_message(self.bot_username, query)
        except Exception:
            return None, None

        menu_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.menu_timeout,
            lambda m: bool(getattr(m, "reply_markup", None)
                           and getattr(m.reply_markup, "inline_keyboard", None)),
        )
        if not menu_msg:
            return None, None

        try:
            await menu_msg.click(0, 0)
        except Exception:
            return None, None

        audio_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.audio_timeout,
            lambda m: bool(m.audio or m.voice or (m.document and "audio" in (m.document.mime_type or ""))),
        )
        if not audio_msg:
            return None, None

        filepath = await self._save_audio_message(assistant, audio_msg, query)
        if not filepath:
            return None, None

        track_details = await self._build_track_details(filepath, query, audio_msg)
        return track_details, filepath

    async def download(self, query: str):
        """
        Public entry point used by the rest of the bot. Tries the user's
        own channel archive first, and only falls back to the VK Music
        bot if the archive has no match. Returns (track_details, filepath)
        on success, or (None, None) if both stages fail.
        """
        track_details, filepath = await self.download_from_own_db(query)
        if filepath:
            return track_details, filepath

        return await self.download_from_vkmusic(query)
