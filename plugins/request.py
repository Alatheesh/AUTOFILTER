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
    if not settings.get("requests_enabled", True): return await message.reply_text("❌ **Requests are currently disabled by the admins.**")
    if len(message.command) < 2: return await message.reply_text("❌ **Usage:** `/request <Movie Name>`\nExample: `/request Avengers Endgame`")
        
    user = message.from_user
    
    if settings.get("inside_enabled", False) and settings.get("inside_placement", "movie").lower() == "request":
        user_data = await db.get_user_settings(user.id)
        if time.time() > user_data.get("inside_pass_expires", 0):
            from plugins.inside_verifier import get_target_post
            target_url = await get_target_post(client, settings)
            if target_url:
                inside_times = settings.get("inside_times", 5) or 1
                hours_per_pass = 24 / inside_times
                return await message.reply_text(
                    f"🔒 **Security Verification Required!**\n\n"
                    f"To prevent spam and unlock requests for the next **{hours_per_pass:.1f} Hours**, please complete this task:\n\n"
                    f"1️⃣ Click the button below to go to our channel.\n"
                    f"2️⃣ Find the latest post containing our secret words.\n"
                    f"3️⃣ **Forward that exact message directly to me here!**",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                )
            else:
                # 🚨 THE FIX: Completely block execution if the link isn't ready!
                if user.id in Config.ADMINS:
                    await message.reply_text("⚠️ **ADMIN DEBUG:** Inside Feature is ON, but no target URL is cached in MongoDB. Please post a new message in your channel with the trigger word!")
                else:
                    await message.reply_text("⏳ Verification system is starting up. Please try again later.")
                return 
    
    movie_name = message.text.split(maxsplit=1)[1]
    req_text = f"🔔 **NEW MOVIE REQUEST**\n\n👤 **User:** {user.first_name} (`{user.id}`)\n🎬 **Requested:** `{movie_name}`"
    
    if TARGET_ADMIN:
        try:
            await client.send_message(TARGET_ADMIN, req_text)
            await message.reply_text(f"✅ **Success!** Your request for `{movie_name}` has been delivered to the admin team.")
        except Exception as e: await message.reply_text("❌ **Error:** Could not deliver request to the admin team.")
    else: await message.reply_text("❌ **Error:** No admin configured to receive requests.")

@Client.on_callback_query(filters.regex(r"^req_(.+)"))
async def request_button_callback(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    if not settings.get("requests_enabled", True): return await callback.answer("❌ Requests are currently disabled.", show_alert=True)
        
    user = callback.from_user
    
    if settings.get("inside_enabled", False) and settings.get("inside_placement", "movie").lower() == "request":
        user_data = await db.get_user_settings(user.id)
        if time.time() > user_data.get("inside_pass_expires", 0):
            from plugins.inside_verifier import get_target_post
            target_url = await get_target_post(client, settings)
            if target_url:
                await callback.message.edit_text(
                    f"🔒 **Security Verification Required!**\n\n"
                    f"To prevent spam and unlock requests, please click the button below, find the post with our secret words, and **forward it to me here**.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                )
                return await callback.answer("Verification required!", show_alert=True)
            else:
                if user.id in Config.ADMINS:
                    await client.send_message(user.id, "⚠️ **ADMIN DEBUG:** Inside Feature is ON, but no link is cached in MongoDB. Please post an ad in your channel first!")
                return await callback.answer("⏳ System starting up. Please try again later.", show_alert=True)
    
    movie_name = callback.data.split("req_", 1)[1]
    req_text = f"🔔 **NEW MOVIE REQUEST**\n\n👤 **User:** {user.first_name} (`{user.id}`)\n🎬 **Requested:** `{movie_name}`"
    
    if TARGET_ADMIN:
        try:
            await client.send_message(TARGET_ADMIN, req_text)
            await callback.message.edit_text(f"✅ **You successfully requested:** `{movie_name}`\n\nThe admins have been notified!")
            await callback.answer("✅ Request successfully delivered!", show_alert=True)
        except Exception as e: await callback.answer("❌ Error delivering request.", show_alert=True)
    else: await callback.answer("❌ No admin configured.", show_alert=True)
