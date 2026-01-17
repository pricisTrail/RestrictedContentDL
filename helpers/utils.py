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
            if media_type == "photo":
                await bot.send_photo(
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
                await bot.send_video(
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
                await bot.send_audio(
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
                await bot.send_document(
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
            # Also forward to bin channel if configured
            await forward_to_bin_channel(bot, media_path, media_type, caption)
            return True
        except Exception as e:
            LOGGER(__name__).error(f"Failed to upload to channel {target_chat_id}: {e}")
            if not is_batch:
                await message.reply(f"❌ Failed to upload to channel: {e}")
            return False
    else:
        # No forward channel configured, upload to user chat as before
        LOGGER(__name__).info(f"Uploading media to user chat: {media_path} ({media_type})")
        
        if media_type == "photo":
            await message.reply_photo(
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

            await message.reply_video(
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
            await message.reply_audio(
                media_path,
                duration=duration,
                performer=artist,
                title=title,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        elif media_type == "document":
            await message.reply_document(
                media_path,
                caption=caption or "",
                progress=Leaves.progress_for_pyrogram,
                progress_args=progress_args,
            )
        
        # Also forward to bin channel if configured
        await forward_to_bin_channel(bot, media_path, media_type, caption)


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
        LOGGER(__name__).error(f"Failed to forward media group to channel: {e}")
        # Try individual uploads as fallback
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


async def forward_media_group_to_bin(bot, valid_media):
    """Forward a media group to the bin channel if BIN_CHANNEL_ID is set.
    This happens regardless of FORWARD_CHANNEL_ID setting.
    """
    if PyroConf.BIN_CHANNEL_ID == 0:
        return  # Bin channel disabled
    
    try:
        channel_id = PyroConf.BIN_CHANNEL_ID
        LOGGER(__name__).info(f"Forwarding media group ({len(valid_media)} items) to bin channel {channel_id}")
        
        await bot.send_media_group(chat_id=channel_id, media=valid_media)
        
        LOGGER(__name__).info(f"Successfully forwarded media group to bin channel {channel_id}")
    except Exception as e:
        LOGGER(__name__).error(f"Failed to forward media group to bin channel: {e}")

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


async def processMediaGroup(chat_message, bot, message, is_batch=False):
    """
    Process and upload a media group.
    
    Args:
        is_batch: If True, suppress individual confirmation messages (for batch downloads)
    
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
        # Determine target: if FORWARD_CHANNEL_ID is set, upload ONLY to channel, not user chat
        if PyroConf.FORWARD_CHANNEL_ID != 0:
            target_chat_id = PyroConf.FORWARD_CHANNEL_ID
            LOGGER(__name__).info(f"Uploading media group directly to channel {target_chat_id}")
            
            try:
                await bot.send_media_group(chat_id=target_chat_id, media=valid_media)
                LOGGER(__name__).info(f"Successfully uploaded media group to channel {target_chat_id}")
                if not is_batch:
                    await message.reply(f"✅ Media group ({len(valid_media)} items) uploaded to channel successfully!")
                await progress_message.delete()
            except Exception as e:
                LOGGER(__name__).error(f"Failed to upload media group to channel: {e}")
                await message.reply(
                    "**❌ Failed to send media group to channel, trying individual uploads**"
                )
                for media in valid_media:
                    try:
                        if isinstance(media, InputMediaPhoto):
                            await bot.send_photo(
                                chat_id=target_chat_id,
                                photo=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaVideo):
                            await bot.send_video(
                                chat_id=target_chat_id,
                                video=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaDocument):
                            await bot.send_document(
                                chat_id=target_chat_id,
                                document=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaAudio):
                            await bot.send_audio(
                                chat_id=target_chat_id,
                                audio=media.media,
                                caption=media.caption,
                            )
                    except Exception as individual_e:
                        await message.reply(
                            f"Failed to upload individual media to channel: {individual_e}"
                        )
                await progress_message.delete()
        else:
            # No forward channel configured, upload to user chat as before
            try:
                await bot.send_media_group(chat_id=message.chat.id, media=valid_media)
                await progress_message.delete()
            except Exception:
                await message.reply(
                    "**❌ Failed to send media group, trying individual uploads**"
                )
                for media in valid_media:
                    try:
                        if isinstance(media, InputMediaPhoto):
                            await bot.send_photo(
                                chat_id=message.chat.id,
                                photo=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaVideo):
                            await bot.send_video(
                                chat_id=message.chat.id,
                                video=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaDocument):
                            await bot.send_document(
                                chat_id=message.chat.id,
                                document=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, InputMediaAudio):
                            await bot.send_audio(
                                chat_id=message.chat.id,
                                audio=media.media,
                                caption=media.caption,
                            )
                        elif isinstance(media, Voice):
                            await bot.send_voice(
                                chat_id=message.chat.id,
                                voice=media.media,
                                caption=media.caption,
                            )
                    except Exception as individual_e:
                        await message.reply(
                            f"Failed to upload individual media: {individual_e}"
                        )

                await progress_message.delete()

        # Also forward to bin channel if configured
        await forward_media_group_to_bin(bot, valid_media)

        for path in temp_paths + invalid_paths:
            cleanup_download(path)
        return True

    await progress_message.delete()
    await message.reply("❌ No valid media found in the media group.")
    for path in invalid_paths:
        cleanup_download(path)
    return False
