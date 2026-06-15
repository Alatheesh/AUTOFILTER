import re
import hashlib
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

SANITIZING_REGEX = r"[_+\[\]\(\)\{\}\-.]"
JUNK_REGEX = r"(?i)(@[\w_]+|t\.me/[\w_]+|www\.[^\s]+|https?://[^\s]+)"

def sanitize_title(title: str) -> str:
    if not title: return "Unknown File"
    clean_title = re.sub(JUNK_REGEX, "", title)
    clean_title = re.sub(SANITIZING_REGEX, " ", clean_title)
    clean_title = " ".join(clean_title.split())
    return clean_title.strip() if clean_title.strip() else title

def generate_file_hash(file_name: str, file_size: int) -> str:
    hash_payload = f"{file_name}_{file_size}".encode("utf-8")
    return hashlib.sha256(hash_payload).hexdigest()

@Client.on_message(filters.document | filters.video | filters.audio, group=1)
async def auto_indexer(client: Client, message: Message):
    media = message.document or message.video or message.audio
    if not media: return

    file_id = media.file_id
    file_unique_id = media.file_unique_id
    raw_title = getattr(media, "file_name", "") or getattr(message, "caption", "") or "Unknown Web File"
    file_size = getattr(media, "file_size", 0)

    sanitized_title = sanitize_title(raw_title)
    crypto_hash = generate_file_hash(raw_title, file_size)

    existing = await db.search_files(crypto_hash, skip=0, limit=1, exact=True)
    if existing: return

    file_data = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "crypto_hash": crypto_hash,
        "title": sanitized_title,
        "raw_title": raw_title,
        "size": file_size,
        "message_id": message.id,
        "chat_id": message.chat.id
    }
    await db.insert_file(file_data)

@Client.on_message(filters.command(["index", "batch"]) & filters.user(Config.ADMINS))
async def mass_indexer_command(client: Client, message: Message):
    target_chat = None
    last_msg_id = 0

    # 1. Read the hidden data from the forwarded message
    if message.reply_to_message:
        reply = message.reply_to_message
        
        # Pyrogram V2.2+ (Kurigram) Extraction
        if getattr(reply, "forward_origin", None) and getattr(reply.forward_origin, "chat", None):
            target_chat = reply.forward_origin.chat.id
            last_msg_id = getattr(reply.forward_origin, "message_id", 0)
            
        # Fallback
        elif getattr(reply, "forward_from_chat", None):
            target_chat = reply.forward_from_chat.id
            last_msg_id = getattr(reply, "forward_from_message_id", 0)

    if not target_chat or not last_msg_id:
        return await message.reply_text(
            "❌ **Usage:**\n"
            "Forward the **VERY LAST (NEWEST)** file from your channel, reply to it, and type `/index`"
        )

    progress_msg = await message.reply_text(f"⏳ **Bypassing Telegram Restrictions...**\nTargeting Channel: `{target_chat}`\nMax Message ID: `{last_msg_id}`")

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat = chat_info.id 
    except Exception as e:
        return await progress_msg.edit_text(f"❌ **Error Accessing Chat:**\n`{e}`\nEnsure the bot is an Admin!")

    await progress_msg.edit_text(f"🚀 **Starting ID Scan on `{chat_info.title or target_chat}`...**\nScanning `{last_msg_id}` total IDs!")
    
    total_found = 0
    total_duplicates = 0
    scanned_count = 0

    try:
        # 2. The Loophole: Count backwards in chunks of 200 instead of asking for history
        for i in range(last_msg_id, 0, -200):
            start_id = max(1, i - 199)
            batch_ids = list(range(start_id, i + 1))
            
            # Fetch by ID (Bots ARE allowed to do this!)
            messages = await client.get_messages(target_chat, message_ids=batch_ids)
            
            for msg in messages:
                scanned_count += 1
                if msg.empty: continue # Skip deleted messages
                
                media = msg.document or msg.video or msg.audio
                if not media: continue

                raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
                sanitized_title = sanitize_title(raw_title)
                file_size = getattr(media, "file_size", 0)
                crypto_hash = generate_file_hash(raw_title, file_size)

                existing = await db.search_files(crypto_hash, skip=0, limit=1, exact=True)
                if existing:
                    total_duplicates += 1
                    continue

                file_data = {
                    "file_id": media.file_id,
                    "file_unique_id": media.file_unique_id,
                    "crypto_hash": crypto_hash,
                    "title": sanitized_title,
                    "raw_title": raw_title,
                    "size": file_size,
                    "message_id": msg.id,
                    "chat_id": msg.chat.id
                }

                await db.insert_file(file_data)
                total_found += 1

            # Update the screen every 400 messages so Telegram doesn't block the bot
            if scanned_count % 400 == 0:
                await progress_msg.edit_text(
                    f"🔄 **ID Scan Progress:**\n"
                    f"• Target: `{chat_info.title or target_chat}`\n"
                    f"• Scanned: `{scanned_count} / {last_msg_id}`\n"
                    f"• Indexed: `{total_found}`\n"
                    f"• Duplicates skipped: `{total_duplicates}`"
                )

        await progress_msg.edit_text(
            f"✅ **Mass Index Completed Successfully!**\n\n"
            f"• Scraped Source: `{chat_info.title or target_chat}`\n"
            f"• Total Scanned: `{last_msg_id}`\n"
            f"• Saved to MongoDB: `{total_found}`\n"
            f"• Duplicates Skipped: `{total_duplicates}`"
        )

    except Exception as e:
        logger.error(f"Error during mass indexing command: {e}")
        await progress_msg.edit_text(f"❌ **Failed to Index Chat:**\n`{str(e)}`")
