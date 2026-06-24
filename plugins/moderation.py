import time
import re
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus
from database.multi_db import db
from config import Config

# --- RAM TRACKERS FOR AUTO-TRIGGERS ---
LINK_TRACKER = {}  # Tracks links sent within a time window
SCRAPER_TRACKER = {} # Tracks search frequency

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
# 🛡️ CONTEXTUAL COMMANDS (PM = Global | Group = Local)
# ==========================================
@Client.on_message(filters.command(["warn", "mute", "ban", "unwarn", "unmute", "unban"]))
async def contextual_punishment(client: Client, message: Message):
    cmd = message.command[0].lower()
    is_global = message.chat.type == ChatType.PRIVATE
    chat_id = "global" if is_global else str(message.chat.id)
    
    if is_global and message.from_user.id not in Config.ADMINS: return
    if not is_global and not await is_group_admin(client, message.chat.id, message.from_user.id): return

    target_user = None
    reason = "No reason provided."
    duration_secs = 0

    if message.reply_to_message:
        target_user = message.reply_to_message.from_user.id
        if len(message.command) > 1: reason = " ".join(message.command[1:])
    else:
        if len(message.command) < 2:
            return await message.reply_text(f"⚠️ **Usage:** `/{cmd} <user_id> [time] [reason]` or reply to a user.")
        target_user = int(message.command[1])
        if len(message.command) > 2: reason = " ".join(message.command[2:])

    if target_user in Config.ADMINS:
        return await message.reply_text("🛑 You cannot punish a System Administrator.")

    # Time parsing for mutes (e.g., 5d, 2h)
    if cmd == "mute" and message.reply_to_message and len(message.command) > 1:
        time_str = message.command[1]
        reason = " ".join(message.command[2:]) if len(message.command) > 2 else reason
        if time_str.endswith('d'): duration_secs = int(time_str[:-1]) * 86400
        elif time_str.endswith('h'): duration_secs = int(time_str[:-1]) * 3600
        elif time_str.endswith('m'): duration_secs = int(time_str[:-1]) * 60
        else: duration_secs = int(time_str) * 3600 # Default to hours

    elif cmd == "mute" and not message.reply_to_message and len(message.command) > 2:
        time_str = message.command[2]
        reason = " ".join(message.command[3:]) if len(message.command) > 3 else reason
        if time_str.endswith('d'): duration_secs = int(time_str[:-1]) * 86400
        elif time_str.endswith('h'): duration_secs = int(time_str[:-1]) * 3600
        elif time_str.endswith('m'): duration_secs = int(time_str[:-1]) * 60
        else: duration_secs = int(time_str) * 3600

    if cmd == "warn":
        warns = await db.add_punishment(target_user, chat_id, "warn", reason=reason)
        # Escalation logic
        limit = 5 # Can be fetched from settings
        if warns >= limit:
            await db.add_punishment(target_user, chat_id, "mute", duration_secs=86400, reason="Exceeded warning limit.")
            msg = f"🔴 User `{target_user}` exceeded {limit} warnings and has been **Auto-Muted**."
        else:
            msg = f"⚠️ User `{target_user}` warned ({warns}/{limit}).\nReason: {reason}"
        await message.reply_text(msg)
        if is_global: await log_to_channel(client, f"#global_warn\nUser: `{target_user}`\nWarns: {warns}/{limit}\nReason: {reason}")

    elif cmd == "mute":
        duration_secs = duration_secs or 86400 # 1 day default
        expiry = time.time() + duration_secs
        await db.add_punishment(target_user, chat_id, "mute", expiry_ts=expiry, reason=reason)
        msg = f"🔇 User `{target_user}` has been muted.\nReason: {reason}"
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unmute", callback_data=f"admin_unmute_{chat_id}_{target_user}")]]) if not is_global else None
        await message.reply_text(msg, reply_markup=btn)
        
        if is_global:
            log_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unmute User", callback_data=f"log_unmute_{target_user}")]])
            await log_to_channel(client, f"#global_mute\nUser: `{target_user}`\nReason: {reason}", log_btn)

    elif cmd == "ban":
        await db.add_punishment(target_user, chat_id, "ban", reason=reason)
        msg = f"🚫 User `{target_user}` has been banned.\nReason: {reason}"
        
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban_{chat_id}_{target_user}")]]) if not is_global else None
        await message.reply_text(msg, reply_markup=btn)
        
        if is_global:
            log_btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unban User", callback_data=f"log_unban_{target_user}")]])
            await log_to_channel(client, f"#global_ban\nUser: `{target_user}`\nReason: {reason}", log_btn)

    elif cmd in ["unwarn", "unmute", "unban"]:
        await db.remove_punishment(target_user, chat_id, cmd.replace("un", ""))
        await message.reply_text(f"✅ User `{target_user}` has been successfully {cmd}ed in this scope.")

# ==========================================
# 📊 UTILITY COMMANDS (/id & /info)
# ==========================================
@Client.on_message(filters.command("id"))
async def get_id(client: Client, message: Message):
    text = f"🆔 **Your ID:** `{message.from_user.id}`\n"
    if message.chat.type != ChatType.PRIVATE:
        text += f"👥 **Group ID:** `{message.chat.id}`"
    if message.reply_to_message:
        text += f"\n👤 **Replied User ID:** `{message.reply_to_message.from_user.id}`"
    await message.reply_text(text)

@Client.on_message(filters.command("info") & filters.user(Config.ADMINS))
async def get_info(client: Client, message: Message):
    target = message.reply_to_message.from_user.id if message.reply_to_message else (int(message.command[1]) if len(message.command)>1 else message.from_user.id)
    user_data = await db.get_user_settings(target)
    
    status, reason, expiry, scope = await db.check_punishment(target, "global")
    global_status = status.upper() if status else "CLEAN"
    
    text = (
        f"📊 **User Intelligence Report**\n\n"
        f"👤 **ID:** `{target}`\n"
        f"⚙️ **Search Mode:** `{user_data.get('search_mode', 'default')}`\n"
        f"🌍 **Global Status:** `{global_status}`\n"
        f"📉 **Searches Performed:** `{user_data.get('total_searches', 0)}`\n"
    )
    if status == "mute": text += f"⏳ **Mute Expires:** <t:{int(expiry)}:R>\n"
    await message.reply_text(text)

# ==========================================
# 🚨 AUTO-TRIGGERS (Links & Bad Words)
# ==========================================
@Client.on_message(filters.text & filters.group, group=-1)
async def auto_moderation_triggers(client: Client, message: Message):
    user_id = message.from_user.id
    chat_id = str(message.chat.id)
    text = message.text.lower()
    
    # Check Bad Words
    settings = await db.get_settings()
    bad_words = settings.get("bad_words", [])
    if any(word in text for word in bad_words if word.strip()):
        await message.delete()
        await db.add_punishment(user_id, chat_id, "mute", expiry_ts=time.time()+(3*86400), reason="Bad words detected.")
        alert = await message.reply_text(f"🔇 {message.from_user.mention} was auto-muted for 3 days due to prohibited language.")
        await asyncio.sleep(10)
        return await alert.delete()

    # Check Link Spammer (3 links in 2 mins)
    if re.search(r"(https?://|t\.me/|www\.)", text):
        if user_id not in LINK_TRACKER: LINK_TRACKER[user_id] = []
        LINK_TRACKER[user_id].append(time.time())
        LINK_TRACKER[user_id] = [t for t in LINK_TRACKER[user_id] if time.time() - t < 120] # Keep last 2 mins
        
        if len(LINK_TRACKER[user_id]) == 1:
            warn = await message.reply_text(f"⚠️ {message.from_user.mention}, please do not send links here. Search for movies by name.")
            await asyncio.sleep(5)
            await warn.delete()
        elif len(LINK_TRACKER[user_id]) >= 3:
            await message.delete()
            await db.add_punishment(user_id, chat_id, "mute", expiry_ts=time.time()+86400, reason="Link Spammer")
            alert = await message.reply_text(f"🔇 {message.from_user.mention} was auto-muted for 24h for link spamming.")
            await asyncio.sleep(10)
            await alert.delete()

# ==========================================
# ⚖️ APPEALS SYSTEM (Log Channel Routing)
# ==========================================
@Client.on_callback_query(filters.regex(r"^appeal_(global|local)_(.+)$"))
async def process_appeal(client: Client, callback: CallbackQuery):
    scope = callback.matches[0].group(1)
    punishment_type = callback.matches[0].group(2)
    user_id = callback.from_user.id
    
    # Prevent appeal spam
    user_data = await db.get_user_settings(user_id)
    if time.time() < user_data.get("next_appeal_time", 0):
        return await callback.answer("⏳ You have already submitted an appeal recently. Please wait.", show_alert=True)
    
    await db.update_user_setting(user_id, "next_appeal_time", time.time() + 86400) # 1 appeal per day
    await callback.answer("✅ Your appeal has been submitted to the administration.", show_alert=True)
    
    if scope == "global":
        action_str = "✅ Unban User" if punishment_type == "ban" else "🔓 Unmute User"
        action_cb = f"log_unban_{user_id}" if punishment_type == "ban" else f"log_unmute_{user_id}"
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(action_str, callback_data=action_cb)],
            [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"log_reject_{user_id}")]
        ])
        await log_to_channel(client, f"⚖️ **NEW GLOBAL APPEAL**\n\n👤 User: `{user_id}` ({callback.from_user.mention})\nType: **{punishment_type.upper()}**\n\nPlease review:", markup)
    else:
        # Group appeal routing -> Send to Group Admins via bot PM (or just notify in group if preferred. For now, notifying in log channel with local tag)
        await log_to_channel(client, f"⚖️ **GROUP APPEAL**\n\nUser `{user_id}` appealed a {punishment_type} in group `{callback.message.chat.id}`.")

@Client.on_callback_query(filters.regex(r"^(log|admin)_(unban|unmute|reject)_(.+)$"))
async def admin_appeal_actions(client: Client, callback: CallbackQuery):
    action = callback.matches[0].group(2)
    
    if action == "reject":
        target_user = int(callback.matches[0].group(3))
        try: await client.send_message(target_user, "❌ Your appeal has been reviewed and **rejected** by the administration. You remain restricted, but you may submit a new appeal later.")
        except: pass
        return await callback.message.edit_text(callback.message.text + "\n\n❌ **Status: REJECTED**")

    # The regex splits differently if it's admin vs log
    parts = callback.data.split("_")
    source = parts[0]
    action_type = parts[1]
    
    if source == "log":
        target_user = int(parts[2])
        chat_id = "global"
    else:
        chat_id = parts[2]
        target_user = int(parts[3])
        if not await is_group_admin(client, callback.message.chat.id, callback.from_user.id):
            return await callback.answer("Access Denied.", show_alert=True)

    await db.remove_punishment(target_user, chat_id, action_type.replace("un", ""))
    await callback.answer(f"✅ User {action_type}ed!", show_alert=True)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ **Status: {action_type.upper()}ED by {callback.from_user.first_name}**")
    
    try: await client.send_message(target_user, f"✅ Good news! Your `{action_type.replace('un', '')}` has been lifted by the administrators.")
    except: pass
