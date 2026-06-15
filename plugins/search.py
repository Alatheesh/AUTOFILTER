import math
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from database.multi_db import db
from config import Config

# Dummy ad slots config for the requirement
AD_SLOT_TEXT = "📢 Join Our Premium Channel!"
AD_SLOT_URL = "https://t.me/premium_channel"

@Client.on_message(filters.group & filters.text & ~filters.command(["start", "help"]))
async def auto_filter(client: Client, message: Message):
    query = message.text
    if len(query) < 3:
        return
        
    results = await db.search_files(query, skip=0, limit=10, exact=False)
    
    if not results:
        # Ghost mode note: We could self-destruct negative responses
        return
        
    buttons = []
    for file in results:
        # Creating a safe-search URL / file deep link
        # Assumes file uses encoded strings or IDs for streaming/retrieval
        file_id = file.get("file_id", "unknown")
        title = file.get("title", "Unknown Title")
        buttons.append([InlineKeyboardButton(text=title, url=f"https://t.me/{client.me.username}?start=file_{file_id}")])
    
    # Adding an AD SLOT if enabled
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    
    # Simple Pagination Next button
    buttons.append([InlineKeyboardButton(text="Next ➡️", callback_data=f"next_0_{query[:20]}")])
    
    await message.reply_text(
        f"**Search Results for:** `{query}`\n\nFound {len(results)} results in our global shards.",
        reply_markup=InlineKeyboardMarkup(buttons),
        quote=True
    )

@Client.on_inline_query()
async def inline_search(client: Client, query: InlineQuery):
    search_query = query.query.strip()
    if len(search_query) < 3:
        await query.answer([])
        return
        
    results = await db.search_files(search_query, skip=0, limit=Config.MAX_RESULTS, exact=False)
    
    articles = []
    for idx, file in enumerate(results):
        articles.append(
            InlineQueryResultArticle(
                title=file.get("title", "Unknown"),
                description=f"Size: {file.get('size', 'Unknown')}",
                input_message_content=InputTextMessageContent(
                    message_text=f"**{file.get('title')}**\n[Click here to get file](https://t.me/{client.me.username}?start=file_{file.get('file_id')})"
                ),
                thumb_url="https://via.placeholder.com/150", # Dummy thumbnail
                id=str(idx)
            )
        )
    
    await query.answer(articles, cache_time=0, is_personal=True)
