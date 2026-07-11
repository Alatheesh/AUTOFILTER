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

INDEXER_STATE = {}

def sanitize_title(title: str) -> str:
    if not title: return "Unknown File"
    clean_title = re.sub(JUNK_REGEX, "", title)
    clean_title = re.sub(SANITIZING_REGEX, " ", clean_title)
    clean_title = " ".join(clean_title.split())
    return clean_title.strip() if clean_title.strip() else title

def generate_file_hash(media) -> str:
    # 🚀 ULTIMATE FIX FOR FAKE DUPLICATES: 
    # Uses Telegram's absolute unique file ID. Impossible to mismatch.
    hash_payload = str(media.file_unique_id).encode("utf-8")
    return hashlib.sha256(hash_payload).hexdigest()

# ==========================================
# 🚀 PASSIVE AUTO-INDEXER
# ==========================================
@Client.on_message(filters.document | filters.video | filters.audio, group=1)
async def auto_indexer(client: Client, message: Message):
    media = message.document or message.video or message.audio
    if not media: return

    raw_title = getattr(media, "file_name", "") or getattr(message, "caption", "") or "Unknown Web File"
    file_size = getattr(media, "file_size", 0)
    crypto_hash = generate_file_hash(media)

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

# ==========================================
# 🛠️ HELPER: TRIGGER INDEXING JOB
# ==========================================
async def trigger_indexing_job(client: Client, message: Message, target_chat, prompt_msg_id=None, known_msg_id=None):
    extracted_msg_id = None
    target_chat_str = str(target_chat).strip()
    
    # 1. 🚀 Parse Links and extract precise message IDs if provided
    if "t.me/" in target_chat_str:
        clean_link = target_chat_str.replace("https://", "").replace("http://", "")
        parts = clean_link.split("t.me/")[1].split("?")[0].split("/")
        if parts[0] == "c" and len(parts) > 1:
            target_chat_str = f"-100{parts[1]}"
            if len(parts) > 2 and parts[2].isdigit():
                extracted_msg_id = int(parts[2])
        else:
            target_chat_str = f"@{parts[0]}"
            if len(parts) > 1 and parts[1].isdigit():
                extracted_msg_id = int(parts[1])
    elif not target_chat_str.startswith("@") and not target_chat_str.replace("-", "").isdigit():
        target_chat_str = f"@{target_chat_str}"

    if extracted_msg_id and not known_msg_id:
        known_msg_id = extracted_msg_id

    # 2. 🚀 Convert to Integer for Pyrogram stability
    try: target_chat_input = int(target_chat_str)
    except ValueError: target_chat_input = target_chat_str

    if prompt_msg_id: 
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, "📡 **Connecting to Chat & Analyzing files...**")
        except Exception: pass

    try:
        chat_info = await client.get_chat(target_chat_input)
        target_chat_name = chat_info.title or str(target_chat_input)
        target_chat_id = chat_info.id # Force exact Integer ID
    except Exception as e:
        err = f"❌ **Error Accessing Chat:** `{target_chat_str}`\nMake sure the bot is an Admin!\n`{e}`"
        if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        else: await message.reply_text(err)
        return

    actual_last_msg_id = None
    
    # 3. 🚀 Direct API fetch for the absolute newest message (No more guessing)
    try:
        async for m in client.get_chat_history(target_chat_id, limit=1):
            actual_last_msg_id = m.id
            break
    except Exception as e:
        logger.warning(f"History fetch failed: {e}")
        
    # 4. 🚀 Trust the Link over the Forward if history is blocked
    if not actual_last_msg_id:
        if extracted_msg_id:
            actual_last_msg_id = extracted_msg_id # Always trust the direct link ID
        elif known_msg_id:
            actual_last_msg_id = known_msg_id 
        else:
            err = (
                f"❌ **Telegram Security Block!**\n"
                f"I cannot see the total files in `{target_chat_name}`.\n\n"
                f"**Fix:** Run `/index` and paste the direct link to the absolute newest post in the channel (e.g. `https://t.me/c/1844188498/107602`)"
            )
            if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
            else: await message.reply_text(err)
            return

    # 5. 🚀 Queue the job
    success = await db.add_index_job(target_chat_id, target_chat_name, actual_last_msg_id)

    if success:
        msg_text = f"✅ **Job Queued Successfully!**\n\nChannel: `{target_chat_name}`\nTargeting Exactly: **{actual_last_msg_id}** messages.\n\nThe bot will safely process this in the background."
    else:
        msg_text = f"⚠️ **Job Started / Reset!**\n\nThe bot is processing `{target_chat_name}`."
        
    if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, msg_text)
    else: await message.reply_text(msg_text)


# ==========================================
# 🛑 STOP ACTIVE INDEXER COMMAND
# ==========================================
@Client.on_message(filters.command("cancel_index") & filters.user(Config.ADMINS))
async def stop_active_index(client: Client, message: Message):
    job = await db.get_active_job()
    if not job:
        return await message.reply_text("⚠️ **No active indexing jobs to cancel.**")
    
    job_id = job["_id"]
    chat_name = job["chat_name"]
    await db.update_job(job_id, {"status": "completed"})
    await message.reply_text(f"🛑 **Indexing Cancelled!**\n\nThe bot has stopped processing `{chat_name}`.")


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command(["index", "batch"]) & filters.user(Config.ADMINS))
async def mass_indexer_command(client: Client, message: Message):
    if message.reply_to_message:
        reply = message.reply_to_message
        target_chat = None
        last_msg_id = None
        if getattr(reply, "forward_origin", None):
            if getattr(reply.forward_origin, "chat", None):
                target_chat = reply.forward_origin.chat.id
                last_msg_id = getattr(reply.forward_origin, "message_id", 0)
            
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
        "3️⃣ **Type** the Link (e.g., `https://t.me/c/1844188498/107602`).\n\n"
        "*(Or click Cancel to abort)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_index_flow")]])
    )
    
    INDEXER_STATE[message.from_user.id] = {"message_id": prompt.id, "timestamp": time.time()}
    raise StopPropagation


# ==========================================
# 🧠 THE CLEAN UI LISTENER
# ==========================================
@Client.on_message(filters.private & filters.user(Config.ADMINS), group=-6)
async def interactive_indexer_listener(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in INDEXER_STATE: raise ContinuePropagation

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
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, "⚠️ **Session Expired.**")
        except Exception: pass
        raise StopPropagation 

    del INDEXER_STATE[user_id]
    try: await message.delete() 
    except Exception: pass
    
    target_chat = None
    known_msg_id = None
    
    if getattr(message, "forward_origin", None):
        if getattr(message.forward_origin, "chat", None):
            target_chat = message.forward_origin.chat.id
            known_msg_id = getattr(message.forward_origin, "message_id", 0)
    elif message.text:
        target_chat = message.text.strip()
    else:
        err = "❌ Invalid input. Please forward a file or send a link."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        except Exception: await message.reply_text(err)
        raise StopPropagation
    
    await trigger_indexing_job(client, message, target_chat, prompt_msg_id, known_msg_id)
    raise StopPropagation

@Client.on_callback_query(filters.regex("^cancel_index_flow$"))
async def cancel_index_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in INDEXER_STATE: del INDEXER_STATE[user_id]
    await callback.message.edit_text("❌ **Operation Cancelled.**")
    await callback.answer("Cancelled", show_alert=False)

# ==========================================
# ⚙️ BACKGROUND QUEUE WORKER
# ==========================================
async def process_indexing_queue(client: Client):
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
                    logger.error(f"❌ Cannot resolve {chat_name}. Retrying in 60s... ({e})")
                    await asyncio.sleep(60)
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
                if not msg or getattr(msg, "empty", False): continue

                media = msg.document or msg.video or msg.audio
                if not media: continue

                raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
                file_size = getattr(media, "file_size", 0)
                
                # 🚀 Apply the new perfect hashing system
                crypto_hash = generate_file_hash(media)

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
                "scanned": job["scanned"] + scanned,
                "saved": job["saved"] + saved,
                "duplicates": job["duplicates"] + dupes
            })

            logger.info(f"🔄 Indexing: {chat_name} - Saved {saved} | Dupes {dupes}")
            await asyncio.sleep(3.0)

        except Exception as e:
            logger.error(f"Indexer Queue error: {e}")
            await asyncio.sleep(10)
