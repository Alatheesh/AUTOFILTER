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

    raw_title = getattr(media, "file_name", "") or getattr(message, "caption", "") or "Unknown Web File"
    file_size = getattr(media, "file_size", 0)
    crypto_hash = generate_file_hash(raw_title, file_size)

    if await db.search_files(crypto_hash, skip=0, limit=1, exact=True): return

    file_data = {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "crypto_hash": crypto_hash,
        "title": sanitize_title(raw_title),
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

    if message.reply_to_message:
        reply = message.reply_to_message
        if getattr(reply, "forward_origin", None) and getattr(reply.forward_origin, "chat", None):
            target_chat = reply.forward_origin.chat.id
            last_msg_id = getattr(reply.forward_origin, "message_id", 0)
        elif getattr(reply, "forward_from_chat", None):
            target_chat = reply.forward_from_chat.id
            last_msg_id = getattr(reply, "forward_from_message_id", 0)

    if not target_chat or not last_msg_id:
        return await message.reply_text("❌ **Usage:** Forward the **NEWEST** file from your channel, reply to it, and type `/index`")

    progress_msg = await message.reply_text("⏳ **Initializing Smart Indexer...**")

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat = chat_info.id 
    except Exception as e:
        return await progress_msg.edit_text(f"❌ **Error Accessing Chat:**\n`{e}`")

    total_found = 0
    total_duplicates = 0
    scanned_count = 0
    non_media_count = 0
    consecutive_duplicates = 0  # To track when to Auto-Skip

    try:
        for i in range(last_msg_id, 0, -200):
            start_id = max(1, i - 199)
            batch_ids = list(range(start_id, i + 1))
            
            messages = await client.get_messages(target_chat, message_ids=batch_ids)
            
            for msg in messages:
                scanned_count += 1
                if msg.empty: 
                    non_media_count += 1
                    continue
                
                media = msg.document or msg.video or msg.audio
                if not media: 
                    non_media_count += 1
                    continue

                raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
                file_size = getattr(media, "file_size", 0)
                crypto_hash = generate_file_hash(raw_title, file_size)

                existing = await db.search_files(crypto_hash, skip=0, limit=1, exact=True)
                if existing:
                    total_duplicates += 1
                    consecutive_duplicates += 1
                    continue

                # We found a new file! Reset duplicate tracker.
                consecutive_duplicates = 0
                file_data = {
                    "file_id": media.file_id,
                    "file_unique_id": media.file_unique_id,
                    "crypto_hash": crypto_hash,
                    "title": sanitize_title(raw_title),
                    "raw_title": raw_title,
                    "size": file_size,
                    "message_id": msg.id,
                    "chat_id": msg.chat.id
                }
                await db.insert_file(file_data)
                total_found += 1

            # SMART AUTO-SKIP: If we hit 400 duplicates in a row, we caught up to the old index.
            if consecutive_duplicates >= 400:
                await progress_msg.edit_text(f"⏭️ **Smart Auto-Skip Triggered!**\nDetected 400 duplicates in a row. Skipping the rest of the channel to save time!")
                break

            messages_left = max(0, last_msg_id - scanned_count)

            if scanned_count % 200 == 0:
                await progress_msg.edit_text(
                    f"🔄 **Smart Indexing in Progress...**\n"
                    f"• Target: `{chat_info.title or target_chat}`\n"
                    f"• Scanned: `{scanned_count}` | Left: `{messages_left}`\n\n"
                    f"📂 **Breakdown:**\n"
                    f"• New Media Saved: `{total_found}`\n"
                    f"• Already Indexed: `{total_duplicates}`\n"
                    f"• Text/Non-Media: `{non_media_count}`"
                )
            
            # ANTI-FLOOD SLEEP: Rest for 2.5 seconds between every batch of 200 messages
            await asyncio.sleep(2.5)

        await progress_msg.edit_text(
            f"✅ **Mass Index Completed Successfully!**\n\n"
            f"• Source: `{chat_info.title or target_chat}`\n"
            f"• Scanned Total: `{scanned_count}`\n"
            f"• Saved Media: `{total_found}`\n"
            f"• Duplicates Ignored: `{total_duplicates}`\n"
            f"• Text/Spam Ignored: `{non_media_count}`"
        )

    except Exception as e:
        logger.error(f"Error during mass indexing: {e}")
        await progress_msg.edit_text(f"❌ **Failed:** `{str(e)}`")
