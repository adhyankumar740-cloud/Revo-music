"""
Tiny in-process health endpoint for Render's "Web Service" health check.

Render Web Services must bind to $PORT or the deploy is marked unhealthy.
This used to be satisfied by running a whole separate Node.js process
(Express + its own GramJS Telegram session) — a second runtime sitting in
RAM 24/7 just to answer a ping. That scraping flow isn't used anymore (the
Python TgScrap path talks to Telegram directly via the existing assistant),
so instead we just bind $PORT inside the bot's own asyncio loop with
aiohttp (already a dependency) — no extra process, no extra Telegram
session, no extra RAM.
"""

import os

from aiohttp import web

from BROKENXMUSIC import LOGGER

logger = LOGGER("WebServer")

_runner = None


async def _health(request):
    return web.json_response({"service": "Revo Music", "status": "online"})


async def start_web_server():
    global _runner
    port = int(os.environ.get("PORT", 8080))

    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/status", _health)

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server listening on 0.0.0.0:{port} (for Render's web-service check)")


async def stop_web_server():
    if _runner:
        await _runner.cleanup()
