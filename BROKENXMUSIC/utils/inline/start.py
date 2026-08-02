from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton
import config
from BROKENXMUSIC import app


def start_panel(_):
    buttons = [
        [
            InlineKeyboardButton(
                text=_["S_B_1"], url=f"https://t.me/{app.username}?startgroup=true", style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(text=_["S_B_2"], url=config.SUPPORT_CHAT, style=ButtonStyle.PRIMARY),
        ],
    ]
    return buttons


def private_panel(_):
    buttons = [
        [
            InlineKeyboardButton(
                text=_["S_B_3"],
                url=f"https://t.me/{app.username}?startgroup=true",
                style=ButtonStyle.SUCCESS,
            )
        ],
        [
            InlineKeyboardButton(text=_["S_B_4"], callback_data="settings_back_helper", style=ButtonStyle.PRIMARY),
        ],
        [
            InlineKeyboardButton(text=_["S_B_6"], url=f"tg://user?id={config.OWNER_ID}", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text=_["S_B_5"], url=config.SUPPORT_CHANNEL, style=ButtonStyle.PRIMARY),
        ],
     ]
    return buttons
