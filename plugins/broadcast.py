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
# 🛠️ THE BUTTON PARSER ENGINE
# ==========================================
def parse_inline_buttons(text: str):
    """Converts [Text | Link] syntax into actual Telegram Inline Buttons."""
    if not text:
        return text, None
        
    markup = []
    lines = text.split('\n')
    final_lines = []
    
    for line in lines:
        buttons = re.findall(r'\[([^\|]+)\|([^\]]+)\]', line)
        if buttons:
            row = []
            for btn_text, btn_link in buttons:
                btn_text = btn_text.strip()
                btn_link = btn_link.strip()
                if btn_link.startswith('http://') or btn_link.startswith('https://'):
                    row.append(InlineKeyboardButton(btn_text, url=btn_link))
                else:
                    row.append(InlineKeyboardButton(btn_text, callback_data=btn_link))
            markup.append(row)
            line = re.sub(r'\[([^\|]+)\|([^\]]+)\]', '', line).strip()
            if line:
                final_lines.append(line)
        else:
            final_lines.append(line)
            
    if not markup:
        return text, None
    return '\n'.join(final_lines), InlineKeyboardMarkup(markup)

# ==========================================
# ⚙️ CORE EXECUTION LOOP
# ==========================================
async def execute_broadcast_run(client: Client, admin_chat_id: int, target_msg: Message, command_text: str, batch_id: str):
    skip_vips = "-novip" in command_text
    is_silent = "-silent" in command_text
    
    # 🌟 Smart Auto-Delete Delay (Seconds, Minutes, Hours)
    ask_match = re.search(r'-ask\s+(\d+)([smh])', command_text)
    auto_delete_seconds = 0
    if ask_match:
        val = int(ask_match.group(1))
        unit = ask_match.group(2)
        if unit == 's':
            auto_delete_seconds = val
        elif unit == 'm':
            auto_delete_seconds = val * 60
        elif unit == 'h':
            auto_delete_seconds = val * 3600

    status_msg = await client.send_message(admin_chat_id, f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")
    
    sent, failed, skipped = 0, 0, 0
    start_time = time.time()

    base_text = target_msg.text or target_msg.caption or ""
    parsed_text, parsed_markup = parse_inline_buttons(base_text)
    base_markup = parsed_markup if parsed_markup else target_msg.reply_markup

    async for user in db.get_all_users():
        user_id = user.get("user_id")
        if not user_id: continue
        
        if skip_vips and user.get("is_vip", False):
            skipped += 1
            continue
            
        # 🌟 Live Smart Name Fallback System
        first_name = user.get("first_name")
        last_name = user.get("last_name", "")
        
        if not first_name or first_name == "User":
            try:
                tg_user = await client.get_users(user_id)
                first_name = tg_user.first_name or "User"
                last_name = tg_user.last_name or ""
            except Exception:
                first_name = "User"
                last_name = ""
        else:
            last_name = last_name or ""
            
        full_name = f"{first_name} {last_name}".strip()
            
        try:
            if target_msg.text:
                custom_text = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)
                sent_msg = await client.send_message(user_id, custom_text, disable_notification=is_silent, reply_markup=base_markup)
            
            elif target_msg.caption:
                custom_caption = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)
                sent_msg = await client.send_cached_media(user_id, file_id=target_msg.photo.file_id if target_msg.photo else target_msg.video.file_id, caption=custom_caption, disable_notification=is_silent, reply_markup=base_markup)
            
            else:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup)
                
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
            
            if auto_delete_seconds > 0:
                asyncio.create_task(schedule_auto_delete(client, user_id, sent_msg.id, auto_delete_seconds))
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup)
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

async def schedule_auto_delete(client, user_id, msg_id, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try:
        await client.delete_messages(user_id, msg_id)
        await db.delete_single_broadcast_log(user_id, msg_id)
    except: pass

# ==========================================
# ⏰ SCHEDULING WORKER
# ==========================================
async def schedule_worker(client: Client):
    await asyncio.sleep(10)
    while True:
        try:
            due_jobs = await db.get_due_broadcasts()
            for job in due_jobs:
                admin_id = job["admin_id"]
                msg_id = job["message_id"]
                try:
                    target_msg = await client.get_messages(admin_id, msg_id)
                    if target_msg.empty:
                        await client.send_message(admin_id, f"❌ **Scheduled Broadcast Failed:** The original message was deleted.\nBatch: `{job['batch_id']}`")
                        await db.mark_broadcast_complete(job["_id"])
                        continue
                    asyncio.create_task(execute_broadcast_run(client, admin_id, target_msg, job["command_text"], job["batch_id"]))
                except Exception: pass
                await db.mark_broadcast_complete(job["_id"])
        except Exception: pass
        await asyncio.sleep(60)

# ==========================================
# ⚙️ COMMAND CENTER (BROADCAST & RECALL)
# ==========================================
@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def ultimate_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    command_text = message.text.lower()
    batch_id = f"Batch_{str(uuid.uuid4())[:6].upper()}"
    
    schedule_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}[:\-]\d{2})', command_text)
    
    if schedule_match:
        raw_date = schedule_match.group(1)
        if len(raw_date) == 16 and raw_date[13] == "-":
            raw_date = raw_date[:13] + ":" + raw_date[14:]
        try:
            ist_timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            dt = datetime.datetime.strptime(raw_date, "%Y-%m-%d %H:%M").replace(tzinfo=ist_timezone)
            run_at_ts = dt.timestamp()
            if run_at_ts <= time.time():
                return await message.reply_text("❌ Scheduled time must be in the future.")
            await db.add_scheduled_broadcast(batch_id, message.chat.id, target_msg.id, run_at_ts, command_text)
            return await message.reply_text(f"⏳ **Broadcast Scheduled!**\n\nBatch ID: `{batch_id}`\nWill auto-deploy at: `{raw_date}` (IST)")
        except ValueError:
            return await message.reply_text("❌ Invalid date format. Please use `YYYY-MM-DD HH:MM`.")

    await execute_broadcast_run(client, message.chat.id, target_msg, command_text, batch_id)

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
    await query.message.edit_text(f"✅ **GHOST PROTOCOL COMPLETE**\n\n`{deleted}` messages from `{batch_id}` have been erased.")

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

# ==========================================
# 💬 TWO-WAY BROADCAST COMMUNICATION
# ==========================================
@Client.on_message(filters.private & filters.reply & ~filters.user(Config.ADMINS))
async def handle_user_reply_to_broadcast(client: Client, message: Message):
    """Catches user replies to broadcasts and forwards them to the primary admin."""
    admin_id = Config.ADMINS[0]  
    await client.send_message(
        chat_id=admin_id,
        text=f"📩 **New Reply to Broadcast!**\n\n"
             f"👤 **User:** {message.from_user.mention}\n"
             f"🆔 **ID:** `{message.from_user.id}`\n"
             f"👇 Their reply is below:"
    )
    await message.forward(admin_id)

@Client.on_message(filters.command("replybroadcast") & filters.user(Config.ADMINS) & filters.reply)
async def smart_admin_reply(client: Client, message: Message):
    """Allows admin to reply directly to the forwarded message with default 48h auto-delete."""
    target_msg = message.reply_to_message
    target_user = None
    
    if target_msg.text and "🆔 **ID:** `" in target_msg.text:
        match = re.search(r"🆔 \*\*ID:\*\* `(\d+)`", target_msg.text)
        if match:
            target_user = int(match.group(1))
    elif target_msg.forward_from:
        target_user = target_msg.forward_from.id
        
    if not target_user:
        return await message.reply_text("❌ **Could not detect User ID.**\nPlease make sure you are replying to the '📩 New Reply' header message.")
        
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Format:** `/replybroadcast [-ask 10s] <your message>`")
        
    raw_text = message.text.split(" ", 1)[1]
    
    # 🌟 Check for the auto-delete flag, DEFAULT TO 48 HOURS (172800 seconds)
    ask_match = re.search(r'-ask\s+(\d+)([smh])', raw_text)
    auto_delete_seconds = 48 * 3600  # Default 48 hours
    
    if ask_match:
        val = int(ask_match.group(1))
        unit = ask_match.group(2)
        if unit == 's': auto_delete_seconds = val
        elif unit == 'm': auto_delete_seconds = val * 60
        elif unit == 'h': auto_delete_seconds = val * 3600
        
        # Remove the '-ask' command from the actual message payload
        raw_text = re.sub(r'-ask\s+\d+[smh]', '', raw_text).strip()
        
    if not raw_text:
        return await message.reply_text("⚠️ You cannot send an empty message.")
    
    try:
        sent_msg = await client.send_message(
            chat_id=target_user, 
            text=f"👨‍💻 **Admin Reply:**\n\n{raw_text}"
        )
        
        confirm_text = f"✅ **Reply successfully delivered to `{target_user}`.**"
        
        if ask_match:
            confirm_text += f"\n*(Will auto-delete in {auto_delete_seconds}s as requested)*"
        else:
            confirm_text += f"\n*(Will auto-delete in 48h by default)*"
            
        # Trigger the deletion timer
        asyncio.create_task(schedule_auto_delete(client, target_user, sent_msg.id, auto_delete_seconds))
            
        await message.reply_text(confirm_text)
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send reply:** `{e}`")
