import re
from os import getenv

from dotenv import load_dotenv
from pyrogram import filters

load_dotenv()


API_ID = int(getenv("API_ID", 35852042)) # ⚠️ fill here or in .env
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

# ⚠️ Your own archived channels (the ones you've been building up for years).
# Comma separated list of usernames / numeric chat ids, e.g.
# "mymusicarchive,-1001234567890,another_channel"
# These are searched FIRST before ever touching the VK Music bot.
SONG_CACHE_SOURCE_CHANNELS = [
    c.strip() for c in getenv("SONG_CACHE_SOURCE_CHANNELS", "").split(",") if c.strip()
]
OWN_CHANNEL_SEARCH_LIMIT = int(getenv("OWN_CHANNEL_SEARCH_LIMIT", 5))
# Warm-up index: how long (in hours) a cached index of SONG_CACHE_SOURCE_CHANNELS
# is considered fresh before it's rebuilt. 0 = never auto-refresh (only rebuilds
# if the cache file is missing or you call warm_up(force_refresh=True)).
MY_MUSIC_INDEX_TTL_HOURS = int(getenv("MY_MUSIC_INDEX_TTL_HOURS", 24))

# Chat id of a group for logging bot's activities
LOGGER_ID = int(getenv("LOGGER_ID", -1002094142057)) # ⚠️ fill here or in .env and ensure that bot and assistant bot are admin in log group 


OWNER_ID = int(getenv("OWNER_ID", 85060382471)) # ⚠️ fill here or in .env

## Fill these variables if you're deploying on heroku.
# Your heroku app name
HEROKU_APP_NAME = getenv("HEROKU_APP_NAME", None) # ⚠️ fill here or in .env if deploying on heroku
# Get it from http://dashboard.heroku.com/account
HEROKU_API_KEY = getenv("HEROKU_API_KEY", None) # ⚠️ fill here or in .env if deploying on heroku

UPSTREAM_REPO = getenv("UPSTREAM_REPO", "https://github.com/mrxbroken011/BROKEN-X-MUSIC.git")
UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "Master")
GIT_TOKEN = getenv("GIT_TOKEN", None)  # Fill this variable if your upstream repository is private

SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/+VSk-FT8RwWwzNDQ1") # ⚠️ fill Your channel link here
SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/+VSk-FT8RwWwzNDQ1") # ⚠️ fill Chat group link here

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
