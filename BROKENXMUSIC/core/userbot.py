from pyrogram import Client

import config

from ..logging import LOGGER

assistants = []
assistantids = []


async def _warm_dialogs(client, label):
    """Pyrogram can't resolve a bare chat/channel ID it hasn't 'seen' yet in
    this session (it needs the peer's access_hash). Assistants run with
    no_updates=True so that never happens passively from incoming updates —
    walk get_dialogs() once at startup so every channel this account is in
    (song-cache source/cache channels included) is resolvable right away,
    instead of a live /play command stalling on this the first time it
    needs one of those channels."""
    try:
        async for _ in client.get_dialogs():
            pass
        LOGGER(__name__).info(f"Warmed dialog cache for {label}")
    except Exception as e:
        LOGGER(__name__).error(f"Failed to warm dialog cache for {label}: {e}")


class Userbot(Client):
    def __init__(self):
        self.one = Client(
            name="Brokenxass1",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING1),
            no_updates=True,
            workers=1,
        )
        self.two = Client(
            name="Brokenxass2",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING2),
            no_updates=True,
            workers=1,
        )
        self.three = Client(
            name="Brokenxass3",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING3),
            no_updates=True,
            workers=1,
        )
        self.four = Client(
            name="Brokenxass4",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING4),
            no_updates=True,
            workers=1,
        )
        self.five = Client(
            name="Brokenxass5",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING5),
            no_updates=True,
            workers=1,
        )

    async def start(self):
        LOGGER(__name__).info(f"Starting Assistants...")
        if config.STRING1:
            await self.one.start()
            try:
                await self.one.join_chat("BROKNXSUPPORT")
                await self.one.join_chat("BROKENXNETWORK1")
                await self.one.join_chat("ABOUTBROKENX")
            except:
                pass
            await _warm_dialogs(self.one, "Assistant 1")
            assistants.append(1)
            try:
                await self.one.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 1 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin!"
                )
                exit()
            self.one.id = self.one.me.id
            self.one.name = self.one.me.mention
            self.one.username = self.one.me.username
            assistantids.append(self.one.id)
            LOGGER(__name__).info(f"Assistant Started as {self.one.name}")

        if config.STRING2:
            await self.two.start()
            try:
                await self.two.join_chat("BROKNXSUPPORT")
                await self.two.join_chat("BROKENXNETWORK1")
                await self.two.join_chat("ABOUTBROKENX")
            except:
                pass
            await _warm_dialogs(self.two, "Assistant 2")
            assistants.append(2)
            try:
                await self.two.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 2 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin!"
                )
                exit()
            self.two.id = self.two.me.id
            self.two.name = self.two.me.mention
            self.two.username = self.two.me.username
            assistantids.append(self.two.id)
            LOGGER(__name__).info(f"Assistant Two Started as {self.two.name}")

        if config.STRING3:
            await self.three.start()
            try:
                await self.three.join_chat("BROKNXSUPPORT")
                await self.three.join_chat("BROKENXNETWORK1")
                await self.three.join_chat("ABOUTBROKENX")
            except:
                pass
            await _warm_dialogs(self.three, "Assistant 3")
            assistants.append(3)
            try:
                await self.three.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 3 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.three.id = self.three.me.id
            self.three.name = self.three.me.mention
            self.three.username = self.three.me.username
            assistantids.append(self.three.id)
            LOGGER(__name__).info(f"Assistant Three Started as {self.three.name}")

        if config.STRING4:
            await self.four.start()
            try:
                await self.four.join_chat("BROKNXSUPPORT")
                await self.four.join_chat("BROKENXNETWORK1")
                await self.four.join_chat("ABOUTBROKENX")
            except:
                pass
            await _warm_dialogs(self.four, "Assistant 4")
            assistants.append(4)
            try:
                await self.four.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 4 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.four.id = self.four.me.id
            self.four.name = self.four.me.mention
            self.four.username = self.four.me.username
            assistantids.append(self.four.id)
            LOGGER(__name__).info(f"Assistant Four Started as {self.four.name}")

        if config.STRING5:
            await self.five.start()
            try:
                await self.five.join_chat("BROKNXSUPPORT")
                await self.five.join_chat("BROKENXNETWORK1")
                await self.five.join_chat("ABOUTBROKENX")
            except:
                pass
            await _warm_dialogs(self.five, "Assistant 5")
            assistants.append(5)
            try:
                await self.five.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 5 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.five.id = self.five.me.id
            self.five.name = self.five.me.mention
            self.five.username = self.five.me.username
            assistantids.append(self.five.id)
            LOGGER(__name__).info(f"Assistant Five Started as {self.five.name}")

    async def stop(self):
        LOGGER(__name__).info(f"Stopping Assistants...")
        try:
            if config.STRING1:
                await self.one.stop()
            if config.STRING2:
                await self.two.stop()
            if config.STRING3:
                await self.three.stop()
            if config.STRING4:
                await self.four.stop()
            if config.STRING5:
                await self.five.stop()
        except:
            pass
