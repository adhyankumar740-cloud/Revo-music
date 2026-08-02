from BROKENXMUSIC.core.bot import Broken
from BROKENXMUSIC.core.dir import dirr
from BROKENXMUSIC.core.userbot import Userbot
from BROKENXMUSIC.misc import dbb, heroku

from .logging import LOGGER
dirr()
dbb()
heroku()

app = Broken()
userbot = Userbot()


from .platforms import *

Apple = AppleAPI()
Carbon = CarbonAPI()
SoundCloud = SoundAPI()
TgScrap = TgScrapAPI()
SongCache = SongCacheAPI()


class _CDNCacheStub:
    """Placeholder: the CDN Cache feature isn't implemented yet. Guarded
    behind config.ENABLE_CDN_CACHE (default False), so these no-ops are
    never actually reached in play.py."""

    async def get(self, query):
        return None

    async def add(self, query, filepath, title, duration_min):
        return None


CDNCache = _CDNCacheStub()
Spotify = SpotifyAPI()
Resso = RessoAPI()
Telegram = TeleAPI()
YouTube = YouTubeAPI()
