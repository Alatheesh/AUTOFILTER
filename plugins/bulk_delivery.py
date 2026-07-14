import asyncio
import time
import logging
import aiohttp
import json
import string
import random
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import math
from pyrogram.errors import FloodWait, UserIsBlocked # 🚀 NEW: Critical safety imports
from database.multi_db import db
from config import Config
from plugins.search import BULK_CACHE
from plugins.media_engine import get_initial_media_markup

# 🚀 Importing the new isolated engine!
from plugins.shortener import VERIFICATION_TOKENS, get_shortlink

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

logger = logging.getLogger(__name__)

async def check_fsub_for_bulk(client: Client, user_id: int) -> bool:
    if not Config.FSUB_CHANNELS: return True
    for channel in Config.FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status.value in ["left", "kicked", "banned", "restricted"]: return False
        except Exception: return False
    return True

@Client.on_message(filters.command("start") & filters.private, group=2)
async def handle_bulk_delivery(client: Client, message: Message):
    if len(message.command) > 1:
        cmd = message.command[1]
        user_id = message.from_user.id

        try: await message.delete()
        except Exception: pass
        
        # 🚀 INSERT THE NEW CODE EXACTLY HERE 🚀
        if cmd == "buyvip":
            from plugins.vip_system import buy_vip_command
            try:
                return await buy_vip_command(client, message)
            except StopPropagation:
                return # Safely catches the stop signal from your VIP menu
        # ----------------------------------------

        if cmd.startswith("bapp_"):
            short_id = cmd.split("_")[1]
            if short_id not in BULK_CACHE:
                return await message.reply_text("⏳ **𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐄𝐱𝐩𝐢𝐫𝐞𝐝!**\n𝐏𝐥𝐞𝐚𝐬𝐞 𝐬𝐞𝐚𝐫𝐜𝐡 𝐟𝐨𝐫 𝐭𝐡𝐞 𝐦𝐨𝐯𝐢𝐞 𝐚𝐠𝐚𝐢𝐧 𝐢𝐧 𝐭𝐡𝐞 𝐠𝐫𝐨𝐮𝐩.")
            
            web_app_url = BULK_CACHE[short_id][2]
            
            settings = await db.get_settings()
            del_enabled = settings.get("filter_delete_enabled", False)
            del_time = settings.get("filter_delete_time", 5)

            msg_text = "📱 **𝗬𝗼𝘂𝗿 𝗠𝘂𝗹𝘁𝗶-𝗦𝗲𝗹𝗲𝗰𝘁 𝗔𝗽𝗽 𝗶𝘀 𝗥𝗲𝗮𝗱𝘆!**\n𝖢𝗅𝗂𝖼𝗄 𝗍𝗁𝖾 𝖻𝗎𝗍𝗍𝗈𝗇 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝗈𝗉𝖾𝗇 𝗂𝗍 𝖺𝗇𝖽 𝖼𝗁𝗈𝗈𝗌𝖾 𝗒𝗈𝗎𝗋 𝖿𝗂𝗅𝖾𝗌."
            if del_enabled:
                msg_text += f"\n\n⏳ *𝖭𝗈𝗍𝖾: 𝖳𝗁𝗂𝗌 𝗆𝖾𝗌𝗌𝖺𝗀𝖾 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗇 {del_time} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌.*"

            app_msg = await message.reply_text(
                msg_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 𝗟𝗮𝘂𝗻𝗰𝗵 𝗪𝗲𝗯 𝗔𝗽𝗽", web_app=WebAppInfo(url=web_app_url))]])
            )

            if del_enabled:
                try:
                    from plugins.advanced import trigger_ghost_self_destruct
                    trigger_ghost_self_destruct(client, user_id, app_msg.id, del_time * 60)
                except Exception as e:
                    logger.error(f"Failed to ghost destruct bapp msg: {e}")

            return

        if cmd.startswith("blk"):
            is_joined = await check_fsub_for_bulk(client, user_id)
            if not is_joined:
                buttons = []
                for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                    try:
                        chat = await client.get_chat(channel)
                        invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
                    except Exception: invite_link = "https://t.me/telegram"
                    buttons.append([InlineKeyboardButton(text=f"𝗝𝗼𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 #{idx}", url=invite_link)])
                return await message.reply_text("🛑 **𝐋𝐨𝐜𝐤 𝐖𝐚𝐫𝐧𝐢𝐧𝐠:**\n𝐘𝐨𝐮 𝐦𝐮𝐬𝐭 𝐣𝐨𝐢𝐧 𝐨𝐮𝐫 𝐨𝐟𝐟𝐢𝐜𝐢𝐚𝐥 𝐜𝐡𝐚𝐧𝐧𝐞𝐥𝐬 𝐛𝐞𝐟𝐨𝐫𝐞 𝐝𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐢𝐧𝐠 𝐛𝐮𝐥𝐤 𝐟𝐢𝐥𝐞𝐬.", reply_markup=InlineKeyboardMarkup(buttons))

            settings = await db.get_settings()
            if settings.get("shortener_enabled", False) or settings.get("is_shortener", False):
                u_sett = await db.get_user_settings(user_id)
                pass_time = u_sett.get("shortener_pass", 0)
                
                if time.time() > pass_time:
                    token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                    VERIFICATION_TOKENS[token] = {"user_id": user_id, "pending_file": None}
                    bot_me = await client.get_me()
                    verify_link = f"https://t.me/{bot_me.username}?start=verify_{token}"
                    
                    api = settings.get("shortener_api") or ""
                    site = settings.get("shortener_url") or "https://api.gplinks.com/api"
                    
                    if api: short_link = await get_shortlink(verify_link, api, site)
                    else: short_link = verify_link
                        
                    del_enabled = settings.get("filter_delete_enabled", False)
                    del_time = settings.get("filter_delete_time", 5)

                    v_req_text = (
                        "🔒 **𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻 𝗥𝗲𝗾𝘂𝗶𝗿𝗲𝗱 𝗳𝗼𝗿 𝗕𝘂𝗹𝗸 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝘀**\n\n"
                        "𝖳𝗈 𝗄𝖾𝖾𝗉 𝗍𝗁𝗂𝗌 𝖻𝗈𝗍 𝖺𝗅𝗂𝗏𝖾, 𝗉𝗅𝖾𝖺𝗌𝖾 𝗏𝖾𝗋𝗂𝖿𝗒 𝗒𝗈𝗎𝗋 𝖺𝖼𝖼𝖾𝗌𝗌. 𝖳𝗁𝗂𝗌 𝗐𝗂𝗅𝗅 𝗀𝗋𝖺𝗇𝗍 𝗒𝗈𝗎 **𝟮𝟰 𝗛𝗼𝘂𝗿𝘀 𝗼𝗳 𝗨𝗻𝗹𝗶𝗺𝗶𝘁𝗲𝗱 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝘀!**\n\n"
                        f"👉 [𝖢𝗅𝗂𝖼𝗄 𝖧𝖾𝗋𝖾 𝗍𝗈 𝖵𝖾𝗋𝗂𝖿𝗒]({short_link})\n\n"
                        "*(𝖮𝗇𝖼𝖾 𝗏𝖾𝗋𝗂𝖿𝗂𝖾𝖽, 𝗃𝗎𝗌𝗍 𝗈𝗉𝖾𝗇 𝗒𝗈𝗎𝗋 𝗆𝗂𝗇𝗂𝗆𝗂𝗓𝖾𝖽 𝖶𝖾𝖻 𝖠𝗉𝗉 𝖺𝗇𝖽 𝖼𝗅𝗂𝖼𝗄 𝖲𝖾𝗇𝖽 𝖺𝗀𝖺𝗂𝗇!)*\n\n"
                        "➖➖➖➖➖➖➖➖➖➖\n"
                        "🛠 **𝗔𝗱𝗺𝗶𝗻 𝗡𝗼𝘁𝗲 (𝗜𝗳 𝗹𝗶𝗻𝗸𝘀 𝗮𝗿𝗲 𝗯𝗿𝗼𝗸𝗲𝗻):**\n"
                        "𝖴𝗌𝖾 `/setshort <API_KEY> <URL_TEMPLATE>` 𝗍𝗈 𝗍𝖾𝗌𝗍 𝖺𝗇𝖽 𝖿𝗂𝗑 𝗒𝗈𝗎𝗋 𝖼𝗈𝗇𝖿𝗂𝗀𝗎𝗋𝖺𝗍𝗂𝗈𝗇!"
                    )
                    
                    if del_enabled: v_req_text += f"\n\n⏳ *𝖭𝗈𝗍𝖾: 𝖳𝗁𝗂𝗌 𝗆𝖾𝗌𝗌𝖺𝗀𝖾 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝖽𝖾𝗅𝖾𝗍𝖾 𝗂𝗇 {del_time} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌.*"

                    req_msg = await message.reply_text(
                        v_req_text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 𝗩𝗲𝗿𝗶𝗳𝘆 𝗔𝗰𝗰𝗲𝘀𝘀", url=short_link)]])
                    )

                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, req_msg.id, del_time * 60)
                        except Exception: pass
                    return

            parts = cmd.split("_")
            if len(parts) < 3: return await message.reply_text("❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐛𝐮𝐥𝐤 𝐫𝐞𝐪𝐮𝐞𝐬𝐭 𝐟𝐨𝐫𝐦𝐚𝐭.")
                
            req_type = parts[0]  
            short_id = parts[1]
            payload = parts[2]
            
            if short_id not in BULK_CACHE:
                return await message.reply_text("⏳ **𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐄𝐱𝐩𝐢𝐫𝐞𝐝!**\n𝐘𝐨𝐮𝐫 𝐬𝐞𝐚𝐫𝐜𝐡 𝐫𝐞𝐬𝐮𝐥𝐭 𝐡𝐚𝐬 𝐞𝐱𝐩𝐢𝐫𝐞𝐝 𝐭𝐨 𝐬𝐚𝐯𝐞 𝐦𝐞𝐦𝐨𝐫𝐲. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐬𝐞𝐚𝐫𝐜𝐡 𝐟𝐨𝐫 𝐭𝐡𝐞 𝐦𝐨𝐯𝐢𝐞 𝐚𝐠𝐚𝐢𝐧 𝐢𝐧 𝐭𝐡𝐞 𝐠𝐫𝐨𝐮𝐩.")
                
            cached_time, cached_files, _ = BULK_CACHE[short_id]
            selected_indices = []

            if req_type == "blks":
                try: selected_indices = [int(x) for x in payload.split("-") if x.isdigit()]
                except Exception: return await message.reply_text("❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐅𝐚𝐢𝐥𝐞𝐝 𝐭𝐨 𝐫𝐞𝐚𝐝 𝐲𝐨𝐮𝐫 𝐟𝐢𝐥𝐞 𝐬𝐞𝐥𝐞𝐜𝐭𝐢𝐨𝐧𝐬.")
            
            elif req_type == "blkc":
                status_msg = await message.reply_text("☁️ **𝗙𝗲𝘁𝗰𝗵𝗶𝗻𝗴 𝘆𝗼𝘂𝗿 𝗺𝗮𝘀𝘀𝗶𝘃𝗲 𝘀𝗲𝗹𝗲𝗰𝘁𝗶𝗼𝗻 𝗳𝗿𝗼𝗺 𝘁𝗵𝗲 𝘀𝗲𝗰𝘂𝗿𝗲 𝗰𝗹𝗼𝘂𝗱...**")
                try:
                    async with aiohttp.ClientSession() as session:
                        if payload.startswith("np_"):
                            np_id = payload.replace("np_", "")
                            async with session.get(f"https://api.npoint.io/{np_id}") as resp:
                                if resp.status == 200:
                                    text_data = await resp.text()
                                    selected_indices = json.loads(text_data)
                                else:
                                    return await status_msg.edit_text(f"❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐍𝐩𝐨𝐢𝐧𝐭 𝐟𝐞𝐭𝐜𝐡 𝐟𝐚𝐢𝐥𝐞𝐝 (𝐂𝐨𝐝𝐞: {resp.status}).")
                                    
                        elif payload.startswith("dp_"):
                            dp_id = payload.replace("dp_", "")
                            async with session.get(f"https://dpaste.com/{dp_id}.txt") as resp:
                                if resp.status == 200:
                                    text_data = await resp.text()
                                    selected_indices = json.loads(text_data)
                                else:
                                    return await status_msg.edit_text(f"❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐃𝐩𝐚𝐬𝐭𝐞 𝐟𝐞𝐭𝐜𝐡 𝐟𝐚𝐢𝐥𝐞𝐝 (𝐂𝐨𝐝𝐞: {resp.status}).")
                        else:
                            # 🚀 SMART FALLBACK: Just Npoint and Dpaste (No Bytebin)
                            async with session.get(f"https://api.npoint.io/{payload}") as resp:
                                if resp.status == 200:
                                    text_data = await resp.text()
                                    selected_indices = json.loads(text_data)
                                else:
                                    async with session.get(f"https://dpaste.com/{payload}.txt") as resp2:
                                        if resp2.status == 200:
                                            text_data = await resp2.text()
                                            selected_indices = json.loads(text_data)
                                        else:
                                            # THIS WILL TELL US EXACTLY WHY IT IS FAILING!
                                            return await status_msg.edit_text(
                                                f"❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐂𝐥𝐨𝐮𝐝 𝐟𝐞𝐭𝐜𝐡 𝐟𝐚𝐢𝐥𝐞𝐝.\n\n"
                                                f"🛠 **𝐃𝐞𝐛𝐮𝐠 𝐈𝐧𝐟𝐨:** 𝐍𝐩𝐨𝐢𝐧𝐭 `[{resp.status}]`, 𝐃𝐩𝐚𝐬𝐭𝐞 `[{resp2.status}]`\n"
                                                f"**𝐑𝐞𝐜𝐞𝐢𝐯𝐞𝐝 𝐈𝐃:** `{payload}`"
                                            )
                    await status_msg.delete()
                    
                except Exception as e:
                    logger.error(f"Bulk Cloud Fetch Error: {e}")
                    return await status_msg.edit_text(f"❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐍𝐞𝐭𝐰𝐨𝐫𝐤 𝐞𝐫𝐫𝐨𝐫 𝐜𝐨𝐧𝐭𝐚𝐜𝐭𝐢𝐧𝐠 𝐜𝐥𝐨𝐮𝐝. 𝐃𝐞𝐭𝐚𝐢𝐥𝐬: {e}")
                    
            selected_files = []
            for i in selected_indices:
                if 0 <= i < len(cached_files):
                    selected_files.append(cached_files[i])
                    
            if not selected_files: return await message.reply_text("⚠️ 𝐍𝐨 𝐯𝐚𝐥𝐢𝐝 𝐟𝐢𝐥𝐞𝐬 𝐰𝐞𝐫𝐞 𝐬𝐞𝐥𝐞𝐜𝐭𝐞𝐝.")
            
            # 🛑 VIP BACKEND SECURITY CHECK
            try:
                from plugins.vip_system import get_all_plans, FREE_USER_LIMITS
                active_plan = await db.get_active_vip_plan(user_id)
                plans = await get_all_plans()
                user_limits = plans.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan and active_plan in plans else FREE_USER_LIMITS
                bulk_limit = user_limits.get("bulk_select_limit", 10)
            except Exception:
                bulk_limit = 10 
                
            if len(selected_files) > bulk_limit:
                return await message.reply_text(
                    f"🛑 **𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲 𝐋𝐨𝐜𝐤:** 𝐘𝐨𝐮 𝐫𝐞𝐪𝐮𝐞𝐬𝐭𝐞𝐝 **{len(selected_files)}** 𝐟𝐢𝐥𝐞𝐬, 𝐛𝐮𝐭 𝐲𝐨𝐮𝐫 𝐜𝐮𝐫𝐫𝐞𝐧𝐭 𝐭𝐢𝐞𝐫 𝐢𝐬 𝐥𝐢𝐦𝐢𝐭𝐞𝐝 𝐭𝐨 **{bulk_limit}** 𝐟𝐢𝐥𝐞𝐬 𝐩𝐞𝐫 𝐛𝐚𝐭𝐜𝐡.\n\n"
                    f"_𝐏𝐥𝐞𝐚𝐬𝐞 𝐬𝐞𝐥𝐞𝐜𝐭 𝐟𝐞𝐰𝐞𝐫 𝐟𝐢𝐥𝐞𝐬 𝐨𝐫 𝐮𝐩𝐠𝐫𝐚𝐝𝐞 𝐭𝐨 𝐚 𝐕𝐈𝐏 𝐩𝐥𝐚𝐧 𝐭𝐨 𝐮𝐧𝐥𝐨𝐜𝐤 𝐥𝐚𝐫𝐠𝐞𝐫 𝐛𝐚𝐭𝐜𝐡 𝐝𝐨𝐰𝐧𝐥𝐨𝐚𝐝𝐬!_"
                )
            
            status_msg = await message.reply_text(f"📦 **𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 {len(selected_files)} 𝗳𝗶𝗹𝗲𝘀...**\n𝖲𝖾𝗇𝖽𝗂𝗇𝗀 𝗍𝗁𝖾𝗆 𝗌𝖾𝖼𝗎𝗋𝖾𝗅𝗒 𝗍𝗈 𝗒𝗈𝗎𝗋 𝖯𝖬.")
            
            successful = 0
            sent_message_ids = []
            
            # 📝 FETCH CUSTOM CAPTION ONCE FOR THE BATCH
            raw_caption = await db.get_custom_caption(None) # PM delivery falls back to global/default
            
            # 🚀 THE NEW DYNAMIC SAFETY LOOP WITH MEDIA BUTTONS
            for f_data in selected_files:
                if f_data:
                    # 📝 Format placeholders for this specific file
                    f_name = f_data.get("title", "Unknown File")
                    f_size = format_size(f_data.get("size", 0))
                    mention = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
                    
                    final_caption = raw_caption.replace("{file_name}", f_name).replace("{size}", f_size).replace("{mention}", mention)
                    
                    # 🚀 INJECT MEDIA ENGINE BUTTONS HERE
                    file_unique_id = f_data.get("file_unique_id")
                    media_buttons = InlineKeyboardMarkup(get_initial_media_markup(file_unique_id))
                    
                    try:
                        sent_file = await client.send_cached_media(
                            chat_id=user_id, 
                            file_id=f_data.get("file_id"), 
                            caption=final_caption,
                            reply_markup=media_buttons # 👈 Buttons Attached!
                        )
                        sent_message_ids.append(sent_file.id)
                        successful += 1
                        await asyncio.sleep(0.5) # Standard safety timer
                        
                    except FloodWait as e:
                        logger.warning(f"⚠️ FloodWait hit during bulk delivery! Sleeping for {e.value} seconds.")
                        await asyncio.sleep(e.value + 2) # Sleep exactly what Telegram asks + 2s buffer
                        
                        # Try sending the file one more time after waking up
                        try:
                            sent_file = await client.send_cached_media(
                                chat_id=user_id, 
                                file_id=f_data.get("file_id"), 
                                caption=final_caption,
                                reply_markup=media_buttons # 👈 Buttons Attached here too!
                            )
                            sent_message_ids.append(sent_file.id)
                            successful += 1
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass # If it fails again, skip the file and move on
                            
                    except UserIsBlocked:
                        logger.warning(f"User {user_id} blocked the bot during massive bulk delivery.")
                        await status_msg.edit_text("❌ **𝐃𝐞𝐥𝐢𝐯𝐞𝐫𝐲 𝐒𝐭𝐨𝐩𝐩𝐞𝐝:** 𝐘𝐨𝐮 𝐛𝐥𝐨𝐜𝐤𝐞𝐝 𝐭𝐡𝐞 𝐛𝐨𝐭!")
                        return 
                        
                    except Exception as e:
                        logger.error(f"Bulk send error: {e}")
                        await asyncio.sleep(0.5)
                    
            await status_msg.delete()
            
            if settings.get("file_delete_enabled", False):
                del_time = settings.get("file_delete_time", 10)
                summary_msg = await message.reply_text(
                    f"✅ **𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗱𝗲𝗹𝗶𝘃𝗲𝗿𝗲𝗱 {successful} 𝗳𝗶𝗹𝗲𝘀!**\n\n"
                    f"⏳ **𝗖𝗮𝘂𝘁𝗶𝗼𝗻:** 𝖠𝗅𝗅 {successful} 𝖿𝗂𝗅𝖾𝗌 𝗐𝗂𝗅𝗅 𝖻𝖾 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝖽𝖾𝗅𝖾𝗍𝖾𝖽 𝗂𝗇 **{del_time} 𝗆𝗂𝗇𝗎𝗍𝖾𝗌** 𝗍𝗈 𝗉𝗋𝗈𝗍𝖾𝖼𝗍 𝗈𝗎𝗋 𝗌𝖾𝗋𝗏𝖾𝗋𝗌. 𝖯𝗅𝖾𝖺𝗌𝖾 𝖿𝗈𝗋𝗐𝖺𝗋𝖽 𝗍𝗁𝖾𝗆 𝗍𝗈 𝗒𝗈𝗎𝗋 𝖲𝖺𝗏𝖾𝖽 𝖬𝖾𝗌𝗌𝖺𝗀𝖾𝗌!"
                )
                try:
                    from plugins.advanced import trigger_ghost_self_destruct
                    for m_id in sent_message_ids:
                        trigger_ghost_self_destruct(client, user_id, m_id, del_time * 60)
                    trigger_ghost_self_destruct(client, user_id, summary_msg.id, del_time * 60)
                except Exception as e:
                    logger.error(f"Bulk Ghost Destruct Error: {e}")
            else:
                await message.reply_text(f"✅ **𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗱𝗲𝗹𝗶𝘃𝗲𝗿𝗲𝗱 {successful} 𝗳𝗶𝗹𝗲𝘀 𝗱𝗶𝗿𝗲𝗰𝘁𝗹𝘆 𝘁𝗼 𝘆𝗼𝘂𝗿 𝗣𝗠!**")
