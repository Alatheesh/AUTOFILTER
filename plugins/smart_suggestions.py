import aiohttp
import urllib.parse
import logging
import re
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from rapidfuzz import process, fuzz
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# 1. TIER 3: MONGODB RAPIDFUZZ (FINAL FALLBACK)
# ==========================================
async def get_mongodb_fallback(query: str, limit=10, threshold=65):
    """
    Scans local database and uses Percentage Match (RapidFuzz).
    """
    try:
        first_word = query.split()[0] if query else query
        pool_query = first_word[:4] if len(first_word) >= 4 else first_word
        
        raw_files = await db.search_files(pool_query, skip=0, limit=300, exact=False)
        
        clean_titles = []
        for item in raw_files:
            title = item.get("title")
            if title and title not in clean_titles:
                clean_titles.append(str(title).strip())
                
        if not clean_titles:
            return []

        results = process.extract(
            query.lower(), 
            [t.lower() for t in clean_titles], 
            scorer=fuzz.WRatio, 
            limit=limit
        )
        
        suggestions = []
        for match_lower, score, index in results:
            if score >= threshold:
                suggestions.append(clean_titles[index])
                
        return suggestions
    except Exception as e:
        logger.error(f"MongoDB Backup Protocol Error: {e}")
        return []

# ==========================================
# 2. TIER 1 & 2: TMDB & IMDB WATERFALL
# ==========================================
async def fetch_smart_spellcheck(query: str, limit=10):
    """
    THE 3-TIER WATERFALL:
    1. Tries TMDB.
    2. Tries IMDB (If TMDB fails or keys are missing).
    3. Tries Local MongoDB (If IMDB fails).
    """
    tmdb_keys = getattr(Config, "TMDB_API_KEYS", [])
    
    # --- TIER 1: TMDB ---
    if tmdb_keys:
        async with aiohttp.ClientSession() as session:
            for key in tmdb_keys:
                try:
                    url = f"https://api.themoviedb.org/3/search/movie?api_key={key}&query={urllib.parse.quote(query)}&page=1"
                    async with session.get(url, timeout=3) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            suggestions = []
                            for item in data.get("results", []):
                                title = item.get("title")
                                if title and title not in suggestions:
                                    suggestions.append(title)
                                    if len(suggestions) >= limit: break
                            if suggestions:
                                return suggestions # Success! Found in TMDB
                except Exception:
                    continue 

    # --- TIER 2: IMDB NO-KEY AUTOCOMPLETE ---
    try:
        clean_query = urllib.parse.quote(query.lower())
        first_letter = clean_query[0] if clean_query else 'a'
        url = f"https://v3.sg.media-imdb.com/suggestion/{first_letter}/{clean_query}.json"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=3) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    suggestions = []
                    for item in data.get("d", []):
                        if item.get("q") in ["feature", "TV series", "movie"]:
                            title = item.get("l")
                            if title and title not in suggestions:
                                suggestions.append(title)
                                if len(suggestions) >= limit: break
                    if suggestions:
                        return suggestions # Success! Found in IMDB
    except Exception as e:
        logger.error(f"IMDB Fallback Error: {e}")
        
    # --- TIER 3: MONGODB RAPIDFUZZ ---
    # If TMDB and IMDB both failed to find the typo, do the DB percentage match
    return await get_mongodb_fallback(query, limit)


async def get_imdb_poster_fallback(movie_name):
    """Secretly pulls a poster from IMDB if no TMDB keys are provided."""
    try:
        clean_query = urllib.parse.quote(movie_name.lower())
        first_letter = clean_query[0] if clean_query else 'a'
        url = f"https://v3.sg.media-imdb.com/suggestion/{first_letter}/{clean_query}.json"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=3) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("d", []):
                        if item.get("q") in ["feature", "TV series", "movie"] and "i" in item:
                            return item["i"].get("imageUrl")
    except Exception: pass
    return None

# ==========================================
# 3. BUTTON ROUTING (BROADCASTS & TYPOS)
# ==========================================
@Client.on_callback_query(filters.regex(r"^(fuz_|fuzzy_)"))
async def handle_all_fuzzy_clicks(client: Client, callback: CallbackQuery):
    if callback.data.startswith("fuzzy_"):
        correct_name = callback.data.split("fuzzy_", 1)[1]
    else:
        correct_name = callback.data.split("fuz_", 1)[1]
        
    # 1. Answer the callback to stop the loading circle (BUTTONS WILL NOT BE DELETED)
    await callback.answer(f"🔍 Fetching: {correct_name}...", show_alert=False)
    
    # 2. Clean the query
    clean_query = re.sub(r"[_+\[\]\(\)\{\}\-.:']", " ", correct_name)
    clean_query = " ".join(clean_query.split())
    
    # 3. Trick the bot into executing a normal search instantly!
    message = callback.message
    message.text = clean_query
    message.from_user = callback.from_user 
    
    from plugins.search import auto_filter
    await auto_filter(client, message)
