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
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent, 
    CallbackQuery, ReplyParameters, WebAppInfo, InputMediaPhoto,
    InlineQueryResultCachedDocument
)
from plugins.monetization import check_double_fsub
from database.multi_db import db
from config import Config
from plugins.moderation import SCRAPER_TRACKER
from plugins.search_filters import get_filter_settings, apply_search_filters, SIZE_MAP

logger = logging.getLogger(__name__)

# ==========================================
# 🔐 SESSION SECURITY TOKEN (Restart Kill-Switch)
# ==========================================
BOT_SESSION_TOKEN = str(uuid.uuid4())[:6]

# --- RAM CACHE SYSTEMS ---
SPAM_TRACKER = {}       
SPAM_COOLDOWN = 3       
QUERY_CACHE = {}        
CACHE_TTL = 300         

BULK_CACHE = {}
BULK_CACHE_TTL = 1800 

MULTI_SEARCH_CACHE = {}
MULTI_SEARCH_TTL = 900 

SEARCH_STICKERS = [
    "CAACAgIAAxkBAAERau9qNXctqQUyQ4JPHMUlrBCSMmTpRwACvAwAAocoMEntN5GZWCFoBDwE",
    "CAACAgIAAxkBAAERavdqNXraBk9c93sSXemtFwSlSN_RnAAC_iYAAp2TAUsNtzXDZ_a-szwE",
    "CAACAgIAAxkBAAERavlqNXreh03oKow7UUFuKzMlU85awAACnRcAArwzqEn0nAMmwtD6cTwE"
]
BULK_BANNER = "https://telegra.ph/file/f8b495d98fd4d89c99150.jpg"

LANG_MAP = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam", "kn": "Kannada", "ja": "Japanese", "ko": "Korean", "es": "Spanish", "fr": "French"}

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
    tmdb_keys = getattr(Config, "TMDB_API_KEYS", [])
    default_meta = {
        "title": query.title(), "rating": "N/A", 
        "poster": Config.DEFAULT_POSTER, 
        "genre": "Unknown", "plot": f"Search results for: {query}", 
        "release_date": "Unknown", "language": "Unknown"
    }
    
    if not tmdb_keys:
        from plugins.smart_suggestions import get_imdb_poster_fallback
        poster = await get_imdb_poster_fallback(query)
        if poster: default_meta["poster"] = poster
        return default_meta
        
    for key in tmdb_keys:
        url = f"https://api.themoviedb.org/3/search/multi?api_key={key}&query={urllib.parse.quote(query)}&page=1"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=3) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("results"):
                            media_results = [r for r in data["results"] if r.get("media_type") in ["movie", "tv"]]
                            if media_results:
                                item = media_results[0]
                                
                                title = item.get("title") or item.get("name") or query.title()
                                release_date = item.get("release_date") or item.get("first_air_date") or "Unknown Date"
                                lang_code = item.get("original_language", "en")
                                lang_full = LANG_MAP.get(lang_code, lang_code.upper())
                                rating = round(item.get('vote_average', 0), 1)
                                
                                poster_url = f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get("poster_path") else default_meta["poster"]
                                
                                return {
                                    "title": title, 
                                    "rating": f"{rating}/10 ⭐" if rating > 0 else "N/A", 
                                    "poster": poster_url, 
                                    "genre": "Movie" if item.get("media_type") == "movie" else "TV Series", 
                                    "plot": item.get("overview", "No plot overview available."),
                                    "release_date": release_date, 
                                    "language": lang_full
                                }
        except Exception: continue
    return default_meta

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
                if resp.status == 200: return f"https://api.npoint.io/{(await resp.json())['id']}"
    except Exception: pass
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://dpaste.com/api/v2/", data={"content": json_string, "syntax": "json"}, timeout=8) as resp:
                if resp.status in [200, 201]:
                    url = (await resp.text()).strip()
                    if url.startswith("http"): return f"{url}.txt"
    except Exception: pass
    return None

def build_safe_webapp_url(client_username, short_id, data_url, user_limit, is_vip=False):
    base_link = getattr(Config, "BULK_LINK", "https://yourusername.github.io/autofilter-web/").strip()
    if not base_link.startswith("http"): base_link = f"https://{base_link}"
    safe_url = urllib.parse.quote(data_url)
    bot_username = client_username or "Bot"
    tier = "premium" if is_vip else "free"
    return f"{base_link}?bot={bot_username}&id={short_id}&limit={user_limit}&tier={tier}&url={safe_url}"

def get_progress_bar(current, total):
    percent = current / total if total > 0 else 0
    filled = int(percent * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"{bar} {int(percent * 100)}%"

def build_bulk_summary_text(found, not_found, time_taken):
    text = "🎬 **Bulk Search Results**\n━━━━━━━━━━━━━━━━━━\n\n**✅ Found**\n"
    for movie, files in found: text += f"🍿 {movie}\n`{len(files)} Files`\n\n"
    if not found: text += "No exact matches found.\n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    if not_found:
        text += "**❌ Not Found (Did you mean?)**\n"
        for movie, suggestion in not_found:
            if suggestion: text += f"❌ {movie} ➡️ *Try: {suggestion}*\n"
            else: text += f"❌ {movie} *(No suggestions)*\n"
    text += f"\n⏱ *Completed in {time_taken:.2f} Seconds*"
    return text

# ==========================================
# 🚀 CORE SEARCH ENGINE
# ==========================================
@Client.on_message((filters.group | filters.private) & filters.text & ~filters.regex(r"^/"))
async def auto_filter(client: Client, message: Message):
    query = message.text.strip()
    if len(query) < 3: return

    query_lower = query.lower()
    if "@admin" in query_lower or "@admins" in query_lower: return
        
    user_id = message.from_user.id
    chat_id = message.chat.id
    current_time = time.time()
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        is_connected = await db.is_group_connected(chat_id)
        if not is_connected:
            return await message.reply_text("⚠️ **Group Not Connected**\n\nThis group is not connected to my database. Please ask a Group Admin to type `/connect` to activate movie searches!")

    # Scraper Protection Layer
    if user_id not in SCRAPER_TRACKER: SCRAPER_TRACKER[user_id] = []
    SCRAPER_TRACKER[user_id].append(current_time)
    SCRAPER_TRACKER[user_id] = [t for t in SCRAPER_TRACKER[user_id] if current_time - t < 60]
    if len(SCRAPER_TRACKER[user_id]) > 50:
        await db.add_punishment(user_id, "global", "ban", reason="Automated Scraper Detection.")
        return await message.reply_text("🚫 **SECURITY LOCK:** You have been permanently banned globally for API scraping.")

    # Lazy Evaluation Interception
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
    
    from plugins.vip_system import get_all_plans, FREE_USER_LIMITS
    active_plan = await db.get_active_vip_plan(user_id)
    plans = await get_all_plans()
    user_limits = plans.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan and active_plan in plans else FREE_USER_LIMITS
    
    # ==========================================
    # 🌟 MULTI-MOVIE BULK SEARCH LOGIC
    # ==========================================
    lines = [line.strip() for line in query.split('\n') if len(line.strip()) > 2]
    unique_movies = []
    for m in lines:
        if m not in unique_movies: unique_movies.append(m)

    history_entries = [{"type": "search", "query": m} for m in unique_movies]
    await db.users.update_one(
        {"user_id": user_id},
        {"$push": {"search_history": {"$each": history_entries, "$slice": -10}}},
        upsert=True
    )
        
    if len(unique_movies) > 1:
        # 🚀 MASTER TOGGLE CHECK
        if not settings.get("multi_search_enabled", True):
            return await message.reply_text("⚠️ **Due to a technical issue, Multi-Search is temporarily paused for everyone. Please wait and stay with us, we will make Multi-Search faster as soon as possible!**")

        # VIP LIMIT CHECK
        multi_limit = user_limits.get("multi_search_limit", 1)
        if multi_limit == 0: return await message.reply_text("❌ Multi-movie search is currently disabled for your tier.")
        if len(unique_movies) > multi_limit:
            return await message.reply_text(f"❌ **Maximum allowed movies per search exceeded.**\n\nYour Limit : `{multi_limit}`\nRequested : `{len(unique_movies)}`\n\n_Upgrade to a higher VIP tier to search more at once!_")

        start_time = time.time()
        session_id = str(uuid.uuid4())[:8]
        
        initial_text = "🎬 **Bulk Movie Search**\n━━━━━━━━━━━━━━━━━━\n**Movies**\n"
        for i, m in enumerate(unique_movies, 1): initial_text += f"{i}. {m}\n"
        initial_text += "━━━━━━━━━━━━━━━━━━\n*Preparing search...*"
        
        try: progress_msg = await message.reply_photo(photo=BULK_BANNER, caption=initial_text)
        except Exception: progress_msg = await message.reply_text(initial_text)

        found_movies, not_found_movies = [], []

        for idx, movie in enumerate(unique_movies):
            prog_text = "🔍 **Searching Movies...**\n\n"
            for prev_idx in range(idx): prog_text += f"✅ {unique_movies[prev_idx]}\n"
            prog_text += f"🟢 {movie}\n"
            for next_idx in range(idx + 1, len(unique_movies)): prog_text += f"⚪ {unique_movies[next_idx]}\n"
            prog_text += f"\nProgress\n`{get_progress_bar(idx, len(unique_movies))}`"
            
            try: await progress_msg.edit_caption(prog_text) if progress_msg.photo else await progress_msg.edit_text(prog_text)
            except Exception: pass
            
            raw_results = await db.search_files(movie, skip=0, limit=10000, exact=False)
            if not raw_results and " " in movie:
                raw_results = await db.search_files(movie.replace(" ", ""), skip=0, limit=10000, exact=False)
                
            filtered = apply_search_filters(raw_results, resolved_mode, resolved_lang, resolved_size)
            
            if filtered: 
                found_movies.append((movie, filtered[:10000])) 
            else: 
                from plugins.smart_suggestions import fetch_smart_spellcheck
                suggestions = await fetch_smart_spellcheck(movie)
                top_suggestion = suggestions[0] if suggestions else None
                not_found_movies.append((movie, top_suggestion))
            
            await asyncio.sleep(0.4) 

        total_time = time.time() - start_time
        summary_text = build_bulk_summary_text(found_movies, not_found_movies, total_time)
        
        # 🚀 INJECT AUTO-DELETE INTIMATION INTO THE SUMMARY
        if settings.get("filter_delete_enabled", False):
            m_time = settings.get("filter_delete_time", 5)
            summary_text += f"\n\n⏳ *Note: This message auto-deletes in {m_time} minutes.*"
        
        buttons = []
        for i, (m_name, files) in enumerate(found_movies):
            buttons.append([InlineKeyboardButton(f"{m_name} ({len(files)})", callback_data=f"bms_sel_{BOT_SESSION_TOKEN}_{session_id}_{i}_0_{user_id}")])
            
        MULTI_SEARCH_CACHE[session_id] = {
            "timestamp": time.time(), "user_id": user_id, "found": found_movies,
            "not_found": not_found_movies, "summary_text": summary_text, "buttons": buttons
        }
        
        final_markup = InlineKeyboardMarkup(buttons) if buttons else None
        
        try: await progress_msg.edit_caption(summary_text, reply_markup=final_markup) if progress_msg.photo else await progress_msg.edit_text(summary_text, reply_markup=final_markup)
        except Exception: pass

        if settings.get("filter_delete_enabled", False):
            from plugins.advanced import trigger_ghost_self_destruct
            del_time = settings.get("filter_delete_time", 5) * 60
            trigger_ghost_self_destruct(client, chat_id, progress_msg.id, del_time)
            
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
            
        from plugins.smart_suggestions import fetch_smart_spellcheck
        suggestions = await fetch_smart_spellcheck(query)
        req_enabled = settings.get("requests_enabled", True)
        
        btn_list = []
        if suggestions:
            for s in suggestions: 
                btn_list.append([InlineKeyboardButton(f"🎬 {s[:40]}", callback_data=f"fuzzy_{s[:40]}")])
        
        if req_enabled:
            btn_list.append([InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{BOT_SESSION_TOKEN}_{user_id}_{query[:30]}")])
            
        if suggestions:
            btn_list.append([InlineKeyboardButton("❌ Cancel", callback_data="close_data")])
            text = f"❌ **No exact match found for '{query}'.**\n\n*Did you mean to search for one of these?*"
        else:
            if req_enabled: text = f"😔 **No exact matches found for '{query}'.**"
            else: text = f"😔 We searched everywhere, but **{query}** isn't in our catalog right now. We add hundreds of new movies automatically every day, so please check back soon!"

        try: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(btn_list) if btn_list else None, reply_parameters=ReplyParameters(message_id=message.id))
        except Exception: await client.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(btn_list) if btn_list else None)
        return

    metadata = await fetch_imdb_tmdb(query)
    buttons = []
    
    has_bypass = user_limits.get("shortlink_bypass", False)
    if not has_bypass: has_bypass = await db.has_active_verification_pass(user_id)
    shortener_on = settings.get("shortener_enabled", False) and not has_bypass

    if settings.get("bulk_enabled", True):
        bulk_limit = user_limits.get("bulk_select_limit", 10)
        web_app_results = filtered_results[:10000] 
        short_id = hashlib.md5(f"{user_id}_{query}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        
        if data_url:
            is_vip = True if active_plan else False
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url, bulk_limit, is_vip)
            
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
        if shortener_on: 
            buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        else: 
            buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{BOT_SESSION_TOKEN}_{user_id}_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
    if len(filtered_results) > 10:
        total_pages = math.ceil(len(filtered_results) / 10)
        buttons.append([
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{BOT_SESSION_TOKEN}_{user_id}_0_{query}"),
            InlineKeyboardButton(text=f"Page 1 of {total_pages}", callback_data="pages_info"),
            InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{BOT_SESSION_TOKEN}_{user_id}_1_{query}")
        ])
    
    filter_notice = ""
    if resolved_mode == "interactive" and (resolved_lang != "all" or resolved_size != "all"):
        filter_notice = f"\n✨ **Filters Applied:** Size: `{resolved_size.upper()}` | Audio: `{resolved_lang.upper()}`"

    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        filter_notice += f"\n\n⏳ *Note: This message auto-deletes in {m_time} minutes.*"

    pm_notice = ""
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        pm_notice = "\n\n*(Click a file to receive it securely in your Private Messages)*"

    caption = (
        f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
        f"⭐️ **Rating:** `{metadata['rating']}`\n"
        f"🗣 **Language:** `{metadata['language']}`\n"
        f"🎭 **Type:** `{metadata['genre']}`\n\n"
        f"📝 **Synopsis:**\n_{metadata['plot']}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 **Found:** `{len(filtered_results)}` matching files.{filter_notice}{pm_notice}"
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
@Client.on_callback_query(filters.regex(r"^bms_sel_(.+)_(.+)_(.+)_(\d+)_(.+)"))
async def handle_bulk_movie_select(client: Client, callback: CallbackQuery):
    token = callback.matches[0].group(1)
    session_id = callback.matches[0].group(2)
    movie_idx = int(callback.matches[0].group(3))
    page = int(callback.matches[0].group(4))
    searcher_id = int(callback.matches[0].group(5))
    
    if token != BOT_SESSION_TOKEN:
        return await callback.answer("⚠️ Session expired due to bot update/restart. Please search again!", show_alert=True)
    if callback.from_user.id != searcher_id:
        return await callback.answer("⚠️ This multi-search wasn't requested by you. Please search your own!", show_alert=True)
    
    if session_id not in MULTI_SEARCH_CACHE or time.time() - MULTI_SEARCH_CACHE[session_id]["timestamp"] > MULTI_SEARCH_TTL:
        return await callback.answer("⏳ Session Expired! Please search again.", show_alert=True)
        
    session_data = MULTI_SEARCH_CACHE[session_id]
    movie_name, files = session_data["found"][movie_idx]
    
    if page == 0: await callback.answer(f"Fetching details for {movie_name}...", show_alert=False)
    else: await callback.answer()
    
    from plugins.vip_system import DEFAULT_PLANS, FREE_USER_LIMITS
    user_id = callback.from_user.id
    active_plan = await db.get_active_vip_plan(user_id)
    user_limits = DEFAULT_PLANS.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan else FREE_USER_LIMITS
    
    metadata = await fetch_imdb_tmdb(movie_name)
    settings = await db.get_settings()
    
    has_bypass = user_limits.get("shortlink_bypass", False)
    if not has_bypass: has_bypass = await db.has_active_verification_pass(user_id)
    shortener_on = settings.get("shortener_enabled", False) and not has_bypass
    
    results = files[page * 10 : (page + 1) * 10]
    buttons = []
    chat_type = callback.message.chat.type
    
    if settings.get("bulk_enabled", True):
        bulk_limit = user_limits.get("bulk_select_limit", 10)
        web_app_results = files[:10000]
        short_id = hashlib.md5(f"{user_id}_{movie_name}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        if data_url:
            is_vip = True if active_plan else False
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url, bulk_limit, is_vip)
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
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{BOT_SESSION_TOKEN}_{user_id}_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
    if len(files) > 10:
        total_pages = math.ceil(len(files) / 10)
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"bms_sel_{BOT_SESSION_TOKEN}_{session_id}_{movie_idx}_{page - 1}_{user_id}"))
        nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(files) > (page + 1) * 10: nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"bms_sel_{BOT_SESSION_TOKEN}_{session_id}_{movie_idx}_{page + 1}_{user_id}"))
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("⬅ Back to Movie List", callback_data=f"bms_back_{BOT_SESSION_TOKEN}_{user_id}_{session_id}")])
    
    caption = (
        f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
        f"⭐️ **Rating:** `{metadata['rating']}`\n"
        f"🗣 **Language:** `{metadata['language']}`\n"
        f"🎭 **Type:** `{metadata['genre']}`\n\n"
        f"📝 **Synopsis:**\n_{metadata['plot']}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 **Found:** `{len(files)}` matching files."
    )
    
    try:
        await callback.message.edit_media(InputMediaPhoto(media=metadata["poster"], caption=caption))
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e: 
        logger.error(f"Failed to edit bulk media: {e}")
        try: await callback.message.edit_text(caption, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception: pass

@Client.on_callback_query(filters.regex(r"^bms_back_(.+)_(.+)_(.+)"))
async def handle_bulk_movie_back(client: Client, callback: CallbackQuery):
    token = callback.matches[0].group(1)
    searcher_id = int(callback.matches[0].group(2))
    session_id = callback.matches[0].group(3)
    
    if token != BOT_SESSION_TOKEN:
        return await callback.answer("⚠️ Session expired due to bot update/restart. Please search again!", show_alert=True)
    if callback.from_user.id != searcher_id:
        return await callback.answer("⚠️ This multi-search wasn't requested by you. Please search your own!", show_alert=True)
        
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
@Client.on_callback_query(filters.regex(r"^(next|prev)_(.+)_(.+)_(.+)_(.+)$"))
async def handle_pagination(client: Client, callback: CallbackQuery):
    action = callback.matches[0].group(1)
    token = callback.matches[0].group(2)
    searcher_id = int(callback.matches[0].group(3))
    page = int(callback.matches[0].group(4))
    base_query = callback.matches[0].group(5)
    
    if token != BOT_SESSION_TOKEN:
        return await callback.answer("⚠️ Session expired due to bot update/restart. Please search again!", show_alert=True)
    if callback.from_user.id != searcher_id:
        return await callback.answer("⚠️ This search wasn't requested by you. Please search your own movie!", show_alert=True)
    
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
    
    from plugins.vip_system import DEFAULT_PLANS, FREE_USER_LIMITS
    active_plan = await db.get_active_vip_plan(user_id)
    user_limits = DEFAULT_PLANS.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan else FREE_USER_LIMITS
    
    has_bypass = user_limits.get("shortlink_bypass", False)
    if not has_bypass: has_bypass = await db.has_active_verification_pass(user_id)
    shortener_on = settings.get("shortener_enabled", False) and not has_bypass

    if settings.get("bulk_enabled", True):
        bulk_limit = user_limits.get("bulk_select_limit", 10)
        web_app_results = filtered_results[:10000]
        short_id = hashlib.md5(f"{user_id}_{base_query}_{time.time()}".encode()).hexdigest()[:8]
        webapp_data = [f"{f.get('title', 'Unknown')}|{format_size(f.get('size', 0))}" for f in web_app_results]
        
        data_url = await upload_json_payload(webapp_data)
        if data_url:
            is_vip = True if active_plan else False
            web_app_url = build_safe_webapp_url(client.me.username, short_id, data_url, bulk_limit, is_vip)
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
        else: buttons.append([InlineKeyboardButton(text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{BOT_SESSION_TOKEN}_{user_id}_{db_id}")])
    
    buttons.append([InlineKeyboardButton(text="🤝 Help Us!", callback_data="help_us_menu")])
    
    total_pages = math.ceil(len(filtered_results) / 10)
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"prev_{BOT_SESSION_TOKEN}_{user_id}_{page - 1}_{base_query}"))
    nav_buttons.append(InlineKeyboardButton(text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
    if len(filtered_results) > (page + 1) * 10: nav_buttons.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"next_{BOT_SESSION_TOKEN}_{user_id}_{page + 1}_{base_query}"))
    buttons.append(nav_buttons)
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    await callback.answer()

@Client.on_inline_query()
async def inline_search(client: Client, query: InlineQuery):
    search_query = query.query.strip()
    user_id = query.from_user.id
    
    if len(search_query) < 3: 
        return await query.answer([])

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            try:
                chat = await client.get_chat(channel)
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
            except Exception: 
                invite_link = "https://t.me/telegram"
            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
        
        buttons.append([InlineKeyboardButton(text="🔄 Try Again", switch_inline_query_current_chat=search_query)])
        
        join_article = InlineQueryResultArticle(
            id="fsub_warning",
            title="🛑 Join Required to Search!",
            description="Click here to join our channels and unlock searches.",
            input_message_content=InputTextMessageContent("🛑 **Access Denied:**\nYou must join our official distribution channels to use the inline search."),
            reply_markup=InlineKeyboardMarkup(buttons),
            thumb_url="https://images.unsplash.com/photo-1560529870-1efc3a4080fd?q=80&w=150" 
        )
        return await query.answer([join_article], cache_time=0, is_personal=True)

    results = await db.search_files(search_query, skip=0, limit=Config.MAX_RESULTS, exact=False)
    articles = []
    raw_caption = await db.get_custom_caption(None)
    
    for idx, file in enumerate(results):
        file_id = file.get("file_id")
        if not file_id: continue
            
        f_name = file.get("title", "Unknown File")
        f_size = format_size(file.get('size', 0))
        mention = f"<a href='tg://user?id={user_id}'>{query.from_user.first_name}</a>"
        final_caption = raw_caption.replace("{file_name}", f_name).replace("{size}", f_size).replace("{mention}", mention)
            
        articles.append(
            InlineQueryResultCachedDocument(
                id=str(idx),
                title=f_name,
                document_file_id=file_id,
                description=f"Size: {f_size}",
                caption=final_caption
            )
        )
        
    await query.answer(articles, cache_time=300, is_personal=True)
