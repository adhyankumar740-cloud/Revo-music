from BROKENXMUSIC.core.bot import Broken
from BROKENXMUSIC.core.dir import dirr
from BROKENXMUSIC.core.git import git
from BROKENXMUSIC.core.userbot import Userbot
from BROKENXMUSIC.misc import dbb, heroku

from .logging import LOGGER

dirr()
git()
dbb()
heroku()

app = Broken()
userbot = Userbot()


from .platforms import *

Apple = AppleAPI()
Carbon = CarbonAPI()
SoundCloud = SoundAPI()
Spotify = SpotifyAPI()
Resso = RessoAPI()
Telegram = TeleAPI()
YouTube = YouTubeAPI()
