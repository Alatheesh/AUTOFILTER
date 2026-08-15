import io
import re
import time
import json
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
async def trigger_indexing_job(
    client: Client,
    message: Message,
    target_chat,
    prompt_msg_id=None,
    known_msg_id=None
):
    """
    Resolves the target channel and creates the normal indexing job.

    Behavior:
    - Public channel: indexes directly; bot does NOT need to be an admin.
    - Private channel: bot MUST be an administrator.
    - If a file was forwarded from anywhere in the channel, its message ID is
      used only to identify the correct channel. It is NOT used as the indexing
      ceiling.
    - The newest existing message is obtained directly from chat history.
      Deleted messages/gaps therefore do not require probing.
    - Database/indexing worker behavior is unchanged.
    """

    extracted_msg_id = None

    # ==========================================
    # ADVANCED LINK PARSER
    # ==========================================
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

        elif (
            not target_chat.startswith("@")
            and not target_chat.replace("-", "").isdigit()
        ):
            target_chat = f"@{target_chat}"

    if extracted_msg_id and not known_msg_id:
        known_msg_id = extracted_msg_id

    try:
        target_chat = int(target_chat)
    except (ValueError, TypeError):
        pass

    # ==========================================
    # RESOLVE CHANNEL
    # ==========================================
    try:
        chat_info = await client.get_chat(target_chat)

        target_chat_name = chat_info.title or str(target_chat)
        target_chat_id = (
            f"@{chat_info.username}"
            if chat_info.username
            else chat_info.id
        )

    except PeerIdInvalid:
        err = (
            f"❌ **Error: Cannot locate chat `{target_chat}`.**\n\n"
            f"**For a public channel:**\n"
            f"• Send its `@username` or public link.\n\n"
            f"**For a private channel:**\n"
            f"• Add the bot to the channel as an **Administrator**, "
            f"then try again."
        )

        if prompt_msg_id:
            await client.edit_message_text(
                message.chat.id,
                prompt_msg_id,
                err
            )
        else:
            await message.reply_text(err)

        return

    except Exception as e:
        logger.error(
            f"Error resolving target chat {target_chat}: {e}",
            exc_info=True
        )

        err = (
            f"❌ **Error Accessing Chat:** `{target_chat}`\n\n"
            f"Make sure the channel is valid and accessible.\n"
            f"Error: `{e}`"
        )

        if prompt_msg_id:
            await client.edit_message_text(
                message.chat.id,
                prompt_msg_id,
                err
            )
        else:
            await message.reply_text(err)

        return

    # ==========================================
    # PUBLIC vs PRIVATE CHANNEL
    # ==========================================
    # Public channel => has a username.
    # Private channel => no public username.
    is_private_channel = not bool(chat_info.username)

    if is_private_channel:
        try:
            me = await client.get_me()

            member = await client.get_chat_member(
                target_chat_id,
                me.id
            )

            member_status = str(
                getattr(member, "status", "")
            ).lower()

            if member_status not in ("administrator", "owner"):
                err = (
                    f"🔒 **Private Channel Detected**\n\n"
                    f"Channel: `{target_chat_name}`\n\n"
                    f"The bot must be added to this private channel "
                    f"as an **Administrator** before indexing can start.\n\n"
                    f"After making the bot an admin, run `/index` again "
                    f"or forward a file from the channel and reply `/index`."
                )

                if prompt_msg_id:
                    await client.edit_message_text(
                        message.chat.id,
                        prompt_msg_id,
                        err
                    )
                else:
                    await message.reply_text(err)

                return

        except Exception as e:
            logger.warning(
                f"Private channel admin check failed for "
                f"{target_chat_name} ({target_chat_id}): {e}"
            )

            err = (
                f"🔒 **Private Channel Requires Administration**\n\n"
                f"Channel: `{target_chat_name}`\n\n"
                f"Please add the bot to this channel as an "
                f"**Administrator** with permission to access messages, "
                f"then try `/index` again."
            )

            if prompt_msg_id:
                await client.edit_message_text(
                    message.chat.id,
                    prompt_msg_id,
                    err
                )
            else:
                await message.reply_text(err)

            return

    # ==========================================
    # FIND THE NEWEST EXISTING MESSAGE
    # ==========================================
    # IMPORTANT:
    # `known_msg_id` from a forwarded file is ONLY a reference that
    # identifies the channel. We intentionally do NOT use it as the
    # indexing ceiling because the forwarded file may be from the
    # middle of the channel.
    #
    # We ask Telegram for the newest existing message directly.
    # Deleted messages/gaps do not matter.
    actual_last_msg_id = None

    try:
        if prompt_msg_id:
            await client.edit_message_text(
                message.chat.id,
                prompt_msg_id,
                "🔄 **Finding the latest message in the channel...**"
            )

        async for latest_message in client.get_chat_history(
            target_chat_id,
            limit=1
        ):
            if latest_message and not getattr(
                latest_message,
                "empty",
                False
            ):
                actual_last_msg_id = latest_message.id
                break

    except FloodWait as fw:
        logger.warning(
            f"FloodWait while finding latest message in "
            f"{target_chat_name}: {fw.value}s"
        )

        if prompt_msg_id:
            await client.edit_message_text(
                message.chat.id,
                prompt_msg_id,
                f"⏳ **Telegram rate limit reached.**\n\n"
                f"Please try again after `{fw.value}` seconds."
            )
        else:
            await message.reply_text(
                f"⏳ Telegram rate limit reached. "
                f"Please try again after `{fw.value}` seconds."
            )

        return

    except Exception as e:
        logger.error(
            f"Failed to find latest message in "
            f"{target_chat_name}: {e}",
            exc_info=True
        )

    # ==========================================
    # FALLBACK
    # ==========================================
    # Only use the forwarded/direct-link message as a fallback if
    # Telegram did not return chat history. This preserves the old
    # behavior without making it the normal path.
    if not actual_last_msg_id and known_msg_id:
        actual_last_msg_id = known_msg_id

    if not actual_last_msg_id:
        err = (
            f"❌ **Cannot find messages in `{target_chat_name}`.**\n\n"
            f"Please make sure:\n"
            f"• The public channel is accessible, or\n"
            f"• The private channel has the bot as an Administrator."
        )

        if prompt_msg_id:
            await client.edit_message_text(
                message.chat.id,
                prompt_msg_id,
                err
            )
        else:
            await message.reply_text(err)

        return

    # ==========================================
    # CREATE THE EXISTING DATABASE INDEX JOB
    # ==========================================
    success = await db.add_index_job(
        target_chat_id,
        target_chat_name,
        actual_last_msg_id
    )

    if success:
        msg_text = (
            f"✅ **Job Queued Successfully!**\n\n"
            f"Channel: `{target_chat_name}`\n"
            f"Starting from newest message: `{actual_last_msg_id}`\n\n"
            f"The bot will safely process the channel in the "
            f"background."
        )
    else:
        msg_text = (
            f"⚠️ **Job Started / Reset!**\n\n"
            f"The bot is processing `{target_chat_name}`."
        )

    if prompt_msg_id:
        await client.edit_message_text(
            message.chat.id,
            prompt_msg_id,
            msg_text
        )
    else:
        await message.reply_text(msg_text)


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

# ==========================================
# 📊 EXPORT INDEXING DATA
# ==========================================
@Client.on_message(filters.command("indexdata") & filters.user(Config.ADMINS))
async def export_index_data(client: Client, message: Message):
    status = await message.reply_text("📥 **Extracting indexing jobs data...**")
    try:
        # Fetch all indexing jobs from the database
        cursor = db.jobs.find({})
        jobs = await cursor.to_list(length=None)
        
        if not jobs:
            return await status.edit_text("⚠️ **No indexing jobs found in the database.**")
        
        # Format the data cleanly
        json_data = json.dumps(jobs, indent=4)
        
        # Create an in-memory JSON file
        file_buffer = io.BytesIO(json_data.encode('utf-8'))
        file_buffer.name = f"indexing_queue_{int(time.time())}.json"
        
        # Send the file to the creator
        await message.reply_document(
            document=file_buffer,
            caption=f"📦 **Indexing Queue Export**\nTotal records found: `{len(jobs)}`\n\n_Contains detailed progression of all queued channels._"
        )
        await status.delete()
        
    except Exception as e:
        logger.error(f"Index Data Export Error: {e}")
        await status.edit_text(f"❌ **Failed to export data:** `{e}`")
