# Copyright (C) @TheSmartBisnu
# Channel: https://t.me/itsSmartDev

import os
import asyncio
from time import time
from PIL import Image
from logger import LOGGER
from typing import Optional
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec, create_subprocess_shell, wait_for

from pyleaves import Leaves
from pyrogram.parser import Parser
from pyrogram.utils import get_channel_id
from pyrogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
    Voice,
)

from helpers.files import (
    fileSizeLimit,
    cleanup_download
)

from helpers.msg import (
    get_parsed_msg
)

from config import PyroConf

# Progress bar template
PROGRESS_BAR = """
Percentage: {percentage:.2f}% | {current}/{total}
Speed: {speed}/s
Estimated Time Left: {est_time} seconds
"""

async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    try:
        stdout = stdout.decode().strip()
    except:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode


async def get_media_info(path):
    try:
        result = await cmd_exec([
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-print_format", "json", "-show_format", "-show_streams", path,
        ])
    except Exception as e:
        LOGGER(__name__).error(f"Get Media Info: {e}. File: {path}")
        return 0, None, None, None, None

    if result[0] and result[2] == 0:
        try:
            import json
            data = json.loads(result[0])

            fields = data.get("format", {})
            duration = round(float(fields.get("duration", 0)))

            tags = fields.get("tags", {})
            artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
            title = tags.get("title") or tags.get("TITLE") or tags.get("Title")

            width = None
            height = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = stream.get("width")
                    height = stream.get("height")
                    break

            return duration, artist, title, width, height
        except Exception as e:
            LOGGER(__name__).error(f"Error parsing media info: {e}")
            return 0, None, None, None, None
    return 0, None, None, None, None


async def get_video_thumbnail(video_file, duration):
    os.makedirs("Assets", exist_ok=True)
    output = os.path.join("Assets", "video_thumb.jpg")

    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if not duration:
        duration = 3
    duration //= 2

    if os.path.exists(output):
        try:
            os.remove(output)
        except:
            pass

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(duration), "-i", video_file,
        "-vframes", "1", "-q:v", "2",
        "-y", output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not os.path.exists(output):
            LOGGER(__name__).warning(f"Thumbnail generation failed: {err}")
            return None
    except Exception as e:
        LOGGER(__name__).warning(f"Thumbnail generation error: {e}")
        return None
    return output


# Generate progress bar for downloading/uploading
def progressArgs(action: str, progress_message, start_time):
    return (action, progress_message, start_time, PROGRESS_BAR, "▓", "░")


async def send_media(
    bot, message, media_path, media_type, caption, progress_message, start_time, is_batch=False
):
    """
    Send media to user or channel.
    
    Args:
        is_batch: If True, suppress individual confirmation messages (for batch downloads)
    
    Returns:
        bool: True if upload succeeded, False otherwise
    """
    file_size = os.path.getsize(media_path)

    if not await fileSizeLimit(file_size, message, "upload"):
        return False

    progress_args = progressArgs("📥 Uploading Progress", progress_message, start_time)
    
    # Determine target: if FORWARD_CHANNEL_ID is set, upload ONLY to channel, not user chat
    if PyroConf.FORWARD_CHANNEL_ID != 0:
        target_chat_id = PyroConf.FORWARD_CHANNEL_ID
        LOGGER(__name__).info(f"Uploading media directly to channel {target_chat_id}: {media_path} ({media_type})")
        
        # Upload directly to channel (not user chat)
        try:
            sent_msg = None
            if media_type == "photo":
                sent_msg = await bot.send_photo(
                    chat_id=target_chat_id,
                    photo=media_path,
                    caption=caption or "",
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progress_args,
                )
            elif media_type == "video":
                duration, _, _, width, height = await get_media_info(media_path)
                if not duration or duration == 0:
                    duration = 0
                if not width or not height:
                    width = 640
                    height = 480
                thumb = await get_video_thumbnail(media_path, duration)
                sent_msg = await bot.send_video(
                    chat_id=target_chat_id,
                    video=media_path,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb,
                    caption=caption or "",
                    supports_streaming=True,
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progress_args,
                )
            elif media_type == "audio":
                duration, artist, title, _, _ = await get_media_info(media_path)
                sent_msg = await bot.send_audio(
                    chat_id=target_chat_id,
                    audio=media_path,
                    duration=duration,
                    performer=artist,
                    title=title,
                    caption=caption or "",
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progress_args,
                )
            elif media_type == "document":
                sent_msg = await bot.send_document(
                    chat_id=target_chat_id,
                    document=media_path,
                    caption=caption or "",
                    progress=Leaves.progress_for_pyrogram,
                    progress_args=progress_args,
                )
            
            LOGGER(__name__).info(f"Successfully uploaded {media_type} to channel {target_chat_id}")
            # Send confirmation to user only if not a batch operation
            if not is_batch:
                await message.reply(f"✅ Media uploaded to channel successfully!")
            
            # Use instant copy for bin channel if we have the sent message
            if sent_msg and PyroConf.BIN_CHANNEL_ID != 0:
                await copy_messages_to_bin(bot, target_chat_id, [sent_msg.id])
            
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Failed to upload to channel {target_chat_id}: {e}")
            if not is_batch:
                await message.reply(f"❌ Failed to upload to channel: {e}")
            return False
    else:
        # No forward channel configured, upload to user chat as before
        LOGGER(__name__).info(f"Uploading media to user chat: {media_path} ({media_type})")
        
        sent_msg = None
        if media_type == "photo":
            sent_msg = await message.reply_photo(
                media_path,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "video":
            duration, _, _, width, height = await get_media_info(media_path)

            if not duration or duration == 0:
                duration = 0
                LOGGER(__name__).warning(f"Could not extract duration for {media_path}")

            if not width or not height:
                width = 640
                height = 480

            thumb = await get_video_thumbnail(media_path, duration)

            sent_msg = await message.reply_video(
                media_path,
                duration=duration,
                width=width,
                height=height,
                thumb=thumb,
                caption=caption or "",
                supports_streaming=True,
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "audio":
            duration, artist, title, _, _ = await get_media_info(media_path)
            sent_msg = await message.reply_audio(
                media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "document":
            sent_msg = await message.reply_document(
                media_path,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        
        # Use instant copy for bin channel if we have the sent message
        if sent_msg and PyroConf.BIN_CHANNEL_ID != 0:
            await copy_messages_to_bin(bot, message.chat.id, [sent_msg.id])


async def forward_to_channel(bot, media_path, media_type, caption):
    """Forward media to the configured channel if FORWARD_CHANNEL_ID is set"""
    if PyroConf.FORWARD_CHANNEL_ID == 0:
        return  # Channel forwarding disabled
    
    try:
        channel_id = PyroConf.FORWARD_CHANNEL_ID
        LOGGER(__name__).info(f"Forwarding {media_type} to channel {channel_id}")
        
        if media_type == "photo":
            await bot.send_photo(
                chat_id=channel_id,
                photo=media_path,
                caption=caption or "",
            )
        elif media_type == "video":
            duration, _, _, width, height = await get_media_info(media_path)
            thumb = await get_video_thumbnail(media_path, duration)
            await bot.send_video(
                chat_id=channel_id,
                video=media_path,
                duration=duration or 0,
                width=width or 640,
                height=height or 480,
                thumb=thumb,
                caption=caption or "",
                supports_streaming=True,
            )
        elif media_type == "audio":
            duration, artist, title, _, _ = await get_media_info(media_path)
            await bot.send_audio(
                chat_id=channel_id,
                audio=media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or "",
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=channel_id,
                document=media_path,
                caption=caption or "",
            )
        
        LOGGER(__name__).info(f"Successfully forwarded {media_type} to channel {channel_id}")
    except Exception as e:
        LOGGER(__name__).error(f"Failed to forward to channel: {e}")


async def forward_media_group_to_channel(bot, valid_media):
    """Forward a media group to the configured channel if FORWARD_CHANNEL_ID is set"""
    if PyroConf.FORWARD_CHANNEL_ID == 0:
        return  # Channel forwarding disabled
    
    try:
        channel_id = PyroConf.FORWARD_CHANNEL_ID
        LOGGER(__name__).info(f"Forwarding media group ({len(valid_media)} items) to channel {channel_id}")
        
        await bot.send_media_group(chat_id=channel_id, media=valid_media)
        
        LOGGER(__name__).info(f"Successfully forwarded media group to channel {channel_id}")
    except Exception as e:
        error_msg = str(e)
        # Check if this is the Pyrogram 'topics' bug - upload actually succeeded
        if "topics" in error_msg.lower() or "missing 1 required keyword-only argument" in error_msg:
            LOGGER(__name__).info(f"Forwarded media group to channel {channel_id} (Pyrogram topics bug)")
        else:
            LOGGER(__name__).error(f"Failed to forward media group to channel: {e}")
            # Try individual uploads as fallback only for real errors
            try:
                for media in valid_media:
                    if isinstance(media, InputMediaPhoto):
                        await bot.send_photo(
                            chat_id=channel_id,
                            photo=media.media,
                            caption=media.caption,
                        )
                    elif isinstance(media, InputMediaVideo):
                        await bot.send_video(
                            chat_id=channel_id,
                            video=media.media,
                            caption=media.caption,
                        )
                    elif isinstance(media, InputMediaDocument):
                        await bot.send_document(
                            chat_id=channel_id,
                            document=media.media,
                            caption=media.caption,
                        )
                    elif isinstance(media, InputMediaAudio):
                        await bot.send_audio(
                            chat_id=channel_id,
                            audio=media.media,
                            caption=media.caption,
                        )
            except Exception as fallback_e:
                LOGGER(__name__).error(f"Failed individual channel upload fallback: {fallback_e}")


async def forward_to_bin_channel(bot, media_path, media_type, caption):
    """Forward media to the bin channel (backup) if BIN_CHANNEL_ID is set.
    This happens regardless of FORWARD_CHANNEL_ID setting.
    """
    if PyroConf.BIN_CHANNEL_ID == 0:
        return  # Bin channel disabled
    
    try:
        channel_id = PyroConf.BIN_CHANNEL_ID
        LOGGER(__name__).info(f"Forwarding {media_type} to bin channel {channel_id}")
        
        if media_type == "photo":
            await bot.send_photo(
                chat_id=channel_id,
                photo=media_path,
                caption=caption or "",
            )
        elif media_type == "video":
            duration, _, _, width, height = await get_media_info(media_path)
            thumb = await get_video_thumbnail(media_path, duration)
            await bot.send_video(
                chat_id=channel_id,
                video=media_path,
                duration=duration or 0,
                width=width or 640,
                height=height or 480,
                thumb=thumb,
                caption=caption or "",
                supports_streaming=True,
            )
        elif media_type == "audio":
            duration, artist, title, _, _ = await get_media_info(media_path)
            await bot.send_audio(
                chat_id=channel_id,
                audio=media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or "",
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=channel_id,
                document=media_path,
                caption=caption or "",
            )
        
        LOGGER(__name__).info(f"Successfully forwarded {media_type} to bin channel {channel_id}")
    except Exception as e:
        LOGGER(__name__).error(f"Failed to forward to bin channel: {e}")


async def copy_messages_to_bin(bot, from_chat_id: int, message_ids: list):
    """Copy already-sent messages to bin channel (instant, no re-upload).
    Uses copy_message to avoid "Forwarded from" tag.
    
    Args:
        bot: The bot client
        from_chat_id: The chat where messages were originally sent
        message_ids: List of message IDs to copy
    """
    if PyroConf.BIN_CHANNEL_ID == 0:
        return  # Bin channel disabled
    
    try:
        bin_channel_id = PyroConf.BIN_CHANNEL_ID
        LOGGER(__name__).info(f"Copying {len(message_ids)} messages from {from_chat_id} to bin channel {bin_channel_id}")
        
        # Use copy_message for each message (no "Forwarded from" tag)
        for msg_id in message_ids:
            try:
                await bot.copy_message(
                    chat_id=bin_channel_id,
                    from_chat_id=from_chat_id,
                    message_id=msg_id
                )
            except Exception as copy_e:
                # Handle topics bug for individual copies
                if "topics" not in str(copy_e).lower():
                    LOGGER(__name__).warning(f"Failed to copy message {msg_id}: {copy_e}")
        
        LOGGER(__name__).info(f"Successfully copied messages to bin channel {bin_channel_id}")
    except Exception as e:
        error_msg = str(e)
        if "topics" in error_msg.lower() or "missing 1 required keyword-only argument" in error_msg:
            LOGGER(__name__).info(f"Copied messages to bin channel {bin_channel_id} (Pyrogram topics bug)")
        else:
            LOGGER(__name__).error(f"Failed to copy messages to bin channel: {e}")


async def forward_media_group_to_bin(bot, valid_media, from_chat_id: int = None, message_ids: list = None, user_client=None, media_count: int = None):
    """Forward a media group to the bin channel if BIN_CHANNEL_ID is set.
    
    If from_chat_id and message_ids are provided, uses instant message copying.
    If user_client is provided and message_ids are not available, tries to get
    recent messages from from_chat_id using user_client (which can use get_chat_history).
    Otherwise falls back to re-uploading the media.
    """
    if PyroConf.BIN_CHANNEL_ID == 0:
        return  # Bin channel disabled
    
    # If we have message IDs from the original upload, use instant copy
    if from_chat_id and message_ids:
        await copy_messages_to_bin(bot, from_chat_id, message_ids)
        return
    
    # If no message IDs but we have user_client, try to get them via history
    if from_chat_id and user_client and media_count:
        try:
            retrieved_ids = []
            async for msg in user_client.get_chat_history(from_chat_id, limit=media_count):
                retrieved_ids.append(msg.id)
            if retrieved_ids:
                retrieved_ids.reverse()  # Oldest first
                LOGGER(__name__).info(f"Retrieved {len(retrieved_ids)} message IDs via user client for bin forwarding")
                await copy_messages_to_bin(bot, from_chat_id, retrieved_ids)
                return
        except Exception as e:
            LOGGER(__name__).warning(f"Could not get message history via user client: {e}")
    
    # Fallback: re-upload the media (slower)
    try:
        channel_id = PyroConf.BIN_CHANNEL_ID
        LOGGER(__name__).info(f"Uploading media group ({len(valid_media)} items) to bin channel {channel_id}")
        
        await bot.send_media_group(chat_id=channel_id, media=valid_media)
        
        LOGGER(__name__).info(f"Successfully uploaded media group to bin channel {channel_id}")
    except Exception as e:
        error_msg = str(e)
        # Check if this is the Pyrogram 'topics' bug - upload actually succeeded
        if "topics" in error_msg.lower() or "missing 1 required keyword-only argument" in error_msg:
            LOGGER(__name__).info(f"Uploaded media group to bin channel {channel_id} (Pyrogram topics bug)")
        else:
            LOGGER(__name__).error(f"Failed to upload media group to bin channel: {e}")

async def download_single_media(msg, progress_message, start_time):
    try:
        media_path = await msg.download(
            progress=Leaves.progress_for_pyrogram,
            progress_args=progressArgs(
                "📥 Downloading Progress", progress_message, start_time
            ),
        )

        parsed_caption = await get_parsed_msg(
            msg.caption or "", msg.caption_entities
        )

        if msg.photo:
            return ("success", media_path, InputMediaPhoto(media=media_path, caption=parsed_caption))
        elif msg.video:
            return ("success", media_path, InputMediaVideo(media=media_path, caption=parsed_caption))
        elif msg.document:
            return ("success", media_path, InputMediaDocument(media=media_path, caption=parsed_caption))
        elif msg.audio:
            return ("success", media_path, InputMediaAudio(media=media_path, caption=parsed_caption))

    except Exception as e:
        LOGGER(__name__).info(f"Error downloading media: {e}")
        return ("error", None, None)

    return ("skip", None, None)


async def processMediaGroup(chat_message, bot, message, is_batch=False, user_client=None):
    """
    Process and upload a media group.
    
    Args:
        is_batch: If True, suppress individual confirmation messages (for batch downloads)
        user_client: Optional user client for retrieving message history (for bin channel forwarding)
    
    Returns:
        bool: True if upload succeeded, False otherwise
    """
    media_group_messages = await chat_message.get_media_group()
    valid_media = []
    temp_paths = []
    invalid_paths = []

    start_time = time()
    progress_message = await message.reply("📥 Downloading media group...")
    LOGGER(__name__).info(
        f"Downloading media group with {len(media_group_messages)} items..."
    )

    download_tasks = []
    for msg in media_group_messages:
        if msg.photo or msg.video or msg.document or msg.audio:
            download_tasks.append(download_single_media(msg, progress_message, start_time))

    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            LOGGER(__name__).error(f"Download task failed: {result}")
            continue

        status, media_path, media_obj = result
        if status == "success" and media_path and media_obj:
            temp_paths.append(media_path)
            valid_media.append(media_obj)
        elif status == "error" and media_path:
            invalid_paths.append(media_path)

    LOGGER(__name__).info(f"Valid media count: {len(valid_media)}")

    if valid_media:
        # Validate all media files exist and are accessible before upload
        validated_media = []
        for media in valid_media:
            media_path = media.media
            if isinstance(media_path, str) and os.path.exists(media_path):
                file_size = os.path.getsize(media_path)
                if file_size > 0:
                    validated_media.append(media)
                    LOGGER(__name__).debug(f"Validated media: {media_path} ({file_size} bytes)")
                else:
                    LOGGER(__name__).warning(f"Skipping empty file: {media_path}")
            else:
                LOGGER(__name__).warning(f"Skipping missing file: {media_path}")
        
        if not validated_media:
            await progress_message.delete()
            await message.reply("❌ All media files in the group are invalid or missing.")
            for path in temp_paths + invalid_paths:
                cleanup_download(path)
            return False
        
        valid_media = validated_media
        LOGGER(__name__).info(f"Validated {len(valid_media)} media files for upload")
        
        # Track message IDs for bin channel forwarding
        sent_message_ids = []
        upload_chat_id = None
        
        # Determine target: if FORWARD_CHANNEL_ID is set, upload ONLY to channel, not user chat
        if PyroConf.FORWARD_CHANNEL_ID != 0:
            target_chat_id = PyroConf.FORWARD_CHANNEL_ID
            upload_chat_id = target_chat_id
            LOGGER(__name__).info(f"Uploading media group directly to channel {target_chat_id}")
            
            try:
                sent_messages = await bot.send_media_group(chat_id=target_chat_id, media=valid_media)
                # Capture message IDs for bin channel forwarding
                if sent_messages:
                    sent_message_ids = [msg.id for msg in sent_messages]
                LOGGER(__name__).info(f"Successfully uploaded media group to channel {target_chat_id}")
                if not is_batch:
                    await message.reply(f"✅ Media group ({len(valid_media)} items) uploaded to channel successfully!")
                await progress_message.delete()
            except Exception as e:
                error_msg = str(e)
                LOGGER(__name__).error(f"Failed to upload media group to channel: {error_msg}")
                
                # Check if this is the Pyrogram 'topics' bug - upload actually succeeded
                if "topics" in error_msg.lower() or "missing 1 required keyword-only argument" in error_msg:
                    LOGGER(__name__).info("Detected Pyrogram 'topics' bug - upload likely succeeded")
                    if not is_batch:
                        await message.reply(f"✅ Media group ({len(valid_media)} items) uploaded to channel!")
                    await progress_message.delete()
                    # Note: We can't get message IDs when topics bug happens, so bin channel forwarding
                    # will fall back to re-uploading. This is a Pyrogram bug workaround.
                    LOGGER(__name__).info("Bin channel will use re-upload method (no message IDs available)")
                else:
                    # Try individual uploads as fallback for real errors
                    if not is_batch:
                        await message.reply(
                            f"⚠️ Media group upload failed ({error_msg}), trying individual uploads..."
                        )
                    
                    success_count = 0
                    fail_count = 0
                    for media in valid_media:
                        try:
                            # Add small delay between uploads to avoid flood limits
                            if success_count > 0:
                                await asyncio.sleep(0.5)
                            
                            sent_msg = None
                            if isinstance(media, InputMediaPhoto):
                                sent_msg = await bot.send_photo(
                                    chat_id=target_chat_id,
                                    photo=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaVideo):
                                sent_msg = await bot.send_video(
                                    chat_id=target_chat_id,
                                    video=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaDocument):
                                sent_msg = await bot.send_document(
                                    chat_id=target_chat_id,
                                    document=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaAudio):
                                sent_msg = await bot.send_audio(
                                    chat_id=target_chat_id,
                                    audio=media.media,
                                    caption=media.caption,
                                )
                            if sent_msg:
                                sent_message_ids.append(sent_msg.id)
                            success_count += 1
                        except Exception as individual_e:
                            fail_count += 1
                            LOGGER(__name__).error(f"Failed individual upload: {individual_e}")
                    
                    if not is_batch:
                        if fail_count == 0:
                            await message.reply(f"✅ All {success_count} items uploaded to channel individually!")
                        else:
                            await message.reply(
                                f"⚠️ Uploaded {success_count} items, failed {fail_count} items to channel"
                            )
                    await progress_message.delete()
        else:
            # No forward channel configured, upload to user chat as before
            upload_chat_id = message.chat.id
            try:
                sent_messages = await bot.send_media_group(chat_id=message.chat.id, media=valid_media)
                if sent_messages:
                    sent_message_ids = [msg.id for msg in sent_messages]
                await progress_message.delete()
            except Exception as e:
                error_msg = str(e)
                LOGGER(__name__).error(f"Failed to send media group to user: {error_msg}")
                
                # Check if this is the Pyrogram 'topics' bug - upload actually succeeded
                if "topics" in error_msg.lower() or "missing 1 required keyword-only argument" in error_msg:
                    LOGGER(__name__).info("Detected Pyrogram 'topics' bug - upload likely succeeded")
                    await progress_message.delete()
                else:
                    await message.reply(
                        f"⚠️ Media group upload failed ({error_msg}), trying individual uploads..."
                    )
                    success_count = 0
                    for media in valid_media:
                        try:
                            # Add small delay between uploads to avoid flood limits
                            if success_count > 0:
                                await asyncio.sleep(0.5)
                            
                            sent_msg = None
                            if isinstance(media, InputMediaPhoto):
                                sent_msg = await bot.send_photo(
                                    chat_id=message.chat.id,
                                    photo=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaVideo):
                                sent_msg = await bot.send_video(
                                    chat_id=message.chat.id,
                                    video=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaDocument):
                                sent_msg = await bot.send_document(
                                    chat_id=message.chat.id,
                                    document=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, InputMediaAudio):
                                sent_msg = await bot.send_audio(
                                    chat_id=message.chat.id,
                                    audio=media.media,
                                    caption=media.caption,
                                )
                            elif isinstance(media, Voice):
                                sent_msg = await bot.send_voice(
                                    chat_id=message.chat.id,
                                    voice=media.media,
                                    caption=media.caption,
                                )
                            if sent_msg:
                                sent_message_ids.append(sent_msg.id)
                            success_count += 1
                        except Exception as individual_e:
                            LOGGER(__name__).error(f"Failed individual upload to user: {individual_e}")

                    await progress_message.delete()

        # Forward to bin channel if configured - use instant copy if we have message IDs
        if sent_message_ids and upload_chat_id:
            await forward_media_group_to_bin(bot, valid_media, from_chat_id=upload_chat_id, message_ids=sent_message_ids)
        else:
            # Pass user_client so it can try to get message history (bots can't, but users can)
            await forward_media_group_to_bin(
                bot, valid_media, 
                from_chat_id=upload_chat_id, 
                user_client=user_client, 
                media_count=len(valid_media)
            )

        for path in temp_paths + invalid_paths:
            cleanup_download(path)
        return True

    await progress_message.delete()
    await message.reply("❌ No valid media found in the media group.")
    for path in invalid_paths:
        cleanup_download(path)
    return False
