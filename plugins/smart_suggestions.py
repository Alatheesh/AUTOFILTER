import aiohttp
import urllib.parse
import logging
import re
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# 1. HIGH SPEED LOCAL BACKUP PROTOCOL
# ==========================================
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

async def get_mongodb_fallback(query: str, limit=3):
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
            
    return list(dict.fromkeys(suggestions))[:limit]

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
                        return suggestions
            except Exception:
                continue # Key failed or timed out, move to the next key
                
    # If all TMDB keys fail, use Backup Protocol
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
# 3. BUTTON ROUTING (BROADCASTS VS TYPOS)
# ==========================================

# ▶️ ROUTE A: The Broadcasting Trigger (Uses "fuz_")
# When you send a broadcast with a movie button, this forces the bot to search it.
@Client.on_callback_query(filters.regex(r"^fuz_(.+)$"))
async def handle_fuz_broadcast_click(client: Client, callback: CallbackQuery):
    suggested_query = callback.data.split("fuz_", 1)[1]
    
    # 1. Remove the buttons so the user knows it registered, preventing the "Deleted Message" crash!
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"🔍 Searching for: {suggested_query}...", show_alert=False)
    
    # 2. Clean the query
    clean_query = re.sub(r"[_+\[\]\(\)\{\}\-.:']", " ", suggested_query)
    clean_query = " ".join(clean_query.split())
    
    # 3. Trick the bot into executing a normal search
    message = callback.message
    message.text = clean_query
    message.from_user = callback.from_user 
    
    from plugins.search import auto_filter
    await auto_filter(client, message)


# ▶️ ROUTE B: The Typo Corrector (Uses "fuzzy_")
# When a user makes a typo, this button fixes their spelling via inline query.
@Client.on_callback_query(filters.regex(r"^fuzzy_"))
async def handle_fuzzy_typo_click(client: Client, callback: CallbackQuery):
    correct_name = callback.data.replace("fuzzy_", "")
    await callback.message.delete()
    
    await client.send_message(
        callback.message.chat.id, 
        f"✨ **Did you mean:** `{correct_name}`\n\nClick below to search again!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔍 Fetch Files", switch_inline_query_current_chat=correct_name)
        ]])
    )
