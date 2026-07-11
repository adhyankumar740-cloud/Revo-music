
from fastapi import FastAPI
import httpx
import asyncio
import os
import time
import psutil
import logging

from BROKENXMUSIC.logging import LOGGER
from contextlib import asynccontextmanager


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

    task = asyncio.create_task(self_ping())

    yield

    log.warning("⚠️ Stopping Background Tasks...")

    task.cancel()

    try:
        await task

    except asyncio.CancelledError:
        log.info("✅ Heartbeat Task Cancelled")


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

                await asyncio.sleep(12)

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
