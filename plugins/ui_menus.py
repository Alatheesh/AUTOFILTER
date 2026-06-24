import random
import logging
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config
from database.multi_db import db
from plugins.moderation import log_to_channel

logger = logging.getLogger(__name__)

# --- STICKER PACKS ---
START_STICKERS = [
    "CAACAgUAAxkBAAERawdqNXyW6Tqft1iZtgABiTVGhBohxgIAApwAA8iUZBRzjwAB89rFhfw8BA",
    "CAACAgIAAxkBAAERawlqNXy1AwABuumeSFheCDM2d624y90AAiYPAAL7WShJIl_khPeHLac8BA"
]

ROBO_STICKERS = [
    "CAACAgUAAxkBAAERautqNXbvA3JLjJg-U_LbOgNmBXLApQACahIAAvYiyVZikUGUoRZynzwE",
    "CAACAgIAAxkBAAERawFqNXvcF78c77WjPHAAAbL9Yk55HMAAAk4CAAJWnb0KMP5rbYEyA288BA",
    "CAACAgIAAxkBAAERawNqNXvnj-tDUwXqJGB_6BYXFfIn-QACwGoAAjg5aUn8Q0qGpRajKzwE"
]

CODE_STICKERS = [
    "CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE",
    "CAACAgIAAxkBAAERavVqNXpmmnxWeKfo-qv-kP8WdLuqkwACShcAAutrqUl9AevFXbjHDzwE",
    "CAACAgEAAxkBAAERavFqNXnOCL7UtEeSAe3-1MHnnBpLPAACMQIAAoKgIEQHCzBVrLHGhzwE"
]

GHOST_STICKERS = [
    "CAACAgEAAxkBAAERawtqNX0dllDVZhRw9UkAAeIssj3C9RAAAtEBAAI-HjBHuHEaSdq4kGA8BA",
    "CAACAgEAAxkBAAERaw1qNX00vFFh52_2RWDP8AtWrF8evAAC0gEAAuZSMUd-GR6sSPZFxDwE"
]

START_BANNER_IMAGES = [
    "https://telegra.ph/file/c4ddf6a9d136cb1735bb1.jpg",
    "https://telegra.ph/file/b36685221ce5ac41ad667.jpg",
    "https://telegra.ph/file/7f59377ace528148d15bd.jpg",
    "https://telegra.ph/file/e006737306ad1c5c16192.jpg",
    "https://telegra.ph/file/f8b495d98fd4d89c99150.jpg",
    "https://telegra.ph/file/320cdc500bc7e3d1c9e94.jpg",
    "https://telegra.ph/file/90ea7771a7c61e2d45d72.jpg",
    "https://telegra.ph/file/0d6adc21a51a32c3ac803.jpg",
    "https://telegra.ph/file/3fd5587f5bf4c3c107c91.jpg",
    "https://telegra.ph/file/2182f0c156d4ae25c8913.jpg",
    "https://telegra.ph/file/5966212c0662fa84433e8.jpg"
]

# ==========================================
# --- HELPER FUNCTIONS ---
# ==========================================
def get_start_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛠 Help", callback_data="ui_help"),
            InlineKeyboardButton("ℹ️ About", callback_data="ui_about")
        ],
        [
            InlineKeyboardButton("👨‍💻 Source", callback_data="ui_source"),
            InlineKeyboardButton("✨ Features", callback_data="ui_features")
        ]
    ])

def is_creator(user_id: int) -> bool:
    return user_id in Config.ADMINS

# ==========================================
# --- HANDLERS ---
# ==========================================
@Client.on_message(filters.command("start") & filters.private, group=2)
async def start_menu_handler(client: Client, message: Message):
    # Process Appeals without breaking other deep links
    if len(message.command) > 1: 
        cmd = message.command[1]
        if cmd.startswith("appeal_"):
            p_type = cmd.split("_")[1]
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Formal Appeal", callback_data=f"appeal_global_{p_type}")]])
            return await message.reply_text(f"⚖️ **Global {p_type.upper()} Appeal Center**\n\nClick the button below to officially submit your appeal to the Creator.", reply_markup=btn)
        
        # If it is NOT an appeal (e.g. file delivery link), we exit this handler 
        # so your original file-delivery logic can take over perfectly.
        return 
        
    try:
        loading_msg = await message.reply_sticker(random.choice(START_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass
        
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12: greeting = "🌅 Good Morning"
    elif 12 <= current_hour < 17: greeting = "☀️ Good Afternoon"
    elif 17 <= current_hour < 21: greeting = "🌆 Good Evening"
    else: greeting = "🌃 Good Night"

    first_name = message.from_user.first_name if message.from_user else "User"
    username = message.from_user.username or "None"
    
    # Send Log Channel Update
    await log_to_channel(client, f"#new_user\n👤 Name: `{first_name}`\n🆔 ID: `{message.from_user.id}`\n🔗 Username: @{username}")

    welcome_text = (
        f"**{greeting}, {first_name}!**\n\n"
        f"Welcome to the **Cloud Auto-Filter Bot**. I am your personal, lightning-fast database assistant.\n\n"
        f"✨ **Use the interactive buttons below to explore my built-in commands:**"
    )
    
    await message.reply_photo(
        photo=random.choice(START_BANNER_IMAGES),
        caption=welcome_text,
        reply_markup=get_start_markup()
    )

@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(ROBO_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    help_text = (
        "🛠 **How to Use the Auto-Filter Bot:**\n\n"
        "• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n"
        "• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n"
        "• `/connect`: Link your group and become the Primary Connector.\n"
        "• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n"
        "• `/history`: Displays your 10 most recent searches.\n"
        "• `/clear_history`: Wipes your query history records clean.\n"
        "• `/settings`: Open the advanced configuration dashboard."
    )
    await message.reply_text(text=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(ROBO_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    about_text = (
        "ℹ️ **About This Bot:**\n\n"
        "• **Engine:** Advanced Asynchronous Pyrogram V2\n"
        "• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n"
        "• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
        "• **Primary Deployment:** Ready for Hugging Face Spaces free-tier hosting with aiohttp daemon\n"
    )
    await message.reply_text(text=about_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))

@Client.on_message(filters.command("source") & filters.private)
async def source_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    source_text = (
        "👨‍💻 **Open Source Repository Details:**\n\n"
        "This application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n"
        "• **Developer:** Google AI Studio Build Architect\n"
        "• **Credits:** Pyrogram & MongoDB Motor Driver"
    )
    await message.reply_text(text=source_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))

@Client.on_callback_query(filters.regex(r"^ui_(help|about|source|features|back)$"))
async def callback_ui_router(client: Client, callback: CallbackQuery):
    target = callback.data.split("_")[1]
    
    if target == "back":
        username = callback.from_user.username if callback.from_user else "User"
        welcome_text = (
            f"👋 **Welcome to the Cloud Auto-Filter Bot, {username}!**\n\n"
            f"I am a highly-optimized, multi-sharded Telegram repository search system. "
            f"Send me any movie or file query and I'll find it instantly across our high-performing MongoDB clusters.\n\n"
            f"✨ **Use the interactive buttons below to explore my built-in commands/specifications:**"
        )
        await callback.message.edit_text(text=welcome_text, reply_markup=get_start_markup())
        return await callback.answer()

    if target == "help":
        help_text = (
            "🛠 **How to Use the Auto-Filter Bot:**\n\n"
            "• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n"
            "• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n"
            "• `/connect`: Link your group and become the Primary Connector.\n"
            "• `/settings`: Open the advanced configuration dashboard."
        )
        await callback.message.edit_text(text=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))

    elif target == "about":
        about_text = (
            "ℹ️ **About This Bot:**\n\n"
            "• **Engine:** Advanced Asynchronous Pyrogram V2\n"
            "• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n"
            "• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
        )
        await callback.message.edit_text(text=about_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))

    elif target == "source":
        source_text = (
            "👨‍💻 **Open Source Repository Details:**\n\n"
            "This application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n"
            "• **Developer:** Google AI Studio Build Architect\n"
            "• **Credits:** Pyrogram & MongoDB Motor Driver"
        )
        await callback.message.edit_text(text=source_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))

    elif target == "features":
        features_text = (
            "✨ **Bot Feature Profile:**\n\n"
            "• **Dynamic UI:** 3-Tier Default vs Interactive Search Engine.\n"
            "• **Monetization Engine:** GPLinks shortener + double force subscription lock.\n"
            "• **Admin Dashboard:** Mass system-wide broadcasting."
        )
        await callback.message.edit_text(text=features_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))
    
    await callback.answer()

@Client.on_message(filters.command("settings"))
async def settings_router(client: Client, message: Message):
    if not message.from_user: return
    user_id = message.from_user.id
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(message.chat.id)
        connected_by = g_sett.get("connected_by")
        
        if not connected_by:
            try: 
                loading_msg = await message.reply_sticker(random.choice(GHOST_STICKERS))
                await asyncio.sleep(3)
                await loading_msg.delete()
            except Exception: pass
            return await message.reply_text("⚠️ **Group Not Connected!**\nAn admin must send `/connect` in this group first to initialize the bot.")
            
        if connected_by != user_id and not is_creator(user_id):
            try: 
                loading_msg = await message.reply_sticker(random.choice(GHOST_STICKERS))
                await asyncio.sleep(3)
                await loading_msg.delete()
            except Exception: pass
            return await message.reply_text("🛑 **Access Denied:** Only the Primary Connector who linked this group can change its settings.")

        try: 
            loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
            await asyncio.sleep(3)
            await loading_msg.delete()
        except Exception: pass

        mode = g_sett.get("search_mode", "let_members_choose")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if mode=='force_default' else '❌'} Force Default", callback_data=f"gset_mode_force_default_{message.chat.id}"),
                InlineKeyboardButton(text=f"{'✅' if mode=='force_interactive' else '❌'} Force Interactive", callback_data=f"gset_mode_force_interactive_{message.chat.id}")
            ],
            [
                InlineKeyboardButton(text=f"{'✅' if mode=='let_members_choose' else '❌'} Let Members Choose", callback_data=f"gset_mode_let_members_choose_{message.chat.id}")
            ]
        ]
        return await message.reply_text(f"🛠️ **Group Settings Menu:** `{message.chat.title}`\nConfigure search visualization structures for all active participants:", reply_markup=InlineKeyboardMarkup(buttons))

    else:
        try: 
            loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
            await asyncio.sleep(3)
            await loading_msg.delete()
        except Exception: pass

        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]]
        managed_groups = await db.get_connected_groups(user_id)
        if managed_groups:
            keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
        if is_creator(user_id):
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home")])
        await message.reply_text("🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:", reply_markup=InlineKeyboardMarkup(keyboard))

@Client.on_callback_query(filters.regex(r"^(tier_|gset_|uset_)"))
async def menus_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    if data == "tier_user_home":
        u_sett = await db.get_user_settings(user_id)
        m = u_sett.get("search_mode", "default")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if m=='default' else '❌'} Default Mode", callback_data="uset_mode_default"),
                InlineKeyboardButton(text=f"{'✅' if m=='interactive' else '❌'} Interactive Mode", callback_data="uset_mode_interactive")
            ]
        ]
        if m == "interactive": buttons.append([InlineKeyboardButton(text="⚙️ Configure File Size & Language", callback_data="uset_interactive_menu")])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")])
        return await query.message.edit_text("👤 **Personal Display Preferences:**\nChoose how output records populate on your workspace screen:", reply_markup=InlineKeyboardMarkup(buttons))

    if data == "uset_mode_default":
        await db.update_user_setting(user_id, "search_mode", "default")
        query.data = "tier_user_home"
        return await menus_callback_handler(client, query)

    if data == "uset_mode_interactive":
        await db.update_user_setting(user_id, "search_mode", "interactive")
        query.data = "uset_interactive_menu"
        return await menus_callback_handler(client, query)

    if data == "uset_interactive_menu":
        u_sett = await db.get_user_settings(user_id)
        s, l = u_sett.get("size", "all"), u_sett.get("language", "all")
        buttons = [
            [InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data="uset_s_small"), InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data="uset_s_medium")],
            [InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data="uset_s_large"), InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data="uset_s_xlarge")],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data="uset_s_all")],
            [InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data="uset_l_tamil"), InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data="uset_l_telugu"), InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data="uset_l_hindi")],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data="uset_l_all")],
            [InlineKeyboardButton("🔙 Save & Return", callback_data="tier_user_home")]
        ]
        return await query.message.edit_text("✨ **Interactive Mode Filter Settings**", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("uset_s_"):
        await db.update_user_setting(user_id, "size", data.replace("uset_s_", "")); query.data = "uset_interactive_menu"; return await menus_callback_handler(client, query)
    if data.startswith("uset_l_"):
        await db.update_user_setting(user_id, "language", data.replace("uset_l_", "")); query.data = "uset_interactive_menu"; return await menus_callback_handler(client, query)

    if data == "tier_group_list":
        managed = await db.get_connected_groups(user_id)
        if not managed: return await query.answer("No linked administration nodes found.", show_alert=True)
        buttons = [[InlineKeyboardButton(text=f"⚙️ {g.get('title', 'Chat ID: ' + str(g['chat_id']))}", callback_data=f"tier_gmanage_{g['chat_id']}")] for g in managed]
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")])
        return await query.message.edit_text("🛡️ **Administered Groups Portal**", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("tier_gmanage_"):
        c_id = int(data.split("_")[2])
        g_sett = await db.get_group_settings(c_id)
        if g_sett.get("connected_by") != user_id and not is_creator(user_id): return await query.answer("Access Denied.", show_alert=True)
        mode = g_sett.get("search_mode", "let_members_choose")
        buttons = [
            [InlineKeyboardButton(text=f"{'✅' if mode=='force_default' else '❌'} Force Default", callback_data=f"gset_mode_force_default_{c_id}"), InlineKeyboardButton(text=f"{'✅' if mode=='force_interactive' else '❌'} Force Interactive", callback_data=f"gset_mode_force_interactive_{c_id}")],
            [InlineKeyboardButton(text=f"{'✅' if mode=='let_members_choose' else '❌'} Let Members Choose", callback_data=f"gset_mode_let_members_choose_{c_id}")]
        ]
        if mode == "force_interactive": buttons.append([InlineKeyboardButton(text="⚙️ Configure Group Size & Language", callback_data=f"gset_interactive_menu_{c_id}")])
        buttons.append([InlineKeyboardButton(text="🔙 Back to List", callback_data="tier_group_list")])
        return await query.message.edit_text(f"🛠️ **Remote Group Matrix Interface**", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("gset_mode_"):
        parts = data.split("_"); target_mode = f"{parts[2]}_{parts[3]}" if parts[3] in ["default", "interactive"] else f"{parts[2]}_{parts[3]}_{parts[4]}"; chat_id = int(parts[-1])
        await db.update_group_setting(chat_id, "search_mode", target_mode); await query.answer("Group layout policy updated successfully.")
        query.data = f"gset_interactive_menu_{chat_id}" if target_mode == "force_interactive" else f"tier_gmanage_{chat_id}"; return await menus_callback_handler(client, query)

    if data.startswith("gset_interactive_menu_"):
        c_id = int(data.split("_")[3])
        g_sett = await db.get_group_settings(c_id)
        s, l = g_sett.get("size_lock", "all"), g_sett.get("language_lock", "all")
        buttons = [
            [InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data=f"gset_s_small_{c_id}"), InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data=f"gset_s_medium_{c_id}")],
            [InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data=f"gset_s_large_{c_id}"), InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data=f"gset_s_xlarge_{c_id}")],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data=f"gset_s_all_{c_id}")],
            [InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data=f"gset_l_tamil_{c_id}"), InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data=f"gset_l_telugu_{c_id}"), InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data=f"gset_l_hindi_{c_id}")],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data=f"gset_l_all_{c_id}")],
            [InlineKeyboardButton("🔙 Save & Return", callback_data=f"tier_gmanage_{c_id}")]
        ]
        return await query.message.edit_text("✨ **Group Interactive Filters**", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("gset_s_"):
        await db.update_group_setting(int(data.split("_")[3]), "size_lock", data.split("_")[2]); query.data = f"gset_interactive_menu_{data.split('_')[3]}"; return await menus_callback_handler(client, query)
    if data.startswith("gset_l_"):
        await db.update_group_setting(int(data.split("_")[3]), "language_lock", data.split("_")[2]); query.data = f"gset_interactive_menu_{data.split('_')[3]}"; return await menus_callback_handler(client, query)

    if data == "tier_root_fallback":
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]]
        if await db.get_connected_groups(user_id): keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
        if is_creator(user_id): keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home")])
        return await query.message.edit_text("🎛️ **Central Command Settings Hub**", reply_markup=InlineKeyboardMarkup(keyboard))

@Client.on_callback_query(filters.regex(r"^set_"))
async def apply_settings_handler(client: Client, callback: CallbackQuery):
    parts = callback.data.split("_")
    scope, setting_type = parts[1], parts[2]
    user_id, chat_id = callback.from_user.id, callback.message.chat.id
    
    if setting_type == "back":
        if scope == "u":
            u_sett = await db.get_user_settings(user_id)
            mode, lang, size = u_sett.get("search_mode", "default"), u_sett.get("language", "all"), u_sett.get("size", "all")
            text = f"⚙️ **Your Personal Settings**\n\n**Search Mode:** `{mode}`\n**Audio Preference:** `{lang}`\n**Size Preference:** `{size}`"
            buttons = [
                [InlineKeyboardButton("Search Mode", callback_data="menu_u_mode")],
                [InlineKeyboardButton("Audio Pref", callback_data="menu_u_lang"), InlineKeyboardButton("Size Pref", callback_data="menu_u_size")],
                [InlineKeyboardButton("Close Panel", callback_data="menu_close")]
            ]
        else:
            g_sett = await db.get_group_settings(chat_id)
            mode, lang, size = g_sett.get("search_mode", "let_members_choose"), g_sett.get("language_lock", "none"), g_sett.get("size_lock", "none")
            text = f"⚙️ **Group Setup Dashboard**\n\n**Search Mode:** `{mode}`\n**Language Lock:** `{lang}`\n**Size Lock:** `{size}`"
            buttons = [
                [InlineKeyboardButton("Change Mode", callback_data="menu_g_mode")],
                [InlineKeyboardButton("Lock Audio", callback_data="menu_g_lang"), InlineKeyboardButton("Lock Size", callback_data="menu_g_size")],
                [InlineKeyboardButton("Close Dashboard", callback_data="menu_close")]
            ]
        return await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    value = "_".join(parts[3:])
    if scope == "u":
        await db.update_user_setting(user_id, ("search_mode" if setting_type == "mode" else setting_type), value)
    else:
        key = {"mode": "search_mode", "lang": "language_lock", "size": "size_lock"}.get(setting_type)
        await db.update_group_setting(chat_id, key, value)
    await callback.answer(f"✅ Updated!", show_alert=True)
    callback.data = f"set_{scope}_back"
    await apply_settings_handler(client, callback)
