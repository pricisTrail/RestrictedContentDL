# Copyright (C) @TheSmartBisnu
# Session Manager for handling user login/logout with Pyrogram

import asyncio
from typing import Optional, Dict, Callable
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded, 
    PhoneCodeInvalid, 
    PhoneCodeExpired,
    PasswordHashInvalid,
    FloodWait,
    PhoneNumberInvalid,
    ApiIdInvalid
)
from helpers.database import get_database
from config import PyroConf
from logger import LOGGER


class LoginState:
    """Track login state for users"""
    IDLE = "idle"
    WAITING_PHONE = "waiting_phone"
    WAITING_CODE = "waiting_code"
    WAITING_PASSWORD = "waiting_password"


class SessionManager:
    """Manages user sessions and login flow"""
    
    def __init__(self):
        # Track login states: {user_id: {"state": state, "client": client, "phone": phone, "phone_code_hash": hash}}
        self.login_states: Dict[int, Dict] = {}
        # Active user clients: {user_id: Client}
        self.active_clients: Dict[int, Client] = {}
        # Primary client for downloads (admin or first logged in user)
        self.primary_client: Optional[Client] = None
        # Fallback to env session
        self.env_client: Optional[Client] = None
    
    async def initialize_env_session(self) -> bool:
        """Initialize client from environment SESSION_STRING if available"""
        if PyroConf.SESSION_STRING and PyroConf.SESSION_STRING != "xxxxxxxxxxxxxxxxxxxxxxx":
            try:
                self.env_client = Client(
                    "env_user_session",
                    workers=100,
                    session_string=PyroConf.SESSION_STRING,
                    max_concurrent_transmissions=1,
                    sleep_threshold=30,
                )
                await self.env_client.start()
                self.primary_client = self.env_client
                LOGGER(__name__).info("ENV session initialized successfully")
                return True
            except Exception as e:
                LOGGER(__name__).warning(f"Failed to initialize ENV session: {e}")
                self.env_client = None
        return False
    
    async def load_sessions_from_db(self) -> int:
        """Load all active sessions from database and start clients"""
        db = get_database()
        if not db or not db.is_connected:
            LOGGER(__name__).warning("Database not connected, cannot load sessions")
            return 0
        
        sessions = await db.get_all_active_sessions()
        loaded = 0
        
        for session_data in sessions:
            user_id = session_data.get("user_id")
            session_string = session_data.get("session_string")
            
            if user_id and session_string:
                try:
                    client = Client(
                        f"user_session_{user_id}",
                        workers=100,
                        session_string=session_string,
                        max_concurrent_transmissions=1,
                        sleep_threshold=30,
                    )
                    await client.start()
                    self.active_clients[user_id] = client
                    
                    # Set first loaded as primary if no primary exists
                    if not self.primary_client:
                        self.primary_client = client
                    
                    loaded += 1
                    LOGGER(__name__).info(f"Loaded session for user {user_id}")
                except Exception as e:
                    LOGGER(__name__).error(f"Failed to load session for user {user_id}: {e}")
                    # Mark session as inactive in DB
                    await db.deactivate_session(user_id)
        
        return loaded
    
    def get_primary_client(self) -> Optional[Client]:
        """Get the primary client for downloads"""
        return self.primary_client
    
    def get_user_client(self, user_id: int) -> Optional[Client]:
        """Get client for a specific user"""
        return self.active_clients.get(user_id)
    
    async def start_login(self, user_id: int) -> str:
        """Start login process for a user"""
        # Check if already logged in
        if user_id in self.active_clients:
            return "⚠️ **You are already logged in!**\n\nUse `/logout` first if you want to re-login."
        
        # Check if already in login process
        if user_id in self.login_states:
            state = self.login_states[user_id].get("state")
            if state == LoginState.WAITING_PHONE:
                return "📱 **Please send your phone number** (with country code).\n\nExample: `+1234567890`"
            elif state == LoginState.WAITING_CODE:
                return "🔐 **Please send the verification code** you received.\n\nExample: `12345`"
            elif state == LoginState.WAITING_PASSWORD:
                return "🔑 **Please send your 2FA password.**"
        
        # Start new login process
        self.login_states[user_id] = {
            "state": LoginState.WAITING_PHONE,
            "client": None,
            "phone": None,
            "phone_code_hash": None
        }
        
        return (
            "🔐 **Login to Telegram**\n\n"
            "Please send your **phone number** with country code.\n\n"
            "Example: `+1234567890`\n\n"
            "⚠️ **Note:** Your session will be stored securely in the database.\n"
            "Use `/cancel` to cancel the login process."
        )
    
    async def handle_phone_number(self, user_id: int, phone: str) -> str:
        """Handle phone number input during login"""
        if user_id not in self.login_states:
            return "❌ **No login session active.** Use `/login` to start."
        
        if self.login_states[user_id]["state"] != LoginState.WAITING_PHONE:
            return "❌ **Not waiting for phone number.**"
        
        # Clean phone number
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+" + phone
        
        try:
            # Create a new client for this login
            client = Client(
                f"login_temp_{user_id}",
                api_id=PyroConf.API_ID,
                api_hash=PyroConf.API_HASH,
                in_memory=True
            )
            
            await client.connect()
            
            # Send code
            sent_code = await client.send_code(phone)
            
            self.login_states[user_id].update({
                "state": LoginState.WAITING_CODE,
                "client": client,
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash
            })
            
            return (
                "✅ **Verification code sent!**\n\n"
                f"📱 Check your Telegram app or SMS for the code.\n\n"
                "Please send the **verification code** (digits only).\n\n"
                "Example: `12345`"
            )
            
        except PhoneNumberInvalid:
            return "❌ **Invalid phone number.** Please check and try again."
        except ApiIdInvalid:
            return "❌ **Invalid API credentials.** Contact the bot admin."
        except FloodWait as e:
            return f"⏳ **Please wait {e.value} seconds** before trying again."
        except Exception as e:
            LOGGER(__name__).error(f"Login error for user {user_id}: {e}")
            await self.cancel_login(user_id)
            return f"❌ **Error:** {str(e)}\n\nLogin cancelled. Use `/login` to try again."
    
    async def handle_verification_code(self, user_id: int, code: str) -> str:
        """Handle verification code input during login"""
        if user_id not in self.login_states:
            return "❌ **No login session active.** Use `/login` to start."
        
        state_data = self.login_states[user_id]
        if state_data["state"] != LoginState.WAITING_CODE:
            return "❌ **Not waiting for verification code.**"
        
        client = state_data["client"]
        phone = state_data["phone"]
        phone_code_hash = state_data["phone_code_hash"]
        
        # Clean code
        code = code.strip().replace(" ", "").replace("-", "")
        
        try:
            await client.sign_in(phone, phone_code_hash, code)
            
            # Successfully signed in - export session and save
            session_string = await client.export_session_string()
            
            # Save to database
            db = get_database()
            if db and db.is_connected:
                await db.save_session(user_id, session_string, phone)
            
            # Create permanent client
            perm_client = Client(
                f"user_session_{user_id}",
                workers=100,
                session_string=session_string,
                max_concurrent_transmissions=1,
                sleep_threshold=30,
            )
            await perm_client.start()
            
            # Disconnect temp client
            await client.disconnect()
            
            # Store in active clients
            self.active_clients[user_id] = perm_client
            
            # Set as primary if none exists
            if not self.primary_client:
                self.primary_client = perm_client
            
            # Clean up login state
            del self.login_states[user_id]
            
            user_info = await perm_client.get_me()
            
            return (
                "✅ **Login Successful!**\n\n"
                f"👤 **Logged in as:** {user_info.first_name or ''} {user_info.last_name or ''}\n"
                f"📱 **Phone:** `{phone}`\n\n"
                "Your session has been saved. You can now use the bot to download media!\n\n"
                "Use `/logout` to remove your session."
            )
            
        except SessionPasswordNeeded:
            self.login_states[user_id]["state"] = LoginState.WAITING_PASSWORD
            return (
                "🔐 **Two-Factor Authentication Required**\n\n"
                "Please send your **2FA password**.\n\n"
                "⚠️ Your password will not be stored."
            )
        except PhoneCodeInvalid:
            return "❌ **Invalid verification code.** Please check and try again."
        except PhoneCodeExpired:
            await self.cancel_login(user_id)
            return "❌ **Verification code expired.** Use `/login` to start again."
        except FloodWait as e:
            return f"⏳ **Please wait {e.value} seconds** before trying again."
        except Exception as e:
            LOGGER(__name__).error(f"Code verification error for user {user_id}: {e}")
            await self.cancel_login(user_id)
            return f"❌ **Error:** {str(e)}\n\nLogin cancelled. Use `/login` to try again."
    
    async def handle_2fa_password(self, user_id: int, password: str) -> str:
        """Handle 2FA password input during login"""
        if user_id not in self.login_states:
            return "❌ **No login session active.** Use `/login` to start."
        
        state_data = self.login_states[user_id]
        if state_data["state"] != LoginState.WAITING_PASSWORD:
            return "❌ **Not waiting for 2FA password.**"
        
        client = state_data["client"]
        phone = state_data["phone"]
        
        try:
            await client.check_password(password)
            
            # Successfully signed in - export session and save
            session_string = await client.export_session_string()
            
            # Save to database
            db = get_database()
            if db and db.is_connected:
                await db.save_session(user_id, session_string, phone)
            
            # Create permanent client
            perm_client = Client(
                f"user_session_{user_id}",
                workers=100,
                session_string=session_string,
                max_concurrent_transmissions=1,
                sleep_threshold=30,
            )
            await perm_client.start()
            
            # Disconnect temp client
            await client.disconnect()
            
            # Store in active clients
            self.active_clients[user_id] = perm_client
            
            # Set as primary if none exists
            if not self.primary_client:
                self.primary_client = perm_client
            
            # Clean up login state
            del self.login_states[user_id]
            
            user_info = await perm_client.get_me()
            
            return (
                "✅ **Login Successful!**\n\n"
                f"👤 **Logged in as:** {user_info.first_name or ''} {user_info.last_name or ''}\n"
                f"📱 **Phone:** `{phone}`\n\n"
                "Your session has been saved. You can now use the bot to download media!\n\n"
                "Use `/logout` to remove your session."
            )
            
        except PasswordHashInvalid:
            return "❌ **Incorrect password.** Please try again."
        except FloodWait as e:
            return f"⏳ **Please wait {e.value} seconds** before trying again."
        except Exception as e:
            LOGGER(__name__).error(f"2FA error for user {user_id}: {e}")
            await self.cancel_login(user_id)
            return f"❌ **Error:** {str(e)}\n\nLogin cancelled. Use `/login` to try again."
    
    async def cancel_login(self, user_id: int) -> str:
        """Cancel ongoing login process"""
        if user_id in self.login_states:
            state_data = self.login_states[user_id]
            client = state_data.get("client")
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
            del self.login_states[user_id]
            return "✅ **Login cancelled.**"
        return "❌ **No active login process to cancel.**"
    
    async def logout(self, user_id: int) -> str:
        """Logout a user and remove their session"""
        # Check if user has an active session
        if user_id not in self.active_clients:
            db = get_database()
            if db and db.is_connected:
                session = await db.get_session(user_id)
                if session:
                    await db.delete_session(user_id)
                    return "✅ **Session removed from database.**"
            return "❌ **You are not logged in.**"
        
        # Stop and remove client
        client = self.active_clients[user_id]
        try:
            await client.stop()
        except:
            pass
        
        del self.active_clients[user_id]
        
        # Update primary client if needed
        if self.primary_client == client:
            if self.active_clients:
                self.primary_client = list(self.active_clients.values())[0]
            elif self.env_client:
                self.primary_client = self.env_client
            else:
                self.primary_client = None
        
        # Remove from database
        db = get_database()
        if db and db.is_connected:
            await db.delete_session(user_id)
        
        return "✅ **Logged out successfully!**\n\nYour session has been removed."
    
    def get_login_state(self, user_id: int) -> Optional[str]:
        """Get current login state for a user"""
        if user_id in self.login_states:
            return self.login_states[user_id].get("state")
        return None
    
    def is_logged_in(self, user_id: int) -> bool:
        """Check if user is logged in"""
        return user_id in self.active_clients
    
    async def get_session_status(self, user_id: int) -> str:
        """Get session status for a user"""
        if user_id in self.active_clients:
            client = self.active_clients[user_id]
            try:
                me = await client.get_me()
                return (
                    "✅ **Session Active**\n\n"
                    f"👤 **Logged in as:** {me.first_name or ''} {me.last_name or ''}\n"
                    f"🆔 **User ID:** `{me.id}`\n"
                    f"📱 **Username:** @{me.username or 'N/A'}"
                )
            except:
                return "⚠️ **Session exists but may be invalid.**"
        
        # Check database
        db = get_database()
        if db and db.is_connected:
            session = await db.get_session(user_id)
            if session:
                if session.get("is_active"):
                    return "⚠️ **Session in database but not loaded.** Try restarting the bot."
                else:
                    return "❌ **Session is deactivated.**"
        
        return "❌ **No session found.** Use `/login` to create one."
    
    async def cleanup(self):
        """Clean up all sessions on shutdown"""
        for user_id, client in list(self.active_clients.items()):
            try:
                await client.stop()
            except:
                pass
        
        if self.env_client:
            try:
                await self.env_client.stop()
            except:
                pass
        
        self.active_clients.clear()
        self.login_states.clear()


# Global session manager instance
session_manager: Optional[SessionManager] = None


def get_session_manager() -> Optional[SessionManager]:
    """Get the session manager instance"""
    return session_manager


async def init_session_manager() -> SessionManager:
    """Initialize and return session manager"""
    global session_manager
    session_manager = SessionManager()
    return session_manager
