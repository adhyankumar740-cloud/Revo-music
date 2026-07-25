import asyncio
import os
import time

import httpx

import config
from BROKENXMUSIC.utils.formatters import check_duration, seconds_to_min

# tg-scrap lives in <repo-root>/tg-scrap and saves files to tg-scrap/downloads
TG_SCRAP_DOWNLOADS = os.path.join(os.getcwd(), "tg-scrap", "downloads")


class TgScrapAPI:
    def __init__(self):
        # tg-scrap's server.js binds to the same $PORT the whole app uses
        port = os.getenv("PORT", "10000")
        self.base_url = f"http://127.0.0.1:{port}"
        self.bot_username = config.VK_MUSIC_BOT
        self.timeout = config.TG_SCRAP_TIMEOUT

    async def download(self, query: str):
        """
        Triggers tg-scrap's /extract-vk endpoint, polls /status until the
        job finishes, and returns (track_details, filepath) — same shape
        as the other platform download() methods — or (None, None) if it
        couldn't find/download anything in time.
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/extract-vk",
                    params={"song": query, "bot": self.bot_username},
                )
                if resp.status_code >= 400 and resp.status_code != 409:
                    return None, None
        except Exception:
            # tg-scrap server not reachable/down — fail fast
            return None, None

        start = time.time()
        while time.time() - start < self.timeout:
            await asyncio.sleep(2)
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    status_resp = await client.get(f"{self.base_url}/status")
                    data = status_resp.json()
            except Exception:
                continue

            details = data.get("details", {}) or {}
            status = details.get("status")

            if status == "completed":
                file_name = details.get("fileName")
                if not file_name:
                    return None, None
                filepath = os.path.join(TG_SCRAP_DOWNLOADS, file_name)
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

            if status == "failed":
                return None, None

        return None, None
