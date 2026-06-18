import time
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db

logger = logging.getLogger(__name__)

@Client.on_message(filters.channel, group=4)
async def live_channel_listener(client: Client, message: Message):
    settings = await db.get_settings()
    if not settings.get("inside_enabled", False):
        return

    channels = settings.get("inside_channels", [])
    words = [w.lower().strip(',.') for w in settings.get("inside_words", [])]

    chat_id_str = str(message.chat.id)
    chat_username = f"@{message.chat.username}" if message.chat.username else ""

    if chat_id_str in channels or chat_username in channels:
        text = message.text or message.caption or ""
        
        if any(word in text.lower() for word in words):
            if message.chat.username:
                url = f"https://t.me/{message.chat.username}/{message.id}"
            else:
                private_id = str(message.chat.id).replace("-100", "")
                url = f"https://t.me/c/{private_id}/{message.id}"
            
            # 🚨 THE UPGRADE: Save to permanent MongoDB instead of temporary memory!
            await db.update_settings({"inside_target_url": url})
            logger.info(f"✅ Successfully cached new target post to Database: {url}")

async def get_target_post(client: Client, settings: dict) -> str:
    # Fetch directly from MongoDB
    return settings.get("inside_target_url")

@Client.on_message(filters.private & filters.forwarded, group=3)
async def catch_forwarded_verification(client: Client, message: Message):
    settings = await db.get_settings()
    
    if not settings.get("inside_enabled", False):
        return
        
    user_text = message.text or message.caption or ""
    words = [w.lower().strip(',.') for w in settings.get("inside_words", [])]
    
    if any(w in user_text.lower() for w in words):
        inside_times = settings.get("inside_times", 5)
        hours_per_pass = 24 / inside_times if inside_times > 0 else 24
        pass_duration_seconds = hours_per_pass * 3600
        
        expires_at = time.time() + pass_duration_seconds
        await db.update_user_setting(message.from_user.id, "inside_pass_expires", expires_at)
        
        await message.reply_text(
            f"✅ **Human Verification Passed!**\n\n"
            f"Thank you for completing the task! You have been granted a **Free Pass** for the next **{hours_per_pass:.1f} Hours**.\n\n"
            f"🎬 You can now browse without interruptions. Please go click your movie or request button again to proceed!"
        )
    else:
        target_url = settings.get("inside_target_url", "")
        await message.reply_text(
            f"❌ **Verification Failed!**\n\n"
            f"That is not the correct post. Please find the exact post with our secret words and forward it directly to me.\n\n"
            f"👉 **Try again using this link:** {target_url}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Correct Post", url=target_url)]]) if target_url else None
        )
