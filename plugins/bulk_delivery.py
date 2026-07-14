import logging
import time
import string
import random
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions, WebAppInfo
from pyrogram.errors import UserIsBlocked, PeerIdInvalid
import math
from database.multi_db import db
from config import Config
from plugins.media_engine import get_initial_media_markup
from plugins.shortener import VERIFICATION_TOKENS, get_shortlink

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

logger = logging.getLogger(__name__)
LAST_CAUTION_MESSAGE = {}
USER_CLICK_TRACKER = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    if not Config.FSUB_CHANNELS: return True
    for channel in Config.FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status.value in ["left", "kicked", "banned", "restricted"]: return False
        except Exception: return False
    return True

async def execute_file_delivery(client: Client, chat_id: int, file_data: dict, user_first_name: str):
    try:
        raw_caption = await db.get_custom_caption(None) 
        f_name = file_data.get("title", "Unknown File")
        f_size = format_size(file_data.get("size", 0))
        mention = f"<a href='tg://user?id={chat_id}'>{user_first_name}</a>"
        
        final_caption = raw_caption.replace("{file_name}", f_name).replace("{size}", f_size).replace("{mention}", mention)
        
        file_unique_id = file_data.get("file_unique_id")
        media_buttons = InlineKeyboardMarkup(get_initial_media_markup(file_unique_id))
        
        sent_file = await client.send_cached_media(
            chat_id=chat_id, 
            file_id=file_data.get("file_id"), 
            caption=final_caption,
            reply_markup=media_buttons 
        )
        settings = await db.get_settings()
        if settings.get("file_delete_enabled", False):
            delete_time_mins = settings.get("file_delete_time", 10)
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                trigger_ghost_self_destruct(client, chat_id, sent_file.id, delete_time_mins * 60)
                
                if chat_id in LAST_CAUTION_MESSAGE:
                    try: await client.delete_messages(chat_id, LAST_CAUTION_MESSAGE[chat_id])
                    except Exception: pass 

                warning_msg = await client.send_message(
                    chat_id, 
                    f"⏳ **𝗔𝘁𝘁𝗲𝗻𝘁𝗶𝗼𝗻:** 𝖳𝗁𝗂𝗌 𝖿𝗂𝗅𝖾 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝗌𝖾𝗅𝖿-𝖽𝖾𝗌𝗍𝗋𝗎𝖼𝗍 𝗂𝗇 {delete_time_mins} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌 𝗍𝗈 𝗉𝗋𝗈𝗍𝖾𝖼𝗍 𝗈𝗎𝗋 𝗌𝖾𝗋𝗏𝖾𝗋𝗌. 𝖯𝗅𝖾𝖺𝗌𝖾 𝖿𝗈𝗋𝗐𝖺𝗋𝖽 𝗂𝗍 𝗍𝗈 𝗒𝗈𝗎𝗋 𝖲𝖺𝗏𝖾𝖽 𝖬𝖾𝗌𝗌𝖺𝗀𝖾𝗌!"
                )
                
                LAST_CAUTION_MESSAGE[chat_id] = warning_msg.id
                trigger_ghost_self_destruct(client, chat_id, warning_msg.id, delete_time_mins * 60)
                
            except Exception as e:
                logger.error(f"Ghost destruct error: {e}")
        return sent_file
    except Exception as send_err:
        raise send_err

@Client.on_callback_query(filters.regex(r"^sendfile_(.+)"))
async def direct_send_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    current_time = time.time()
    
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ 𝖯𝗋𝗈𝖼𝖾𝗌𝗌𝗂𝗇𝗀... 𝗉𝗅𝖾𝖺𝗌𝖾 𝗐𝖺𝗂𝗍 𝖺 𝗆𝗈𝗆𝖾𝗇𝗍 𝖻𝖾𝖿𝗈𝗋𝖾 𝖼𝗅𝗂𝖼𝗄𝗂𝗇𝗀 𝖺𝗀𝖺𝗂𝗇.", show_alert=False)
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
            buttons.append([InlineKeyboardButton(text=f"𝗝𝗼𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 #{idx}", url=invite_link, style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton(text="🔄 𝗥𝗲𝗾𝘂𝗲𝘀𝘁 𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻", callback_data="check_membership_retry", style=ButtonStyle.SUCCESS)])
        await callback.message.reply_text("🛑 **𝐋𝐨𝐜𝐤 𝐖𝐚𝐫𝐧𝐢𝐧𝐠:**\n𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐣𝐨𝐢𝐧 𝐨𝐮𝐫 𝐨𝐟𝐟𝐢𝐜𝐢𝐚𝐥 𝐝𝐢𝐬𝐭𝐫𝐢𝐛𝐮𝐭𝐢𝐨𝐧 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬 𝐛𝐞𝐟𝐨𝐫𝐞 𝐝𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐢𝐧𝐠 𝐟𝐢𝐥𝐞𝐬.", reply_markup=InlineKeyboardMarkup(buttons))
        return await callback.answer("𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐣𝐨𝐢𝐧 𝐭𝐡𝐞 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬 𝐟𝐢𝐫𝐬𝐭!", show_alert=True)

    file_data = await db.get_file(db_id)
    if not file_data: return await callback.answer("❌ 𝐄𝐫𝐫𝐨𝐫: 𝐅𝐢𝐥𝐞 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝 𝐢𝐧 𝐝𝐚𝐭𝐚𝐛𝐚𝐬𝐞.", show_alert=True)

    try:
        await execute_file_delivery(client, user_id, file_data, callback.from_user.first_name)
        if callback.message.chat.type.name in ["GROUP", "SUPERGROUP"]:
            await callback.answer("✅ 𝗙𝗶𝗹𝗲 𝘀𝗲𝗻𝘁 𝘀𝗲𝗰𝘂𝗿𝗲𝗹𝘆 𝘁𝗼 𝘆𝗼𝘂𝗿 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗠𝗲𝘀𝘀𝗮𝗴𝗲𝘀!", show_alert=True)
        else:
            await callback.answer("✅ 𝗙𝗶𝗹𝗲 𝗿𝗲𝘁𝗿𝗶𝗲𝘃𝗲𝗱 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!", show_alert=False)
    except (UserIsBlocked, PeerIdInvalid, Exception) as e:
        bot_me = await client.get_me()
        start_url = f"https://t.me/{bot_me.username}?start=getfile_{db_id}"
        error_text = f"👋 𝗛𝗲𝘆 {callback.from_user.mention},\n\n𝖨 𝖼𝖺𝗇𝗇𝗈𝗍 𝗌𝖾𝗇𝖽 𝖿𝗂𝗅𝖾𝗌 𝗍𝗈 𝗒𝗈𝗎𝗋 𝖯𝖬 𝗎𝗇𝗍𝗂𝗅 𝗒𝗈𝗎 𝗌𝗍𝖺𝗋𝗍 𝗆𝖾! 𝖯𝗅𝖾𝖺𝗌𝖾 𝖼𝗅𝗂𝖼𝗄 𝗍𝗁𝖾 𝖻𝗎𝗍𝗍𝗈𝗇 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝗌𝗍𝖺𝗋𝗍 𝗍𝗁𝖾 𝖻𝗈𝗍 𝖺𝗇𝖽 𝗋𝖾𝖼𝖾𝗂𝗏𝖾 𝗒𝗈𝗎𝗋 𝖿𝗂𝗅𝖾."
        alert_msg = await client.send_message(chat_id=chat_id, text=error_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 𝗦𝘁𝗮𝗿𝘁 𝗕𝗼𝘁 𝘁𝗼 𝗚𝗲𝘁 𝗙𝗶𝗹𝗲", url=start_url, style=ButtonStyle.SUCCESS)]]))
        await callback.answer("⚠️ 𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐬𝐭𝐚𝐫𝐭 𝐭𝐡𝐞 𝐛𝐨𝐭 𝐢𝐧 𝐏𝐌 𝐟𝐢𝐫𝐬𝐭!", show_alert=True)
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

        current_time = time.time()
        if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0: return 
        USER_CLICK_TRACKER[user_id] = current_time

        try: await message.delete()
        except Exception: pass

        if cmd.startswith("verify_"):
            token = cmd.split("_")[1]
            if token in VERIFICATION_TOKENS:
                token_data = VERIFICATION_TOKENS[token]
                
                if token_data["user_id"] == user_id:
                    await db.grant_verification_pass(user_id)
                    del VERIFICATION_TOKENS[token]
                    
                    settings = await db.get_settings()
                    del_enabled = settings.get("filter_delete_enabled", False)
                    del_time = settings.get("filter_delete_time", 5)

                    v_text = "✅ **𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹!** 𝖸𝗈𝗎 𝗇𝗈𝗐 𝗁𝖺𝗏𝖾 𝗍𝖾𝗆𝗉𝗈𝗋𝖺𝗋𝗒 𝗎𝗇𝗅𝗂𝗆𝗂𝗍𝖾𝖽 𝖺𝖼𝖼𝖾𝗌𝗌 𝗍𝗈 𝖽𝗂𝗋𝖾𝖼𝗍 𝖿𝗂𝗅𝖾𝗌."
                    if del_enabled: v_text += f"\n\n⏳ *𝖭𝗈𝗍𝖾: 𝖳𝗁𝗂𝗌 𝗆𝖾𝗌𝗌𝖺𝗀𝖾 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗇 {del_time} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌.*"

                    success_msg = await message.reply_text(v_text)
                    
                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, success_msg.id, del_time * 60)
                        except Exception: pass

                    pending_file = token_data.get("pending_file")
                    if pending_file:
                        file_data = await db.get_file(pending_file)
                        if file_data: await execute_file_delivery(client, user_id, file_data, message.from_user.first_name)
                return
            else:
                return await message.reply_text("❌ **𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐨𝐫 𝐄𝐱𝐩𝐢𝐫𝐞𝐝 𝐓𝐨𝐤𝐞𝐧.** 𝐏𝐥𝐞𝐚𝐬𝐞 𝐬𝐞𝐚𝐫𝐜𝐡 𝐟𝐨𝐫 𝐭𝐡𝐞 𝐦𝐨𝐯𝐢𝐞 𝐚𝐠𝐚𝐢𝐧.")

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
                    buttons.append([InlineKeyboardButton(text=f"𝗝𝗼𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 #{idx}", url=invite_link, style=ButtonStyle.PRIMARY)])
                buttons.append([InlineKeyboardButton(text="🔄 𝗥𝗲𝗾𝘂𝗲𝘀𝘁 𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻", callback_data=f"retry_getfile_{db_id}", style=ButtonStyle.SUCCESS)])
                return await message.reply_text("🛑 **𝐋𝐨𝐜𝐤 𝐖𝐚𝐫𝐧𝐢𝐧𝐠:**\n𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐣𝐨𝐢𝐧 𝐨𝐮𝐫 𝐨𝐟𝐟𝐢𝐜𝐢𝐚𝐥 𝐝𝐢𝐬𝐭𝐫𝐢𝐛𝐮𝐭𝐢𝐨𝐧 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬 𝐛𝐞𝐟𝐨𝐫𝐞 𝐝𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐢𝐧𝐠 𝐟𝐢𝐥𝐞𝐬.", reply_markup=InlineKeyboardMarkup(buttons))

            settings = await db.get_settings()
            from plugins.vip_system import DEFAULT_PLANS, FREE_USER_LIMITS
            active_plan = await db.get_active_vip_plan(user_id)
            user_limits = DEFAULT_PLANS.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan else FREE_USER_LIMITS
            
            has_bypass = user_limits.get("shortlink_bypass", False)
            if not has_bypass: has_bypass = await db.has_active_verification_pass(user_id)
            
            if settings.get("shortener_enabled", False) and not has_bypass:
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
                        "🔒 **𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻 𝗥𝗲𝗾𝘂𝗶𝗿𝗲𝗱**\n\n"
                        "𝖳𝗈 𝗄𝖾𝖾𝗉 𝗍𝗁𝗂𝗌 𝖻𝗈𝗍 𝖺𝗅𝗂𝗏𝖾, 𝗉𝗅𝖾𝖺𝗌𝖾 𝗏𝖾𝗋𝗂𝖿𝗒 𝗒𝗈𝗎𝗋 𝖺𝖼𝖼𝖾𝗌𝗌. 𝖳𝗁𝗂𝗌 𝗐𝗂𝗅𝗅 𝗀𝗋𝖺𝗇𝗍 𝗒𝗈𝗎 **𝟮𝟰 𝗛𝗼𝘂𝗿𝘀 𝗼𝗳 𝗨𝗻𝗹𝗶𝗺𝗶𝘁𝗲𝗱 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝘀!**\n\n"
                        f"👉 [𝖢𝗅𝗂𝖼𝗄 𝖧𝖾𝗋𝖾 𝗍𝗈 𝖵𝖾𝗋𝗂𝖿𝗒]({short_link})\n\n"
                        "➖➖➖➖➖➖➖➖➖➖\n"
                        "🛠 **𝗔𝗱𝗺𝗶𝗻 𝗡𝗼𝘁𝗲 (𝗜𝗳 𝗹𝗶𝗻𝗸𝘀 𝗮𝗿𝗲 𝗯𝗿𝗼𝗸𝗲𝗻):**\n"
                        "𝖴𝗌𝖾 `/setshort <API_KEY> <URL_TEMPLATE>` 𝗍𝗈 𝗍𝖾𝗌𝗍 𝖺𝗇𝖽 𝖿𝗂𝗑 𝗒𝗈𝗎𝗋 𝖼𝗈𝗇𝖿𝗂𝗀𝗎𝗋𝖺𝗍𝗂𝗈𝗇!"
                    )
                    if del_enabled: v_req_text += f"\n\n⏳ *𝖭𝗈𝗍𝖾: 𝖳𝗁𝗂𝗌 𝗆𝖾𝗌𝗌𝖺𝗀𝖾 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗇 {del_time} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌.*"

                    req_msg = await message.reply_text(
                        v_req_text, link_preview_options=LinkPreviewOptions(is_disabled=True), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 𝗩𝗲𝗿𝗶𝗳𝘆 𝗔𝗰𝗰𝗲𝘀𝘀", url=short_link, style=ButtonStyle.SUCCESS)]])
                    )

                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, req_msg.id, del_time * 60)
                        except Exception: pass
                    return

            file_data = await db.get_file(db_id)
            if not file_data: return await message.reply_text("❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐅𝐢𝐥𝐞 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝 𝐢𝐧 𝐝𝐚𝐭𝐚𝐛𝐚𝐬𝐞 𝐨𝐫 𝐡𝐚𝐬 𝐛𝐞𝐞𝐧 𝐝𝐞𝐥𝐞𝐭𝐞𝐝.")
            await execute_file_delivery(client, user_id, file_data, message.from_user.first_name)

@Client.on_callback_query(filters.regex(r"^retry_getfile_(.+)"))
async def retry_getfile_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    current_time = time.time()
    
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ 𝖢𝗁𝖾𝖼𝗄𝗂𝗇𝗀... 𝗉𝗅𝖾𝖺𝗌𝖾 𝗐𝖺𝗂𝗍 𝖺 𝗆𝗈𝗆𝖾𝗇𝗍.", show_alert=False)
    USER_CLICK_TRACKER[user_id] = current_time

    db_id = callback.data.split("_")[2]
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined: return await callback.answer("❌ 𝐘𝐨𝐮 𝐬𝐭𝐢𝐥𝐥 𝐡𝐚𝐯𝐞𝐧'𝐭 𝐣𝐨𝐢𝐧𝐞𝐝 𝐚𝐥𝐥 𝐫𝐞𝐪𝐮𝐢𝐫𝐞𝐝 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬!", show_alert=True)
    file_data = await db.get_file(db_id)
    if not file_data: return await callback.answer("❌ 𝐄𝐫𝐫𝐨𝐫: 𝐅𝐢𝐥𝐞 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝.", show_alert=True)
    await callback.message.delete()
    await execute_file_delivery(client, user_id, file_data, callback.from_user.first_name)

@Client.on_callback_query(filters.regex(r"^check_membership_retry$"))
async def standard_retry_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    current_time = time.time()
    
    if user_id in USER_CLICK_TRACKER and current_time - USER_CLICK_TRACKER[user_id] < 3.0:
        return await callback.answer("⏳ 𝖢𝗁𝖾𝖼𝗄𝗂𝗇𝗀... 𝗉𝗅𝖾𝖺𝗌𝖾 𝗐𝖺𝗂𝗍 𝖺 𝗆𝗈𝗆𝖾𝗇𝗍.", show_alert=False)
    USER_CLICK_TRACKER[user_id] = current_time

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined: return await callback.answer("❌ 𝐘𝐨𝐮 𝐬𝐭𝐢𝐥𝐥 𝐡𝐚𝐯𝐞𝐧'𝐭 𝐣𝐨𝐢𝐧𝐞𝐝 𝐚𝐥𝐥 𝐫𝐞𝐪𝐮𝐢𝐫𝐞𝐝 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬!", show_alert=True)
    await callback.message.delete()
    await callback.message.reply_text("✅ **𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹!** 𝖯𝗅𝖾𝖺𝗌𝖾 𝖼𝗅𝗂𝖼𝗄 𝗍𝗁𝖾 𝖽𝗈𝗐𝗇𝗅𝗈𝖺𝖽 𝖻𝗎𝗍𝗍𝗈𝗇 𝖺𝗀𝖺𝗂𝗇.")
