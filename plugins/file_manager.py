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

# ==========================================
# 🧹 BULK JUNK CLEANER (With Safety Preview)
# ==========================================
@Client.on_message(filters.command("cleanjunk") & filters.user(Config.ADMINS))
async def clean_junk_files(client: Client, message: Message):
    # Determine if this is a dry run (preview) or actual deletion
    is_dry_run = "force" not in message.text.lower()
    
    status_msg = await message.reply_text("🔍 **Scanning for junk files...**")
    
    size_threshold = 25 * 1024 * 1024  # 25 MB
    JUNK_EXTENSIONS = [".zip", ".rar", ".txt", ".pdf", ".apk", ".exe", ".iso", ".tar", ".gz"]
    MOVIE_EXTENSIONS = [".mkv", ".mp4", ".avi", ".webm", ".m4v", ".flv"]
    
    junk_regex = "(" + "|".join([ext.replace(".", "\\.") + "$" for ext in JUNK_EXTENSIONS]) + ")"
    movie_regex = "(" + "|".join([ext.replace(".", "\\.") + "$" for ext in MOVIE_EXTENSIONS]) + ")"
    
    query = {
        "$or": [
            {"title": {"$regex": junk_regex, "$options": "i"}},
            {
                "size": {"$lt": size_threshold, "$gt": 0},
                "title": {"$not": {"$regex": movie_regex, "$options": "i"}}
            }
        ]
    }

    total_to_delete = 0
    sample_files = []

    # Calculate what would be deleted
    for coll in db.collections:
        cursor = coll.find(query).limit(10) # Get 10 samples
        async for doc in cursor:
            sample_files.append(doc.get("title", "Unknown File"))
        total_to_delete += await coll.count_documents(query)

    if total_to_delete == 0:
        return await status_msg.edit_text("✨ **Database is clean!** No junk files found.")

    if is_dry_run:
        sample_text = "\n".join([f"• `{f}`" for f in sample_files])
        return await status_msg.edit_text(
            f"⚠️ **Preview Mode (Safe)**\n\n"
            f"Found `{total_to_delete}` files that match junk criteria.\n\n"
            f"**Sample files to be deleted:**\n{sample_text}\n\n"
            f"To permanently delete these, type: `/cleanjunk force`"
        )

    # If 'force' was used, proceed to delete
    deleted_count = 0
    for coll in db.collections:
        result = await coll.delete_many(query)
        deleted_count += result.deleted_count
        
    await status_msg.edit_text(f"✅ **Cleanup Complete!**\n\n🗑️ Permanently destroyed `{deleted_count}` junk files.")
