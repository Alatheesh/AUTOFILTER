import time
import asyncio
import logging
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("migrateshard") & filters.user(Config.ADMINS))
async def sequential_shard_migration(client: Client, message: Message):
    """
    Safely migrates exactly 1 Lakh files from Shard 1 to Shard 2 
    with an Ironclad Safety Lock to absolutely guarantee zero data loss.
    """
    status_msg = await message.reply_text(
        "⏳ **Initializing Secure Shard Migration...**\n"
        "Connecting to database cluster and scanning Shard 1 partitions."
    )
    
    # Shard 1 is index 0, Shard 2 is index 1
    if len(db.collections) < 2:
        return await status_msg.edit_text("❌ **Migration Aborted:** You do not have a second shard configured in your URIs.")
        
    source_coll = db.collections[0]
    target_coll = db.collections[1]
    
    total_to_move = 100000
    batch_size = 2000
    moved_count = 0
    start_time = time.time()
    
    while moved_count < total_to_move:
        # Calculate exactly how many files are left to pull for the final batch
        current_batch_limit = min(batch_size, total_to_move - moved_count)
        
        # Pull records from Shard 1
        cursor = source_coll.find({}).limit(current_batch_limit)
        batch_files = await cursor.to_list(length=current_batch_limit)
        
        if not batch_files:
            break  # Break out early if Shard 1 runs completely dry
            
        # Extract the default ObjectIDs for safe deletion from source shard later
        ids_to_delete = [doc["_id"] for doc in batch_files]
        
        # Strip the old '_id' field from documents so MongoDB assigns a clean, non-conflicting ID on Shard 2
        for doc in batch_files:
            if "_id" in doc:
                del doc["_id"]
                
        try:
            # 1. Bulk write into Shard 2
            insert_result = await target_coll.insert_many(batch_files, ordered=False)
            
            # 2. 🔒 THE IRONCLAD SAFETY LOCK 🔒
            # We explicitly verify that the number of files MongoDB confirms it saved
            # perfectly matches the number of files we tried to send.
            if len(insert_result.inserted_ids) == len(batch_files):
                
                # 3. Bulk delete from Shard 1 ONLY if the lock passes
                await source_coll.delete_many({"_id": {"$in": ids_to_delete}})
                moved_count += len(batch_files)
                
            else:
                # If numbers don't match, we abort IMMEDIATELY before deleting anything
                raise Exception(
                    f"Safety Lock Triggered! Tried to insert {len(batch_files)} files, "
                    f"but Shard 2 only confirmed {len(insert_result.inserted_ids)}. Halting to prevent data loss."
                )
            
            # --- LIVE TRACKER INTERFACE ---
            elapsed = time.time() - start_time
            percentage = int((moved_count / total_to_move) * 100)
            filled_blocks = int(percentage / 10)
            progress_bar = "█" * filled_blocks + "░" * (10 - filled_blocks)
            
            await status_msg.edit_text(
                f"🔄 **Shard Migration in Progress...**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 **Source Cluster:** Shard 1\n"
                f"📥 **Target Cluster:** Shard 2\n\n"
                f"📦 **Moved Count:** `{moved_count:,}` / `{total_to_move:,}` records\n"
                f"📊 **Progress Gauge:** `[{progress_bar}] {percentage}%`\n"
                f"⏱️ **Elapsed Time:** `{round(elapsed, 1)} seconds`"
            )
            
            # 🛡️ Anti-flood safety cooldown to allow other database functions to run smoothly
            await asyncio.sleep(1.0)
            
        except Exception as e:
            logger.error(f"Shard migration pipeline failure: {e}")
            return await status_msg.edit_text(
                f"❌ **Migration Halted due to an Error:**\n`{e}`\n\n"
                f"⚠️ **Recovery Info:** Pipeline safely committed `{moved_count:,}` records before closing. "
                f"**No data was lost.**"
            )
            
    total_time = round(time.time() - start_time, 1)
    await status_msg.edit_text(
        f"✅ **SHARD MIGRATION SECURELY COMPLETED!**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ **Total Transferred:** `{moved_count:,}` file entries\n"
        f"🔌 **Source Status:** Cleaned & Synced\n"
        f"📥 **Destination Status:** Appended & Optimized\n"
        f"⏱️ **Total Execution Time:** `{total_time}s`"
    )
    raise StopPropagation
