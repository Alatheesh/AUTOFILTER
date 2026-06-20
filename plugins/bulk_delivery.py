import asyncio
import time
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config
from plugins.search import BULK_CACHE

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
    if len(message.command) > 1 and message.command[1].startswith("blk_"):
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
            
        short_id, hex_mask = parts[1], parts[2]
        
        if short_id not in BULK_CACHE:
            return await message.reply_text("⏳ **Session Expired!**\nYour search result has expired to save memory. Please search for the movie again in the group.")
            
        cached_time, cached_files = BULK_CACHE[short_id]
        
        # Decode the Hexadecimal Bitmask
        try: mask = int(hex_mask, 16)
        except ValueError: return await message.reply_text("❌ **Error:** Invalid file selection mask.")
            
        selected_files = []
        for i, f_data in enumerate(cached_files):
            if (mask & (1 << i)):
                selected_files.append(f_data)
                
        if not selected_files: return await message.reply_text("⚠️ No valid files were selected.")
        
        status_msg = await message.reply_text(f"📦 **Processing {len(selected_files)} files...**\nSending them securely to your PM.")
        
        successful = 0
        sent_message_ids = []
        settings = await db.get_settings()
        
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
                
        # 🚀 NEW: SINGLE DELETION SUMMARY CAUTION
        await status_msg.delete()
        if settings.get("file_delete_enabled", False):
            del_time = settings.get("file_delete_time", 10)
            summary_msg = await message.reply_text(
                f"✅ **Successfully delivered {successful} files!**\n\n"
                f"⏳ **Caution:** All {successful} files will be automatically deleted in **{del_time} minutes** to protect our servers. Please forward them to your Saved Messages!"
            )
            
            try:
                from plugins.advanced import trigger_ghost_self_destruct
                # Destruct all files
                for m_id in sent_message_ids:
                    trigger_ghost_self_destruct(client, user_id, m_id, del_time * 60)
                # Destruct the summary message too
                trigger_ghost_self_destruct(client, user_id, summary_msg.id, del_time * 60)
            except Exception as e:
                logger.error(f"Ghost destruct error in bulk: {e}")
        else:
            await message.reply_text(f"✅ **Successfully delivered {successful} files directly to you!**")
