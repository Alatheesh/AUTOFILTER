import asyncio
import json
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

BROADCAST_QUEUE = asyncio.Queue()
BROADCAST_STATUS = {"total": 0, "processed": 0, "success": 0, "failed": 0, "is_running": False}

CURRENT_WRITE_SHARD = 0

async def process_broadcast_queue(client: Client):
    global BROADCAST_STATUS
    while not BROADCAST_QUEUE.empty():
        msg_to_copy, target_user = await BROADCAST_QUEUE.get()
        try:
            await msg_to_copy.copy(chat_id=target_user)
            BROADCAST_STATUS["success"] += 1
        except Exception as e:
            BROADCAST_STATUS["failed"] += 1
        finally:
            BROADCAST_STATUS["processed"] += 1
            BROADCAST_QUEUE.task_done()
            await asyncio.sleep(0.05) 
            
    BROADCAST_STATUS["is_running"] = False

def format_bytes(size):
    # Formats bytes into KB, MB, GB
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
    
    shards_active = db_stats.get("shards_active", 0)
    total_files = db_stats.get("total_files", 0)
    distribution = db_stats.get("shard_distribution", [])
    
    used_space = format_bytes(db_stats.get("total_size_bytes", 0))
    left_space = format_bytes(db_stats.get("space_left_bytes", 0))
    est_files_left = db_stats.get("estimated_files_left", 0)
    
    shards_text = ""
    for idx, count in enumerate(distribution):
        status_flag = "🟢 Active" if idx == CURRENT_WRITE_SHARD else "⚪ Standby"
        shards_text += f"• **Shard {idx + 1}**: `{count}` files - {status_flag}\n"

    dashboard_text = (
        f"📊 **Advanced System Status Dashboard**\n\n"
        f"🖥️ **Active DB Clusters:** `{shards_active}`\n"
        f"🗂️ **Total Indexed Files:** `{total_files:,}`\n\n"
        f"💾 **Storage Analytics:**\n"
        f"• **Space Used:** `{used_space}`\n"
        f"• **Space Remaining:** `{left_space}`\n"
        f"• **Estimated Capacity Left:** `~{est_files_left:,} files`\n\n"
        f"🖲️ **Shard Distribution:**\n{shards_text}\n"
        f"⚙️ Use `/rotate` to balance active write lanes."
    )
    await status_msg.edit_text(dashboard_text)

@Client.on_message(filters.command("rotate") & filters.user(Config.ADMINS))
async def force_shard_rotation(client: Client, message: Message):
    global CURRENT_WRITE_SHARD
    if not db.collections:
        return await message.reply_text("❌ No database connections established.")
    prev = CURRENT_WRITE_SHARD
    CURRENT_WRITE_SHARD = (CURRENT_WRITE_SHARD + 1) % len(db.collections)
    await message.reply_text(f"🔄 **Shard Lane Rotator Triggered:**\n\n• Previous Target: `Shard {prev + 1}`\n• New Target: `Shard {CURRENT_WRITE_SHARD + 1}`")

@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS))
async def queue_broadcast_init(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("❌ **Usage:** Reply to any campaign banner message with `/broadcast` to proceed.")
    if BROADCAST_STATUS["is_running"]:
        return await message.reply_text("⚠️ **Wait:** A broadcast is running.")

    subscribers = [message.from_user.id] 
    BROADCAST_STATUS.update({"total": len(subscribers), "processed": 0, "success": 0, "failed": 0, "is_running": True})

    for user_id in subscribers:
        await BROADCAST_QUEUE.put((message.reply_to_message, user_id))

    asyncio.create_task(process_broadcast_queue(client))
    await message.reply_text("🚀 **Broadcast campaigns initiated!**")

@Client.on_message(filters.command("backup") & filters.user(Config.ADMINS))
async def multi_shard_json_backup(client: Client, message: Message):
    progress = await message.reply_text("📥 **Connecting to database Shard 0...**")
    try:
        cursor = db.collections[0].find({}).limit(1000)
        documents = await cursor.to_list(length=1000)
        for doc in documents:
            doc["_id"] = str(doc["_id"])

        output_path = "shard0_backup.json"
        with open(output_path, "w") as backup_file:
            json.dump(documents, backup_file, indent=4)

        await message.reply_document(document=output_path, caption=f"📦 **Backup Export**\nProcessed `{len(documents)}` files.")
        await progress.delete()
    except Exception as e:
        await progress.edit_text(f"❌ **Schema Export Failed:** `{str(e)}`")
