import re
import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

logger = logging.getLogger(__name__)

@Client.on_callback_query(filters.regex(r"^fuz_(.+)$"))
async def handle_fuzzy_click(client: Client, callback: CallbackQuery):
    suggested_query = callback.data.split("fuz_", 1)[1]
    
    # 1. Edit the message to a loading screen (Prevents the reply crash!)
    await callback.message.edit_text(f"⏳ **Loading database files for:** `{suggested_query}`...")
    
    # 2. Strip special TMDB characters (like hyphens and colons) so it matches your DB!
    clean_query = re.sub(r"[_+\[\]\(\)\{\}\-.:']", " ", suggested_query)
    clean_query = " ".join(clean_query.split())
    
    # 3. Route the cleaned text directly into your search engine
    message = callback.message
    message.text = clean_query
    message.from_user = callback.from_user 
    
    from plugins.search import auto_filter
    await auto_filter(client, message)
    
    # 4. Clean up the "Loading" message now that the movies have successfully sent!
    try:
        await callback.message.delete()
    except Exception:
        
        pass
