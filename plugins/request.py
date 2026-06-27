import time
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# 🧠 State Machine for Clean Interactive Requests
REQUEST_STATE = {}

# ==========================================
# 📢 DIRECT COMMAND AND INTERACTIVE WIZARD
# ==========================================
@Client.on_message(filters.command("request") & filters.private)
async def request_command(client: Client, message: Message):
    settings = await db.get_settings()
    if not settings.get("requests_enabled", True): 
        await message.reply_text("❌ **Requests are currently disabled by the admins.**")
        raise StopPropagation
        
    user = message.from_user
        
    # Fast Route (If they provided the name in the command)
    if len(message.command) >= 2:
        movie_name = message.text.split(maxsplit=1)[1]
        req_text = f"#Movie_Request\n\n🔔 **NEW MOVIE REQUEST**\n\n👤 **User:** {user.first_name} (`{user.id}`)\n🎬 **Requested:**\n`{movie_name}`"
        
        if hasattr(Config, "LOG_CHANNEL") and Config.LOG_CHANNEL:
            try:
                await client.send_message(Config.LOG_CHANNEL, req_text)
                await message.reply_text("✅ **Success!** Your request has been delivered to the admin team.")
            except Exception: 
                await message.reply_text("❌ **Error:** Could not deliver request. Make sure I am an Admin in the Logs Channel!")
        else: 
            await message.reply_text("❌ **Error:** No log channel configured to receive requests.")
        raise StopPropagation

    # Clean Interactive Route
    prompt = await message.reply_text(
        "📝 **Submit a Movie Request**\n\n"
        "Please reply with the details of the movie you want. For the fastest response, try to use this format:\n\n"
        "`Name = `\n"
        "`Year = `\n"
        "`Language = `\n\n"
        "*(Note: You can type it however you want, but this format helps us find it faster! Click Cancel to abort).* ",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_request_flow")]])
    )
    
    REQUEST_STATE[user.id] = {
        "message_id": prompt.id,
        "timestamp": time.time()
    }
    raise StopPropagation

# ==========================================
# 🧠 THE CLEAN UI LISTENER
# ==========================================
@Client.on_message(filters.text & filters.private, group=-4)
async def interactive_request_listener(client: Client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in REQUEST_STATE:
        raise ContinuePropagation

    if message.text.startswith("/"):
        del REQUEST_STATE[user_id]
        raise ContinuePropagation

    state = REQUEST_STATE[user_id]
    prompt_msg_id = state["message_id"]
    timestamp = state["timestamp"]

    if time.time() - timestamp > 172800:
        del REQUEST_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis request prompt is older than 48 hours. Please run `/request` again."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation 

    user_request_text = message.text.strip()
    del REQUEST_STATE[user_id]
    
    try: await message.delete() 
    except Exception: pass

    user = message.from_user
    admin_text = f"#Movie_Request\n\n🔔 **NEW MOVIE REQUEST**\n\n👤 **User:** {user.first_name} (`{user.id}`)\n🎬 **Requested Details:**\n\n{user_request_text}"
    
    if hasattr(Config, "LOG_CHANNEL") and Config.LOG_CHANNEL:
        try:
            await client.send_message(Config.LOG_CHANNEL, admin_text)
            success_msg = f"✅ **Request Sent Successfully!**\n\n**Your Request:**\n_{user_request_text}_\n\nThe admin team has been notified!"
            try: await client.edit_message_text(message.chat.id, prompt_msg_id, success_msg)
            except Exception: await message.reply_text(success_msg)
        except Exception: 
            fail_msg = "❌ **Error:** Could not deliver request. Make sure I am an Admin in the Logs Channel!"
            try: await client.edit_message_text(message.chat.id, prompt_msg_id, fail_msg)
            except Exception: await message.reply_text(fail_msg)
    else:
        fail_msg = "❌ **Error:** No log channel configured to receive requests."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, fail_msg)
        except Exception: await message.reply_text(fail_msg)

    raise StopPropagation

@Client.on_callback_query(filters.regex("^cancel_request_flow$"))
async def cancel_request_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in REQUEST_STATE:
        del REQUEST_STATE[user_id]
    await callback.message.edit_text("❌ **Request Cancelled.**\n\nYou can use `/request` whenever you're ready.")
    await callback.answer("Cancelled", show_alert=False)

# ==========================================
# 🔘 INLINE BUTTON CALLBACK (From Search Results)
# ==========================================
@Client.on_callback_query(filters.regex(r"^req_(.+)"))
async def request_button_callback(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    if not settings.get("requests_enabled", True): 
        return await callback.answer("❌ Requests are currently disabled.", show_alert=True)
        
    user = callback.from_user
    movie_name = callback.data.split("req_", 1)[1]
    req_text = f"#Movie_Request\n\n🔔 **NEW MOVIE REQUEST (From Search Button)**\n\n👤 **User:** {user.first_name} (`{user.id}`)\n🎬 **Requested:** `{movie_name}`"
    
    if hasattr(Config, "LOG_CHANNEL") and Config.LOG_CHANNEL:
        try:
            await client.send_message(Config.LOG_CHANNEL, req_text)
            await callback.message.edit_text(f"✅ **You successfully requested:**\n`{movie_name}`\n\nThe admins have been notified!")
            await callback.answer("✅ Request successfully delivered!", show_alert=True)
        except Exception: 
            await callback.answer("❌ Error delivering request to Logs.", show_alert=True)
    else: 
        await callback.answer("❌ No log channel configured.", show_alert=True)
