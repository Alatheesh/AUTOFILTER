import time
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db

logger = logging.getLogger(__name__)

# Memory Cache so the bot doesn't spam Telegram's API checking the channel every second
TARGET_CACHE = {"url": None, "text": None, "expires": 0}

async def get_target_post(client: Client, settings: dict) -> str:
    global TARGET_CACHE
    
    # Use cache if it's less than 10 minutes old
    if time.time() < TARGET_CACHE["expires"] and TARGET_CACHE["url"]:
        return TARGET_CACHE["url"]

    channels = settings.get("inside_channels", [])
    words = [w.lower() for w in settings.get("inside_words", [])]

    if not channels or not words:
        return None

    for channel in channels:
        try:
            target_chat = int(channel) if channel.lstrip('-').isdigit() else channel
            chat_info = await client.get_chat(target_chat)
            
            # Scan the last 20 messages in the channel for your trigger words
            async for msg in client.get_chat_history(target_chat, limit=20):
                text = msg.text or msg.caption or ""
                text_lower = text.lower()
                
                if any(word in text_lower for word in words):
                    # Generate the direct link to the post
                    if chat_info.username:
                        url = f"https://t.me/{chat_info.username}/{msg.id}"
                    else:
                        private_id = str(chat_info.id).replace("-100", "")
                        url = f"https://t.me/c/{private_id}/{msg.id}"
                        
                    TARGET_CACHE["url"] = url
                    TARGET_CACHE["text"] = text
                    TARGET_CACHE["expires"] = time.time() + 600 
                    return url
        except Exception as e:
            logger.error(f"Inside Fetcher Error on {channel}: {e}")
            continue
            
    return None

@Client.on_message(filters.private & filters.forwarded, group=3)
async def catch_forwarded_verification(client: Client, message: Message):
    settings = await db.get_settings()
    
    if not settings.get("inside_enabled", False):
        return
        
    if not TARGET_CACHE["text"]:
        await get_target_post(client, settings)
        if not TARGET_CACHE["text"]: return 
        
    user_text = message.text or message.caption or ""
    words = [w.lower() for w in settings.get("inside_words", [])]
    
    # 🚨 THE CORE CHECK: Does their forwarded message contain your secret words?
    if any(w in user_text.lower() for w in words):
        
        # Calculate Time Math (e.g., 24 hours / 5 times = 4.8 hours per pass)
        inside_times = settings.get("inside_times", 5)
        hours_per_pass = 24 / inside_times if inside_times > 0 else 24
        pass_duration_seconds = hours_per_pass * 3600
        
        # Save the Expiration to MongoDB
        expires_at = time.time() + pass_duration_seconds
        await db.update_user_setting(message.from_user.id, "inside_pass_expires", expires_at)
        
        await message.reply_text(
            f"✅ **Human Verification Passed!**\n\n"
            f"Thank you for completing the task! You have been granted a **Free Pass** for the next **{hours_per_pass:.1f} Hours**.\n\n"
            f"🎬 You can now browse without interruptions. Please go click your movie/request button again to proceed!"
        )
    else:
        # If they forwarded the wrong post
        target_url = TARGET_CACHE["url"]
        await message.reply_text(
            f"❌ **Verification Failed!**\n\n"
            f"That is not the correct post. Please click the button below, find the exact post with our secret words, and forward it directly to me.\n\n"
            f"👉 **Try again using this link:** {target_url}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open Correct Post", url=target_url)]])
        )
