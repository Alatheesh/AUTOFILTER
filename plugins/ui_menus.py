import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config
from database.multi_db import db

logger = logging.getLogger(__name__)

# ==========================================
# --- ORIGINAL WELCOME & HELP MENUS ---
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

@Client.on_message(filters.command("start") & filters.private, group=2)
async def start_menu_handler(client: Client, message: Message):
    if len(message.command) > 1:
        return
        
    username = message.from_user.username if message.from_user else "User"
    welcome_text = (
        f"👋 **Welcome to the Cloud Auto-Filter Bot, {username}!**\n\n"
        f"✨ **Use the interactive buttons below to explore my built-in commands:**"
    )
    await message.reply_text(text=welcome_text, reply_markup=get_start_markup())

@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):
    help_text = (
        "🛠 **How to Use the Auto-Filter Bot:**\n\n"
        "• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n"
        "• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n"
        "• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n"
        "• `/history`: Displays your 10 most recent searches.\n"
        "• `/clear_history`: Wipes your query history records clean.\n"
        "• `/settings`: Open the advanced configuration dashboard."
    )
    await message.reply_text(text=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
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

# ==========================================
# --- 3-TIER SETTINGS DASHBOARD ---
# ==========================================

def is_creator(user_id: int) -> bool:
    return user_id in Config.ADMINS

@Client.on_message(filters.command("settings"))
async def settings_router(client: Client, message: Message):
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        me = await client.get_me()
        bot_member = await client.get_chat_member(message.chat.id, me.id)
        
        if not bot_member.privileges or not bot_member.privileges.can_delete_messages:
            return await message.reply_text("❌ **Permission Error:** I need administrative rights with `Delete Messages` privileges to configure layouts securely.")
            
        try:
            user_member = await client.get_chat_member(message.chat.id, user_id)
            if user_member.status not in ["administrator", "creator"]:
                return await message.reply_text("🛑 This configuration dashboard is restricted to group administrators.")
        except Exception:
            return await message.reply_text("❌ Failed to verify your group administrative permissions.")

        group_admins = []
        async for admin in client.get_chat_members(message.chat.id, filter="administrators"):
            if not admin.user.is_bot:
                group_admins.append(admin.user.id)
                
        await db.update_group_setting(message.chat.id, "admins", group_admins)
        await db.update_group_setting(message.chat.id, "title", message.chat.title)

        g_sett = await db.get_group_settings(message.chat.id)
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

    # CASE B: SETTINGS CALLED IN PRIVATE DM
    keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]]
    
    managed_groups = await db.get_admin_groups(user_id)
    if managed_groups:
        keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
        
    if is_creator(user_id):
        keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home")])
        
    await message.reply_text("🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:", reply_markup=InlineKeyboardMarkup(keyboard))

@Client.on_callback_query(filters.regex(r"^(tier_|gset_|uset_)"))
async def menus_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    # ----------------------------------------------------
    # TIER 1: USER PERSONAL PM SETTINGS
    # ----------------------------------------------------
    if data == "tier_user_home":
        u_sett = await db.get_user_settings(user_id)
        m = u_sett.get("search_mode", "default")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if m=='default' else '❌'} Default Mode", callback_data="uset_mode_default"),
                InlineKeyboardButton(text=f"{'✅' if m=='interactive' else '❌'} Interactive Mode", callback_data="uset_mode_interactive")
            ]
        ]
        
        if m == "interactive":
            buttons.append([InlineKeyboardButton(text="⚙️ Configure File Size & Language", callback_data="uset_interactive_menu")])
            
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

    # THE NEW PERSONAL SIZE/LANGUAGE FILTER MENU
    if data == "uset_interactive_menu":
        u_sett = await db.get_user_settings(user_id)
        s = u_sett.get("size", "all")
        l = u_sett.get("language", "all")
        
        buttons = [
            [
                InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data="uset_s_small"),
                InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data="uset_s_medium")
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data="uset_s_large"),
                InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data="uset_s_xlarge")
            ],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data="uset_s_all")],
            [
                InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data="uset_l_tamil"),
                InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data="uset_l_telugu"),
                InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data="uset_l_hindi")
            ],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data="uset_l_all")],
            [InlineKeyboardButton("🔙 Save & Return", callback_data="tier_user_home")]
        ]
        return await query.message.edit_text(
            "✨ **Interactive Mode Filter Settings**\n"
            "Select your preferred language and file size threshold. These will be automatically applied whenever you search!", 
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    if data.startswith("uset_s_"):
        new_s = data.replace("uset_s_", "")
        await db.update_user_setting(user_id, "size", new_s)
        query.data = "uset_interactive_menu"
        return await menus_callback_handler(client, query)

    if data.startswith("uset_l_"):
        new_l = data.replace("uset_l_", "")
        await db.update_user_setting(user_id, "language", new_l)
        query.data = "uset_interactive_menu"
        return await menus_callback_handler(client, query)


    # ----------------------------------------------------
    # TIER 2: GROUP ADMIN SETTINGS
    # ----------------------------------------------------
    if data == "tier_group_list":
        managed = await db.get_admin_groups(user_id)
        if not managed:
            return await query.answer("No linked administration nodes found.", show_alert=True)
            
        buttons = []
        for g in managed:
            title = g.get("title", f"Chat ID: {g['chat_id']}")
            buttons.append([InlineKeyboardButton(text=f"⚙️ {title}", callback_data=f"tier_gmanage_{g['chat_id']}")])
            
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")])
        return await query.message.edit_text("🛡️ **Administered Groups Portal:**\nSelect a community cluster node below to tweak layout policies remotely:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("tier_gmanage_"):
        c_id = int(data.split("_")[2])
        g_sett = await db.get_group_settings(c_id)
        
        if user_id not in g_sett.get("admins", []) and not is_creator(user_id):
            return await query.answer("Access Denied.", show_alert=True)
            
        mode = g_sett.get("search_mode", "let_members_choose")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if mode=='force_default' else '❌'} Force Default", callback_data=f"gset_mode_force_default_{c_id}"),
                InlineKeyboardButton(text=f"{'✅' if mode=='force_interactive' else '❌'} Force Interactive", callback_data=f"gset_mode_force_interactive_{c_id}")
            ],
            [InlineKeyboardButton(text=f"{'✅' if mode=='let_members_choose' else '❌'} Let Members Choose", callback_data=f"gset_mode_let_members_choose_{c_id}")]
        ]
        
        if mode == "force_interactive":
            buttons.append([InlineKeyboardButton(text="⚙️ Configure Group Size & Language", callback_data=f"gset_interactive_menu_{c_id}")])
            
        buttons.append([InlineKeyboardButton(text="🔙 Back to List", callback_data="tier_group_list")])
        
        return await query.message.edit_text(f"🛠️ **Remote Group Matrix Interface**\nModifying rule sets for channel group `{g_sett.get('title', c_id)}`:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("gset_mode_"):
        parts = data.split("_")
        target_mode = f"{parts[2]}_{parts[3]}" if parts[3] in ["default", "interactive"] else f"{parts[2]}_{parts[3]}_{parts[4]}"
        chat_id = int(parts[-1])
        g_sett = await db.get_group_settings(chat_id)
        
        if user_id not in g_sett.get("admins", []) and not is_creator(user_id):
            return await query.answer("Unauthorized.", show_alert=True)
            
        await db.update_group_setting(chat_id, "search_mode", target_mode)
        await query.answer("Group layout policy updated successfully.")
        
        if target_mode == "force_interactive":
            query.data = f"gset_interactive_menu_{chat_id}"
        else:
            query.data = f"tier_gmanage_{chat_id}"
            
        return await menus_callback_handler(client, query)

    # THE NEW GROUP SIZE/LANGUAGE FILTER MENU
    if data.startswith("gset_interactive_menu_"):
        c_id = int(data.split("_")[3])
        g_sett = await db.get_group_settings(c_id)
        s = g_sett.get("size_lock", "all")
        l = g_sett.get("language_lock", "all")
        
        buttons = [
            [
                InlineKeyboardButton(f"{'✅ ' if s=='small' else ''}< 500 MB", callback_data=f"gset_s_small_{c_id}"),
                InlineKeyboardButton(f"{'✅ ' if s=='medium' else ''}500 MB - 1 GB", callback_data=f"gset_s_medium_{c_id}")
            ],
            [
                InlineKeyboardButton(f"{'✅ ' if s=='large' else ''}1 GB - 2 GB", callback_data=f"gset_s_large_{c_id}"),
                InlineKeyboardButton(f"{'✅ ' if s=='xlarge' else ''}> 2 GB", callback_data=f"gset_s_xlarge_{c_id}")
            ],
            [InlineKeyboardButton(f"{'✅ ' if s=='all' else ''}Any File Size", callback_data=f"gset_s_all_{c_id}")],
            [
                InlineKeyboardButton(f"{'✅ ' if l=='tamil' else ''}Tamil", callback_data=f"gset_l_tamil_{c_id}"),
                InlineKeyboardButton(f"{'✅ ' if l=='telugu' else ''}Telugu", callback_data=f"gset_l_telugu_{c_id}"),
                InlineKeyboardButton(f"{'✅ ' if l=='hindi' else ''}Hindi", callback_data=f"gset_l_hindi_{c_id}")
            ],
            [InlineKeyboardButton(f"{'✅ ' if l=='all' else ''}Any Language", callback_data=f"gset_l_all_{c_id}")],
            [InlineKeyboardButton("🔙 Save & Return", callback_data=f"tier_gmanage_{c_id}")]
        ]
        return await query.message.edit_text(
            f"✨ **Group Interactive Filters**\n"
            f"Force all members in group `{c_id}` to only see files matching these exact parameters:", 
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    if data.startswith("gset_s_"):
        parts = data.split("_")
        new_s = parts[2]
        c_id = int(parts[3])
        await db.update_group_setting(c_id, "size_lock", new_s)
        query.data = f"gset_interactive_menu_{c_id}"
        return await menus_callback_handler(client, query)

    if data.startswith("gset_l_"):
        parts = data.split("_")
        new_l = parts[2]
        c_id = int(parts[3])
        await db.update_group_setting(c_id, "language_lock", new_l)
        query.data = f"gset_interactive_menu_{c_id}"
        return await menus_callback_handler(client, query)


    # --- FALLBACK HUB REFRESH ---
    if data == "tier_root_fallback":
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]]
        
        if await db.get_admin_groups(user_id):
            keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
            
        if is_creator(user_id):
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home")])
            
        return await query.message.edit_text("🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:", reply_markup=InlineKeyboardMarkup(keyboard))
