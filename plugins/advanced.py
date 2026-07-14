import asyncio
import logging
import aiohttp
import time
import random
import urllib.parse
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database.multi_db import db  # 🚀 Added database import for Permanent History!

logger = logging.getLogger(__name__)

ACTIVE_GHOST_TASKS = {}
PLOT_STATE = {}

@Client.on_callback_query(filters.regex("^pages_info$"))
async def ignore_page_button(client: Client, callback: CallbackQuery):
    await callback.answer("📖 You are currently viewing this page.", show_alert=False)

# ==========================================
# 🎬 CORE TMDB PLOT FETCHER ENGINE
# ==========================================
async def process_plot_query(client: Client, message: Message, query: str, prompt_msg_id: int = None):
    """Handles the TMDB fetching and history logging, then edits the UI."""
    user_id = message.from_user.id
    
    # 🚀 FIX: Save History PERMANENTLY to MongoDB (Keep last 10 only)
    await db.users.update_one(
        {"user_id": user_id},
        {"$push": {
            "search_history": {
                "$each": [{"type": "plot", "query": query}],
                "$slice": -10
            }
        }},
        upsert=True
    )

    status_text = f"🔍 **Searching TMDB database for `{query}`...**"
    
    if prompt_msg_id:
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, status_text)
        except Exception: pass
    else:
        status_msg = await message.reply_text(status_text)
        prompt_msg_id = status_msg.id

    # Ensure API keys are loaded
    if not hasattr(Config, "TMDB_API_KEYS") or not Config.TMDB_API_KEYS:
        err_msg = "❌ **Error:** TMDB API keys are missing in the configuration."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, err_msg)
        except Exception: await message.reply_text(err_msg)
        return

    # Randomly select a key to prevent rate limiting
    api_key = random.choice(Config.TMDB_API_KEYS)
    safe_query = urllib.parse.quote_plus(query)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={safe_query}") as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results")
                    if results:
                        movie = results[0]
                        overview = movie.get("overview") or "No plot overview available on TMDB."
                        release_date = movie.get("release_date", "Unknown")
                        year = release_date[:4] if release_date else "Unknown"
                        rating = round(movie.get("vote_average", 0), 1)
                        
                        summary_text = (
                            f"🎬 **Movie Details: {movie.get('title', query)}**\n"
                            f"🗓️ **Release Year:** `{year}`  ⭐️ **Rating:** `{rating}/10`\n\n"
                            f"📝 **Plot Overview:**\n{overview}"
                        )
                        try: await client.edit_message_text(message.chat.id, prompt_msg_id, summary_text)
                        except Exception: await message.reply_text(summary_text)
                        return
    except Exception as e:
        logger.error(f"TMDB Plot fetch error: {e}")

    # Fallback if TMDB fails or no results found
    fallback_summary = f"❌ **No results found on TMDB for:** `{query}`"
    try: await client.edit_message_text(message.chat.id, prompt_msg_id, fallback_summary)
    except Exception: await message.reply_text(fallback_summary)


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command("plot"))
async def plot_command(client: Client, message: Message):
    # 1. Fast Route (If they provide the movie name in the command)
    if len(message.command) >= 2:
        query = " ".join(message.command[1:])
        await process_plot_query(client, message, query)
        raise StopPropagation

    # 2. Clean Interactive Route
    prompt = await message.reply_text(
        "🍿 **Movie Plot Fetcher**\n\n"
        "What movie or series would you like to know about?\n"
        "*(Please reply with the title, or click Cancel)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_plot_flow")]])
    )
    
    PLOT_STATE[message.from_user.id] = {
        "message_id": prompt.id,
        "timestamp": time.time()
    }
    raise StopPropagation


# ==========================================
# 🧠 THE CLEAN UI LISTENER
# ==========================================
@Client.on_message(filters.text & filters.private, group=-7)
async def interactive_plot_listener(client: Client, message: Message):
    user_id = message.from_user.id
    
    if user_id not in PLOT_STATE:
        raise ContinuePropagation

    if message.text.startswith("/"):
        del PLOT_STATE[user_id]
        raise ContinuePropagation

    state = PLOT_STATE[user_id]
    prompt_msg_id = state["message_id"]
    timestamp = state["timestamp"]

    # 🛑 48-Hour Security Check
    if time.time() - timestamp > 172800:
        del PLOT_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please run `/plot` again."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation 

    # ✅ Capture Data & Clean the Chat
    query = message.text.strip()
    del PLOT_STATE[user_id]
    
    try: await message.delete() 
    except Exception: pass

    await process_plot_query(client, message, query, prompt_msg_id)
    
    raise StopPropagation


@Client.on_callback_query(filters.regex("^cancel_plot_flow$"))
async def cancel_plot_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in PLOT_STATE:
        del PLOT_STATE[user_id]
    await callback.message.edit_text("❌ **Operation Cancelled.**\n\nYou can use `/plot` whenever you're ready.")
    await callback.answer("Cancelled", show_alert=False)


# ==========================================
# ⚙️ HISTORY & GHOST MODE UTILITIES
# ==========================================
@Client.on_message(filters.command("history"))
async def view_search_history(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 🚀 Fetch History PERMANENTLY from MongoDB
    user_data = await db.users.find_one({"user_id": user_id})
    history = user_data.get("search_history", []) if user_data else []

    if not history:
        await message.reply_text("✨ Your query history is presently clean!")
        raise StopPropagation

    history_lines = []
    for idx, entry in enumerate(history, start=1):
        h_type = entry.get("type", "search").upper()
        h_query = entry.get("query", "")
        history_lines.append(f"{idx}. `[{h_type}]` {h_query}")

    history_text = (
        f"📑 **Your Recent Search & Plot History (Top 10):**\n\n"
        f"{chr(10).join(history_lines)}\n\n"
        f"💡 Use `/clear_history` to wipe storage logs."
    )
    await message.reply_text(history_text)
    raise StopPropagation

@Client.on_message(filters.command("clear_history"))
async def clear_history(client: Client, message: Message):
    user_id = message.from_user.id
    # 🚀 Erase History PERMANENTLY from MongoDB
    await db.users.update_one({"user_id": user_id}, {"$set": {"search_history": []}})
    await message.reply_text("🧹 **Your search history has been wiped clean successfully.**")
    raise StopPropagation

async def ghost_mode_delete_routine(client: Client, chat_id: int, message_id: int, expiry: int):
    await asyncio.sleep(expiry)
    try:
        await client.delete_messages(chat_id, message_id)
        logger.info(f"[GHOST MODE] Successfully purged message {message_id} in {chat_id} after {expiry} seconds.")
    except Exception as e:
        logger.error(f"[GHOST MODE] Failed to remove message {message_id} in {chat_id}: {e}")
    finally:
        task_key = f"{chat_id}_{message_id}"
        if task_key in ACTIVE_GHOST_TASKS:
            del ACTIVE_GHOST_TASKS[task_key]

def trigger_ghost_self_destruct(client: Client, chat_id: int, message_id: int, duration_seconds: int):
    loop = asyncio.get_event_loop()
    task = loop.create_task(ghost_mode_delete_routine(client, chat_id, message_id, duration_seconds))
    ACTIVE_GHOST_TASKS[f"{chat_id}_{message_id}"] = task
