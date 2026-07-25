#!/bin/bash
echo "⚙️ Initializing Node.js Environment..."
node -v
npm -v

echo "📡 Launching Tg-Scrap Server (Web Service + Downloader)..."
(cd tg-scrap && PORT="${PORT:-10000}" node server.js) &

echo "🔑 Authorizing Telegram Bot..."
while true; do
    python3 -m BROKENXMUSIC 
    echo "⚠️ Core Process Terminated. Rebooting in 5s..."
    sleep 5
done
