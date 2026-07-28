import re
from os import getenv

from dotenv import load_dotenv
from pyrogram import filters

load_dotenv()


API_ID = int(getenv("API_ID")) # ⚠️ fill here or in .env
API_HASH = getenv("API_HASH", "") # ⚠️ fill here or in .env

# Get your token from @BotFather on Telegram.
BOT_TOKEN = getenv("BOT_TOKEN", "") # ⚠️ fill here or in .env
BOT_USERNAME = ("BOT_USERNAME", "") # ⚠️ fill here or in .env
# Get your mongo url from cloud.mongodb.com
MONGO_DB_URI = getenv("MONGO_DB_URI", "") # ⚠️ fill here or in .env

DURATION_LIMIT_MIN = int(getenv("DURATION_LIMIT", 19000))

# ⚠️ Tg-Scrap: auto-download+play a song via a VK Music Telegram bot before falling back to YouTube
ENABLE_TG_SCRAP_PLAY = getenv("ENABLE_TG_SCRAP_PLAY", "True").lower() == "true"
VK_MUSIC_BOT = getenv("VK_MUSIC_BOT", "vkmusic_bot")
TG_SCRAP_MENU_TIMEOUT = int(getenv("TG_SCRAP_MENU_TIMEOUT", 15))  # wait for the bot's results menu
TG_SCRAP_TIMEOUT = int(getenv("TG_SCRAP_TIMEOUT", 30))  # wait for the audio file after clicking
TG_SCRAP_MAX_MENU_HOPS = int(getenv("TG_SCRAP_MAX_MENU_HOPS", 3))  # nested menus to click through

# How long (seconds) YouTube.race_download() lets the direct HF-resolver
# path run alone before it wakes vkmusic_bot up at all. Raise this if
# direct is winning fast but you still see occasional slow songs falling
# through late; lower it if you'd rather have TgScrap start earlier as a
# safety net at the cost of hitting vkmusic_bot more often.
RACE_DIRECT_HEAD_START = float(getenv("RACE_DIRECT_HEAD_START", 4))

# ⚠️ Your own archived channels (the ones you've been building up for years).
# Comma separated list of usernames / numeric chat ids, e.g.
# "mymusicarchive,-1001234567890,another_channel"
# These are searched FIRST before ever touching the VK Music bot.
def _normalize_channel(c):
    c = c.strip()
    try:
        return int(c)  # numeric channel ids (e.g. -1001234567890) need to be int
    except ValueError:
        return c  # usernames stay as strings

SONG_CACHE_SOURCE_CHANNELS = [
    _normalize_channel(c) for c in getenv("SONG_CACHE_SOURCE_CHANNELS", "").split(",") if c.strip()
]

# Song Cache: turns your source channels + this single auto-growing channel
# into a fast MongoDB-indexed local library (see BROKENXMUSIC/platforms/SongCache.py).
# Every song freshly pulled via TgScrap gets uploaded here and indexed, so the
# next request for it is an instant file_id-based hit — no re-download.
ENABLE_SONG_CACHE = getenv("ENABLE_SONG_CACHE", "False").lower() == "true"

# ⚠️ Fast-path: resolve/download audio via the external HF Space (yt-dlp
# running server-side, see HF_RESOLVER_URL below) BEFORE falling back to
# TgScrap. This is what makes the "live-stream hit (no download wait)" path
# in the logs work.
ENABLE_YTDLP_DIRECT_AUDIO = getenv("ENABLE_YTDLP_DIRECT_AUDIO", "False").lower() == "true"

# --- Fast external resolver (HF Space running yt-dlp) -----------------------
# Tried FIRST, before any local tier — typically resolves in 2-4s vs 15-20s
# on Render's free CPU. If it's unreachable, times out, or fails, the bot
# transparently falls back to the local tiers below, so this is purely an
# accelerator and never a single point of failure.
# Example: https://your-username-your-space.hf.space/api/resolve
HF_RESOLVER_URL = getenv("HF_RESOLVER_URL", "").strip().rstrip("/")
HF_RESOLVER_TIMEOUT = float(getenv("HF_RESOLVER_TIMEOUT", 8))
HF_RESOLVER_DOWNLOAD_TIMEOUT = float(getenv("HF_RESOLVER_DOWNLOAD_TIMEOUT", 60))
# /api/resolve occasionally gets a transient non-JSON response from the HF
# Space (cold-start holding page, brief redeploy, edge hiccup) even while the
# Space is otherwise healthy. Retry a couple of times with a short delay
# before giving up and falling back to the local tiers.
HF_RESOLVER_RETRIES = int(getenv("HF_RESOLVER_RETRIES", 2))
HF_RESOLVER_RETRY_DELAY = float(getenv("HF_RESOLVER_RETRY_DELAY", 1.5))
# Must match the RESOLVER_API_KEY secret set on the HF Space.
HF_RESOLVER_API_KEY = getenv("HF_RESOLVER_API_KEY", "").strip()
# CDN Cache is an unfinished feature (no CDNCache module exists yet) — keep off.
ENABLE_CDN_CACHE = getenv("ENABLE_CDN_CACHE", "False").lower() == "true"
_raw_song_cache_channel = getenv("SONG_CACHE_CHANNEL", "").strip()
SONG_CACHE_CHANNEL = _normalize_channel(_raw_song_cache_channel) if _raw_song_cache_channel else None

# Default cap on how many messages /indexcache scans per channel per run.
# Scanning a huge channel's *entire* history in one unlimited pass is what
# was triggering long, invisible FloodWait sleeps. 0 = no limit (old
# behaviour) — override per-run with "/indexcache <number>".
SONG_CACHE_INDEX_LIMIT = int(getenv("SONG_CACHE_INDEX_LIMIT", 1000))
# Optional: pin ONE assistant (1-5) to always handle /indexcache, so a big
# indexing run never competes with live /play requests for the same
# account. Leave unset to use the old "just grab whichever assistant"
# behaviour. Only matters if you run 2+ assistants (STRING1 + STRING2 ...).
SONG_CACHE_INDEX_ASSISTANT = getenv("SONG_CACHE_INDEX_ASSISTANT")
SONG_CACHE_INDEX_ASSISTANT = (
    int(SONG_CACHE_INDEX_ASSISTANT) if SONG_CACHE_INDEX_ASSISTANT and SONG_CACHE_INDEX_ASSISTANT.isdigit() else None
)

# Optional: dedicate ONE assistant purely to joining voice chats + actually
# streaming audio into them. That account's Pyrogram connection is then
# NEVER used for TgScrap (VK-bot scraping) or SongCache file fetching/
# indexing — those all run on the OTHER assistants instead (round-robin
# across whichever ones are left, see SongCache._live_pool).
# Default is OFF ("") — every group gets a RANDOMLY assigned assistant for
# playback, so with 5 assistants configured, playback load spreads across
# all 5 instead of funneling every group through a single account. Set this
# to a number (1-5) only if you specifically want one assistant reserved
# purely for playback and never for scraping/fetching.
DEDICATED_PLAY_ASSISTANT = getenv("DEDICATED_PLAY_ASSISTANT", "")
DEDICATED_PLAY_ASSISTANT = (
    int(DEDICATED_PLAY_ASSISTANT) if DEDICATED_PLAY_ASSISTANT and DEDICATED_PLAY_ASSISTANT.isdigit() else None
)

# Local disk LRU cache: once a song (cache-channel hit OR a fresh VK-scrape)
# has been pulled once on this server, keep a copy on local disk so a
# repeat request for the same song skips Telegram entirely — no download,
# no network round-trip, just an instant local file. Oldest entries are
# evicted once the folder passes LOCAL_CACHE_MAX_MB.
LOCAL_CACHE_ENABLED = getenv("LOCAL_CACHE_ENABLED", "True").lower() == "true"
# Render free tier's disk is small + ephemeral (wiped on every restart) —
# 400MB keeps this a light bonus layer instead of competing with your app
# for the little disk space free tier gives you.
LOCAL_CACHE_MAX_MB = int(getenv("LOCAL_CACHE_MAX_MB", 400))

# Chat id of a group for logging bot's activities
LOGGER_ID = int(getenv("LOGGER_ID",-5466660938)) # ⚠️ fill here or in .env and ensure that bot and assistant bot are admin in log group 


OWNER_ID = int(getenv("OWNER_ID")) # ⚠️ fill here or in .env

## Fill these variables if you're deploying on heroku.
# Your heroku app name
HEROKU_APP_NAME = getenv("HEROKU_APP_NAME", None) # ⚠️ fill here or in .env if deploying on heroku
# Get it from http://dashboard.heroku.com/account
HEROKU_API_KEY = getenv("HEROKU_API_KEY", None) # ⚠️ fill here or in .env if deploying on heroku

SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/TimeStudios01") # ⚠️ fill Your channel link here
SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/+qZBUgJbCwYw5ZTJl") # ⚠️ fill Chat group link here

# Set this to True if you want the assistant to automatically leave chats after an interval
AUTO_LEAVING_ASSISTANT = bool(getenv("AUTO_LEAVING_ASSISTANT", False))


# Get this credentials from https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID = getenv("SPOTIFY_CLIENT_ID", "1c21247d714244ddbb09925dac565aed")
SPOTIFY_CLIENT_SECRET = getenv("SPOTIFY_CLIENT_SECRET", "709e1a2969664491b58200860623ef19")


# Maximum limit for fetching playlist's track from youtube, spotify, apple links.
PLAYLIST_FETCH_LIMIT = int(getenv("PLAYLIST_FETCH_LIMIT", 1000))



TG_AUDIO_FILESIZE_LIMIT = int(getenv("TG_AUDIO_FILESIZE_LIMIT", 104857600))
TG_VIDEO_FILESIZE_LIMIT = int(getenv("TG_VIDEO_FILESIZE_LIMIT", 1073741824))




STRING1 = getenv("STRING_SESSION", None) # ⚠️ fill in .env
STRING2 = getenv("STRING_SESSION2", None)
STRING3 = getenv("STRING_SESSION3", None)
STRING4 = getenv("STRING_SESSION4", None)
STRING5 = getenv("STRING_SESSION5", None)


BANNED_USERS = filters.user()
adminlist = {}
lyrical = {}
votemode = {}
autoclean = []
confirmer = {}

AYU = [
    "💞", "𝚃𝙷𝙸𝚂 𝚂𝙾𝙽𝙶 𝙸𝚂 𝚃𝙾𝚃𝙰𝙻𝙻𝚈 𝙵𝙰𝙱𝚄𝙻𝙰𝚂𝚃𝙸𝙲...🔥🥰", "🔍", "🧪", "ʜᴏʟᴅ ᴏɴ ᴅᴀʀʟɪɴɢ 💗", "⚡️", "🔥", "ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...❤‍🔥", "🎩", "🌈", "🍷", "🥂", "🥃", 
    "ᴀᴄᴄʜɪ ᴘᴀsᴀɴᴅ ʜᴀɪ 🥰", "ʟᴏᴏᴋɪɴɢ ғᴏʀ ʏᴏᴜʀ sᴏɴɢ... ᴡᴀɪᴛ! 💗", "🪄", "💌", "ᴏᴋ ʙᴀʙʏ ᴡᴀɪᴛ😘 ғᴇᴡ sᴇᴄᴏɴᴅs", "ᴀʜʜ! ɢᴏᴏᴅ ᴄʜᴏɪᴄᴇ ʜᴏʟᴅ ᴏɴ...",  
    "ᴡᴏᴡ! ɪᴛ's ᴍʏ ғᴀᴠᴏʀɪᴛᴇ sᴏɴɢ...", "ɴɪᴄᴇ ᴄʜᴏɪᴄᴇ..! ᴡᴀɪᴛ 𝟸 sᴇᴄᴏɴᴅ", "🔎", "🍹", "ɪ ʟᴏᴠᴇ ᴛʜᴀᴛ sᴏɴɢ..!😍", "💥", "💗", "✨"
]


# ⚠️ change images urls if you want to change 

START_IMG_URL = [
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
     "https://files.catbox.moe/2le6ng.png", 
]

PING_IMG_URL = getenv(
    "PING_IMG_URL", "https://files.catbox.moe/wcf1mg.png"
)
PLAYLIST_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
STATS_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
TELEGRAM_AUDIO_URL = "https://files.catbox.moe/wcf1mg.png"
TELEGRAM_VIDEO_URL = "https://files.catbox.moe/wcf1mg.png"
STREAM_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
SOUNCLOUD_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
YOUTUBE_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
SPOTIFY_ARTIST_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
SPOTIFY_ALBUM_IMG_URL = "https://files.catbox.moe/wcf1mg.png"
SPOTIFY_PLAYLIST_IMG_URL = "https://files.catbox.moe/wcf1mg.png"


def time_to_seconds(time):
    stringt = str(time)
    return sum(int(x) * 60**i for i, x in enumerate(reversed(stringt.split(":"))))


DURATION_LIMIT = int(time_to_seconds(f"{DURATION_LIMIT_MIN}:00"))


if SUPPORT_CHANNEL:
    if not re.match("(?:http|https)://", SUPPORT_CHANNEL):
        raise SystemExit(
            "[ERROR] - Your SUPPORT_CHANNEL url is wrong. Please ensure that it starts with https://"
        )

if SUPPORT_CHAT:
    if not re.match("(?:http|https)://", SUPPORT_CHAT):
        raise SystemExit(
            "[ERROR] - Your SUPPORT_CHAT url is wrong. Please ensure that it starts with https://"
        )
