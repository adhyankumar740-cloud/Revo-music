import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        logging.FileHandler("log.txt"),
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
