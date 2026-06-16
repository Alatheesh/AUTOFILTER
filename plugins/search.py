import math
import os
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, 
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery
)
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

AD_SLOT_TEXT = "📢 Join Our VIP Channel [Ads Free]!"
AD_SLOT_URL = "https://t.me/premium_channel"

MB = 1024 * 1024
GB = 1024 * MB

SIZE_MAP = {
    "small": (0, 500 * MB),
    "medium": (500 * MB, 1 * GB),
    "large": (1 * GB, 2 * GB),
    "xlarge": (2 * GB, float('inf')),
    "all": (0, float('inf'))
}

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2): return levenshtein_distance(s2, s1)
    if len(s2) == 0: return len(s1)
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
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    if not tmdb_api_key:
        return {
            "title": query.title(), "rating": "8.2/10", 
            "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", 
            "genre": "Sci-Fi, Adventure", "plot": "Connect TMDB_API_KEY to unlock actual live movie details."
        }
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={query}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("results"):
                        movie = data["results"][0]
                        poster_url = f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get("poster_path") else "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600"
                        return {
                            "title": movie.get("title", query), "rating": f"{movie.get('vote_average', 'N/A')}/10", 
                            "poster": poster_url, "genre": "Drama", "plot": movie.get("overview", "No overview available.")
                        }
    except Exception as e: logger.error(f"TMDB Fetch Error: {e}")
    return {
        "title": query.title(), "rating": "N/A", 
        "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", 
        "genre": "Uncategorized", "plot": f"A query search matching: {query}"
    }

async def get_tmdb_suggestions(query: str) -> list:
    """Uses TMDB API to find the perfectly spelled movie title for typos."""
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    if not tmdb_api_key: return []
        
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={query}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    titles = []
                    for m in results:
                        t = m.get("title")
                        if t and t not in titles:
                            titles.append(t)
                        if len(titles) >= 3: # Grab top 3 perfect matches
                            break
                    return titles
    except Exception as e: logger.error(f"TMDB Suggestion Error: {e}")
    return []

async def get_fuzzy_suggestions(query: str) -> list:
    """Fallback: Searches local DB if TMDB API is offline."""
    titles = await db.search_files("", skip=0, limit=100, exact=False)
    suggestions = []
    for item in titles:
        title = item.get("title", "")
        if title and levenshtein_distance(query.lower(), title.lower()) <= 5:
            suggestions.append(title)
    return list(set(suggestions))[:3]

async def get_filter_settings(user_id: int, chat_id: int, chat_type):
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(chat_id)
        g_mode = g_sett.get("search_mode", "let_members_choose")
        if g_mode == "force_default": return "default", "all", "all"
        elif g_mode == "force_interactive": return "interactive", g_sett.get("language_lock", "all"), g_sett.get("size_lock", "all")
    u_sett = await db.get_user_settings(user_id)
    return u_sett.get("search_mode", "default"), u_sett.get("language", "all"), u_sett.get("size", "all")

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(["start", "help", "about", "source", "settings", "request", "plot", "history", "clear_history", "broadcast", "stats", "backup", "admin", "index", "batch", "migrate_db"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3: return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    resolved_mode, resolved_lang, resolved_size = await get_filter_settings(user_id, chat_id, message.chat.type)

    raw_query = query
    if resolved_mode == "interactive" and resolved_lang not in ["all", "none"]:
        raw_query += f" {resolved_lang}"

    raw_results = await db.search_files(raw_query, skip=0, limit=150, exact=False)
    
    min_bytes, max_bytes = SIZE_MAP.get(resolved_size, (0, float('inf')))
    filtered_results = [f for f in raw_results if min_bytes <= f.get("size", 0) <= max_bytes]

    results = filtered_results[:10]
    
    # ==========================================
    # --- TMDB SMART BUTTON GENERATOR ---
    # ==========================================
    if not results:
        # 1. Try TMDB first for perfect spelling, fallback to local DB if no API key
        suggestions = await get_tmdb_suggestions(query)
        if not suggestions:
            suggestions = await get_fuzzy_suggestions(query)
            
        btn_list = []
        if suggestions:
            for s in suggestions:
                # 2. Build the clickable auto-correct buttons
                btn_list.append([InlineKeyboardButton(f"🔍 Search: {s}", callback_data=f"fuz_{s[:50]}")])
                
        # 3. Always keep the Request button at the bottom
        btn_list.append([InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{query[:40]}")])
        
        if suggestions:
            await message.reply_text("😔 **No exact matches found.**\n\nDid you mean one of these?", reply_markup=InlineKeyboardMarkup(btn_list))
        else:
            await message.reply_text("😔 **No files found matching your criteria.**", reply_markup=InlineKeyboardMarkup(btn_list))
        return
    # ==========================================
        
    metadata = await fetch_imdb_tmdb(query)
    buttons = []
    
    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    
    if len(filtered_results) > 10:
        total_pages = math.ceil(len(filtered_results) / 10)
        buttons.append([
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_0_{query}"),
            InlineKeyboardButton(text=f"Page 1 of {total_pages}", callback_data="pages_info"),
            InlineKeyboardButton(text="Next ▶️", callback_data=f"next_1_{query}")
        ])
    
    filter_notice = ""
    if resolved_mode == "interactive" and (resolved_lang != "all" or resolved_size != "all"):
        filter_notice = f"\n✨ **Filters Applied:** Size: `{resolved_size.upper()}` | Audio: `{resolved_lang.upper()}`"

    caption = (
        f"🎬 **{metadata['title']}**\n"
        f"⭐️ Rating: `{metadata['rating']}`\n"
        f"🎭 Genre: `{metadata['genre']}`\n\n"
        f"📝 **Plot:** {metadata['plot']}\n\n"
        f"🔍 Found {len(filtered_results)} matching files.{filter_notice}"
    )
    
    try:
        await message.reply_photo(photo=metadata["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^(next|prev)_(\d+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action, page_str, base_query = callback.data.split("_", 2)
    page = int(page_str)
    
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    chat_type = callback.message.chat.type
    
    resolved_mode, resolved_lang, resolved_size = await get_filter_settings(user_id, chat_id, chat_type)

    raw_query = base_query
    if resolved_mode == "interactive" and resolved_lang not in ["all", "none"]:
        raw_query += f" {resolved_lang}"
        
    raw_results = await db.search_files(raw_query, skip=0, limit=150, exact=False)
    
    min_bytes, max_bytes = SIZE_MAP.get(resolved_size, (0, float('inf')))
    filtered_results = [f for f in raw_results if min_bytes <= f.get("size", 0) <= max_bytes]
    
    results = filtered_results[page * 10 : (page + 1) * 10]
    
    if not results:
        return await callback.answer("⚠️ No more pages available matching your filters!", show_alert=True)
        
    buttons = []
    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    
    total_pages = math.ceil(len(filtered_results) / 10)
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{page - 1}_{base_query}"))
        
    nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
    
    if len(filtered_results) > (page + 1) * 10:
        nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{page + 1}_{base_query}"))
        
    buttons.append(nav_buttons)
    
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
                description=f"Size: {format_size(file.get('size', 0))}",
                input_message_content=InputTextMessageContent(
                    message_text=f"**{file.get('title')}**\n\n📥 [Download File Here](https://t.me/{client.me.username}?start=getfile_{db_id})"
                ),
                thumb_url="https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=150",
                id=str(idx)
            )
        )
    
    await query.answer(articles, cache_time=3600, is_personal=True)
