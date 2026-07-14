import time
import re
import asyncio
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ChatType, ChatMemberStatus, ButtonStyle
from database.multi_db import db
from config import Config

SPAM_TRACKER = {}
SCRAPER_TRACKER = {}

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
            await message.reply_text(f"⚠️ **𝐔𝐬𝐚𝐠𝐞:** `/{cmd} <user_id> [time] [reason]`")
            raise StopPropagation
        try: target_user = int(message.command[1])
        except ValueError: 
            await message.reply_text("⚠️ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐔𝐬𝐞𝐫 𝐈𝐃.")
            raise StopPropagation
        if len(message.command) > 2: time_str = message.command[2]
        if len(message.command) > 3: reason = " ".join(message.command[3:])

    if target_user in Config.ADMINS: 
        await message.reply_text("🛑 𝐂𝐚𝐧𝐧𝐨𝐭 𝐩𝐮𝐧𝐢𝐬𝐡 𝐚 𝐒𝐲𝐬𝐭𝐞𝐦 𝐀𝐝𝐦𝐢𝐧𝐢𝐬𝐭𝐫𝐚𝐭𝐨𝐫.")
        raise StopPropagation

    duration_secs = 86400 # 1 day default
    if time_str:
        if time_str.endswith('d'): duration_secs = int(time_str[:-1]) * 86400
        elif time_str.endswith('h'): duration_secs = int(time_str[:-1]) * 3600
        elif time_str.endswith('m'): duration_secs = int(time_str[:-1]) * 60
        else:
            try: duration_secs = int(time_str) * 3600
            except: reason = f"{time_str} {reason}"

    sett = await db.get_settings() if is_global else await db.get_group_settings(int(chat_id_str))
    warn_lim = sett.get("warn_limit", 3)
    mute_lim = sett.get("mute_limit", 3)
    am_en = sett.get("auto_mute_enabled", False)
    ab_en = sett.get("auto_ban_enabled", False)
    
    if cmd == "warn":
        warns = await db.add_punishment(target_user, chat_id_str, "warn", reason=reason)
        
        if am_en and warns >= warn_lim:
            mutes = await db.add_punishment(target_user, chat_id_str, "mute", expiry_ts=time.time()+86400, reason="Exceeded warnings limit via manual warn")
            await db.remove_punishment(target_user, chat_id_str, "warn") 
            
            if ab_en and mutes >= mute_lim:
                await db.add_punishment(target_user, chat_id_str, "ban", reason="Exceeded mute limit")
                await message.reply_text(f"🔴 𝐔𝐬𝐞𝐫 `{target_user}` 𝐡𝐢𝐭 {warn_lim}/{warn_lim} 𝐰𝐚𝐫𝐧𝐢𝐧𝐠𝐬 𝐚𝐧𝐝 {mute_lim}/{mute_lim} 𝐦𝐮𝐭𝐞𝐬. 𝐓𝐡𝐞𝐲 𝐡𝐚𝐯𝐞 𝐛𝐞𝐞𝐧 **𝐀𝐮𝐭𝐨-𝐁𝐚𝐧𝐧𝐞𝐝**.")
            else:
                await message.reply_text(f"🔴 𝐔𝐬𝐞𝐫 `{target_user}` 𝐡𝐢𝐭 {warn_lim}/{warn_lim} 𝐰𝐚𝐫𝐧𝐢𝐧𝐠𝐬 𝐚𝐧𝐝 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 **𝐀𝐮𝐭𝐨-𝐌𝐮𝐭𝐞𝐝 𝐟𝐨𝐫 𝟐𝟒𝐇**.")
        else:
            await message.reply_text(f"⚠️ 𝐔𝐬𝐞𝐫 `{target_user}` 𝐰𝐚𝐫𝐧𝐞𝐝 ({warns}/{warn_lim}).\n𝐑𝐞𝐚𝐬𝐨𝐧: {reason}")
            
    elif cmd == "mute":
        mutes = await db.add_punishment(target_user, chat_id_str, "mute", expiry_ts=time.time() + duration_secs, reason=reason)
        
        if ab_en and mutes >= mute_lim:
            await db.add_punishment(target_user, chat_id_str, "ban", reason="Exceeded mute limit via manual mute")
            await message.reply_text(f"🚫 𝐔𝐬𝐞𝐫 `{target_user}` 𝐡𝐢𝐭 {mute_lim}/{mute_lim} 𝐦𝐮𝐭𝐞𝐬 𝐚𝐧𝐝 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 **𝐀𝐮𝐭𝐨-𝐁𝐚𝐧𝐧𝐞𝐝**.")
        else:
            btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("🔓 𝗨𝗻𝗺𝘂𝘁𝗲", callback_data=f"admin_unmute_{chat_id_str}_{target_user}", style=ButtonStyle.SUCCESS)]])
            await message.reply_text(f"🔇 𝐔𝐬𝐞𝐫 `{target_user}` 𝐦𝐮𝐭𝐞𝐝 ({mutes}/{mute_lim} 𝐦𝐮𝐭𝐞𝐬).\n𝐔𝐧𝐥𝐨𝐜𝐤𝐬: <t:{int(time.time() + duration_secs)}:R>", reply_markup=btn)
            if is_global: await log_to_channel(client, f"#muteuser `{target_user}`\nReason: {reason}")

    elif cmd == "ban":
        await db.add_punishment(target_user, chat_id_str, "ban", reason=reason)
        btn = None if is_global else InlineKeyboardMarkup([[InlineKeyboardButton("✅ 𝗨𝗻𝗯𝗮𝗻", callback_data=f"admin_unban_{chat_id_str}_{target_user}", style=ButtonStyle.SUCCESS)]])
        await message.reply_text(f"🚫 𝐔𝐬𝐞𝐫 `{target_user}` 𝐛𝐚𝐧𝐧𝐞𝐝.\n𝐑𝐞𝐚𝐬𝐨𝐧: {reason}", reply_markup=btn)
        if is_global: await log_to_channel(client, f"#banuser `{target_user}`\nReason: {reason}")

    elif cmd in ["unwarn", "unmute", "unban"]:
        await db.remove_punishment(target_user, chat_id_str, cmd.replace("un", ""))
        await message.reply_text(f"✅ 𝗨𝘀𝗲𝗿 `{target_user}` 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 {cmd}𝗲𝗱.")
        
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
            
    if not admin_ids:
        return await message.reply_text("⚠️ **𝐄𝐫𝐫𝐨𝐫:** 𝖭𝗈 𝖺𝖽𝗆𝗂𝗇𝗌 𝖺𝗋𝖾 𝗋𝖾𝗀𝗂𝗌𝗍𝖾𝗋𝖾𝖽 𝗂𝗇 𝗍𝗁𝖾 𝖻𝗈𝗍'𝗌 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾 𝖿𝗈𝗋 𝗍𝗁𝗂𝗌 𝗀𝗋𝗈𝗎𝗉. 𝖠𝗇 𝖺𝖽𝗆𝗂𝗇 𝗇𝖾𝖾𝖽𝗌 𝗍𝗈 𝗋𝗎𝗇 `/connect` 𝗈𝗋 `/refreshadmins` 𝖿𝗂𝗋𝗌𝗍.")
        
    chat_title = message.chat.title
    msg_link = message.link if message.link else f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.id}"
    
    report_text = f"🚨 **𝗘𝗠𝗘𝗥𝗚𝗘𝗡𝗖𝗬 𝗥𝗘𝗣𝗢𝗥𝗧** 🚨\n\n"
    report_text += f"👥 **𝗚𝗿𝗼𝘂𝗽:** `{chat_title}`\n"
    report_text += f"👤 **𝗥𝗲𝗽𝗼𝗿𝘁𝗲𝗿:** {reporter.mention} (`{reporter.id}`)\n"
    
    if message.reply_to_message:
        target_msg = message.reply_to_message
        target_user = target_msg.from_user
        user_info = f"{target_user.mention} (`{target_user.id}`)" if target_user else "Unknown/Anonymous"
        report_text += f"🎯 **𝗥𝗲𝗽𝗼𝗿𝘁𝗲𝗱 𝗨𝘀𝗲𝗿:** {user_info}\n\n"
        report_text += f"📝 **𝗥𝗲𝗽𝗼𝗿𝘁𝗲𝗱 𝗠𝗲𝘀𝘀𝗮𝗴𝗲:**\n_{target_msg.text or target_msg.caption or '[Media/Non-text message]'}_\n\n"
    else:
        report_text += f"\n📝 **𝗥𝗲𝗽𝗼𝗿𝘁 𝗠𝗲𝘀𝘀𝗮𝗴𝗲:**\n_{message.text}_\n\n"
        
    report_text += f"*(𝖯𝗅𝖾𝖺𝗌𝖾 𝖼𝗁𝖾𝖼𝗄 𝗍𝗁𝖾 𝗀𝗋𝗈𝗎𝗉 𝗍𝗈 𝗍𝖺𝗄𝖾 𝖺𝖼𝗍𝗂𝗈𝗇)*"
    
    sent_count = 0
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 𝗚𝗼 𝘁𝗼 𝗠𝗲𝘀𝘀𝗮𝗴𝗲", url=msg_link, style=ButtonStyle.PRIMARY)]])
    for adm in admin_ids:
        try:
            await client.send_message(adm, report_text, disable_web_page_preview=True, reply_markup=markup)
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send report to admin {adm}: {e}")
            
    if sent_count > 0:
        await message.reply_text(f"✅ **𝗘𝗺𝗲𝗿𝗴𝗲𝗻𝗰𝘆 𝗥𝗲𝗽𝗼𝗿𝘁 𝘀𝗲𝗻𝘁 𝘀𝗲𝗰𝘂𝗿𝗲𝗹𝘆 𝘁𝗼 {sent_count} 𝗮𝗱𝗺𝗶𝗻(𝘀).**")
    else:
        await message.reply_text("⚠️ **𝐅𝐚𝐢𝐥𝐞𝐝 𝐭𝐨 𝐫𝐞𝐚𝐜𝐡 𝐚𝐝𝐦𝐢𝐧𝐬.** 𝖳𝗁𝖾𝗒 𝗆𝗂𝗀𝗁𝗍 𝗁𝖺𝗏𝖾 𝖻𝗅𝗈𝖼𝗄𝖾𝖽 𝗍𝗁𝖾 𝖻𝗈𝗍 𝗂𝗇 𝗍𝗁𝖾𝗂𝗋 𝗉𝗋𝗂𝗏𝖺𝗍𝖾 𝗆𝖾𝗌𝗌𝖺𝗀𝖾𝗌.")

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

    if link_en and re.search(r"(https?://|t\.me/|www\.)", text):
        issue_warn = True
        warn_reason = "Sending unauthorized links"

    if bw_en and not issue_warn:
        if any(word in text for word in bad_words if word.strip()):
            issue_warn = True
            warn_reason = "Using prohibited language"

    if not issue_warn:
        if user_id not in SPAM_TRACKER: SPAM_TRACKER[user_id] = []
        SPAM_TRACKER[user_id].append(current_time)
        SPAM_TRACKER[user_id] = [t for t in SPAM_TRACKER[user_id] if current_time - t < 3] 
        if len(SPAM_TRACKER[user_id]) >= 5:
            issue_warn = True
            warn_reason = "Extreme message flooding"

    if issue_warn:
        await message.delete()
        warns = await db.add_punishment(user_id, chat_id_str, "warn", reason=warn_reason)
        
        if am_en and warns >= warn_lim:
            mutes = await db.add_punishment(user_id, chat_id_str, "mute", expiry_ts=current_time + 86400, reason=f"Hit warnings limit ({warn_reason})")
            await db.remove_punishment(user_id, chat_id_str, "warn") 
            
            if ab_en and mutes >= mute_lim:
                await db.add_punishment(user_id, chat_id_str, "ban", reason="Hit mutes limit")
                alert = await message.reply_text(f"🚫 {message.from_user.mention} 𝐰𝐚𝐬 **𝐀𝐮𝐭𝐨-𝐁𝐚𝐧𝐧𝐞𝐝** 𝐟𝐨𝐫 𝐫𝐞𝐩𝐞𝐚𝐭𝐞𝐝𝐥𝐲 𝐛𝐫𝐞𝐚𝐤𝐢𝐧𝐠 𝐫𝐮𝐥𝐞𝐬 ({mutes}/{mute_lim} 𝐦𝐮𝐭𝐞𝐬).")
            else:
                alert = await message.reply_text(f"🔇 {message.from_user.mention} 𝐰𝐚𝐬 **𝐀𝐮𝐭𝐨-𝐌𝐮𝐭𝐞𝐝 𝐟𝐨𝐫 𝟐𝟒𝐡** 𝐟𝐨𝐫 𝐡𝐢𝐭𝐭𝐢𝐧𝐠 {warn_lim}/{warn_lim} 𝐰𝐚𝐫𝐧𝐢𝐧𝐠𝐬.")
        else:
            alert = await message.reply_text(f"⚠️ {message.from_user.mention}, 𝐲𝐨𝐮 𝐡𝐚𝐯𝐞 𝐛𝐞𝐞𝐧 𝐰𝐚𝐫𝐧𝐞𝐝! ({warns}/{warn_lim})\n𝐑𝐞𝐚𝐬𝐨𝐧: {warn_reason}")
            
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
    
    await callback.answer("✅ 𝗬𝗼𝘂𝗿 𝗮𝗽𝗽𝗲𝗮𝗹 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝘀𝘂𝗯𝗺𝗶𝘁𝘁𝗲𝗱 𝘁𝗼 𝘁𝗵𝗲 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝘁𝗶𝗼𝗻.", show_alert=True)
    try: await callback.message.edit_text(callback.message.text + "\n\n✅ **𝗔𝗽𝗽𝗲𝗮𝗹 𝗦𝘂𝗯𝗺𝗶𝘁𝘁𝗲𝗱.** 𝖯𝗅𝖾𝖺𝗌𝖾 𝗐𝖺𝗂𝗍 𝖿𝗈𝗋 𝖺𝖽𝗆𝗂𝗇 𝗋𝖾𝗏𝗂𝖾𝗐.", reply_markup=None)
    except Exception: pass
    
    if scope == "global":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ 𝗨𝗻{ptype.capitalize()}", callback_data=f"log_un{ptype}_{user_id}", style=ButtonStyle.SUCCESS)], [InlineKeyboardButton("❌ 𝗥𝗲𝗷𝗲𝗰𝘁 𝗔𝗽𝗽𝗲𝗮𝗹", callback_data=f"log_reject_{user_id}", style=ButtonStyle.DANGER)]])
        await log_to_channel(client, f"⚖️ **𝗡𝗘𝗪 𝗚𝗟𝗢𝗕𝗔𝗟 𝗔𝗣𝗣𝗘𝗔𝗟**\n\n👤 𝗨𝘀𝗲𝗿: `{user_id}`\n𝗧𝘆𝗽𝗲: **{ptype.upper()}**\n\n𝖯𝗅𝖾𝖺𝗌𝖾 𝗋𝖾𝗏𝗂𝖾𝗐:", markup)
    else:
        g_sett = await db.get_group_settings(int(chat_id))
        connected_by = g_sett.get("connected_by")
        if connected_by:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ 𝗨𝗻{ptype.capitalize()}", callback_data=f"admin_un{ptype}_{chat_id}_{user_id}", style=ButtonStyle.SUCCESS)], [InlineKeyboardButton("❌ 𝗥𝗲𝗷𝗲𝗰𝘁 𝗔𝗽𝗽𝗲𝗮𝗹", callback_data=f"admin_reject_{chat_id}_{user_id}", style=ButtonStyle.DANGER)]])
            try: await client.send_message(connected_by, f"⚖️ **𝗚𝗥𝗢𝗨𝗣 𝗔𝗣𝗣𝗘𝗔𝗟**\n\n👤 𝗨𝘀𝗲𝗿: `{user_id}`\n👥 𝗚𝗿𝗼𝘂𝗽: `{callback.message.chat.title}`\n𝗧𝘆𝗽𝗲: **{ptype.upper()}**", reply_markup=markup)
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
        try: await client.send_message(target_user, "❌ 𝗬𝗼𝘂𝗿 𝗮𝗽𝗽𝗲𝗮𝗹 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝗿𝗲𝘃𝗶𝗲𝘄𝗲𝗱 𝗮𝗻𝗱 **𝗿𝗲𝗷𝗲𝗰𝘁𝗲𝗱** 𝗯𝘆 𝘁𝗵𝗲 𝗮𝗱𝗺𝗶𝗻𝗶𝘀𝘁𝗿𝗮𝘁𝗶𝗼𝗻.")
        except: pass
        return await callback.message.edit_text(callback.message.text + "\n\n❌ **𝗦𝘁𝗮𝘁𝘂𝘀: 𝗥𝗘𝗝𝗘𝗖𝗧𝗘𝗗**")

    await db.remove_punishment(target_user, chat_id, action.replace("un", ""))
    await callback.answer(f"✅ 𝗨𝘀𝗲𝗿 {action}𝗲𝗱!", show_alert=True)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ **𝗦𝘁𝗮𝘁𝘂𝘀: {action.upper()}𝗘𝗗**")
    
    try: await client.send_message(target_user, f"✅ 𝗚𝗼𝗼𝗱 𝗻𝗲𝘄𝘀! 𝖸𝗈𝗎𝗋 `{action.replace('un', '')}` 𝗁𝖺𝗌 𝖻𝖾𝖾𝗇 𝗅𝗂𝖿𝗍𝖾𝖽 𝖻𝗒 𝗍𝗁𝖾 𝖺𝖽𝗆𝗂𝗇𝗂𝗌𝗍𝗋𝖺𝗍𝗈𝗋𝗌.")
    except: pass
