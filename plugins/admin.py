import asyncio
import json
import logging
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

BROADCAST_QUEUE = asyncio.Queue()
BROADCAST_STATUS = {"total": 0, "processed": 0, "success": 0, "failed": 0, "is_running": False}

ADMIN_STATE = {}

@Client.on_message(filters.text & filters.private & filters.user(Config.ADMINS), group=0)
async def admin_input_catcher(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_STATE:
        raise ContinuePropagation 

    if message.text.startswith("/"):
        del ADMIN_STATE[user_id]
        raise ContinuePropagation

    state = ADMIN_STATE[user_id]
    user_input = message.text.strip()

    if state == "waiting_for_api":
        await db.update_settings({"shortener_api": user_input})
        del ADMIN_STATE[user_id]
        await message.reply_text("✅ **Success!** API Key updated in the database.\nType `/admin` to view.")
    
    elif state == "waiting_for_url":
        await db.update_settings({"shortener_url": user_input})
        del ADMIN_STATE[user_id]
        await message.reply_text("✅ **Success!** Shortener Link updated in the database.\nType `/admin` to view.")

@Client.on_message(filters.command("admin") & filters.user(Config.ADMINS))
async def admin_direct_command(client: Client, message: Message):
    await send_settings_home(message)

async def send_settings_home(message_or_query):
    text = "👑 **Bot Creator Control Panel**\n\nSelect a master module to configure:"
    buttons = [
        [InlineKeyboardButton("🔗 Shortener Settings", callback_data="set_shortener")],
        [InlineKeyboardButton("📝 Request Feature", callback_data="set_requests")],
        [InlineKeyboardButton("🔙 Back", callback_data="tier_root_fallback")]
    ]
    
    if isinstance(message_or_query, Message):
        await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message_or_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^(set_|toggle_requests)"))
async def settings_callbacks(client: Client, callback: CallbackQuery):
    action = callback.data
    user_id = callback.from_user.id

    if action == "set_home":
        if user_id in ADMIN_STATE: del ADMIN_STATE[user_id]
        await send_settings_home(callback)

    elif action == "set_shortener":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("shortener_enabled", False) else "🔴 OFF"
        api = settings.get("shortener_api", "Not Set")
        url = settings.get("shortener_url", "Not Set")

        text = (
            f"🔗 **Shortener Configurations**\n\n"
            f"**Status:** {status}\n"
            f"**Current URL:** `{url}`\n"
            f"**Current API:** `{api}`"
        )
        buttons = [
            [InlineKeyboardButton(f"Toggle Shortener {'OFF' if 'ON' in status else 'ON'}", callback_data="set_toggle")],
            [InlineKeyboardButton("✏️ Change API Key", callback_data="set_api")],
            [InlineKeyboardButton("✏️ Change Link", callback_data="set_url")],
            [InlineKeyboardButton("🔙 Back", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "set_toggle":
        settings = await db.get_settings()
        current_state = settings.get("shortener_enabled", False)
        await db.update_settings({"shortener_enabled": not current_state})
        callback.data = "set_shortener"
        await settings_callbacks(client, callback)

    elif action == "set_api":
        ADMIN_STATE[user_id] = "waiting_for_api"
        await callback.message.edit_text(
            "✏️ **Send the new API Key in the chat now.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_home")]])
        )

    elif action == "set_url":
        ADMIN_STATE[user_id] = "waiting_for_url"
        await callback.message.edit_text(
            "✏️ **Send the new URL Link in the chat now.**\n(Example: `https://gplinks.in/api`)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_home")]])
        )

    elif action == "set_requests":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("requests_enabled", True) else "🔴 OFF"
        text = (
            f"📝 **Movie Request Feature**\n\n"
            f"**Status:** {status}\n\n"
            f"When ON, users can use `/request` or click the button when a movie isn't found. "
            f"Requests will be delivered directly to the Admin DMs."
        )
        buttons = [
            [InlineKeyboardButton(f"Toggle Requests {'OFF' if 'ON' in status else 'ON'}", callback_data="toggle_requests")],
            [InlineKeyboardButton("🔙 Back", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "toggle_requests":
        settings = await db.get_settings()
        current_state = settings.get("requests_enabled", True)
        await db.update_settings({"requests_enabled": not current_state})
        callback.data = "set_requests"
        await settings_callbacks(client, callback)

async def process_broadcast_queue(client: Client):
    global BROADCAST_STATUS
    while not BROADCAST_QUEUE.empty():
        msg_to_copy, target_user = await BROADCAST_QUEUE.get()
        try:
            await msg_to_copy.copy(chat_id=target_user)
            BROADCAST_STATUS["success"] += 1
        except Exception: BROADCAST_STATUS["failed"] += 1
        finally:
            BROADCAST_STATUS["processed"] += 1
            BROADCAST_QUEUE.task_done()
            await asyncio.sleep(0.05) 
    BROADCAST_STATUS["is_running"] = False

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'KB', 2: 'MB', 3: 'GB'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def format_eta(seconds):
    """Converts raw seconds into a human-readable Days, Hours, Minutes format."""
    if seconds <= 0:
        return "🎉 Fully Processed!"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    
    eta_strings = []
    if days > 0:
        eta_strings.append(f"{int(days)}d")
    if hours > 0:
        eta_strings.append(f"{int(hours)}h")
    if minutes > 0:
        eta_strings.append(f"{int(minutes)}m")
        
    return " ".join(eta_strings) if eta_strings else "< 1 minute"

@Client.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def bot_stats_dashboard(client: Client, message: Message):
    status_msg = await message.reply_text("📊 **Aggregating multi-shard metadata & queue stats...**")
    db_stats = await db.global_stats()
    
    used_space = format_bytes(db_stats.get("total_size_bytes", 0))
    left_space = format_bytes(db_stats.get("space_left_bytes", 0))
    shards_text = "".join([f"• **Shard {idx + 1}**: `{count}` files\n" for idx, count in enumerate(db_stats.get("shard_distribution", []))])
    
    total_files = db_stats.get('total_files', 0)
    indexed_meta = db_stats.get('indexed_metadata', 0)
    pending_meta = total_files - indexed_meta
    
    # ==========================================
    # WORKER 1: MASS INDEXING QUEUE ETA
    # ==========================================
    active_job = await db.get_active_job()
    if active_job:
        target = active_job.get("chat_name", "Unknown")
        total_msgs = active_job.get("start_id", 0)
        left_msgs = max(0, active_job.get("current_id", 0))
        scanned = active_job.get("scanned", 0)
        saved = active_job.get("saved", 0)
        
        idx_pct = (scanned / total_msgs * 100) if total_msgs > 0 else 0
        
        # Math: 6 seconds per batch of 200 messages (5s sleep + 1s API)
        idx_eta_seconds = (left_msgs / 200) * 6.0
        idx_eta_string = format_eta(idx_eta_seconds)
        
        indexing_text = (
            f"🔄 **Status:** `Active`\n"
            f"• **Channel:** `{target}`\n"
            f"• **Progress:** `{scanned:,}` / `{total_msgs:,}` (`{idx_pct:.1f}%`)\n"
            f"• **Files Saved:** `{saved:,}`\n"
            f"• **ETA:** `{idx_eta_string}`"
        )
    else:
        indexing_text = "💤 **Status:** `Idle (Queue Empty)`\n• No active `/index` jobs."

    # ==========================================
    # WORKER 2: METADATA EXTRACTION ETA
    # ==========================================
    # Math: 4 seconds sleep + 1.5 seconds metadata overhead
    meta_eta_seconds = pending_meta * 5.5 
    meta_eta_string = format_eta(meta_eta_seconds)
    meta_pct = (indexed_meta / total_files * 100) if total_files > 0 else 100

    dashboard_text = (
        f"📊 **Advanced System Status Dashboard**\n\n"
        f"🗂️ **Total Indexed Files:** `{total_files:,}`\n"
        f"💾 **Space Used:** `{used_space}` | **Remaining:** `{left_space}`\n\n"
        f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
        f"{indexing_text}\n\n"
        f"⚙️ **WORKER 2: Metadata Extraction**\n"
        f"• **Extracted:** `{indexed_meta:,}` / `{total_files:,}` (`{meta_pct:.1f}%`)\n"
        f"• **Pending:** `{pending_meta:,}` files\n"
        f"• **ETA:** `{meta_eta_string}`\n\n"
        f"🖲️ **Shard Distribution:**\n{shards_text}"
    )
    await status_msg.edit_text(dashboard_text)

@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS))
async def queue_broadcast_init(client: Client, message: Message):
    if not message.reply_to_message: return await message.reply_text("❌ Reply to a message with `/broadcast`")
    if BROADCAST_STATUS["is_running"]: return await message.reply_text("⚠️ A broadcast is running.")

    subscribers = [message.from_user.id] 
    BROADCAST_STATUS.update({"total": len(subscribers), "processed": 0, "success": 0, "failed": 0, "is_running": True})
    for user_id in subscribers: await BROADCAST_QUEUE.put((message.reply_to_message, user_id))
    asyncio.create_task(process_broadcast_queue(client))
    await message.reply_text("🚀 **Broadcast initiated!**")

@Client.on_message(filters.command("backup") & filters.user(Config.ADMINS))
async def multi_shard_json_backup(client: Client, message: Message):
    progress = await message.reply_text("📥 **Connecting to database Shard 0...**")
    try:
        cursor = db.collections[0].find({}).limit(1000)
        documents = await cursor.to_list(length=1000)
        for doc in documents: doc["_id"] = str(doc["_id"])
        with open("shard0_backup.json", "w") as f: json.dump(documents, f, indent=4)
        await message.reply_document("shard0_backup.json", caption=f"📦 **Backup Export**\nProcessed `{len(documents)}` files.")
        await progress.delete()
    except Exception as e: await progress.edit_text(f"❌ **Schema Export Failed:** `{str(e)}`")

# ==========================================================
# THE ONE-TIME DATABASE MIGRATION TOOL
# ==========================================================
@Client.on_message(filters.command("migrate_db") & filters.user(Config.ADMINS))
async def migrate_old_database(client: Client, message: Message):
    status = await message.reply_text("🔄 **Starting Database Migration...**\nTagging old files for the background worker.")
    
    total_updated = 0
    try:
        # Loop through all your Shards
        for coll in db.collections:
            # Find files that DO NOT have a language field, and set them to "pending"
            result = await coll.update_many(
                {"language": {"$exists": False}},
                {"$set": {"language": "pending"}}
            )
            total_updated += result.modified_count
            
        await status.edit_text(f"✅ **Migration Complete!**\n\nSuccessfully tagged `{total_updated:,}` old files.\nThe Background Worker will now begin processing them silently!")
    except Exception as e:
        await status.edit_text(f"❌ **Migration Failed:** `{str(e)}`")
