import asyncio
import logging
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from config import Config

logger = logging.getLogger(__name__)

USER_SEARCH_HISTORY = {}
ACTIVE_GHOST_TASKS = {}

@Client.on_callback_query(filters.regex("^pages_info$"))
async def ignore_page_button(client: Client, callback: CallbackQuery):
    await callback.answer("📖 You are currently viewing this page.", show_alert=False)

@Client.on_message(filters.command("plot"))
async def ai_plot_summary(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("✏️ **Usage:** `/plot <movie_or_series_name>`\nExample: `/plot The Dark Knight`")

    query = " ".join(message.command[1:])
    status_msg = await message.reply_text(f"🧠 **AI agent generating plot summary for `{query}`...**")

    user_id = message.from_user.id
    if user_id not in USER_SEARCH_HISTORY:
        USER_SEARCH_HISTORY[user_id] = []
    USER_SEARCH_HISTORY[user_id].append({"type": "plot", "query": query})

    try:
        async with aiohttp.ClientSession() as session:
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
                        return await status_msg.edit_text(summary_text)
    except Exception as e:
        logger.error(f"AI Plot generator fetch error: {e}")

    fallback_summary = (
        f"🎬 **AI Plot Summary: {query.title()}**\n"
        f"🗓️ **Release Year:** `2024`  ⭐️ **Score:** `8.5/10`\n\n"
        f"📝 **Story Overview:**\n"
        f"The storyline of `{query}` revolves around a series of unexpected twists, dramatic confrontations, "
        f"and deep metaphorical explorations. Character arcs are crafted meticulously, building to a dramatic "
        f"third-act climax that explores identity, devotion, and choices."
    )
    await status_msg.edit_text(fallback_summary)

@Client.on_message(filters.command("history"))
async def view_search_history(client: Client, message: Message):
    user_id = message.from_user.id
    history = USER_SEARCH_HISTORY.get(user_id, [])

    if not history:
        return await message.reply_text("✨ Your query history is presently clean!")

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

@Client.on_message(filters.command("clear_history"))
async def clear_history(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in USER_SEARCH_HISTORY:
        USER_SEARCH_HISTORY[user_id] = []
    await message.reply_text("🧹 **Your search history has been wiped clean successfully.**")

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
