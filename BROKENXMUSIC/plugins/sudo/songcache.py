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

    # Optional: /indexcache 500  -> scan only 500 msgs/channel this run.
    # /indexcache 0 -> no limit (old, can-be-slow-and-flood-prone behaviour).
    # No number -> use config.SONG_CACHE_INDEX_LIMIT (default 1000).
    limit_per_channel = None
    if len(message.command) > 1 and message.command[1].isdigit():
        limit_per_channel = int(message.command[1])

    effective_limit = (
        limit_per_channel if limit_per_channel is not None else config.SONG_CACHE_INDEX_LIMIT
    )
    status = await message.reply_text(
        f"🔎 Indexing {len(config.SONG_CACHE_SOURCE_CHANNELS)} channel(s), "
        f"up to {effective_limit or 'unlimited'} messages/channel... "
        f"this can take a while for large channels.\n\n"
        f"If it looks stuck, check `log.txt` on the server for "
        f"`[SongCache]` and `FloodWait` lines — large channels can hit "
        f"Telegram rate limits and pause for a while, that's expected."
    )
    try:
        total = await SongCache.index_channels(limit_per_channel=limit_per_channel)
    except Exception as e:
        return await status.edit_text(f"❌ Indexing failed: `{e}`")

    note = (
        "\n\nRun `/indexcache` again to continue scanning further back."
        if effective_limit
        else ""
    )
    await status.edit_text(f"✅ Indexed **{total}** tracks into the song cache.{note}")
