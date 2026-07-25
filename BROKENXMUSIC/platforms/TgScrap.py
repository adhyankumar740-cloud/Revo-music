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
    session, no HTTP round-trip. Fastest possible path.
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
        # Only used to exclude messages that already existed before we sent
        # the query. Deliberately NOT used to skip messages on later polls —
        # vkmusic_bot edits its menu message in place to attach the audio,
        # so the same message id must be re-checked every poll or the edit
        # (and the audio) is missed forever.
        baseline_ids = set()
        try:
            async for msg in client.get_chat_history(chat_id, limit=5):
                baseline_ids.add(msg.id)
        except Exception:
            pass

        start = time.time()
        while time.time() - start < timeout:
            await asyncio.sleep(poll_interval)
            try:
                async for msg in client.get_chat_history(chat_id, limit=5):
                    if msg.id in baseline_ids:
                        continue
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
            logger.error(f"[TgScrap] No connected assistant available for query: {query!r}")
            return None, None
        logger.info(f"[TgScrap] Using assistant: {getattr(assistant, 'name', assistant)}")

        try:
            await assistant.send_message(self.bot_username, query)
            logger.info(f"[TgScrap] Sent query to {self.bot_username}: {query!r}")
        except Exception as e:
            logger.error(f"[TgScrap] send_message failed: {e}")
            return None, None

        menu_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.menu_timeout,
            lambda m: bool(getattr(m, "reply_markup", None)
                           and getattr(m.reply_markup, "inline_keyboard", None)),
        )
        if not menu_msg:
            logger.error(f"[TgScrap] No menu (inline keyboard) received within {self.menu_timeout}s for: {query!r}")
            return None, None

        # Log the full button layout so we can see what row/col 0,0 actually is
        try:
            kb = menu_msg.reply_markup.inline_keyboard
            layout = [[(b.text, b.callback_data) for b in row] for row in kb]
            logger.info(f"[TgScrap] Menu received. Text={menu_msg.text!r} Buttons={layout}")
        except Exception as e:
            logger.error(f"[TgScrap] Could not read button layout: {e}")

        # This isn't a results list — it's the "no results" / pagination-settings
        # menu (⬅️ ❌ ➡️ + bitrate/lossless/title toggles). Clicking (0,0) on it
        # hits the ⬅️ previous-page button, not a track, so bail out instead.
        if menu_msg.text and "found nothing" in menu_msg.text.lower():
            logger.error(f"[TgScrap] Bot reported no results for: {query!r}")
            return None, None

        try:
            click_result = await menu_msg.click(0, 0)
            logger.info(f"[TgScrap] Clicked (0,0). Result: {click_result!r}")
        except Exception as e:
            logger.error(f"[TgScrap] click(0,0) raised: {e}")
            return None, None

        audio_msg = await self._wait_for(
            assistant,
            self.bot_username,
            self.audio_timeout,
            lambda m: bool(m.audio or m.voice or (m.document and "audio" in (m.document.mime_type or ""))),
        )
        if not audio_msg:
            logger.error(f"[TgScrap] No audio received within {self.audio_timeout}s after click, for: {query!r}")
            # Peek at whatever DID arrive after the click, to see if it looped back to a menu/search prompt
            try:
                async for m in assistant.get_chat_history(self.bot_username, limit=3):
                    logger.info(f"[TgScrap] Recent msg after click -> text={m.text!r} has_menu={bool(getattr(m, 'reply_markup', None))} has_audio={bool(m.audio)}")
            except Exception:
                pass
            return None, None
        logger.info(f"[TgScrap] Audio message received for: {query!r}")

        os.makedirs(TG_SCRAP_DOWNLOADS, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "track"
        file_name = f"{safe_name}_{int(time.time())}.mp3"
        filepath = os.path.join(TG_SCRAP_DOWNLOADS, file_name)

        try:
            await assistant.download_media(audio_msg, file_name=filepath)
        except Exception:
            return None, None

        if not os.path.exists(filepath):
            return None, None

        try:
            dur_sec = await asyncio.get_event_loop().run_in_executor(
                None, check_duration, filepath
            )
            duration_min = seconds_to_min(dur_sec)
        except Exception:
            duration_min = "Unknown"

        track_details = {
            "title": query.title(),
            "duration_min": duration_min,
            "filepath": filepath,
        }
        return track_details, filepath
