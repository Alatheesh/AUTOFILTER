import time
import re
import asyncio
import datetime
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatPermissions
from pyrogram.enums import ChatType, ChatMemberStatus
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

SPAM_TRACKER = {}
SCRAPER_TRACKER = {}
APPEAL_COOLDOWN = {} 

async def is_group_admin(client, chat_id, user_id):
    if user_id in Config.ADMINS: return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception: return False

async def log_to_channel(client, text, markup=None):
    if Config.LOG_CHANNEL:
        try: await client.send_message(Config.LOG_CHANNEL, text, reply_markup=markup)
        except Exception: pass

# ==========================================
# 🧠 THE MASTER UNIFIED PUNISHMENT ENGINE
# ==========================================
async def execute_punishment(client: Client, message: Message, target_user: int, chat_id_str: str, action_type: str, reason: str, duration_secs: int = 86400):
    """Handles ALL punishments (Manual + Automatic) as a single connected system."""
    is_global = chat_id_str == "global"
    
    # 1. Fetch exact limits for the scope
    if is_global:
        sett = await db.get_settings()
        am_en = sett.get("auto_mute_enabled", True)
        ab_en = sett.get("auto_ban_enabled", True)
    else:
        sett = await db.get_group_settings(int(chat_id_str))
        am_en = sett.get("auto_mute_enabled", False)
        ab_en = sett.get("auto_ban_enabled", False)
        
    warn_lim = sett.get("warn_limit", 3)
    mute_lim = sett.get("mute_limit", 3)

    # 2. Check Hierarchy (Don't warn someone who is already muted/banned)
    curr_type, _, _, curr_scope = await db.check_punishment(target_user, chat_id_str)
    hierarchy = {"clean": 0, "warn": 1, "mute": 2, "ban": 3}
    if hierarchy.get(curr_type, 0) > hierarchy.get(action_type, 1) and curr_scope == chat_id_str:
        return False, f"User is already {curr_type.upper()}ED. Cannot apply a lesser punishment."

    # 3. Apply to Database
    expiry = time.time() + duration_secs if action_type == "mute" else 0
    count = await db.add_punishment(target_user, chat_id_str, action_type, duration_secs, expiry, reason)

    final_action = action_type
    final_reason = reason
    
    # 4. ⚙️ THE ESCALATION PIPELINE
    if final_action == "warn" and am_en and count >= warn_lim:
        final_action = "mute"
        final_reason = f"Hit warnings limit ({warn_lim}). Trigger: {reason}"
        duration_secs = 86400
        expiry = time.time() + 86400
        count = await db.add_punishment(target_user, chat_id_str, "mute", 86400, expiry, final_reason)
        await db.remove_punishment(target_user, chat_id_str, "warn")
        
    if final_action == "mute" and ab_en and count >= mute_lim:
        final_action = "ban"
        final_reason = f"Hit mutes limit ({mute_lim}). Trigger: {reason}"
        count = await db.add_punishment(target_user, chat_id_str, "ban", 0, 0, final_reason)
        await db.remove_punishment(target_user, chat_id_str, "mute")

    # 5. Native Telegram Enforcement
    if not is_global:
        chat_id_int = int(chat_id_str)
        if final_action == "mute":
            until_dt = datetime.datetime.now() + datetime.timedelta(seconds=duration_secs)
            try: await client.restrict_chat_member(chat_id_int, target_user, ChatPermissions(can_send_messages=False), until_date=until_dt)
            except Exception: pass
        elif final_action == "ban":
            try: await client.ban_chat_member(chat_id_int, target_user)
            except Exception: pass

    # 6. Notifications & PM Appeals
    try: target_user_obj = await client.get_users(target_user)
    except Exception: target_user_obj = None
    mention = target_user_obj.mention if target_user_obj else f"`{target_user}`"
    loc_name = "Global System" if is_global else message.chat.title

    if not is_global:
        if final_action == "ban": alert = await client.send_message(int(chat_id_str), f"🚫 {mention} was **Banned**.\nReason: {final_reason}")
        elif final_action == "mute": alert = await client.send_message(int(chat_id_str), f"🔇 {mention} was **Muted**.\nReason: {final_reason}")
        elif final_action == "warn": alert = await client.send_message(int(chat_id_str), f"⚠️ {mention}, you have been **Warned** ({count}/{warn_lim}).\nReason: {final_reason}")
            
        async def auto_delete_alert(msg_to_delete):
            await asyncio.sleep(10)
            try: await msg_to_delete.delete()
            except Exception: pass
        if final_action == "warn": asyncio.create_task(auto_delete_alert(alert))

    if final_action in ["mute", "ban"]:
        appeal_cb = f"appeal_{chat_id_str}_{final_action}_{target_user}"
        try:
            msg = f"🚫 **Notice:** You were `{final_action}d` in **{loc_name}**.\n**Reason:** {final_reason}\n\nIf you believe this was an error, click below to submit an appeal to the administrators."
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Appeal", callback_data=appeal_cb)]])
            await client.send_message(target_user, msg, reply_markup=btn)
        except Exception: pass 
        if is_global: await log_to_channel(client, f"#{final_action}user `{target_user}`\nReason: {final_reason}")
        
    elif is_global and final_action == "warn":
        try: await client.send_message(target_user, f"⚠️ **SYSTEM WARNING** ({count}/{warn_lim})\nYour message was deleted. Reason: {final_reason}. Repeated violations will result in a global ban.")
        except Exception: pass

    return True, final_action

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
            except Exception: reason = f"{time_str} {reason}"

    # 🚀 SEND TO THE UNIFIED ENGINE
    if cmd in ["warn", "mute", "ban"]:
        success, result_state = await execute_punishment(client, message, target_user, chat_id_str, cmd, reason, duration_secs)
        if not success:
            await message.reply_text(f"⚠️ {result_state}")
        elif is_global:
            await message.reply_text(f"✅ Command successful. User is now `{result_state.upper()}ED` globally.")

    # 🟢 REMOVE PUNISHMENTS
    elif cmd in ["unwarn", "unmute", "unban"]:
        await db.remove_punishment(target_user, chat_id_str, cmd.replace("un", ""))
        if not is_global: 
            try: await client.unban_chat_member(message.chat.id, target_user)
            except Exception: pass
        await message.reply_text(f"✅ User `{target_user}` successfully {cmd}ed.")
        
    raise StopPropagation

# ==========================================
# 🚨 EMERGENCY ADMIN REPORT SYSTEM
# ==========================================
@Client.on_message(filters.group & filters.text & filters.regex(r"(?i)@admins?"), group=1)
async def emergency_admin_report(client: Client, message: Message):
    chat_id = message.chat.id
    reporter = message.from_user
    
    admin_ids = await db.get_group_admins(chat_id)
    if not admin_ids:
        g_sett = await db.get_group_settings(chat_id)
        if g_sett.get("connected_by"): admin_ids = [g_sett.get("connected_by")]
            
    if not admin_ids: return await message.reply_text("⚠️ **Error:** No admins are registered in the bot's database for this group.")
        
    chat_title = message.chat.title
    msg_link = message.link if message.link else f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.id}"
    
    report_text = f"🚨 **EMERGENCY REPORT** 🚨\n\n👥 **Group:** `{chat_title}`\n👤 **Reporter:** {reporter.mention} (`{reporter.id}`)\n"
    if message.reply_to_message:
        target_msg = message.reply_to_message
        target_user = target_msg.from_user
        user_info = f"{target_user.mention} (`{target_user.id}`)" if target_user else "Unknown/Anonymous"
        report_text += f"🎯 **Reported User:** {user_info}\n\n📝 **Reported Message:**\n_{target_msg.text or target_msg.caption or '[Media/Non-text message]'}_\n\n"
    else: report_text += f"\n📝 **Report Message:**\n_{message.text}_\n\n"
        
    report_text += f"*(Please check the group to take action)*"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Message", url=msg_link)]])
    
    sent_count = 0
    for adm in admin_ids:
        try:
            await client.send_message(adm, report_text, disable_web_page_preview=True, reply_markup=markup)
            sent_count += 1
        except Exception: pass
            
    if sent_count > 0: await message.reply_text(f"✅ **Emergency Report sent securely to {sent_count} admin(s).**")
    else: await message.reply_text("⚠️ **Failed to reach admins.** They might have blocked the bot in their private messages.")

# ==========================================
# 🚨 AUTO-MODERATION TRIGGERS (PM & Groups)
# ==========================================
@Client.on_message(filters.text & (filters.group | filters.private), group=-1)
async def auto_moderation_triggers(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in Config.ADMINS: return 

    chat_id = message.chat.id
    chat_id_str = str(chat_id) if message.chat.type != ChatType.PRIVATE else "global"
    text = message.text
    current_time = time.time()
    
    # 🚀 1. THE LOOPHOLE FIX: Block already muted/banned users immediately!
    p_type, p_reason, p_expiry, p_scope = await db.check_punishment(user_id, chat_id_str)
    if p_type in ["mute", "ban"]:
        if message.chat.type != ChatType.PRIVATE:
            try: await message.delete()
            except Exception: pass
        raise StopPropagation # DO NOT SCAN! THEY ARE ALREADY GHOSTED!
    
    global_settings = await db.get_settings()
    global_bad_words = global_settings.get("bad_words", [])
    
    if message.chat.type != ChatType.PRIVATE:
        g_sett = await db.get_group_settings(chat_id)
        link_en = g_sett.get("anti_link_enabled", False)
        bw_en = g_sett.get("bad_words_enabled", False)
        local_bad_words = g_sett.get("bad_words", [])
    else:
        link_en = False 
        bw_en = True 
        local_bad_words = []

    issue_warn = False
    warn_reason = ""

    # 1. LINK FILTER (Group Only)
    if link_en and message.chat.type != ChatType.PRIVATE and re.search(r"(https?://|t\.me/|www\.)", text, re.IGNORECASE):
        issue_warn = True
        warn_reason = "Sending unauthorized links"

    # 2. BAD WORDS FILTER
    if bw_en and not issue_warn:
        combined_words = list(set(global_bad_words + local_bad_words))
        clean_words = [re.escape(w.strip()) for w in combined_words if w.strip()]
        
        if clean_words:
            bad_words_pattern = r'\b(?:' + '|'.join(clean_words) + r')\b'
            if re.search(bad_words_pattern, text, re.IGNORECASE):
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

    # 🚨 EXECUTE UNIFIED PUNISHMENT 🚨
    if issue_warn:
        try: await message.delete()
        except Exception: pass
        
        # Sent directly to the Master Engine
        await execute_punishment(client, message, user_id, chat_id_str, "warn", warn_reason)
        
        # 🛑 BLOCK MESSAGE FROM REACHING SEARCH ENGINE
        raise StopPropagation

# ==========================================
# ⚖️ APPEALS SYSTEM (With Spam & Leech Protection)
# ==========================================
@Client.on_callback_query(filters.regex(r"^appeal_(.+)_(mute|ban)_(.+)$"))
async def process_appeal(client: Client, callback: CallbackQuery):
    chat_id_str = callback.matches[0].group(1)
    ptype = callback.matches[0].group(2)
    target_user_id = int(callback.matches[0].group(3))
    
    if callback.from_user.id != target_user_id:
        return await callback.answer("⚠️ Access Denied: You cannot submit an appeal for someone else!", show_alert=True)
        
    current_time = time.time()
    if target_user_id in APPEAL_COOLDOWN and current_time - APPEAL_COOLDOWN[target_user_id] < 3600:
        rem = int((3600 - (current_time - APPEAL_COOLDOWN[target_user_id])) / 60)
        return await callback.answer(f"⏳ Please wait {rem} minutes before submitting another appeal.", show_alert=True)
        
    APPEAL_COOLDOWN[target_user_id] = current_time
    
    await callback.answer("✅ Your appeal has been submitted to the administration.", show_alert=True)
    try: await callback.message.edit_text(callback.message.text + "\n\n✅ **Appeal Submitted.** Please wait for admin review.", reply_markup=None)
    except Exception: pass
    
    if chat_id_str == "global":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"log_un{ptype}_{target_user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"log_reject_{target_user_id}")]])
        await log_to_channel(client, f"⚖️ **NEW GLOBAL APPEAL**\n\n👤 User: `{target_user_id}`\nType: **{ptype.upper()}**\n\nPlease review:", markup)
    else:
        g_sett = await db.get_group_settings(int(chat_id_str))
        connected_by = g_sett.get("connected_by")
        if connected_by:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Un{ptype.capitalize()}", callback_data=f"admin_un{ptype}_{chat_id_str}_{target_user_id}")], [InlineKeyboardButton("❌ Reject Appeal", callback_data=f"admin_reject_{chat_id_str}_{target_user_id}")]])
            try: await client.send_message(connected_by, f"⚖️ **GROUP APPEAL**\n\n👤 User: `{target_user_id}`\n👥 Group ID: `{chat_id_str}`\nType: **{ptype.upper()}**", reply_markup=markup)
            except Exception: pass

@Client.on_callback_query(filters.regex(r"^(log|admin)_(unban|unmute|reject)_(.+)$"))
async def admin_appeal_actions(client: Client, callback: CallbackQuery):
    action = callback.matches[0].group(2)
    data_parts = callback.data.split("_")
    source = data_parts[0]
    
    if source == "log":
        target_user = int(data_parts[2])
        chat_id_str = "global"
    else:
        chat_id_str = data_parts[2]
        target_user = int(data_parts[3])

    if action == "reject":
        try: await client.send_message(target_user, "❌ Your appeal has been reviewed and **rejected** by the administration.")
        except Exception: pass
        return await callback.message.edit_text(callback.message.text + "\n\n❌ **Status: REJECTED**")

    await db.remove_punishment(target_user, chat_id_str, action.replace("un", ""))
    
    if chat_id_str != "global":
        try: await client.unban_chat_member(int(chat_id_str), target_user)
        except Exception: pass
        
    await callback.answer(f"✅ User {action}ed!", show_alert=True)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ **Status: {action.upper()}ED**")
    
    try: await client.send_message(target_user, f"✅ Good news! Your `{action.replace('un', '')}` has been lifted by the administrators.")
    except Exception: pass
