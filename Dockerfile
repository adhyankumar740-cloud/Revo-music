FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    unzip \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs an external JS runtime to solve YouTube's challenge and get
# real (non-image-only) formats — see https://github.com/yt-dlp/yt-dlp/wiki/EJS.
# It only auto-detects "deno" by default (installed Node.js alone is NOT
# picked up automatically), so install deno here and put it on PATH.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"

# --- PO Token provider (bgutil-ytdlp-pot-provider) --------------------------
# Fixes the root cause of the "Sign in to confirm you're not a bot" errors:
# YouTube wants a PO (Proof-of-Origin) token as attestation that a request
# comes from a real client. Without one, this server's IP gets bot-flagged
# and android_vr/web clients get rejected, forcing the slow JS-challenge
# fallback tier every time. This runs as a small internal Node.js HTTP
# server (127.0.0.1:4416, never exposed publicly) that generates real POT
# tokens; yt-dlp's Python plugin (installed via requirements.txt) picks it
# up automatically at its default address — no extra yt-dlp options needed
# anywhere in the bot's own code.
RUN npm install -g yarn \
    && git clone --depth 1 --branch 0.6.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && yarn install --frozen-lockfile \
    && npx tsc

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
# (The bgutil POT provider above is a DIFFERENT Node.js process, kept —
# that one's actively used now.)

CMD bash start.sh
