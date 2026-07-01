import logging
import time
import string
import random
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from pyrogram.errors import UserIsBlocked, PeerIdInvalid
from database.multi_db import db
from config import Config

# 🚀 Import our new isolated engine!
from plugins.shortener import VERIFICATION_TOKENS, get_shortlink

logger = logging.getLogger(__name__)

# 🧠 Tracks the last caution message sent to keep the PM clean
LAST_CAUTION_MESSAGE = {}

# 🧠 Anti-Spam Tracker: Prevents users from clicking download multiple times quickly
USER_CLICK_TRACKER = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    if not Config.FSUB_CHANNELS: return True
    for channel in Config.FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status.value in ["left", "kicked", "banned", "restricted"]: return False
        except Exception: return False
    return True

async def execute_file_delivery(client: Client, chat_id: int, file_id: str):
    try:
        sent_file = await client.send_cached_media(
            chat_id=chat_id, 
            file_id=file_id, 
            caption="✨ **Here is your requested file.**\n\n🛡 *Provided securely by the Auto-Filter System.*"
        )
        settings = await db.get_settings()
        if settings.get("file_delete_enabled", False):
            delete_time_mins = settings.get("file_delete_time", 10)
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                trigger_ghost_self_destruct(client, chat_id, sent_file.id, delete_time_mins * 60)
                
                # 🧹 1. DELETE the previous caution message if it exists
                if chat_id in LAST_CAUTION_MESSAGE:
                    try:
                        await client.delete_messages(chat_id, LAST_CAUTION_MESSAGE[chat_id])
                    except Exception:
                        pass # Message might have already been deleted by Ghost Mode, which is fine.

                # 📨 2. SEND the new caution message at the bottom
                warning_msg = await client.send_message(
                    chat_id, 
                    f"⏳ **Attention:** This file will automatically self-destruct in {delete_time_mins} minutes to protect our servers. Please forward it to your Saved Messages!"
                )
                
                # 🧠 3. SAVE the new message ID so it can be deleted next time
                LAST_CAUTION_MESSAGE[chat_id] = warning_msg.id
                
                # 👻 4. TRIGGER your existing Ghost Mode timer so it still deletes itself eventually
                trigger_ghost_self_destruct(client, chat_id, warning_msg.id, delete_time_mins * 60)
                
            except Exception as e:
                logger.error(f"Ghost destruct error: {e}")
        return sent_file
    except Exception as send_err:
        raise send_err

@Client.on_callback_query(filters.regex(r"^sendfile_(.+)"))
async def direct_send_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 🛑 ANTI-SPAM DEBOUNCE (3 Seconds)
    current_time = time.time()
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ Processing... please wait a moment before clicking again.", show_alert=False)
    USER_CLICK_TRACKER[user_id] = current_time

    chat_id = callback.message.chat.id
    db_id = callback.data.split("_")[1]

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            try:
                chat = await client.get_chat(channel)
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
            except Exception: invite_link = "https://t.me/telegram"
            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
        buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
        await callback.message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels before downloading files.", reply_markup=InlineKeyboardMarkup(buttons))
        return await callback.answer("You must join the channels first!", show_alert=True)

    file_data = await db.get_file(db_id)
    if not file_data: return await callback.answer("❌ Error: File not found in database.", show_alert=True)

    try:
        await execute_file_delivery(client, user_id, file_data.get("file_id"))
        if callback.message.chat.type.name in ["GROUP", "SUPERGROUP"]:
            await callback.answer("✅ File sent securely to your Private Messages!", show_alert=True)
        else:
            await callback.answer("✅ File retrieved successfully!", show_alert=False)
    except (UserIsBlocked, PeerIdInvalid, Exception) as e:
        bot_me = await client.get_me()
        start_url = f"https://t.me/{bot_me.username}?start=getfile_{db_id}"
        error_text = f"👋 Hey {callback.from_user.mention},\n\nI cannot send files to your PM until you start me! Please click the button below to start the bot and receive your file."
        alert_msg = await client.send_message(chat_id=chat_id, text=error_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Bot to Get File", url=start_url)]]))
        await callback.answer("⚠️ You must start the bot in PM first!", show_alert=True)
        settings = await db.get_settings()
        if settings.get("filter_delete_enabled", False):
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                trigger_ghost_self_destruct(client, chat_id, alert_msg.id, 120)
            except Exception: pass

@Client.on_message(filters.command("start") & filters.private, group=1)
async def deep_link_start(client: Client, message: Message):
    if len(message.command) > 1:
        cmd = message.command[1]
        user_id = message.from_user.id

        # 🛑 ANTI-SPAM DEBOUNCE FOR DEEP LINKS (3 Seconds)
        current_time = time.time()
        if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
            return 
        USER_CLICK_TRACKER[user_id] = current_time

        try: await message.delete()
        except Exception: pass

        if cmd.startswith("verify_"):
            token = cmd.split("_")[1]
            if token in VERIFICATION_TOKENS:
                token_data = VERIFICATION_TOKENS[token]
                
                if token_data["user_id"] == user_id:
                    pass_expiry = time.time() + (24 * 3600)
                    await db.update_user_setting(user_id, "shortener_pass", pass_expiry)
                    del VERIFICATION_TOKENS[token]
                    
                    settings = await db.get_settings()
                    del_enabled = settings.get("filter_delete_enabled", False)
                    del_time = settings.get("filter_delete_time", 5)

                    v_text = "✅ **Verification Successful!** You have unlimited access for 24 hours."
                    if del_enabled: v_text += f"\n\n⏳ *Note: This message will automatically delete in {del_time} minutes.*"

                    success_msg = await message.reply_text(v_text)
                    
                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, success_msg.id, del_time * 60)
                        except Exception: pass

                    pending_file = token_data.get("pending_file")
                    if pending_file:
                        file_data = await db.get_file(pending_file)
                        if file_data: await execute_file_delivery(client, user_id, file_data.get("file_id"))
                return
            else:
                return await message.reply_text("❌ **Invalid or Expired Token.** Please search for the movie again.")

        if cmd.startswith("getfile_"):
            db_id = cmd.split("_")[1]
            
            is_joined = await check_double_fsub(client, user_id)
            if not is_joined:
                buttons = []
                for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                    try:
                        chat = await client.get_chat(channel)
                        invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
                    except Exception: invite_link = "https://t.me/telegram"
                    buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
                buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data=f"retry_getfile_{db_id}")])
                return await message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels before downloading files.", reply_markup=InlineKeyboardMarkup(buttons))

            settings = await db.get_settings()
            if settings.get("shortener_enabled", False):
                u_sett = await db.get_user_settings(user_id)
                pass_time = u_sett.get("shortener_pass", 0)
                
                if time.time() > pass_time:
                    token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                    VERIFICATION_TOKENS[token] = {"user_id": user_id, "pending_file": db_id}
                    bot_me = await client.get_me()
                    verify_link = f"https://t.me/{bot_me.username}?start=verify_{token}"
                    
                    api = settings.get("shortener_api") or ""
                    site = settings.get("shortener_url") or "https://api.gplinks.com/api"
                    
                    if api: short_link = await get_shortlink(verify_link, api, site)
                    else: short_link = verify_link
                        
                    del_enabled = settings.get("filter_delete_enabled", False)
                    del_time = settings.get("filter_delete_time", 5)

                    v_req_text = (
                        "🔒 **Verification Required**\n\n"
                        "To keep this bot alive, please verify your access. This will grant you **24 Hours of Unlimited Downloads!**\n\n"
                        f"👉 [Click Here to Verify]({short_link})\n\n"
                        "➖➖➖➖➖➖➖➖➖➖\n"
                        "🛠 **Admin Note (If links are broken):**\n"
                        "Use `/setshort <API_KEY> <URL_TEMPLATE>` to test and fix your configuration!"
                    )
                    if del_enabled: v_req_text += f"\n\n⏳ *Note: This message will automatically delete in {del_time} minutes.*"

                    req_msg = await message.reply_text(
                        v_req_text, link_preview_options=LinkPreviewOptions(is_disabled=True), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Verify Access", url=short_link)]])
                    )

                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, req_msg.id, del_time * 60)
                        except Exception: pass
                    return

            file_data = await db.get_file(db_id)
            if not file_data: return await message.reply_text("❌ **Error:** File not found in database or has been deleted.")
            await execute_file_delivery(client, user_id, file_data.get("file_id"))

@Client.on_callback_query(filters.regex(r"^retry_getfile_(.+)"))
async def retry_getfile_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id

    # 🛑 ANTI-SPAM DEBOUNCE (3 Seconds)
    current_time = time.time()
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ Checking... please wait a moment.", show_alert=False)
    USER_CLICK_TRACKER[user_id] = current_time

    db_id = callback.data.split("_")[2]
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined: return await callback.answer("❌ You still haven't joined all required channels!", show_alert=True)
    file_data = await db.get_file(db_id)
    if not file_data: return await callback.answer("❌ Error: File not found.", show_alert=True)
    await callback.message.delete()
    await execute_file_delivery(client, user_id, file_data.get("file_id"))

@Client.on_callback_query(filters.regex(r"^check_membership_retry$"))
async def standard_retry_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 🛑 ANTI-SPAM DEBOUNCE (3 Seconds)
    current_time = time.time()
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ Checking... please wait a moment.", show_alert=False)
    USER_CLICK_TRACKER[user_id] = current_time

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined: return await callback.answer("❌ You still haven't joined all required channels!", show_alert=True)
    await callback.message.delete()
    await callback.message.reply_text("✅ Verification successful! Please click the download button again.")
