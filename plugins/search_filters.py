import math
import time
import random
import json
import urllib.parse
import hashlib
import aiohttp
import asyncio
from collections import defaultdict
from pyrogram import Client
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyParameters, WebAppInfo, CallbackQuery
)
from database.multi_db import db
from config import Config

MB = 1024 * 1024
GB = 1024 * MB

# 🌟 THE ADAPTIVE SPEED CONTROLLER
GROUP_LAST_SENT = defaultdict(float)
GROUP_THROTTLE_LOCKS = defaultdict(asyncio.Lock)

# ==========================================
# 📏 SIZE FILTER MAPPING
# ==========================================
SIZE_MAP = {
    "small": (0, 500 * MB),
    "medium": (500 * MB, 1 * GB),
    "large": (1 * GB, 2 * GB),
    "xlarge": (2 * GB, float('inf')),
    "all": (0, float('inf'))
}

# ==========================================
# 🛠️ HELPER UTILITIES
# ==========================================
def style_btn(color_mode: bool, style_enum, **kwargs):
    """Safely injects Telegram Premium colors into buttons ONLY if color_mode is True."""
    if color_mode and style_enum:
        kwargs["style"] = style_enum
    return InlineKeyboardButton(**kwargs)

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

async def upload_json_payload(data_list):
    json_string = json.dumps(data_list)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.npoint.io/", json=data_list, timeout=8) as resp:
                if resp.status == 200: return f"https://api.npoint.io/{(await resp.json())['id']}"
    except Exception: pass
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://dpaste.com/api/v2/", data={"content": json_string, "syntax": "json"}, timeout=8) as resp:
                if resp.status in [200, 201]:
                    url = (await resp.text()).strip()
                    if url.startswith("http"): return f"{url}.txt"
    except Exception: pass
    return None

def build_safe_webapp_url(client_username, short_id, data_url, user_limit, is_vip=False, plan_name="Free Tier", expiry_str="N/A"):
    base_link = getattr(Config, "BULK_LINK", "https://yourusername.github.io/autofilter-web/").strip()
    if not base_link.startswith("http"): base_link = f"https://{base_link}"
    safe_url = urllib.parse.quote(data_url)
    bot_username = client_username or "Bot"
    tier = "premium" if is_vip else "free"
    
    safe_plan = urllib.parse.quote(str(plan_name))
    safe_exp = urllib.parse.quote(str(expiry_str))
    
    return f"{base_link}?bot={bot_username}&id={short_id}&limit={user_limit}&tier={tier}&plan={safe_plan}&exp={safe_exp}&url={safe_url}"

# ==========================================
# ⚙️ MODE & FILTER CONFLICT RESOLUTION
# ==========================================
async def get_filter_settings(user_id: int, chat_id: int, chat_type):
    """
    Resolves conflicts between Group Admin forced settings and User personal settings.
    """
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(chat_id)
        g_mode = g_sett.get("search_mode", "let_members_choose")
        
        if g_mode == "force_default": 
            return "default", "all", "all"
        elif g_mode == "force_interactive": 
            return "interactive", g_sett.get("language_lock", "all"), g_sett.get("size_lock", "all")
        elif g_mode == "force_hypertext":
            return "hypertext", "all", "all"
        elif g_mode == "force_matrix":
            return "matrix", "all", "all"
            
    u_sett = await db.get_user_settings(user_id)
    return u_sett.get("search_mode", "default"), u_sett.get("language", "all"), u_sett.get("size", "all")

# ==========================================
# 🔍 MASTER FILTER ENGINE
# ==========================================
def apply_search_filters(raw_results: list, mode: str, language: str, size: str) -> list:
    """
    Filters file results according to mode criteria before rendering.
    """
    min_bytes, max_bytes = SIZE_MAP.get(size, (0, float('inf')))
    filtered_results = []
    
    for file in raw_results:
        if not (min_bytes <= file.get("size", 0) <= max_bytes): 
            continue
            
        if mode == "interactive":
            if language not in ["all", "none"]:
                lang_data = file.get("language", "unknown").lower()
                title_data = file.get("title", "").lower()
                if language.lower() not in lang_data and language.lower() not in title_data:
                    continue

        filtered_results.append(file)
        
    return filtered_results

# ==========================================
# 🎨 MODE DISPLAY & LAYOUT IMPLEMENTATIONS
# ==========================================

# --- 1. DEFAULT MODE LAYOUT ---
def render_default_mode(results, filtered_results, metadata, user_id, bot_username, session_token, query, page, total_pages, shortener_on, color_mode, bulk_btn, chat_type, settings):
    buttons = []
    if bulk_btn:
        buttons.insert(0, [bulk_btn])

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        rnd_color = random.choice([ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER])
        
        if shortener_on:
            buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{bot_username}?start=getfile_{db_id}")])
        else:
            buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{session_token}_{user_id}_{db_id}")])

    buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    if len(filtered_results) > 10:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="◀️ Prev", callback_data=f"prev_{session_token}_{user_id}_{page - 1}_{query}"))
        nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(filtered_results) > (page + 1) * 10:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="Next ▶️", callback_data=f"next_{session_token}_{user_id}_{page + 1}_{query}"))
        buttons.append(nav_buttons)

    del_notice = ""
    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        del_notice = f"\n\n⏳ *Note: This message auto-deletes in {m_time} minutes.*"

    pm_notice = ""
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        pm_notice = "\n\n*(Click a file to receive it securely in your Private Messages)*"

    caption = (
        f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
        f"⭐️ **Rating:** `{metadata['rating']}`\n"
        f"🗣 **Language:** `{metadata['language']}`\n"
        f"🎭 **Type:** `{metadata['genre']}`\n\n"
        f"📝 **Synopsis:**\n_{metadata['plot']}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 **Found:** `{len(filtered_results)}` matching files.{del_notice}{pm_notice}"
    )
    return caption, InlineKeyboardMarkup(buttons), False


# --- 2. INTERACTIVE MODE LAYOUT ---
def render_interactive_mode(results, filtered_results, metadata, user_id, bot_username, session_token, query, page, total_pages, shortener_on, color_mode, bulk_btn, chat_type, resolved_lang, resolved_size, settings):
    buttons = []
    if bulk_btn:
        buttons.insert(0, [bulk_btn])

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        rnd_color = random.choice([ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER])
        
        if shortener_on:
            buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{bot_username}?start=getfile_{db_id}")])
        else:
            buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{session_token}_{user_id}_{db_id}")])

    buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    if len(filtered_results) > 10:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="◀️ Prev", callback_data=f"prev_{session_token}_{user_id}_{page - 1}_{query}"))
        nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(filtered_results) > (page + 1) * 10:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="Next ▶️", callback_data=f"next_{session_token}_{user_id}_{page + 1}_{query}"))
        buttons.append(nav_buttons)

    filter_notice = ""
    if resolved_lang != "all" or resolved_size != "all":
        filter_notice = f"\n✨ **Filters Applied:** Size: `{resolved_size.upper()}` | Audio: `{resolved_lang.upper()}`"

    del_notice = ""
    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        del_notice = f"\n\n⏳ *Note: This message auto-deletes in {m_time} minutes.*"

    pm_notice = ""
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        pm_notice = "\n\n*(Click a file to receive it securely in your Private Messages)*"

    caption = (
        f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
        f"⭐️ **Rating:** `{metadata['rating']}`\n"
        f"🗣 **Language:** `{metadata['language']}`\n"
        f"🎭 **Type:** `{metadata['genre']}`\n\n"
        f"📝 **Synopsis:**\n_{metadata['plot']}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 **Found:** `{len(filtered_results)}` matching files.{filter_notice}{del_notice}{pm_notice}"
    )
    return caption, InlineKeyboardMarkup(buttons), False


# --- 3. HYPERTEXT (TEXT-LINK) MODE LAYOUT ---
def render_hypertext_mode(results, filtered_results, metadata, user_id, bot_username, session_token, query, page, total_pages, shortener_on, color_mode, bulk_btn, chat_type, settings):
    text = f"🍿 <u>**{metadata['title']} ({metadata['release_date'][:4]})**</u>\n"
    text += f"⭐️ **Rating:** `{metadata['rating']}` | 🗣 `{metadata['language']}`\n\n"
    text += "👇 **Click a link to receive your file:**\n\n"

    for file in results:
        db_id = str(file.get("_id", ""))
        f_size = format_size(file.get('size', 0))
        f_title = str(file.get('title', 'Unknown File')).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        link = f"https://t.me/{bot_username}?start=getfile_{db_id}"
        text += f"📁 <a href='{link}'>[{f_size}] {f_title}</a>\n\n"

    buttons = []
    
    if bulk_btn:
        buttons.append([bulk_btn])

    buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    if len(filtered_results) > 10:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="◀️ Prev", callback_data=f"prev_{session_token}_{user_id}_{page - 1}_{query}"))
        nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(filtered_results) > (page + 1) * 10:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="Next ▶️", callback_data=f"next_{session_token}_{user_id}_{page + 1}_{query}"))
        buttons.append(nav_buttons)

    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        text += f"⏳ *Note: This message auto-deletes in {m_time} minutes.*"

    return text, InlineKeyboardMarkup(buttons) if buttons else None, True


# --- 4. COMPACT KEYPAD (MATRIX) MODE LAYOUT ---
def render_matrix_mode(results, filtered_results, metadata, user_id, bot_username, session_token, query, page, total_pages, shortener_on, color_mode, bulk_btn, chat_type, settings):
    text = (
        f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
        f"⭐️ **Rating:** `{metadata['rating']}` | 🎭 `{metadata['genre']}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for idx, file in enumerate(results):
        emoji = number_emojis[idx] if idx < 10 else str(idx + 1)
        f_size = format_size(file.get('size', 0))
        f_title = str(file.get('title', 'Unknown File')).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        audio = str(file.get("language", "unknown")).title()
        if audio == "Pending": audio = "Scanning..."
        
        subs = str(file.get("subtitle", "none")).title()
        if subs == "Pending": subs = "Scanning..."
        
        text += f"{emoji} <b>[{f_size}]</b> <code>{f_title}</code>\n"
        text += f"   ┗ 🔊 <b>{audio}</b> | 💬 <b>{subs}</b>\n\n"
        
    text += f"━━━━━━━━━━━━━━━━━━\n🔍 **Found:** `{len(filtered_results)}` matching files."

    buttons = []
    if bulk_btn:
        buttons.append([bulk_btn])
        
    buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    numeric_rows = []
    current_row = []
    for idx, file in enumerate(results):
        db_id = str(file.get("_id", ""))
        display_num = str(idx + 1)
        
        if shortener_on:
            btn = style_btn(color_mode, ButtonStyle.PRIMARY, text=display_num, url=f"https://t.me/{bot_username}?start=getfile_{db_id}")
        else:
            btn = style_btn(color_mode, ButtonStyle.PRIMARY, text=display_num, callback_data=f"sendfile_{session_token}_{user_id}_{db_id}")
            
        current_row.append(btn)
        if len(current_row) == 5:
            numeric_rows.append(current_row)
            current_row = []
            
    if current_row:
        numeric_rows.append(current_row)
        
    buttons.extend(numeric_rows)

    if len(filtered_results) > 10:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.DANGER, text="◀️ Prev", callback_data=f"prev_{session_token}_{user_id}_{page - 1}_{query}"))
            
        nav_buttons.append(style_btn(color_mode, ButtonStyle.SUCCESS, text=f"Page {page + 1}/{total_pages}", callback_data="pages_info"))
        
        if len(filtered_results) > (page + 1) * 10:
            nav_buttons.append(style_btn(color_mode, ButtonStyle.DANGER, text="Next ▶️", callback_data=f"next_{session_token}_{user_id}_{page + 1}_{query}"))
            
        buttons.append(nav_buttons)

    if settings.get("filter_delete_enabled", False):
        m_time = settings.get("filter_delete_time", 5)
        text += f"\n\n⏳ *Note: This message auto-deletes in {m_time} minutes.*"

    return text, InlineKeyboardMarkup(buttons) if buttons else None, True


# ==========================================
# 🚀 MASTER RENDER & DISPATCH ENGINE
# ==========================================
async def send_search_display(
    client: Client,
    chat_id: int,
    message_id: int,
    mode: str,
    filtered_results: list,
    metadata: dict,
    user_id: int,
    session_token: str,
    query: str,
    page: int,
    shortener_on: bool,
    color_mode: bool,
    bulk_btn,
    chat_type,
    resolved_lang: str,
    resolved_size: str,
    settings: dict
):
    """
    Renders and deploys the message corresponding to the active mode.
    """
    results = filtered_results[page * 10 : (page + 1) * 10]
    total_pages = math.ceil(len(filtered_results) / 10)

    if mode == "matrix":
        content, markup, is_text_only = render_matrix_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )
    elif mode == "hypertext":
        content, markup, is_text_only = render_hypertext_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )
    elif mode == "interactive":
        content, markup, is_text_only = render_interactive_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, resolved_lang, resolved_size, settings
        )
    else:  # default mode
        content, markup, is_text_only = render_default_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )

    # ========================================================
    # 🌟 GROUP QUEUE SYSTEM (Limits Flooding, Sends to Group)
    # ========================================================
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        async with GROUP_THROTTLE_LOCKS[chat_id]:
            now = time.time()
            time_since_last = now - GROUP_LAST_SENT[chat_id]
            
            # If a message was sent less than 3 seconds ago, queue it!
            if time_since_last < 3.0:
                await asyncio.sleep(3.0 - time_since_last)

            # Send directly to the group
            if is_text_only:
                try:
                    msg = await client.send_message(
                        chat_id=chat_id, text=content, reply_markup=markup, 
                        disable_web_page_preview=True, reply_parameters=ReplyParameters(message_id=message_id)
                    )
                except Exception:
                    msg = await client.send_message(chat_id=chat_id, text=content, reply_markup=markup, disable_web_page_preview=True)
            else:
                try:
                    msg = await client.send_photo(
                        chat_id=chat_id, photo=metadata["poster"], caption=content, 
                        reply_markup=markup, reply_parameters=ReplyParameters(message_id=message_id)
                    )
                except Exception:
                    msg = await client.send_message(chat_id=chat_id, text=content, reply_markup=markup)

            # Record exactly when this message was sent to reset the queue timer
            GROUP_LAST_SENT[chat_id] = time.time()

    # ========================================================
    # 🌟 PRIVATE MESSAGE SYSTEM (Instant, No Queue Needed)
    # ========================================================
    else:
        if is_text_only:
            try:
                msg = await client.send_message(
                    chat_id=chat_id, text=content, reply_markup=markup, 
                    disable_web_page_preview=True, reply_parameters=ReplyParameters(message_id=message_id)
                )
            except Exception:
                msg = await client.send_message(chat_id=chat_id, text=content, reply_markup=markup, disable_web_page_preview=True)
        else:
            try:
                msg = await client.send_photo(
                    chat_id=chat_id, photo=metadata["poster"], caption=content, 
                    reply_markup=markup, reply_parameters=ReplyParameters(message_id=message_id)
                )
            except Exception:
                msg = await client.send_message(chat_id=chat_id, text=content, reply_markup=markup)

    if settings.get("filter_delete_enabled", False):
        from plugins.advanced import trigger_ghost_self_destruct
        trigger_ghost_self_destruct(client, chat_id, msg.id, settings.get("filter_delete_time", 5) * 60)

    return msg


async def update_pagination_display(
    client: Client,
    callback: CallbackQuery,
    mode: str,
    filtered_results: list,
    metadata: dict,
    user_id: int,
    session_token: str,
    base_query: str,
    page: int,
    shortener_on: bool,
    color_mode: bool,
    bulk_btn,
    chat_type,
    resolved_lang: str,
    resolved_size: str,
    settings: dict
):
    """
    Rerenders message page views on callback execution.
    """
    results = filtered_results[page * 10 : (page + 1) * 10]
    total_pages = math.ceil(len(filtered_results) / 10)

    if mode == "matrix":
        content, markup, is_text_only = render_matrix_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, base_query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )
    elif mode == "hypertext":
        content, markup, is_text_only = render_hypertext_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, base_query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )
    elif mode == "interactive":
        content, markup, is_text_only = render_interactive_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, base_query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, resolved_lang, resolved_size, settings
        )
    else:
        content, markup, is_text_only = render_default_mode(
            results, filtered_results, metadata, user_id, client.me.username, 
            session_token, base_query, page, total_pages, shortener_on, color_mode, 
            bulk_btn, chat_type, settings
        )

    try:
        if is_text_only:
            await callback.message.edit_text(content, reply_markup=markup, disable_web_page_preview=True)
        else:
            await callback.message.edit_reply_markup(reply_markup=markup)
    except Exception:
        pass
    await callback.answer()


async def update_bulk_display(
    client: Client,
    callback: CallbackQuery,
    mode: str,
    results: list,
    filtered_results: list,
    metadata: dict,
    user_id: int,
    session_token: str,
    session_id: str,
    movie_idx: int,
    page: int,
    shortener_on: bool,
    color_mode: bool,
    bulk_btn,
    chat_type,
    settings: dict
):
    """
    Renders the Bulk Movie Select view, respecting the user's layout mode.
    """
    from pyrogram.types import InputMediaPhoto
    
    buttons = []
    if bulk_btn:
        buttons.append([bulk_btn])

    caption = ""
    is_text_only = False

    if mode == "hypertext":
        is_text_only = True
        caption = f"🍿 <u>**{metadata['title']} ({metadata['release_date'][:4]})**</u>\n"
        caption += f"⭐️ **Rating:** `{metadata['rating']}` | 🗣 `{metadata['language']}`\n\n"
        caption += "👇 **Click a link to receive your file:**\n\n"
        for file in results:
            db_id = str(file.get("_id", ""))
            f_size = format_size(file.get('size', 0))
            f_title = str(file.get('title', 'Unknown File')).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            link = f"https://t.me/{client.me.username}?start=getfile_{db_id}"
            caption += f"📁 <a href='{link}'>[{f_size}] {f_title}</a>\n\n"
        caption += f"━━━━━━━━━━━━━━━━━━\n🔍 **Found:** `{len(filtered_results)}` matching files."
        buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    elif mode == "matrix":
        is_text_only = True
        caption = (
            f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
            f"⭐️ **Rating:** `{metadata['rating']}` | 🎭 `{metadata['genre']}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, file in enumerate(results):
            emoji = number_emojis[idx] if idx < 10 else str(idx + 1)
            f_size = format_size(file.get('size', 0))
            f_title = str(file.get('title', 'Unknown File')).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            audio = str(file.get("language", "unknown")).title()
            if audio == "Pending": audio = "Scanning..."
            
            subs = str(file.get("subtitle", "none")).title()
            if subs == "Pending": subs = "Scanning..."
            
            caption += f"{emoji} <b>[{f_size}]</b> <code>{f_title}</code>\n"
            caption += f"   ┗ 🔊 <b>{audio}</b> | 💬 <b>{subs}</b>\n\n"
            
        caption += f"━━━━━━━━━━━━━━━━━━\n🔍 **Found:** `{len(filtered_results)}` matching files."
        
        buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])
        
        numeric_rows = []
        current_row = []
        for idx, file in enumerate(results):
            db_id = str(file.get("_id", ""))
            display_num = str(idx + 1)
            if shortener_on:
                btn = style_btn(color_mode, ButtonStyle.PRIMARY, text=display_num, url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")
            else:
                btn = style_btn(color_mode, ButtonStyle.PRIMARY, text=display_num, callback_data=f"sendfile_{session_token}_{user_id}_{db_id}")
            current_row.append(btn)
            if len(current_row) == 5:
                numeric_rows.append(current_row)
                current_row = []
        if current_row:
            numeric_rows.append(current_row)
        buttons.extend(numeric_rows)

    else:
        caption = (
            f"🎬 **{metadata['title']}** ({metadata['release_date'][:4]})\n"
            f"⭐️ **Rating:** `{metadata['rating']}`\n"
            f"🗣 **Language:** `{metadata['language']}`\n"
            f"🎭 **Type:** `{metadata['genre']}`\n\n"
            f"📝 **Synopsis:**\n_{metadata['plot']}_\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔍 **Found:** `{len(filtered_results)}` matching files."
        )
        for file in results:
            db_id = str(file.get("_id", ""))
            f_size = format_size(file.get('size', 0))
            rnd_color = random.choice([ButtonStyle.PRIMARY, ButtonStyle.SUCCESS, ButtonStyle.DANGER])
            
            if shortener_on: 
                buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
            else: 
                buttons.append([style_btn(color_mode, rnd_color, text=f"📂 [{f_size}] - {file.get('title', 'Unknown')}", callback_data=f"sendfile_{session_token}_{user_id}_{db_id}")])
                
        buttons.append([style_btn(color_mode, ButtonStyle.SUCCESS, text="🤝 Help Us!", callback_data="help_us_menu")])

    total_pages = math.ceil(len(filtered_results) / 10)
    if len(filtered_results) > 10:
        nav_buttons = []
        if page > 0: 
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="◀️ Prev", callback_data=f"bms_sel_{session_token}_{session_id}_{movie_idx}_{page - 1}_{user_id}"))
        nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text=f"Page {page + 1} of {total_pages}", callback_data="pages_info"))
        if len(filtered_results) > (page + 1) * 10: 
            nav_buttons.append(style_btn(color_mode, ButtonStyle.PRIMARY, text="Next ▶️", callback_data=f"bms_sel_{session_token}_{session_id}_{movie_idx}_{page + 1}_{user_id}"))
        buttons.append(nav_buttons)

    buttons.append([style_btn(color_mode, ButtonStyle.DANGER, text="⬅ Back to Movie List", callback_data=f"bms_back_{session_token}_{user_id}_{session_id}")])
    
    markup = InlineKeyboardMarkup(buttons)
    
    # 🚀 CLEANED UP EXECUTION BLOCK - NO DUPLICATES
    try:
        is_media = bool(callback.message.photo or callback.message.video or callback.message.document)
        new_msg = None
        
        if is_text_only or (is_media and len(caption) > 1000):
            if is_media:
                await callback.message.delete()
                new_msg = await client.send_message(
                    chat_id=callback.message.chat.id,
                    text=caption,
                    reply_markup=markup,
                    disable_web_page_preview=True
                )
            else:
                await callback.message.edit_text(caption, reply_markup=markup, disable_web_page_preview=True)
        else:
            try:
                await callback.message.edit_media(InputMediaPhoto(media=metadata["poster"], caption=caption))
                await callback.message.edit_reply_markup(reply_markup=markup)
            except Exception:
                await callback.message.edit_caption(caption, reply_markup=markup)
                
        # 🚀 Re-attach the auto-delete timer if a new message was spawned!
        if new_msg and settings.get("filter_delete_enabled", False):
            from plugins.advanced import trigger_ghost_self_destruct
            trigger_ghost_self_destruct(client, callback.message.chat.id, new_msg.id, settings.get("filter_delete_time", 5) * 60)
            
    except Exception:
        pass
        
    await callback.answer()
