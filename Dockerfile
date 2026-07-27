FROM python:3.11-slim

# NOTE: Node.js, Deno, and the bgutil POT-provider sidecar have all been
# REMOVED from this Dockerfile. They existed only to support yt-dlp's
# JS-challenge solving and PO-token generation running LOCALLY on Render.
# yt-dlp itself has been fully offloaded to an external HF Space now — this
# container never runs yt-dlp at all, so none of that is needed here
# anymore. Build time and image size both drop substantially as a result.

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    unzip \
    ca-certificates \
    build-essential \
    python3 \
    pkg-config \
    libcairo2-dev \
    libpango1.0-dev \
    libjpeg-dev \
    libgif-dev \
    librsvg2-dev \
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
