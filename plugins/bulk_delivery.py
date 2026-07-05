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
        
        if cmd.startswith("bapp_"):
            short_id = cmd.split("_")[1]
            if short_id not in BULK_CACHE:
                return await message.reply_text("⏳ **Session Expired!**\nPlease search for the movie again in the group.")
            
            web_app_url = BULK_CACHE[short_id][2]
            
            settings = await db.get_settings()
            del_enabled = settings.get("filter_delete_enabled", False)
            del_time = settings.get("filter_delete_time", 5)

            msg_text = "📱 **Your Multi-Select App is Ready!**\nClick the button below to open it and choose your files."
            if del_enabled:
                msg_text += f"\n\n⏳ *Note: This message will automatically delete in {del_time} minutes.*"

            app_msg = await message.reply_text(
                msg_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Launch Web App", web_app=WebAppInfo(url=web_app_url))]])
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
                    buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
                return await message.reply_text("🛑 **Lock Warning:**\nYou must join our official channels before downloading bulk files.", reply_markup=InlineKeyboardMarkup(buttons))

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
                        "🔒 **Verification Required for Bulk Downloads**\n\n"
                        "To keep this bot alive, please verify your access. This will grant you **24 Hours of Unlimited Downloads!**\n\n"
                        f"👉 [Click Here to Verify]({short_link})\n\n"
                        "*(Once verified, just open your minimized Web App and click Send again!)*\n\n"
                        "➖➖➖➖➖➖➖➖➖➖\n"
                        "🛠 **Admin Note (If links are broken):**\n"
                        "Use `/setshort <API_KEY> <URL_TEMPLATE>` to test and fix your configuration!"
                    )
                    
                    if del_enabled: v_req_text += f"\n\n⏳ *Note: This message will automatically delete in {del_time} minutes.*"

                    req_msg = await message.reply_text(
                        v_req_text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Verify Access", url=short_link)]])
                    )

                    if del_enabled:
                        try:
                            from plugins.advanced import trigger_ghost_self_destruct
                            trigger_ghost_self_destruct(client, user_id, req_msg.id, del_time * 60)
                        except Exception: pass
                    return

            parts = cmd.split("_")
            if len(parts) < 3: return await message.reply_text("❌ **Error:** Invalid bulk request format.")
                
            req_type = parts[0]  
            short_id = parts[1]
            payload = parts[2]
            
            if short_id not in BULK_CACHE:
                return await message.reply_text("⏳ **Session Expired!**\nYour search result has expired to save memory. Please search for the movie again in the group.")
                
            cached_time, cached_files, _ = BULK_CACHE[short_id]
            selected_indices = []

            if req_type == "blks":
                try: selected_indices = [int(x) for x in payload.split("-") if x.isdigit()]
                except Exception: return await message.reply_text("❌ **Error:** Failed to read your file selections.")
            
            elif req_type == "blkc":
                status_msg = await message.reply_text("☁️ **Fetching your massive selection from the secure cloud...**")
                try:
                    async with aiohttp.ClientSession() as session:
                        if payload.startswith("np_"):
                            np_id = payload.replace("np_", "")
                            async with session.get(f"https://api.npoint.io/{np_id}") as resp:
                                if resp.status == 200:
                                    text_data = await resp.text()
                                    selected_indices = json.loads(text_data)
                                else:
                                    return await status_msg.edit_text(f"❌ **Error:** Npoint fetch failed (Code: {resp.status}).")
                                    
                        elif payload.startswith("dp_"):
                            dp_id = payload.replace("dp_", "")
                            async with session.get(f"https://dpaste.com/{dp_id}.txt") as resp:
                                if resp.status == 200:
                                    text_data = await resp.text()
                                    selected_indices = json.loads(text_data)
                                else:
                                    return await status_msg.edit_text(f"❌ **Error:** Dpaste fetch failed (Code: {resp.status}).")
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
                                                f"❌ **Error:** Cloud fetch failed.\n\n"
                                                f"🛠 **Debug Info:** Npoint `[{resp.status}]`, Dpaste `[{resp2.status}]`\n"
                                                f"**Received ID:** `{payload}`"
                                            )
                    await status_msg.delete()
                    
                except Exception as e:
                    logger.error(f"Bulk Cloud Fetch Error: {e}")
                    return await status_msg.edit_text(f"❌ **Error:** Network error contacting cloud. Details: {e}")

            selected_files = []
            for i in selected_indices:
                if 0 <= i < len(cached_files):
                    selected_files.append(cached_files[i])
                    
            if not selected_files: return await message.reply_text("⚠️ No valid files were selected.")
            
            # 🛑 VIP BACKEND SECURITY CHECK (Fixed to properly read the 50-file limit!)
            try:
                from plugins.vip_system import get_all_plans, FREE_USER_LIMITS
                active_plan = await db.get_active_vip_plan(user_id)
                plans = await get_all_plans()
                user_limits = plans.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan and active_plan in plans else FREE_USER_LIMITS
                bulk_limit = user_limits.get("bulk_select_limit", 10)
            except Exception:
                # Fallback limit just in case
                bulk_limit = 10 
                
            if len(selected_files) > bulk_limit:
                return await message.reply_text(
                    f"🛑 **Security Lock:** You requested **{len(selected_files)}** files, but your current tier is limited to **{bulk_limit}** files per batch.\n\n"
                    f"_Please select fewer files or upgrade to a VIP plan to unlock larger batch downloads!_"
                )
            
            status_msg = await message.reply_text(f"📦 **Processing {len(selected_files)} files...**\nSending them securely to your PM.")
            
            successful = 0
            sent_message_ids = []
            
            # 📝 FETCH CUSTOM CAPTION ONCE FOR THE BATCH
            raw_caption = await db.get_custom_caption(None) # PM delivery falls back to global/default
            
            # 🚀 THE NEW DYNAMIC SAFETY LOOP
            for f_data in selected_files:
                if f_data:
                    # 📝 Format placeholders for this specific file
                    f_name = f_data.get("title", "Unknown File")
                    f_size = format_size(f_data.get("size", 0))
                    mention = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
                    
                    final_caption = raw_caption.replace("{file_name}", f_name).replace("{size}", f_size).replace("{mention}", mention)
                    
                    try:
                        sent_file = await client.send_cached_media(
                            chat_id=user_id, 
                            file_id=f_data.get("file_id"), 
                            caption=final_caption
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
                                caption=final_caption
                            )
                            sent_message_ids.append(sent_file.id)
                            successful += 1
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass # If it fails again, skip the file and move on
                            
                    except UserIsBlocked:
                        logger.warning(f"User {user_id} blocked the bot during massive bulk delivery.")
                        await status_msg.edit_text("❌ **Delivery Stopped:** You blocked the bot!")
                        return # Immediately abort the entire delivery process to save API calls
                        
                    except Exception as e:
                        logger.error(f"Bulk send error: {e}")
                        await asyncio.sleep(0.5)
                    
            await status_msg.delete()
            
            if settings.get("file_delete_enabled", False):
                del_time = settings.get("file_delete_time", 10)
                summary_msg = await message.reply_text(
                    f"✅ **Successfully delivered {successful} files!**\n\n"
                    f"⏳ **Caution:** All {successful} files will be automatically deleted in **{del_time} minutes** to protect our servers. Please forward them to your Saved Messages!"
                )
                try:
                    from plugins.advanced import trigger_ghost_self_destruct
                    for m_id in sent_message_ids:
                        trigger_ghost_self_destruct(client, user_id, m_id, del_time * 60)
                    trigger_ghost_self_destruct(client, user_id, summary_msg.id, del_time * 60)
                except Exception as e:
                    logger.error(f"Bulk Ghost Destruct Error: {e}")
            else:
                await message.reply_text(f"✅ **Successfully delivered {successful} files directly to your PM!**")
