import logging
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# 🗑️ MANUAL FILE DELETION (Reply-to-Delete)
# ==========================================
@Client.on_message(filters.command(["del", "delete", "remove"]) & filters.user(Config.ADMINS) & filters.reply)
async def delete_specific_file(client: Client, message: Message):
    target_msg = message.reply_to_message
    
    # Extract the media object from the replied message
    media = target_msg.document or target_msg.video or target_msg.audio
    
    if not media:
        await message.reply_text("❌ **Invalid Target:** Please reply directly to a valid movie or file message to delete it.")
        raise StopPropagation

    unique_id = media.file_unique_id
    deleted_count = 0
    
    # Iterate through your database shards to find and delete the exact file
    for coll in db.collections:
        result = await coll.delete_many({"file_unique_id": unique_id})
        deleted_count += result.deleted_count

    if deleted_count > 0:
        await message.reply_text(f"✅ **Target Eliminated!**\n\nPermanently deleted `{deleted_count}` copy(s) of this file from the database.")
        
        # Optional: Safely delete the forwarded message from the chat to keep things clean
        try:
            await target_msg.delete()
        except Exception:
            pass
    else:
        await message.reply_text("⚠️ **Not Found:** This file is not currently indexed in your database. It may have already been deleted.")
        
    raise StopPropagation
