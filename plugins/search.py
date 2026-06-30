import math
import os
import time
import random
import logging
import aiohttp
import json
import urllib.parse
import hashlib
import asyncio
import uuid
from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ChatType
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, 
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, CallbackQuery, ReplyParameters, WebAppInfo, InputMediaPhoto
)
from database.multi_db import db
from config import Config
from plugins.moderation import SCRAPER_TRACKER

# 🚀 Import our new Extensible Filter Engine!
from plugins.search_filters import get_filter_settings, apply_search_filters, SIZE_MAP

logger = logging.getLogger(__name__)

# --- RAM CACHE SYSTEMS ---
SPAM_TRACKER = {}       
SPAM_COOLDOWN = 3       
QUERY_CACHE = {}        
CACHE_TTL = 300         

BULK_CACHE = {}
BULK_CACHE_TTL = 1800 

# 🚀 NEW: Multi Search Cache
MULTI_SEARCH_CACHE = {}
MULTI_SEARCH_TTL = 900 # 15 minutes

SEARCH_STICKERS = [
    "CAACAgIAAxkBAAERau9qNXctqQUyQ4JPHMUlrBCSMmTpRwACvAwAAocoMEntN5GZWCFoBDwE",
    "CAACAgIAAxkBAAERavdqNXraBk9c93sSXemtFwSlSN_RnAAC_iYAAp2TAUsNtzXDZ_a-szwE",
    "CAACAgIAAxkBAAERavlqNXreh03oKow7UUFuKzMlU85awAACnRcAArwzqEn0nAMmwtD6cTwE"
]
GHOST_STICKERS = [
    "CAACAgEAAxkBAAERawtqNX0dllDVZhRw9UkAAeIssj3C9RAAAtEBAAI-HjBHuHEaSdq4kGA8BA"
]
BULK_BANNER = "https://telegra.ph/file/f8b495d98fd4d89c99150.jpg"

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
            "genre": "Sci-Fi", "plot": "Connect TMDB_API_KEY to unlock actual movie details.",
            "release_date": "Unknown", "runtime": "N/A", "language": "en"
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
                            "poster": poster_url, "genre": "Drama", "plot": movie.get("overview", "No overview available."),
                            "release_date": movie.get("release_date", "Unknown"), "language": movie.get("original_language", "en")
                        }
    except Exception: pass
    return {"title": query.title(), "rating": "N/A", "poster": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600", "genre": "Unknown", "plot": f"Matches for: {query}", "release_date": "Unknown", "language": "Unknown"}

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

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

async def upload_json_payload(data_list):
    json_string = json.dumps(data_list)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.npoint.io/", json=data_list, timeout=8) as resp:
                if resp.status == 200:
                    return f"https://api.npoint.io/{(await resp.json())['id']}"
    except Exception as e: logger.error(f"Npoint Cloud Upload Failed: {e}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://dpaste.com/api/v2/", data={"content": json_string, "syntax": "json"}, timeout=8) as resp:
                if resp.status in [200, 201]:
                    url = (await resp.text()).strip()
                    if url.startswith("http"):
                        return f"{url}.txt"
    except Exception as e: logger.error(f"Dpaste Cloud Upload Failed: {e}")
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

def get_progress_bar(current, total):
    percent = current / total if total > 0 else 0
    filled = int(percent * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"{bar} {int(percent * 100)}%"

def build_bulk_summary_text(found, not_found, time_taken):
    text = "🎬 **Bulk Search Results**\n━━━━━━━━━━━━━━━━━━\n\n**Found**\n"
    for movie, files in found:
        text += f"🍿 {movie}\n`{len(files)} Files`\n\n"
    if not found:
        text += "No movies found.\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━\n"
    if not_found:
        text += "**Not Found**\n"
        for movie in not_found: text += f"❌ {movie}\n"
        
    text += f"\n⏱ *Completed in {time_taken:.2f} Seconds*"
    return text

# ==========================================
# 🚀 ADMIN COMMAND: CONFIG MULTI-SEARCH
# ==========================================
@Client.on_message(filters.command("setmultisearch") & filters.user(Config.ADMINS))
async def set_multi_search_limit(client: Client, message: Message):
    if len(message.command) < 2:
        settings = await db.get_settings()
        limit = settings.get("multi_search_limit", 5)
        status = f"{limit} movies/search" if limit > 0 else "Disabled"
        return await message.reply_text(f"⚙️ **Multi Search Settings**\n\nCurrently: `{status}`\n\nTo change, use:\n`/setmultisearch <number>` (e.g. `/setmultisearch 10`)\n`/setmultisearch off` (to disable)")
    
    arg = message.command[1].strip().lower()
    if arg == "off":
        await db.update_settings({"multi_search_limit": 0})
        await message.reply_text("✅ Multi-Movie search has been **disabled**.")
    elif arg.isdigit():
        new_limit = int(arg)
        await db.update_settings({"multi_search_limit": new_limit})
        await message.reply_text(f"✅ Multi-Movie search limit updated to **{new_limit} movies per request**.")
    else:
        await message.reply_text("❌ Invalid input. Use a number or 'off'.")
    raise StopPropagation

# ==========================================
# 🚀 CORE SEARCH ENGINE (HANDLES BOTH)
# ==========================================
@Client.on_message((filters.group | filters.private) & filters.text & ~filters.regex(r"^/"))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3: return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_time = time.time()
    
    # 🚀 NEW: Smart Group Connection Interceptor
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        is_connected = await db.is_group_connected(chat_id)
        if not is_connected:
            return await message.reply_text("⚠️ **Group Not Connected**\n\nThis group is not connected to my database. Please ask a Group Admin to type `/connect` to activate movie searches!")

    # 🚨 1. Scraper Protection Layer
    if user_id not in SCRAPER_TRACKER: SCRAPER_TRACKER[user_id] = []
    SCRAPER_TRACKER[user_id].append(current_time)
    SCRAPER_TRACKER[user_id] = [t for t in SCRAPER_TRACKER[user_id] if current_time - t < 60]
    
    if len(SCRAPER_TRACKER[user_id]) > 50:
        await db.add_punishment(user_id, "global", "ban", reason="Automated Scraper Detection.")
        return await message.reply_text("🚫 **SECURITY LOCK:** You have been permanently banned globally for API scraping.")

    # ⚖️ 2. Lazy Evaluation Interception
    p_type, p_reason, p_expiry, p_scope = await db.check_punishment(user_id, str(chat_id))
    if p_type:
        lock_msg = f"🚫 You are **{p_type.upper()}ED** " + ("globally." if p_scope == "global" else "in this group.")
        lock_msg += f"\nReason: {p_reason}"
        if p_type == "mute" and p_expiry > 0: lock_msg += f"\nUnlocks: <t:{int(p_expiry)}:R>"
        
        if p_scope == "global" and message.chat.type != ChatType.PRIVATE:
            bot_me = await client.get_me()
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Appeal in PM", url=f"https://t.me/{bot_me.username}?start=appeal_{p_type}")]])
        else:
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Appeal", callback_data=f"appeal_{p_scope}_{p_type}")]])
            
        return await message.reply_text(lock_msg, reply_markup=btn)

    await asyncio.create_task(db.add_search_count(user_id))
    
    if user_id in SPAM_TRACKER and current_time - SPAM_TRACKER[user_id] < SPAM_COOLDOWN: return 
    SPAM_TRACKER[user_id] = current_time

    chat_type = getattr(message.chat, "type", ChatType.PRIVATE)
    resolved_mode, resolved_lang, resolved_size = await get_filter_settings(user_id, chat_id, chat_type)
    settings = await db.get_settings()
    
    # ==========================================
    # 🌟 MULTI-MOVIE BULK SEARCH LOGIC
    # ==========================================
    lines = [line.strip() for line in query.split('\n') if len(line.strip()) > 2]
    unique_movies = []
    for m in lines:
        if m not in unique_movies: unique_movies.append(m)
        
    if len(unique_movies) > 1:
        multi_limit = settings.get("multi_search_limit", 5)
        if multi_limit == 0: return await message.reply_text("❌ Multi-movie search is currently disabled by admins.")
        if len(unique_movies) > multi_limit:
            return await message.reply_text(f"❌ **Maximum allowed movies per search exceeded.**\n\nAllowed : `{multi_limit}`\nRequested : `{len(unique_movies)}`")

        start_time = time.time()
        session_id = str(uuid.uuid4())[:8]
        
        initial_text = "🎬 **Bulk Movie Search**\n━━━━━━━━━━━━━━━━━━\n**Movies**\n"
        for i, m in enumerate(unique_movies, 1): initial_text += f"{i}. {m}\n"
        initial_text += "━━━━━━━━━━━━━━━━━━\n*Preparing search...*"
        
        try: progress_msg = await message.reply_photo(photo=BULK_BANNER, caption=initial_text)
        except Exception: progress_msg = await message.reply_text(initial_text)

        found_movies = []
        not_found_movies = []

        for idx, movie in enumerate(unique_movies):
            prog_text = "🔍 **Searching Movies...**\n\n"
            for prev_idx in range(idx): prog_text += f"✅ {unique_movies[prev_idx]}\n"
            prog_text += f"🟢 {movie}\n"
            for next_idx in range(idx + 1, len(unique_movies)): prog_text += f"⚪ {unique_movies[next_idx]}\n"
            prog_text += f"\nProgress\n`{get_progress_bar(idx, len(unique_movies))}`"
            
            try: await progress_msg.edit_caption(prog_text) if progress_msg.photo else await progress_msg.edit_text(prog_text)
            except Exception: pass
            
            # Execute Search and Filter
            raw_results = await db.search_files(movie, skip=0, limit=10000, exact=False)
            filtered = apply_search_filters(raw_results, resolved_mode, resolved_lang, resolved_size)
            
            if filtered: found_movies.append((movie, filtered[:10000])) # Save all found for bulk delivery later
            else: not_found_movies.append(movie)
            
            await asyncio.sleep(0.4) 

        total_time = time.time() - start_time
        summary_text = build_bulk_summary_text(found_movies, not_found_movies, total_time)
        
        buttons = []
        for i, (m_name, files) in enumerate(found_movies):
            buttons.append([InlineKeyboardButton(f"{m_name} ({len(files)})", callback_data=f"bms_sel_{session_id}_{i}_0")])
            
        MULTI_SEARCH_CACHE[session_id] = {
            "timestamp": time.time(),
            "user_id": user_id,
            "found": found_movies,
            "not_found": not_found_movies,
            "summary_text": summary_text,
            "buttons": buttons
        }
        
        try: await progress_msg.edit_caption(summary_text, reply_markup=InlineKeyboardMarkup(buttons)) if progress_msg.photo else await progress_msg.edit_text(summary_text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception: pass

        # 👉 RESTORED: Auto-delete for Multi-Search
        if settings.get("filter_delete_enabled", False):
            from plugins.advanced import trigger_ghost_self_destruct
            trigger_ghost_self_destruct(client, chat_id, progress_msg.id, settings.get("filter_delete_time", 5) * 60)
            
        return

    # ==========================================
    # 🌟 NORMAL SINGLE SEARCH LOGIC
    # ==========================================
    loading_msg = None
    try: loading_msg = await message.reply_sticker(random.choice(SEARCH_STICKERS))
    except Exception: pass

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

    filtered_results = apply_search_filters(raw_results, resolved_mode, resolved_lang, resolved_size)
    results = filtered_results[:10]
    
    if not results:
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
    shortener_on = settings.get("shortener_enabled", False)

    # 👉 RESTORED: Bulk Delivery for Single Search
    if settings.get("bulk_enabled", True):
        web_app_results = filtered_results[:10000] 
        short_id = hashlib.md5(f"{user_id}_{query}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url)
            
            BULK_CACHE[short_id] = (time.time(), web_app_results, web_app_url)
            for k in list(BULK_CACHE.keys()):
                if time.time() - BULK_CACHE[k][0] > BULK_CACHE_TTL: del BULK_CACHE[k]

            if chat_type == ChatType.PRIVATE:
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", web_app=WebAppInfo(url=web_app_url))])
            else:
                bot_url = f"https://t.me/{client.me.username}?start=bapp_{short_id}"
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", url=bot_url)])
        else:
            logger.error("Skipped drawing Bulk Delivery button because Cloud Upload failed completely.")

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        if shortener_on: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{db_id}")])
    
    # 👉 RESTORED: Help Us button
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
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
    
    if loading_msg:
        try: await loading_msg.delete()
        except Exception: pass
        
    try: msg = await message.reply_photo(photo=metadata["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons), reply_parameters=ReplyParameters(message_id=message.id))
    except Exception: msg = await client.send_message(chat_id, caption, reply_markup=InlineKeyboardMarkup(buttons))

    if settings.get("filter_delete_enabled", False):
        from plugins.advanced import trigger_ghost_self_destruct
        trigger_ghost_self_destruct(client, chat_id, msg.id, settings.get("filter_delete_time", 5) * 60)


# ==========================================
# 🌟 MULTI-SEARCH CALLBACKS
# ==========================================
@Client.on_callback_query(filters.regex(r"^bms_sel_(.+)_(.+)_(\d+)"))
async def handle_bulk_movie_select(client: Client, callback: CallbackQuery):
    session_id = callback.matches[0].group(1)
    movie_idx = int(callback.matches[0].group(2))
    page = int(callback.matches[0].group(3))
    
    if session_id not in MULTI_SEARCH_CACHE or time.time() - MULTI_SEARCH_CACHE[session_id]["timestamp"] > MULTI_SEARCH_TTL:
        return await callback.answer("⏳ Session Expired! Please search again.", show_alert=True)
        
    session_data = MULTI_SEARCH_CACHE[session_id]
    movie_name, files = session_data["found"][movie_idx]
    
    if page == 0: await callback.answer(f"Fetching details for {movie_name}...", show_alert=False)
    else: await callback.answer()
    
    metadata = await fetch_imdb_tmdb(movie_name)
    settings = await db.get_settings()
    shortener_on = settings.get("shortener_enabled", False)
    
    # Get the paginated results for this specific movie
    results = files[page * 10 : (page + 1) * 10]
    
    buttons = []
    user_id = callback.from_user.id
    chat_type = callback.message.chat.type
    
    # 👉 RESTORED: Bulk WebApp Delivery explicitly added into Multi-Search!
    if settings.get("bulk_enabled", True):
        web_app_results = files[:1000] 
        short_id = hashlib.md5(f"{user_id}_{movie_name}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url)
            
            BULK_CACHE[short_id] = (time.time(), web_app_results, web_app_url)
            for k in list(BULK_CACHE.keys()):
                if time.time() - BULK_CACHE[k][0] > BULK_CACHE_TTL: del BULK_CACHE[k]

            if chat_type == ChatType.PRIVATE:
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", web_app=WebAppInfo(url=web_app_url))])
            else:
                bot_url = f"https://t.me/{client.me.username}?start=bapp_{short_id}"
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", url=bot_url)])

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        if shortener_on: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{db_id}")])
    
    # 👉 RESTORED: Help Us Button in Multi-Search
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
    # 👉 RESTORED: Pagination in Multi-Search
    if len(files) > 10:
        total_pages = math.ceil(len(files) / 10)
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"bms_sel_{session_id}_{movie_idx}_{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(files) > (page + 1) * 10: nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"bms_sel_{session_id}_{movie_idx}_{page + 1}"))
        buttons.append(nav_buttons)

    # Back to Movie List
    buttons.append([InlineKeyboardButton("⬅ Back to Movie List", callback_data=f"bms_back_{session_id}")])
    
    caption = f"🎬 **{metadata['title']}**\n🗓 Year: `{metadata['release_date'][:4]}` | ⭐️ `{metadata['rating']}`\n🎭 Genre: `{metadata['genre']}`\n🗣 Language: `{metadata['language'].upper()}`\n\n📝 **Plot:** {metadata['plot']}\n\n🔍 Found {len(files)} matching files."
    
    try:
        await callback.message.edit_media(InputMediaPhoto(media=metadata["poster"], caption=caption))
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e: 
        logger.error(f"Failed to edit bulk media: {e}")
        try: await callback.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception: pass

@Client.on_callback_query(filters.regex(r"^bms_back_(.+)"))
async def handle_bulk_movie_back(client: Client, callback: CallbackQuery):
    session_id = callback.matches[0].group(1)
    
    if session_id not in MULTI_SEARCH_CACHE or time.time() - MULTI_SEARCH_CACHE[session_id]["timestamp"] > MULTI_SEARCH_TTL:
        return await callback.answer("⏳ Session Expired! Please search again.", show_alert=True)
        
    session_data = MULTI_SEARCH_CACHE[session_id]
    
    try:
        await callback.message.edit_media(InputMediaPhoto(media=BULK_BANNER, caption=session_data["summary_text"]))
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(session_data["buttons"]))
    except Exception:
        try: await callback.message.edit_text(session_data["summary_text"], reply_markup=InlineKeyboardMarkup(session_data["buttons"]))
        except Exception: pass
        
    await callback.answer()


# ==========================================
# 🌟 NORMAL PAGINATION CALLBACKS
# ==========================================
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
    
    filtered_results = apply_search_filters(raw_results, resolved_mode, resolved_lang, resolved_size)
    
    results = filtered_results[page * 10 : (page + 1) * 10]
    if not results: return await callback.answer("⚠️ No more pages available matching your filters!", show_alert=True)
        
    buttons = []
    settings = await db.get_settings()
    shortener_on = settings.get("shortener_enabled", False)

    # 👉 RESTORED: Bulk Delivery in Single Search Pagination
    if settings.get("bulk_enabled", True):
        web_app_results = filtered_results[:1000] 
        short_id = hashlib.md5(f"{user_id}_{base_query}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url)
            
            BULK_CACHE[short_id] = (time.time(), web_app_results, web_app_url)
            for k in list(BULK_CACHE.keys()):
                if time.time() - BULK_CACHE[k][0] > BULK_CACHE_TTL: del BULK_CACHE[k]

            if chat_type == ChatType.PRIVATE:
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", web_app=WebAppInfo(url=web_app_url))])
            else:
                bot_url = f"https://t.me/{client.me.username}?start=bapp_{short_id}"
                buttons.insert(0, [InlineKeyboardButton(text=f"☑️ Select Multiple Movies ({len(web_app_results)})", url=bot_url)])

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        if shortener_on: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{db_id}")])
    
    # 👉 RESTORED: Help Us
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
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
