# Deployment Guide — Broken ✘ Music

This document provides **complete, production-grade deployment guidance** for Broken ✘ Music across VPS, Docker, and major cloud platforms.

Please read this file fully before deploying.

--- 

## General Deployment Rules (Must Read)

- Always **fork the repository** before deploying.
- Never hardcode secrets in source code.
- Never push `.env`, API keys, or session strings to GitHub.
- Monitor logs after deployment.
- You are responsible for compliance with platform policies.

Failure to follow these rules can result in service suspension or account restrictions.

---

## Required Before Deployment

You must have the following ready:

- Telegram `API_ID` & `API_HASH`
- Telegram Bot Token
- Telegram User String Session
- MongoDB URI
- Custom YouTube API Key [Get From Here](https://t.me/aboutbrokenx) 
- ffmpeg available in runtime

All values must be set using **environment variables only**.

---

## Environment Variable Template

```
API_ID=
API_HASH=
BOT_TOKEN=
OWNER_ID=
LOGGER_ID=
MONGO_DB_URI=
STRING_SESSION=

YTAPIURL=https://mrbroken-brokenxbots.hf.space
YTKEY=[GET](https://t.me/aboutbrokenx) 
```

⚠️ Never expose these values publicly.

---

## One-Click Cloud Deployments

> Recommended for quick setup and testing.  
> Not ideal for heavy production traffic.

### Heroku
<a href="https://dashboard.heroku.com/new?template=https://github.com/mrxbroken011/BROKEN-X-MUSIC">
<img src="https://img.shields.io/badge/Deploy-Heroku-purple?style=for-the-badge&logo=heroku"/>
</a>

**Notes**
- Free tier may sleep
- ffmpeg buildpack required
- Logs reset on dyno restart

---

### Render
<a href="https://render.com/deploy?repo=https://github.com/mrxbroken011/BROKEN-X-MUSIC">
<img src="https://img.shields.io/badge/Deploy-Render-white?style=for-the-badge&logo=render&logoColor=black"/>
</a>

**Notes**
- Suitable for small to medium usage
- Configure environment variables manually
- Ensure background worker mode

---

### Railway
<a href="https://railway.app/new/template?template=https://github.com/mrxbroken011/BROKEN-X-MUSIC">
<img src="https://img.shields.io/badge/Deploy-Railway-0b0d16?style=for-the-badge&logo=railway"/>
</a>

**Notes**
- Fast setup
- Resource-based billing
- Monitor usage carefully

---

### Koyeb
<a href="https://app.koyeb.com/deploy?type=git&repository=github.com/mrxbroken011/BROKEN-X-MUSIC">
<img src="https://img.shields.io/badge/Deploy-Koyeb-black?style=for-the-badge&logo=koyeb"/>
</a>

**Notes**
- Good global latency
- Requires correct service type
- ffmpeg must be available

---

## VPS Deployment (Recommended for Production)

Best choice for **stability, performance, and control**.

### Minimum Requirements
- Ubuntu 20.04+
- 1 GB RAM (2 GB recommended)
- Python 3.9+
- ffmpeg installed

### Basic Steps (High Level)

1. Update system
2. Install dependencies
3. Clone your fork
4. Create virtual environment
5. Install requirements
6. Start bot using `tmux` or `systemd`

### Why VPS is Recommended
- No sleep
- Full control
- Better audio stability
- No forced rate limits

---

## Docker Deployment (Advanced / Recommended)

Docker is ideal if you want:
- Isolation
- Easy restarts
- Predictable runtime

### Docker Compose (Preferred)

Start with:
```
docker-compose up -d
```

### Warnings
- Do not bake secrets into the image
- Use `.env` only
- Monitor logs with `docker logs`

---

## Platform Comparison

| Platform | Stability | Recommended |
|--------|----------|-------------|
| VPS | ⭐⭐⭐⭐⭐ | Yes (Production) |
| Docker VPS | ⭐⭐⭐⭐⭐ | Yes |
| Heroku | ⭐⭐ | Testing only |
| Render | ⭐⭐⭐ | Light usage |
| Railway | ⭐⭐⭐ | Medium usage |
| Koyeb | ⭐⭐⭐ | Medium usage |

---

## Common Deployment Mistakes

- Missing ffmpeg
- Exposed `.env`
- Wrong API key
- Using cookies on cloud
- Running without background process

Avoiding these will save significant debugging time.

---

## Final Responsibility Notice

This project is provided as a technical tool.

You are solely responsible for:
- Deployment
- Usage
- Policy compliance
- Resource management

Deploy responsibly.

---

© 2025 Broken ✘ Network
