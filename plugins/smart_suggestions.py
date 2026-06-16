import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

logger = logging.getLogger(__name__)

@Client.on_callback_query(filters.regex(r"^fuz_(.+)$"))
async def handle_fuzzy_click(client: Client, callback: CallbackQuery):
    # 1. Extract the corrected movie name from the button they clicked
    suggested_query = callback.data.split("fuz_", 1)[1]
    
    # 2. Show a loading spinner at the top of their screen
    await callback.answer(f"🔍 Searching database for: {suggested_query}...")
    
    # 3. Delete the old "Did you mean?" error message to keep the chat clean
    await callback.message.delete()
    
    # 4. "Trick" the bot into thinking the user manually typed the correct spelling
    message = callback.message
    message.text = suggested_query
    message.from_user = callback.from_user 
    
    # 5. Route the perfectly spelled text directly back into your search engine!
    from plugins.search import auto_filter
    await auto_filter(client, message)
