# Copyright (C) @TheSmartBisnu
# Channel: https://t.me/itsSmartDev

from os import getenv
from time import time
from dotenv import load_dotenv

try:
    load_dotenv("config.env")
except:
    pass

# Validate bot token
if not getenv("BOT_TOKEN") or not getenv("BOT_TOKEN").count(":") == 1:
    print("Error: BOT_TOKEN must be in format '123456:abcdefghijklmnopqrstuvwxyz'")
    exit(1)


# Pyrogram setup
class PyroConf(object):
    API_ID = int(getenv("API_ID", "6"))
    API_HASH = getenv("API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e")
    BOT_TOKEN = getenv("BOT_TOKEN")
    
    # SESSION_STRING is now optional - sessions can be created via /login command
    SESSION_STRING = getenv("SESSION_STRING", "")
    
    # MongoDB URI for storing user sessions (required for multi-user support)
    MONGO_URI = getenv("MONGO_URI", "")
    
    BOT_START_TIME = time()

    # Admin user ID to receive startup notifications (your Telegram user ID)
    ADMIN_ID = int(getenv("ADMIN_ID", "0"))

    # Max parallel downloads/uploads (higher = faster but more resource usage)
    MAX_CONCURRENT_TRANSMISSIONS = int(getenv("MAX_CONCURRENT_TRANSMISSIONS", "3"))
    BATCH_SIZE = int(getenv("BATCH_SIZE", "10"))
    FLOOD_WAIT_DELAY = int(getenv("FLOOD_WAIT_DELAY", "3"))

    # Forward channel configuration - Bot must be admin in this channel
    FORWARD_CHANNEL_ID = int(getenv("FORWARD_CHANNEL_ID", "0"))

    # Bin channel - ALL media gets forwarded here as backup (regardless of FORWARD_CHANNEL_ID)
    # Bot must be admin in this channel
    BIN_CHANNEL_ID = int(getenv("BIN_CHANNEL_ID", "0"))

