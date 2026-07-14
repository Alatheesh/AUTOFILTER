import asyncio
import logging
import aiohttp
import time
import random
import urllib.parse
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ButtonStyle
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database.multi_db import db  

logger = logging.getLogger(__name__)

ACTIVE_GHOST_TASKS = {}
PLOT_STATE = {}

@Client.on_callback_query(filters.regex("^pages_info$"))
async def ignore_page_button(client: Client, callback: CallbackQuery):
    await callback.answer("📖 𝖸𝗈𝗎 𝖺𝗋𝖾 𝖼𝗎𝗋𝗋𝖾𝗇𝗍𝗅𝗒 𝗏𝗂𝖾𝗐𝗂𝗇𝗀 𝗍𝗁𝗂𝗌 𝗉𝖺𝗀𝖾.", show_alert=False)

# ==========================================
# 🎬 CORE TMDB PLOT FETCHER ENGINE
# ==========================================
async def process_plot_query(client: Client, message: Message, query: str, prompt_msg_id: int = None):
    user_id = message.from_user.id
    
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

    status_text = f"🔍 **𝖲𝖾𝖺𝗋𝖼𝗁𝗂𝗇𝗀 𝖳𝖬𝖣𝖡 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾 𝖿𝗈𝗋 `{query}`...**"
    
    if prompt_msg_id:
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, status_text)
        except Exception: pass
    else:
        status_msg = await message.reply_text(status_text)
        prompt_msg_id = status_msg.id

    if not hasattr(Config, "TMDB_API_KEYS") or not Config.TMDB_API_KEYS:
        err_msg = "❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐓𝐌𝐃𝐁 𝐀𝐏𝐈 𝐤𝐞𝐲𝐬 𝐚𝐫𝐞 𝐦𝐢𝐬𝐬𝐢𝐧𝐠 𝐢𝐧 𝐭𝐡𝐞 𝐜𝐨𝐧𝐟𝐢𝐠𝐮𝐫𝐚𝐭𝐢𝐨𝐧."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, err_msg)
        except Exception: await message.reply_text(err_msg)
        return

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
                        overview = movie.get("overview") or "𝖭𝗈 𝗉𝗅𝗈𝗍 𝗈𝗏𝖾𝗋𝗏𝗂𝖾𝗐 𝖺𝗏𝖺𝗂𝗅𝖺𝖻𝗅𝖾 𝗈𝗇 𝖳𝖬𝖣𝖡."
                        release_date = movie.get("release_date", "𝖴𝗇𝗄𝗇𝗈𝗐𝗇")
                        year = release_date[:4] if release_date else "𝖴𝗇𝗄𝗇𝗈𝗐𝗇"
                        rating = round(movie.get("vote_average", 0), 1)
                        
                        summary_text = (
                            f"🎬 **𝗠𝗼𝘃𝗶𝗲 𝗗𝗲𝘁𝗮𝗶𝗹𝘀: {movie.get('title', query)}**\n"
                            f"🗓️ **𝗥𝗲𝗹𝗲𝗮𝘀𝗲 𝗬𝗲𝗮𝗿:** `{year}`  ⭐️ **𝗥𝗮𝘁𝗶𝗻𝗴:** `{rating}/𝟭𝟬`\n\n"
                            f"📝 **𝗣𝗹𝗼𝘁 𝗢𝘃𝗲𝗿𝘃𝗶𝗲𝘄:**\n{overview}"
                        )
                        try: await client.edit_message_text(message.chat.id, prompt_msg_id, summary_text)
                        except Exception: await message.reply_text(summary_text)
                        return
    except Exception as e:
        logger.error(f"TMDB Plot fetch error: {e}")

    fallback_summary = f"❌ **𝐍𝐨 𝐫𝐞𝐬𝐮𝐥𝐭𝐬 𝐟𝐨𝐮𝐧𝐝 𝐨𝐧 𝐓𝐌𝐃𝐁 𝐟𝐨𝐫:** `{query}`"
    try: await client.edit_message_text(message.chat.id, prompt_msg_id, fallback_summary)
    except Exception: await message.reply_text(fallback_summary)


# ==========================================
# 📢 DIRECT COMMAND & WIZARD LAUNCHER
# ==========================================
@Client.on_message(filters.command("plot"))
async def plot_command(client: Client, message: Message):
    if len(message.command) >= 2:
        query = " ".join(message.command[1:])
        await process_plot_query(client, message, query)
        raise StopPropagation

    prompt = await message.reply_text(
        "🍿 **𝗠𝗼𝘃𝗶𝗲 𝗣𝗹𝗼𝘁 𝗙𝗲𝘁𝗰𝗵𝗲𝗿**\n\n"
        "𝖶𝗁𝖺𝗍 𝗆𝗈𝗏𝗂𝖾 𝗈𝗋 𝗌𝖾𝗋𝗂𝖾𝗌 𝗐𝗈𝗎𝗅𝖽 𝗒𝗈𝗎 𝗅𝗂𝗄𝖾 𝗍𝗈 𝗄𝗇𝗈𝗐 𝖺𝖻𝗈𝗎𝗍?\n"
        "*(𝖯𝗅𝖾𝖺𝗌𝖾 𝗋𝖾𝗉𝗅𝗒 𝗐𝗂𝗍𝗁 𝗍𝗁𝖾 𝗍𝗂𝗍𝗅𝖾, 𝗈𝗋 𝖼𝗅𝗂𝖼𝗄 𝖢𝖺𝗇𝖼𝖾𝗅)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="cancel_plot_flow", style=ButtonStyle.DANGER)]])
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

    if time.time() - timestamp > 172800:
        del PLOT_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐄𝐱𝐩𝐢𝐫𝐞𝐝.**\n\n𝐓𝐡𝐢𝐬 𝐩𝐫𝐨𝐦𝐩𝐭 𝐢𝐬 𝐨𝐥𝐝𝐞𝐫 𝐭𝐡𝐚𝐧 𝟒𝟖 𝐡𝐨𝐮𝐫𝐬. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐮𝐧 `/plot` 𝐚𝐠𝐚𝐢𝐧."
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation 

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
    await callback.message.edit_text("❌ **𝐎𝐩𝐞𝐫𝐚𝐭𝐢𝐨𝐧 𝐂𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝.**\n\n𝐘𝐨𝐮 𝐜𝐚𝐧 𝐮𝐬𝐞 `/plot` 𝐰𝐡𝐞𝐧𝐞𝐯𝐞𝐫 𝐲𝐨𝐮'𝐫𝐞 𝐫𝐞𝐚𝐝𝐲.")
    await callback.answer("𝖢𝖺𝗇𝖼𝖾𝗅𝗅𝖾𝖽", show_alert=False)


# ==========================================
# ⚙️ HISTORY & GHOST MODE UTILITIES
# ==========================================
@Client.on_message(filters.command("history"))
async def view_search_history(client: Client, message: Message):
    user_id = message.from_user.id
    user_data = await db.users.find_one({"user_id": user_id})
    history = user_data.get("search_history", []) if user_data else []

    if not history:
        await message.reply_text("✨ 𝖸𝗈𝗎𝗋 𝗊𝗎𝖾𝗋𝗒 𝗁𝗂𝗌𝗍𝗈𝗋𝗒 𝗂𝗌 𝗉𝗋𝖾𝗌𝖾𝗇𝗍𝗅𝗒 𝖼𝗅𝖾𝖺𝗇!")
        raise StopPropagation

    history_lines = []
    for idx, entry in enumerate(history, start=1):
        h_type = entry.get("type", "search").upper()
        h_query = entry.get("query", "")
        history_lines.append(f"{idx}. `[{h_type}]` {h_query}")

    history_text = (
        f"📑 **𝗬𝗼𝘂𝗿 𝗥𝗲𝗰𝗲𝗻𝘁 𝗦𝗲𝗮𝗿𝗰𝗵 & 𝗣𝗹𝗼𝘁 𝗛𝗶𝘀𝘁𝗼𝗿𝘆 (𝗧𝗼𝗽 𝟭𝟬):**\n\n"
        f"{chr(10).join(history_lines)}\n\n"
        f"💡 𝖴𝗌𝖾 `/clear_history` 𝗍𝗈 𝗐𝗂𝗉𝖾 𝗌𝗍𝗈𝗋𝖺𝗀𝖾 𝗅𝗈𝗀𝗌."
    )
    await message.reply_text(history_text)
    raise StopPropagation

@Client.on_message(filters.command("clear_history"))
async def clear_history(client: Client, message: Message):
    user_id = message.from_user.id
    await db.users.update_one({"user_id": user_id}, {"$set": {"search_history": []}})
    await message.reply_text("🧹 **𝗬𝗼𝘂𝗿 𝘀𝗲𝗮𝗿𝗰𝗵 𝗵𝗶𝘀𝘁𝗼𝗿𝘆 𝗵𝗮𝘀 𝗯𝗲𝗲𝗻 𝘄𝗶𝗽𝗲𝗱 𝗰𝗹𝗲𝗮𝗻 𝘀𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆.**")
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
