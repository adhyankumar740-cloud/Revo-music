import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        # Capped at 5MB x 2 backups instead of an unbounded log.txt that
        # just grows forever and eats into Render's disk quota over time.
        RotatingFileHandler("log.txt", maxBytes=5 * 1024 * 1024, backupCount=2),
        logging.StreamHandler(),
    ],
)

logging.getLogger("httpx").setLevel(logging.ERROR)
# NOTE: was ERROR — that silently ate pyrogram's FloodWait "Sleeping for Xs"
# warnings, which made long operations (like /indexcache on a big channel)
# look completely stuck with zero log output. WARNING keeps normal pyrogram
# noise down but still surfaces FloodWait sleeps.
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pytgcalls").setLevel(logging.ERROR)


def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
