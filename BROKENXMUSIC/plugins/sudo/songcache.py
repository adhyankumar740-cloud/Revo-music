from pyrogram import filters

import config
from BROKENXMUSIC import SongCache, app
from BROKENXMUSIC.misc import SUDOERS


@app.on_message(filters.command(["indexcache", "buildcache"]) & SUDOERS)
async def index_song_cache(_, message):
    if not config.SONG_CACHE_SOURCE_CHANNELS:
        return await message.reply_text(
            "⚠️ No `SONG_CACHE_SOURCE_CHANNELS` configured. Set that env var "
            "to a comma-separated list of your channel ids/usernames first."
        )

    status = await message.reply_text(
        f"🔎 Indexing {len(config.SONG_CACHE_SOURCE_CHANNELS)} channel(s)... "
        f"this can take a while for large channels."
    )
    try:
        total = await SongCache.index_channels()
    except Exception as e:
        return await status.edit_text(f"❌ Indexing failed: `{e}`")

    await status.edit_text(f"✅ Indexed **{total}** tracks into the song cache.")
