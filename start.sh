#!/bin/bash
echo "🔑 Authorizing Telegram Bot..."

# --- PO Token provider (bgutil-ytdlp-pot-provider) --------------------------
# Internal-only Node.js server on 127.0.0.1:4416 (never exposed to the
# internet — Render only cares about the ONE public port the Python bot
# itself binds via webserver.py). yt-dlp's Python plugin auto-detects it
# at this default address, so no yt-dlp option changes were needed anywhere
# else in the codebase. Runs once for the container's whole lifetime;
# logged separately so it doesn't clutter the main bot log / crash-restart
# loop below.
echo "🔐 Starting PO Token provider (bgutil) on 127.0.0.1:4416..."
(
    while true; do
        node /opt/bgutil-ytdlp-pot-provider/server/build/main.js >> /tmp/bgutil-pot.log 2>&1
        echo "$(date): bgutil POT server exited, restarting in 5s..." >> /tmp/bgutil-pot.log
        sleep 5
    done
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
