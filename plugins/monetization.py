import logging
import time
import string
import random
import aiohttp
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserIsBlocked, PeerIdInvalid
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# In-memory storage for shortener tokens
VERIFICATION_TOKENS = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    """Checks if the user has joined the forced subscription channels."""
    if not Config.FSUB_CHANNELS:
        return True
    for channel in Config.FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status.value in ["left", "kicked", "banned", "restricted"]:
                return False
        except Exception:
            # If the bot is not in the channel or user hasn't joined
            return False
    return True

async def get_shortlink(url: str, api: str, site: str) -> str:
    """Contacts the Shortener API to generate a monetized link."""
    try:
        async with aiohttp.ClientSession() as session:
            api_url = f"{site}?api={api}&url={url}"
            async with session.get(api_url) as response:
                data = await response.json()
                if data.get("status") == "success" or data.get("status"):
                    return data.get("shortenedUrl", url)
    except Exception as e:
        logger.error(f"Shortener API Error: {e}")
    return url

async def execute_file_delivery(client: Client, chat_id: int, file_id: str):
    """Sends the file, handles caution cleanup, and sets self-destruct timers."""
    try:
        sent_file = await client.send_cached_media(
            chat_id=chat_id, 
            file_id=file_id, 
            caption="✨ **Here is your requested file.**\n\n🛡 *Provided securely by the Auto-Filter System.*"
        )
        
        # 🔥 RESTORED: AUTO DELETE GHOST MODE LOGIC
        settings = await db.get_settings()
        if settings.get("file_delete_enabled", False):
            delete_time_mins = settings.get("file_delete_time", 10)
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                
                # Delete the actual file
                trigger_ghost_self_destruct(client, chat_id, sent_file.id, delete_time_mins * 60)
                
                # Send and delete the warning message
                warning_msg = await client.send_message(
                    chat_id, 
                    f"⏳ **Attention:** This file will automatically self-destruct in {delete_time_mins} minutes to protect our servers. Please forward it to your Saved Messages!"
                )
                trigger_ghost_self_destruct(client, chat_id, warning_msg.id, delete_time_mins * 60)
            except Exception as e:
                logger.error(f"Ghost destruct error: {e}")
                
        return sent_file
    except Exception as send_err:
        # We raise the error up so the callback handler can catch it if the user hasn't started the bot!
        raise send_err

# -----------------------------------------------------
# 🔥 HYBRID DIRECT FILE BUTTON LISTENER (PM DELIVERY)
# -----------------------------------------------------
@Client.on_callback_query(filters.regex(r"^sendfile_(.+)"))
async def direct_send_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    db_id = callback.data.split("_")[1]

    # Verify FSub (Since they bypassed /start)
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            try:
                chat = await client.get_chat(channel)
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
            except Exception: 
                invite_link = "https://t.me/telegram"
            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
        buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
        await callback.message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels before downloading files.", reply_markup=InlineKeyboardMarkup(buttons))
        return await callback.answer("You must join the channels first!", show_alert=True)

    file_data = await db.get_file(db_id)
    if not file_data:
        return await callback.answer("❌ Error: File not found in database.", show_alert=True)

    try:
        # 🚀 TRY TO SEND FILE DIRECTLY TO THEIR PM
        await execute_file_delivery(client, user_id, file_data.get("file_id"))
        
        # Determine if they clicked it in a group vs already in PM
        if callback.message.chat.type.name in ["GROUP", "SUPERGROUP"]:
            await callback.answer("✅ File sent securely to your Private Messages!", show_alert=True)
        else:
            await callback.answer("✅ File retrieved successfully!", show_alert=False)
            
    except (UserIsBlocked, PeerIdInvalid, Exception) as e:
        # ❌ FAILED: User hasn't started bot, or blocked it.
        bot_me = await client.get_me()
        start_url = f"https://t.me/{bot_me.username}?start=getfile_{db_id}"
        
        error_text = (
            f"👋 Hey {callback.from_user.mention},\n\n"
            f"I cannot send files to your PM until you start me! Please click the button below to start the bot and receive your file."
        )
        
        # Send notification in group
        alert_msg = await client.send_message(
            chat_id=chat_id,
            text=error_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Bot to Get File", url=start_url)]])
        )
        await callback.answer("⚠️ You must start the bot in PM first!", show_alert=True)
        
        # Auto-delete the alert message after 2 minutes to prevent group spam
        settings = await db.get_settings()
        if settings.get("filter_delete_enabled", False):
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                trigger_ghost_self_destruct(client, chat_id, alert_msg.id, 120)
            except Exception:
                logger.warning("Ghost self destruct failed for alert message.")


# -----------------------------------------------------
# 🔥 RESTORED: DEEP LINK & SHORTENER LOGIC
# -----------------------------------------------------
@Client.on_message(filters.command("start") & filters.private, group=1)
async def deep_link_start(client: Client, message: Message):
    if len(message.command) > 1:
        cmd = message.command[1]

        # 🚀 NEW BULK DELIVERY HANDLER
        if cmd.startswith("bulk_"):
            user_id = message.from_user.id
            
            # Verify Force Sub first
            is_joined = await check_double_fsub(client, user_id)
            if not is_joined:
                buttons = []
                for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                    try:
                        chat = await client.get_chat(channel)
                        invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
                    except Exception: 
                        invite_link = "https://t.me/telegram"
                    buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
                
                return await message.reply_text("🛑 **Lock Warning:**\nYou must join our official channels before downloading bulk files.", reply_markup=InlineKeyboardMarkup(buttons))

            file_ids = cmd.split("bulk_")[1].split("-")
            
            # Send a status message so they know the bot is working
            status_msg = await message.reply_text(f"📦 **Queueing {len(file_ids)} files...**\nSending them securely to avoid group spam. Please wait!")
            
            successful = 0
            for db_id in file_ids:
                if not db_id: continue
                file_data = await db.get_file(db_id) 
                if file_data:
                    await execute_file_delivery(client, user_id, file_data.get("file_id"))
                    successful += 1
                    # 🛡️ ANTI-SPAM SHIELD: 0.5s delay to prevent Telegram FloodWait limits!
                    await asyncio.sleep(0.5) 
                    
            return await status_msg.edit_text(f"✅ **Successfully delivered {successful} files directly to you!**")
        
        # --- TOKEN VERIFICATION (Returning from Shortener) ---
        if cmd.startswith("verify_"):
            token = cmd.split("_")[1]
            if token in VERIFICATION_TOKENS:
                user_id = message.from_user.id
                token_data = VERIFICATION_TOKENS[token]
                
                if token_data["user_id"] == user_id:
                    # Grant pass for 24 hours
                    pass_expiry = time.time() + (24 * 3600)
                    await db.update_user_setting(user_id, "shortener_pass", pass_expiry)
                    del VERIFICATION_TOKENS[token]
                    
                    await message.reply_text("✅ **Verification Successful!** You have unlimited access for 24 hours.")
                    
                    # Deliver the pending file automatically after verification
                    pending_file = token_data.get("pending_file")
                    if pending_file:
                        file_data = await db.get_file(pending_file)
                        if file_data:
                            await execute_file_delivery(client, user_id, file_data.get("file_id"))
                return
            else:
                return await message.reply_text("❌ **Invalid or Expired Token.** Please search for the movie again.")

        # --- GET FILE VIA BOT START ---
        if cmd.startswith("getfile_"):
            user_id = message.from_user.id
            db_id = cmd.split("_")[1]
            
            # 1. Verify FSub 
            is_joined = await check_double_fsub(client, user_id)
            if not is_joined:
                buttons = []
                for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                    try:
                        chat = await client.get_chat(channel)
                        invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
                    except Exception: 
                        invite_link = "https://t.me/telegram"
                    buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
                
                buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data=f"retry_getfile_{db_id}")])
                return await message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels before downloading files.", reply_markup=InlineKeyboardMarkup(buttons))

            # 2. Check Shortener Status
            settings = await db.get_settings()
            if settings.get("shortener_enabled", False):
                u_sett = await db.get_user_settings(user_id)
                pass_time = u_sett.get("shortener_pass", 0)
                
                # If pass is expired, force shortener
                if time.time() > pass_time:
                    token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                    VERIFICATION_TOKENS[token] = {"user_id": user_id, "pending_file": db_id}
                    
                    bot_me = await client.get_me()
                    verify_link = f"https://t.me/{bot_me.username}?start=verify_{token}"
                    
                    api = settings.get("shortener_api", "")
                    site = settings.get("shortener_url", "https://gplinks.in/api")
                    
                    if api:
                        short_link = await get_shortlink(verify_link, api, site)
                    else:
                        short_link = verify_link
                        
                    return await message.reply_text(
                        "🔒 **Verification Required**\n\n"
                        "To keep this bot alive, please verify your access. This will grant you **24 Hours of Unlimited Downloads!**\n\n"
                        f"👉 [Click Here to Verify]({short_link})",
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Verify Access", url=short_link)]])
                    )

            # 3. Deliver File (If no shortener or pass is valid)
            file_data = await db.get_file(db_id)
            if not file_data:
                return await message.reply_text("❌ **Error:** File not found in database or has been deleted.")
                
            await execute_file_delivery(client, user_id, file_data.get("file_id"))

@Client.on_callback_query(filters.regex(r"^retry_getfile_(.+)"))
async def retry_getfile_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    db_id = callback.data.split("_")[2]
    
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        return await callback.answer("❌ You still haven't joined all required channels!", show_alert=True)
        
    file_data = await db.get_file(db_id)
    if not file_data:
        return await callback.answer("❌ Error: File not found.", show_alert=True)
        
    await callback.message.delete()
    await execute_file_delivery(client, user_id, file_data.get("file_id"))

@Client.on_callback_query(filters.regex(r"^check_membership_retry$"))
async def standard_retry_callback(client: Client, callback: CallbackQuery):
    is_joined = await check_double_fsub(client, callback.from_user.id)
    if not is_joined:
        return await callback.answer("❌ You still haven't joined all required channels!", show_alert=True)
        
    await callback.message.delete()
    await callback.message.reply_text("✅ Verification successful! Please click the download button again.")
