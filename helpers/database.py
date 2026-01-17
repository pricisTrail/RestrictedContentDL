# Copyright (C) @TheSmartBisnu
# MongoDB Database Handler for Session Storage

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any
from logger import LOGGER

class Database:
    """MongoDB database handler for storing user sessions"""
    
    def __init__(self, mongo_uri: str, db_name: str = "telegram_bot"):
        self.mongo_uri = mongo_uri
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.sessions_collection = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(
                self.mongo_uri,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000
            )
            # Test connection
            await self.client.admin.command('ping')
            
            self.db = self.client[self.db_name]
            self.sessions_collection = self.db["user_sessions"]
            
            # Create index on user_id for faster lookups
            await self.sessions_collection.create_index("user_id", unique=True)
            
            self._connected = True
            LOGGER(__name__).info("Successfully connected to MongoDB")
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Failed to connect to MongoDB: {e}")
            self._connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            self._connected = False
            LOGGER(__name__).info("Disconnected from MongoDB")
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def save_session(self, user_id: int, session_string: str, phone_number: str = None) -> bool:
        """Save or update a user session"""
        try:
            await self.sessions_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "session_string": session_string,
                        "phone_number": phone_number,
                        "is_active": True
                    }
                },
                upsert=True
            )
            LOGGER(__name__).info(f"Session saved for user {user_id}")
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Failed to save session for user {user_id}: {e}")
            return False
    
    async def get_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user session by user ID"""
        try:
            session = await self.sessions_collection.find_one({"user_id": user_id})
            return session
        except Exception as e:
            LOGGER(__name__).error(f"Failed to get session for user {user_id}: {e}")
            return None
    
    async def get_active_session(self, user_id: int) -> Optional[str]:
        """Get active session string for a user"""
        session = await self.get_session(user_id)
        if session and session.get("is_active"):
            return session.get("session_string")
        return None
    
    async def delete_session(self, user_id: int) -> bool:
        """Delete a user session"""
        try:
            result = await self.sessions_collection.delete_one({"user_id": user_id})
            if result.deleted_count > 0:
                LOGGER(__name__).info(f"Session deleted for user {user_id}")
                return True
            return False
        except Exception as e:
            LOGGER(__name__).error(f"Failed to delete session for user {user_id}: {e}")
            return False
    
    async def deactivate_session(self, user_id: int) -> bool:
        """Deactivate a user session without deleting it"""
        try:
            result = await self.sessions_collection.update_one(
                {"user_id": user_id},
                {"$set": {"is_active": False}}
            )
            return result.modified_count > 0
        except Exception as e:
            LOGGER(__name__).error(f"Failed to deactivate session for user {user_id}: {e}")
            return False
    
    async def get_all_active_sessions(self) -> list:
        """Get all active sessions"""
        try:
            cursor = self.sessions_collection.find({"is_active": True})
            sessions = await cursor.to_list(length=None)
            return sessions
        except Exception as e:
            LOGGER(__name__).error(f"Failed to get active sessions: {e}")
            return []
    
    async def get_admin_session(self) -> Optional[str]:
        """Get admin session (first active session or env session)"""
        try:
            # First, try to get any active session
            session = await self.sessions_collection.find_one({"is_active": True})
            if session:
                return session.get("session_string")
            return None
        except Exception as e:
            LOGGER(__name__).error(f"Failed to get admin session: {e}")
            return None
    
    # ============ Bot Settings Methods ============
    
    async def save_setting(self, key: str, value: Any) -> bool:
        """Save a bot setting to the database"""
        try:
            settings_collection = self.db["bot_settings"]
            await settings_collection.update_one(
                {"key": key},
                {"$set": {"key": key, "value": value}},
                upsert=True
            )
            LOGGER(__name__).info(f"Setting saved: {key} = {value}")
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Failed to save setting {key}: {e}")
            return False
    
    async def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a bot setting from the database"""
        try:
            settings_collection = self.db["bot_settings"]
            setting = await settings_collection.find_one({"key": key})
            if setting:
                return setting.get("value", default)
            return default
        except Exception as e:
            LOGGER(__name__).error(f"Failed to get setting {key}: {e}")
            return default
    
    async def delete_setting(self, key: str) -> bool:
        """Delete a bot setting from the database"""
        try:
            settings_collection = self.db["bot_settings"]
            result = await settings_collection.delete_one({"key": key})
            if result.deleted_count > 0:
                LOGGER(__name__).info(f"Setting deleted: {key}")
                return True
            return False
        except Exception as e:
            LOGGER(__name__).error(f"Failed to delete setting {key}: {e}")
            return False


# Global database instance
db: Optional[Database] = None


async def init_database(mongo_uri: str) -> Database:
    """Initialize and return database instance"""
    global db
    db = Database(mongo_uri)
    await db.connect()
    return db


def get_database() -> Optional[Database]:
    """Get current database instance"""
    return db
