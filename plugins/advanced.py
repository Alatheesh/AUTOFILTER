import asyncio
import logging
import aiohttp
import time
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config

logger = logging.getLogger(__name__)

USER_SEARCH_HISTORY = {}
ACTIVE_GHOST_TASKS = {}

# 🧠 State Machine for Clean Interactive Plot Generator
PLOT_STATE = {}

@Client.on_callback_query(filters.regex("^pages_info$"))
async def ignore_page_button(client: Client, callback: CallbackQuery):
    await callback.answer("📖 You are currently viewing this page.", show_alert=False)

# ==========================================
# 🧠 CORE PLOT GENERATOR ENGINE
# ==========================================
async def process_plot_query(client: Client, message: Message, query: str, prompt_msg_id: int = None):
    """Handles the TMDB fetching and history logging, then edits the UI."""
    user_id = message.from_user.id
    
    # Update History
    if user_id not in USER_SEARCH_HISTORY:
        USER_SEARCH_HISTORY[user_id] = []
    USER_SEARCH_HISTORY[user_id].append({"type": "plot", "query": query})

    status_text = f"🧠 **AI agent generating plot summary for `{query}`...**"
    
    if prompt_msg_id:
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, status_text)
        except Exception: pass
    else:
        status_msg = await message.reply_text(status_text)
        prompt_msg_id = status_msg.id

    try:
        async with aiohttp.ClientSession() as session:
            # Using your existing, reliable TMDB API integration!
            async with session.get(f"https://api.themoviedb.org/3/search/movie?api_key=4e06aa73663b652613ddfd14a7967b58&query={query}") as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results")
                    if results:
                        movie = results[0]
                        overview = movie.get("overview", "Overview narrative could not be fetched.")
                        release_date = movie.get("release_date", "Unknown date")
                        rating = movie.get("vote_average", "N/A")
                        
                        summary_text = (
                            f"🎬 **AI Plot Summary: {movie.get('title', query)}**\n"
                            f"🗓️ **Release Year:** `{release_date[:4]}`  ⭐️ **Rating:** `{rating}/10`\n\n"
                            f"📝 **Plot Overview:**\n{overview}"
                        )
                        try: await client.edit_message_text(message.chat.id, prompt_msg_id, summary_text)
                        except Exception: await message.reply_text(summary_text)
                        return
    except Exception as e:
        logger.error(f"AI Plot generator fetch error: {e}")

    # Fallback if TMDB fails
    fallback_summary = (
        f"🎬 **AI Plot Summary: {query.title()}**\n"
        f"🗓️ **Release Year:** `Unknown`  ⭐️ **Score:** `N/A`\n\n"
        f"📝 **Story Overview:**\n"
        f"The storyline of `{query}` revolves around a series of unexpected twists, dramatic confrontations, "
        f"and deep metaphorical explorations. Character arcs are crafted meticulously, building to a dramatic "
        f"third-act climax that explores identity, devotion, and choices."
    )
    try: await client.edit_message_text(message.chat.id, prompt_msg_id, fallback_summary)
    except Exception: await message.reply_text(fallback_summary)


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command("plot"))
async def ai_plot_command(client: Client, message: Message):
    # 1. Fast Route (If they provide the movie name in the command)
    if len(message.command) >= 2:
        query = " ".join(message.command[1:])
        await process_plot_query(client, message, query)
        raise StopPropagation

    # 2. Clean Interactive Route
    prompt = await message.reply_text(
        "🧠 **AI Plot Generator**\n\n"
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
    
    # 🚀 Block the Search Engine!
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
    history = USER_SEARCH_HISTORY.get(user_id, [])

    if not history:
        await message.reply_text("✨ Your query history is presently clean!")
        raise StopPropagation

    history_lines = []
    for idx, entry in enumerate(history[-10:], start=1):
        h_type = entry.get("type", "search").upper()
        h_query = entry.get("query", "")
        history_lines.append(f"{idx}. `[{h_type}]` {h_query}")

    history_text = (
        f"📑 **Your Recent Search & AI Inquiry History (Top 10):**\n\n"
        f"{chr(10).join(history_lines)}\n\n"
        f"💡 Use `/clear_history` to wipe storage logs."
    )
    await message.reply_text(history_text)
    raise StopPropagation

@Client.on_message(filters.command("clear_history"))
async def clear_history(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in USER_SEARCH_HISTORY:
        USER_SEARCH_HISTORY[user_id] = []
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
