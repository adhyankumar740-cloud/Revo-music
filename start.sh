#!/bin/bash
echo "🔑 Authorizing Telegram Bot..."

while true; do
    output=$(python3 -m BROKENXMUSIC 2>&1 | tee /tmp/last_run.log)
    wait_time=$(echo "$output" | grep -oP "A wait of \K[0-9]+(?= seconds)")
    if [ -n "$wait_time" ]; then
        echo "⏳ FloodWait detected, sleeping for ${wait_time}s..."
        sleep "$wait_time"
    else
        echo "⚠️ Core Process Terminated. Rebooting in 5s..."
        sleep 5
    fi
done
