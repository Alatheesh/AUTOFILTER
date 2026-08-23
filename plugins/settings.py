import logging
import asyncio
import json
import time
import datetime
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ChatType, ButtonStyle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config
from database.multi_db import db
from plugins.background_worker import is_fast_mode_active, toggle_fast_mode

logger = logging.getLogger(__name__)

START_TIME = time.time()
ADMIN_STATE = {}

CODE_STICKERS = ["CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE"]
GHOST_STICKERS = ["CAACAgEAAxkBAAERawtqNX0dllDVZhRw9UkAAeIssj3C9RAAAtEBAAI-HjBHuHEaSdq4kGA8BA"]

def is_creator(user_id: int) -> bool:
    return user_id in Config.ADMINS

def format_bytes(size):
    power, n = 2**10, 0
    power_labels = {0 : '', 1: 'KB', 2: 'MB', 3: 'GB'}
    while size > power: size /= power; n += 1
    return f"{size:.2f} {power_labels[n]}"

def format_eta(seconds):
    if seconds <= 0: return "🎉 Fully Processed!"
    days, hours, minutes = seconds // 86400, (seconds % 86400) // 3600, (seconds % 3600) // 60
    eta = []
    if days > 0: eta.append(f"{int(days)}d")
    if hours > 0: eta.append(f"{int(hours)}h")
    if minutes > 0: eta.append(f"{int(minutes)}m")
    return " ".join(eta) if eta else "< 1 minute"

def format_uptime(seconds):
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, sec = divmod(remainder, 60)
    parts = []
    if days: parts.append(f"{int(days)}d")
    if hours: parts.append(f"{int(hours)}h")
    if minutes: parts.append(f"{int(minutes)}m")
    parts.append(f"{int(sec)}s")
    return " ".join(parts) if parts else "Just started"

# ==========================================
# 🧠 UNIFIED ADMIN INPUT CATCHER (Group -5)
# ==========================================
@Client.on_message(filters.text & filters.private, group=-5)
async def admin_input_catcher(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_STATE:
        raise ContinuePropagation 

    if message.text.startswith("/"):
        del ADMIN_STATE[user_id]
        raise ContinuePropagation

    state_data = ADMIN_STATE[user_id]
    state, prompt_msg_id, timestamp = state_data["state"], state_data.get("msg_id"), state_data.get("timestamp", 0)

    if time.time() - timestamp > 172800:
        del ADMIN_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        expired_text = "⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please restart the setup."
        if prompt_msg_id:
            try: await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=expired_text)
            except Exception: await message.reply_text(expired_text)
        else: await message.reply_text(expired_text)
        raise StopPropagation

    user_input = message.text.strip()

    async def finish_input(success_text, back_callback="set_home"):
        del ADMIN_STATE[user_id]
        try: await message.delete() 
        except Exception: pass
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data=back_callback)]])
        if prompt_msg_id:
            try: await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=success_text, reply_markup=markup)
            except Exception: await message.reply_text(success_text, reply_markup=markup)
        else: await message.reply_text(success_text, reply_markup=markup)

    # 🛑 MODERATION CONFIGURATIONS
    if state.startswith("setup_badwords_") or state.startswith("setup_warnlimit_") or state.startswith("setup_mutelimit_"):
        parts = state.split("_")
        key, scope, chat_id = parts[1], parts[2], parts[3]
        back_callback = f"mod_menu_automute_{scope}_{chat_id}" if key in ["badwords", "warnlimit"] else f"mod_menu_autoban_{scope}_{chat_id}"

        if key == "badwords":
            words = [w.strip().lower() for w in user_input.split(",") if w.strip()]
            if scope == "global": await db.update_settings({"bad_words": words})
            else: await db.update_group_setting(int(chat_id), "bad_words", words)
            await finish_input(f"✅ **Bad words permanently saved in database:**\n`{', '.join(words)}`", back_callback)

        elif key == "warnlimit":
            if user_input.isdigit():
                limit = int(user_input)
                if scope == "global": await db.update_settings({"warn_limit": limit})
                else: await db.update_group_setting(int(chat_id), "warn_limit", limit)
                await finish_input(f"✅ **Warns limit set to:** `{limit}`\nUsers will be auto-muted after {limit} warnings.", back_callback)
            else: await message.reply_text("❌ **Invalid Input!** Please send only a number.")

        elif key == "mutelimit":
            if user_input.isdigit():
                limit = int(user_input)
                if scope == "global": await db.update_settings({"mute_limit": limit})
                else: await db.update_group_setting(int(chat_id), "mute_limit", limit)
                await finish_input(f"✅ **Mutes limit set to:** `{limit}`\nUsers will be auto-banned after {limit} mutes.", back_callback)
            else: await message.reply_text("❌ **Invalid Input!** Please send only a number.")

    # ⚙️ CORE ADMIN CONFIGURATIONS
    elif state == "setup_inside_words":
        words = [w.strip() for w in user_input.split() if w.strip()]
        await db.update_settings({"inside_words": words})
        await finish_input(f"✅ **Words Saved!**\n`{words}`", "set_inside")

    elif state == "setup_inside_times":
        if user_input.isdigit():
            await db.update_settings({"inside_times": int(user_input)})
            await finish_input(f"✅ **Times Saved:** `{user_input}` per day.", "set_inside")
        else: await message.reply_text("❌ **Invalid Input!** Please send only a number (e.g., `4`).")

    elif state == "setup_inside_channels":
        channels = [c.strip() for c in user_input.split() if c.strip()]
        await db.update_settings({"inside_channels": channels})
        await finish_input(f"✅ **Channels Saved!**\n`{channels}`", "set_inside")

    elif state == "setup_shortener_url":
        await db.update_settings({"shortener_url": user_input})
        ADMIN_STATE[user_id] = {"state": "setup_shortener_api", "msg_id": prompt_msg_id, "timestamp": time.time()}
        try: await message.delete() 
        except Exception: pass
        text = "✅ **URL Saved!**\n\nNow, please send me your secret **API Key** for this shortener."
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]])
        if prompt_msg_id:
            try: await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=text, reply_markup=markup)
            except Exception: 
                msg = await message.reply_text(text, reply_markup=markup)
                ADMIN_STATE[user_id]["msg_id"] = msg.id
        else:
            msg = await message.reply_text(text, reply_markup=markup)
            ADMIN_STATE[user_id]["msg_id"] = msg.id

    elif state == "setup_shortener_api":
        await db.update_settings({"shortener_api": user_input, "shortener_enabled": True})
        await finish_input("✅ **Success!** API Key saved and Shortener is now **🟢 ON**.", "set_shortener")

    elif state == "waiting_for_api":
        await db.update_settings({"shortener_api": user_input})
        await finish_input("✅ **Success!** API Key updated in the database.", "set_shortener")

    elif state == "waiting_for_url":
        await db.update_settings({"shortener_url": user_input})
        await finish_input("✅ **Success!** Shortener Link updated in the database.", "set_shortener")

    elif state == "setup_file_time":
        if user_input.isdigit():
            await db.update_settings({"file_delete_time": int(user_input)})
            await finish_input(f"✅ **File Delete Time Saved:** `{user_input} Minutes`", "set_autodelete")
        else: await message.reply_text("❌ **Invalid Input!** Please send only a number in minutes (e.g., `30`).")

    elif state == "setup_filter_time":
        if user_input.isdigit():
            await db.update_settings({"filter_delete_time": int(user_input)})
            await finish_input(f"✅ **Filter Delete Time Saved:** `{user_input} Minutes`", "set_autodelete")
        else: await message.reply_text("❌ **Invalid Input!** Please send only a number in minutes (e.g., `5`).")

    # 📝 FILE CAPTION INPUT CATCHER
    elif state.startswith("setup_caption_"):
        scope = state.replace("setup_caption_", "")
        
        if scope == "global":
            await db.set_custom_caption(None, user_input, is_global=True)
            back_callback = "set_caption_global"
        else:
            chat_id = int(scope)
            await db.set_custom_caption(chat_id, user_input, is_global=False)
            back_callback = f"set_caption_{chat_id}" # 🚀 FIXED: Removed 'local_'
            
        await finish_input(f"✅ **Custom Caption Saved!**\n\nPreview:\n{user_input}", back_callback)
            
    raise StopPropagation

# ==========================================
# 🛠 MASTER SETTINGS ROUTER
# ==========================================
@Client.on_message(filters.command("settings"))
async def settings_router(client: Client, message: Message):
    if not message.from_user: return
    user_id = message.from_user.id
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(message.chat.id)
        if not g_sett.get("connected_by"):
            return await message.reply_text("⚠️ **Group Not Connected!**\nAn admin must send `/connect` in this group first to initialize the bot.")
            
        if g_sett.get("connected_by") != user_id and not is_creator(user_id):
            return await message.reply_text("🛑 **Access Denied:** Only the Primary Connector who linked this group can change its settings.")

        mode = g_sett.get("search_mode", "let_members_choose")
        c_mode = g_sett.get("color_mode", "let_members_choose")
        
        # 🔄 Cycle Logic for Layout
        if mode == "let_members_choose": mode_btn = InlineKeyboardButton("Layout: Let Members Choose 🔄", callback_data=f"gset_mode_force_default_{message.chat.id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_default": mode_btn = InlineKeyboardButton("Layout: Forced Default 🔄", callback_data=f"gset_mode_force_interactive_{message.chat.id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_interactive": mode_btn = InlineKeyboardButton("Layout: Forced Interactive 🔄", callback_data=f"gset_mode_force_hypertext_{message.chat.id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_hypertext": mode_btn = InlineKeyboardButton("Layout: Forced Matrix 🔄", callback_data=f"gset_mode_force_matrix_{message.chat.id}", style=ButtonStyle.PRIMARY)
        else: mode_btn = InlineKeyboardButton("Layout: Forced Matrix 🔄", callback_data=f"gset_mode_let_members_choose_{message.chat.id}", style=ButtonStyle.PRIMARY)

        # 🎨 Cycle Logic for Colors
        if c_mode == "let_members_choose": color_btn = InlineKeyboardButton("Colors: Let Members Choose 🔄", callback_data=f"gset_color_force_on_{message.chat.id}", style=ButtonStyle.PRIMARY)
        elif c_mode == "force_on": color_btn = InlineKeyboardButton("Colors: Forced ON 🔄", callback_data=f"gset_color_force_off_{message.chat.id}", style=ButtonStyle.PRIMARY)
        else: color_btn = InlineKeyboardButton("Colors: Forced OFF 🔄", callback_data=f"gset_color_let_members_choose_{message.chat.id}", style=ButtonStyle.PRIMARY)

        buttons = [
            [InlineKeyboardButton("🛡️ Moderation Rules Hub", callback_data=f"set_mod_local_{message.chat.id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 File Caption Settings", callback_data=f"set_caption_{message.chat.id}", style=ButtonStyle.PRIMARY)],
            [mode_btn],
            [color_btn]
        ]
        await message.reply_text(f"🛠️ **Group Settings Menu:** `{message.chat.title}`\nConfigure settings and moderation limits for this group:", reply_markup=InlineKeyboardMarkup(buttons))
        raise StopPropagation

    else:
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home", style=ButtonStyle.PRIMARY)]]
        if await db.get_connected_groups(user_id): keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list", style=ButtonStyle.PRIMARY)])
        if is_creator(user_id):
            keyboard.append([InlineKeyboardButton("📊 User Stats Dashboard", callback_data="ui_userstats", style=ButtonStyle.PRIMARY)])
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home", style=ButtonStyle.SUCCESS)])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Features", callback_data="ui_features", style=ButtonStyle.DANGER)])
            
        await message.reply_text("🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:", reply_markup=InlineKeyboardMarkup(keyboard))
        raise StopPropagation

@Client.on_message(filters.command("admin") & filters.user(Config.ADMINS))
async def admin_direct_command(client: Client, message: Message):
    text = "👑 **Bot Creator Control Panel**\n\nSelect a master module to configure:"
    buttons = [
        [InlineKeyboardButton("🔗 Shortener Settings", callback_data="set_shortener", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("📝 Request Feature", callback_data="set_requests", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🕵️‍♂️ Inside Settings", callback_data="set_inside", style=ButtonStyle.PRIMARY)], 
        [InlineKeyboardButton("🗑 Search & Auto-Delete Settings", callback_data="set_autodelete", style=ButtonStyle.PRIMARY)], 
        [InlineKeyboardButton("📝 Global File Caption", callback_data="set_caption_global", style=ButtonStyle.PRIMARY)], 
        [InlineKeyboardButton("🛡️ Global Moderation Hub", callback_data="set_mod_global", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 Exit", callback_data="tier_root_fallback", style=ButtonStyle.DANGER)]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    raise StopPropagation

# ==========================================
# 🎛️ USER & GROUP SETTINGS CALLBACKS
# ==========================================
@Client.on_callback_query(filters.regex(r"^(tier_|gset_|uset_|menu_)"))
async def menus_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    if data == "tier_user_home":
        u_sett = await db.get_user_settings(user_id)
        m = u_sett.get("search_mode", "default")
        c = u_sett.get("color_mode", False) # 🎨 NEW
        buttons = [
            [InlineKeyboardButton(text=f"{'✅' if m=='default' else '❌'} Default Mode", callback_data="uset_mode_default", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text=f"{'✅' if m=='interactive' else '❌'} Interactive Mode", callback_data="uset_mode_interactive", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text=f"{'✅' if m=='hypertext' else '❌'} HyperText Mode", callback_data="uset_mode_hypertext", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text=f"{'✅' if m=='matrix' else '❌'} Matrix Mode", callback_data="uset_mode_matrix", style=ButtonStyle.PRIMARY)], 
            [InlineKeyboardButton(text=f"{'✅' if c else '❌'} Colorful Buttons UI", callback_data="uset_toggle_color", style=ButtonStyle.SUCCESS)]
        ]
        if m == "interactive": buttons.append([InlineKeyboardButton(text="⚙️ Configure File Size & Language", callback_data="uset_interactive_menu", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback", style=ButtonStyle.DANGER)])
        return await query.message.edit_text("👤 **Personal Display Preferences:**\nChoose how output records populate on your workspace screen:", reply_markup=InlineKeyboardMarkup(buttons))

    if data == "uset_mode_default":
        await db.update_user_setting(user_id, "search_mode", "default")
        query.data = "tier_user_home"; return await menus_callback_handler(client, query)

    if data == "uset_mode_interactive":
        await db.update_user_setting(user_id, "search_mode", "interactive")
        query.data = "uset_interactive_menu"; return await menus_callback_handler(client, query)

    if data == "uset_mode_hypertext":
        await db.update_user_setting(user_id, "search_mode", "hypertext")
        query.data = "tier_user_home"; return await menus_callback_handler(client, query)

    if data == "uset_mode_matrix":
        await db.update_user_setting(user_id, "search_mode", "matrix")
        query.data = "tier_user_home"; return await menus_callback_handler(client, query)

    # 🎨 NEW: Handler for Personal Color Toggle
    if data == "uset_toggle_color":
        u_sett = await db.get_user_settings(user_id)
        await db.update_user_setting(user_id, "color_mode", not u_sett.get("color_mode", False))
        query.data = "tier_user_home"; return await menus_callback_handler(client, query)

    if data == "uset_interactive_menu":
        u_sett = await db.get_user_settings(user_id)
        s, l = u_sett.get("size", "all"), u_sett.get("language", "all")
        buttons = [
            [InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data="uset_s_small", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data="uset_s_medium", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data="uset_s_large", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data="uset_s_xlarge", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data="uset_s_all", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data="uset_l_tamil", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data="uset_l_telugu", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data="uset_l_hindi", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data="uset_l_all", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Save & Return", callback_data="tier_user_home", style=ButtonStyle.SUCCESS)]
        ]
        try:
            return await query.message.edit_text("✨ **Interactive Mode Filter Settings**", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            return await query.answer() # Silently ignores double-clicks

    if data.startswith("uset_s_"):
        await db.update_user_setting(user_id, "size", data.replace("uset_s_", "")); query.data = "uset_interactive_menu"; return await menus_callback_handler(client, query)
    if data.startswith("uset_l_"):
        await db.update_user_setting(user_id, "language", data.replace("uset_l_", "")); query.data = "uset_interactive_menu"; return await menus_callback_handler(client, query)

    if data == "tier_group_list":
        managed = await db.get_connected_groups(user_id)
        if not managed: return await query.answer("No linked administration nodes found.", show_alert=True)
        buttons = [[InlineKeyboardButton(text=f"⚙️ {g.get('title', 'Chat ID: ' + str(g['chat_id']))}", callback_data=f"tier_gmanage_{g['chat_id']}", style=ButtonStyle.PRIMARY)] for g in managed]
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback", style=ButtonStyle.DANGER)])
        return await query.message.edit_text("🛡️ **Administered Groups Portal**", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("tier_gmanage_"):
        c_id = int(data.split("_")[2])
        g_sett = await db.get_group_settings(c_id)
        if g_sett.get("connected_by") != user_id and not is_creator(user_id): return await query.answer("Access Denied.", show_alert=True)
        
        mode = g_sett.get("search_mode", "let_members_choose")
        c_mode = g_sett.get("color_mode", "let_members_choose")
        
        # 🔄 Cycle Logic for Layout (CALLBACK VERSION)
        if mode == "let_members_choose": mode_btn = InlineKeyboardButton("Layout: Let Members Choose 🔄", callback_data=f"gset_mode_force_default_{c_id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_default": mode_btn = InlineKeyboardButton("Layout: Forced Default 🔄", callback_data=f"gset_mode_force_interactive_{c_id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_interactive": mode_btn = InlineKeyboardButton("Layout: Forced Interactive 🔄", callback_data=f"gset_mode_force_hypertext_{c_id}", style=ButtonStyle.PRIMARY)
        elif mode == "force_hypertext": mode_btn = InlineKeyboardButton("Layout: Forced Matrix 🔄", callback_data=f"gset_mode_force_matrix_{c_id}", style=ButtonStyle.PRIMARY)
        else: mode_btn = InlineKeyboardButton("Layout: Forced Matrix 🔄", callback_data=f"gset_mode_let_members_choose_{c_id}", style=ButtonStyle.PRIMARY)

        # 🎨 Cycle Logic for Colors
        if c_mode == "let_members_choose": color_btn = InlineKeyboardButton("Colors: Let Members Choose 🔄", callback_data=f"gset_color_force_on_{c_id}", style=ButtonStyle.PRIMARY)
        elif c_mode == "force_on": color_btn = InlineKeyboardButton("Colors: Forced ON 🔄", callback_data=f"gset_color_force_off_{c_id}", style=ButtonStyle.PRIMARY)
        else: color_btn = InlineKeyboardButton("Colors: Forced OFF 🔄", callback_data=f"gset_color_let_members_choose_{c_id}", style=ButtonStyle.PRIMARY)

        buttons = [
            [InlineKeyboardButton("🛡️ Moderation Rules Hub", callback_data=f"set_mod_local_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 File Caption Settings", callback_data=f"set_caption_{c_id}", style=ButtonStyle.PRIMARY)],
            [mode_btn],
            [color_btn]
        ]
        if mode == "force_interactive": buttons.append([InlineKeyboardButton("⚙️ Configure Group Size & Language", callback_data=f"gset_interactive_menu_{c_id}", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton("🔙 Back to List", callback_data="tier_group_list", style=ButtonStyle.DANGER)])
        
        try:
            return await query.message.edit_text(f"🛠️ **Remote Group Matrix Interface**", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            return await query.answer() # CRASH PREVENTION: Ignores spam clicks silently

    if data.startswith("gset_mode_"):
        chat_id = int(data.split("_")[-1])
        # 🚀 THE FIX: Safely extract the mode name without hardcoding list checks
        target_mode = data.replace("gset_mode_", "").replace(f"_{chat_id}", "")
        
        g_sett = await db.get_group_settings(chat_id)
        if g_sett.get("search_mode") == target_mode:
            return await query.answer("Already set to this mode!", show_alert=False) # CRASH PREVENTION
            
        await db.update_group_setting(chat_id, "search_mode", target_mode)
        await query.answer("Group layout policy updated.", show_alert=False)
        query.data = f"tier_gmanage_{chat_id}"
        return await menus_callback_handler(client, query)

    if data.startswith("gset_color_"):
        parts = data.split("_")
        chat_id = int(parts[-1])
        target_mode = "_".join(parts[2:-1]) 
        
        g_sett = await db.get_group_settings(chat_id)
        if g_sett.get("color_mode") == target_mode:
            return await query.answer("Already set to this mode!", show_alert=False) # CRASH PREVENTION

        await db.update_group_setting(chat_id, "color_mode", target_mode)
        await query.answer("Group color policy updated.", show_alert=False)
        query.data = f"tier_gmanage_{chat_id}"
        return await menus_callback_handler(client, query)

    if data.startswith("gset_interactive_menu_"):
        c_id = int(data.split("_")[3])
        g_sett = await db.get_group_settings(c_id)
        s, l = g_sett.get("size_lock", "all"), g_sett.get("language_lock", "all")
        buttons = [
            [InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data=f"gset_s_small_{c_id}", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data=f"gset_s_medium_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data=f"gset_s_large_{c_id}", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data=f"gset_s_xlarge_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data=f"gset_s_all_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data=f"gset_l_tamil_{c_id}", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data=f"gset_l_telugu_{c_id}", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data=f"gset_l_hindi_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data=f"gset_l_all_{c_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Save & Return", callback_data=f"tier_gmanage_{c_id}", style=ButtonStyle.SUCCESS)]
        ]
        try:
            return await query.message.edit_text("✨ **Group Interactive Filters**", reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            return await query.answer() # Silently ignores double-clicks

    if data.startswith("gset_s_"):
        await db.update_group_setting(int(data.split("_")[3]), "size_lock", data.split("_")[2]); query.data = f"gset_interactive_menu_{data.split('_')[3]}"; return await menus_callback_handler(client, query)
    if data.startswith("gset_l_"):
        await db.update_group_setting(int(data.split("_")[3]), "language_lock", data.split("_")[2]); query.data = f"gset_interactive_menu_{data.split('_')[3]}"; return await menus_callback_handler(client, query)

    if data == "tier_root_fallback":
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home", style=ButtonStyle.PRIMARY)]]
        if await db.get_connected_groups(user_id): keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list", style=ButtonStyle.PRIMARY)])
        if is_creator(user_id):
            keyboard.append([InlineKeyboardButton("📊 User Stats Dashboard", callback_data="ui_userstats", style=ButtonStyle.PRIMARY)])
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home", style=ButtonStyle.SUCCESS)])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Features", callback_data="ui_features", style=ButtonStyle.DANGER)])
        
        return await query.message.edit_text("🎛️ **Central Command Settings Hub**", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# 👑 CREATOR & MODERATION CALLBACKS
# ==========================================
@Client.on_callback_query(filters.regex(r"^(set_home|set_inside|set_shortener|set_requests|set_autodelete|toggle_multisearch|set_mod_|mod_|inside_|time_|toggle_|set_placements|toggle_place_|set_caption_|edit_caption_|del_caption_|guide_caption_|set_toggle|set_api|set_url)"))
async def settings_callbacks(client: Client, callback: CallbackQuery):
    action = callback.data
    user_id = callback.from_user.id

    if action in ["set_home", "set_inside", "set_shortener", "set_requests", "set_autodelete"] or action.startswith("set_mod_") or action.startswith("set_caption_"):
        if user_id in ADMIN_STATE: del ADMIN_STATE[user_id]

    if action == "set_home":
        text = "👑 **Bot Creator Control Panel**\n\nSelect a master module to configure:"
        buttons = [
            [InlineKeyboardButton("🔗 Shortener Settings", callback_data="set_shortener", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 Request Feature", callback_data="set_requests", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🕵️‍♂️ Inside Settings", callback_data="set_inside", style=ButtonStyle.PRIMARY)], 
            [InlineKeyboardButton("🗑 Search & Auto-Delete Settings", callback_data="set_autodelete", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 Global File Caption", callback_data="set_caption_global", style=ButtonStyle.PRIMARY)], 
            [InlineKeyboardButton("🛡️ Global Moderation Hub", callback_data="set_mod_global", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Exit", callback_data="tier_root_fallback", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # --- THE ADVANCED MODERATION HUB ---
    elif action.startswith("set_mod_"):
        parts = action.split("_")
        scope = parts[2]
        chat_id = parts[3] if len(parts) > 3 else "global"
        back_btn = "set_home" if scope == "global" else f"tier_gmanage_{chat_id}"

        text = f"🛡️ **{'GLOBAL' if scope=='global' else 'LOCAL'} MODERATION HUB**\n\nSelect a punishment module to configure:"
        buttons = [
            [InlineKeyboardButton("🔇 Auto-Mute Rules", callback_data=f"mod_menu_automute_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🚫 Auto-Ban Rules", callback_data=f"mod_menu_autoban_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back", callback_data=back_btn, style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("mod_menu_automute_"):
        parts = action.split("_"); scope = parts[3]; chat_id = parts[4]
        sett = await db.get_settings() if scope == "global" else await db.get_group_settings(int(chat_id))

        am_en = sett.get("auto_mute_enabled", False)
        link_en = sett.get("anti_link_enabled", False)
        bw_en = sett.get("bad_words_enabled", False)
        warn_lim = sett.get("warn_limit", 3)

        text = f"🔇 **AUTO-MUTE CONFIGURATION**\n\nConfigure triggers that will automatically issue warnings. Reaching the Warns Limit triggers an Auto-Mute."
        buttons = [
            [InlineKeyboardButton(f"Auto-Mute Engine: {'🟢 ON' if am_en else '🔴 OFF'}", callback_data=f"mod_toggle_automute_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"🔗 Track Links: {'🟢 ON' if link_en else '🔴 OFF'}", callback_data=f"mod_toggle_antilink_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"🤬 Track Bad Words: {'🟢 ON' if bw_en else '🔴 OFF'}", callback_data=f"mod_toggle_badwords_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 Edit Bad Words Database", callback_data=f"mod_edit_badwords_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"⚠️ Warns Limit: {warn_lim}", callback_data=f"mod_edit_warnlimit_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back", callback_data=f"set_mod_{scope}_{chat_id}", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("mod_menu_autoban_"):
        parts = action.split("_"); scope = parts[3]; chat_id = parts[4]
        sett = await db.get_settings() if scope == "global" else await db.get_group_settings(int(chat_id))

        ab_en = sett.get("auto_ban_enabled", False)
        mute_lim = sett.get("mute_limit", 3)

        text = f"🚫 **AUTO-BAN CONFIGURATION**\n\nAutomatically ban users who continually break the rules and accumulate too many Mutes."
        buttons = [
            [InlineKeyboardButton(f"Auto-Ban Engine: {'🟢 ON' if ab_en else '🔴 OFF'}", callback_data=f"mod_toggle_autoban_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"🔇 Mutes Limit: {mute_lim}", callback_data=f"mod_edit_mutelimit_{scope}_{chat_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back", callback_data=f"set_mod_{scope}_{chat_id}", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("mod_toggle_"):
        parts = action.split("_"); key, scope, chat_id = parts[2], parts[3], parts[4]
        key_map = {"automute": "auto_mute_enabled", "antilink": "anti_link_enabled", "badwords": "bad_words_enabled", "autoban": "auto_ban_enabled"}
        db_key = key_map[key]

        if scope == "global":
            sett = await db.get_settings()
            await db.update_settings({db_key: not sett.get(db_key, False)})
        else:
            sett = await db.get_group_settings(int(chat_id))
            await db.update_group_setting(int(chat_id), db_key, not sett.get(db_key, False))

        callback.data = f"mod_menu_automute_{scope}_{chat_id}" if key in ["automute", "antilink", "badwords"] else f"mod_menu_autoban_{scope}_{chat_id}"
        await settings_callbacks(client, callback)

    elif action.startswith("mod_edit_"):
        parts = action.split("_"); key, scope, chat_id = parts[2], parts[3], parts[4]
        ADMIN_STATE[user_id] = {"state": f"setup_{key}_{scope}_{chat_id}", "msg_id": callback.message.id, "timestamp": time.time()}
        back_btn = f"mod_menu_automute_{scope}_{chat_id}" if key in ["badwords", "warnlimit"] else f"mod_menu_autoban_{scope}_{chat_id}"

        if key == "badwords": msg = "📝 **Send me the list of bad words separated by commas.**\n*(These are permanently saved in the database even if you turn the toggle off)*\nExample: `porn, bet, casino`"
        elif key == "warnlimit": msg = "⚠️ **Send the number of WARNINGS a user can receive before they are Auto-Muted.**\n*(This value is permanently saved in the database)*\nExample: `3`"
        elif key == "mutelimit": msg = "🔇 **Send the number of MUTES a user can receive before they are Auto-Banned.**\n*(This value is permanently saved in the database)*\nExample: `3`"

        await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=back_btn)]]))

    # --- CORE SETTINGS ---
    elif action == "set_inside":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("inside_enabled", False) else "🔴 OFF"
        words, times, channels = settings.get("inside_words", []), settings.get("inside_times", 5), settings.get("inside_channels", [])
        
        legacy_p = settings.get("inside_placement", "movie")
        placements = settings.get("inside_placements", [legacy_p] if isinstance(legacy_p, str) else ["movie"])
        p_str = ", ".join([p.capitalize() for p in placements]) if placements else "None"

        text = (
            f"🕵️‍♂️ **Inside Task Settings**\n\n"
            f"**Status:** {status}\n"
            f"**Trigger Words:** `{', '.join(words) if words else 'None Set'}`\n"
            f"**Pass Limit:** `{times} times/day`\n"
            f"**Target Channels:** `{', '.join(channels) if channels else 'None Set'}`\n"
            f"**Active Placements:** `{p_str}`\n\n"
            f"Use the buttons below to modify the task verification flow:"
        )
        buttons = [
            [InlineKeyboardButton(f"Toggle Feature {'OFF' if 'ON' in status else 'ON'}", callback_data="inside_toggle", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📝 Edit Words", callback_data="inside_words", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⏱ Edit Times", callback_data="inside_times", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📢 Edit Channels", callback_data="inside_channels", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📍 Edit Placements", callback_data="set_placements", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="set_home", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "inside_toggle":
        settings = await db.get_settings()
        await db.update_settings({"inside_enabled": not settings.get("inside_enabled", False)})
        callback.data = "set_inside"; await settings_callbacks(client, callback)

    elif action == "inside_words":
        ADMIN_STATE[user_id] = {"state": "setup_inside_words", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the trigger words in the chat.**\nSeparate them with spaces (e.g., `#example1 #sponsor2`).", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]]))

    elif action == "inside_times":
        ADMIN_STATE[user_id] = {"state": "setup_inside_times", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the number of verifications per day.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]]))

    elif action == "inside_channels":
        ADMIN_STATE[user_id] = {"state": "setup_inside_channels", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the Target Channel Usernames or IDs.**\nSeparate multiple with spaces.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_inside")]]))

    elif action == "set_placements":
        settings = await db.get_settings()
        legacy_p = settings.get("inside_placement", "movie")
        placements = settings.get("inside_placements", [legacy_p] if isinstance(legacy_p, str) else ["movie"])

        m_status = "✅" if "movie" in placements else "❌"
        w_status = "✅" if "welcome" in placements else "❌"

        text = (
            "📍 **Verification Placements**\n\n"
            "Select where the verification lock should be enforced. You can enable multiple at the same time!"
        )
        buttons = [
            [InlineKeyboardButton(f"{m_status} Movie Downloads", callback_data="toggle_place_movie", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"{w_status} Welcome Menu (/start)", callback_data="toggle_place_welcome", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back", callback_data="set_inside", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action.startswith("toggle_place_"):
        place = action.split("_")[2] # "movie" or "welcome"
        settings = await db.get_settings()
        legacy_p = settings.get("inside_placement", "movie")
        placements = settings.get("inside_placements", [legacy_p] if isinstance(legacy_p, str) else ["movie"])

        if place in placements: placements.remove(place)
        else: placements.append(place)

        await db.update_settings({"inside_placements": placements})
        callback.data = "set_placements"; await settings_callbacks(client, callback)

    elif action == "set_shortener":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("shortener_enabled", False) else "🔴 OFF"
        api, url = settings.get("shortener_api", "Not Set"), settings.get("shortener_url", "Not Set")

        text = f"🔗 **Shortener Configurations**\n\n**Status:** {status}\n**Current URL Template:** `{url}`\n**Current API Key:** `{api}`\n\n📖 **Auto-Setup:** Send `/setshort <your_full_link>` directly in the chat to auto-configure!"
        buttons = [
            [InlineKeyboardButton(f"Toggle Shortener {'OFF' if 'ON' in status else 'ON'}", callback_data="set_toggle", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("✏️ Change API Key", callback_data="set_api", style=ButtonStyle.PRIMARY), InlineKeyboardButton("✏️ Change Link", callback_data="set_url", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back", callback_data="set_home", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "set_toggle":
        settings = await db.get_settings()
        if settings.get("shortener_enabled", False): await db.update_settings({"shortener_enabled": False})
        else:
            ADMIN_STATE[user_id] = {"state": "setup_shortener_url", "msg_id": callback.message.id, "timestamp": time.time()}
            return await callback.message.edit_text("🛠 **Shortener Setup**\nSend me the **Shortener URL** in the chat.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]]))
        callback.data = "set_shortener"; await settings_callbacks(client, callback)

    elif action == "set_api":
        ADMIN_STATE[user_id] = {"state": "waiting_for_api", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the new API Key.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]]))

    elif action == "set_url":
        ADMIN_STATE[user_id] = {"state": "waiting_for_url", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the new URL Link template.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_shortener")]]))

    elif action == "set_requests":
        settings = await db.get_settings()
        status = "🟢 ON" if settings.get("requests_enabled", True) else "🔴 OFF"
        text = f"📝 **Movie Request Feature**\n\n**Status:** {status}\n\nWhen ON, users can use `/request` when a movie isn't found."
        buttons = [[InlineKeyboardButton(f"Toggle Requests {'OFF' if 'ON' in status else 'ON'}", callback_data="toggle_requests")], [InlineKeyboardButton("🔙 Back", callback_data="set_home")]]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "toggle_requests":
        settings = await db.get_settings()
        await db.update_settings({"requests_enabled": not settings.get("requests_enabled", True)})
        callback.data = "set_requests"; await settings_callbacks(client, callback)

    # 🚀 UPGRADED: SEARCH & AUTO-DELETE HUB
    elif action == "set_autodelete":
        settings = await db.get_settings()
        
        f_status = "🟢 ON" if settings.get("file_delete_enabled", False) else "🔴 OFF"
        m_status = "🟢 ON" if settings.get("filter_delete_enabled", False) else "🔴 OFF"
        ms_status = "🟢 ON" if settings.get("multi_search_enabled", True) else "🔴 OFF"
        
        f_time = settings.get("file_delete_time", 10)
        m_time = settings.get("filter_delete_time", 5)

        text = (
            f"🗑 **Search & Auto-Delete Settings**\n\n"
            f"🌟 **Multi-Search Engine:** {ms_status}\n"
            f"📂 **File Deletion:** {f_status} `({f_time} mins)`\n"
            f"🔍 **Search Filter Deletion:** {m_status} `({m_time} mins)`"
        )
        buttons = [
            [InlineKeyboardButton(f"Files: {f_status}", callback_data="toggle_file_del", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"Filters: {m_status}", callback_data="toggle_filter_del", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("⏱ Set File Time", callback_data="time_file_del", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⏱ Set Filter Time", callback_data="time_filter_del", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(f"🌟 Multi-Search Engine: {ms_status}", callback_data="toggle_multisearch", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="set_home", style=ButtonStyle.DANGER)]
        ]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # 🚀 NEW: MULTI-SEARCH TOGGLE HANDLER
    elif action == "toggle_multisearch":
        settings = await db.get_settings()
        await db.update_settings({"multi_search_enabled": not settings.get("multi_search_enabled", True)})
        callback.data = "set_autodelete"
        await settings_callbacks(client, callback)

    elif action == "toggle_file_del":
        settings = await db.get_settings()
        await db.update_settings({"file_delete_enabled": not settings.get("file_delete_enabled", False)})
        callback.data = "set_autodelete"; await settings_callbacks(client, callback)

    elif action == "toggle_filter_del":
        settings = await db.get_settings()
        await db.update_settings({"filter_delete_enabled": not settings.get("filter_delete_enabled", False)})
        callback.data = "set_autodelete"; await settings_callbacks(client, callback)

    elif action == "time_file_del":
        ADMIN_STATE[user_id] = {"state": "setup_file_time", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the File Auto-Delete time in MINUTES.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_autodelete")]]))

    elif action == "time_filter_del":
        ADMIN_STATE[user_id] = {"state": "setup_filter_time", "msg_id": callback.message.id, "timestamp": time.time()}
        await callback.message.edit_text("✏️ **Send the Search Result Auto-Delete time in MINUTES.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="set_autodelete")]]))

    # 📝 FILE CAPTION MENUS & LOGIC
    elif action.startswith("set_caption_"):
        scope = action.replace("set_caption_", "")
        
        # Check if they have a custom caption currently
        if scope == "global":
            bot_settings = await db.settings.find_one({"_id": "bot_settings"})
            has_custom = bot_settings and bot_settings.get("custom_caption") is not None
            back_btn = "set_home"
            title = "GLOBAL"
        else:
            chat_id = int(scope)
            group = await db.groups.find_one({"chat_id": chat_id})
            has_custom = group and group.get("custom_caption") is not None
            back_btn = f"tier_gmanage_{chat_id}"
            title = f"GROUP ({chat_id})"
            
        text = f"📝 **{title} File Caption Settings**\n\nCustomize the text sent alongside movie files."
        if has_custom: text += "\n\n🟢 **Status:** Custom Caption Active"
        else: text += "\n\n🟡 **Status:** Using Default/Fallback Caption"
        
        buttons = [
            [InlineKeyboardButton("✏️ Change Caption", callback_data=f"edit_caption_{scope}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("📖 Caption Guide", callback_data=f"guide_caption_{scope}", style=ButtonStyle.PRIMARY)]
        ]
        if has_custom:
            buttons.insert(1, [InlineKeyboardButton("🗑 Delete Custom Caption", callback_data=f"del_caption_{scope}", style=ButtonStyle.DANGER)])
            
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=back_btn, style=ButtonStyle.DANGER)])
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        
    elif action.startswith("edit_caption_"):
        scope = action.replace("edit_caption_", "")
        ADMIN_STATE[user_id] = {"state": f"setup_caption_{scope}", "msg_id": callback.message.id, "timestamp": time.time()}
        
        text = "✏️ **Send me the new HTML Caption.**\n\nYou can use placeholders like `{file_name}`, `{size}`, and `{mention}`.\nCheck the Guide for more details."
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=f"set_caption_{scope}")]]))
        
    elif action.startswith("guide_caption_"):
        scope = action.replace("guide_caption_", "")
        text = (
            "📖 **Caption Formatting Guide**\n\n"
            "You can use standard HTML tags (like `<b>`, `<i>`, `<code>`, `<a href='url'>`).\n\n"
            "**Dynamic Placeholders:**\n"
            "• `{file_name}` : Original file name.\n"
            "• `{size}` : File size (e.g., 1.5 GB).\n"
            "• `{mention}` : Tags the user requesting the file.\n\n"
            "**Example Setup:**\n"
            "`<b>{file_name}</b>`\n"
            "`Size: {size}`\n"
            "`Requested by: {mention}`"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"set_caption_{scope}")]]))

    elif action.startswith("del_caption_"):
        scope = action.replace("del_caption_", "")
        if scope == "global":
            await db.delete_custom_caption(None, is_global=True)
        else:
            await db.delete_custom_caption(int(scope), is_global=False)
            
        await callback.answer("✅ Custom caption removed. Reverting to default.", show_alert=True)
        callback.data = f"set_caption_{scope}"
        await settings_callbacks(client, callback)

# ==========================================
# 📊 SYSTEM ADMIN COMMANDS & STATS DASHBOARDS
# ==========================================

@Client.on_message(filters.command("backup") & filters.user(Config.ADMINS))
async def multi_shard_json_backup(client: Client, message: Message):

    progress = await message.reply_text(
        "📥 **Connecting to database Shard 0...**"
    )

    try:
        # The actual MongoDB database for Shard 0
        database = db.collections[0].database

        # Collections that should NOT be included in the backup
        excluded_collections = {
            "files",
            "index",
            "indexes"
        }

        # Get all collection names
        collection_names = await database.list_collection_names()

        backup_data = {}
        total_documents = 0

        for collection_name in collection_names:

            # Skip files and index collections
            if collection_name.lower() in excluded_collections:
                continue

            await progress.edit_text(
                f"📦 **Backing up data...**\n\n"
                f"📂 Collection: `{collection_name}`\n"
                f"⏳ Processing..."
            )

            collection = database[collection_name]

            # Get ALL documents — no 1000 limit
            cursor = collection.find({})

            documents = await cursor.to_list(length=None)

            # Convert MongoDB ObjectId and other BSON values safely
            cleaned_documents = []

            for document in documents:
                cleaned_documents.append(
                    json.loads(
                        json.dumps(
                            document,
                            default=str
                        )
                    )
                )

            # Add collection data to backup
            backup_data[collection_name] = cleaned_documents

            total_documents += len(cleaned_documents)

        # Create backup file
        backup_file = "shard0_backup.json"

        with open(
            backup_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                backup_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        await progress.edit_text(
            f"📤 **Uploading backup to Telegram...**\n\n"
            f"📊 Processed `{total_documents}` documents."
        )

        await message.reply_document(
            backup_file,
            caption=(
                f"📦 **Database Backup Export**\n\n"
                f"💾 Shard: `0`\n"
                f"📊 Total Documents: `{total_documents}`\n\n"
                f"❌ Excluded: `files`, `index`, `indexes`"
            )
        )

        # Delete temporary backup after sending
        if os.path.exists(backup_file):
            os.remove(backup_file)

        await progress.delete()

    except Exception as e:

        await progress.edit_text(
            f"❌ **Database Backup Failed:**\n"
            f"`{str(e)}`"
        )

    raise StopPropagation

@Client.on_message(filters.command("clear_job") & filters.user(Config.ADMINS))
async def clear_active_job(client: Client, message: Message):
    job = await db.get_active_job()
    if job: await db.update_job(job["_id"], {"status": "completed"}); await message.reply_text("✅ **Stuck indexing job marked as completed.**")
    else: await message.reply_text("⚠️ **No active job found.**")
    raise StopPropagation

@Client.on_message(filters.command("userstats") & filters.user(Config.ADMINS))
async def get_user_stats(client: Client, message: Message):

    progress = await message.reply_text(
        "📊 **Calculating user statistics...**"
    )

    try:
        # ==========================================
        # 👥 BASIC USER STATISTICS
        # ==========================================

        total_users = await db.users.count_documents({})

        search_result = await db.users.aggregate([
            {
                "$group": {
                    "_id": None,
                    "total_searches": {
                        "$sum": {
                            "$ifNull": [
                                "$total_searches",
                                0
                            ]
                        }
                    }
                }
            }
        ]).to_list(length=1)

        total_searches = (
            search_result[0].get("total_searches", 0)
            if search_result else 0
        )

        average_searches = (
            round(total_searches / total_users, 2)
            if total_users > 0 else 0
        )

        users_with_no_searches = await db.users.count_documents({
            "$or": [
                {"total_searches": {"$exists": False}},
                {"total_searches": 0},
                {"total_searches": None}
            ]
        })


        # ==========================================
        # ⚙️ USER PREFERENCES
        # ==========================================

        async def get_most_used(field):

            result = await db.users.aggregate([
                {
                    "$match": {
                        field: {
                            "$exists": True,
                            "$nin": [None, ""]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": f"${field}",
                        "count": {
                            "$sum": 1
                        }
                    }
                },
                {
                    "$sort": {
                        "count": -1
                    }
                },
                {
                    "$limit": 1
                }
            ]).to_list(length=1)

            if result:
                return str(result[0]["_id"])

            return "N/A"


        most_search_mode = await get_most_used(
            "search_mode"
        )

        most_quality = await get_most_used(
            "quality"
        )

        most_language = await get_most_used(
            "language"
        )

        most_size = await get_most_used(
            "size"
        )


        # ==========================================
        # 💎 VIP STATISTICS
        # ==========================================

        import time
        from datetime import datetime

        current_time = time.time()

        # Correct VIP collection
        vip_documents = await db.vip_users.find(
            {}
        ).to_list(length=None)

        active_vip = 0
        expired_vip = 0
        trial_users = 0
        plan_distribution = {}

        for vip in vip_documents:

            # --------------------------------------
            # Get plan from existing document formats
            # --------------------------------------

            plan = (
                vip.get("plan")
                or vip.get("plan_id")
                or "Unknown"
            )

            # --------------------------------------
            # Detect trial users
            # Trial documents use started_at
            # --------------------------------------

            is_trial = (
                "started_at" in vip
                and "plan_id" in vip
            )

            if is_trial:
                trial_users += 1

            # --------------------------------------
            # Get expiry from both formats
            # --------------------------------------

            expiry = (
                vip.get("expiry")
                or vip.get("expires_at")
            )

            # Convert datetime expiry if necessary
            if isinstance(expiry, datetime):
                expiry = expiry.timestamp()

            # Convert string timestamp if necessary
            try:
                if expiry is not None:
                    expiry = float(expiry)
            except (ValueError, TypeError):
                expiry = None

            # Normalize status
            status = str(
                vip.get("status", "")
            ).lower()

            # --------------------------------------
            # Active / Expired calculation
            # --------------------------------------

            if expiry is not None:

                if expiry > current_time:

                    # Trial users are counted separately
                    if not is_trial:
                        active_vip += 1

                else:

                    # Trial users are counted separately
                    if not is_trial:
                        expired_vip += 1

            elif status == "active":

                # VIP marked active without expiry
                if not is_trial:
                    active_vip += 1

            elif status:

                # Any other status
                if not is_trial:
                    expired_vip += 1

            # --------------------------------------
            # Plan Distribution
            # --------------------------------------

            plan_distribution[plan] = (
                plan_distribution.get(plan, 0) + 1
            )


        # ==========================================
        # 📊 BUILD PLAN DISTRIBUTION
        # ==========================================

        if plan_distribution:

            plan_text = ""

            for plan, count in sorted(
                plan_distribution.items(),
                key=lambda item: item[1],
                reverse=True
            ):

                plan_text += (
                    f"\n   • `{plan}`: `{count:,}`"
                )

        else:

            plan_text = (
                "\n   • No VIP plans found"
            )


        # ==========================================
        # 📊 FINAL MESSAGE
        # ==========================================

        stats_text = (
            "📊 **USER STATISTICS**\n\n"

            f"👥 Total Users: `{total_users:,}`\n"
            f"🔎 Total Searches: `{total_searches:,}`\n"
            f"📈 Average Searches/User: "
            f"`{average_searches}`\n"
            f"😴 Users With 0 Searches: "
            f"`{users_with_no_searches:,}`\n\n"

            "━━━━━━━━━━━━━━\n\n"

            "⚙️ **USER PREFERENCES**\n\n"

            f"🔍 Most Used Search Mode: "
            f"`{most_search_mode}`\n"

            f"🎬 Most Selected Quality: "
            f"`{most_quality}`\n"

            f"🌐 Most Selected Language: "
            f"`{most_language}`\n"

            f"📦 Most Selected Size: "
            f"`{most_size}`\n\n"

            "━━━━━━━━━━━━━━\n\n"

            "💎 **VIP STATISTICS**\n\n"

            f"├ 🟢 Active VIP Users: "
            f"`{active_vip:,}`\n"

            f"├ ⌛ Expired VIP Users: "
            f"`{expired_vip:,}`\n"

            f"├ 🎁 Trial Users: "
            f"`{trial_users:,}`\n"

            f"└ 📊 Plan Distribution:"
            f"{plan_text}"
        )

        await progress.edit_text(
            stats_text
        )

    except Exception as e:

        await progress.edit_text(
            "❌ **Failed to get user statistics**\n\n"
            f"`{str(e)}`"
        )

    raise StopPropagation

async def get_stats_home_text_and_buttons():
    db_stats = await db.global_stats()
    shards_text = "".join([f"• **Shard {idx + 1}**: `{count:,}` files\n" for idx, count in enumerate(db_stats.get("shard_distribution", []))])
    text = f"📊 **Advanced System Status Dashboard**\n\n⏱️ **Bot Uptime:** `{format_uptime(time.time() - START_TIME)}`\n🗂️ **Total Indexed Files:** `{db_stats.get('total_files', 0):,}`\n\n💾 **Storage Analytics:**\n• **Space Used:** `{format_bytes(db_stats.get('total_size_bytes', 0))}`\n• **Space Remaining:** `{format_bytes(db_stats.get('space_left_bytes', 0))}`\n\n🖲️ **Shard Distribution:**\n{shards_text}"
    buttons = [
        [InlineKeyboardButton("⚙️ Worker 1: Indexing", callback_data="stats_worker1", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⚙️ Worker 2: Metadata", callback_data="stats_worker2", style=ButtonStyle.PRIMARY)], 
        [InlineKeyboardButton("⚙️ Worker 3: Broadcast Engine", callback_data="stats_worker3_home", style=ButtonStyle.PRIMARY)], 
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="stats_refresh_home", style=ButtonStyle.SUCCESS)]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker1_text_and_buttons():
    active_job = await db.get_active_job()
    
    # 🚀 NEW: Dynamically count how many channels are queued or processing
    queue_count = await db.jobs.count_documents({"status": {"$in": ["pending", "processing"]}})
    
    if active_job:
        target = active_job.get("chat_name", "Unknown Channel")
        scanned = active_job.get("scanned", 0)
        saved = active_job.get("saved", 0)
        duplicates = active_job.get("duplicates", 0)
        current_id = active_job.get("current_id", 0)

        remaining = max(0, current_id)
        total_msgs = scanned + remaining
        idx_pct = round((scanned / total_msgs * 100), 2) if total_msgs > 0 else 0.0

        skipped_empty = scanned - (saved + duplicates)
        if skipped_empty < 0:
            skipped_empty = 0

        if remaining <= 0:
            status_text = "✅ Completed (Sleeping)"
            idx_eta_string = "🎉 Fully Processed!"
        else:
            status_text = "🔄 Active (Deep Scan in Progress...)"
            idx_eta_seconds = remaining * 0.4  
            idx_eta_string = format_eta(idx_eta_seconds)

        text = (
            f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
            f"🔄 **Status:** `{status_text}`\n"
            f"📡 **Channels in Queue:** `{queue_count}`\n\n"
            f"• **Target Channel:** `{target}`\n"
            f"• **Scanned:** `{scanned:,}` | **Remaining to Scan:** `{remaining:,}`\n"
            f"• **Total Progress:** `{scanned:,}` / `{total_msgs:,}` (`{idx_pct}%`)\n"
            f"• **Estimated Time Left:** `{idx_eta_string}`\n\n"
            f"📂 **Content Deep-Breakdown:**\n"
            f"• **New Media Saved:** `{saved:,}`\n"
            f"• **Duplicates Skipped:** `{duplicates:,}`\n"
            f"• **Deleted / Empty Skipped:** `{skipped_empty:,}`\n\n"
            f"💡 *Tip: Use `/indexdata` to export all queued job details.*"
        )
    else:
        text = (
            f"⚙️ **WORKER 1: Mass Channel Indexing**\n"
            f"💤 **Status:** `Idle (Queue Empty)`\n"
            f"📡 **Channels in Queue:** `0`\n\n"
            f"No active mass channel indexing tasks are currently running in the background queue.\n\n"
            f"💡 *Tip: Use `/indexdata` to export all queued job details.*"
        )

    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home", style=ButtonStyle.DANGER),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w1", style=ButtonStyle.SUCCESS)
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker2_text_and_buttons():
    from plugins.background_worker import is_fast_mode_active
    
    db_stats = await db.global_stats()
    total_files = db_stats.get('total_files', 0)
    
    pending_meta = 0
    corrupted_count = 0
    
    for coll in db.collections:
        pending_meta += await coll.count_documents({"language": "pending"})
        corrupted_count += await coll.count_documents({"language": {"$in": ["unknown", "corrupted"]}})

    indexed_meta = total_files - pending_meta - corrupted_count
    
    is_fast = is_fast_mode_active()
    time_per_file = 2.0 if is_fast else 4.5 
    
    meta_eta_seconds = pending_meta * time_per_file 
    meta_eta_string = format_eta(meta_eta_seconds)
    
    processed_files = total_files - pending_meta
    meta_pct = (processed_files / total_files * 100) if total_files > 0 else 100

    text = (
        f"⚙️ **WORKER 2: Language & Metadata Extraction**\n"
        f"🔄 **Status:** `Processing Database Shards...`\n\n"
        f"• **Extracted Files:** `{indexed_meta:,}` / `{total_files:,}`\n"
        f"• **Corrupted / Skipped:** `{corrupted_count:,}` files\n"
        f"• **Current Progress:** `{meta_pct:.1f}%` complete\n"
        f"• **Pending Migration Queue:** `{pending_meta:,}` files left\n"
        f"• **Estimated Completion Time (ETA):** `{meta_eta_string}`"
    )

    fast_status = "⚡ Fast Mode: ON" if is_fast else "🐢 Fast Mode: OFF"

    buttons = [
        [
            InlineKeyboardButton(fast_status, callback_data="stats_toggle_fastmode", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w2", style=ButtonStyle.SUCCESS)
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home", style=ButtonStyle.DANGER)
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def get_worker3_home_text_and_buttons():
    pending_count = await db.scheduled_broadcasts.count_documents({"status": "pending"})
    vault_count = await db.broadcast_logs.count_documents({"timestamp": {"$gte": time.time() - (48 * 3600)}})
    text = f"⚙️ **WORKER 3: Broadcast & Scheduler Engine**\n🔄 **Status:** `Active & Monitoring`\n\n• **Pending Scheduled Jobs:** `{pending_count}`\n• **Messages in 48H Vault:** `{vault_count}`"
    
    buttons = [
        [
            InlineKeyboardButton("📅 Scheduled Queue", callback_data="stats_worker3_sched", style=ButtonStyle.PRIMARY), 
            InlineKeyboardButton("📡 Recent Batches", callback_data="stats_worker3_recent", style=ButtonStyle.PRIMARY)
        ], 
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_home", style=ButtonStyle.DANGER), 
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_home", style=ButtonStyle.SUCCESS)
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)


async def get_worker3_sched_text_and_buttons():
    schedules = await db.scheduled_broadcasts.find({"status": "pending"}).sort("run_at", 1).limit(5).to_list(length=5)
    text = f"📅 **SCHEDULED BROADCAST QUEUE**\n\n**Total Pending Jobs:** `{await db.scheduled_broadcasts.count_documents({'status': 'pending'})}`\n\n"
    
    if not schedules: 
        text += "No broadcasts are currently scheduled."
    else:
        for s in schedules: 
            text += f"• `{s['batch_id']}` - ⏳ `{datetime.datetime.fromtimestamp(s['run_at'], datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %I:%M %p')}`\n"
            
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_worker3_home", style=ButtonStyle.DANGER), 
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_sched", style=ButtonStyle.SUCCESS)
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)


async def get_worker3_recent_text_and_buttons():
    text = f"📡 **RECENT BROADCAST BATCHES (48H Vault)**\n\n"
    has_batches = False
    
    async for batch in await db.get_recent_batches():
        has_batches, b_id = True, batch["_id"]
        eng = await db.get_batch_engagement(b_id)
        text += f"• **{b_id}**: `{batch['count']} sent` | 💬 `{eng['replies']} replies` | 🔄 `{eng['followups']} follows`\n"
        
    if not has_batches: 
        text += "No broadcasts sent in the last 48 hours."
        
    buttons = [
        [
            InlineKeyboardButton("🔙 Back", callback_data="stats_worker3_home", style=ButtonStyle.DANGER), 
            InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh_w3_recent", style=ButtonStyle.SUCCESS)
        ]
    ]
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def bot_stats_dashboard(client: Client, message: Message):
    status_msg = await message.reply_text("📊 **Querying core analytics engine...**")
    text, markup = await get_stats_home_text_and_buttons()
    await status_msg.edit_text(text, reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^stats_"))
async def stats_callback_handler(client: Client, callback: CallbackQuery):
    action = callback.data
    try:
        if action == "stats_toggle_fastmode":
            from plugins.background_worker import toggle_fast_mode
            new_state = toggle_fast_mode()
            status_msg = "Fast Mode Activated! ⚡" if new_state else "Returned to Normal Speed 🐢"
            await callback.answer(status_msg, show_alert=False)
            
            text, markup = await get_worker2_text_and_buttons()
            return await callback.message.edit_text(text, reply_markup=markup)

        # 🚀 THE NEW RECHECK BUTTON LOGIC IS SAFELY INJECTED HERE
        if action == "stats_toggle_recheck":
            from plugins.background_worker import is_recheck_mode_active, start_recheck_mode, stop_recheck_mode
            
            if is_recheck_mode_active():
                stop_recheck_mode()
                await callback.answer("⏹ Recheck mode stopped.", show_alert=False)
            else:
                # 🛑 RULE ENFORCEMENT: Check for pending files across all shards
                pending_count = 0
                for coll in db.collections:
                    pending_count += await coll.count_documents({"language": "pending"})
                
                if pending_count > 0:
                    return await callback.answer(f"⚠️ Cannot start recheck!\n\nThere are still {pending_count} unskipped (pending) files currently processing. Let them finish first.", show_alert=True)
                
                # If clean, start the engine!
                start_recheck_mode()
                await callback.answer("🔄 Recheck mode activated! Worker 2 is now scanning skipped/corrupted files.", show_alert=True)
            
            text, markup = await get_worker2_text_and_buttons()
            return await callback.message.edit_text(text, reply_markup=markup)

        if action == "stats_home": text, markup = await get_stats_home_text_and_buttons()
        elif action == "stats_worker1": text, markup = await get_worker1_text_and_buttons()
        elif action == "stats_worker2": text, markup = await get_worker2_text_and_buttons()
        elif action == "stats_worker3_home": text, markup = await get_worker3_home_text_and_buttons()
        elif action == "stats_worker3_sched": text, markup = await get_worker3_sched_text_and_buttons()
        elif action == "stats_worker3_recent": text, markup = await get_worker3_recent_text_and_buttons()
        elif action in ["stats_refresh_home", "stats_refresh_w1", "stats_refresh_w2", "stats_refresh_w3_home", "stats_refresh_w3_sched", "stats_refresh_w3_recent"]:
            await callback.answer("🔄 Metrics synchronized successfully!", show_alert=False)
            if action == "stats_refresh_home": text, markup = await get_stats_home_text_and_buttons()
            elif action == "stats_refresh_w1": text, markup = await get_worker1_text_and_buttons()
            elif action == "stats_refresh_w2": text, markup = await get_worker2_text_and_buttons()
            elif action == "stats_refresh_w3_home": text, markup = await get_worker3_home_text_and_buttons()
            elif action == "stats_refresh_w3_sched": text, markup = await get_worker3_sched_text_and_buttons()
            elif action == "stats_refresh_w3_recent": text, markup = await get_worker3_recent_text_and_buttons()
            
        await callback.message.edit_text(text, reply_markup=markup)
    except Exception: 
        await callback.answer("⚠️ Processing sync issue. Try running /stats again.", show_alert=True)

# ==========================================
# 📊 USER STATS CALLBACK HANDLER
# ==========================================
@Client.on_callback_query(filters.regex("^ui_userstats$") & filters.user(Config.ADMINS))
async def on_ui_userstats(client: Client, callback: CallbackQuery):
    total_users = await db.users.count_documents({})
    total_muted = await db.punishments.count_documents({"type": "mute"})
    total_banned = await db.punishments.count_documents({"type": "ban"})
    
    stats_text = (
        f"📊 **Bot User Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"🟢 Active Users: `{total_users - total_banned}`\n"
        f"🔇 Total Muted: `{total_muted}`\n"
        f"🚫 Total Banned: `{total_banned}`\n\n"
        f"⚙️ **Admin Shortcuts:**\n"
        f"`/mute <id> [time] [reason]`\n"
        f"`/ban <id> [reason]`"
    )
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="tier_root_fallback", style=ButtonStyle.DANGER)]])
    
    try:
        await callback.message.edit_text(stats_text, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        await callback.answer("⚠️ Error loading stats.", show_alert=True)
        logger.error(f"User Stats UI Error: {e}")
