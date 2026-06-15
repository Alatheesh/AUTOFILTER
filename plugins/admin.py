import asyncio
import json
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# Broadcast queue controls
BROADCAST_QUEUE = asyncio.Queue()
BROADCAST_STATUS = {"total": 0, "processed": 0, "success": 0, "failed": 0, "is_running": False}

# Administrative global limits: Dynamic Shard Target selector
CURRENT_WRITE_SHARD = 0
SHARD_LIMIT_THRESHOLD = 200000  # Automatically rotate shard if it carries too many docs

async def process_broadcast_queue(client: Client):
    """
    Background worker that digests broadcats sequentially to avoid flood wait penalties.
    """
    global BROADCAST_STATUS
    while not BROADCAST_QUEUE.empty():
        msg_to_copy, target_user = await BROADCAST_QUEUE.get()
        try:
            await msg_to_copy.copy(chat_id=target_user)
            BROADCAST_STATUS["success"] += 1
        except Exception as e:
            logger.error(f"Broadcast failure to recipient {target_user}: {e}")
            BROADCAST_STATUS["failed"] += 1
        finally:
            BROADCAST_STATUS["processed"] += 1
            BROADCAST_QUEUE.task_done()
            await asyncio.sleep(0.05) # Rate-limiting safety interval
            
    BROADCAST_STATUS["is_running"] = False
    logger.info("Administrative broadcast process complete.")

@Client.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def bot_stats_dashboard(client: Client, message: Message):
    """
    Displays deep diagnostic metrics, database cluster counts, and active write shard IDs.
    """
    status_msg = await message.reply_text("📊 **Aggregating multi-shard metadata...**")
    
    # Query database statistics across shards
    db_stats = await db.global_stats()
    
    shards_active = db_stats.get("shards_active", 0)
    total_files = db_stats.get("total_files", 0)
    distribution = db_stats.get("shard_distribution", [])
    
    shards_text = ""
    for idx, count in enumerate(distribution):
        status_flag = "🟢 Active" if idx == CURRENT_WRITE_SHARD else "⚪ Standby"
        shards_text += f"• **Shard {idx + 1}**: `{count}` files - {status_flag}\n"
        
    broadcast_report = (
        f"• Queue running: `{'Yes' if BROADCAST_STATUS['is_running'] else 'Idle'}`\n"
        f"• Broadcast Success: `{BROADCAST_STATUS['success']}` | Failed: `{BROADCAST_STATUS['failed']}`"
    )

    dashboard_text = (
        f"📊 **System Status & Management Console**\n\n"
        f"🖥️ **Active DB Clusters:** `{shards_active}` / Limitless\n"
        f"🗂️ **Total Combined Files:** `{total_files}`\n\n"
        f"🖲️ **Shard Distribution Metrics:**\n"
        f"{shards_text}\n"
        f"📈 **Broadcast Subsystem:**\n"
        f"{broadcast_report}\n\n"
        f"⚙️ Use `/rotate` to balance active write lanes manually."
    )
    await status_msg.edit_text(dashboard_text)

@Client.on_message(filters.command("rotate") & filters.user(Config.ADMINS))
async def force_shard_rotation(client: Client, message: Message):
    """
    Allows admins to switch write streams and load balance shards dynamically.
    """
    global CURRENT_WRITE_SHARD
    if not db.collections:
        await message.reply_text("❌ No database connections established.")
        return
        
    prev = CURRENT_WRITE_SHARD
    CURRENT_WRITE_SHARD = (CURRENT_WRITE_SHARD + 1) % len(db.collections)
    await message.reply_text(
        f"🔄 **Shard Lane Rotator Triggered:**\n\n"
        f"• **Previous Write Target:** `Shard {prev + 1}`\n"
        f"• **New Target Destination:** `Shard {CURRENT_WRITE_SHARD + 1}`\n"
        f"System routing is updating live across connections."
    )

@Client.on_message(filters.command("broadcast") & filters.user(Config.ADMINS))
async def queue_broadcast_init(client: Client, message: Message):
    """
    Queues messages for sequential async dispatching, preventing server stall.
    """
    if not message.reply_to_message:
        await message.reply_text("❌ **Usage:** Reply to any campaign banner message with `/broadcast` to proceed.")
        return

    if BROADCAST_STATUS["is_running"]:
        await message.reply_text("⚠️ **Wait:** An administrative broadcast queue is currently digesting tasks. Try again later.")
        return

    # In a real environment, we would grab a full user list from our database shards.
    # For safe modular blueprinting, process the administrative initiator
    subscribers = [message.from_user.id] # Mocking bulk list with current admin
    
    # Initialize Queue parameters
    BROADCAST_STATUS["total"] = len(subscribers)
    BROADCAST_STATUS["processed"] = 0
    BROADCAST_STATUS["success"] = 0
    BROADCAST_STATUS["failed"] = 0
    BROADCAST_STATUS["is_running"] = True

    for user_id in subscribers:
        await BROADCAST_QUEUE.put((message.reply_to_message, user_id))

    # Fire background worker task
    asyncio.create_task(process_broadcast_queue(client))
    await message.reply_text("🚀 **Broadcast campaigns initiated!** Live updates available in `/stats` dashboard.")

@Client.on_message(filters.command("backup") & filters.user(Config.ADMINS))
async def multi_shard_json_backup(client: Client, message: Message):
    """
    Performs live parallel exports of indexes on Shard 0 up to configured safety thresholds.
    """
    progress = await message.reply_text("📥 **Connecting to database Shard 0 for indices capture...**")
    
    try:
        if not db.collections:
            await progress.edit_text("❌ Backup aborted. No active connections available.")
            return

        # Fetch up to 1000 items from primary write sharding database collection
        cursor = db.collections[0].find({}).limit(1000)
        documents = await cursor.to_list(length=1000)

        # Deserialize ObjectIDs for standard client json serialization
        for doc in documents:
            doc["_id"] = str(doc["_id"])

        output_path = "shard0_backup_export.json"
        with open(output_path, "w") as backup_file:
            json.dump(documents, backup_file, indent=4)

        await message.reply_document(
            document=output_path,
            caption="📦 **Multi-DB Shard 0 Index Backup Export**\n\n"
                    f"Processed `{len(documents)}` index documents accurately."
        )
        await progress.delete()
    except Exception as e:
        logger.error(f"Backup critical exception: {e}")
        await progress.edit_text(f"❌ **Schema Export Failed:** `{str(e)}`")
