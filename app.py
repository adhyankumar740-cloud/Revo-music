
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

async def _start_telegram_client():
    if tg_client.is_connected:
        return
    log.info("🔐 Starting Telegram client for this process (needed for /resolve)...")
    try:
        await tg_client.start()
        log.info("✅ Telegram client started in FastAPI process")
    except Exception as e:
        # /search still works without this - only /resolve needs Telegram,
        # and it already fails cleanly (502) if the client isn't up yet.
        log.error(f"❌ Telegram client failed to start: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):

    log.info("⚡ Starting FastAPI Lifespan...")

    # IMPORTANT: do NOT await this here. If Telegram login is slow (or gets
    # stuck), awaiting it would block ASGI startup from ever completing -
    # meaning uvicorn never opens its port, and Render's port-scan times out
    # with "no open ports detected" (this is exactly what happened before).
    # Running it as a background task lets the port open immediately;
    # /resolve just won't work until this finishes in the background.
    telegram_start_task = asyncio.create_task(_start_telegram_client())

    task = asyncio.create_task(self_ping())

    yield

    log.warning("⚠️ Stopping Background Tasks...")

    task.cancel()
    telegram_start_task.cancel()

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

from BROKENXMUSIC.platforms.Youtube import resolve_song_stream_location, GET_MESSAGES_TIMEOUT, prefetch_video
from BROKENXMUSIC.utils.formatters import time_to_seconds
from youtube_search import YoutubeSearch
from fastapi.responses import StreamingResponse

RELAY_API_KEY = os.getenv("RELAY_API_KEY", "")

# How many of the top /search results to start resolving in the background
# right away, instead of waiting for the user to actually tap one. This is
# what removes the "first play buffers a lot" wait - the slow part
# (BrokenXAPI download+convert+upload) now happens while they're still
# looking at the results list.
PREFETCH_TOP_N = int(os.getenv("PREFETCH_TOP_N", 4))

# asyncio only holds a WEAK reference to a task's coroutine while it runs -
# if we don't keep our own reference, a fire-and-forget task can get
# garbage-collected mid-flight. Keep them in a set and drop each one via its
# own done-callback once it finishes.
_bg_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


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

    for track in tracks[:PREFETCH_TOP_N]:
        _fire_and_forget(prefetch_video(track["video_id"]))

    return {"query": query, "results": tracks}


# RESOLVE no longer downloads anything - it only finds WHERE the file lives
# on Telegram (BrokenXAPI call + one get_messages lookup), so it returns in
# a few seconds regardless of file size. This bound only needs to cover
# BROKENXAPI_TIMEOUT + GET_MESSAGES_TIMEOUT, not a full download anymore.
RESOLVE_HARD_TIMEOUT = int(os.getenv("RESOLVE_HARD_TIMEOUT", 45))


@app.get("/resolve")
async def resolve(
    request: Request,
    video_id: str = Query(...),
    x_relay_key: str | None = Header(default=None),
):
    _check_relay_key(x_relay_key)

    # If the Telegram client for THIS process hasn't finished logging in yet
    # (it starts in the background - see lifespan()), get_messages() would
    # otherwise hang/fail unpredictably. Tell the app to retry shortly
    # instead of letting the request sit until the gateway kills it.
    if not tg_client.is_connected:
        raise HTTPException(status_code=503, detail="Server is still starting up, retry in a few seconds")

    log.info(f"🎯 Resolve requested: {video_id}")

    try:
        channel_name, message_id = await asyncio.wait_for(
            resolve_song_stream_location(video_id), timeout=RESOLVE_HARD_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.error(f"⏱️ Resolve timed out for {video_id} after {RESOLVE_HARD_TIMEOUT}s")
        raise HTTPException(status_code=504, detail="Resolving this video took too long, try again")

    if not channel_name:
        raise HTTPException(status_code=502, detail="Could not resolve this video")

    return {
        "video_id": video_id,
        "stream_url": f"{str(request.base_url).rstrip('/')}/stream/{channel_name}/{message_id}",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STREAM (proxies audio bytes chunk-by-chunk, no server-side download)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Uses Pyrogram's stream_media() to pull the file from Telegram in pieces
# and forward each piece straight into the HTTP response as it arrives.
# The Android app can start playing as soon as the first chunks land,
# instead of waiting for the whole file to be downloaded to disk first.

@app.get("/stream/{channel_name}/{message_id}")
async def stream(
    channel_name: str,
    message_id: int,
    x_relay_key: str | None = Header(default=None),
):
    _check_relay_key(x_relay_key)

    if not tg_client.is_connected:
        raise HTTPException(status_code=503, detail="Server is still starting up, retry in a few seconds")

    try:
        msg = await asyncio.wait_for(
            tg_client.get_messages(channel_name, message_id), timeout=GET_MESSAGES_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Could not fetch this file in time")

    media = msg and (msg.audio or msg.voice or msg.document or msg.video)
    if not media:
        raise HTTPException(status_code=404, detail="No media at this message - resolve again")

    file_size = getattr(media, "file_size", None)
    mime_type = getattr(media, "mime_type", None) or "audio/mpeg"

    async def chunk_stream():
        async for chunk in tg_client.stream_media(msg):
            yield chunk

    headers = {"Content-Length": str(file_size)} if file_size else {}
    return StreamingResponse(chunk_stream(), media_type=mime_type, headers=headers)


@app.get("/audio/{filename}")
async def audio(filename: str, x_relay_key: str | None = Header(default=None)):
    _check_relay_key(x_relay_key)

    safe_name = os.path.basename(filename)
    file_path = os.path.join("downloads", safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Not found - call /resolve first")

    return FileResponse(file_path, media_type="audio/webm")
