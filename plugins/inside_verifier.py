import time
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# 🧠 State Machine: Only triggers if the user clicks "I will help"
VERIFIER_STATE = {}

@Client.on_message(filters.channel, group=4)
async def live_channel_listener(client: Client, message: Message):
    settings = await db.get_settings()
    if not settings.get("inside_enabled", False): return

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
            
            await db.update_settings({"inside_target_url": url})
            logger.info(f"✅ Cached new Help Us post to Database: {url}")

async def get_target_post(client: Client, settings: dict) -> str:
    return settings.get("inside_target_url")

# ==========================================
# 🤝 VOLUNTARY "HELP US" MENUS
# ==========================================
@Client.on_callback_query(filters.regex(r"^help_us_menu$"))
async def help_us_menu(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    target_url = await get_target_post(client, settings)
    
    if not target_url:
        if callback.from_user.id in Config.ADMINS:
            return await callback.answer("⚠️ Admin: No target URL cached yet. Post a message with the secret words.", show_alert=True)
        return await callback.answer("🙏 Thank you for wanting to help! We don't have an active task right now.", show_alert=True)

    text = (
        "🤝 **Support Our Bot!**\n\n"
        "To keep our servers running and the bot free, you can assist us by forwarding a specific post from our channel.\n\n"
        "Would you be willing to help us out right now?"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I will help", callback_data="help_us_start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="help_us_cancel")]
    ])
    await callback.message.edit_text(text, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"^help_us_start$"))
async def help_us_start(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    target_url = await get_target_post(client, settings)
    
    text = (
        "🙏 **Thank you for your support!**\n\n"
        "Please follow these easy steps:\n"
        "1️⃣ Click the button below to go to our channel.\n"
        "2️⃣ **Forward that exact post back to me here.**\n\n"
        "I am waiting for your forwarded message..."
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="help_us_cancel")]
    ])
    msg = await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    
    # 🚀 ACTIVATE THE VERIFIER LISTENER FOR THIS USER
    VERIFIER_STATE[callback.from_user.id] = {
        "msg_id": msg.id,
        "timestamp": time.time()
    }

@Client.on_callback_query(filters.regex(r"^help_us_cancel$"))
async def help_us_cancel(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in VERIFIER_STATE:
        del VERIFIER_STATE[user_id]
    await callback.message.edit_text("❌ **Help action cancelled.**\n\nNo worries! You can continue using the bot to request and download movies as usual.")

# ==========================================
# 🧠 THE FORWARD INTERCEPTOR
# ==========================================
@Client.on_message(filters.private & filters.forwarded, group=-8)
async def catch_forwarded_verification(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 1. Are they currently volunteering to help?
    if user_id not in VERIFIER_STATE:
        raise ContinuePropagation 
        
    state = VERIFIER_STATE[user_id]
    prompt_msg_id = state["msg_id"]
    timestamp = state["timestamp"]
    
    if time.time() - timestamp > 172800:
        del VERIFIER_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nYour help session timed out. You can click the 'Help Us' button again anytime!"
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation
        
    settings = await db.get_settings()
    user_text = message.text or message.caption or ""
    words = [w.lower().strip(',.') for w in settings.get("inside_words", [])]
    
    try: await message.delete()
    except Exception: pass
    
    # 2. Check Verification
    if any(w in user_text.lower() for w in words):
        del VERIFIER_STATE[user_id]
        
        # 💎 NEW: Grant Dynamic Verification Pass using the new database engine
        await db.grant_verification_pass(user_id)
        
        success_text = (
            f"🎉 **Thank you so much!**\n\n"
            f"Your support means the world to us and helps keep this bot alive.\n\n"
            f"**✅ Reward Unlocked:** You now have temporary unlimited access to direct files!\n\n"
            f"Enjoy your movies! 🍿"
        )
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
        except Exception: await message.reply_text(success_text)
        
    else:
        target_url = settings.get("inside_target_url", "")
        fail_text = (
            f"❌ **That wasn't quite right.**\n\n"
            f"Please make sure you forward the exact post from the channel directly to me.\n\n"
            f"👉 **Try again using this link:** {target_url}"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Open Correct Post", url=target_url)],
            [InlineKeyboardButton("❌ Cancel", callback_data="help_us_cancel")]
        ]) if target_url else None
        
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, fail_text, reply_markup=markup)
        except Exception: await message.reply_text(fail_text, reply_markup=markup)
        
    raise StopPropagation
