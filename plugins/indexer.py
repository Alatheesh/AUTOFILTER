import re
import hashlib
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# Sanitization regexes to strip junk links, telegram user mentions, websites, and excessive specials
SANITIZING_REGEX = r"[_+\[\]\(\)\{\}\-.]"
JUNK_REGEX = r"(?i)(@[\w_]+|t\.me/[\w_]+|www\.[^\s]+|https?://[^\s]+)"

def sanitize_title(title: str) -> str:
    if not title:
        return "Unknown File"
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
    offset = 0

    # ==========================================
    # ---> THE V2 KEY EXTRACTOR (REPLY TRICK) <---
    # ==========================================
    if message.reply_to_message:
        reply = message.reply_to_message
        
        # Pyrogram V2.2+ Method
        if getattr(reply, "forward_origin", None) and getattr(reply.forward_origin, "chat", None):
            target_chat = reply.forward_origin.chat.id
            
        # Old Pyrogram Method (Fallback)
        elif getattr(reply, "forward_from_chat", None):
            target_chat = reply.forward_from_chat.id

        if len(message.command) > 1:
            try: offset = int(message.command[1])
            except ValueError: pass

    # If they typed the ID manually
    elif len(message.command) > 1:
        try: target_chat = int(message.command[1])
        except ValueError: target_chat = message.command[1]

    if not target_chat:
        return await message.reply_text(
            "❌ **Usage:**\n"
            "Forward **ONE** file from your private channel, reply to it, and type `/index`"
        )

    progress_msg = await message.reply_text(f"⏳ **Unlocking Channel...**\nReading secret key for: `{target_chat}`")

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat = chat_info.id 
    except Exception as e:
        return await progress_msg.edit_text(f"❌ **Error Accessing Chat:**\n`{e}`\n\nMake sure I am an Admin in the channel, and you replied to a forwarded message!")

    await progress_msg.edit_text(f"⏳ **Starting index sweep on `{chat_info.title or target_chat}`...**")
    
    total_found = 0
    total_duplicates = 0

    try:
        async for msg in client.get_chat_history(target_chat, offset=offset):
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

            if total_found % 50 == 0:
                await progress_msg.edit_text(
                    f"🔄 **Index Progress Updated:**\n"
                    f"• Target: `{chat_info.title or target_chat}`\n"
                    f"• Indexed: `{total_found}`\n"
                    f"• Duplicates skipped: `{total_duplicates}`"
                )

        await progress_msg.edit_text(
            f"✅ **Mass Index Completed Successfully!**\n\n"
            f"• Scraped Source: `{chat_info.title or target_chat}`\n"
            f"• Indexed Files: `{total_found}`\n"
            f"• Duplicates Skipped: `{total_duplicates}`"
        )

    except Exception as e:
        logger.error(f"Error during mass indexing command: {e}")
        await progress_msg.edit_text(f"❌ **Failed to Index Chat:**\n`{str(e)}`")
