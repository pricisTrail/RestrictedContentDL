# Copyright (C) @TheSmartBisnu
# Channel: https://t.me/itsSmartDev

import os
import shutil
import psutil
import asyncio
from time import time

from pyleaves import Leaves
from pyrogram.enums import ParseMode
from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, BadRequest, ChatAdminRequired, ChatWriteForbidden
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus

from helpers.utils import (
    processMediaGroup,
    progressArgs,
    send_media
)

from helpers.files import (
    get_download_path,
    fileSizeLimit,
    get_readable_file_size,
    get_readable_time,
    cleanup_download
)

from helpers.msg import (
    getChatMsgID,
    get_file_name,
    get_parsed_msg
)

from helpers.database import init_database, get_database
from helpers.session_manager import (
    init_session_manager, 
    get_session_manager, 
    LoginState
)

from config import PyroConf
from logger import LOGGER

# Initialize the bot client
bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=100,
    parse_mode=ParseMode.MARKDOWN,
    max_concurrent_transmissions=1, # ✅ SAFE DEFAULT
    sleep_threshold=30,
)

# Global session manager reference
session_mgr = None

RUNNING_TASKS = set()
download_semaphore = None

def track_task(coro):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)
    def _remove(_):
        RUNNING_TASKS.discard(task)
    task.add_done_callback(_remove)
    return task


def get_user_client(user_id: int = None):
    """Get the appropriate user client for downloads"""
    global session_mgr
    if session_mgr:
        # First try user-specific client
        if user_id:
            client = session_mgr.get_user_client(user_id)
            if client:
                return client
        # Fall back to primary client
        return session_mgr.get_primary_client()
    return None


@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    LOGGER(__name__).info(f"Received /start from user {message.from_user.id}")
    
    # Check if user has a session
    user_client = get_user_client(message.from_user.id)
    session_status = "✅ Session active" if user_client else "❌ No session - use /login"
    
    welcome_text = (
        "👋 **Welcome to Media Downloader Bot!**\n\n"
        "I can grab photos, videos, audio, and documents from any Telegram post.\n"
        "Just send me a link (paste it directly or use `/dl <link>`),\n"
        "or reply to a message with `/dl`.\n\n"
        f"🔐 **Session Status:** {session_status}\n\n"
        "ℹ️ Use `/help` to view all commands and examples.\n\n"
        "Ready? Send me a Telegram post link!"
    )

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Update Channel", url="https://t.me/itsSmartDev")]]
    )
    await message.reply(welcome_text, reply_markup=markup, disable_web_page_preview=True)
    LOGGER(__name__).info(f"Sent welcome message to user {message.from_user.id}")


@bot.on_message(filters.command("help") & filters.private)
async def help_command(_, message: Message):
    help_text = (
        "💡 **Media Downloader Bot Help**\n\n"
        "➤ **Session Management**\n"
        "   – `/login` - Login with your Telegram account\n"
        "   – `/logout` - Remove your session\n"
        "   – `/session` - Check your session status\n"
        "   – `/cancel` - Cancel ongoing login process\n\n"
        "➤ **Download Media**\n"
        "   – Send `/dl <post_URL>` **or** just paste a Telegram post link to fetch photos, videos, audio, or documents.\n\n"
        "➤ **Batch Download**\n"
        "   – Send `/bdl start_link end_link` to grab a series of posts in one go.\n"
        "     💡 Example: `/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`\n"
        "**It will download all posts from ID 100 to 120.**\n\n"
        "➤ **Requirements**\n"
        "   – You must be logged in (`/login`) to access restricted chats.\n\n"
        "➤ **If the bot hangs**\n"
        "   – Send `/killall` to cancel any pending downloads.\n\n"
        "➤ **Logs**\n"
        "   – Send `/logs` to download the bot's logs file.\n\n"
        "➤ **Channel Upload Mode**\n"
        "   – `/channel` - Check current channel status\n"
        "   – `/setchannel <id>` - Set forward channel (admin only)\n"
        "   – `/clearchannel` - Disable channel mode (admin only)\n"
        "   – When set, media uploads go **directly to the channel**\n\n"
        "➤ **Stats**\n"
        "   – Send `/stats` to view current status:\n\n"
        "**Example**:\n"
        "  • `/dl https://t.me/itsSmartDev/547`\n"
        "  • `https://t.me/itsSmartDev/547`"
    )
    
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Update Channel", url="https://t.me/itsSmartDev")]]
    )
    await message.reply(help_text, reply_markup=markup, disable_web_page_preview=True)


# ============ Session Management Commands ============

@bot.on_message(filters.command("login") & filters.private)
async def login_command(_, message: Message):
    """Start login process"""
    global session_mgr
    if not session_mgr:
        await message.reply("❌ **Session manager not initialized.** Please try again later.")
        return
    
    # Check if MongoDB is connected
    db = get_database()
    if not db or not db.is_connected:
        await message.reply(
            "⚠️ **Database not connected.**\n\n"
            "Sessions cannot be saved without MongoDB.\n"
            "Please configure `MONGO_URI` in config.env."
        )
        return
    
    response = await session_mgr.start_login(message.from_user.id)
    await message.reply(response)


@bot.on_message(filters.command("logout") & filters.private)
async def logout_command(_, message: Message):
    """Logout and remove session"""
    global session_mgr
    if not session_mgr:
        await message.reply("❌ **Session manager not initialized.**")
        return
    
    response = await session_mgr.logout(message.from_user.id)
    await message.reply(response)


@bot.on_message(filters.command("session") & filters.private)
async def session_command(_, message: Message):
    """Check session status"""
    global session_mgr
    if not session_mgr:
        await message.reply("❌ **Session manager not initialized.**")
        return
    
    response = await session_mgr.get_session_status(message.from_user.id)
    await message.reply(response)


@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(_, message: Message):
    """Cancel ongoing login process"""
    global session_mgr
    if not session_mgr:
        await message.reply("❌ **Session manager not initialized.**")
        return
    
    response = await session_mgr.cancel_login(message.from_user.id)
    await message.reply(response)


async def handle_login_flow(message: Message) -> bool:
    """Handle login flow messages. Returns True if message was handled."""
    global session_mgr
    if not session_mgr:
        return False
    
    user_id = message.from_user.id
    login_state = session_mgr.get_login_state(user_id)
    
    if not login_state or login_state == LoginState.IDLE:
        return False
    
    text = message.text.strip() if message.text else ""
    
    if login_state == LoginState.WAITING_PHONE:
        response = await session_mgr.handle_phone_number(user_id, text)
        await message.reply(response)
        return True
    
    elif login_state == LoginState.WAITING_CODE:
        response = await session_mgr.handle_verification_code(user_id, text)
        await message.reply(response)
        return True
    
    elif login_state == LoginState.WAITING_PASSWORD:
        # Delete the password message for security
        try:
            await message.delete()
        except:
            pass
        response = await session_mgr.handle_2fa_password(user_id, text)
        await message.reply(response)
        return True
    
    return False


# ============ Download Handlers ============

async def handle_download(bot: Client, message: Message, post_url: str, is_batch: bool = False):
    """
    Handle downloading media from a Telegram post URL.
    
    Args:
        is_batch: If True, suppress individual confirmation messages (for batch downloads)
    """
    async with download_semaphore:
        if "?" in post_url:
            post_url = post_url.split("?", 1)[0]

        # Get user client for this user or primary client
        user_client = get_user_client(message.from_user.id)
        
        if not user_client:
            await message.reply(
                "❌ **No active session found!**\n\n"
                "Please use `/login` to connect your Telegram account first.\n"
                "This is required to access chats and download media."
            )
            return

        try:
            chat_id, message_id = getChatMsgID(post_url)
            chat_message = await user_client.get_messages(chat_id=chat_id, message_ids=message_id)

            LOGGER(__name__).info(f"Downloading media from URL: {post_url}")

            if chat_message.document or chat_message.video or chat_message.audio:
                file_size = (
                    chat_message.document.file_size
                    if chat_message.document
                    else chat_message.video.file_size
                    if chat_message.video
                    else chat_message.audio.file_size
                )

                if not await fileSizeLimit(
                    file_size, message, "download", user_client.me.is_premium
                ):
                    return

            parsed_caption = await get_parsed_msg(
                chat_message.caption or "", chat_message.caption_entities
            )
            parsed_text = await get_parsed_msg(
                chat_message.text or "", chat_message.entities
            )

            if chat_message.media_group_id:
                if not await processMediaGroup(chat_message, bot, message, is_batch=is_batch):
                    if not is_batch:
                        await message.reply(
                            "**Could not extract any valid media from the media group.**"
                        )
                return

            elif chat_message.media:
                start_time = time()
                progress_message = await message.reply("**📥 Downloading Progress...**")

                filename = get_file_name(message_id, chat_message)
                download_path = get_download_path(message.id, filename)

                media_path = await chat_message.download(
                    file_name=download_path,
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progressArgs(
                        "📥 Downloading Progress", progress_message, start_time
                    ),
                )

                if not media_path or not os.path.exists(media_path):
                    await progress_message.edit("**❌ Download failed: File not saved properly**")
                    return

                file_size = os.path.getsize(media_path)
                if file_size == 0:
                    await progress_message.edit("**❌ Download failed: File is empty**")
                    cleanup_download(media_path)
                    return

                LOGGER(__name__).info(f"Downloaded media: {media_path} (Size: {file_size} bytes)")

                media_type = (
                    "photo"
                    if chat_message.photo
                    else "video"
                    if chat_message.video
                    else "audio"
                    if chat_message.audio
                    else "document"
                )
                await send_media(
                    bot,
                    message,
                    media_path,
                    media_type,
                    parsed_caption,
                    progress_message,
                    start_time,
                    is_batch=is_batch,
                )

                cleanup_download(media_path)
                await progress_message.delete()

            elif chat_message.text or chat_message.caption:
                await message.reply(parsed_text or parsed_caption)
            else:
                await message.reply("**No media or text found in the post URL.**")

        except (PeerIdInvalid, BadRequest, KeyError):
            await message.reply(
                "**Make sure you are logged in and part of the chat.**\n\n"
                "Use `/login` to connect your Telegram account."
            )
        except ValueError as e:
            # URL parsing errors - log but don't spam the user
            LOGGER(__name__).debug(f"URL parsing error: {e}")
        except Exception as e:
            error_message = f"**❌ {str(e)}**"
            await message.reply(error_message)
            LOGGER(__name__).error(f"Download error: {e}")


@bot.on_message(filters.command("dl") & filters.private)
async def download_media(bot: Client, message: Message):
    if len(message.command) < 2:
        await message.reply("**Provide a post URL after the /dl command.**")
        return

    post_url = message.command[1]
    await track_task(handle_download(bot, message, post_url))


@bot.on_message(filters.command("bdl") & filters.private)
async def download_range(bot: Client, message: Message):
    args = message.text.split()

    if len(args) != 3 or not all(arg.startswith("https://t.me/") for arg in args[1:]):
        await message.reply(
            "🚀 **Batch Download Process**\n"
            "`/bdl start_link end_link`\n\n"
            "💡 **Example:**\n"
            "`/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`"
        )
        return

    # Get user client
    user_client = get_user_client(message.from_user.id)
    if not user_client:
        await message.reply(
            "❌ **No active session found!**\n\n"
            "Please use `/login` to connect your Telegram account first."
        )
        return

    try:
        start_chat, start_id = getChatMsgID(args[1])
        end_chat,   end_id   = getChatMsgID(args[2])
    except Exception as e:
        return await message.reply(f"**❌ Error parsing links:\n{e}**")

    if start_chat != end_chat:
        return await message.reply("**❌ Both links must be from the same channel.**")
    if start_id > end_id:
        return await message.reply("**❌ Invalid range: start ID cannot exceed end ID.**")

    try:
        await user_client.get_chat(start_chat)
    except Exception:
        pass

    prefix = args[1].rsplit("/", 1)[0]
    loading = await message.reply(f"📥 **Downloading posts {start_id}–{end_id}…**")

    downloaded = skipped = failed = 0
    failed_ids = []  # Track which post IDs failed
    batch_tasks = []
    batch_msg_ids = []  # Track message IDs for current batch
    BATCH_SIZE = PyroConf.BATCH_SIZE

    for msg_id in range(start_id, end_id + 1):
        url = f"{prefix}/{msg_id}"
        try:
            chat_msg = await user_client.get_messages(chat_id=start_chat, message_ids=msg_id)
            if not chat_msg:
                skipped += 1
                continue

            has_media = bool(chat_msg.media_group_id or chat_msg.media)
            has_text  = bool(chat_msg.text or chat_msg.caption)
            if not (has_media or has_text):
                skipped += 1
                continue

            # Pass is_batch=True to suppress individual confirmation messages
            task = track_task(handle_download(bot, message, url, is_batch=True))
            batch_tasks.append(task)
            batch_msg_ids.append(msg_id)

            if len(batch_tasks) >= BATCH_SIZE:
                results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                for i, result in enumerate(results):
                    if isinstance(result, asyncio.CancelledError):
                        await loading.delete()
                        return await message.reply(
                            f"**❌ Batch canceled** after downloading `{downloaded}` posts."
                        )
                    elif isinstance(result, Exception):
                        failed += 1
                        failed_ids.append(batch_msg_ids[i])
                        LOGGER(__name__).error(f"Error at post {batch_msg_ids[i]}: {result}")
                    else:
                        downloaded += 1

                batch_tasks.clear()
                batch_msg_ids.clear()
                await asyncio.sleep(PyroConf.FLOOD_WAIT_DELAY)

        except Exception as e:
            failed += 1
            failed_ids.append(msg_id)
            LOGGER(__name__).error(f"Error at {url}: {e}")

    if batch_tasks:
        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                failed_ids.append(batch_msg_ids[i])
            else:
                downloaded += 1

    await loading.delete()
    
    # Build summary message based on channel mode
    if PyroConf.FORWARD_CHANNEL_ID != 0:
        summary = (
            "**✅ Batch Process Complete!**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"📤 **Uploaded to channel** : `{downloaded}` file(s)\n"
            f"⏭️ **Skipped**              : `{skipped}` (no content)\n"
            f"❌ **Failed**               : `{failed}` error(s)\n\n"
            f"📢 **Target Channel:** `{PyroConf.FORWARD_CHANNEL_ID}`"
        )
    else:
        summary = (
            "**✅ Batch Process Complete!**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"📥 **Downloaded** : `{downloaded}` post(s)\n"
            f"⏭️ **Skipped**    : `{skipped}` (no content)\n"
            f"❌ **Failed**     : `{failed}` error(s)"
        )
    
    # Add failed post IDs if any
    if failed_ids:
        # Limit to first 20 failed IDs to avoid message being too long
        if len(failed_ids) <= 20:
            failed_list = ", ".join(str(id) for id in failed_ids)
        else:
            failed_list = ", ".join(str(id) for id in failed_ids[:20]) + f"... (+{len(failed_ids) - 20} more)"
        summary += f"\n\n❌ **Failed Post IDs:** `{failed_list}`"
    
    await message.reply(summary)


# List of all command names for the catch-all handler
ALL_COMMANDS = ["start", "help", "dl", "stats", "logs", "killall", "channel", "setchannel", "clearchannel", "bdl", "ping", "login", "logout", "session", "cancel"]

@bot.on_message(filters.private & ~filters.command(ALL_COMMANDS) & ~filters.me)
async def handle_any_message(bot: Client, message: Message):
    # First check if this is part of a login flow
    if await handle_login_flow(message):
        return
    
    # Only process text messages that look like valid Telegram URLs
    if message.text and not message.text.startswith("/"):
        text = message.text.strip()
        # Only process if it looks like a valid Telegram post URL
        if text.startswith(("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/")):
            # Check if it has a message ID (contains at least one slash after the domain)
            parts = text.replace("https://", "").replace("http://", "").split("/")
            if len(parts) >= 3:  # domain/channel/message_id
                await track_task(handle_download(bot, message, text))
        # Silently ignore non-URL messages - don't spam errors


@bot.on_message(filters.command("stats") & filters.private)
async def stats(_, message: Message):
    currentTime = get_readable_time(time() - PyroConf.BOT_START_TIME)
    total, used, free = shutil.disk_usage(".")
    total = get_readable_file_size(total)
    used = get_readable_file_size(used)
    free = get_readable_file_size(free)
    sent = get_readable_file_size(psutil.net_io_counters().bytes_sent)
    recv = get_readable_file_size(psutil.net_io_counters().bytes_recv)
    cpuUsage = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    process = psutil.Process(os.getpid())
    
    # Get session info
    global session_mgr
    active_sessions = 0
    if session_mgr:
        active_sessions = len(session_mgr.active_clients)

    stats = (
        "**≧◉◡◉≦ Bot is Up and Running successfully.**\n\n"
        f"**➜ Bot Uptime:** `{currentTime}`\n"
        f"**➜ Active Sessions:** `{active_sessions}`\n"
        f"**➜ Total Disk Space:** `{total}`\n"
        f"**➜ Used:** `{used}`\n"
        f"**➜ Free:** `{free}`\n"
        f"**➜ Memory Usage:** `{round(process.memory_info()[0] / 1024**2)} MiB`\n\n"
        f"**➜ Upload:** `{sent}`\n"
        f"**➜ Download:** `{recv}`\n\n"
        f"**➜ CPU:** `{cpuUsage}%` | "
        f"**➜ RAM:** `{memory}%` | "
        f"**➜ DISK:** `{disk}%`"
    )
    await message.reply(stats)


@bot.on_message(filters.command("logs") & filters.private)
async def logs(_, message: Message):
    """Send the logs file (admin only)"""
    # Only allow admin to use this command
    if PyroConf.ADMIN_ID != 0 and message.from_user.id != PyroConf.ADMIN_ID:
        await message.reply("❌ **Only the admin can access logs.**")
        return
    
    if os.path.exists("logs.txt"):
        await message.reply_document(document="logs.txt", caption="**Logs**")
    else:
        await message.reply("**Logs file not found.**")


@bot.on_message(filters.command("killall") & filters.private)
async def cancel_all_tasks(_, message: Message):
    cancelled = 0
    for task in list(RUNNING_TASKS):
        if not task.done():
            task.cancel()
            cancelled += 1
    await message.reply(f"**Cancelled {cancelled} running task(s).**")


@bot.on_message(filters.command("channel") & filters.private)
async def channel_status(_, message: Message):
    """Check the forward channel status and bot permissions"""
    if PyroConf.FORWARD_CHANNEL_ID == 0:
        await message.reply(
            "📢 **Channel Forwarding Status**\n\n"
            "❌ **Status:** Disabled\n\n"
            "To enable, set `FORWARD_CHANNEL_ID` in your config.env file.\n"
            "Example: `FORWARD_CHANNEL_ID = -1001234567890`"
        )
        return
    
    try:
        # Try to get chat info
        chat = await bot.get_chat(PyroConf.FORWARD_CHANNEL_ID)
        
        # Check if bot is admin
        try:
            bot_member = await bot.get_chat_member(PyroConf.FORWARD_CHANNEL_ID, bot.me.id)
            is_admin = bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
            can_post = getattr(bot_member.privileges, 'can_post_messages', True) if bot_member.privileges else True
        except Exception:
            is_admin = False
            can_post = False
        
        status_emoji = "✅" if is_admin and can_post else "⚠️"
        admin_status = "Yes" if is_admin else "No"
        post_status = "Yes" if can_post else "No"
        
        await message.reply(
            f"📢 **Channel Upload Mode**\n\n"
            f"{status_emoji} **Channel:** {chat.title}\n"
            f"🔢 **ID:** `{PyroConf.FORWARD_CHANNEL_ID}`\n\n"
            f"👤 **Bot is Admin:** {admin_status}\n"
            f"📝 **Can Post Messages:** {post_status}\n\n"
            + ("✅ **Media will be uploaded directly to this channel!**\n"
               "_(User chat will only receive a confirmation message)_" if is_admin and can_post else 
               "⚠️ **Bot needs admin permissions to post in this channel.**")
        )
    except PeerIdInvalid:
        await message.reply(
            "📢 **Channel Forwarding Status**\n\n"
            "❌ **Error:** Invalid channel ID\n\n"
            f"The channel ID `{PyroConf.FORWARD_CHANNEL_ID}` is not valid.\n"
            "Make sure either the bot or user session has access to this channel."
        )
    except Exception as e:
        await message.reply(
            f"📢 **Channel Forwarding Status**\n\n"
            f"❌ **Error:** {str(e)}\n\n"
            f"Channel ID: `{PyroConf.FORWARD_CHANNEL_ID}`"
        )


@bot.on_message(filters.command("setchannel") & filters.private)
async def set_channel(_, message: Message):
    """Set the forward channel ID at runtime (overrides .env)"""
    
    if len(message.command) < 2:
        await message.reply(
            "📢 **Set Forward Channel**\n\n"
            "**Usage:** `/setchannel <channel_id>`\n\n"
            "**Examples:**\n"
            "• `/setchannel -1001234567890`\n"
            "• `/setchannel @mychannel`\n\n"
            "**Note:** The bot must be an admin in the target channel.\n"
            "Use `/clearchannel` to disable channel mode."
        )
        return
    
    channel_input = message.command[1]
    
    try:
        # Try to parse as integer first
        if channel_input.lstrip('-').isdigit():
            channel_id = int(channel_input)
        else:
            # Try to resolve username
            try:
                chat = await bot.get_chat(channel_input)
                channel_id = chat.id
            except Exception:
                await message.reply(
                    f"❌ **Could not find channel:** `{channel_input}`\n\n"
                    "Make sure the bot has access to the channel."
                )
                return
        
        # Verify bot has access and permissions
        try:
            chat = await bot.get_chat(channel_id)
            bot_member = await bot.get_chat_member(channel_id, bot.me.id)
            is_admin = bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
            
            if not is_admin:
                await message.reply(
                    f"⚠️ **Warning:** Bot is not an admin in **{chat.title}**\n\n"
                    f"Channel ID `{channel_id}` has been set, but uploads may fail.\n"
                    "Please add the bot as an admin with posting permissions."
                )
            
            # Update the config at runtime
            old_channel = PyroConf.FORWARD_CHANNEL_ID
            PyroConf.FORWARD_CHANNEL_ID = channel_id
            
            # Save to database for persistence
            db = get_database()
            if db and db.is_connected:
                await db.save_setting("forward_channel_id", channel_id)
                persistence_note = "✅ Setting saved to database (persists across restarts)"
            else:
                persistence_note = "⚠️ Database not connected - setting will reset on restart"
            
            LOGGER(__name__).info(f"Forward channel changed from {old_channel} to {channel_id} by user {message.from_user.id}")
            
            await message.reply(
                f"✅ **Forward Channel Updated!**\n\n"
                f"📢 **Channel:** {chat.title}\n"
                f"🔢 **ID:** `{channel_id}`\n\n"
                "All downloaded media will now be uploaded directly to this channel.\n\n"
                f"{persistence_note}"
            )
        except Exception as e:
            await message.reply(
                f"❌ **Could not access channel:** `{channel_id}`\n\n"
                f"Error: {str(e)}"
            )
    except ValueError:
        await message.reply(
            f"❌ **Invalid channel ID:** `{channel_input}`\n\n"
            "Please provide a valid channel ID (e.g., `-1001234567890`) or username."
        )


@bot.on_message(filters.command("clearchannel") & filters.private)
async def clear_channel(_, message: Message):
    """Clear the forward channel (disable channel mode)"""
    
    if PyroConf.FORWARD_CHANNEL_ID == 0:
        await message.reply("ℹ️ **Channel mode is already disabled.**")
        return
    
    old_channel = PyroConf.FORWARD_CHANNEL_ID
    PyroConf.FORWARD_CHANNEL_ID = 0
    
    # Save to database for persistence
    db = get_database()
    if db and db.is_connected:
        await db.delete_setting("forward_channel_id")
        persistence_note = "✅ Setting removed from database"
    else:
        persistence_note = "⚠️ Database not connected - original .env setting may restore on restart"
    
    LOGGER(__name__).info(f"Forward channel cleared (was {old_channel}) by user {message.from_user.id}")
    
    await message.reply(
        "✅ **Channel Mode Disabled!**\n\n"
        "Media will now be sent directly to your chat instead of a channel.\n\n"
        f"{persistence_note}"
    )


async def initialize():
    global download_semaphore, session_mgr
    download_semaphore = asyncio.Semaphore(PyroConf.MAX_CONCURRENT_DOWNLOADS)
    
    # Initialize database if MongoDB URI is configured
    if PyroConf.MONGO_URI:
        LOGGER(__name__).info("Connecting to MongoDB...")
        db = await init_database(PyroConf.MONGO_URI)
        if db.is_connected:
            LOGGER(__name__).info("MongoDB connected successfully!")
        else:
            LOGGER(__name__).warning("MongoDB connection failed. Sessions will not be persisted.")
    else:
        LOGGER(__name__).warning("MONGO_URI not configured. Session persistence is disabled.")
    
    # Initialize session manager
    session_mgr = await init_session_manager()
    
    # Try to initialize ENV session as fallback
    env_session_ok = await session_mgr.initialize_env_session()
    if env_session_ok:
        LOGGER(__name__).info("ENV session initialized as fallback")
    
    # Load sessions from database
    db = get_database()
    if db and db.is_connected:
        loaded = await session_mgr.load_sessions_from_db()
        LOGGER(__name__).info(f"Loaded {loaded} session(s) from database")
        
        # Load forward channel setting from database
        saved_channel = await db.get_setting("forward_channel_id")
        if saved_channel is not None and saved_channel != 0:
            PyroConf.FORWARD_CHANNEL_ID = int(saved_channel)
            LOGGER(__name__).info(f"Loaded forward channel from database: {saved_channel}")


# ============ Health Check Server for Koyeb ============
def run_health_server():
    """Run health check server in a separate thread"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            uptime = get_readable_time(time() - PyroConf.BOT_START_TIME)
            response = {
                "status": "healthy",
                "uptime": uptime,
                "message": "Bot is running"
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        
        def log_message(self, format, *args):
            # Suppress HTTP request logs
            pass
    
    port = int(os.getenv("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    LOGGER(__name__).info(f"Health check server running on port {port}")
    server.serve_forever()


async def send_startup_notification():
    """Send startup notification to admin"""
    if PyroConf.ADMIN_ID and PyroConf.ADMIN_ID != 0:
        try:
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Get session status
            global session_mgr
            session_status = "No sessions"
            if session_mgr:
                if session_mgr.primary_client:
                    session_status = "Primary session active"
                active_count = len(session_mgr.active_clients)
                if active_count > 0:
                    session_status = f"{active_count} session(s) active"
            
            # Get DB status
            db = get_database()
            db_status = "Connected" if db and db.is_connected else "Not connected"
            
            startup_msg = (
                "🚀 **Bot Started Successfully!**\n\n"
                f"📅 **Time:** `{now}`\n"
                f"🔧 **Status:** All systems operational\n"
                f"🗄️ **Database:** {db_status}\n"
                f"🔐 **Sessions:** {session_status}\n"
                f"✅ **Health Check:** Running on port 8000\n\n"
                "The bot is now ready to receive messages!\n"
                "Use `/login` to add a new session."
            )
            await bot.send_message(PyroConf.ADMIN_ID, startup_msg)
            LOGGER(__name__).info(f"Startup notification sent to admin {PyroConf.ADMIN_ID}")
        except Exception as e:
            LOGGER(__name__).warning(f"Failed to send startup notification: {e}")


@bot.on_message(filters.command("ping") & filters.private)
async def ping(_, message: Message):
    """Simple ping command to test if bot is responding"""
    LOGGER(__name__).info(f"Received /ping from user {message.from_user.id}")
    await message.reply("🏓 **Pong!** Bot is alive and responding!")


if __name__ == "__main__":
    import threading
    
    try:
        LOGGER(__name__).info("Starting Bot with Health Check Server...")
        
        # Start health check server in a separate thread
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
        LOGGER(__name__).info("Health check thread started")
        
        # Initialize everything (semaphore, database, sessions)
        asyncio.get_event_loop().run_until_complete(initialize())
        
        # Start bot first to get bot.me
        bot.start()
        LOGGER(__name__).info("Bot started!")
        
        # Send startup notification
        asyncio.get_event_loop().run_until_complete(send_startup_notification())
        
        LOGGER(__name__).info("Bot is now ready to receive messages!")
        
        # Run idle to keep the bot running
        from pyrogram import idle
        asyncio.get_event_loop().run_until_complete(idle())
        
    except KeyboardInterrupt:
        pass
    except Exception as err:
        LOGGER(__name__).error(f"Fatal error: {err}")
    finally:
        # Cleanup sessions
        if session_mgr:
            asyncio.get_event_loop().run_until_complete(session_mgr.cleanup())
        LOGGER(__name__).info("Bot Stopped")
