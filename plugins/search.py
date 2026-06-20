import math
import os
import time
import random
import logging
import aiohttp
import json
import urllib.parse
import hashlib
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, 
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery, ReplyParameters, WebAppInfo
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

# --- RAM CACHE SYSTEMS ---
SPAM_TRACKER = {}       
SPAM_COOLDOWN = 3       
QUERY_CACHE = {}        
CACHE_TTL = 300         

BULK_CACHE = {}
BULK_CACHE_TTL = 1800 

SEARCH_STICKERS = [
    "CAACAgIAAxkBAAERau9qNXctqQUyQ4JPHMUlrBCSMmTpRwACvAwAAocoMEntN5GZWCFoBDwE",
    "CAACAgIAAxkBAAERavdqNXraBk9c93sSXemtFwSlSN_RnAAC_iYAAp2TAUsNtzXDZ_a-szwE",
    "CAACAgIAAxkBAAERavlqNXreh03oKow7UUFuKzMlU85awAACnRcAArwzqEn0nAMmwtD6cTwE"
]
GHOST_STICKERS = [
    "CAACAgEAAxkBAAERawtqNX0dllDVZhRw9UkAAeIssj3C9RAAAtEBAAI-HjBHuHEaSdq4kGA8BA"
]

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
            "genre": "Sci-Fi", "plot": "Connect TMDB_API_KEY to unlock actual movie details."
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
    except Exception: pass
    return {"title": query.title(), "rating": "N/A", "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", "genre": "Unknown", "plot": f"Matches for: {query}"}

async def get_fuzzy_suggestions(query: str) -> list:
    first_word = query.split()[0] if query else query
    pool_query = first_word[:4] if len(first_word) >= 4 else first_word
    titles = await db.search_files(pool_query, skip=0, limit=300, exact=False)
    suggestions = []
    query_lower = query.lower()
    for item in titles:
        title = item.get("title", "")
        if not title: continue
        title_lower = title.lower()
        if all(word in title_lower for word in query_lower.split()):
            suggestions.append(title)
            continue
        dist = levenshtein_distance(query_lower, title_lower)
        if dist <= max(2, len(query_lower) // 4):
            suggestions.append(title)
    return list(dict.fromkeys(suggestions))[:3]

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

async def upload_json_payload(data_list):
    json_string = json.dumps(data_list)
    
    # 1. NPOINT
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.npoint.io/", json=data_list, timeout=8) as resp:
                if resp.status == 200:
                    return f"https://api.npoint.io/{(await resp.json())['id']}"
    except Exception as e: logger.error(f"Npoint Cloud Upload Failed: {e}")

    # 2. DPASTE
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://dpaste.com/api/v2/", data={"content": json_string, "syntax": "json"}, timeout=8) as resp:
                if resp.status in [200, 201]:
                    url = (await resp.text()).strip()
                    if url.startswith("http"):
                        return f"{url}.txt"
    except Exception as e: logger.error(f"Dpaste Cloud Upload Failed: {e}")
        
    # 3. RENTRY
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://rentry.co/api/new", data={"text": json_string}, timeout=8) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    if res.get("url"):
                        return f"{res['url']}/raw"
    except Exception as e: logger.error(f"Rentry Cloud Upload Failed: {e}")
        
    return None

def build_safe_webapp_url(client_username, short_id, data_url):
    base_link = getattr(Config, "BULK_LINK", "https://yourusername.github.io/autofilter-web/").strip()
    if not base_link.startswith("http"):
        base_link = f"https://{base_link}"
        
    safe_url = urllib.parse.quote(data_url)
    bot_username = client_username or "Bot"
    
    return f"{base_link}?bot={bot_username}&id={short_id}&url={safe_url}"

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(["start", "help", "about", "source", "settings", "request", "plot", "history", "clear_history", "broadcast", "stats", "backup", "admin", "index", "batch", "migrate_db", "clear_job", "optimize_db", "connect", "disconnect"]))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3: return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_time = time.time()
    
    if user_id in SPAM_TRACKER and current_time - SPAM_TRACKER[user_id] < SPAM_COOLDOWN: return 
    SPAM_TRACKER[user_id] = current_time

    loading_msg = None
    try: loading_msg = await message.reply_sticker(random.choice(SEARCH_STICKERS))
    except Exception: pass

    chat_type = getattr(message.chat, "type", ChatType.PRIVATE)
    resolved_mode, resolved_lang, resolved_size = await get_filter_settings(user_id, chat_id, chat_type)

    cache_key = f"{query.lower()}_{resolved_mode}_{resolved_lang}_{resolved_size}"
    
    if cache_key in QUERY_CACHE:
        cached_time, cached_results = QUERY_CACHE[cache_key]
        if current_time - cached_time < CACHE_TTL: raw_results = cached_results
        else:
            del QUERY_CACHE[cache_key]
            raw_results = None
    else: raw_results = None

    if raw_results is None:
        raw_results = await db.search_files(query, skip=0, limit=10000, exact=False)
        if not raw_results and " " in query:
            raw_results = await db.search_files(query.replace(" ", ""), skip=0, limit=10000, exact=False)
        QUERY_CACHE[cache_key] = (current_time, raw_results)

    min_bytes, max_bytes = SIZE_MAP.get(resolved_size, (0, float('inf')))
    filtered_results = []
    
    for f in raw_results:
        if not (min_bytes <= f.get("size", 0) <= max_bytes): continue
        if resolved_mode == "interactive" and resolved_lang not in ["all", "none"]:
            if resolved_lang.lower() not in f.get("language", "unknown").lower() and resolved_lang.lower() not in f.get("title", "").lower():
                continue
        filtered_results.append(f)

    results = filtered_results[:10]
    
    # 🚀 REMOVED EARLY STICKER DELETION FROM HERE
    
    if not results:
        # If no results, delete the sticker right before sending the suggestions
        if loading_msg:
            try: await loading_msg.delete()
            except Exception: pass
            
        suggestions = await get_fuzzy_suggestions(query)
        btn_list = []
        for s in suggestions: btn_list.append([InlineKeyboardButton(f"🔍 Search: {s}", callback_data=f"fuz_{s[:50]}")])
        btn_list.append([InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{query[:40]}")])
        try: await message.reply_text("😔 **No exact matches found.**", reply_markup=InlineKeyboardMarkup(btn_list), reply_parameters=ReplyParameters(message_id=message.id))
        except Exception: await client.send_message(chat_id, "😔 **No matches found.**", reply_markup=InlineKeyboardMarkup(btn_list))
        return

    metadata = await fetch_imdb_tmdb(query)
    buttons = []
    settings = await db.get_settings()
    shortener_on = settings.get("shortener_enabled", False)

    if settings.get("bulk_enabled", True):
        web_app_results = filtered_results[:1000] 
        short_id = hashlib.md5(f"{user_id}_{query}_{time.time()}".encode()).hexdigest()[:8]
        
        BULK_CACHE[short_id] = (time.time(), web_app_results)
        for k in list(BULK_CACHE.keys()):
            if time.time() - BULK_CACHE[k][0] > BULK_CACHE_TTL: del BULK_CACHE[k]

        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url)
            buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", web_app=WebAppInfo(url=web_app_url))])
        else:
            logger.error("Skipped drawing Bulk Delivery button because Cloud Upload failed completely.")

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        if shortener_on: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{db_id}")])
    
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

    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        filter_notice += f"\n\n⏳ *Note: This search result will automatically delete in {m_time} minutes.*"

    pm_notice = ""
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        pm_notice = "\n\n*(Click a file to receive it securely in your Private Messages)*"

    caption = (
        f"🎬 **{metadata['title']}**\n⭐️ Rating: `{metadata['rating']}`\n🎭 Genre: `{metadata['genre']}`\n\n"
        f"📝 **Plot:** {metadata['plot']}\n\n🔍 Found {len(filtered_results)} matching files.{filter_notice}{pm_notice}"
    )
    
    # 🚀 THE FIX: Now we delete the sticker right here, exactly before sending the final message!
    if loading_msg:
        try: await loading_msg.delete()
        except Exception: pass
        
    try: msg = await message.reply_photo(photo=metadata["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons), reply_parameters=ReplyParameters(message_id=message.id))
    except Exception: msg = await client.send_message(chat_id, caption, reply_markup=InlineKeyboardMarkup(buttons))

    if settings.get("filter_delete_enabled", False):
        from plugins.advanced import trigger_ghost_self_destruct
        trigger_ghost_self_destruct(client, chat_id, msg.id, settings.get("filter_delete_time", 5) * 60)

@Client.on_callback_query(filters.regex(r"^(next|prev)_(\d+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action, page_str, base_query = callback.data.split("_", 2)
    page = int(page_str)
    
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    chat_type = callback.message.chat.type
    resolved_mode, resolved_lang, resolved_size = await get_filter_settings(user_id, chat_id, chat_type)

    raw_results = await db.search_files(base_query, skip=0, limit=10000, exact=False)
    if not raw_results and " " in base_query: raw_results = await db.search_files(base_query.replace(" ", ""), skip=0, limit=10000, exact=False)
    
    min_bytes, max_bytes = SIZE_MAP.get(resolved_size, (0, float('inf')))
    filtered_results = []
    for f in raw_results:
        if not (min_bytes <= f.get("size", 0) <= max_bytes): continue
        if resolved_mode == "interactive" and resolved_lang not in ["all", "none"]:
            if resolved_lang.lower() not in f.get("language", "unknown").lower() and resolved_lang.lower() not in f.get("title", "").lower():
                continue
        filtered_results.append(f)
    
    results = filtered_results[page * 10 : (page + 1) * 10]
    if not results: return await callback.answer("⚠️ No more pages available matching your filters!", show_alert=True)
        
    buttons = []
    settings = await db.get_settings()
    shortener_on = settings.get("shortener_enabled", False)

    if settings.get("bulk_enabled", True):
        web_app_results = filtered_results[:1000] 
        short_id = hashlib.md5(f"{user_id}_{base_query}_{time.time()}".encode()).hexdigest()[:8]
        BULK_CACHE[short_id] = (time.time(), web_app_results)
        
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url)
            buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", web_app=WebAppInfo(url=web_app_url))])

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        if shortener_on: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text=AD_SLOT_TEXT, url=AD_SLOT_URL)])
    total_pages = math.ceil(len(filtered_results) / 10)
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{page - 1}_{base_query}"))
    nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
    if len(filtered_results) > (page + 1) * 10: nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{page + 1}_{base_query}"))
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
        articles.append(InlineQueryResultArticle(title=file.get("title", "Unknown File"), description=f"Size: {format_size(file.get('size', 0))}", input_message_content=InputTextMessageContent(message_text=f"**{file.get('title')}**\n\n📥 [Download File Here](https://t.me/{client.me.username}?start=getfile_{db_id})"), thumb_url="https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=150", id=str(idx)))
    await query.answer(articles, cache_time=3600, is_personal=True)
