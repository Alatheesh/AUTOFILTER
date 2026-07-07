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
# 1. HIGH SPEED LOCAL BACKUP PROTOCOL (RAPIDFUZZ)
# ==========================================
async def get_mongodb_fallback(query: str, limit=3, threshold=65):
    """
    BACKUP PROTOCOL: Safely pulls files from your MultiDB and applies 
    RapidFuzz (percentage math) to find the closest match.
    """
    try:
        # 1. Safely pull a pool of potential matches using your DB's native search
        first_word = query.split()[0] if query else query
        pool_query = first_word[:4] if len(first_word) >= 4 else first_word
        
        # 🚀 CRITICAL FIX: Use your native db.search_files instead of db.files!
        raw_files = await db.search_files(pool_query, skip=0, limit=300, exact=False)
        
        # Extract clean, unique titles
        clean_titles = []
        for item in raw_files:
            title = item.get("title")
            if title and title not in clean_titles:
                clean_titles.append(str(title).strip())
                
        if not clean_titles:
            return []

        # 2. 🚀 THE PERCENTAGE MATH (RapidFuzz WRatio)
        results = process.extract(
            query.lower(), 
            [t.lower() for t in clean_titles], 
            scorer=fuzz.WRatio, 
            limit=limit
        )
        
        suggestions = []
        for match_lower, score, index in results:
            if score >= threshold: # Only accept if the percentage match is >= 65%
                suggestions.append(clean_titles[index])
                
        return suggestions
    except Exception as e:
        logger.error(f"MongoDB Backup Protocol Error: {e}")
        return []

# ==========================================
# 2. TMDB / IMDB EXTERNAL FETCHERS
# ==========================================
async def fetch_smart_spellcheck(query: str, limit=3):
    """Rotates TMDB keys. Falls back to local database if keys fail or are empty."""
    tmdb_keys = Config.TMDB_API_KEYS
    
    if not tmdb_keys:
        return await get_mongodb_fallback(query, limit)

    suggestions = []
    async with aiohttp.ClientSession() as session:
        for key in tmdb_keys:
            try:
                url = f"https://api.themoviedb.org/3/search/movie?api_key={key}&query={urllib.parse.quote(query)}&page=1"
                async with session.get(url, timeout=3) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("results", []):
                            title = item.get("title")
                            if title and title not in suggestions:
                                suggestions.append(title)
                                if len(suggestions) >= limit: break
                        
                        # 🚀 BUG FIX: If TMDB responds but finds 0 results for the typo,
                        # do NOT give up. Break the loop and let MongoDB try to fix it!
                        if suggestions:
                            return suggestions
            except Exception:
                continue # Key failed or timed out, move to the next key
                
    # If all TMDB keys fail OR TMDB returns 0 matches for the typo, use Backup Protocol
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
    # 1. Extract the movie name
    if callback.data.startswith("fuzzy_"):
        correct_name = callback.data.split("fuzzy_", 1)[1]
    else:
        correct_name = callback.data.split("fuz_", 1)[1]
        
    # 2. 🚀 CRITICAL FIX: DO NOT DELETE THE MESSAGE! 
    # Just remove the buttons so auto_filter has a message to reply to.
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"🔍 Fetching: {correct_name}...", show_alert=False)
    
    # 3. Clean the query
    import re
    clean_query = re.sub(r"[_+\[\]\(\)\{\}\-.:']", " ", correct_name)
    clean_query = " ".join(clean_query.split())
    
    # 4. Trick the bot into executing a normal search instantly!
    message = callback.message
    message.text = clean_query
    message.from_user = callback.from_user 
    
    from plugins.search import auto_filter
    await auto_filter(client, message)
