import asyncio
import time
import uuid
import re
import datetime
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, PeerIdInvalid, MessageNotModified, UserIsBot
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# 🧠 State Machine: Remembers message IDs and Timestamps for clean UI editing
BROADCAST_STATE = {}

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
async def execute_broadcast_run(client: Client, admin_chat_id: int, target_msg: Message, command_text: str, batch_id: str, status_msg_id: int = None):
    # 🚀 FIX & NEW FEATURE: VIP Parsing Flags
    skip_vips = "-novip" in command_text
    only_vips = "-vip" in command_text and not skip_vips # Prioritizes -novip if both are accidentally used
    
    is_silent = "-silent" in command_text
    allow_replies = "-reply" in command_text
    reply_marker = "\n\n*(💬 Reply directly to this message to respond!)*"
    
    # 🎯 1. Auto-Delete Parser
    ask_match = re.search(r'-ask\s+(\d+)([smh])', command_text)
    auto_delete_seconds = 0
    if ask_match:
        val = int(ask_match.group(1))
        unit = ask_match.group(2)
        if unit == 's': auto_delete_seconds = val
        elif unit == 'm': auto_delete_seconds = val * 60
        elif unit == 'h': auto_delete_seconds = val * 3600

    # 🎯 2. Follow-Up Parser
    followup_match = re.search(r'-followup\s+(Batch_[A-Z0-9]+)', command_text, re.IGNORECASE)
    followup_batch = followup_match.group(1).upper() if followup_match else None
    
    if followup_batch:
        await db.increment_batch_followup(followup_batch)

    # 🎯 3. Reaction Parser
    reaction_match = re.search(r'-reaction\s+([^\n\-]+)', command_text)
    reactions = [e for e in reaction_match.group(1).split() if e] if reaction_match else []

    # UI Tracker
    if status_msg_id:
        try:
            status_msg = await client.get_messages(admin_chat_id, status_msg_id)
            await status_msg.edit_text(f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")
        except Exception:
            status_msg = await client.send_message(admin_chat_id, f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")
    else:
        status_msg = await client.send_message(admin_chat_id, f"🔄 **Deploying Broadcast...**\nBatch ID: `{batch_id}`")

    # 🚀 VIP PRE-FETCHER: Grabs all active VIPs into RAM instantly to prevent DB crashing during the loop!
    active_vip_ids = set()
    if skip_vips or only_vips:
        now = datetime.datetime.now()
        ts_now = time.time()
        async for vip in db.vip_users.find({}):
            if vip.get("status") == "Active" and "expiry" in vip and isinstance(vip["expiry"], datetime.datetime) and vip["expiry"] > now:
                active_vip_ids.add(vip.get("user_id"))
            elif "expires_at" in vip and isinstance(vip["expires_at"], (int, float)) and vip["expires_at"] > ts_now:
                active_vip_ids.add(vip.get("user_id"))

    sent = failed = skipped = 0
    start_time = time.time()

    # Preserve exact markdown (bold, links, etc.) when converting to string
    base_text = ""
    if target_msg.text:
        base_text = target_msg.text.markdown if hasattr(target_msg.text, 'markdown') else str(target_msg.text)
    elif target_msg.caption:
        base_text = target_msg.caption.markdown if hasattr(target_msg.caption, 'markdown') else str(target_msg.caption)

    parsed_text, parsed_markup = parse_inline_buttons(base_text)
    
    # Feature Flags
    has_tags = "{first_name}" in parsed_text or "{last_name}" in parsed_text or "{full_name}" in parsed_text
    needs_custom_text = has_tags or allow_replies

    # Generate Buttons
    final_markup = []
    if parsed_markup: final_markup.extend(parsed_markup.inline_keyboard)
    elif target_msg.reply_markup: final_markup.extend(target_msg.reply_markup.inline_keyboard)
        
    if reactions:
        reaction_row = [InlineKeyboardButton(text=emoji, callback_data=f"breact_{batch_id}_{emoji}") for emoji in reactions]
        final_markup.append(reaction_row)
        
    base_markup = InlineKeyboardMarkup(final_markup) if final_markup else None

    # Audience Iterator
    target_audience = await db.get_broadcast_logs(followup_batch) if followup_batch else db.get_all_users()

    async for item in target_audience:
        user_id = item.get("user_id")
        if not user_id: continue
        
        # 🚀 APPLY VIP FILTER LOGIC
        if skip_vips or only_vips:
            is_user_vip = user_id in active_vip_ids
            if skip_vips and is_user_vip:
                skipped += 1
                continue
            if only_vips and not is_user_vip:
                skipped += 1
                continue
        
        reply_to_id = item.get("message_id") if followup_batch else None
        user_data = await db.users.find_one({"user_id": user_id}) if followup_batch else item
        if not user_data: user_data = {}
            
        try:
            # Only run intensive name fetching if tags are actually used!
            if needs_custom_text:
                first_name_raw = user_data.get("first_name")
                last_name_raw = user_data.get("last_name")
                
                # Smart Telegram Fetch: If DB is empty, get name from API!
                if not first_name_raw or first_name_raw == "User":
                    try:
                        tg_user = await client.get_users(user_id)
                        first_name = tg_user.first_name or "User"
                        last_name = tg_user.last_name or ""
                        # Sync DB so it runs instantly next time
                        await db.users.update_one({"user_id": user_id}, {"$set": {"first_name": first_name, "last_name": last_name}})
                    except Exception:
                        first_name = "User"
                        last_name = ""
                else:
                    first_name = str(first_name_raw)
                    last_name = str(last_name_raw) if last_name_raw else ""
                    
                full_name = f"{first_name} {last_name}".strip()
                
                # Replace tags securely
                custom_text = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)
                if allow_replies:
                    custom_text += reply_marker
                    
                # Use .copy for media to preserve file structures natively, and .send_message for text
                if target_msg.media:
                    sent_msg = await target_msg.copy(user_id, caption=custom_text, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                else:
                    sent_msg = await client.send_message(user_id, text=custom_text, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
            else:
                # Absolute Fastest Route: No tags used, simple universal copy
                sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                
            await db.log_broadcast(batch_id, user_id, sent_msg.id)
            sent += 1
            
            if auto_delete_seconds > 0:
                asyncio.create_task(schedule_auto_delete(client, user_id, sent_msg.id, auto_delete_seconds))
                
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                # Retry logic
                if needs_custom_text and target_msg.media:
                    sent_msg = await target_msg.copy(user_id, caption=custom_text, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                elif needs_custom_text:
                    sent_msg = await client.send_message(user_id, text=custom_text, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                else:
                    sent_msg = await target_msg.copy(user_id, disable_notification=is_silent, reply_markup=base_markup, reply_to_message_id=reply_to_id)
                await db.log_broadcast(batch_id, user_id, sent_msg.id)
                sent += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, UserIsBot):
            failed += 1
        except Exception as e:
            logger.error(f"Broadcast error on user {user_id}: {e}")
            failed += 1
            
        if (sent + failed) % 20 == 0:
            elapsed = time.time() - start_time
            await status_msg.edit_text(f"🚀 **LIVE TRACKER**\n🏷 `{batch_id}`\n🟢 Sent: `{sent}`\n🔴 Failed: `{failed}`\n⏭ Skipped: `{skipped}`\n⏱ Time: `{round(elapsed, 1)}s`")
            
    total_time = round(time.time() - start_time, 1)
    
    tracker_buttons = []
    if reactions:
        tracker_buttons.append([InlineKeyboardButton("🔄 Refresh Reactions", callback_data=f"trk_{batch_id}_{sent}_{failed}_{skipped}")])
        
    tracker_markup = InlineKeyboardMarkup(tracker_buttons) if tracker_buttons else None
    
    await status_msg.edit_text(f"✅ **BROADCAST COMPLETE**\n\n🏷 **Batch ID:** `{batch_id}`\n🟢 **Total Sent:** `{sent}`\n🔴 **Dead Accounts:** `{failed}`\n⏭ **Skipped:** `{skipped}`\n⏱ **Total Time:** `{total_time}s`\n\n*(Use `/broadcast_del {batch_id}` to recall)*", reply_markup=tracker_markup)

async def schedule_auto_delete(client, user_id, msg_id, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try:
        await client.delete_messages(user_id, msg_id)
        await db.delete_single_broadcast_log(user_id, msg_id)
    except Exception:
        pass


# ==========================================
# 🧠 INTERACTIVE STATE WIZARD
# ==========================================
async def process_broadcast_command(client: Client, message: Message, target_msg: Message, command_text: str, prompt_msg_id: int = None):
    """Processes parameters to decide if it schedules, cancels, or executes a broadcast."""
    stop_match = re.search(r'-(?:stop|cancel)followup\s+(Batch_[A-Z0-9]+)', command_text, re.IGNORECASE)
    if stop_match:
        batch_id_to_cancel = stop_match.group(1).upper()
        success = await db.cancel_scheduled_broadcast(batch_id_to_cancel)
        text = f"✅ **Cancelled!** Scheduled broadcast `{batch_id_to_cancel}` has been deleted from the queue." if success else f"❌ **Failed:** Could not find a pending scheduled broadcast with ID `{batch_id_to_cancel}`."
        if prompt_msg_id:
            try: await client.edit_message_text(message.chat.id, prompt_msg_id, text)
            except Exception: await message.reply_text(text)
        else: await message.reply_text(text)
        return

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
                text = "❌ Scheduled time must be in the future."
                if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, text) 
                else: await message.reply_text(text)
                return
                
            await db.add_scheduled_broadcast(batch_id, message.chat.id, target_msg.id, run_at_ts, command_text)
            text = f"⏳ **Broadcast Scheduled!**\n\nBatch ID: `{batch_id}`\nWill auto-deploy at: `{raw_date}` (IST)\n*(Use `/cancelfollowup {batch_id}` to cancel)*"
            if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, text) 
            else: await message.reply_text(text)
            return
        except ValueError:
            text = "❌ Invalid date format. Please use `YYYY-MM-DD HH:MM`."
            if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, text)
            else: await message.reply_text(text)
            return

    await execute_broadcast_run(client, message.chat.id, target_msg, command_text, batch_id, prompt_msg_id)


@Client.on_message(filters.private & filters.user(Config.ADMINS), group=-3)
async def interactive_broadcast_listener(client: Client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in BROADCAST_STATE:
        raise ContinuePropagation

    if message.text and message.text.startswith("/"):
        del BROADCAST_STATE[user_id]
        raise ContinuePropagation

    state_data = BROADCAST_STATE[user_id]
    action = state_data["action"]
    prompt_msg_id = state_data["message_id"]
    timestamp = state_data["timestamp"]

    # 🛑 48-Hour Security Check (172,800 Seconds)
    if time.time() - timestamp > 172800:
        del BROADCAST_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please restart the setup."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation 

    if action == "broadcast_wait_msg":
        target_msg_id = message.id
        BROADCAST_STATE[user_id] = {
            "action": "broadcast_wait_params",
            "target_msg_id": target_msg_id,
            "message_id": prompt_msg_id,
            "timestamp": time.time()
        }
        text = (
            "✅ **Message Saved!**\n\n"
            "Now, send any parameters you want to apply (e.g., `-novip`, `-vip`, `-silent`, `-ask 10m`, or a schedule time like `2026-12-31 15:30`).\n\n"
            "*(Send `none` to deploy immediately without parameters)*"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast_flow")]])
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, text, reply_markup=markup)
        except Exception: pass

    elif action == "broadcast_wait_params":
        command_text = message.text.strip().lower() if message.text else ""
        if command_text == "none":
            command_text = ""
            
        target_msg_id = state_data["target_msg_id"]
        del BROADCAST_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        
        target_msg = await client.get_messages(message.chat.id, target_msg_id)
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, "🔄 **Processing your broadcast request...**")
        except Exception: pass
        
        await process_broadcast_command(client, message, target_msg, command_text, prompt_msg_id)

    elif action == "cancel_followup_wait":
        batch_id = message.text.strip()
        del BROADCAST_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        
        success = await db.cancel_scheduled_broadcast(batch_id)
        text = f"✅ **Cancelled!** Scheduled broadcast `{batch_id}` has been deleted from the queue." if success else f"❌ **Failed:** Could not find a pending scheduled broadcast with ID `{batch_id}`."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, text)
        except Exception: await message.reply_text(text)

    elif action == "broadcast_edit_wait_id":
        batch_id = message.text.strip()
        BROADCAST_STATE[user_id] = {
            "action": "broadcast_edit_wait_text",
            "batch_id": batch_id,
            "message_id": prompt_msg_id,
            "timestamp": time.time()
        }
        try: await message.delete()
        except Exception: pass
        
        text = f"📝 **Editing Batch: `{batch_id}`**\n\nPlease send the new text for this broadcast."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast_flow")]])
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, text, reply_markup=markup)
        except Exception: pass

    elif action == "broadcast_edit_wait_text":
        batch_id = state_data["batch_id"]
        new_text = message.text
        del BROADCAST_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, f"👻 **Deploying Ghost Update to `{batch_id}`...**")
        except Exception: pass
        
        edited = 0
        async for log in await db.get_broadcast_logs(batch_id):
            try:
                await client.edit_message_text(log["user_id"], log["message_id"], new_text)
                edited += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception: pass
                
        text = f"✅ **UPDATE COMPLETE**\n\nSilently edited `{edited}` messages."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, text)
        except Exception: await message.reply_text(text)

    raise StopPropagation


@Client.on_callback_query(filters.regex("^cancel_broadcast_flow$"))
async def cancel_broadcast_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BROADCAST_STATE:
        del BROADCAST_STATE[user_id]
    await callback.message.edit_text("❌ **Operation Cancelled.**\n\nYou can start over whenever you're ready.")
    await callback.answer("Cancelled", show_alert=False)

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
@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS))
async def ultimate_broadcast(client: Client, message: Message):
    if message.reply_to_message:
        target_msg = message.reply_to_message
        command_text = message.text.replace("/broadcast", "").strip().lower()
        await process_broadcast_command(client, message, target_msg, command_text)
    else:
        prompt = await message.reply_text(
            "📢 **Broadcast Wizard**\n\nPlease send or forward the message (text, photo, video) you want to broadcast.\n\n*(Or click Cancel to abort)*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast_flow")]])
        )
        BROADCAST_STATE[message.from_user.id] = {
            "action": "broadcast_wait_msg",
            "message_id": prompt.id,
            "timestamp": time.time()
        }
    
    raise StopPropagation

@Client.on_message(filters.command(["cancel_followup", "cancel_schedule", "stopfollowup", "cancelfollowup"]) & filters.user(Config.ADMINS))
async def cancel_scheduled_job(client: Client, message: Message):
    if len(message.command) < 2:
        prompt = await message.reply_text(
            "🛑 **Cancel Scheduled Broadcast**\n\nPlease send the **Batch ID** you want to cancel.\n\n*(Or click Cancel to abort)*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast_flow")]])
        )
        BROADCAST_STATE[message.from_user.id] = {
            "action": "cancel_followup_wait",
            "message_id": prompt.id,
            "timestamp": time.time()
        }
        raise StopPropagation 
        
    batch_id = message.command[1].strip()
    success = await db.cancel_scheduled_broadcast(batch_id)
    
    if success:
        await message.reply_text(f"✅ **Cancelled!** Scheduled broadcast `{batch_id}` has been deleted from the queue.")
    else:
        await message.reply_text(f"❌ **Failed:** Could not find a pending scheduled broadcast with ID `{batch_id}`.")
        
    raise StopPropagation 

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
        await status.edit_text(f"✅ **GHOST PROTOCOL COMPLETE**\n\n`{deleted}` messages from `{batch_id}` have been permanently erased from user chats.")
        raise StopPropagation 

    batches = await db.get_recent_batches()
    buttons = []
    async for batch in batches:
        b_id = batch["_id"]
        count = batch["count"]
        buttons.append([InlineKeyboardButton(f"🗑 Scrub {b_id} ({count} msgs)", callback_data=f"delbatch_{b_id}")])
        
    if not buttons:
        await message.reply_text("📂 The 48-Hour Vault is currently empty.")
        raise StopPropagation 
        
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text("🛡 **THE RECALL VAULT**\n\nSelect a recent batch to instantly delete it from all user inboxes:", reply_markup=reply_markup)
    raise StopPropagation 

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
        if len(parts) < 2:
            raise IndexError
        batch_id = parts[1]
        new_text = parts[2]
    except IndexError:
        if len(message.command) == 1:
            prompt = await message.reply_text(
                "👻 **Ghost Edit Wizard**\n\nPlease send the **Batch ID** you want to update.\n\n*(Or click Cancel to abort)*",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast_flow")]])
            )
            BROADCAST_STATE[message.from_user.id] = {
                "action": "broadcast_edit_wait_id",
                "message_id": prompt.id,
                "timestamp": time.time()
            }
            raise StopPropagation 
            
        await message.reply_text("⚠️ Format: `/broadcast_edit <Batch_ID> <New Text>`")
        raise StopPropagation 
        
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
    raise StopPropagation 

@Client.on_message(filters.command("user_broadcast") & filters.user(Config.ADMINS) & filters.reply)
async def direct_support(client: Client, message: Message):
    try:
        command_parts = message.text.split(" ", 2)
        if len(command_parts) < 2:
            await message.reply_text("⚠️ **Format:** `/user_broadcast <user_id> [-silent] [-ask 10m]`")
            raise StopPropagation 
            
        target_user = int(command_parts[1])
        command_text = command_parts[2].lower() if len(command_parts) > 2 else ""
        
        command_text = command_text.replace("—", "-").replace("–", "-") 
        is_silent = "-silent" in command_text
        
        ask_match = re.search(r'-ask\s+(\d+)([smh])', command_text)
        auto_delete_seconds = 0
        if ask_match:
            val = int(ask_match.group(1))
            unit = ask_match.group(2)
            if unit == 's': auto_delete_seconds = val
            elif unit == 'm': auto_delete_seconds = val * 60
            elif unit == 'h': auto_delete_seconds = val * 3600

        target_msg = message.reply_to_message
        
        base_text = ""
        if target_msg.text:
            base_text = target_msg.text.markdown if hasattr(target_msg.text, 'markdown') else str(target_msg.text)
        elif target_msg.caption:
            base_text = target_msg.caption.markdown if hasattr(target_msg.caption, 'markdown') else str(target_msg.caption)

        parsed_text, parsed_markup = parse_inline_buttons(base_text)
        
        final_markup = []
        if parsed_markup: final_markup.extend(parsed_markup.inline_keyboard)
        elif target_msg.reply_markup: final_markup.extend(target_msg.reply_markup.inline_keyboard)
            
        base_markup = InlineKeyboardMarkup(final_markup) if final_markup else None

        has_tags = "{first_name}" in parsed_text or "{last_name}" in parsed_text or "{full_name}" in parsed_text
        if has_tags:
            user_data = await db.users.find_one({"user_id": target_user}) or {}
            first_name_raw = user_data.get("first_name")
            last_name_raw = user_data.get("last_name")
            
            if not first_name_raw or first_name_raw == "User":
                try:
                    tg_user = await client.get_users(target_user)
                    first_name = tg_user.first_name or "User"
                    last_name = tg_user.last_name or ""
                except Exception:
                    first_name, last_name = "User", ""
            else:
                first_name = str(first_name_raw)
                last_name = str(last_name_raw) if last_name_raw else ""
                
            full_name = f"{first_name} {last_name}".strip()
            parsed_text = parsed_text.replace("{first_name}", first_name).replace("{last_name}", last_name).replace("{full_name}", full_name)

        if target_msg.media:
            sent_msg = await target_msg.copy(target_user, caption=parsed_text, disable_notification=is_silent, reply_markup=base_markup)
        else:
            sent_msg = await client.send_message(target_user, text=parsed_text, disable_notification=is_silent, reply_markup=base_markup)
            
        # 🚀 Save the Direct Message to the Vault so it can be deleted later!
        await db.log_broadcast("DIRECT_PM", target_user, sent_msg.id)
        
        confirm_text = f"✅ Securely dropped into `{target_user}`'s PMs."
        if auto_delete_seconds > 0:
            asyncio.create_task(schedule_auto_delete(client, target_user, sent_msg.id, auto_delete_seconds))
            confirm_text += f"\n*(Will auto-delete in {auto_delete_seconds}s)*"
            
        await message.reply_text(confirm_text)
        
    except StopPropagation:
        raise
    except ValueError:
        await message.reply_text("❌ Failed: Invalid User ID format.")
    except Exception as e:
        await message.reply_text(f"❌ Failed: `{e}`")
    raise StopPropagation 


@Client.on_message(filters.command("delbroadcastuser") & filters.user(Config.ADMINS))
async def surgical_wipe(client: Client, message: Message):
    try:
        # Check if the ID is missing so it doesn't crash with "list index out of range"
        if len(message.command) < 2:
            await message.reply_text("⚠️ **Format:** `/delbroadcastuser <user_id>`")
            raise StopPropagation
            
        target_user = int(message.command[1])
        latest_log = await db.get_user_latest_broadcast(target_user)
        
        if not latest_log:
            await message.reply_text("❌ No recent broadcasts found for this user in the vault.")
            raise StopPropagation 
            
        telegram_deleted = True
        try:
            await client.delete_messages(target_user, latest_log["message_id"])
        except Exception:
            telegram_deleted = False
            
        await db.delete_single_broadcast_log(target_user, latest_log["message_id"])
        
        if telegram_deleted:
            await message.reply_text(f"✅ **SURGICAL WIPE COMPLETE**\nThe last message was scrubbed from `{target_user}`'s chat and the database.")
        else:
            await message.reply_text(
                f"⚠️ **PARTIAL WIPE SUCCESSFUL**\n\n"
                f"Telegram blocked the physical deletion (the message is likely older than 48 hours or the user cleared their chat history).\n\n"
                f"However, the record has been **successfully permanently erased** from your database vault."
            )
            
    except StopPropagation:
        # Ignore Pyrogram's silent exit command so it doesn't print a blank error
        raise
    except ValueError:
        await message.reply_text("❌ **Failed:** Invalid User ID. Please provide a valid number.")
        raise StopPropagation
    except Exception as e:
        await message.reply_text(f"❌ **Failed:** `{e}`")
        raise StopPropagation
# ==========================================
# 💬 TWO-WAY BROADCAST COMMUNICATION
# ==========================================
@Client.on_message(filters.private & filters.reply & ~filters.user(Config.ADMINS))
async def handle_user_reply_to_broadcast(client: Client, message: Message):
    target_msg = message.reply_to_message
    
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
    raise StopPropagation 

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
        await message.reply_text("❌ **Could not detect User ID.**\nPlease reply to the '📩 New Reply' header.")
        raise StopPropagation 
        
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Format:** `/replybroadcast [-ask 10s] <your message>`")
        raise StopPropagation 
        
    raw_text = message.text.split(" ", 1)[1]
    
    # Sanitize Mobile Keyboards
    raw_text = raw_text.replace("—", "-").replace("–", "-")
    
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
        await message.reply_text("⚠️ You cannot send an empty message.")
        raise StopPropagation 
    
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
        
    raise StopPropagation
