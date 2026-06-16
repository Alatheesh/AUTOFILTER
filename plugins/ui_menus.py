import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserNotParticipant
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
    # Ignore payload starts (getfile_, ref_) because monetization.py handles them
    if len(message.command) > 1:
        return
        
    username = message.from_user.username or message.from_user.first_name or "User"
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
        "• `/settings`: Open the configuration dashboard."
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
        "• **License:** Open Source MIT\n"
        "• **Credits:** Pyrogram & MongoDB Motor Driver"
    )
    await message.reply_text(text=source_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))

@Client.on_callback_query(filters.regex(r"^ui_(help|about|source|features|back)$"))
async def callback_ui_router(client: Client, callback: CallbackQuery):
    target = callback.data.split("_")[1]
    
    if target == "back":
        username = callback.from_user.username or callback.from_user.first_name or "User"
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
            "• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n"
            "• `/history`: Displays your 10 most recent searches.\n"
            "• `/settings`: Open the configuration dashboard."
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
            "• **Asynchronous Scaling:** Motor-driven multi-DB load array.\n"
            "• **Search Enhancers:** Levenshtein-distance spelling suggestions.\n"
            "• **Dynamic UI:** 3-Tier Default vs Interactive Search Engine.\n"
            "• **Monetization Engine:** GPLinks shortener + force sub lock.\n"
            "• **Admin Dashboard:** Mass system-wide broadcasting."
        )
        await callback.message.edit_text(text=features_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))

    await callback.answer()


# ==========================================
# --- 3-TIER SETTINGS DASHBOARD ---
# ==========================================

def is_creator(user_id: int) -> bool:
    return user_id == Config.ADMINS[0] if isinstance(Config.ADMINS, list) else user_id == Config.ADMINS

@Client.on_message(filters.command("settings"))
async def settings_router(client: Client, message: Message):
    user_id = message.from_user.id
    
    # CASE A: SETTINGS CALLED INSIDE A GROUP CHAT
    if message.chat.type in ["group", "supergroup"]:
        # 1. Check Bot's own Admin rights
        bot_member = await client.get_chat_member(message.chat.id, "me")
        if not bot_member.privileges or not bot_member.privileges.can_delete_messages:
            return await message.reply_text(
                "❌ **Permission Error:** I need administrative rights with `Delete Messages` privileges to configure layouts securely."
            )
            
        # 2. Check triggering user's Group Admin status
        try:
            user_member = await client.get_chat_member(message.chat.id, user_id)
            if user_member.status not in ["administrator", "creator"]:
                return await message.reply_text("🛑 This configuration dashboard is restricted to group administrators.")
        except Exception:
            return await message.reply_text("❌ Failed to verify your group administrative permissions.")

        # Sync current group admins list to DB for remote management later
        group_admins = []
        async for admin in client.get_chat_members(message.chat.id, filter="administrators"):
            if not admin.user.is_bot:
                group_admins.append(admin.user.id)
        await db.update_group_setting(message.chat.id, "admins", group_admins)
        await db.update_group_setting(message.chat.id, "title", message.chat.title)

        # Build Group Config layout
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
        return await message.reply_text(
            f"🛠️ **Group Settings Menu:** `{message.chat.title}`\nConfigure search visualization structures for all active participants:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # CASE B: SETTINGS CALLED IN PRIVATE DM (DYNAMICS ACCORDING TO HIERARCHY ID)
    u_sett = await db.get_user_settings(user_id)
    u_mode = u_sett.get("search_mode", "default")
    
    keyboard = [
        [InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]
    ]
    
    # If Group Admin, append structural portal
    managed_groups = await db.get_admin_groups(user_id)
    if managed_groups:
        keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
        
    # If Creator, append master platform keys
    if is_creator(user_id):
        keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="tier_creator_home")])
        
    await message.reply_text(
        "🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@Client.on_callback_query(filters.regex(r"^(tier_|gset_|uset_)"))
async def menus_callback_handler(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    # --- TIER 1 HANDLERS (USER PERSONAL PM) ---
    if data == "tier_user_home":
        u_sett = await db.get_user_settings(user_id)
        m = u_sett.get("search_mode", "default")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if m=='default' else '❌'} Default Mode", callback_data="uset_mode_default"),
                InlineKeyboardButton(text=f"{'✅' if m=='interactive' else '❌'} Interactive Mode", callback_data="uset_mode_interactive")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")]
        ]
        return await query.message.edit_text("👤 **Personal Display Preferences:**\nChoose how output records populate on your workspace screen:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("uset_mode_"):
        new_mode = data.replace("uset_mode_", "")
        await db.update_user_setting(user_id, "search_mode", new_mode)
        await query.answer(f"UI Layout updated to: {new_mode.upper()}")
        return await menus_callback_handler(client, query.create(data="tier_user_home"))

    # --- TIER 2 HANDLERS (GROUP CONTROLS OVERRIDES) ---
    if data == "tier_group_list":
        managed = await db.get_admin_groups(user_id)
        if not managed: return await query.answer("No linked administration nodes found.", show_alert=True)
        buttons = []
        for g in managed:
            title = g.get("title", f"Chat ID: {g['chat_id']}")
            buttons.append([InlineKeyboardButton(text=f"⚙️ {title}", callback_data=f"tier_gmanage_{g['chat_id']}")])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")])
        return await query.message.edit_text("🛡️ **Administered Groups Portal:**\nSelect a community cluster node below to tweak layout policies remotely:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("tier_gmanage_"):
        c_id = int(data.split("_")[2])
        g_sett = await db.get_group_settings(c_id)
        if user_id not in g_sett.get("admins", []):
            return await query.answer("Access Denied. You are not a synchronized manager for this node.", show_alert=True)
        mode = g_sett.get("search_mode", "let_members_choose")
        buttons = [
            [
                InlineKeyboardButton(text=f"{'✅' if mode=='force_default' else '❌'} Force Default", callback_data=f"gset_mode_force_default_{c_id}"),
                InlineKeyboardButton(text=f"{'✅' if mode=='force_interactive' else '❌'} Force Interactive", callback_data=f"gset_mode_force_interactive_{c_id}")
            ],
            [InlineKeyboardButton(text=f"{'✅' if mode=='let_members_choose' else '❌'} Let Members Choose", callback_data=f"gset_mode_let_members_choose_{c_id}")],
            [InlineKeyboardButton(text="🔙 Back to List", callback_data="tier_group_list")]
        ]
        return await query.message.edit_text(f"🛠️ **Remote Group Matrix Interface**\nModifying rule sets for channel group `{g_sett.get('title', c_id)}`:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("gset_mode_"):
        parts = data.split("_")
        target_mode = f"{parts[2]}_{parts[3]}" if parts[3] == "default" or parts[3] == "interactive" else f"{parts[2]}_{parts[3]}_{parts[4]}"
        chat_id = int(parts[-1])
        g_sett = await db.get_group_settings(chat_id)
        
        # Verify access rules locally or via server query match
        if user_id not in g_sett.get("admins", []) and not is_creator(user_id):
            return await query.answer("Unauthorized action layer clearance.", show_alert=True)
            
        await db.update_group_setting(chat_id, "search_mode", target_mode)
        await query.answer("Group layout policy updated successfully.")
        
        # Determine fallback window route base path
        if query.message.chat.type in ["group", "supergroup"]:
            # Rerender group view inline directly
            buttons = [
                [
                    InlineKeyboardButton(text=f"{'✅' if target_mode=='force_default' else '❌'} Force Default", callback_data=f"gset_mode_force_default_{chat_id}"),
                    InlineKeyboardButton(text=f"{'✅' if target_mode=='force_interactive' else '❌'} Force Interactive", callback_data=f"gset_mode_force_interactive_{chat_id}")
                ],
                [InlineKeyboardButton(text=f"{'✅' if target_mode=='let_members_choose' else '❌'} Let Members Choose", callback_data=f"gset_mode_let_members_choose_{chat_id}")]
            ]
            return await query.message.edit_text(f"🛠️ **Group Settings Menu:**\nConfigure search visualization structures for all active participants:", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            return await menus_callback_handler(client, query.create(data=f"tier_gmanage_{chat_id}"))

    # --- TIER 3 HANDLERS (BOT CREATOR CONTROL PANEL) ---
    if data == "tier_creator_home":
        if not is_creator(user_id): return await query.answer("Clearance validation failure.", show_alert=True)
        g_settings = await db.get_settings()
        sh_status = "ACTIVE" if g_settings.get("shortener_enabled", False) else "DISABLED"
        buttons = [
            [InlineKeyboardButton(text=f"🌐 Global Shortener: {sh_status}", callback_data="tier_toggle_shortener")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="tier_root_fallback")]
        ]
        return await query.message.edit_text("👑 **Master Creator Engine Dashboard**\nGlobal engine controls override matrix settings directly:", reply_markup=InlineKeyboardMarkup(buttons))

    if data == "tier_toggle_shortener":
        if not is_creator(user_id): return await query.answer("Access Violation.")
        g_settings = await db.get_settings()
        curr = g_settings.get("shortener_enabled", False)
        await db.settings.update_one({"id": "global"}, {"$set": {"shortener_enabled": not curr}}, upsert=True)
        await query.answer("Global system shortener state flipped.")
        return await menus_callback_handler(client, query.create(data="tier_creator_home"))

    if data == "tier_root_fallback":
        # Remount layout index home page
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home")]]
        if await db.get_admin_groups(user_id):
            keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list")])
        if is_creator(user_id):
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="tier_creator_home")])
        return await query.message.edit_text("🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:", reply_markup=InlineKeyboardMarkup(keyboard))
