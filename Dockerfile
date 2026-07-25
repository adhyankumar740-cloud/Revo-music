FROM node:18-bullseye-slim AS node
FROM python:3.10-slim

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules

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

# tg-scrap (Node.js Telegram channel downloader) dependencies
RUN cd tg-scrap && npm install --omit=dev

#if deploying as web services on Render or any other web service go for render branch 
CMD bash start.sh

#if deploying with vps or heroku 
#CMD bash start
