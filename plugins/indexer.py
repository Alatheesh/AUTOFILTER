import re
import time
import hashlib
import logging
import asyncio
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, PeerIdInvalid, ChannelInvalid
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

SANITIZING_REGEX = r"[_+\[\]\(\)\{\}\-.]"
JUNK_REGEX = r"(?i)(@[\w_]+|t\.me/[\w_]+|www\.[^\s]+|https?://[^\s]+)"

# 🧠 State Machine for Clean Interactive Indexing
INDEXER_STATE = {}

def sanitize_title(title: str) -> str:
    if not title: return "Unknown File"
    clean_title = re.sub(JUNK_REGEX, "", title)
    clean_title = re.sub(SANITIZING_REGEX, " ", clean_title)
    clean_title = " ".join(clean_title.split())
    return clean_title.strip() if clean_title.strip() else title

def generate_file_hash(file_name: str, file_size: int) -> str:
    hash_payload = f"{file_name}_{file_size}".encode("utf-8")
    return hashlib.sha256(hash_payload).hexdigest()

def is_valid_movie(media) -> bool:
    """Strictly checks if a document is actually a movie file."""
    mime = getattr(media, "mime_type", "").lower()
    name = getattr(media, "file_name", "").lower()
    if mime.startswith("video/"): return True
    if name.endswith((".mkv", ".mp4", ".avi", ".webm", ".flv", ".mov")): return True
    return False

# ==========================================
# 🚀 PASSIVE AUTO-INDEXER (Set-It-and-Forget-It)
# ==========================================
@Client.on_message((filters.document | filters.video), group=1)
async def auto_indexer(client: Client, message: Message):
    media = message.video or message.document
    if not media: return

    # 🚨 STRICT FILTER: Ignore anything that isn't a movie/video
    if message.document and not is_valid_movie(media): return

    raw_title = getattr(media, "file_name", "") or getattr(message, "caption", "") or "Unknown Movie File"
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
        "message_id": message.id,
        "chat_id": message.chat.id,
        "language": "pending",
        "subtitle": "pending"
    }
    await db.insert_file(file_data)
    logger.info(f"✅ Auto-Indexed new movie: {raw_title}")

# ==========================================
# 🛠️ HELPER: TRIGGER INDEXING JOB
# ==========================================
async def trigger_indexing_job(client: Client, message: Message, target_chat, prompt_msg_id=None, known_msg_id=None):
    try: target_chat = int(target_chat)
    except ValueError: pass

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat_name = chat_info.title or str(target_chat)
        target_chat_id = chat_info.id
    except Exception as e:
        err = f"❌ **Error Accessing Chat:** Ensure I am an Admin in `{target_chat}`!\n`{e}`"
        if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        else: await message.reply_text(err)
        return

    last_msg_id = known_msg_id
    
    if not last_msg_id:
        try:
            async for m in client.get_chat_history(target_chat_id, limit=1):
                last_msg_id = m.id
                break
        except Exception as e:
            err = f"❌ **Error reading history:** Ensure I have 'Read Messages' rights in `{target_chat_name}`!"
            if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
            else: await message.reply_text(err)
            return

    if not last_msg_id:
        err = "❌ **Error:** That channel appears to be completely empty."
        if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        else: await message.reply_text(err)
        return

    success = await db.add_index_job(target_chat_id, target_chat_name, last_msg_id)

    if success:
        msg_text = f"✅ **Job Queued Successfully!**\n\nChannel: `{target_chat_name}`\nTargeting ~`{last_msg_id}` messages.\n\nThe bot will safely process this in the background."
    else:
        msg_text = f"⚠️ **Job Started / Reset!**\n\nThe bot is processing `{target_chat_name}`."
        
    if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, msg_text)
    else: await message.reply_text(msg_text)


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command(["index", "batch"]) & filters.user(Config.ADMINS))
async def mass_indexer_command(client: Client, message: Message):
    if message.reply_to_message:
        reply = message.reply_to_message
        target_chat = None
        last_msg_id = None
        
        if getattr(reply, "forward_origin", None) and getattr(reply.forward_origin, "chat", None):
            target_chat = reply.forward_origin.chat.id
            last_msg_id = getattr(reply.forward_origin, "message_id", 0)
        elif getattr(reply, "forward_from_chat", None):
            target_chat = reply.forward_from_chat.id
            last_msg_id = getattr(reply, "forward_from_message_id", 0)
            
        if target_chat and last_msg_id:
            await trigger_indexing_job(client, message, target_chat, known_msg_id=last_msg_id)
            raise StopPropagation
            
    if len(message.command) > 1:
        target_chat = message.command[1].strip()
        await trigger_indexing_job(client, message, target_chat)
        raise StopPropagation

    prompt = await message.reply_text(
        "📦 **Mass Indexing Wizard**\n\n"
        "How would you like to target the channel?\n"
        "1️⃣ **Forward** any file from the channel here.\n"
        "2️⃣ **Type** the Channel ID (e.g., `-10012345678`).\n"
        "3️⃣ **Type** the Public Username (e.g., `@MyChannel`).\n\n"
        "*(Or click Cancel to abort)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_index_flow")]])
    )
    
    INDEXER_STATE[message.from_user.id] = {
        "message_id": prompt.id,
        "timestamp": time.time()
    }
    raise StopPropagation


# ==========================================
# 🧠 THE CLEAN UI LISTENER
# ==========================================
@Client.on_message(filters.private & filters.user(Config.ADMINS), group=-6)
async def interactive_indexer_listener(client: Client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in INDEXER_STATE:
        raise ContinuePropagation

    if message.text and message.text.startswith("/"):
        del INDEXER_STATE[user_id]
        raise ContinuePropagation

    state = INDEXER_STATE[user_id]
    prompt_msg_id = state["message_id"]
    timestamp = state["timestamp"]

    if time.time() - timestamp > 172800:
        del INDEXER_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please run `/index` again."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation 

    del INDEXER_STATE[user_id]
    try: await message.delete() 
    except Exception: pass
    
    target_chat = None
    known_msg_id = None
    
    if getattr(message, "forward_origin", None) and getattr(message.forward_origin, "chat", None):
        target_chat = message.forward_origin.chat.id
        known_msg_id = getattr(message.forward_origin, "message_id", 0)
    elif getattr(message, "forward_from_chat", None):
        target_chat = message.forward_from_chat.id
        known_msg_id = getattr(message, "forward_from_message_id", 0)
    elif message.text:
        target_chat = message.text.strip()
    else:
        err = "❌ Invalid input. Please forward a file or send text."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        except Exception: await message.reply_text(err)
        raise StopPropagation

    try: await client.edit_message_text(message.chat.id, prompt_msg_id, "🔄 **Connecting to chat & calculating files...**")
    except Exception: pass
    
    await trigger_indexing_job(client, message, target_chat, prompt_msg_id, known_msg_id)
    raise StopPropagation


@Client.on_callback_query(filters.regex("^cancel_index_flow$"))
async def cancel_index_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in INDEXER_STATE:
        del INDEXER_STATE[user_id]
    await callback.message.edit_text("❌ **Operation Cancelled.**\n\nYou can start over whenever you're ready.")
    await callback.answer("Cancelled", show_alert=False)


# ==========================================
# ⚙️ BACKGROUND QUEUE WORKER
# ==========================================
async def process_indexing_queue(client: Client):
    """Runs 24/7. Survives crashes. Safely parses queued channels."""
    logger.info("🟢 Safe Indexing Job Queue Started!")

    try:
        if hasattr(db, "db") and "jobs" in await db.db.list_collection_names():
            await db.db.jobs.update_many({"status": "processing"}, {"$set": {"status": "pending"}})
            logger.info("✅ Resumed stuck indexing jobs from previous restart.")
    except Exception:
        pass

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
                await asyncio.sleep(5)
                continue

            start_id = max(1, current_id - 199)
            batch_ids = list(range(start_id, current_id + 1))

            try:
                messages = await client.get_messages(chat_id, message_ids=batch_ids)
            except FloodWait as fw:
                logger.warning(f"⚠️ Indexer Rate Limit! Sleeping {fw.value}s")
                await asyncio.sleep(fw.value)
                continue
            except (PeerIdInvalid, ChannelInvalid): 
                logger.warning(f"⚠️ Telegram memory syncing for {chat_name}. Attempting to resolve peer...")
                try:
                    await client.get_chat(chat_id)
                    await asyncio.sleep(2)
                    continue 
                except Exception as e:
                    logger.error(f"❌ FATAL: Cannot resolve {chat_name}. Aborting job! ({e})")
                    await db.update_job(job_id, {"status": "completed"})
                    continue
            except Exception as e:
                logger.error(f"Failed to fetch batch for {chat_name}: {e}")
                await db.update_job(job_id, {"current_id": start_id - 1})
                await asyncio.sleep(5)
                continue

            saved = 0
            dupes = 0
            scanned = 0

            for msg in messages:
                scanned += 1
                if msg.empty: continue

                media = msg.video or msg.document
                if not media: continue
                
                # 🚨 STRICT FILTER: Ignore non-movies in the queue batch too
                if msg.document and not is_valid_movie(media): continue

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
                        "language": "pending",
                        "subtitle": "pending"
                    }
                    await db.insert_file(file_data)
                    saved += 1

            await db.update_job(job_id, {
                "current_id": start_id - 1,
                "scanned": job.get("scanned", 0) + scanned,
                "saved": job.get("saved", 0) + saved,
                "duplicates": job.get("duplicates", 0) + dupes
            })

            logger.info(f"🔄 Queue Indexing: {chat_name} - Saved {saved} new movies.")
            await asyncio.sleep(3.0)

        except Exception as e:
            logger.error(f"Indexer Queue error: {e}")
            await asyncio.sleep(10)
