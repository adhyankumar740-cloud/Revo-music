from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_DB_URI

from ..logging import LOGGER

LOGGER(__name__).info("Connecting to your Mongo Database...")
try:
    # Default driver pool size (100) is built for a busy multi-instance
    # service — a single small music bot never needs that many concurrent
    # connections, and each one costs memory (its own socket + buffers).
    _mongo_async_ = AsyncIOMotorClient(MONGO_DB_URI, maxPoolSize=10)
    mongodb = _mongo_async_.BROKN
    LOGGER(__name__).info("Connected to your Mongo Database.")
except:
    LOGGER(__name__).error("Failed to connect to your Mongo Database.")
    exit()
