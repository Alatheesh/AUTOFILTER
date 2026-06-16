import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db

# Active query runtime lookup container tracking filters state parameters safely
FILTER_SESSION_CACHE = {}

@Client.on_message(filters.text & (filters.group | filters.private) & ~filters.command(["start", "settings", "index", "request", "broadcast", "stats", "backup", "plot", "history", "clear_history"]))
async def filter_search_handler(client: Client, message: Message):
    query_text = message.text.strip()
    if len(query_text) < 2: return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # STEP 1: RESOLVE THE 3-TIER OPERATIVE LAYOUT CONTEXT PRECEDENCE
    resolved_mode = "default"
    
    if message.chat.type in ["group", "supergroup"]:
        g_sett = await db.get_group_settings(chat_id)
        g_mode = g_sett.get("search_mode", "let_members_choose")
        
        if g_mode == "force_default":
            resolved_mode = "default"
        elif g_mode == "force_interactive":
            resolved_mode = "interactive"
        else: # Fallback Cascade to individual User Personal PM selection rules
            u_sett = await db.get_user_settings(user_id)
            resolved_mode = u_sett.get("search_mode", "default")
    else:
        # PM context directly takes Tier 1 rules
        u_sett = await db.get_user_settings(user_id)
        resolved_mode = u_sett.get("search_mode", "default")

    # STEP 2: MULTI-SHARD QUERY (Fixed the MultiDB attribute error)
    matching_files = await db.search_files(query_text, skip=0, limit=20, exact=False)
    
    if not matching_files:
        req_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 Request this Movie", callback_data=f"req_{query_text[:40]}")]])
        return await message.reply_text("🔍 No files matched your query pattern.", reply_markup=req_buttons)

    # STEP 3: DISTRIBUTE DISPLAY TO MATCH RESOLVED LAYOUT TYPE RULES
    if resolved_mode == "default":
        # Mode A: Instantly build full results array dump layout immediately
        buttons = []
        for f in matching_files:
            db_id = str(f.get("_id", ""))
            title = f.get("title", "Unknown Title")
            buttons.append([InlineKeyboardButton(text=f"🎬 {title}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        return await message.reply_text(f"🎯 **Results found matching:** `{query_text}`", reply_markup=InlineKeyboardMarkup(buttons))

    else:
        # Mode B: Filter Engine Hub UI Menu Layer Generation Pattern
        session_id = f"{user_id}_{chat_id}_{message.id}"
        FILTER_SESSION_CACHE[session_id] = {
            "query": query_text,
            "files": matching_files
        }
        
        buttons = [
            [
                InlineKeyboardButton(text="🎥 Filter Quality", callback_data=f"fui_qual_{session_id}"),
                InlineKeyboardButton(text="🗣️ Filter Language", callback_data=f"fui_lang_{session_id}")
            ],
            [InlineKeyboardButton(text="📜 Show All Files Directly", callback_data=f"fui_all_{session_id}")]
        ]
        return await message.reply_text(
            f"✨ **Search Filter Panel:** `{query_text}`\nRefine file distribution lists dynamically using filters:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

@Client.on_callback_query(filters.regex(r"^fui_"))
async def filter_ui_callback_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split("_")
    action = parts[1]
    session_id = f"{parts[2]}_{parts[3]}_{parts[4]}"
    
    session = FILTER_SESSION_CACHE.get(session_id)
    if not session:
        return await query.answer("Search validation cache expired. Please execute a fresh query.", show_alert=True)
        
    files_pool = session["files"]

    if action == "all":
        buttons = []
        for f in files_pool:
            db_id = str(f.get("_id", ""))
            title = f.get("title", "Unknown Title")
            buttons.append([InlineKeyboardButton(text=f"🎬 {title}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
        return await query.message.edit_text("🍿 **Displaying unparsed comprehensive file list index details:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "qual":
        buttons = [
            [
                InlineKeyboardButton(text="1080p Only", callback_data=f"fsub_run_{session_id}_1080p"),
                InlineKeyboardButton(text="720p Only", callback_data=f"fsub_run_{session_id}_720p")
            ],
            [
                InlineKeyboardButton(text="480p Only", callback_data=f"fsub_run_{session_id}_480p"),
                InlineKeyboardButton(text="🔙 Back", callback_data=f"fsub_back_{session_id}")
            ]
        ]
        return await query.message.edit_text("🎥 **Select the maximum parsing resolution quality matrix standard parameter:**", reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "lang":
        buttons = [
            [
                InlineKeyboardButton(text="Tamil Audio", callback_data=f"fsub_run_{session_id}_tamil"),
                InlineKeyboardButton(text="Telugu Audio", callback_data=f"fsub_run_{session_id}_telugu")
            ],
            [
                InlineKeyboardButton(text="Hindi Audio", callback_data=f"fsub_run_{session_id}_hindi"),
                InlineKeyboardButton(text="🔙 Back", callback_data=f"fsub_back_{session_id}")
            ]
        ]
        return await query.message.edit_text("🗣️ **Select targeted translation localized sound language pipeline parameter:**", reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^fsub_"))
async def sub_filter_processing_execution_handler(client: Client, query: CallbackQuery):
    data = query.data
    parts = data.split("_")
    action = parts[1]
    session_id = f"{parts[2]}_{parts[3]}_{parts[4]}"
    
    session = FILTER_SESSION_CACHE.get(session_id)
    if not session: return await query.answer("Query cache expired.", show_alert=True)
    
    if action == "back":
        buttons = [
            [
                InlineKeyboardButton(text="🎥 Filter Quality", callback_data=f"fui_qual_{session_id}"),
                InlineKeyboardButton(text="🗣️ Filter Language", callback_data=f"fui_lang_{session_id}")
            ],
            [InlineKeyboardButton(text="📜 Show All Files Directly", callback_data=f"fui_all_{session_id}")]
        ]
        return await query.message.edit_text(f"✨ **Search Filter Panel:** `{session['query']}`\nRefine file distribution lists dynamically using filters:", reply_markup=InlineKeyboardMarkup(buttons))
        
    tag = parts[5].lower()
    filtered_results = [f for f in session["files"] if tag in f.get("title", "").lower()]
    
    if not filtered_results:
        buttons = [[InlineKeyboardButton(text="🔙 Change Filter Settings", callback_data=f"fsub_back_{session_id}")]]
        return await query.message.edit_text(f"❌ No matching criteria parameters isolated for string marker segment: `{tag.upper()}`", reply_markup=InlineKeyboardMarkup(buttons))
        
    buttons = []
    for f in filtered_results:
        db_id = str(f.get("_id", ""))
        title = f.get("title", "Unknown Title")
        buttons.append([InlineKeyboardButton(text=f"🎬 {title}", url=f"https://t.me/{client.me.username}?start=getfile_{db_id}")])
    buttons.append([InlineKeyboardButton(text="🔄 Adjust Filter Selection Rules", callback_data=f"fsub_back_{session_id}")])
    
    await query.message.edit_text(f"🎯 **Filtered Index Results Matrix List [Tag: {tag.upper()}]:**", reply_markup=InlineKeyboardMarkup(buttons))
