import math
import os
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, 
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery
)
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

AD_SLOT_TEXT = "📢 Join Our VIP Channel [Ads Free]!"
AD_SLOT_URL = "https://t.me/premium_channel"

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2): return levenshtein_distance(s2, s1)
    if len(s2) == 0: return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions, deletions, substitutions = previous_row[j + 1] + 1, current_row[j] + 1, previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

async def fetch_imdb_tmdb(query: str) -> dict:
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    if not tmdb_api_key:
        return {"title": query.title(), "rating": "8.2/10", "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", "genre": "Sci-Fi, Adventure, Mystique", "plot": "Connect TMDB_API_KEY to unlock actual live movie details."}
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={query}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("results"):
                        movie = data["results"][0]
                        poster_url = f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600"
                        return {"title": movie.get("title", query), "rating": f"{movie.get('vote_average', 'N/A')}/10", "poster": poster_url, "genre": "Drama", "plot": movie.get("overview", "No overview available.")}
    except Exception: pass
    return {"title": query.title(), "rating": "N/A", "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", "genre": "Uncategorized", "plot": f"A query search matching: {query}"}

async def get_fuzzy_suggestions(query: str) -> list:
    titles = await db.search_files("", skip=0, limit=100, exact=False)
    suggestions = []
    for item in titles:
        title = item.get("title", "")
        if title and levenshtein_distance(query.lower(), title.lower()) <= 5: suggestions.append(title)
    return list(set(suggestions))[:3]

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(["start", "help", "about", "source", "settings", "request"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3: return
        
    results = await db.search_files(query, skip=0, limit=10, exact=False)
    
    if not results:
        suggestions = await get_fuzzy_suggestions(query)
        req_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{query[:40]}")]])
        
        if suggestions:
            s_text = ", ".join([f"`{s}`" for s in suggestions])
            await message.reply_text(f"😔 No files found matching your query.\n\n**Did you mean:** {s_text}?", reply_markup=req_buttons)
        else:
            await message.reply_text("😔 No files found matching your query across our live shards.", reply_markup=req_buttons)
        return
        
    metadata = await fetch_imdb_tmdb(query)
    buttons = []
    for file in results:
        # THE FIX: We pull the short '_id' instead of the long 'file_id'
        db_id = str(file.get("_id", ""))
        buttons.append([InlineKeyboardButton(text=f"📂 {file.get('title', 'Unknown Title')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    buttons.append([
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_0_{query}"),
        InlineKeyboardButton(text="Page 1", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_1_{query}")
    ])
    
    caption = f"🎬 **{metadata['title']}**\n⭐️ Rating: `{metadata['rating']}`\n🎭 Genre: `{metadata['genre']}`\n\n📝 **Plot:** {metadata['plot']}\n\n🔍 Found **{len(results)}** files matching your request."
    
    try: await message.reply_photo(photo=metadata["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception: await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^(next|prev)_(\d+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action, page_str, query = callback.data.split("_", 2)
    page = int(page_str)
    limit = 10
    results = await db.search_files(query, skip=page * limit, limit=limit, exact=False)
    
    if not results: return await callback.answer("⚠️ No more pages available!", show_alert=True)
        
    buttons = []
    for file in results:
        db_id = str(file.get("_id", ""))
        buttons.append([InlineKeyboardButton(text=f"📂 {file.get('title', 'Unknown Title')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    buttons.append([
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{max(0, page - 1)}_{query}"),
        InlineKeyboardButton(text=f"Page {page + 1}", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{page + 1}_{query}")
    ])
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await callback.answer()

@Client.on_inline_query()
async def inline_search(client: Client, query: InlineQuery):
    search_query = query.query.strip()
    if len(search_query) < 3: return await query.answer([])
        
    results = await db.search_files(search_query, skip=0, limit=Config.MAX_RESULTS, exact=False)
    
    articles = []
    for idx, file in enumerate(results):
        db_id = str(file.get("_id", ""))
        articles.append(
            InlineQueryResultArticle(
                title=file.get("title", "Unknown File"),
                description=f"Format / Size: {file.get('size', 'N/A')}",
                input_message_content=InputTextMessageContent(
                    message_text=f"**{file.get('title')}**\n\n📥 [Download File Here](https://t.me/{client.me.username}?start=getfile_{db_id})"
                ),
                thumb_url="https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=150",
                id=str(idx)
            )
        )
    
    await query.answer(articles, cache_time=3600, is_personal=True)
