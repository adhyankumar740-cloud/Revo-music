#!/bin/bash
echo "⚙️ Initializing Node.js Environment..."
node -v
npm -v
echo "⚙️ Initializing BrokenXAPI"
brokenx -v 

echo "🚀 Launching System Core API..."
python3 -m uvicorn app:app --host 0.0.0.0 --port 10000 &

echo "🔑 Authorizing Telegram Bot..."
while true; do
    python3 -m BROKENXMUSIC 
    echo "⚠️ Core Process Terminated. Rebooting in 5s..."
    sleep 5
done
