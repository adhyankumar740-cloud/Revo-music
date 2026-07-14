from BROKENXMUSIC.core.bot import Broken
from BROKENXMUSIC.core.dir import dirr
from BROKENXMUSIC.core.git import git
from BROKENXMUSIC.core.userbot import Userbot
from BROKENXMUSIC.misc import dbb, heroku

from .logging import LOGGER

dirr()
# git() was unconditionally re-syncing this bot's code from the ORIGINAL
# upstream repo (config.UPSTREAM_REPO) on every single startup. On hosts
# like Render/Koyeb, this directory usually isn't a real git checkout, so
# git() falls into its "init a fresh repo + hard reset to upstream" branch -
# which silently overwrote all custom code (including the /stream relay)
# back to the stock upstream version on every restart. That's why edits
# kept reverting no matter how many times a redeploy was done.
# Only VPS-style deployments that intentionally want this self-update
# behavior should enable it, via AUTO_UPDATE=True in the environment.
import os as _os
if _os.getenv("AUTO_UPDATE", "False").lower() == "true":
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
