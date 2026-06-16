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
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    if not tmdb_api_key:
        return {
            "title": query.title(), 
            "rating": "8.2/10", 
            "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", 
            "genre": "Sci-Fi, Adventure, Mystique", 
            "plot": "Connect TMDB_API_KEY to unlock actual live movie details."
        }
        
    url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={query}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("results"):
                        movie = data["results"][0]
                        if movie.get("poster_path"):
                            poster_url = f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}"
                        else:
                            poster_url = "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600"
                            
                        return {
                            "title": movie.get("title", query), 
                            "rating": f"{movie.get('vote_average', 'N/A')}/10", 
                            "poster": poster_url, 
                            "genre": "Drama", 
                            "plot": movie.get("overview", "No overview available.")
                        }
    except Exception as e:
        logger.error(f"TMDB Fetch Error: {e}")
        
    return {
        "title": query.title(), 
        "rating": "N/A", 
        "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", 
        "genre": "Uncategorized", 
        "plot": f"A query search matching: {query}"
    }

async def get_fuzzy_suggestions(query: str) -> list:
    titles = await db.search_files("", skip=0, limit=100, exact=False)
    suggestions = []
    
    for item in titles:
        title = item.get("title", "")
        if title and levenshtein_distance(query.lower(), title.lower()) <= 5:
            suggestions.append(title)
            
    return list(set(suggestions))[:3]

# THE NEW SEARCH ENGINE: Resolves your settings and modifies the query automatically!
async def get_filtered_query(user_id: int, chat_id: int, chat_type, base_query: str) -> str:
    resolved_mode = "default"
    resolved_qual = "all"
    resolved_lang = "all"
    
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(chat_id)
        g_mode = g_sett.get("search_mode", "let_members_choose")
        if g_mode == "force_default":
            resolved_mode = "default"
        elif g_mode == "force_interactive":
            resolved_mode = "interactive"
            resolved_qual = g_sett.get("quality_lock", "all")
            resolved_lang = g_sett.get("language_lock", "all")
        else:
            u_sett = await db.get_user_settings(user_id)
            resolved_mode = u_sett.get("search_mode", "default")
            resolved_qual = u_sett.get("quality", "all")
            resolved_lang = u_sett.get("language", "all")
    else:
        u_sett = await db.get_user_settings(user_id)
        resolved_mode = u_sett.get("search_mode", "default")
        resolved_qual = u_sett.get("quality", "all")
        resolved_lang = u_sett.get("language", "all")

    actual_query = base_query
    if resolved_mode == "interactive":
        if resolved_qual not in ["all", "none"]:
            actual_query += f" {resolved_qual}"
        if resolved_lang not in ["all", "none"]:
            actual_query += f" {resolved_lang}"
            
    return actual_query


@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(["start", "help", "about", "source", "settings", "request", "plot", "history", "clear_history", "broadcast", "stats", "backup", "admin"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3:
        return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # We call our new settings engine to get the filtered query invisibly!
    filtered_query = await get_filtered_query(user_id, chat_id, message.chat.type, query)

    # Search the database using the filtered query
    results = await db.search_files(filtered_query, skip=0, limit=10, exact=False)
    
    if not results:
        suggestions = await get_fuzzy_suggestions(query)
        req_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{query[:40]}")]])
        
        if suggestions:
            s_text = ", ".join([f"`{s}`" for s in suggestions])
            await message.reply_text(
                f"😔 No files found matching your criteria.\n\n**Did you mean:** {s_text}?", 
                reply_markup=req_buttons
            )
        else:
            await message.reply_text(
                "😔 No files found matching your criteria across our live shards.", 
                reply_markup=req_buttons
            )
        return
        
    metadata = await fetch_imdb_tmdb(query)
    buttons = []
    
    for file in results:
        db_id = str(file.get("_id", ""))
        buttons.append([InlineKeyboardButton(text=f"📂 {file.get('title', 'Unknown Title')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    buttons.append([
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_0_{query}"),
        InlineKeyboardButton(text="Page 1", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_1_{query}")
    ])
    
    # Check if filters were applied to notify the user
    filter_notice = ""
    if filtered_query != query:
        filter_notice = f"\n✨ **Filters Applied:** `{filtered_query.replace(query, '').strip()}`"

    caption = (
        f"🎬 **{metadata['title']}**\n"
        f"⭐️ Rating: `{metadata['rating']}`\n"
        f"🎭 Genre: `{metadata['genre']}`\n\n"
        f"📝 **Plot:** {metadata['plot']}\n\n"
        f"🔍 Found matching files.{filter_notice}"
    )
    
    try:
        await message.reply_photo(
            photo=metadata["poster"], 
            caption=caption, 
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        await message.reply_text(
            caption, 
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# ==========================================
# --- ORIGINAL RESTORED PAGINATION ---
# ==========================================
@Client.on_callback_query(filters.regex(r"^(next|prev)_(\d+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action, page_str, base_query = callback.data.split("_", 2)
    page = int(page_str)
    limit = 10
    
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    chat_type = callback.message.chat.type
    
    # Dynamically re-apply filters based on settings so pagination doesn't break!
    filtered_query = await get_filtered_query(user_id, chat_id, chat_type, base_query)
    
    results = await db.search_files(filtered_query, skip=page * limit, limit=limit, exact=False)
    
    if not results:
        return await callback.answer("⚠️ No more pages available matching your filters!", show_alert=True)
        
    buttons = []
    for file in results:
        db_id = str(file.get("_id", ""))
        buttons.append([InlineKeyboardButton(text=f"📂 {file.get('title', 'Unknown Title')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    buttons.append([
        InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{max(0, page - 1)}_{base_query}"),
        InlineKeyboardButton(text=f"Page {page + 1}", callback_data="pages_info"),
        InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{page + 1}_{base_query}")
    ])
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await callback.answer()

# ==========================================
# --- ORIGINAL RESTORED INLINE SEARCH ---
# ==========================================
@Client.on_inline_query()
async def inline_search(client: Client, query: InlineQuery):
    search_query = query.query.strip()
    if len(search_query) < 3:
        return await query.answer([])
        
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
