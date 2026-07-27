import hashlib
import os
from os import path

import aiohttp

import config
from BROKENXMUSIC import LOGGER
from BROKENXMUSIC.utils.formatters import seconds_to_min


def _hf_headers() -> dict:
    key = getattr(config, "HF_RESOLVER_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


class SoundAPI:
    def __init__(self):
        pass

    async def valid(self, link: str):
        if "soundcloud" in link:
            return True
        else:
            return False

    async def download(self, url):
        """Downloads any yt-dlp-supported URL (SoundCloud etc.) via the HF
        Space's generic /api/download-url endpoint — no yt-dlp import here
        on Render at all anymore."""
        logger = LOGGER("SoundCloud")
        hf_resolver_url = getattr(config, "HF_RESOLVER_URL", "").strip().rstrip("/")
        if not hf_resolver_url:
            logger.warning("⚠️ [SOUNDCLOUD] HF_RESOLVER_URL not set")
            return False

        os.makedirs("downloads", exist_ok=True)
        key = hashlib.md5(url.encode()).hexdigest()
        dl_timeout = getattr(config, "HF_RESOLVER_DOWNLOAD_TIMEOUT", 60)

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=dl_timeout)
            ) as session:
                async with session.get(
                    f"{hf_resolver_url}/api/download-url",
                    params={"url": url, "key": key},
                    headers=_hf_headers(),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"❌ [SOUNDCLOUD] HTTP {resp.status}: {body[:200]}")
                        return False

                    cd = resp.headers.get("Content-Disposition", "")
                    ext = "mp3"
                    if "filename=" in cd:
                        fname = cd.split("filename=")[-1].strip('"; ')
                        if "." in fname:
                            ext = fname.rsplit(".", 1)[-1]

                    dest = path.join("downloads", f"{key}.{ext}")
                    tmp_dest = dest + ".part"
                    with open(tmp_dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 256):
                            f.write(chunk)
                    os.replace(tmp_dest, dest)

                    title = resp.headers.get("X-Title") or "SoundCloud Track"
                    duration = resp.headers.get("X-Duration") or "0"
                    uploader = resp.headers.get("X-Uploader") or "Unknown"
                    try:
                        duration_sec = int(float(duration))
                    except ValueError:
                        duration_sec = 0

                    track_details = {
                        "title": title,
                        "duration_sec": duration_sec,
                        "duration_min": seconds_to_min(duration_sec),
                        "uploader": uploader,
                        "filepath": dest,
                    }
                    return track_details, dest
        except Exception as e:
            logger.error(f"❌ [SOUNDCLOUD] failed: {e}")
            return False
