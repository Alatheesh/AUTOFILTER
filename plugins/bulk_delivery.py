import asyncio
import time
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config
from plugins.search import BULK_CACHE

# 🚀 THE FIX: Import the exact same working delivery function that single-files use!
from plugins.monetization import execute_file_delivery

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
                    async with session.get(f"https://api.npoint.io/{payload}") as resp:
                        if resp.status == 200:
                            selected_indices = await resp.json()
                        else:
                            return await status_msg.edit_text("❌ **Error:** Cloud fetch failed.")
                await status_msg.delete()
            except Exception:
                return await status_msg.edit_text("❌ **Error:** Network error contacting cloud.")

        selected_files = []
        for i in selected_indices:
            if 0 <= i < len(cached_files):
                selected_files.append(cached_files[i])
                
        if not selected_files: return await message.reply_text("⚠️ No valid files were selected.")
        
        status_msg = await message.reply_text(f"📦 **Processing {len(selected_files)} files...**\nSending them securely to your PM.")
        
        successful = 0
        
        # 🚀 THE FIX: Use execute_file_delivery so Auto-Delete ghost mode is handled perfectly.
        for f_data in selected_files:
            if f_data:
                try:
                    await execute_file_delivery(client, user_id, f_data.get("file_id"))
                    successful += 1
                except Exception as e:
                    logger.error(f"Bulk send error: {e}")
                
                await asyncio.sleep(0.5) 
                
        await status_msg.edit_text(f"✅ **Successfully delivered {successful} files directly to your PM!**")
