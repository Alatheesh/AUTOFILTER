import re
import hashlib
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# Sanitization regexes to strip junk links, telegram user mentions, websites, and excessive specials
SANITIZING_REGEX = r"[_+\[\]\(\)\{\}\-.]"
JUNK_REGEX = r"(?i)(@[\w_]+|t\.me/[\w_]+|www\.[^\s]+|https?://[^\s]+)"

def sanitize_title(title: str) -> str:
    """
    Cleans up file titles by removing promo links, @usernames, brackets,
    and special characters, replacing them with clean spacing.
    """
    if not title:
        return "Unknown File"
    
    # 1. Strip external URLs & telegram usernames
    clean_title = re.sub(JUNK_REGEX, "", title)
    
    # 2. Replace brackets and specific symbols with space
    clean_title = re.sub(SANITIZING_REGEX, " ", clean_title)
    
    # 3. Handle double spacing and casing
    clean_title = " ".join(clean_title.split())
    return clean_title.strip() if clean_title.strip() else title

def generate_file_hash(file_name: str, file_size: int) -> str:
    """
    Generates a cryptographic SHA256 signature for deduplication based on metadata
    where precise server file-checksums are unavailable.
    """
    hash_payload = f"{file_name}_{file_size}".encode("utf-8")
    return hashlib.sha256(hash_payload).hexdigest()

@Client.on_message(filters.document | filters.video | filters.audio, group=1)
async def auto_indexer(client: Client, message: Message):
    """
    Background listener that intercepts media posts in channels/chats
    and indexes them into the distributed multi-DB.
    """
    media = message.document or message.video or message.audio
    if not media:
        return

    file_id = media.file_id
    file_unique_id = media.file_unique_id
    raw_title = getattr(media, "file_name", "") or getattr(message, "caption", "") or "Unknown Web File"
    file_size = getattr(media, "file_size", 0)

    # 1. Clean Title Sanitization
    sanitized_title = sanitize_title(raw_title)

    # 2. Cryptographic Fingerprint for Deduplication
    crypto_hash = generate_file_hash(raw_title, file_size)

    # 3. Query all multi-DB shards to check if this cryptohash identifier exists
    existing = await db.search_files(crypto_hash, skip=0, limit=1, exact=True)
    if existing:
        logger.debug(f"Media file with unique hash {crypto_hash} already indexed. Skipping.")
        return

    file_data = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "crypto_hash": crypto_hash,
        "title": sanitized_title,
        "raw_title": raw_title,
        "size": file_size,
        "message_id": message.id,
        "chat_id": message.chat.id
    }

    # Insert with multi-DB shard balancing logic
    success = await db.insert_file(file_data)
    if success:
        logger.info(f"Successfully indexed: '{sanitized_title}' ({file_size} bytes)")

@Client.on_message(filters.command(["index", "batch"]) & filters.user(Config.ADMINS))
async def mass_indexer_command(client: Client, message: Message):
    """
    Admin command to scrape historical media content from any group or channel
    fully asynchronously, bypassing rate limits.
    """
    target_chat = None
    offset = 0

    # 1. Did the user reply to a forwarded message?
    if message.reply_to_message and message.reply_to_message.forward_from_chat:
        target_chat = message.reply_to_message.forward_from_chat.id
        if len(message.command) > 1:
            try:
                offset = int(message.command[1])
            except ValueError:
                pass

    # 2. Did the user type the ID manually?
    elif len(message.command) > 1:
        try:
            target_chat = int(message.command[1])
        except ValueError:
            target_chat = message.command[1]
            
        if len(message.command) > 2:
            try:
                offset = int(message.command[2])
            except ValueError:
                pass

    if not target_chat:
        await message.reply_text(
            "❌ **Usage:**\n\n"
            "**Method 1:** `/index -1001844188498`\n"
            "**Method 2:** Forward a file from the channel, reply to it, and type `/index`"
        )
        return

    progress_msg = await message.reply_text(f"⏳ **Initializing Indexer...**\nResolving chat: `{target_chat}`")

    # ==========================================
    # ---> THE PEER RESOLUTION FIX <---
    # ==========================================
    try:
        # Force Pyrogram to look up the chat so it knows it is a Channel/Supergroup
        chat_info = await client.get_chat(target_chat)
        target_chat = chat_info.id 
        
        # Security Check: Telegram Bot API blocks history reading in Basic Groups
        if chat_info.type in [ChatType.GROUP, ChatType.PRIVATE]:
            return await progress_msg.edit_text(
                "❌ **Telegram API Restriction:**\n\n"
                "Bots are strictly forbidden from reading chat history in Basic Groups or Private Chats.\n\n"
                "**How to fix:** If this is a group, upgrade it to a Supergroup by going to Group Settings -> Chat History -> Set to 'Visible'."
            )
    except Exception as e:
        return await progress_msg.edit_text(f"❌ **Error Accessing Chat:**\n`{e}`\n\nMake sure I am added as an Admin in that channel/group!")
    # ==========================================

    await progress_msg.edit_text(f"⏳ **Starting index sweep on `{chat_info.title or target_chat}` at offset {offset}...**")
    
    total_found = 0
    total_duplicates = 0

    try:
        async for msg in client.get_chat_history(target_chat, offset=offset):
            media = msg.document or msg.video or msg.audio
            if not media:
                continue

            raw_title = getattr(media, "file_name", "") or getattr(msg, "caption", "") or "Unknown"
            sanitized_title = sanitize_title(raw_title)
            file_size = getattr(media, "file_size", 0)
            crypto_hash = generate_file_hash(raw_title, file_size)

            existing = await db.search_files(crypto_hash, skip=0, limit=1, exact=True)
            if existing:
                total_duplicates += 1
                continue

            file_data = {
                "file_id": media.file_id,
                "file_unique_id": media.file_unique_id,
                "crypto_hash": crypto_hash,
                "title": sanitized_title,
                "raw_title": raw_title,
                "size": file_size,
                "message_id": msg.id,
                "chat_id": msg.chat.id
            }

            await db.insert_file(file_data)
            total_found += 1

            if total_found % 50 == 0:
                await progress_msg.edit_text(
                    f"🔄 **Index Progress Updated:**\n"
                    f"• Target: `{chat_info.title or target_chat}`\n"
                    f"• Indexed: `{total_found}`\n"
                    f"• Duplicates skipped: `{total_duplicates}`"
                )

        await progress_msg.edit_text(
            f"✅ **Mass Index Completed Successfully!**\n\n"
            f"• Scraped Source: `{chat_info.title or target_chat}`\n"
            f"• Indexed Files: `{total_found}`\n"
            f"• Duplicates Skipped: `{total_duplicates}`"
        )

    except Exception as e:
        logger.error(f"Error during mass indexing command: {e}")
        await progress_msg.edit_text(f"❌ **Failed to Index Chat:**\n`{str(e)}`")
