import time
import re
import asyncio
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus
from database.multi_db import db
from config import Config

SPAM_TRACKER = {}

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
# 🛑 SMART CONTEXTUAL MODERATION (Manual Commands)
# ==========================================
@Client.on_message(filters.command(["warn", "mute", "ban", "unwarn", "unmute", "unban"]))
async def contextual_punishment(client: Client, message: Message):
    cmd = message.command[0].lower()
    is_global = message.chat.type == ChatType.PRIVATE
    chat_id_str = "global" if is_global else str(message.chat.id)
    
    if is_global and message.from_user.id not in Config.ADMINS: raise StopPropagation
    if not is_global and not await is_group_admin(client, message.chat.id, message.from_user.id): raise StopPropagation

    target_user, time_str, reason = None, "", "Manual Admin Action"

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

    duration_secs = 86400 # 1 day default
    if time_str:
        if time_str.endswith('d'): duration_secs = int(time_str[:-1]) * 86400
        elif time_str.endswith('h'): duration_secs = int(time_str[:-1]) * 3600
        elif time_str.endswith('m'): duration_secs = int(time_str[:-1]) * 60
        else:
            try: duration_secs = int(time_str) * 3600
            except: reason = f"{time_str} {reason}"

    # Fetch limits and toggles dynamically
    sett = await db.get_settings() if is_global else await db.get_group_settings(int(chat_id_str))
    warn_lim = sett.get("warn_limit", 3)
    mute_lim = sett.get("mute_limit", 3)
    am_en = sett.get("auto_mute_enabled", False)
    ab_en = sett.get("auto_ban_enabled", False)
    
    if cmd == "warn":
        warns = await db.add_punishment(target_user, chat_id_str, "warn", reason=reason)
        
        if am_en and warns >= warn_lim:
            mutes = await db.add_punishment(target_user, chat_id_str, "mute", expiry_ts=time.time()+86400, reason="Exceeded warnings limit via manual warn")
            await db.remove_punishment(target_user, chat_id_str, "warn") # Reset warns
            
            if ab_en and mutes >= mute_lim:
                await db.add_punishment(target_user, chat_id_str, "ban", reason="Exceeded mute limit")
                await message.reply_text(f"🔴 User `{target_user}` hit {warn_lim}/{warn_lim} warnings and {mute_lim}/{mute_lim} mutes. They have been **Auto-Banned**.")
            else:
                await message.reply_text(f"🔴 User `{target_user}` hit {warn_lim}/{warn_lim} warnings and has been **Auto-Muted for 24H**.")
        else:
            await message.reply_text(f"⚠️ User `{target_user}` warned ({warns}/{warn_lim}).\nReason: {reason}")
            
    elif cmd == "mute":
        mutes = await db.add_punishment(target_user, chat_id_str, "mute", expiry_ts=time.time() + duration_secs, reason=reason)
        
        if ab_en and mutes >= mute_lim:
            await db.add_punishment(target_user, chat_id_str, "ban", reason="Exceeded mute limit via manual mute")
            await message.reply_text(f"🚫 User `{target_user}` hit {mute_lim}/{mute_lim} mutes and has been **Auto-Banned**.")
        else:
            btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Unmute", callback_data=f"admin_unmute_{chat_id_str}_{target_user}")]])
            await message.reply_text(f"🔇 User `{target_user}` muted ({mutes}/{mute_lim} mutes).\nUnlocks: <t:{int(time.time() + duration_secs)}:R>", reply_markup=btn)
            if is_global: await log_to_channel(client, f"#muteuser `{target_user}`\nReason: {reason}")

    elif cmd == "ban":
        await db.add_punishment(target_user, chat_id_str, "ban", reason=reason)
        btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban_{chat_id_str}_{target_user}")]])
        await message.reply_text(f"🚫 User `{target_user}` banned.\nReason: {reason}", reply_markup=btn)
        if is_global: await log_to_channel(client, f"#banuser `{target_user}`\nReason: {reason}")

    elif cmd in ["unwarn", "unmute", "unban"]:
        await db.remove_punishment(target_user, chat_id_str, cmd.replace("un", ""))
        await message.reply_text(f"✅ User `{target_user}` successfully {cmd}ed.")
        
    raise StopPropagation

# ==========================================
# 🚨 AUTO-MODERATION TRIGGERS (Groups Only)
# ==========================================
@Client.on_message(filters.text & filters.group, group=-1)
async def auto_moderation_triggers(client: Client, message: Message):
    user_id = message.from_user.id
    chat_id_str = str(message.chat.id)
    text = message.text.lower()
    current_time = time.time()
    
    g_sett = await db.get_group_settings(message.chat.id)
    
    am_en = g_sett.get("auto_mute_enabled", False)
    link_en = g_sett.get("anti_link_enabled", False)
    bw_en = g_sett.get("bad_words_enabled", False)
    ab_en = g_sett.get("auto_ban_enabled", False)
    warn_lim = g_sett.get("warn_limit", 3)
    mute_lim = g_sett.get("mute_limit", 3)
    bad_words = g_sett.get("bad_words", [])

    issue_warn = False
    warn_reason = ""

    # 1. LINK FILTER
    if link_en and re.search(r"(https?://|t\.me/|www\.)", text):
        issue_warn = True
        warn_reason = "Sending unauthorized links"

    # 2. BAD WORDS FILTER
    if bw_en and not issue_warn:
        if any(word in text for word in bad_words if word.strip()):
            issue_warn = True
            warn_reason = "Using prohibited language"

    # 3. SPAM FILTER (Always on: 5 msgs / 3 secs)
    if not issue_warn:
        if user_id not in SPAM_TRACKER: SPAM_TRACKER[user_id] = []
        SPAM_TRACKER[user_id].append(current_time)
        SPAM_TRACKER[user_id] = [t for t in SPAM_TRACKER[user_id] if current_time - t < 3] 
        if len(SPAM_TRACKER[user_id]) >= 5:
            issue_warn = True
            warn_reason = "Extreme message flooding"

    # 🚨 CASCADE EXECUTION 🚨
    if issue_warn:
        await message.delete()
        warns = await db.add_punishment(user_id, chat_id_str, "warn", reason=warn_reason)
        
        if am_en and warns >= warn_lim:
            mutes = await db.add_punishment(user_id, chat_id_str, "mute", expiry_ts=current_time + 86400, reason=f"Hit warnings limit ({warn_reason})")
            await db.remove_punishment(user_id, chat_id_str, "warn") # clear warns after muting
            
            if ab_en and mutes >= mute_lim:
                await db.add_punishment(user_id, chat_id_str, "ban", reason="Hit mutes limit")
                alert = await message.reply_text(f"🚫 {message.from_user.mention} was **Auto-Banned** for repeatedly breaking rules ({mutes}/{mute_lim} mutes).")
            else:
                alert = await message.reply_text(f"🔇 {message.from_user.mention} was **Auto-Muted for 24h** for hitting {warn_lim}/{warn_lim} warnings.")
        else:
            alert = await message.reply_text(f"⚠️ {message.from_user.mention}, you have been warned! ({warns}/{warn_lim})\nReason: {warn_reason}")
            
        await asyncio.sleep(10)
        try: await alert.delete()
        except Exception: pass

# ==========================================
# ⚖️ APPEALS SYSTEM
# ==========================================
@Client.on_callback_query(filters.regex(r"^appeal_(global|local)_(.+)$"))
async def process_appeal(client: Client, callback: CallbackQuery):
    scope = callback.matches[0].group(1)
    ptype = callback.matches[0].group(2)
    user_id = callback.from_user.id
    chat_id = str(callback.message.chat.id)
    
    await callback.answer("✅ Your appeal has been submitted to the administration.", show_alert=True)
    try: await callback.message.edit_text(callback.message.text + "\n\n✅ **Appeal Submitted.** Please wait for admin review.", reply_markup=None)
    except Exception: pass
    
    if scope == "global":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"log_un{ptype}_{user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"log_reject_{user_id}")]])
        await log_to_channel(client, f"⚖️ **NEW GLOBAL APPEAL**\n\n👤 User: `{user_id}`\nType: **{ptype.upper()}**\n\nPlease review:", markup)
    else:
        g_sett = await db.get_group_settings(int(chat_id))
        connected_by = g_sett.get("connected_by")
        if connected_by:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"admin_un{ptype}_{chat_id}_{user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"admin_reject_{chat_id}_{user_id}")]])
            try: await client.send_message(connected_by, f"⚖️ **GROUP APPEAL**\n\n👤 User: `{user_id}`\n👥 Group: `{callback.message.chat.title}`\nType: **{ptype.upper()}**", reply_markup=markup)
            except: pass

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

    if action == "reject":
        try: await client.send_message(target_user, "❌ Your appeal has been reviewed and **rejected** by the administration.")
        except: pass
        return await callback.message.edit_text(callback.message.text + "\n\n❌ **Status: REJECTED**")

    await db.remove_punishment(target_user, chat_id, action.replace("un", ""))
    await callback.answer(f"✅ User {action}ed!", show_alert=True)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ **Status: {action.upper()}ED**")
    
    try: await client.send_message(target_user, f"✅ Good news! Your `{action.replace('un', '')}` has been lifted by the administrators.")
    except: pass
