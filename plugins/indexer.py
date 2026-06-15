import re
import hashlib
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
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

    # Uses the fixed duplicate checker
    if await db.check_exists(crypto_hash): return

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
    if len(message.command) < 2:
        return await message.reply_text(
            "❌ **Usage:** `/index <chat_username_or_id>`\n"
            "Example: `/index @movies_channel`"
        )

    target_chat = message.command[1]
    
    try:
        target_chat = int(target_chat)
    except ValueError:
        pass

    progress_msg = await message.reply_text(f"⏳ **Starting Smart Indexer on `{target_chat}`...**")
    
    total_found = 0
    total_duplicates = 0
    scanned_count = 0
    non_media_count = 0
    consecutive_duplicates = 0

    try:
        async for msg in client.get_chat_history(target_chat):
            scanned_count += 1
            
            media = msg.document or msg.video or msg.audio
            if not media:
                non_media_count += 1
            else:
                raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
                file_size = getattr(media, "file_size", 0)
                crypto_hash = generate_file_hash(raw_title, file_size)

                # Uses the fixed duplicate checker
                if await db.check_exists(crypto_hash):
                    total_duplicates += 1
                    consecutive_duplicates += 1
                else:
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

            if consecutive_duplicates >= 400:
                await progress_msg.edit_text("⏭️ **Smart Auto-Skip Triggered!**\nDetected 400 duplicates in a row. Stopping early to save resources.")
                break

            if scanned_count % 100 == 0:
                try:
                    await progress_msg.edit_text(
                        f"🔄 **Smart Indexing in Progress...**\n"
                        f"• Target: `{target_chat}`\n"
                        f"• Scanned: `{scanned_count}`\n\n"
                        f"📂 **Breakdown:**\n"
                        f"• New Media Saved: `{total_found}`\n"
                        f"• Already Indexed: `{total_duplicates}`\n"
                        f"• Text/Non-Media: `{non_media_count}`"
                    )
                except Exception:
                    pass 
                    
            await asyncio.sleep(0.05)

        await progress_msg.edit_text(
            f"✅ **Mass Index Completed!**\n\n"
            f"• Target: `{target_chat}`\n"
            f"• Total Scanned: `{scanned_count}`\n"
            f"• Saved Media: `{total_found}`\n"
            f"• Skipped Duplicates: `{total_duplicates}`\n"
            f"• Skipped Text: `{non_media_count}`"
        )

    except Exception as e:
        logger.error(f"Error during mass indexing: {e}")
        await progress_msg.edit_text(f"❌ **Failed:** `{str(e)}`\n\n*(Note: Ensure the bot is an Admin in the target channel!)*")
