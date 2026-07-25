FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt

# NOTE: the tg-scrap Node.js sidecar (Express + its own GramJS Telegram
# session) has been removed from the boot process. It was only there to
# satisfy Render's "Web Service" port-bind check for an old scraping flow
# that isn't used anymore — the Python bot now binds $PORT itself via
# BROKENXMUSIC/utils/webserver.py in the same process, so a whole separate
# Node.js runtime (+ its own Telegram session held in RAM) is no longer
# needed. The tg-scrap/ folder can be deleted from the repo entirely if you
# don't use its standalone CLI scripts for anything else.

CMD bash start.sh
