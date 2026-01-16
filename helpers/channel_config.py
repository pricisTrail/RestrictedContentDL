# Copyright (C) @TheSmartBisnu
# Channel: https://t.me/itsSmartDev

import json
import os
from config import PyroConf
from logger import LOGGER

CONFIG_FILE = "channel_settings.json"

def load_channel_config():
    """Load channel configuration from JSON file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                return config.get("forward_channel_id", PyroConf.FORWARD_CHANNEL_ID)
    except Exception as e:
        LOGGER(__name__).error(f"Error loading channel config: {e}")
    return PyroConf.FORWARD_CHANNEL_ID


def save_channel_config(channel_id: int):
    """Save channel configuration to JSON file"""
    try:
        config = {"forward_channel_id": channel_id}
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        LOGGER(__name__).info(f"Channel config saved: {channel_id}")
        return True
    except Exception as e:
        LOGGER(__name__).error(f"Error saving channel config: {e}")
        return False


def get_forward_channel_id():
    """Get the current forward channel ID (from JSON or config.env fallback)"""
    return load_channel_config()


def set_forward_channel_id(channel_id: int):
    """Set the forward channel ID"""
    return save_channel_config(channel_id)


def is_channel_forwarding_enabled():
    """Check if channel forwarding is enabled"""
    return get_forward_channel_id() != 0
