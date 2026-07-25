import asyncio
import os
import re
import time

import config
from BROKENXMUSIC import LOGGER
from BROKENXMUSIC.utils.formatters import check_duration, seconds_to_min

logger = LOGGER("TgScrap")

# Downloaded songs are saved here (same folder tg-scrap's own scripts use,
# kept for consistency even though tg-scrap's Node process isn't involved
# in this flow anymore).
TG_SCRAP_DOWNLOADS = os.path.join(os.getcwd(), "tg-scrap", "downloads")


class TgScrapAPI:
    """
    Scrapes a song from a VK-Music-style Telegram bot using the music
    bot's OWN assistant account (the same Pyrogram userbot that joins
    voice chats) — no separate Node.js process, no second Telegram
    session, no HTTP round-trip.

    This is now purely the FALLBACK path. Your own archived channels are
    handled by SongCache (BROKENXMUSIC/platforms/SongCache.py + MongoDB),
    which play.py checks first — that's the fast path, built once via the
    /indexcache command instead of scanning channels live on every request.
    """

    def __init__(self):
        self.bot_username = config.VK_MUSIC_BOT
        self.menu_timeout = config.TG_SCRAP_MENU_TIMEOUT
        self.audio_timeout = config.TG_SCRAP_TIMEOUT

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

    async def download(self, query: str):
        """
        Returns (track_details, filepath) on success, or (None, None) if
        the bot didn't reply / no audio came back in time.
        """
        assistant = self._get_assistant()
        if not assistant:
            logger.error(f"[TgScrap] No connected assistant available for query {query!r}")
            return None, None

        try:
            await assistant.send_message(self.bot_username, query)
        except Exception as e:
            logger.error(f"[TgScrap] Could not message {self.bot_username} for {query!r}: {e}")
            return None, None

        menu_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.menu_timeout,
            lambda m: bool(getattr(m, "reply_markup", None)
                           and getattr(m.reply_markup, "inline_keyboard", None)),
        )
        if not menu_msg:
            logger.error(
                f"[TgScrap] {self.bot_username} gave no results menu for {query!r} "
                f"within {self.menu_timeout}s"
            )
            return None, None

        try:
            await menu_msg.click(0, 0)
        except Exception as e:
            logger.error(f"[TgScrap] Could not click result menu for {query!r}: {e}")
            return None, None

        audio_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.audio_timeout,
            lambda m: bool(m.audio or m.voice or (m.document and "audio" in (m.document.mime_type or ""))),
        )
        if not audio_msg:
            logger.error(
                f"[TgScrap] No audio received from {self.bot_username} for {query!r} "
                f"within {self.audio_timeout}s"
            )
            return None, None

        os.makedirs(TG_SCRAP_DOWNLOADS, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "track"
        file_name = f"{safe_name}_{int(time.time())}.mp3"
        filepath = os.path.join(TG_SCRAP_DOWNLOADS, file_name)

        try:
            await assistant.download_media(audio_msg, file_name=filepath)
        except Exception as e:
            logger.error(f"[TgScrap] download_media failed for {query!r}: {e}")
            return None, None

        if not os.path.exists(filepath):
            logger.error(f"[TgScrap] Downloaded file missing on disk for {query!r}: {filepath}")
            return None, None

        # Validate the file is actually playable audio before handing it off
        # to the voice-chat stream — a truncated/corrupt download would
        # otherwise silently join the call and just produce no sound.
        try:
            dur_sec = await asyncio.get_event_loop().run_in_executor(
                None, check_duration, filepath
            )
            if not dur_sec:
                raise ValueError("ffprobe reported zero/no duration")
            duration_min = seconds_to_min(dur_sec)
        except Exception as e:
            logger.error(
                f"[TgScrap] Downloaded file for {query!r} failed validation "
                f"(likely corrupt/incomplete): {e}"
            )
            try:
                os.remove(filepath)
            except Exception:
                pass
            return None, None

        track_details = {
            "title": query.title(),
            "duration_min": duration_min,
            "filepath": filepath,
        }
        return track_details, filepath
