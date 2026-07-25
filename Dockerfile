FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
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
