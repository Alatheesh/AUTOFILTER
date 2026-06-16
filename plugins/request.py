import time
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

TARGET_ADMIN = Config.ADMINS[0] if Config.ADMINS else None

@Client.on_message(filters.command("request") & filters.private)
async def request_command(client: Client, message: Message):
    settings = await db.get_settings()
    
    if not settings.get("requests_enabled", True):
        return await message.reply_text("❌ **Requests are currently disabled by the admins.**")
    
    if len(message.command) < 2:
        return await message.reply_text("❌ **Usage:** `/request <Movie Name>`\nExample: `/request Avengers Endgame`")
        
    movie_name = message.text.split(maxsplit=1)[1]
    user = message.from_user
    
    # --- INSIDE FEATURE: REQUEST PLACEMENT ---
    if settings.get("inside_enabled", False) and settings.get("inside_placement", "request") == "request":
        user_data = await db.get_user_settings(user.id)
        if time.time() > user_data.get("inside_pass_expires", 0):
            from plugins.inside_verifier import get_target_post
            target_url = await get_target_post(client, settings)
            if target_url:
                return await message.reply_text(
                    f"🔒 **Security Verification Required!**\n\n"
                    f"To prove you are human and submit requests, please click the button below, find the post with our secret words, and **forward it to me here**.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                )
    # ----------------------------------------
    
    req_text = (
        f"🔔 **NEW MOVIE REQUEST**\n\n"
        f"👤 **User:** {user.first_name} (`{user.id}`)\n"
        f"🎬 **Requested:** `{movie_name}`"
    )
    
    if TARGET_ADMIN:
        try:
            await client.send_message(TARGET_ADMIN, req_text)
            await message.reply_text(f"✅ **Success!** Your request for `{movie_name}` has been delivered to the admin team.")
        except Exception as e:
            logger.error(f"Failed to send request to admin: {e}")
            await message.reply_text("❌ **Error:** Could not deliver request to the admin team.")
    else:
         await message.reply_text("❌ **Error:** No admin configured to receive requests.")

@Client.on_callback_query(filters.regex(r"^req_(.+)"))
async def request_button_callback(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    
    if not settings.get("requests_enabled", True):
        return await callback.answer("❌ Requests are currently disabled by the admins.", show_alert=True)
        
    movie_name = callback.data.split("req_", 1)[1]
    user = callback.from_user
    
    # --- INSIDE FEATURE: REQUEST PLACEMENT ---
    if settings.get("inside_enabled", False) and settings.get("inside_placement", "request") == "request":
        user_data = await db.get_user_settings(user.id)
        if time.time() > user_data.get("inside_pass_expires", 0):
            from plugins.inside_verifier import get_target_post
            target_url = await get_target_post(client, settings)
            if target_url:
                await callback.message.edit_text(
                    f"🔒 **Security Verification Required!**\n\n"
                    f"To prove you are human and submit requests, please click the button below, find the post with our secret words, and **forward it to me here**.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                )
                return await callback.answer("Verification required!", show_alert=True)
    # ----------------------------------------
    
    req_text = (
        f"🔔 **NEW MOVIE REQUEST**\n\n"
        f"👤 **User:** {user.first_name} (`{user.id}`)\n"
        f"🎬 **Requested:** `{movie_name}`"
    )
    
    if TARGET_ADMIN:
        try:
            await client.send_message(TARGET_ADMIN, req_text)
            await callback.message.edit_text(f"✅ **You successfully requested:** `{movie_name}`\n\nThe admins have been notified and will upload it soon!")
            await callback.answer("✅ Request successfully delivered to the admin team!", show_alert=True)
        except Exception as e:
            logger.error(f"Failed to send request to admin: {e}")
            await callback.answer("❌ Error delivering request.", show_alert=True)
    else:
        await callback.answer("❌ No admin configured to receive requests.", show_alert=True)
