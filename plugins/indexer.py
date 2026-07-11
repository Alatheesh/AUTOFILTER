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

def generate_file_hash(media) -> str:
    # 🚀 FIX: Uses Telegram's absolute unique file ID.
    # Completely eliminates the fake duplicate bug.
    hash_payload = str(media.file_unique_id).encode("utf-8")
    return hashlib.sha256(hash_payload).hexdigest()

# ==========================================
# 🚀 PASSIVE AUTO-INDEXER (Set-It-and-Forget-It)
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
    """Processes the target chat, finds the absolute latest message, and queues the job."""
    
    extracted_msg_id = None
    
    # 🚀 Advanced Link Parser 
    if isinstance(target_chat, str):
        target_chat = target_chat.strip()
        if "t.me/" in target_chat:
            parts = target_chat.split("t.me/")[1].split("?")[0].split("/")
            if parts[0] == "c" and len(parts) > 1:
                target_chat = f"-100{parts[1]}"
                if len(parts) > 2 and parts[2].isdigit():
                    extracted_msg_id = int(parts[2])
            else:
                target_chat = f"@{parts[0]}"
                if len(parts) > 1 and parts[1].isdigit():
                    extracted_msg_id = int(parts[1])
        elif not target_chat.startswith("@") and not target_chat.replace("-", "").isdigit():
            target_chat = f"@{target_chat}"

    if extracted_msg_id and not known_msg_id:
        known_msg_id = extracted_msg_id

    try: target_chat = int(target_chat)
    except ValueError: pass

    try:
        chat_info = await client.get_chat(target_chat)
        target_chat_name = chat_info.title or str(target_chat)
        target_chat_id = f"@{chat_info.username}" if chat_info.username else chat_info.id
            
    except PeerIdInvalid:
        err = (
            f"❌ **Error: Cannot locate chat `{target_chat}` in memory.**\n\n"
            f"**The Fix:**\n"
            f"• If it's a **Public Channel**, please provide its `@username` or link instead of its numeric ID.\n"
            f"• If it's a **Private Channel**, you MUST either add the bot as an admin OR forward a file from it first!"
        )
        if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        else: await message.reply_text(err)
        return
    except Exception as e:
        err = f"❌ **Error Accessing Chat:** `{target_chat}`\nMake sure it is a valid public channel, or that the bot is an admin!\n`{e}`"
        if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
        else: await message.reply_text(err)
        return

    actual_last_msg_id = None
    
    # 🚀 METHOD A: Standard History Request (Works if bot is Admin)
    try:
        async for m in client.get_chat_history(target_chat_id, limit=1):
            actual_last_msg_id = m.id
            break
    except Exception:
        pass 
        
    # 🚀 METHOD B: The "Ascending Radar Probe" (WITH GAP JUMPER)
    if not actual_last_msg_id:
        try:
            if prompt_msg_id: 
                await client.edit_message_text(message.chat.id, prompt_msg_id, "📡 **Bypassing Security... Probing for the newest post...**")
            
            probe_id = known_msg_id if known_msg_id else 1
            last_good_id = probe_id
            
            # 1. Aggressive Jump (+1000) - Tolerates up to 50,000 deleted messages!
            empty_streak = 0
            while True:
                msg = await client.get_messages(target_chat_id, probe_id + 1000)
                if not msg or getattr(msg, "empty", False):
                    empty_streak += 1
                    if empty_streak >= 50: # If we hit 50 empty gaps in a row, it's definitely the end.
                        break
                else:
                    empty_streak = 0
                    last_good_id = probe_id + 1000
                probe_id += 1000
                await asyncio.sleep(0.1) # Safety delay
            
            # Revert to highest confirmed ID to start moderate jumps
            probe_id = last_good_id
                
            # 2. Moderate Jump (+100) - Tolerates up to 2,000 deleted messages
            empty_streak = 0
            while True:
                msg = await client.get_messages(target_chat_id, probe_id + 100)
                if not msg or getattr(msg, "empty", False):
                    empty_streak += 1
                    if empty_streak >= 20:
                        break
                else:
                    empty_streak = 0
                    last_good_id = probe_id + 100
                probe_id += 100
                await asyncio.sleep(0.1)
                
            probe_id = last_good_id

            # 3. Fine Tuning (+10)
            empty_streak = 0
            while True:
                msg = await client.get_messages(target_chat_id, probe_id + 10)
                if not msg or getattr(msg, "empty", False):
                    empty_streak += 1
                    if empty_streak >= 10:
                        break
                else:
                    empty_streak = 0
                    last_good_id = probe_id + 10
                probe_id += 10
                await asyncio.sleep(0.1)

            # Set ceiling to highest verified ID + safety buffer
            actual_last_msg_id = last_good_id + 50 
            
        except Exception as e:
            logger.error(f"Ascending Radar Probe failed: {e}")
            pass

    # FALLBACK
    if not actual_last_msg_id:
        if known_msg_id:
            actual_last_msg_id = known_msg_id
        else:
            err = (
                "❌ **Telegram Security Block:** I cannot scan this channel from the outside.\n\n"
                "**How to Fix This:**\n"
                "1️⃣ Add me to the channel as an Admin, OR\n"
                "2️⃣ **Forward the absolute newest file** from the channel to me, OR\n"
                "3️⃣ Send a **direct link** to the newest post (e.g., `t.me/ChannelName/1500`)."
            )
            if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, err)
            else: await message.reply_text(err)
            return

    success = await db.add_index_job(target_chat_id, target_chat_name, actual_last_msg_id)

    if success:
        msg_text = f"✅ **Job Queued Successfully!**\n\nChannel: `{target_chat_name}`\nTargeting ~`{actual_last_msg_id}` messages.\n\nThe bot will safely process this in the background."
    else:
        msg_text = f"⚠️ **Job Started / Reset!**\n\nThe bot is processing `{target_chat_name}`."
        
    if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, msg_text)
    else: await message.reply_text(msg_text)


@Client.on_message(filters.command("cancel_index") & filters.user(Config.ADMINS))
async def stop_active_index(client: Client, message: Message):
    # Fetch the currently running job from the database
    job = await db.get_active_job()
    
    if not job:
        return await message.reply_text("⚠️ **No active indexing jobs to cancel.**")
        
    job_id = job["_id"]
    chat_name = job["chat_name"]
    
    # Trick the background worker into thinking the job is finished
    await db.update_job(job_id, {"status": "completed"})
    
    await message.reply_text(f"🛑 **Indexing Cancelled!**\n\nThe background worker has been ordered to stop processing `{chat_name}`.")


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command(["index", "batch"]) & filters.user(Config.ADMINS))
async def mass_indexer_command(client: Client, message: Message):
    
    if message.reply_to_message:
        reply = message.reply_to_message
        target_chat = None
        last_msg_id = None
        
        # 🚀 FIX: Removed deprecated forward_from_chat. Modern Pyrogram v2 check!
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
        "3️⃣ **Type** the Link or Username (e.g., `@MyChannel` or `t.me/c/...`).\n\n"
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
    
    # 🚀 FIX: Removed deprecated forward_from_chat. Modern Pyrogram v2 check!
    if getattr(message, "forward_origin", None):
        if getattr(message.forward_origin, "chat", None):
            target_chat = message.forward_origin.chat.id
            known_msg_id = getattr(message.forward_origin, "message_id", 0)
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
                # Keep trying to resolve the peer instead of killing the job
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

            logger.info(f"🔄 Queue Indexing: {chat_name} - Saved {saved} new files.")
            await asyncio.sleep(3.0)

        except Exception as e:
            logger.error(f"Indexer Queue error: {e}")
            await asyncio.sleep(10)
