from pyrogram import filters
from BROKENXMUSIC import app
import asyncio

link = "https://telegra.ph/file/522b3538da93c082b62dd.mp4"
text = "🙄👉🏻 ᴅᴏɴ'ᴛ ᴡᴀᴛᴄʜ ᴛʜɪs 👈🏻🙄\n"
repo = "https://github.com/mrxbroken011/BROKEN-X-MUSIC/fork"

@app.on_message(filters.command("repo"))
async def start(_, msg):
    brokn = await msg.reply_text("<b>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ..ɢᴇᴛᴛɪɴɢ ɢɪᴛʜᴜʙ ʟɪɴᴋ</b>")
    
    await asyncio.sleep(5)
    await brokn.edit("<b>ᴘʀᴏᴄᴇssɪɴɢ...</b>")
    
    await asyncio.sleep(4)
    await brokn.edit("<b>ʟᴏᴀᴅɪɴɢ.....</b>")
    
    await asyncio.sleep(6)
    await brokn.edit("<b>ᴀʙʜɪ ʙʜɪ ʏᴀʜɪ ʜᴀɪ ʙᴇsʜᴀʀᴀᴍ ʀᴜᴋᴊᴀ 𝟷𝟶 sᴇᴄᴏɴᴅ ᴀᴜʀ!!!...</b>")
    
    await asyncio.sleep(8)
    await brokn.delete()
    
    await app.send_video(
        chat_id=msg.chat.id, 
        video=link, 
        caption=f"<b>{text}</b>[❤‍🔥GIT REPO]({repo})", 
        has_spoiler=True
    )
