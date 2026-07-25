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
        # How many nested inline-keyboard menus to click through (top
        # option each time) before giving up. 1 = old single-click
        # behaviour. Some bots need 2-3 (track list -> quality/format).
        self.max_menu_hops = getattr(config, "TG_SCRAP_MAX_MENU_HOPS", 3)

    def _get_assistant(self):
        # Local import to avoid circular imports at module load time.
        from BROKENXMUSIC import userbot

        for client in (userbot.one, userbot.two, userbot.three, userbot.four, userbot.five):
            if client and getattr(client, "is_connected", False):
                return client
        return None

    async def _wait_for(self, client, chat_id, min_id, timeout, condition, poll_interval=0.4):
        """Assistants run with no_updates=True (deliberately — it avoids the
        RAM/CPU cost of live update dispatch for accounts that don't need
        it), so they never receive push events and a MessageHandler would
        simply never fire here. Polling get_chat_history is the only option
        for them — but poll fast, and use a strict `msg.id > min_id`
        threshold (the ID of the message we just sent) instead of a
        seen-ids/history snapshot. That threshold can't ever miss a fast
        reply: message IDs are monotonically increasing per chat, so
        anything the bot sends back is guaranteed to have a higher ID than
        our own message, no matter how quickly it arrives."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                async for msg in client.get_chat_history(chat_id, limit=5):
                    if msg.id <= min_id:
                        continue
                    if condition(msg):
                        return msg
            except Exception:
                pass
            await asyncio.sleep(poll_interval)
        return None

    async def _locate_audio(self, query: str):
        """Message the scraper bot, click through its menu(s), and return
        (assistant, audio_msg) once an actual audio message shows up — or
        (None, None) on timeout/failure. This is the shared, unavoidably
        sequential part (search -> menu -> click); `download()` and
        `stream_or_download()` both build on top of it, they just differ
        in how they turn `audio_msg` into playable bytes."""
        assistant = self._get_assistant()
        if not assistant:
            logger.error(f"[TgScrap] No connected assistant available for query {query!r}")
            return None, None

        # Some bots (Shazam-style finders) send several messages back for
        # one query: a search-echo message (often carries just one small
        # button, e.g. a 🔍 icon) first, THEN the real track-list menu
        # (many button rows: each track + "More tracks" + a search/share
        # row + "Add to group" ...), and sometimes a promo message after
        # that. Requiring several rows filters out the echo message so we
        # target the actual track list, not whatever keyboard shows up
        # first.
        MIN_MENU_ROWS = 3

        try:
            sent = await assistant.send_message(self.bot_username, query)
        except Exception as e:
            logger.error(f"[TgScrap] Could not message {self.bot_username} for {query!r}: {e}")
            return None, None

        menu_msg = await self._wait_for(
            assistant,
            self.bot_username,
            sent.id,
            self.menu_timeout,
            lambda m: bool(getattr(m, "reply_markup", None))
            and len(getattr(m.reply_markup, "inline_keyboard", []) or []) >= MIN_MENU_ROWS,
        )
        if not menu_msg:
            logger.error(
                f"[TgScrap] {self.bot_username} gave no results menu "
                f"(>= {MIN_MENU_ROWS} rows) for {query!r} within {self.menu_timeout}s"
            )
            return None, None

        # Some bots (e.g. Shazam-style finders) don't hand over audio after
        # one click — they show a track list, then a second menu (pick
        # format/quality), sometimes more. Keep clicking the top option of
        # whatever inline keyboard shows up next, until actual audio
        # arrives or we run out of menu hops / time.
        audio_msg = None
        current_menu = menu_msg
        for hop in range(self.max_menu_hops):
            try:
                await current_menu.click(0, 0)
            except Exception as e:
                logger.error(
                    f"[TgScrap] Could not click menu (hop {hop + 1}) for {query!r}: {e}"
                )
                return None, None

            next_msg = await self._wait_for(
                assistant,
                self.bot_username,
                current_menu.id,
                self.audio_timeout,
                lambda m: bool(
                    m.audio or m.voice
                    or (m.document and "audio" in (m.document.mime_type or ""))
                    or len(getattr(getattr(m, "reply_markup", None), "inline_keyboard", []) or []) >= 2
                ),
            )
            if not next_msg:
                break

            if next_msg.audio or next_msg.voice or (
                next_msg.document and "audio" in (next_msg.document.mime_type or "")
            ):
                audio_msg = next_msg
                break

            # It's another real menu (2+ rows, e.g. a quality/format
            # picker) — go one hop deeper. Single-button messages (promo
            # footers etc.) don't satisfy the condition above, so they're
            # simply skipped over by _wait_for.
            current_menu = next_msg

        if not audio_msg:
            logger.error(
                f"[TgScrap] No audio received from {self.bot_username} for {query!r} "
                f"after {self.max_menu_hops} menu hop(s), within {self.audio_timeout}s each"
            )
            return None, None

        return assistant, audio_msg

    async def download(self, query: str):
        """
        Returns (track_details, filepath) on success, or (None, None) if
        the bot didn't reply / no audio came back in time.

        Full-download path: waits for the entire file to land on disk and
        validates it with ffprobe before returning. Safe and simple, but
        the caller (and therefore the voice-chat join) can't start until
        the whole file has been transferred. Prefer stream_or_download()
        for actual playback — this one's still handy for callers that
        genuinely need a real file on disk (e.g. re-uploading to a cache
        channel).
        """
        located = await self._locate_audio(query)
        if not located or not located[0]:
            return None, None
        assistant, audio_msg = located

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

    async def stream_or_download(self, query: str, save_dir=None, fifo_open_timeout=20):
        """Like download(), but instead of waiting for the whole track to
        land on disk before playback can even be attempted, it pipes the
        scraper bot's chunks into a named pipe (FIFO) as they arrive —
        ffmpeg (via pytgcalls) reads from that FIFO exactly like it would a
        regular file, so join_call()/play() can be issued immediately and
        audio starts as soon as the first chunk is in, instead of after
        search + menu-clicks + full-download + ffprobe validation all
        finish first.

        Returns (track_details, fifo_path) on success, or (None, None) if
        the bot never produced audio, or if the FIFO plumbing itself isn't
        available on this platform (falls back to download() then)."""
        located = await self._locate_audio(query)
        if not located or not located[0]:
            return None, None
        assistant, audio_msg = located

        async def _open_gen():
            gen = assistant.stream_media(audio_msg)
            try:
                chunk = await gen.__anext__()
                return gen, chunk
            except StopAsyncIteration:
                return gen, b""
            except Exception as e:
                return None, e

        gen, first_chunk = await _open_gen()
        if gen is None:
            logger.info(
                f"[TgScrap] Stream probe failed for {query!r} ({first_chunk}) "
                f"— falling back to full download."
            )
            return await self._download_from_audio_msg(query, assistant, audio_msg)

        save_dir = save_dir or TG_SCRAP_DOWNLOADS
        os.makedirs(save_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "track"
        fifo_path = os.path.join(save_dir, f"{safe_name}_{int(time.time())}.fifo")

        try:
            os.mkfifo(fifo_path)
        except Exception as e:
            logger.error(
                f"[TgScrap] mkfifo failed for {query!r} ({e}) — falling back "
                f"to full download."
            )
            return await self._download_from_audio_msg(query, assistant, audio_msg)

        async def _pump():
            fd = None
            try:
                fd = await asyncio.wait_for(
                    asyncio.to_thread(os.open, fifo_path, os.O_WRONLY),
                    timeout=fifo_open_timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"[TgScrap] Nobody read the FIFO for {query!r} within "
                    f"{fifo_open_timeout}s — abandoning stream."
                )
            except Exception as e:
                logger.error(f"[TgScrap] FIFO open failed for {query!r}: {e}")

            if fd is not None:
                try:
                    if first_chunk:
                        await asyncio.to_thread(os.write, fd, first_chunk)
                    async for chunk in gen:
                        await asyncio.to_thread(os.write, fd, chunk)
                except Exception as e:
                    logger.error(f"[TgScrap] Streaming into FIFO failed for {query!r}: {e}")
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
            try:
                os.remove(fifo_path)
            except Exception:
                pass

        asyncio.create_task(_pump())

        duration_min = "Unknown"
        try:
            dur = getattr(getattr(audio_msg, "audio", None) or getattr(audio_msg, "voice", None), "duration", 0)
            if dur:
                duration_min = seconds_to_min(dur)
        except Exception:
            pass

        track_details = {
            "title": query.title(),
            "duration_min": duration_min,
            "filepath": fifo_path,
        }
        return track_details, fifo_path

    async def _download_from_audio_msg(self, query, assistant, audio_msg):
        """Shared tail end of download() (full-file-on-disk + ffprobe
        validation), reusable by stream_or_download()'s fallback path
        without re-running the search/menu-click steps."""
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
            return None, None

        try:
            dur_sec = await asyncio.get_event_loop().run_in_executor(
                None, check_duration, filepath
            )
            if not dur_sec:
                raise ValueError("ffprobe reported zero/no duration")
            duration_min = seconds_to_min(dur_sec)
        except Exception as e:
            logger.error(f"[TgScrap] Fallback download validation failed for {query!r}: {e}")
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
