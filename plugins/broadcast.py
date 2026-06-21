import asyncio
import time
import uuid
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid
from database.multi_db import db
from config import Config

# ==========================================
# ⚙️ MODULE 1 & 2: THE COMMAND CENTER & TRACKER
# ==========================================

@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def ultimate_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    command_text = message.text.lower()
    
    # Parse Tags
    skip_vips = "-novip" in command_text
    is_silent = "-silent" in command_text
    
    # Check for the -ask <hours> tag
    ask_match = re.search(r'-ask\s+(\d+)h', command_text)
    auto_delete_hours = int(ask_match.group(1)) if ask_match else 0

    batch_id = f"Batch_{str(uuid.uuid4())[:6].upper()}"
    status_msg = await message.reply_text(f"🔄 **Preparing Broadcast...**\nBatch ID: `{batch_id}`")
    
    sent, failed, skipped = 0, 0, 0
    start_time = time.time()

    async for user in db.get_all_users():
        # 🚀 THE FIX: Correctly mapping "user_id" instead of "id"
        user_id = user.get("user_id")
        if not user_id:
            continue
            
        first_name = user.get("first_name", "User")
        
        # VIP Exclusion Logic
        if skip_vips and user.get("is_vip", False):
            skipped += 1
            continue
            
        try:
            # Dynamic Personalization ({first_name}) & Sending
            if target_msg.text:
                custom_text = target_msg.text.replace("{first_name}", first_name)
                # Copy markup if "Watch Now" buttons exist
                markup = target_msg.reply_markup if target_msg.reply_markup else None
                sent_msg = await client.send_message(user_id, custom_text, disable_notification=is_silent, reply_markup=markup)
            else:
                # For Polls, Images, and Media (Native Copy)
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent)
                
            # Log to 48-Hour Vault
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
            
            # The -ask Auto-Delete Task
            if auto_delete_hours > 0:
                asyncio.create_task(schedule_auto_delete(client, user_id, sent_msg.id, auto_delete_hours))
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            # Retry after flood
            sent_msg = await target_msg.copy(user_id, disable_notification=is_silent)
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            failed += 1
            # Optional: Add db.delete_user(user_id) here for the Database Janitor feature
        except Exception:
            failed += 1
            
        # Live Tracker Update (Every 20 messages to avoid flood limits)
        if (sent + failed) % 20 == 0:
            elapsed = time.time() - start_time
            await status_msg.edit_text(
                f"🚀 **LIVE BROADCAST TRACKER**\n\n"
                f"🏷 **Batch ID:** `{batch_id}`\n"
                f"🟢 **Sent:** `{sent}`\n"
                f"🔴 **Failed:** `{failed}`\n"
                f"⏭ **Skipped (VIP):** `{skipped}`\n"
                f"⏱ **Elapsed Time:** `{round(elapsed, 1)}s`"
            )
            
    # Final Dashboard Update
    total_time = round(time.time() - start_time, 1)
    await status_msg.edit_text(
        f"✅ **BROADCAST COMPLETE**\n\n"
        f"🏷 **Batch ID:** `{batch_id}`\n"
        f"🟢 **Total Sent:** `{sent}`\n"
        f"🔴 **Dead Accounts:** `{failed}`\n"
        f"⏭ **Skipped:** `{skipped}`\n"
        f"⏱ **Total Time:** `{total_time}s`\n\n"
        f"*(Use `/broadcast_del` to recall this batch)*"
    )

async def schedule_auto_delete(client, user_id, msg_id, hours):
    """Background worker for the -ask global timeout."""
    await asyncio.sleep(hours * 3600)
    try:
        await client.delete_messages(user_id, msg_id)
        await db.delete_single_broadcast_log(user_id, msg_id)
    except:
        pass

# ==========================================
# 🛡️ MODULE 3: DAMAGE CONTROL (VAULT & EDIT)
# ==========================================

@Client.on_message(filters.command("broadcast_del") & filters.user(Config.ADMINS))
async def recall_vault_menu(client: Client, message: Message):
    batches = await db.get_recent_batches()
    buttons = []
    
    async for batch in batches:
        b_id = batch["_id"]
        count = batch["count"]
        buttons.append([InlineKeyboardButton(f"🗑 Scrub {b_id} ({count} msgs)", callback_data=f"delbatch_{b_id}")])
        
    if not buttons:
        return await message.reply_text("📂 The 48-Hour Vault is currently empty.")
        
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("🛡 **THE RECALL VAULT**\n\nSelect a recent batch to instantly delete it from all user inboxes:", reply_markup=reply_markup)

@Client.on_callback_query(filters.regex(r"^delbatch_") & filters.user(Config.ADMINS))
async def execute_batch_scrub(client: Client, query: CallbackQuery):
    batch_id = query.data.split("_")[1]
    await query.message.edit_text(f"🧨 **Scrubbing Batch `{batch_id}`...**")
    
    deleted = 0
    async for log in await db.get_broadcast_logs(batch_id):
        try:
            await client.delete_messages(log["user_id"], log["message_id"])
            deleted += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except:
            pass
            
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
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except:
            pass
            
    await status.edit_text(f"✅ **UPDATE COMPLETE**\n\nSilently edited `{edited}` messages.")

# ==========================================
# 🎯 MODULE 4: SURGICAL ROUTING
# ==========================================

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
        
        if not latest_log:
            return await message.reply_text("❌ No recent broadcasts found for this user in the vault.")
            
        await client.delete_messages(target_user, latest_log["message_id"])
        await db.delete_single_broadcast_log(target_user, latest_log["message_id"])
        
        await message.reply_text(f"✅ **SURGICAL WIPE COMPLETE**\nThe last ad was scrubbed from `{target_user}`'s chat.")
    except Exception as e:
        await message.reply_text(f"❌ Failed: `{e}`")
