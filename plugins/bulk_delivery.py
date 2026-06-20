import asyncio
import time
import logging
import aiohttp
import json
import string
import random
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config
from plugins.search import BULK_CACHE

# 🚀 Import the Shortener Logic from the Monetization file!
from plugins.monetization import VERIFICATION_TOKENS, get_shortlink

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
    if len(message.command) > 1 and message.command[1].startswith("blk"):
        cmd = message.command[1]
        user_id = message.from_user.id
        
        # 1. Check Force Sub Status
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

        # 🚀 THE FIX: Check Shortener Verification before allowing any bulk downloads!
        settings = await db.get_settings()
        if settings.get("shortener_enabled", False):
            u_sett = await db.get_user_settings(user_id)
            pass_time = u_sett.get("shortener_pass", 0)
            
            if time.time() > pass_time:
                token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                
                # Store token. We use 'None' for pending_file because they will just click Send in the Web App again!
                VERIFICATION_TOKENS[token] = {"user_id": user_id, "pending_file": None}
                
                bot_me = await client.get_me()
                verify_link = f"https://t.me/{bot_me.username}?start=verify_{token}"
                
                api = settings.get("shortener_api", "")
                site = settings.get("shortener_url", "https://gplinks.in/api")
                
                if api:
                    short_link = await get_shortlink(verify_link, api, site)
                else:
                    short_link = verify_link
                    
                return await message.reply_text(
                    "🔒 **Verification Required for Bulk Downloads**\n\n"
                    "To keep this bot alive, please verify your access. This will grant you **24 Hours of Unlimited Downloads!**\n\n"
                    f"👉 [Click Here to Verify]({short_link})\n\n"
                    "*(Once verified, just open your minimized Web App and click Send again!)*",
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Verify Access", url=short_link)]])
                )

        # 2. Process the Bulk Request
        parts = cmd.split("_")
        if len(parts) < 3:
            return await message.reply_text("❌ **Error:** Invalid bulk request format.")
            
        req_type = parts[0]  
        short_id = parts[1]
        payload = parts[2]
        
        if short_id not in BULK_CACHE:
            return await message.reply_text("⏳ **Session Expired!**\nYour search result has expired to save memory. Please search for the movie again in the group.")
            
        cached_time, cached_files = BULK_CACHE[short_id]
        selected_indices = []

        if req_type == "blks":
            try:
                selected_indices = [int(x) for x in payload.split("-") if x.isdigit()]
            except Exception:
                return await message.reply_text("❌ **Error:** Failed to read your file selections.")
        
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
                                return await status_msg.edit_text("❌ **Error:** Npoint fetch failed.")
                    elif payload.startswith("dp_"):
                        dp_id = payload.replace("dp_", "")
                        async with session.get(f"https://dpaste.com/{dp_id}.txt") as resp:
                            if resp.status == 200:
                                text_data = await resp.text()
                                selected_indices = json.loads(text_data)
                            else:
                                return await status_msg.edit_text("❌ **Error:** Dpaste fetch failed.")
                    else:
                        async with session.get(f"https://api.npoint.io/{payload}") as resp:
                            if resp.status == 200:
                                text_data = await resp.text()
                                selected_indices = json.loads(text_data)
                            else:
                                return await status_msg.edit_text("❌ **Error:** Cloud fetch failed.")
                await status_msg.delete()
            except Exception as e:
                logger.error(f"Bulk Cloud Fetch Error: {e}")
                return await status_msg.edit_text("❌ **Error:** Network error contacting cloud.")

        selected_files = []
        for i in selected_indices:
            if 0 <= i < len(cached_files):
                selected_files.append(cached_files[i])
                
        if not selected_files: return await message.reply_text("⚠️ No valid files were selected.")
        
        status_msg = await message.reply_text(f"📦 **Processing {len(selected_files)} files...**\nSending them securely to your PM.")
        
        successful = 0
        sent_message_ids = []
        
        for f_data in selected_files:
            if f_data:
                try:
                    sent_file = await client.send_cached_media(
                        chat_id=user_id, 
                        file_id=f_data.get("file_id"), 
                        caption="✨ **Here is your requested file.**\n\n🛡 *Provided securely by the Auto-Filter System.*"
                    )
                    sent_message_ids.append(sent_file.id)
                    successful += 1
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
