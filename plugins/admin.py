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

    # --- THE NEW SETUP WIZARD STATES ---
    if state == "setup_shortener_url":
        await db.update_settings({"shortener_url": user_input})
        ADMIN_STATE[user_id] = "setup_shortener_api"
        await message.reply_text("✅ **URL Saved!**\n\nNow, please send me your secret **API Key** for this shortener.")
        
    elif state == "setup_shortener_api":
        await db.update_settings({"shortener_api": user_input, "shortener_enabled": True})
        del ADMIN_STATE[user_id]
        await message.reply_text("✅ **Success!** API Key saved and Shortener is now **🟢 ON**.\nType `/admin` to view.")

    # --- THE EXISTING EDIT STATES ---
    elif state == "waiting_for_api":
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
        
        # THE FIX: If ON, turn it off. If OFF, start the Setup Wizard!
        if current_state:
            await db.update_settings({"shortener_enabled": False})
            callback.data = "set_shortener"
            await settings_callbacks(client, callback)
        else:
            ADMIN_STATE[user_id] = "setup_shortener_url"
            await callback.message.edit_text(
                "🛠 **Shortener Setup Wizard**\n\n"
                "To enable the shortener, please send me the **Shortener URL** in the chat now.\n"
                "(Example: `https://gplinks.in/api`)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_home")]])
            )

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
    if seconds <= 0: return "🎉 Fully Processed!"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    eta_strings = []
    if days > 0: eta_strings.append(f"{int(days)}d")
    if hours > 0: eta_strings.append(f"{int(hours)}h")
    if minutes > 0: eta_strings.append(f"{int(minutes)}m")
    return " ".join(eta_strings) if eta_strings else "< 1 minute"

# ==========================================================
# 📊 MAIN STATS DASHBOARD GENERATORS
# ==========================================================

async def get_stats_home_text_and_buttons():
    db_stats = await db.global_stats()
    
    used_space = format_bytes(db_stats.get("total_size_bytes", 0))
    left_space = format_bytes(db_stats.get("space_left_bytes", 0))
    shards_text = "".join([f"• **Shard {idx + 1}**: `{count:,}` files\n" for idx, count in enumerate(db_stats.get("shard_distribution", []))])
    total_files = db_stats.get('total_files', 0)
    
    text = (
        f"📊 **Advanced System Status Dashboard**\n\n"
        f"🗂️ **Total Indexed Files:** `{total_files:,}`\n\n"
        f"💾 **Storage Analytics:**\n"
        f"• **Space Used:** `{used_space}`\n"
        f"• **Space Remaining:** `{left_space}`\n"
        f"• **Estimated Capacity Left:** `~{db_stats.get('estimated_files_left', 0):,} files`\n\n"
        f"🖲️ **Shard Distribution:**\n{shards_text}"
    )
    
    buttons = [
        [
            InlineKeyboardButton("⚙️ Worker 1: Indexing", callback_data="stats_worker1"),
            InlineKeyboardButton("⚙️ Worker 2: Metadata", callback_data="stats_worker2")
        ],
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="stats_refresh_home")]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker1_text_and_buttons():
    active_job = await db.get_active_job()
    
    if active_job:
        target = active_job.get("chat_name", "Unknown Channel")
        scanned = active_job.get("scanned", 0)
        current = active_job.get("current_id", 0)
        left = max(0, current)
        total_msgs = active_job.get("start_id", 0) or (scanned + left)
        
        saved = active_job.get("saved", 0)
        duplicates = active_job.get("duplicates", 0) or active_job.get("duplicates_skipped", 0)
        non_media = active_job.get("non_media", 0) or active_job.get("text_skipped", 0)
        
        idx_pct = (scanned / total_msgs * 100) if total_msgs > 0 else 0
        idx_eta_seconds = (left / 200) * 6.0
        idx_eta_string = format_eta(idx_eta_seconds)
        
        text = (
            f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
            f"🔄 **Status:** `Active (Deep Scan in Progress...)`\n\n"
            f"• **Target Channel:** `{target}`\n"
            f"• **Scanned:** `{scanned:,}` | **Left:** `{left:,}`\n"
            f"• **Total Progress:** `{scanned:,}` / `{total_msgs:,}` (`{idx_pct:.1f}%`)\n"
            f"• **Estimated Time Left:** `{idx_eta_string}`\n\n"
            f"📂 **Content Deep-Breakdown:**\n"
            f"• **New Media Saved:** `{saved:,}`\n"
            f"• **Duplicates Skipped:** `{duplicates:,}`\n"
            f"• **Text / Non-Media Skipped:** `{non_media:,}`"
        )
    else:
        text = (
            f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
            f"💤 **Status:** `Idle (Queue Empty)`\n\n"
            f"No active mass channel indexing tasks are currently running in the background queue."
        )
        
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w1")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker2_text_and_buttons():
    db_stats = await db.global_stats()
    total_files = db_stats.get('total_files', 0)
    indexed_meta = db_stats.get('indexed_metadata', 0)
    pending_meta = total_files - indexed_meta
    
    meta_eta_seconds = pending_meta * 5.5 
    meta_eta_string = format_eta(meta_eta_seconds)
    meta_pct = (indexed_meta / total_files * 100) if total_files > 0 else 100
    
    text = (
        f"⚙️ **WORKER 2: Language & Metadata Extraction**\n"
        f"🔄 **Status:** `Processing Database Shards...`\n\n"
        f"• **Extracted Files:** `{indexed_meta:,}` / `{total_files:,}`\n"
        f"• **Current Progress:** `{meta_pct:.1f}%` complete\n"
        f"• **Pending Migration Queue:** `{pending_meta:,}` files left\n"
        f"• **Estimated Completion Time (ETA):** `{meta_eta_string}`\n\n"
        f"💡 *Note: This background process routes with a safety buffer delay to avoid hitting Telegram flood limits.*"
    )
    
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w2")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

# ==========================================================
# 🔌 PYROGRAM ROUTERS & EVENT HANDLERS
# ==========================================================

@Client.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def bot_stats_dashboard(client: Client, message: Message):
    status_msg = await message.reply_text("📊 **Querying core analytics engine...**")
    text, markup = await get_stats_home_text_and_buttons()
    await status_msg.edit_text(text, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"^stats_"))
async def stats_callback_handler(client: Client, callback: CallbackQuery):
    action = callback.data
    try:
        if action == "stats_home":
            text, markup = await get_stats_home_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
        elif action == "stats_worker1":
            text, markup = await get_worker1_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
        elif action == "stats_worker2":
            text, markup = await get_worker2_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
        elif action in ["stats_refresh_home", "stats_refresh_w1", "stats_refresh_w2"]:
            await callback.answer("🔄 Metrics synchronized successfully!", show_alert=False)
            if action == "stats_refresh_home":
                text, markup = await get_stats_home_text_and_buttons()
            elif action == "stats_refresh_w1":
                text, markup = await get_worker1_text_and_buttons()
            else:
                text, markup = await get_worker2_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error handling stats inline navigation: {e}")
        await callback.answer("⚠️ Processing sync issue. Try running /stats again.", show_alert=True)

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

@Client.on_message(filters.command("migrate_db") & filters.user(Config.ADMINS))
async def migrate_old_database(client: Client, message: Message):
    status = await message.reply_text("🔄 **Starting Database Migration...**\nTagging old files for the background worker.")
    total_updated = 0
    try:
        for coll in db.collections:
            result = await coll.update_many(
                {"language": {"$exists": False}},
                {"$set": {"language": "pending"}}
            )
            total_updated += result.modified_count
        await status.edit_text(f"✅ **Migration Complete!**\n\nSuccessfully tagged `{total_updated:,}` old files.\nThe Background Worker will now begin processing them silently!")
    except Exception as e:
        await status.edit_text(f"❌ **Migration Failed:** `{str(e)}`")
