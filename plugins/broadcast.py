import asyncio
import time
import uuid
import re
import datetime
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid, MessageNotModified
from database.multi_db import db
from config import Config

# ==========================================
# 🛠️ THE BUTTON PARSER ENGINE
# ==========================================
def parse_inline_buttons(text: str):
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
        return '\n'.join(final_lines), None
        
    return '\n'.join(final_lines), InlineKeyboardMarkup(markup)

# ==========================================
# ⚙️ CORE EXECUTION LOOP
# ==========================================
async def execute_broadcast_run(client: Client, admin_chat_id: int, target_msg: Message, command_text: str, batch_id: str):
    skip_vips = "-novip" in command_text
    is_silent = "-silent" in command_text
    allow_replies = "-reply" in command_text
    reply_marker = "\n\n*(💬 Reply directly to this message to respond!)*"
    
    # 🎯 1. Auto-Delete Parser
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

    # 🎯 2. Countdown Parser (NATIVE TELEGRAM TIMESTAMP)
    countdown_match = re.search(r'-countdown\s+(\d+)([smh])', command_text)
    countdown_seconds = 0
    time_string = ""
    if countdown_match:
        val = int(countdown_match.group(1))
        unit = countdown_match.group(2)
        if unit == 's':
            countdown_seconds = val
        elif unit == 'm':
            countdown_seconds = val * 60
        elif unit == 'h':
            countdown_seconds = val * 3600
        
        target_ts = int(time.time()) + countdown_seconds
        time_string = f"\n\n⏳ **Expires:** <t:{target_ts}:R>"

    # 🎯 3. Follow-Up Parser
    followup_match = re.search(r'-followup\s+(Batch_[A-Z0-9]+)', command_text, re.IGNORECASE)
    followup_batch = followup_match.group(1).upper() if followup_match else None
    
    if followup_batch:
        await db.increment_batch_followup(followup_batch)

    # 🎯 4. Reaction Parser
    reaction_match = re.search(r'-reaction\s+([^\n\-]+)', command_text)
    reactions = []
    if reaction_match:
        reactions = [e for e in reaction_match.group(1).split() if e]

    status_msg = await client.send_message(admin_chat_id, f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")
    sent = 0
    failed = 0
    skipped = 0
    start_time = time.time()

    base_text = target_msg.text or target_msg.caption or ""
    parsed_text, parsed_markup = parse_inline_buttons(base_text)
    
    # Generate Reaction Buttons
    final_markup = []
    if parsed_markup:
        final_markup.extend(parsed_markup.inline_keyboard)
    elif target_msg.reply_markup:
        final_markup.extend(target_msg.reply_markup.inline_keyboard)
        
    if reactions:
        reaction_row = [InlineKeyboardButton(text=emoji, callback_data=f"breact_{batch_id}_{emoji}") for emoji in reactions]
        final_markup.append(reaction_row)
        
    if final_markup:
        base_markup = InlineKeyboardMarkup(final_markup)
    else:
        base_markup = None

    # 🔄 Determine Target Audience
    if followup_batch:
        target_audience = await db.get_broadcast_logs(followup_batch)
    else:
        target_audience = db.get_all_users()

    async for item in target_audience:
        user_id = item.get("user_id")
        
        if followup_batch:
            reply_to_id = item.get("message_id")
        else:
            reply_to_id = None
        
        if not user_id:
            continue
        
        if followup_batch:
            user_data = await db.users.find_one({"user_id": user_id})
        else:
            user_data = item
            
        if not user_data:
            user_data = {}
        
        if skip_vips and user_data.get("is_vip", False):
            skipped += 1
            continue
            
        first_name = user_data.get("first_name", "User")
        last_name = user_data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()
            
        try:
            has_tags = "{first_name}" in parsed_text or "{last_name}" in parsed_text or "{full_name}" in parsed_text
            has_appends = allow_replies or countdown_seconds > 0
            
            # PERFECT FORMATTING LOGIC: Copy strictly if no variables are used.
            if has_tags or has_appends:
                if target_msg.text:
                    custom_text = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)
                    if allow_replies:
                        custom_text += reply_marker
                    if countdown_seconds > 0:
                        custom_text += time_string
                    sent_msg = await client.send_message(user_id, custom_text, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                elif target_msg.caption:
                    custom_caption = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)
                    if allow_replies:
                        custom_caption += reply_marker
                    if countdown_seconds > 0:
                        custom_caption += time_string
                    sent_msg = await client.send_cached_media(user_id, file_id=target_msg.photo.file_id if target_msg.photo else target_msg.video.file_id, caption=custom_caption, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                else:
                    sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
            else:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
            
            if auto_delete_seconds > 0:
                asyncio.create_task(schedule_auto_delete(client, user_id, sent_msg.id, auto_delete_seconds))
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                await db.log_broadcast(batch_id, user_id, sent_msg.id)
                sent += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
            failed += 1
        except Exception:
            failed += 1
            
        if (sent + failed) % 20 == 0:
            elapsed = time.time() - start_time
            await status_msg.edit_text(f"🚀 **LIVE TRACKER**\n🏷 `{batch_id}`\n🟢 Sent: `{sent}`\n🔴 Failed: `{failed}`\n⏱ Time: `{round(elapsed, 1)}s`")
            
    total_time = round(time.time() - start_time, 1)
    
    tracker_buttons = []
    if reactions:
        tracker_buttons.append([InlineKeyboardButton("🔄 Refresh Reactions", callback_data=f"trk_{batch_id}_{sent}_{failed}_{skipped}")])
        
    if tracker_buttons:
        tracker_markup = InlineKeyboardMarkup(tracker_buttons)
    else:
        tracker_markup = None
    
    await status_msg.edit_text(f"✅ **BROADCAST COMPLETE**\n\n🏷 **Batch ID:** `{batch_id}`\n🟢 **Total Sent:** `{sent}`\n🔴 **Dead Accounts:** `{failed}`\n⏭ **Skipped:** `{skipped}`\n⏱ **Total Time:** `{total_time}s`\n\n*(Use `/broadcast_del {batch_id}` to recall)*", reply_markup=tracker_markup)

async def schedule_auto_delete(client, user_id, msg_id, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try:
        await client.delete_messages(user_id, msg_id)
        await db.delete_single_broadcast_log(user_id, msg_id)
    except Exception:
        pass

# ==========================================
# ⏰ REACTION & TRACKER CALLBACKS
# ==========================================
@Client.on_callback_query(filters.regex(r"^breact_([^_]+)_(.+)$"))
async def handle_broadcast_reaction(client: Client, callback: CallbackQuery):
    parts = callback.data.split("_", 3)
    batch_id = f"{parts[1]}_{parts[2]}" 
    emoji = parts[3]
    
    is_new = await db.add_batch_reaction(batch_id, emoji, callback.from_user.id)
    if is_new:
        await callback.answer(f"You reacted with {emoji}!", show_alert=False)
    else:
        await callback.answer("You already reacted!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^trk_([^_]+)_(.+)"))
async def refresh_admin_tracker(client: Client, callback: CallbackQuery):
    parts = callback.data.split("_")
    batch_id = f"{parts[1]}_{parts[2]}"
    sent = parts[3]
    failed = parts[4]
    skipped = parts[5]
    
    reaction_stats = await db.get_batch_engagement(batch_id)
    
    if reaction_stats["reactions"]:
        react_text = "\n\n📊 **Reaction Engagement:**\n"
    else:
        react_text = ""
        
    for emoji, count in reaction_stats["reactions"].items():
        react_text += f"{emoji} `{count}`\n"
        
    try:
        await callback.message.edit_text(f"✅ **BROADCAST COMPLETE**\n\n🏷 **Batch ID:** `{batch_id}`\n🟢 **Total Sent:** `{sent}`\n🔴 **Dead Accounts:** `{failed}`\n⏭ **Skipped:** `{skipped}`{react_text}\n*(Use `/broadcast_del {batch_id}` to recall)*", reply_markup=callback.message.reply_markup)
        await callback.answer("Stats Refreshed!", show_alert=False)
    except MessageNotModified:
        # Silently catch the 400 error when stats haven't changed yet
        await callback.answer("No new reactions yet!", show_alert=False)

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
                except Exception:
                    pass
                await db.mark_broadcast_complete(job["_id"])
        except Exception:
            pass
        await asyncio.sleep(60)

# ==========================================
# ⚙️ COMMAND CENTER (BROADCAST & RECALL)
# ==========================================
@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def ultimate_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    command_text = message.text.lower()
    
    stop_match = re.search(r'-(?:stop|cancel)followup\s+(Batch_[A-Z0-9]+)', command_text, re.IGNORECASE)
    if stop_match:
        batch_id_to_cancel = stop_match.group(1).upper()
        success = await db.cancel_scheduled_broadcast(batch_id_to_cancel)
        if success:
            return await message.reply_text(f"✅ **Cancelled!** Scheduled broadcast `{batch_id_to_cancel}` has been deleted from the queue.")
        else:
            return await message.reply_text(f"❌ **Failed:** Could not find a pending scheduled broadcast with ID `{batch_id_to_cancel}`.")

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
            return await message.reply_text(f"⏳ **Broadcast Scheduled!**\n\nBatch ID: `{batch_id}`\nWill auto-deploy at: `{raw_date}` (IST)\n*(Use `/cancelfollowup {batch_id}` to cancel)*")
        except ValueError:
            return await message.reply_text("❌ Invalid date format. Please use `YYYY-MM-DD HH:MM`.")

    await execute_broadcast_run(client, message.chat.id, target_msg, command_text, batch_id)

@Client.on_message(filters.command(["cancel_followup", "cancel_schedule", "stopfollowup", "cancelfollowup"]) & filters.user(Config.ADMINS))
async def cancel_scheduled_job(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Format:** `/stopfollowup <Batch_ID>`")
        
    batch_id = message.command[1].strip()
    success = await db.cancel_scheduled_broadcast(batch_id)
    
    if success:
        await message.reply_text(f"✅ **Cancelled!** Scheduled broadcast `{batch_id}` has been deleted from the queue.")
    else:
        await message.reply_text(f"❌ **Failed:** Could not find a pending scheduled broadcast with ID `{batch_id}`.")

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
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
                
        await db.delete_broadcast_batch(batch_id)
        return await status.edit_text(f"✅ **GHOST PROTOCOL COMPLETE**\n\n`{deleted}` messages from `{batch_id}` have been permanently erased from user chats.")

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
    batch_id = query.data.replace("delbatch_", "")
    await query.message.edit_text(f"🧨 **Scrubbing Batch `{batch_id}`...**")
    deleted = 0
    async for log in await db.get_broadcast_logs(batch_id):
        try:
            await client.delete_messages(log["user_id"], log["message_id"])
            deleted += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass
            
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
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass
            
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
        if not latest_log:
            return await message.reply_text("❌ No recent broadcasts found for this user in the vault.")
            
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
    target_msg = message.reply_to_message
    
    # 🚀 INTELLIGENT DB LOOKUP: Matches the replied message directly to the broadcast batch!
    log = await db.broadcast_logs.find_one({"user_id": message.from_user.id, "message_id": target_msg.id})
    if not log:
        return 
        
    batch_id = log["batch_id"]
    await db.add_batch_reply(batch_id, message.from_user.id)
    
    admin_id = Config.ADMINS[0]  
    await client.send_message(
        chat_id=admin_id,
        text=f"📩 **New Reply to Broadcast!**\n\n👤 **User:** {message.from_user.mention}\n🆔 **ID:** `{message.from_user.id}`\n🏷 **Batch:** `{batch_id}`\n👇 Their reply is below:"
    )
    await message.forward(admin_id)

@Client.on_message(filters.command("replybroadcast") & filters.user(Config.ADMINS) & filters.reply)
async def smart_admin_reply(client: Client, message: Message):
    target_msg = message.reply_to_message
    target_user = None
    
    if target_msg.text and "🆔 **ID:** `" in target_msg.text:
        match = re.search(r"🆔 \*\*ID:\*\* `(\d+)`", target_msg.text)
        if match:
            target_user = int(match.group(1))
    elif getattr(target_msg, "forward_origin", None) and getattr(target_msg.forward_origin, "sender_user", None):
        target_user = target_msg.forward_origin.sender_user.id
    elif getattr(target_msg, "forward_from", None):
        target_user = target_msg.forward_from.id
        
    if not target_user:
        return await message.reply_text("❌ **Could not detect User ID.**\nPlease reply to the '📩 New Reply' header.")
        
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Format:** `/replybroadcast [-ask 10s] <your message>`")
        
    raw_text = message.text.split(" ", 1)[1]
    ask_match = re.search(r'-ask\s+(\d+)([smh])', raw_text)
    auto_delete_seconds = 48 * 3600 
    
    if ask_match:
        val = int(ask_match.group(1))
        unit = ask_match.group(2)
        
        if unit == 's':
            auto_delete_seconds = val
        elif unit == 'm':
            auto_delete_seconds = val * 60
        elif unit == 'h':
            auto_delete_seconds = val * 3600
            
        raw_text = re.sub(r'-ask\s+\d+[smh]', '', raw_text).strip()
        
    if not raw_text:
        return await message.reply_text("⚠️ You cannot send an empty message.")
    
    try:
        sent_msg = await client.send_message(chat_id=target_user, text=f"👨‍💻 **Admin Reply:**\n\n{raw_text}")
        confirm_text = f"✅ **Reply successfully delivered to `{target_user}`.**"
        
        if ask_match:
            confirm_text += f"\n*(Will auto-delete in {auto_delete_seconds}s)*"
        else:
            confirm_text += f"\n*(Will auto-delete in 48h)*"
            
        asyncio.create_task(schedule_auto_delete(client, target_user, sent_msg.id, auto_delete_seconds))
        await message.reply_text(confirm_text)
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send reply:** `{e}`")
