import re
import hashlib
import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
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

    if await db.check_exists(crypto_hash): return

    file_data = {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "crypto_hash": crypto_hash,
        "title": sanitize_title(raw_title),
        "raw_title": raw_title,
        "size": file_size,
        "message_id": msg.id,
        "chat_id": msg.chat.id,
        "language": "pending",
        "subtitle": "pending" 
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

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat_name = chat_info.title or str(target_chat)
    except Exception as e:
        return await message.reply_text(f"❌ **Error Accessing Chat:** Ensure bot is an Admin there!\n`{e}`")

    success = await db.add_index_job(target_chat, target_chat_name, last_msg_id)
    
    if success:
        await message.reply_text(f"✅ **Job Queued Successfully!**\n\nChannel: `{target_chat_name}`\nThe bot will safely process this in the background to prevent bans and survive restarts.")
    else:
        await message.reply_text(f"⚠️ **Job Already Exists!**\n\nThe bot is already scheduled to process `{target_chat_name}`.")

async def process_indexing_queue(client: Client):
    """Runs 24/7. Survives crashes. Safely parses queued channels."""
    logger.info("🟢 Safe Indexing Job Queue Started!")
    
    while True:
        try:
            job = await db.get_active_job()
            if not job:
                await asyncio.sleep(60) 
                continue
                
            job_id = job["_id"]
            chat_id = job["chat_id"]
            chat_name = job["chat_name"]
            current_id = job["current_id"]
            
            await db.update_job(job_id, {"status": "processing"})
            
            if current_id <= 0:
                await db.update_job(job_id, {"status": "completed"})
                logger.info(f"✅ Indexing completed for {chat_name}")
                continue

            start_id = max(1, current_id - 199)
            batch_ids = list(range(start_id, current_id + 1))
            
            try:
                messages = await client.get_messages(chat_id, message_ids=batch_ids)
            except FloodWait as fw:
                logger.warning(f"⚠️ Indexer Rate Limit! Sleeping {fw.value}s")
                await asyncio.sleep(fw.value)
                continue
            except Exception as e:
                logger.error(f"Failed to fetch batch for {chat_name}: {e}")
                await db.update_job(job_id, {"current_id": start_id - 1})
                continue
            
            saved = 0
            dupes = 0
            scanned = 0
            
            for msg in messages:
                scanned += 1
                if msg.empty: continue
                
                media = msg.document or msg.video or msg.audio
                if not media: continue

                raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
                file_size = getattr(media, "file_size", 0)
                crypto_hash = generate_file_hash(raw_title, file_size)

                if await db.check_exists(crypto_hash):
                    dupes += 1
                else:
                    file_data = {
                        "file_id": media.file_id,
                        "file_unique_id": media.file_unique_id,
                        "crypto_hash": crypto_hash,
                        "title": sanitize_title(raw_title),
                        "raw_title": raw_title,
                        "size": file_size,
                        "message_id": msg.id,
                        "chat_id": msg.chat.id,
                        "language": "pending"
                    }
                    await db.insert_file(file_data)
                    saved += 1
            
            await db.update_job(job_id, {
                "current_id": start_id - 1,
                "scanned": job["scanned"] + scanned,
                "saved": job["saved"] + saved,
                "duplicates": job["duplicates"] + dupes
            })
            
            logger.info(f"🔄 Queue Indexing: {chat_name} - Saved {saved} new files. Surviving.")
            
            await asyncio.sleep(5.0)

        except Exception as e:
            logger.error(f"Indexer Queue error: {e}")
            await asyncio.sleep(10)
