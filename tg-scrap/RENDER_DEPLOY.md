# Telegram Channel Downloader — Render Web Service Guide

This is your original repo (`abhishekjnvk/telegram-channel-downloader`) with
small changes so it can run as a **Render Web Service** using your
**existing string session** (no OTP/interactive login on the server), plus
a small Express layer (`server.js`) on top of the same download code the CLI
uses.

The original CLI (`npm start`, `node cli.js ...`) still works exactly as
before if you ever want to run it locally.

## What changed in the code (and why)

| File | Change |
|---|---|
| `utils/paths.js` (new) | `EXPORT_DIR` now reads from an env var, so Render can point it at a persistent disk instead of a hardcoded `./export` folder. |
| `utils/file-helper.js` | Credentials (`apiId`, `apiHash`, `sessionId`) are read from env vars when present, instead of requiring `config.json` (Render has no local file with your secrets). |
| `modules/dialoges.js` | `getDialogName` no longer force-exits the process on first run — it resolves the channel name directly from Telegram if a cached list isn't there yet. Needed because a server can't do the CLI's "run once to build a list, run again to actually download" dance. |
| `scripts/download-channel.js` | `handle()` can now accept an already-connected `client` and an `exitProcess: false` flag, so the web server can download several channels back-to-back without reconnecting or killing its own process. |
| `server.js` (new) | Express server exposing `/download`, `/status`, `/dialogs`. |

## 1. Environment variables to set on Render

Go to your Render service → **Environment** → add these:

| Key | Value | Notes |
|---|---|---|
| `TELEGRAM_API_ID` | your api id | from https://my.telegram.org/apps |
| `TELEGRAM_API_HASH` | your api hash | from https://my.telegram.org/apps |
| `TELEGRAM_SESSION` | your existing string session | since you already have this, no OTP step happens |
| `CHANNELS` | e.g. `channel1,channel2,channel3,channel4,channel5` | comma separated usernames/ids of your 4-5 channels |
| `APP_SECRET` | any random string you invent | required as the `x-api-key` header to trigger a download |
| `EXPORT_DIR` | `/data/export` | only works if you attach a Persistent Disk (see below) |
| `PORT` | leave unset | Render sets this automatically |

## 2. Persistent disk (important)

Render's default filesystem is **wiped on every deploy/restart**. To keep
downloaded files:

1. Render dashboard → your service → **Disks** → **Add Disk**
2. Mount path: `/data`
3. Keep `EXPORT_DIR=/data/export`

This is a paid Render feature. Without it, download the files off Render
soon after each run (e.g. via the `/status` endpoint + manually copying, or
just treat each run as temporary and download-then-move).

## 3. Deploy steps

1. Push this whole folder to a GitHub repo.
2. Render → **New** → **Web Service** → connect the repo.
3. Build command: `npm install`
4. Start command: `npm run server`
5. Add the environment variables from step 1.
6. Deploy.

## 4. Using it once deployed

**Find your exact channel usernames/ids** (optional, if unsure):
```bash
curl https://your-service.onrender.com/dialogs -H "x-api-key: your-app-secret"
```

**Start downloading your 4-5 channels in one call:**
```bash
curl -X POST https://your-service.onrender.com/download \
  -H "x-api-key: your-app-secret"
```
This uses the `CHANNELS` env var. To override per-request instead:
```bash
curl -X POST https://your-service.onrender.com/download \
  -H "x-api-key: your-app-secret" \
  -H "Content-Type: application/json" \
  -d '{"channels": ["channel1","channel2","channel3"]}'
```

**Check progress:**
```bash
curl https://your-service.onrender.com/status
```

## Notes

- Each `/download` call processes all listed channels one after another
  (fully downloads channel 1, then channel 2, etc.) and downloads **every**
  media message in each channel — same as running the CLI. Large channels
  can take a long time.
- Only one job runs at a time, to stay within Telegram's rate limits.
- Never commit `.env` or `config.json` — only set secrets through Render's
  Environment tab. `TELEGRAM_SESSION` gives full access to your Telegram
  account; treat it like a password.
- Free Render web services can sleep after inactivity; a mid-download
  restart will stop the current job (already-downloaded files are kept if
  you attached a persistent disk — just call `/download` again to resume,
  since each channel restarts from where its message offset tracking left
  off). If you need guaranteed long unattended runs, a Render **Background
  Worker** is a more natural fit than a Web Service, but this setup works
  fine for triggering downloads on demand.

---

## Original project README (unchanged, for reference)

See `Readme.md` for the original local/CLI setup instructions.
