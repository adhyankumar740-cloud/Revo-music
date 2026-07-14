
from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse
import httpx
import asyncio
import os
import time
import psutil
import logging

from BROKENXMUSIC.logging import LOGGER
from contextlib import asynccontextmanager

# Imported here (instead of further down) so it's available to lifespan()
# below. This is the SAME Pyrogram client class used by the bot process
# (python3 -m BROKENXMUSIC), but since start.sh runs the bot and this FastAPI
# server as two SEPARATE OS processes, they do NOT share a live connection -
# each process needs its own .start() call. Without this, /resolve fails
# with "Client has not been started yet" as soon as it tries to fetch the
# downloaded file back from Telegram.
from BROKENXMUSIC import app as tg_client


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLOBAL LOGGING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] - [%(levelname)s] - %(name)s - %(message)s",
)

log = LOGGER(__name__)

log.info("🚀 Broken X Network Booting...")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LIFESPAN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

@asynccontextmanager
async def lifespan(app: FastAPI):

    log.info("⚡ Starting FastAPI Lifespan...")

    if not tg_client.is_connected:
        log.info("🔐 Starting Telegram client for this process (needed for /resolve)...")
        try:
            await tg_client.start()
            log.info("✅ Telegram client started in FastAPI process")
        except Exception as e:
            # Don't crash the whole API if this fails - /search will still
            # work, only /resolve (which needs Telegram) will error until
            # this is fixed (check API_ID/API_HASH/BOT_TOKEN/LOGGER_ID).
            log.error(f"❌ Telegram client failed to start: {e}")

    task = asyncio.create_task(self_ping())

    yield

    log.warning("⚠️ Stopping Background Tasks...")

    task.cancel()

    try:
        await task

    except asyncio.CancelledError:
        log.info("✅ Heartbeat Task Cancelled")

    if tg_client.is_connected:
        await tg_client.stop()
        log.info("🔌 Telegram client stopped")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEARTBEAT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def self_ping():

    url = os.getenv(
        "SPACE_URL", 
        f"http://localhost:{os.getenv('PORT', 10000)}"
    )

    log.info(f"🌐 Heartbeat URL Loaded: {url}")

    async with httpx.AsyncClient() as client:

        while True:

            try:

                await asyncio.sleep(600)

                response = await client.get(
                    url,
                    timeout=5.0
                )

                log.info(
                    f"📡 System Heartbeat: {response.status_code}"
                )

            except Exception as e:

                log.error(
                    f"❌ Heartbeat Failed: {e}"
                )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FASTAPI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = FastAPI(
    title="Broken X Network - System Core",
    version="4.2.1",
    lifespan=lifespan
)

start_time = time.time()

log.info("✅ FastAPI Initialized")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ROOT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/")
async def root():

    uptime = time.time() - start_time

    log.info("📥 Root Endpoint Hit")

    return {
        "status": "Operational",
        "node_version": os.popen('node -v').read().strip(),
        "memory_usage": f"{psutil.virtual_memory().percent}%",
        "uptime": f"{int(uptime)} seconds",
        "api_endpoint": "https://api.telegram.org",
        "service": "BrokenX-Music-Core"
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEALTH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/health")
async def health():

    log.info("💚 Health Endpoint Hit")

    return {
        "status": "healthy",
        "timestamp": time.time()
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESOLVE (BrokenXAPI relay for the Android app)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Reuses the SAME Pyrogram client + BrokenXAPI key the bot already uses for
# /play (see BROKENXMUSIC/platforms/Youtube.py -> download_song()). No new
# Telegram session, no new BrokenXAPI usage pattern - just an HTTP door into
# the same flow, for your own Android app instead of a Telegram chat command.

from BROKENXMUSIC.platforms.Youtube import download_song
from BROKENXMUSIC.utils.formatters import time_to_seconds
from youtube_search import YoutubeSearch

RELAY_API_KEY = os.getenv("RELAY_API_KEY", "")


def _check_relay_key(x_relay_key: str | None):
    if RELAY_API_KEY and x_relay_key != RELAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Relay-Key header")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEARCH (BrokenXAPI relay for the Android app)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# No Google/YouTube Data API key here - youtube_search scrapes YouTube's own
# search results page, same package Youtube.py already uses for /play's
# track()/details() lookups. Keeps search+metadata on the same relay as
# playback, instead of needing a separate quota-limited API key on the app.

@app.get("/search")
async def search(
    query: str = Query(...),
    limit: int = Query(default=20, le=25),
    x_relay_key: str | None = Header(default=None),
):
    _check_relay_key(x_relay_key)

    log.info(f"🔎 Search requested: {query}")

    try:
        raw_results = YoutubeSearch(query, max_results=limit).to_dict()
    except Exception as e:
        log.error(f"❌ Search failed: {e}")
        raise HTTPException(status_code=502, detail="Search failed")

    tracks = []
    for r in raw_results:
        video_id = r.get("id")
        if not video_id:
            continue
        duration_str = r.get("duration") or "0:00"
        try:
            duration_sec = time_to_seconds(duration_str)
        except Exception:
            duration_sec = 0
        thumbnails = r.get("thumbnails") or [""]
        tracks.append({
            "video_id": video_id,
            "title": r.get("title") or "Unknown Title",
            "artist": r.get("channel") or "Unknown Artist",
            "thumbnail": thumbnails[0],
            "duration_sec": duration_sec,
        })

    return {"query": query, "results": tracks}


@app.get("/resolve")
async def resolve(
    request: Request,
    video_id: str = Query(...),
    x_relay_key: str | None = Header(default=None),
):
    _check_relay_key(x_relay_key)

    log.info(f"🎯 Resolve requested: {video_id}")

    file_path = await download_song(video_id)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=502, detail="Could not resolve this video")

    filename = os.path.basename(file_path)
    return {
        "video_id": video_id,
        "stream_url": f"{str(request.base_url).rstrip('/')}/audio/{filename}",
    }


@app.get("/audio/{filename}")
async def audio(filename: str, x_relay_key: str | None = Header(default=None)):
    _check_relay_key(x_relay_key)

    safe_name = os.path.basename(filename)
    file_path = os.path.join("downloads", safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Not found - call /resolve first")

    return FileResponse(file_path, media_type="audio/webm")
