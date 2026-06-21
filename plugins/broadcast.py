import asyncio
import time
import uuid
import re
import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid
from database.multi_db import db
from config import Config

# ==========================================
# ⚙️ CORE EXECUTION LOOP
# ==========================================
async def execute_broadcast_run(client: Client, admin_chat_id: int, target_msg: Message, command_text: str, batch_id: str):
    skip_vips = "-novip" in command_text
    is_silent = "-silent" in command_text
    ask_match = re.search(r'-ask\s+(\d+)h', command_text)
    auto_delete_hours = int(ask_match.group(1)) if ask_match else 0

    status_msg = await client.send_message(admin_chat_id, f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")
    
    sent, failed, skipped = 0, 0, 0
    start_time = time.time()

    async for user in db.get_all_users():
        user_id = user.get("user_id")
        if not user_id: continue
            
        first_name = user.get("first_name", "User")
        
        if skip_vips and user.get("is_vip", False):
            skipped += 1
            continue
            
        try:
            if target_msg.text:
                custom_text = target_msg.text.replace("{first_name}", first_name)
                markup = target_msg.reply_markup if target_msg.reply_markup else None
                sent_msg = await client.send_message(user_id, custom_text, disable_notification=is_silent, reply_markup=markup)
            else:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent)
                
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
            
            if auto_delete_hours > 0:
                asyncio.create_task(schedule_auto_delete(client, user_id, sent_msg.id, auto_delete_hours))
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent)
                await db.log_broadcast(batch_id, user_id, sent_msg.id)
                sent += 1
            except: failed += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid): failed += 1
        except Exception: failed += 1
            
        if (sent + failed) % 20 == 0:
            elapsed = time.time() - start_time
            await status_msg.edit_text(
                f"🚀 **LIVE BROADCAST TRACKER**\n\n"
                f"🏷 **Batch ID:** `{batch_id}`\n"
                f"🟢 **Sent:** `{sent}`\n"
                f"🔴 **Failed:** `{failed}`\n"
                f"⏭ **Skipped:** `{skipped}`\n"
                f"⏱ **Time:** `{round(elapsed, 1)}s`"
            )
            
    total_time = round(time.time() - start_time, 1)
    await status_msg.edit_text(
        f"✅ **BROADCAST COMPLETE**\n\n"
        f"🏷 **Batch ID:** `{batch_id}`\n"
        f"🟢 **Total Sent:** `{sent}`\n"
        f"🔴 **Dead Accounts:** `{failed}`\n"
        f"⏭ **Skipped:** `{skipped}`\n"
        f"⏱ **Total Time:** `{total_time}s`\n\n"
        f"*(Use `/broadcast_del {batch_id}` to recall)*"
    )

async def schedule_auto_delete(client, user_id, msg_id, hours):
    await asyncio.sleep(hours * 3600)
    try:
        await client.delete_messages(user_id, msg_id)
        await db.delete_single_broadcast_log(user_id, msg_id)
    except: pass

# ==========================================
# ⏰ SCHEDULING WORKER
# ==========================================
async def schedule_worker(client: Client):
    """Background worker that continuously monitors the database for queued broadcasts."""
    await asyncio.sleep(10) # Let bot boot up safely
    while True:
        try:
            due_jobs = await db.get_due_broadcasts()
            for job in due_jobs:
                admin_id = job["admin_id"]
                msg_id = job["message_id"]
                
                try:
                    target_msg = await client.get_messages(admin_id, msg_id)
                    if target_msg.empty:
                        await client.send_message(admin_id, f"❌ **Scheduled Broadcast Failed:** The original message you replied to was deleted.\nBatch: `{job['batch_id']}`")
                        await db.mark_broadcast_complete(job["_id"])
                        continue
                        
                    asyncio.create_task(execute_broadcast_run(client, admin_id, target_msg, job["command_text"], job["batch_id"]))
                except Exception: pass
                
                await db.mark_broadcast_complete(job["_id"])
        except Exception: pass
        await asyncio.sleep(60) # Checks the database every 1 minute

# ==========================================
# ⚙️ THE COMMAND CENTER
# ==========================================
@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def ultimate_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    command_text = message.text.lower()
    batch_id = f"Batch_{str(uuid.uuid4())[:6].upper()}"
    
    # 🚀 Check for the Date Tag: Supports YYYY-MM-DD HH:MM or YYYY-MM-DD HH-MM
    schedule_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}[:\-]\d{2})', command_text)
    
    if schedule_match:
        raw_date = schedule_match.group(1)
        # Normalize HH-MM to HH:MM if you used a hyphen
        if len(raw_date) == 16 and raw_date[13] == "-":
            raw_date = raw_date[:13] + ":" + raw_date[14:]
            
        try:
            # 🇮🇳 THE IST TIMEZONE FIX
            # Create a timezone object for IST (UTC + 5 hours and 30 minutes)
            ist_timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            
            # Parse the time and explicitly attach the IST timezone to it
            dt = datetime.datetime.strptime(raw_date, "%Y-%m-%d %H:%M").replace(tzinfo=ist_timezone)
            run_at_ts = dt.timestamp()
            
            if run_at_ts <= time.time():
                return await message.reply_text("❌ Scheduled time must be in the future.")
                
            await db.add_scheduled_broadcast(batch_id, message.chat.id, target_msg.id, run_at_ts, command_text)
            return await message.reply_text(f"⏳ **Broadcast Scheduled!**\n\nBatch ID: `{batch_id}`\nWill auto-deploy at: `{raw_date}` (IST)")
        except ValueError:
            return await message.reply_text("❌ Invalid date format. Please use `YYYY-MM-DD HH:MM`.")

    # If no date tag is found, run the broadcast immediately
    await execute_broadcast_run(client, message.chat.id, target_msg, command_text, batch_id)

# ==========================================
# 🛡️ MODULE 3 & 4 (RECALL AND SURGICAL WIPES)
# ==========================================
@Client.on_message(filters.command("broadcast_del") & filters.user(Config.ADMINS))
async def recall_vault_menu(client: Client, message: Message):
    if len(message.command) > 1:
        batch_id = message.command[1].strip()
        status = await message.reply_text(f"🧨 **Scrubbing Batch `{batch_id}`...**")
        
        deleted = 0
        async for log in await db.get_broadcast_logs(batch_id):
            try:
                await client.delete_messages(log["user_id"], log["message_id"])
                deleted += 1
            except FloodWait as e: await asyncio.sleep(e.value)
            except: pass
                
        await db.delete_broadcast_batch(batch_id)
        return await status.edit_text(f"✅ **GHOST PROTOCOL COMPLETE**\n\n`{deleted}` messages from `{batch_id}` have been permanently erased from user chats.")

    batches = await db.get_recent_batches()
    buttons = []
    async for batch in batches:
        b_id = batch["_id"]
        count = batch["count"]
        buttons.append([InlineKeyboardButton(f"🗑 Scrub {b_id} ({count} msgs)", callback_data=f"delbatch_{b_id}")])
        
    if not buttons: return await message.reply_text("📂 The 48-Hour Vault is currently empty.")
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("🛡 **THE RECALL VAULT**\n\nSelect a recent batch to instantly delete it from all user inboxes:", reply_markup=reply_markup)

@Client.on_callback_query(filters.regex(r"^delbatch_") & filters.user(Config.ADMINS))
async def execute_batch_scrub(client: Client, query: CallbackQuery):
    batch_id = query.data.replace("delbatch_", "")
    await query.message.edit_text(f"🧨 **Scrubbing Batch `{batch_id}`...**")
    
    deleted = 0
    async for log in await db.get_broadcast_logs(batch_id):
        try:
            await client.delete_messages(log["user_id"], log["message_id"])
            deleted += 1
        except FloodWait as e: await asyncio.sleep(e.value)
        except: pass
            
    await db.delete_broadcast_batch(batch_id)
    await query.message.edit_text(f"✅ **GHOST PROTOCOL COMPLETE**\n\n`{deleted}` messages from `{batch_id}` have been permanently erased from user chats.")

@Client.on_message(filters.command("broadcast_edit") & filters.user(Config.ADMINS))
async def ghost_update(client: Client, message: Message):
    try:
        parts = message.text.split(" ", 2)
        batch_id = parts[1]
        new_text = parts[2]
    except IndexError:
        return await message.reply_text("⚠️ Format: `/broadcast_edit <Batch_ID> <New Text>`")
        
    status = await message.reply_text(f"👻 **Deploying Ghost Update to `{batch_id}`...**")
    edited = 0
    async for log in await db.get_broadcast_logs(batch_id):
        try:
            await client.edit_message_text(log["user_id"], log["message_id"], new_text)
            edited += 1
        except FloodWait as e: await asyncio.sleep(e.value)
        except: pass
            
    await status.edit_text(f"✅ **UPDATE COMPLETE**\n\nSilently edited `{edited}` messages.")

@Client.on_message(filters.command("user_broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def direct_support(client: Client, message: Message):
    try:
        target_user = int(message.command[1])
        await message.reply_to_message.copy(target_user)
        await message.reply_text(f"✅ Securely dropped into `{target_user}`'s PMs.")
    except Exception as e:
        await message.reply_text(f"❌ Failed: `{e}`")

@Client.on_message(filters.command("delbroadcastuser") & filters.user(Config.ADMINS))
async def surgical_wipe(client: Client, message: Message):
    try:
        target_user = int(message.command[1])
        latest_log = await db.get_user_latest_broadcast(target_user)
        if not latest_log: return await message.reply_text("❌ No recent broadcasts found for this user in the vault.")
            
        await client.delete_messages(target_user, latest_log["message_id"])
        await db.delete_single_broadcast_log(target_user, latest_log["message_id"])
        await message.reply_text(f"✅ **SURGICAL WIPE COMPLETE**\nThe last ad was scrubbed from `{target_user}`'s chat.")
    except Exception as e:
        await message.reply_text(f"❌ Failed: `{e}`")
