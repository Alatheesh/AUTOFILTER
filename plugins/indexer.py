import re
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# Sanitizer Regex definitions
SANITIZING_REGEX = r"[_+\[\]\(\)]"
JUNK_REGEX = r"(?i)(@[\w]+|t\.me/[\w]+|www\.[^\s]+|https?://[^\s]+)"

def sanitize_title(title: str) -> str:
    # Remove junk links, usernames, and special brackets
    clean_title = re.sub(JUNK_REGEX, "", title)
    clean_title = re.sub(SANITIZING_REGEX, " ", clean_title)
    # Strip multiple spaces
    return " ".join(clean_title.split())

@Client.on_message(filters.document | filters.video | filters.audio, group=1)
async def file_indexer(client: Client, message: Message):
    # Depending on configuration, maybe only index from LOG_CHANNEL or FSUB_CHANNELS
    # Assuming here we index from configured FSUB_CHANNELS to be safe, or allow via group forward
    
    media = message.document or message.video or message.audio
    if not media:
        return
        
    file_id = media.file_id
    file_unique_id = media.file_unique_id
    raw_title = getattr(media, "file_name", None) or getattr(message, "caption", None) or "Unknown Media"
    
    sanitized_title = sanitize_title(raw_title)
    file_size = getattr(media, "file_size", 0)
    
    # Very basic deduplication before indexing:
    # First query specific shard or all shards? We do a quick global search exactly on file_unique_id
    
    existing = await db.search_files(file_unique_id, skip=0, limit=1, exact=True)
    if existing:
        logger.debug(f"File {file_unique_id} already exists, skipping deduplication.")
        return
        
    file_data = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "title": sanitized_title,
        "raw_title": raw_title,
        "size": file_size,
        "message_id": message.id,
        "chat_id": message.chat.id
    }
    
    # Insert in round-robin / shard logic
    success = await db.insert_file(file_data)
    if success:
        logger.info(f"Indexed: {sanitized_title}")
    else:
        logger.error(f"Failed to index: {sanitized_title}")

@Client.on_message(filters.command("index") & filters.user(Config.ADMINS))
async def manual_index_channel(client: Client, message: Message):
    # Mass channel scraping logic
    if len(message.command) < 2:
        await message.reply("Usage: /index <chat_id> <skip_count>")
        return
        
    chat_id = message.command[1]
    skip_count = int(message.command[2]) if len(message.command) > 2 else 0
    
    status = await message.reply("Indexing started...")
    count = 0
    
    try:
        async for msg in client.get_chat_history(chat_id, offset=skip_count):
            if msg.document or msg.video or msg.audio:
                # Call indexer logic manually
                await file_indexer(client, msg)
                count += 1
                
                if count % 100 == 0:
                    await status.edit(f"Indexed {count} files so far...")
                    
        await status.edit(f"Indexing complete! Total new files added: {count}")
    except Exception as e:
        await status.edit(f"Error occurred during mass index: {e}")
