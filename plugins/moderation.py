import time
import re
import asyncio
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.handlers import MessageHandler
from database.multi_db import db
from config import Config

# --- IN-MEMORY TRACKERS ---
LINK_TRACKER = {}  
SPAM_TRACKER = {}
SCRAPER_TRACKER = {} 

# 🧠 State Machine for Clean Interactive Admin Prompts
ADMIN_STATE = {}

async def is_group_admin(client, chat_id, user_id):
    if user_id in Config.ADMINS: return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except: return False

async def log_to_channel(client, text, markup=None):
    if Config.LOG_CHANNEL:
        try: await client.send_message(Config.LOG_CHANNEL, text, reply_markup=markup)
        except Exception: pass

# ==========================================
# 📊 USER STATS & INFO
# ==========================================
@Client.on_message(filters.command("userstats") & filters.user(Config.ADMINS))
async def get_user_stats(client: Client, message: Message):
    total_users = await db.users.count_documents({})
    total_muted = await db.punishments.count_documents({"type": "mute"})
    total_banned = await db.punishments.count_documents({"type": "ban"})
    
    stats_text = (
        f"📊 **Global Users Stats**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"🟢 Active Users: `{total_users - total_banned}`\n"
        f"🔇 Currently Muted: `{total_muted}`\n"
        f"🚫 Permanently Banned: `{total_banned}`\n\n"
        f"*(Manage Auto-Mute and Auto-Ban triggers in `/settings`)*"
    )
    await message.reply_text(stats_text)
    raise StopPropagation

@Client.on_message(filters.command("info") & filters.user(Config.ADMINS))
async def get_info(client: Client, message: Message):
    target = message.reply_to_message.from_user.id if message.reply_to_message else (int(message.command[1]) if len(message.command)>1 else message.from_user.id)
    
    # 1. Fetch live profile data from Telegram
    try:
        tg_user = await client.get_users(target)
        first_name = tg_user.first_name or ""
        last_name = tg_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip() or "Unknown"
        username = f"@{tg_user.username}" if tg_user.username else "No Username"
        user_mention = tg_user.mention("Emergency DM Link")
        dc_id = tg_user.dc_id or "Unknown"
        is_premium = "Yes ⭐️" if tg_user.is_premium else "No"
        photo_id = tg_user.photo.big_file_id if tg_user.photo else None
    except Exception:
        full_name = "Unknown (Not in bot cache)"
        username = "N/A"
        user_mention = f"[Emergency DM Link](tg://user?id={target})"
        dc_id = "N/A"
        is_premium = "N/A"
        photo_id = None

    # 2. Fetch usage data from your database
    user_data = await db.get_user_settings(target)
    status, reason, expiry, scope = await db.check_punishment(target, "global")
    
    total_searches = user_data.get('total_searches', 0)
    total_requests = user_data.get('total_requests', 0)
    joined_date = user_data.get('joined_date', "Unknown (Legacy User)")
    
    text = (
        f"👤 **User Intelligence Report**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**ID:** `{target}`\n"
        f"**Name:** {full_name}\n"
        f"**Username:** {username}\n"
        f"**Telegram DC:** `{dc_id}`\n"
        f"**Premium:** `{is_premium}`\n"
        f"**Contact:** {user_mention}\n\n"
        f"📈 **Bot Usage Statistics:**\n"
        f"• **Joined:** `{joined_date}`\n"
        f"• **Total Searches:** `{total_searches}`\n"
        f"• **Movies Requested:** `{total_requests}`\n\n"
        f"🌍 **Global Status:** `{status.upper() if status else 'CLEAN'}`"
    )
    if status == "mute": text += f"\n⏳ **Unlocks:** <t:{int(expiry)}:R>"
    if status: text += f"\n📝 **Reason:** {reason}"
    
    # 3. Send with Photo if available, otherwise just text
    if photo_id:
        try: await message.reply_photo(photo=photo_id, caption=text)
        except Exception: await message.reply_text(text)
    else:
        await message.reply_text(text)
    raise StopPropagation

@Client.on_message(filters.command("id"))
async def get_id(client: Client, message: Message):
    text = f"🆔 **Your ID:** `{message.from_user.id}`\n"
    if message.chat.type != ChatType.PRIVATE: text += f"👥 **Group ID:** `{message.chat.id}`"
    await message.reply_text(text)
    raise StopPropagation

# ==========================================
# ⚙️ CONFIGURATION CAPTURE (Clean UI Upgrade)
# ==========================================
@Client.on_callback_query(filters.regex(r"^mod_(badwords|limits)$"))
async def mod_settings_btn(client: Client, callback: CallbackQuery):
    action = callback.matches[0].group(1)
    
    ADMIN_STATE[callback.from_user.id] = {
        "action": action,
        "message_id": callback.message.id,
        "timestamp": time.time()
    }
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_mod_state")]])
    if action == "badwords":
        await callback.message.edit_text("📝 **Send me the list of bad words separated by commas.**\nExample: `porn, bet, casino`", reply_markup=markup)
    else:
        await callback.message.edit_text("⏱ **Send me the number of warnings a user can get before they are Auto-Muted.**\nExample: `3`", reply_markup=markup)
    await callback.answer()

@Client.on_callback_query(filters.regex("^cancel_mod_state$"))
async def cancel_mod_state_handler(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in ADMIN_STATE:
        del ADMIN_STATE[user_id]
    await callback.message.edit_text("❌ **Configuration Cancelled.**\n\nYou can restart it from the settings menu.")
    await callback.answer("Cancelled", show_alert=False)

@Client.on_message(filters.private & filters.text & filters.user(Config.ADMINS), group=-5)
async def admin_state_catcher(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_STATE:
        raise ContinuePropagation

    if message.text.startswith("/"):
        del ADMIN_STATE[user_id]
        raise ContinuePropagation

    state_data = ADMIN_STATE[user_id]
    action = state_data["action"]
    prompt_msg_id = state_data["message_id"]
    timestamp = state_data["timestamp"]

    # 🛑 48-Hour Security Check
    if time.time() - timestamp > 172800:
        del ADMIN_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please restart from the settings."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation
        
    text_input = message.text.strip()
    del ADMIN_STATE[user_id]
    try: await message.delete()
    except Exception: pass

    if action == "badwords":
        words = [w.strip().lower() for w in text_input.split(",") if w.strip()]
        await db.update_settings({"bad_words": words})
        success_text = f"✅ **Bad words custom dictionary updated:**\n`{', '.join(words)}`"
    elif action == "limits":
        try:
            limit = int(text_input)
            await db.update_settings({"strike_limit": limit})
            success_text = f"✅ **Warning Strikeout limit set to:** `{limit}`"
        except Exception:
            success_text = "⚠️ **Invalid Input:** Please send a valid number. Start over from settings."

    try: await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
    except Exception: await message.reply_text(success_text)
    raise StopPropagation

# ==========================================
# 🛡️ MANUAL COMMANDS (With Full Time Parsing)
# ==========================================
@Client.on_message(filters.command(["warn", "mute", "ban", "unwarn", "unmute", "unban"]))
async def contextual_punishment(client: Client, message: Message):
    cmd = message.command[0].lower()
    is_global = message.chat.type == ChatType.PRIVATE
    chat_id = "global" if is_global else str(message.chat.id)
    
    if is_global and message.from_user.id not in Config.ADMINS: 
        raise StopPropagation
    if not is_global and not await is_group_admin(client, message.chat.id, message.from_user.id): 
        raise StopPropagation

    target_user = None
    time_str = ""
    reason = "Manual Admin Action"

    # Smart Argument Parsing (Handles both replies and direct ID)
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user.id
        if len(message.command) > 1: time_str = message.command[1]
        if len(message.command) > 2: reason = " ".join(message.command[2:])
    else:
        if len(message.command) < 2: 
            await message.reply_text(f"⚠️ **Usage:** `/{cmd} <user_id> [time] [reason]`")
            raise StopPropagation
        try: target_user = int(message.command[1])
        except ValueError: 
            await message.reply_text("⚠️ Invalid User ID.")
            raise StopPropagation
        if len(message.command) > 2: time_str = message.command[2]
        if len(message.command) > 3: reason = " ".join(message.command[3:])

    if target_user in Config.ADMINS: 
        await message.reply_text("🛑 Cannot punish a System Administrator.")
        raise StopPropagation

    # Time Parsing Engine
    duration_secs = 86400 # 1 day default
    if time_str:
        if time_str.endswith('d'): duration_secs = int(time_str[:-1]) * 86400
        elif time_str.endswith('h'): duration_secs = int(time_str[:-1]) * 3600
        elif time_str.endswith('m'): duration_secs = int(time_str[:-1]) * 60
        else:
            try: duration_secs = int(time_str) * 3600 # Default to hours if no letter
            except: reason = f"{time_str} {reason}" # If it wasn't a time, it was part of the reason
    
    if cmd == "warn":
        warns = await db.add_punishment(target_user, chat_id, "warn", reason=reason)
        settings = await db.get_settings()
        limit = settings.get("strike_limit", 5) 
        
        if warns >= limit:
            await db.add_punishment(target_user, chat_id, "mute", expiry_ts=time.time()+86400, reason="Exceeded warnings limit")
            await message.reply_text(f"🔴 User `{target_user}` hit {limit}/{limit} warnings and has been **Auto-Muted**.")
        else:
            await message.reply_text(f"⚠️ User `{target_user}` warned ({warns}/{limit}).\nReason: {reason}")
            
    elif cmd == "mute":
        await db.add_punishment(target_user, chat_id, "mute", expiry_ts=time.time() + duration_secs, reason=reason)
        btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unmute", callback_data=f"admin_unmute_{chat_id}_{target_user}")]])
        await message.reply_text(f"🔇 User `{target_user}` muted.\nUnlocks: <t:{int(time.time() + duration_secs)}:R>", reply_markup=btn)
        if is_global: await log_to_channel(client, f"#muteuser `{target_user}`\nReason: {reason}", InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unmute", callback_data=f"log_unmute_{target_user}")]]))

    elif cmd == "ban":
        await db.add_punishment(target_user, chat_id, "ban", reason=reason)
        btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban_{chat_id}_{target_user}")]])
        await message.reply_text(f"🚫 User `{target_user}` banned.\nReason: {reason}", reply_markup=btn)
        if is_global: await log_to_channel(client, f"#banuser `{target_user}`\nReason: {reason}", InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unban", callback_data=f"log_unban_{target_user}")]]))

    elif cmd in ["unwarn", "unmute", "unban"]:
        await db.remove_punishment(target_user, chat_id, cmd.replace("un", ""))
        await message.reply_text(f"✅ User `{target_user}` successfully {cmd}ed.")
        
    raise StopPropagation

# ==========================================
# 🚨 AUTO-TRIGGERS (Spam, Links, Bad Words)
# ==========================================
@Client.on_message(filters.text & filters.group, group=-1)
async def auto_moderation_triggers(client: Client, message: Message):
    user_id = message.from_user.id
    chat_id = str(message.chat.id)
    text = message.text.lower()
    current_time = time.time()
    
    settings = await db.get_settings()
    
    # 1. 🛑 THE SPAM FILTER (5 messages in 3 seconds -> 5 Hour Mute)
    if user_id not in SPAM_TRACKER: SPAM_TRACKER[user_id] = []
    SPAM_TRACKER[user_id].append(current_time)
    SPAM_TRACKER[user_id] = [t for t in SPAM_TRACKER[user_id] if current_time - t < 3] 
    
    if len(SPAM_TRACKER[user_id]) >= 5:
        await message.delete()
        await db.add_punishment(user_id, chat_id, "mute", expiry_ts=current_time + (5 * 3600), reason="Flooding/Spamming the chat")
        alert = await message.reply_text(f"🔇 {message.from_user.mention} was **Auto-Muted for 5 Hours** due to extreme message spam.")
        await asyncio.sleep(10)
        return await alert.delete()

    # 2. 🤬 THE BAD WORDS FILTER
    bad_words = settings.get("bad_words", [])
    if any(word in text for word in bad_words if word.strip()):
        await message.delete()
        await db.add_punishment(user_id, chat_id, "mute", expiry_ts=current_time + (3 * 86400), reason="Prohibited Language")
        alert = await message.reply_text(f"🔇 {message.from_user.mention} was **Auto-Muted for 3 Days** for using prohibited bad words.")
        await asyncio.sleep(10)
        return await alert.delete()

    # 3. 🔗 THE LINK SPAMMER
    if re.search(r"(https?://|t\.me/|www\.)", text):
        if user_id not in LINK_TRACKER: LINK_TRACKER[user_id] = []
        LINK_TRACKER[user_id].append(current_time)
        LINK_TRACKER[user_id] = [t for t in LINK_TRACKER[user_id] if current_time - t < 120]
        
        count = len(LINK_TRACKER[user_id])
        if count == 1:
            warn = await message.reply_text(f"⚠️ {message.from_user.mention}, please do not send links here. Search by movie name only.")
            await asyncio.sleep(5)
            await warn.delete()
        elif count >= 3:
            await message.delete()
            await db.add_punishment(user_id, chat_id, "mute", expiry_ts=current_time + 86400, reason="Repeated Link Spamming")
            alert = await message.reply_text(f"🔇 {message.from_user.mention} was **Auto-Muted for 24h** for ignoring link warnings.")
            await asyncio.sleep(10)
            await alert.delete()

# ==========================================
# ⚖️ APPEALS SYSTEM (Anti-Spam & Sync Upgrades)
# ==========================================
@Client.on_callback_query(filters.regex(r"^appeal_(global|local)_(.+)$"))
async def process_appeal(client: Client, callback: CallbackQuery):
    scope = callback.matches[0].group(1)
    ptype = callback.matches[0].group(2)
    user_id = callback.from_user.id
    chat_id = str(callback.message.chat.id)
    
    await callback.answer("✅ Your appeal has been submitted to the administration.", show_alert=True)
    
    # 🚀 FIX 1: Prevent spam by modifying the user's message to remove the button!
    try:
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ **Appeal Submitted.** Please wait for admin review.",
            reply_markup=None
        )
    except Exception: pass
    
    if scope == "global":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"log_un{ptype}_{user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"log_reject_{user_id}")]])
        await log_to_channel(client, f"⚖️ **NEW GLOBAL APPEAL**\n\n👤 User: `{user_id}`\nType: **{ptype.upper()}**\n\nPlease review:", markup)
    else:
        g_sett = await db.get_group_settings(int(chat_id))
        connected_by = g_sett.get("connected_by")
        if connected_by:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"admin_un{ptype}_{chat_id}_{user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"admin_reject_{chat_id}_{user_id}")]])
            try: await client.send_message(connected_by, f"⚖️ **GROUP APPEAL**\n\nA user appealed a punishment in your group.\n\n👤 User: `{user_id}`\n👥 Group: `{callback.message.chat.title}`\nType: **{ptype.upper()}**", reply_markup=markup)
            except: await log_to_channel(client, f"⚖️ **GROUP APPEAL (Fallback)**\nUser `{user_id}` appealed in group `{chat_id}`.")

@Client.on_callback_query(filters.regex(r"^(log|admin)_(unban|unmute|reject)_(.+)$"))
async def admin_appeal_actions(client: Client, callback: CallbackQuery):
    action = callback.matches[0].group(2)
    data_parts = callback.data.split("_")
    source = data_parts[0]
    
    if source == "log":
        target_user = int(data_parts[2])
        chat_id = "global"
    else:
        chat_id = data_parts[2]
        target_user = int(data_parts[3])

    # 🚀 FIX 2: Check Database Sync! Prevent double actions if manually unmuted/unbanned.
    status, reason, expiry, p_scope = await db.check_punishment(target_user, chat_id)
    expected_status = action.replace("un", "") # Turns "unban" into "ban"
    
    if action != "reject" and status != expected_status:
        await callback.answer(f"⚠️ User is already {action}ed manually!", show_alert=True)
        return await callback.message.edit_text(callback.message.text + f"\n\n⚠️ **Status: ALREADY {action.upper()}ED MANUALLY**")

    if action == "reject":
        try: await client.send_message(target_user, "❌ Your appeal has been reviewed and **rejected** by the administration. You remain restricted, but may submit a new appeal later.")
        except: pass
        return await callback.message.edit_text(callback.message.text + "\n\n❌ **Status: REJECTED**")

    await db.remove_punishment(target_user, chat_id, action.replace("un", ""))
    await callback.answer(f"✅ User {action}ed!", show_alert=True)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ **Status: {action.upper()}ED**")
    
    try: await client.send_message(target_user, f"✅ Good news! Your `{action.replace('un', '')}` has been lifted by the administrators.")
    except: pass
