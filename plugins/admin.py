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
    if user_id not in ADMIN_STATE: raise ContinuePropagation
    if message.text.startswith("/"):
        del ADMIN_STATE[user_id]
        raise ContinuePropagation

    state = ADMIN_STATE[user_id]
    user_input = message.text.strip()

    if state == "waiting_for_api":
        await db.update_settings({"shortener_api": user_input})
        del ADMIN_STATE[user_id]
        await message.reply_text("✅ API Key updated! Type `/settings` to view.")
    elif state == "waiting_for_url":
        await db.update_settings({"shortener_url": user_input})
        del ADMIN_STATE[user_id]
        await message.reply_text("✅ Shortener Link updated! Type `/settings` to view.")

@Client.on_message(filters.command("settings") & filters.user(Config.ADMINS))
async def settings_command(client: Client, message: Message):
    await send_settings_home(message)

async def send_settings_home(message_or_query):
    text = "⚙️ **Admin Control Panel**\n\nSelect a module to configure:"
    buttons = [
        [InlineKeyboardButton("🔗 Shortener Settings", callback_data="set_shortener")],
        [InlineKeyboardButton("📝 Request Settings", callback_data="set_requests")]
    ]
    if isinstance(message_or_query, Message): await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    else: await message_or_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

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
        text = f"🔗 **Shortener Configurations**\n\n**Status:** {status}\n**URL:** `{settings.get('shortener_url')}`\n**API:** `{settings.get('shortener_api')}`"
        buttons = [
            [InlineKeyboardButton(f"Toggle Shortener {'OFF' if 'ON' in status else 'ON'}", callback_data="set_toggle")],
            [InlineKeyboardButton("✏️ Change API Key", callback_data="set_api"), InlineKeyboardButton("✏️ Change Link", callback_data="set_url")],
            [InlineKeyboardButton("🔙 Back", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "set_toggle":
        settings = await db.get_settings()
        await db.update_settings({"shortener_enabled": not settings.get("shortener_enabled", False)})
        await settings_callbacks(client, callback._replace(data="set_shortener"))

    elif action == "set_api":
        ADMIN_STATE[user_id] = "waiting_for_api"
        await callback.message.edit_text("✏️ **Send the new API Key in the chat now.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_home")]]))

    elif action == "set_url":
        ADMIN_STATE[user_id] = "waiting_for_url"
        await callback.message.edit_text("✏️ **Send the new URL Link in the chat now.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_home")]]))

    elif action == "set_requests":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("requests_enabled", True) else "🔴 OFF"
        text = f"📝 **Request Feature**\n\n**Status:** {status}\n\nIf ON, users can request movies. Requests will be sent directly to you."
        buttons = [
            [InlineKeyboardButton(f"Toggle Requests {'OFF' if 'ON' in status else 'ON'}", callback_data="toggle_requests")],
            [InlineKeyboardButton("🔙 Back", callback_data="set_home")]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "toggle_requests":
        settings = await db.get_settings()
        await db.update_settings({"requests_enabled": not settings.get("requests_enabled", True)})
        await settings_callbacks(client, callback._replace(data="set_requests"))

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

@Client.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def bot_stats_dashboard(client: Client, message: Message):
    status_msg = await message.reply_text("📊 **Aggregating multi-shard metadata...**")
    db_stats = await db.global_stats()
    used_space = format_bytes(db_stats.get("total_size_bytes", 0))
    left_space = format_bytes(db_stats.get("space_left_bytes", 0))
    shards_text = "".join([f"• **Shard {idx + 1}**: `{count}` files\n" for idx, count in enumerate(db_stats.get("shard_distribution", []))])
    
    await status_msg.edit_text(
        f"📊 **Advanced System Status Dashboard**\n\n"
        f"🗂️ **Total Indexed Files:** `{db_stats.get('total_files', 0):,}`\n\n"
        f"💾 **Storage Analytics:**\n"
        f"• **Space Used:** `{used_space}`\n"
        f"• **Space Remaining:** `{left_space}`\n"
        f"• **Estimated Capacity Left:** `~{db_stats.get('estimated_files_left', 0):,} files`\n\n"
        f"🖲️ **Shard Distribution:**\n{shards_text}"
    )

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
