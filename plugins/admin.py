import asyncio
import json
import logging
import time
import datetime  # 🚀 NEW: Required for converting timestamps into readable dates
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

START_TIME = time.time()

# 🧠 Upgraded State Machine: Now remembers message IDs for clean UI editing
ADMIN_STATE = {}

@Client.on_message(filters.text & filters.private & filters.user(Config.ADMINS), group=0)
async def admin_input_catcher(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_STATE:
        raise ContinuePropagation 

    if message.text.startswith("/"):
        del ADMIN_STATE[user_id]
        raise ContinuePropagation

    # Extract state and the original prompt message ID
    state_data = ADMIN_STATE[user_id]
    if isinstance(state_data, dict):
        state = state_data["state"]
        prompt_msg_id = state_data.get("msg_id")
    else:
        state = state_data
        prompt_msg_id = None

    user_input = message.text.strip()

    # 🚀 THE UX UPGRADE: Auto-delete user text and beautifully edit the prompt
    async def finish_input(success_text, back_callback="set_home"):
        del ADMIN_STATE[user_id]
        try:
            await message.delete() # Deletes the user's messy text reply!
        except Exception:
            pass
        
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data=back_callback)]])
        if prompt_msg_id:
            try:
                await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=success_text, reply_markup=markup)
            except Exception:
                await message.reply_text(success_text, reply_markup=markup)
        else:
            await message.reply_text(success_text, reply_markup=markup)

    # Apply the clean UX to all inputs
    if state == "setup_inside_words":
        words = [w.strip() for w in user_input.split() if w.strip()]
        await db.update_settings({"inside_words": words})
        await finish_input(f"✅ **Words Saved!**\n`{words}`", "set_inside")

    elif state == "setup_inside_times":
        if user_input.isdigit():
            await db.update_settings({"inside_times": int(user_input)})
            await finish_input(f"✅ **Times Saved:** `{user_input}` per day.", "set_inside")
        else:
            await message.reply_text("❌ **Invalid Input!** Please send only a number (e.g., `4`).")

    elif state == "setup_inside_channels":
        channels = [c.strip() for c in user_input.split() if c.strip()]
        await db.update_settings({"inside_channels": channels})
        await finish_input(f"✅ **Channels Saved!**\n`{channels}`", "set_inside")

    elif state == "setup_shortener_url":
        await db.update_settings({"shortener_url": user_input})
        ADMIN_STATE[user_id] = {"state": "setup_shortener_api", "msg_id": prompt_msg_id}
        try: 
            await message.delete() 
        except Exception: 
            pass
        
        text = "✅ **URL Saved!**\n\nNow, please send me your secret **API Key** for this shortener."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]])
        
        if prompt_msg_id:
            try: 
                await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=text, reply_markup=markup)
            except Exception: 
                msg = await message.reply_text(text, reply_markup=markup)
                ADMIN_STATE[user_id]["msg_id"] = msg.id
        else:
            msg = await message.reply_text(text, reply_markup=markup)
            ADMIN_STATE[user_id]["msg_id"] = msg.id

    elif state == "setup_shortener_api":
        await db.update_settings({"shortener_api": user_input, "shortener_enabled": True})
        await finish_input("✅ **Success!** API Key saved and Shortener is now **🟢 ON**.", "set_shortener")

    elif state == "waiting_for_api":
        await db.update_settings({"shortener_api": user_input})
        await finish_input("✅ **Success!** API Key updated in the database.", "set_shortener")

    elif state == "waiting_for_url":
        await db.update_settings({"shortener_url": user_input})
        await finish_input("✅ **Success!** Shortener Link updated in the database.", "set_shortener")

    elif state == "setup_file_time":
        if user_input.isdigit():
            await db.update_settings({"file_delete_time": int(user_input)})
            await finish_input(f"✅ **File Delete Time Saved:** `{user_input} Minutes`", "set_autodelete")
        else:
            await message.reply_text("❌ **Invalid Input!** Please send only a number in minutes (e.g., `30`).")

    elif state == "setup_filter_time":
        if user_input.isdigit():
            await db.update_settings({"filter_delete_time": int(user_input)})
            await finish_input(f"✅ **Filter Delete Time Saved:** `{user_input} Minutes`", "set_autodelete")
        else:
            await message.reply_text("❌ **Invalid Input!** Please send only a number in minutes (e.g., `5`).")


@Client.on_message(filters.command("admin") & filters.user(Config.ADMINS))
async def admin_direct_command(client: Client, message: Message):
    await send_settings_home(message)

async def send_settings_home(message_or_query):
    text = "👑 **Bot Creator Control Panel**\n\nSelect a master module to configure:"
    buttons = [
        [InlineKeyboardButton("🔗 Shortener Settings", callback_data="set_shortener")],
        [InlineKeyboardButton("📝 Request Feature", callback_data="set_requests")],
        [InlineKeyboardButton("🕵️‍♂️ Inside Settings", callback_data="set_inside")], 
        [InlineKeyboardButton("🗑 Auto-Delete Filters", callback_data="set_autodelete")],
        [InlineKeyboardButton("🔙 Exit", callback_data="tier_root_fallback")]
    ]

    if isinstance(message_or_query, Message):
        await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message_or_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^(set_|toggle_|inside_|time_)"))
async def settings_callbacks(client: Client, callback: CallbackQuery):
    action = callback.data
    user_id = callback.from_user.id

    if action in ["set_home", "set_inside", "set_shortener", "set_requests", "set_autodelete"]:
        if user_id in ADMIN_STATE:
            del ADMIN_STATE[user_id]

    if action == "set_home":
        await send_settings_home(callback)

    elif action == "set_inside":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("inside_enabled", False) else "🔴 OFF"
        words = settings.get("inside_words", [])
        times = settings.get("inside_times", 5)
        channels = settings.get("inside_channels", [])
        placement = settings.get("inside_placement", "movie").capitalize()

        text = (
            f"🕵️‍♂️ **Inside Task Settings**\n\n"
            f"**Status:** {status}\n"
            f"**Trigger Words:** `{', '.join(words) if words else 'None Set'}`\n"
            f"**Pass Limit:** `{times} times/day`\n"
            f"**Target Channels:** `{', '.join(channels) if channels else 'None Set'}`\n"
            f"**Placement Module:** `{placement}`\n\n"
            f"Use the buttons below to modify the task verification flow:"
        )
        buttons = [
            [InlineKeyboardButton(f"Toggle Feature {'OFF' if 'ON' in status else 'ON'}", callback_data="inside_toggle")],
            [InlineKeyboardButton("📝 Edit Words", callback_data="inside_words"), InlineKeyboardButton("⏱ Edit Times", callback_data="inside_times")],
            [InlineKeyboardButton("📢 Edit Channels", callback_data="inside_channels")],
            [InlineKeyboardButton(f"🔄 Placement: {placement}", callback_data="inside_placement")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "inside_toggle":
        settings = await db.get_settings()
        current = settings.get("inside_enabled", False)
        await db.update_settings({"inside_enabled": not current})
        callback.data = "set_inside"
        await settings_callbacks(client, callback)

    elif action == "inside_words":
        ADMIN_STATE[user_id] = {"state": "setup_inside_words", "msg_id": callback.message.id}
        await callback.message.edit_text(
            "✏️ **Send the trigger words in the chat.**\nSeparate them with spaces (e.g., `#example1 #sponsor2`).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]])
        )

    elif action == "inside_times":
        ADMIN_STATE[user_id] = {"state": "setup_inside_times", "msg_id": callback.message.id}
        await callback.message.edit_text(
            "✏️ **Send the number of verifications per day.**\n(Example: Send `4` to require verification every 6 hours).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]])
        )

    elif action == "inside_channels":
        ADMIN_STATE[user_id] = {"state": "setup_inside_channels", "msg_id": callback.message.id}
        await callback.message.edit_text(
            "✏️ **Send the Target Channel Usernames or IDs.**\nSeparate multiple with spaces (e.g., `-10012345 @MyChannel`).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]])
        )

    elif action == "inside_placement":
        settings = await db.get_settings()
        current_placement = settings.get("inside_placement", "movie")

        if current_placement == "movie":
            nxt = "request"
        elif current_placement == "request":
            nxt = "welcome"
        else:
            nxt = "movie"

        await db.update_settings({"inside_placement": nxt})
        callback.data = "set_inside"
        await settings_callbacks(client, callback)

    elif action == "set_shortener":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("shortener_enabled", False) else "🔴 OFF"
        api = settings.get("shortener_api", "Not Set")
        url = settings.get("shortener_url", "Not Set")

        text = (
            f"🔗 **Shortener Configurations**\n\n"
            f"**Status:** {status}\n"
            f"**Current URL Template:** `{url}`\n"
            f"**Current API Key:** `{api}`\n\n"
            f"📖 **How to Setup Your Shortener:**\n\n"
            f"⚡ **Method 1: Auto-Setup (Recommended)**\n"
            f"Just send `/setshort <your_full_link>` directly in the chat.\n"
            f"*(The bot will extract your key and format the template!)*\n\n"
            f"🛠 **Method 2: Manual Setup**\n"
            f"1. Click **Toggle Shortener** to turn it ON/OFF.\n"
            f"2. Click **Change API Key** and send your secret key.\n"
            f"3. Click **Change Link** and send your exact URL format.\n"
            f"⚠️ *Important: You must use `{{api}}` and `{{url}}` as placeholders in your manual link!*"
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

        if current_state:
            await db.update_settings({"shortener_enabled": False})
        else:
            ADMIN_STATE[user_id] = {"state": "setup_shortener_url", "msg_id": callback.message.id}
            return await callback.message.edit_text(
                "🛠 **Shortener Setup Wizard**\n\n"
                "To enable the shortener, please send me the **Shortener URL** in the chat now.\n"
                "(Example: `https://gplinks.in/api?api={api}&url={url}`)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]])
            )
            
        callback.data = "set_shortener"
        await settings_callbacks(client, callback)

    elif action == "set_api":
        ADMIN_STATE[user_id] = {"state": "waiting_for_api", "msg_id": callback.message.id}
        await callback.message.edit_text(
            "✏️ **Send the new API Key in the chat now.**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]])
        )

    elif action == "set_url":
        ADMIN_STATE[user_id] = {"state": "waiting_for_url", "msg_id": callback.message.id}
        await callback.message.edit_text(
            "✏️ **Send the new URL Link template in the chat now.**\n\n"
            "💡 *Tip: Use `{api}` and `{url}` as placeholders! The bot will automatically inject your key and the movie link here.*\n"
            "(Example: `https://gplinks.in/api?api={api}&url={url}`)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]])
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

    elif action == "set_autodelete":
        settings = await db.get_settings()
        f_status = "🟢 ON" if settings.get("file_delete_enabled", False) else "🔴 OFF"
        m_status = "🟢 ON" if settings.get("filter_delete_enabled", False) else "🔴 OFF"
        f_time = settings.get("file_delete_time", 10)
        m_time = settings.get("filter_delete_time", 5)

        text = (
            f"🗑 **Auto-Delete (Ghost Mode) Settings**\n\n"
            f"📂 **File Deletion:** {f_status} `({f_time} mins)`\n"
            f"*Deletes actual movie files after delivery.*\n\n"
            f"🔍 **Search Filter Deletion:** {m_status} `({m_time} mins)`\n"
            f"*Deletes movie search result messages.*\n\n"
            f"*(Note: Timers over 1440 mins/24 hrs may be interrupted by server restarts).* "
        )
        buttons = [
            [
                InlineKeyboardButton(f"Files: {f_status}", callback_data="toggle_file_del"),
                InlineKeyboardButton(f"Filters: {m_status}", callback_data="toggle_filter_del")
            ],
            [
                InlineKeyboardButton("⏱ Set File Time", callback_data="time_file_del"),
                InlineKeyboardButton("⏱ Set Filter Time", callback_data="time_filter_del")
            ],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "toggle_file_del":
        settings = await db.get_settings()
        await db.update_settings({"file_delete_enabled": not settings.get("file_delete_enabled", False)})
        callback.data = "set_autodelete"
        await settings_callbacks(client, callback)

    elif action == "toggle_filter_del":
        settings = await db.get_settings()
        await db.update_settings({"filter_delete_enabled": not settings.get("filter_delete_enabled", False)})
        callback.data = "set_autodelete"
        await settings_callbacks(client, callback)

    elif action == "time_file_del":
        ADMIN_STATE[user_id] = {"state": "setup_file_time", "msg_id": callback.message.id}
        await callback.message.edit_text("✏️ **Send the File Auto-Delete time in MINUTES.**\n(e.g., `30` for 30 minutes).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_autodelete")]]))

    elif action == "time_filter_del":
        ADMIN_STATE[user_id] = {"state": "setup_filter_time", "msg_id": callback.message.id}
        await callback.message.edit_text("✏️ **Send the Search Result Auto-Delete time in MINUTES.**\n(e.g., `5` for 5 minutes).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_autodelete")]]))

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

def format_uptime(seconds):
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, sec = divmod(remainder, 60)
    parts = []
    if days: parts.append(f"{int(days)}d")
    if hours: parts.append(f"{int(hours)}h")
    if minutes: parts.append(f"{int(minutes)}m")
    parts.append(f"{int(sec)}s")
    return " ".join(parts) if parts else "Just started"

# ==========================================
# 📊 STATS DASHBOARD GENERATORS
# ==========================================

async def get_stats_home_text_and_buttons():
    db_stats = await db.global_stats()

    used_space = format_bytes(db_stats.get("total_size_bytes", 0))
    left_space = format_bytes(db_stats.get("space_left_bytes", 0))
    shards_text = "".join([f"• **Shard {idx + 1}**: `{count:,}` files\n" for idx, count in enumerate(db_stats.get("shard_distribution", []))])
    total_files = db_stats.get('total_files', 0)
    
    uptime_seconds = time.time() - START_TIME
    uptime_string = format_uptime(uptime_seconds)

    text = (
        f"📊 **Advanced System Status Dashboard**\n\n"
        f"⏱️ **Bot Uptime:** `{uptime_string}`\n"
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
        [
            InlineKeyboardButton("⚙️ Worker 3: Broadcast Engine", callback_data="stats_worker3_home")
        ],
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="stats_refresh_home")]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker1_text_and_buttons():
    active_job = await db.get_active_job()

    if active_job:
        target = active_job.get("chat_name", "Unknown Channel")
        scanned = active_job.get("scanned", 0)
        saved = active_job.get("saved", 0)
        duplicates = active_job.get("duplicates", 0)
        
        current_id = active_job.get("current_id", 0)

        remaining = max(0, current_id)
        total_msgs = scanned + remaining
        idx_pct = round((scanned / total_msgs * 100), 2) if total_msgs > 0 else 0.0

        skipped_empty = scanned - (saved + duplicates)
        if skipped_empty < 0:
            skipped_empty = 0

        if remaining <= 0:
            status_text = "✅ Completed (Sleeping)"
            idx_eta_string = "🎉 Fully Processed!"
        else:
            status_text = "🔄 Active (Deep Scan in Progress...)"
            idx_eta_seconds = remaining * 0.4  
            idx_eta_string = format_eta(idx_eta_seconds)

        text = (
            f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
            f"🔄 **Status:** `{status_text}`\n\n"
            f"• **Target Channel:** `{target}`\n"
            f"• **Scanned:** `{scanned:,}` | **Remaining to Scan:** `{remaining:,}`\n"
            f"• **Total Progress:** `{scanned:,}` / `{total_msgs:,}` (`{idx_pct}%`)\n"
            f"• **Estimated Time Left:** `{idx_eta_string}`\n\n"
            f"📂 **Content Deep-Breakdown:**\n"
            f"• **New Media Saved:** `{saved:,}`\n"
            f"• **Duplicates Skipped:** `{duplicates:,}`\n"
            f"• **Deleted / Empty Skipped:** `{skipped_empty:,}`"
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
    
    corrupted_count = 0
    for coll in db.collections:
        corrupted_count += await coll.count_documents({"language": "unknown"})

    meta_eta_seconds = pending_meta * 5.5 
    meta_eta_string = format_eta(meta_eta_seconds)
    meta_pct = (indexed_meta / total_files * 100) if total_files > 0 else 100

    text = (
        f"⚙️ **WORKER 2: Language & Metadata Extraction**\n"
        f"🔄 **Status:** `Processing Database Shards...`\n\n"
        f"• **Extracted Files:** `{indexed_meta:,}` / `{total_files:,}`\n"
        f"• **Corrupted / Skipped:** `{corrupted_count:,}` files\n"
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

# 🚀 NEW WORKER 3 DASHBOARD
async def get_worker3_home_text_and_buttons():
    pending_count = await db.scheduled_broadcasts.count_documents({"status": "pending"})
    
    forty_eight_hours_ago = time.time() - (48 * 3600)
    vault_count = await db.broadcast_logs.count_documents({"timestamp": {"$gte": forty_eight_hours_ago}})
    
    text = (
        f"⚙️ **WORKER 3: Broadcast & Scheduler Engine**\n"
        f"🔄 **Status:** `Active & Monitoring`\n\n"
        f"📊 **Engine Overview:**\n"
        f"• **Pending Scheduled Jobs:** `{pending_count}`\n"
        f"• **Messages in 48H Vault:** `{vault_count}`\n\n"
        f"Select an option below to view detailed tracking analytics:"
    )
    buttons = [
        [
            InlineKeyboardButton("📅 Scheduled Queue", callback_data="stats_worker3_sched"),
            InlineKeyboardButton("📡 Recent Batches", callback_data="stats_worker3_recent")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_home")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker3_sched_text_and_buttons():
    cursor = db.scheduled_broadcasts.find({"status": "pending"}).sort("run_at", 1).limit(5)
    schedules = await cursor.to_list(length=5)
    
    total_pending = await db.scheduled_broadcasts.count_documents({"status": "pending"})
    
    text = f"📅 **SCHEDULED BROADCAST QUEUE**\n\n**Total Pending Jobs:** `{total_pending}`\n\n"
    
    if not schedules:
        text += "No broadcasts are currently scheduled."
    else:
        text += "**Next 5 Upcoming Broadcasts:**\n"
        ist_timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        
        for s in schedules:
            dt = datetime.datetime.fromtimestamp(s["run_at"], ist_timezone)
            time_str = dt.strftime('%Y-%m-%d %I:%M %p')
            text += f"• `{s['batch_id']}` - ⏳ `{time_str}`\n"
            
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_worker3_home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_sched")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker3_recent_text_and_buttons():
    batches_cursor = await db.get_recent_batches()
    
    text = f"📡 **RECENT BROADCAST BATCHES (48H Vault)**\n\n"
    has_batches = False
    
    async for batch in batches_cursor:
        has_batches = True
        b_id = batch["_id"]
        count = batch["count"]
        text += f"• **{b_id}**: `{count} messages sent`\n"
        
    if not has_batches:
        text += "No broadcasts sent in the last 48 hours."
    else:
        text += "\n*(Use `/broadcast_del` to manage these)*"
        
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_worker3_home"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_recent")
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

# ==========================================
# 📊 STATS CALLBACK ROUTER
# ==========================================
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
            
        # 🚀 NEW WORKER 3 ROUTING
        elif action == "stats_worker3_home":
            text, markup = await get_worker3_home_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
        elif action == "stats_worker3_sched":
            text, markup = await get_worker3_sched_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
        elif action == "stats_worker3_recent":
            text, markup = await get_worker3_recent_text_and_buttons()
            await callback.message.edit_text(text, reply_markup=markup)
            
        # REFRESH HANDLERS
        elif action in ["stats_refresh_home", "stats_refresh_w1", "stats_refresh_w2", "stats_refresh_w3_home", "stats_refresh_w3_sched", "stats_refresh_w3_recent"]:
            await callback.answer("🔄 Metrics synchronized successfully!", show_alert=False)
            if action == "stats_refresh_home":
                text, markup = await get_stats_home_text_and_buttons()
            elif action == "stats_refresh_w1":
                text, markup = await get_worker1_text_and_buttons()
            elif action == "stats_refresh_w2":
                text, markup = await get_worker2_text_and_buttons()
            elif action == "stats_refresh_w3_home":
                text, markup = await get_worker3_home_text_and_buttons()
            elif action == "stats_refresh_w3_sched":
                text, markup = await get_worker3_sched_text_and_buttons()
            elif action == "stats_refresh_w3_recent":
                text, markup = await get_worker3_recent_text_and_buttons()
                
            await callback.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error handling stats inline navigation: {e}")
        await callback.answer("⚠️ Processing sync issue. Try running /stats again.", show_alert=True)

# ==========================================
# ⚙️ ADMIN COMMANDS
# ==========================================
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

@Client.on_message(filters.command("optimize_db") & filters.user(Config.ADMINS))
async def trigger_db_optimization(client: Client, message: Message):
    status = await message.reply_text("⚙️ **Building MongoDB Text Indexes...** This may take a moment.")
    await db.ensure_indexes()
    await status.edit_text("⚡️ **Optimization Complete!** Your database is now searching at maximum speed.")

@Client.on_message(filters.command("migrate_db") & filters.user(Config.ADMINS))
async def reset_unknown_languages(client: Client, message: Message):
    status = await message.reply_text("⚙️ **Upgrading Database for Subtitles & Audio...**")
    total_reset = 0
    
    for coll in db.collections:
        result = await coll.update_many(
            {
                "$or": [
                    {"language": "unknown"},
                    {"subtitle": {"$exists": False}}
                ]
            },
            {
                "$set": {
                    "language": "pending",
                    "subtitle": "pending"
                }
            }
        )
        total_reset += result.modified_count
        
    await status.edit_text(f"✅ **Database Migration Complete!**\n\nSent `{total_reset}` old files back to the Worker 2 queue to extract their Subtitles and Audio tags.")

@Client.on_message(filters.command("clear_job") & filters.user(Config.ADMINS))
async def clear_active_job(client: Client, message: Message):
    job = await db.get_active_job()
    if job:
        await db.update_job(job["_id"], {"status": "completed"})
        await message.reply_text("✅ **Stuck indexing job marked as completed.** The loop will now stop.")
    else:
        await message.reply_text("⚠️ **No active job found.**")
