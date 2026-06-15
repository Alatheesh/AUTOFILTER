import math
import os
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    Message, 
    InlineQuery, 
    InlineQueryResultArticle, 
    InputTextMessageContent, 
    CallbackQuery
)
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# AD Configuration
AD_SLOT_TEXT = "📢 Join Our VIP Channel [Ads Free]!"
AD_SLOT_URL = "https://t.me/premium_channel"

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

async def fetch_imdb_tmdb(query: str) -> dict:
    """
    Asynchronously queries TMDb API for beautiful movie poster/metadata formatting.
    Falls back gracefully if key is not configured, returning placeholders with dynamic matching.
    """
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    if not tmdb_api_key:
        return {
            "title": query.title(),
            "rating": "8.2/10",
            "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600",
            "genre": "Sci-Fi, Adventure, Mystique",
            "plot": "An intriguing storyline based on your search query. Connect TMDB_API_KEY to unlock actual live movie details."
        }
    
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={query}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results")
                    if results:
                        movie = results[0]
                        poster_path = movie.get("poster_path")
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600"
                        return {
                            "title": movie.get("title", query),
                            "rating": f"{movie.get('vote_average', 'N/A')}/10",
                            "poster": poster_url,
                            "genre": "Drama, Cinematic Spectacle",
                            "plot": movie.get("overview", "No overview description available.")
                        }
    except Exception as e:
        logger.error(f"Error fetching tmdb: {e}")
    
    return {
        "title": query.title(),
        "rating": "N/A",
        "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600",
        "genre": "Uncategorized",
        "plot": f"A query search matching: {query}"
    }

async def get_fuzzy_suggestions(query: str) -> list:
    """
    Scans the database and suggests potential spelling corrections using Levenshtein distance.
    """
    # Grab a small sample of general titles
    titles = await db.search_files("", skip=0, limit=100, exact=False)
    suggestions = []
    
    for item in titles:
        title = item.get("title", "")
        if not title:
            continue
        dist = levenshtein_distance(query.lower(), title.lower())
        # If edit distance is relatively close, recommend it
        if dist <= 5:
            suggestions.append(title)
            
    return list(set(suggestions))[:3]

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(["start", "help", "about", "source"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3:
        return
        
    # Standard DB file search
    results = await db.search_files(query, skip=0, limit=10, exact=False)
    
    if not results:
        # Fetch fuzzy feedback if no direct matches found
        suggestions = await get_fuzzy_suggestions(query)
        if suggestions:
            s_text = ", ".join([f"`{s}`" for s in suggestions])
            await message.reply_text(
                f"😔 No files found matching your query.\n\n**Did you mean:** {s_text}?",
                quote=True
            )
        else:
            await message.reply_text(
                "😔 No files found matching your query across our live shards.",
                quote=True
            )
        return
        
    # Fetch movie poster and details for rich layout embedding
    metadata = await fetch_imdb_tmdb(query)
    
    buttons = []
    for file in results:
        file_id = file.get("file_id", "unknown")
        title = file.get("title", "Unknown Title")
        # Direct deep-link back to the bot start command for delivery
        buttons.append([InlineKeyboardButton(text=f"📂 {title}", url=f"https://t.me/{client.me.username}?start=file_{file_id}")])
    
    # 📢 GLOBAL DYNAMIC AD SLOT ROW
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    
    # PAGINATION CONTROL PANEL
    pagination_row = [
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_0_{query}"),
        InlineKeyboardButton(text="Page 1", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_1_{query}")
    ]
    buttons.append(pagination_row)
    
    caption = (
        f"🎬 **{metadata['title']}**\n"
        f"⭐️ Rating: `{metadata['rating']}`\n"
        f"🎭 Genre: `{metadata['genre']}`\n\n"
        f"📝 **Plot:** {metadata['plot']}\n\n"
        f"🔍 Found **{len(results)}** files matching your request."
    )
    
    # Provide poster layout if valid image exists, fall back elegantly to text
    try:
        await message.reply_photo(
            photo=metadata["poster"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(buttons),
            quote=True
        )
    except Exception as e:
        logger.warning(f"Failed to reply with photo poster, sending text-only fallback: {e}")
        await message.reply_text(
            caption,
            reply_markup=InlineKeyboardMarkup(buttons),
            quote=True
        )

@Client.on_callback_query(filters.regex(r"^(next|prev)_(\d+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action, page_str, query = callback.data.split("_", 2)
    page = int(page_str)
    
    limit = 10
    skip = page * limit
    results = await db.search_files(query, skip=skip, limit=limit, exact=False)
    
    if not results:
        await callback.answer("⚠️ No more pages available!", show_alert=True)
        return
        
    buttons = []
    for file in results:
        file_id = file.get("file_id", "unknown")
        title = file.get("title", "Unknown Title")
        buttons.append([InlineKeyboardButton(text=f"📂 {title}", url=f"https://t.me/{client.me.username}?start=file_{file_id}")])
    
    # GLOBAL DYNAMIC AD SLOT ROW
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    
    # Pagination Row Adjustments
    prev_page = page - 1 if page > 0 else 0
    next_page = page + 1
    
    pagination_row = [
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{prev_page}_{query}"),
        InlineKeyboardButton(text=f"Page {page + 1}", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{next_page}_{query}")
    ]
    buttons.append(pagination_row)
    
    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    await callback.answer()

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
                title=file.get("title", "Unknown File"),
                description=f"Format / Size: {file.get('size', 'N/A')}",
                input_message_content=InputTextMessageContent(
                    message_text=f"**{file.get('title')}**\n\n📥 [Download File Here](https://t.me/{client.me.username}?start=file_{file.get('file_id')})"
                ),
                thumb_url="https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=150",
                id=str(idx)
            )
        )
    
    await query.answer(articles, cache_time=3600, is_personal=True)
