import re
import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

logger = logging.getLogger(__name__)

@Client.on_callback_query(filters.regex(r"^fuz_(.+)$"))
async def handle_fuzzy_click(client: Client, callback: CallbackQuery):
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
