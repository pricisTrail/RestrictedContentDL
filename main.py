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

# Client for user session
user = Client(
    "user_session",
    workers=100,
    session_string=PyroConf.SESSION_STRING,
    max_concurrent_transmissions=1, # ✅ SAFE DEFAULT
    sleep_threshold=30,
)

RUNNING_TASKS = set()
download_semaphore = None

def track_task(coro):
    task = asyncio.create_task(coro)
    RUNNING_TASKS.add(task)
    def _remove(_):
        RUNNING_TASKS.discard(task)
    task.add_done_callback(_remove)
    return task


@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    LOGGER(__name__).info(f"Received /start from user {message.from_user.id}")
    welcome_text = (
        "👋 **Welcome to Media Downloader Bot!**\n\n"
        "I can grab photos, videos, audio, and documents from any Telegram post.\n"
        "Just send me a link (paste it directly or use `/dl <link>`),\n"
        "or reply to a message with `/dl`.\n\n"
        "ℹ️ Use `/help` to view all commands and examples.\n"
        "🔒 Make sure the user client is part of the chat.\n\n"
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
        "➤ **Download Media**\n"
        "   – Send `/dl <post_URL>` **or** just paste a Telegram post link to fetch photos, videos, audio, or documents.\n\n"
        "➤ **Batch Download**\n"
        "   – Send `/bdl start_link end_link` to grab a series of posts in one go.\n"
        "     💡 Example: `/bdl https://t.me/mychannel/100 https://t.me/mychannel/120`\n"
        "**It will download all posts from ID 100 to 120.**\n\n"
        "➤ **Requirements**\n"
        "   – Make sure the user client is part of the chat.\n\n"
        "➤ **If the bot hangs**\n"
        "   – Send `/killall` to cancel any pending downloads.\n\n"
        "➤ **Logs**\n"
        "   – Send `/logs` to download the bot’s logs file.\n\n"
        "➤ **Channel Forwarding**\n"
        "   – Send `/channel` to check the forward channel status.\n\n"
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


async def handle_download(bot: Client, message: Message, post_url: str):
    async with download_semaphore:
        if "?" in post_url:
            post_url = post_url.split("?", 1)[0]

        try:
            chat_id, message_id = getChatMsgID(post_url)
            chat_message = await user.get_messages(chat_id=chat_id, message_ids=message_id)

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
                    file_size, message, "download", user.me.is_premium
                ):
                    return

            parsed_caption = await get_parsed_msg(
                chat_message.caption or "", chat_message.caption_entities
            )
            parsed_text = await get_parsed_msg(
                chat_message.text or "", chat_message.entities
            )

            if chat_message.media_group_id:
                if not await processMediaGroup(chat_message, bot, message):
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
                )

                cleanup_download(media_path)
                await progress_message.delete()

            elif chat_message.text or chat_message.caption:
                await message.reply(parsed_text or parsed_caption)
            else:
                await message.reply("**No media or text found in the post URL.**")

        except (PeerIdInvalid, BadRequest, KeyError):
            await message.reply("**Make sure the user client is part of the chat.**")
        except Exception as e:
            error_message = f"**❌ {str(e)}**"
            await message.reply(error_message)
            LOGGER(__name__).error(e)


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
        await user.get_chat(start_chat)
    except Exception:
        pass

    prefix = args[1].rsplit("/", 1)[0]
    loading = await message.reply(f"📥 **Downloading posts {start_id}–{end_id}…**")

    downloaded = skipped = failed = 0
    batch_tasks = []
    BATCH_SIZE = PyroConf.BATCH_SIZE

    for msg_id in range(start_id, end_id + 1):
        url = f"{prefix}/{msg_id}"
        try:
            chat_msg = await user.get_messages(chat_id=start_chat, message_ids=msg_id)
            if not chat_msg:
                skipped += 1
                continue

            has_media = bool(chat_msg.media_group_id or chat_msg.media)
            has_text  = bool(chat_msg.text or chat_msg.caption)
            if not (has_media or has_text):
                skipped += 1
                continue

            task = track_task(handle_download(bot, message, url))
            batch_tasks.append(task)

            if len(batch_tasks) >= BATCH_SIZE:
                results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, asyncio.CancelledError):
                        await loading.delete()
                        return await message.reply(
                            f"**❌ Batch canceled** after downloading `{downloaded}` posts."
                        )
                    elif isinstance(result, Exception):
                        failed += 1
                        LOGGER(__name__).error(f"Error: {result}")
                    else:
                        downloaded += 1

                batch_tasks.clear()
                await asyncio.sleep(PyroConf.FLOOD_WAIT_DELAY)

        except Exception as e:
            failed += 1
            LOGGER(__name__).error(f"Error at {url}: {e}")

    if batch_tasks:
        results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                failed += 1
            else:
                downloaded += 1

    await loading.delete()
    await message.reply(
        "**✅ Batch Process Complete!**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **Downloaded** : `{downloaded}` post(s)\n"
        f"⏭️ **Skipped**    : `{skipped}` (no content)\n"
        f"❌ **Failed**     : `{failed}` error(s)"
    )


@bot.on_message(filters.private & ~filters.command(["start", "help", "dl", "stats", "logs", "killall", "channel", "bdl", "ping"]))
async def handle_any_message(bot: Client, message: Message):
    if message.text and not message.text.startswith("/"):
        await track_task(handle_download(bot, message, message.text))


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

    stats = (
        "**≧◉◡◉≦ Bot is Up and Running successfully.**\n\n"
        f"**➜ Bot Uptime:** `{currentTime}`\n"
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
    if os.path.exists("logs.txt"):
        await message.reply_document(document="logs.txt", caption="**Logs**")
    else:
        await message.reply("**Not exists**")


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
            f"📢 **Channel Forwarding Status**\n\n"
            f"{status_emoji} **Channel:** {chat.title}\n"
            f"🔢 **ID:** `{PyroConf.FORWARD_CHANNEL_ID}`\n\n"
            f"👤 **Bot is Admin:** {admin_status}\n"
            f"📝 **Can Post Messages:** {post_status}\n\n"
            + ("✅ **Ready to forward media!**" if is_admin and can_post else 
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


async def initialize():
    global download_semaphore
    download_semaphore = asyncio.Semaphore(PyroConf.MAX_CONCURRENT_DOWNLOADS)


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
            startup_msg = (
                "🚀 **Bot Started Successfully!**\n\n"
                f"📅 **Time:** `{now}`\n"
                f"🔧 **Status:** All systems operational\n"
                f"✅ **Health Check:** Running on port 8000\n\n"
                "The bot is now ready to receive messages!"
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
        
        # Initialize semaphore
        asyncio.get_event_loop().run_until_complete(initialize())
        
        # Start user session first
        user.start()
        LOGGER(__name__).info("User session started!")
        
        # Send startup notification (before blocking run())
        asyncio.get_event_loop().run_until_complete(send_startup_notification())
        
        LOGGER(__name__).info("Bot is now ready to receive messages!")
        
        # Run the bot (this blocks and handles updates)
        bot.run()
        
    except KeyboardInterrupt:
        pass
    except Exception as err:
        LOGGER(__name__).error(f"Fatal error: {err}")
    finally:
        LOGGER(__name__).info("Bot Stopped")


