#!/bin/bash
echo "🔑 Authorizing Telegram Bot..."

# --- PO Token provider (bgutil-ytdlp-pot-provider) --------------------------
# Internal-only Node.js server on 127.0.0.1:4416 (never exposed to the
# internet — Render only cares about the ONE public port the Python bot
# itself binds via webserver.py). yt-dlp's Python plugin auto-detects it
# at this default address, so no yt-dlp option changes were needed anywhere
# else in the codebase. Runs once for the container's whole lifetime.
#
# NOTE: output goes straight to this script's own stdout (prefixed
# "[POT]"), NOT to a file — a file under /tmp can only be read via
# Render's Shell tab, which is a paid feature. Printing to stdout means it
# shows up in the normal free-tier "Logs" tab instead, mixed in with the
# rest of the boot log.
echo "🔐 Starting PO Token provider (bgutil) on 127.0.0.1:4416..."
echo "[POT] node version: $(node --version 2>&1 || echo 'node NOT FOUND')"
echo "[POT] build file check:"
ls -la /opt/bgutil-ytdlp-pot-provider/server/build/ 2>&1 | sed 's/^/[POT]   /'
(
    while true; do
        # stdbuf forces line-buffering — without it, piping node's stdout
        # through sed can fully block-buffer it, silently hiding node's own
        # startup logs (or crash messages) for a long time even though the
        # process is actually running.
        stdbuf -oL -eL node /opt/bgutil-ytdlp-pot-provider/server/build/main.js 2>&1 | stdbuf -oL sed 's/^/[POT] /'
        echo "[POT] $(date): server exited, restarting in 5s..."
        sleep 5
    done
) &

# Give the server a moment to bind, then log a plain reachability check —
# this alone (visible in the free Logs tab) tells you if it's actually up
# without needing Shell access at all.
(
    sleep 10
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:4416/ 2>&1)
    if [ -n "$code" ] && [ "$code" != "000" ]; then
        echo "[POT] ✅ reachable on 127.0.0.1:4416 (HTTP $code)"
    else
        echo "[POT] ❌ NOT reachable on 127.0.0.1:4416 (curl result: '$code') — check the [POT] lines above for a startup error"
    fi
) &

while true; do
    python3 -u -m BROKENXMUSIC 2>&1 | tee /tmp/last_run.log
    wait_time=$(grep -oP "A wait of \K[0-9]+(?= seconds)" /tmp/last_run.log | tail -1)
    if [ -n "$wait_time" ]; then
        echo "⏳ FloodWait detected, sleeping for ${wait_time}s..."
        sleep "$wait_time"
    else
        echo "⚠️ Core Process Terminated. Rebooting in 5s..."
        sleep 5
    fi
done
