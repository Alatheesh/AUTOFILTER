import logging
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    Message, 
    CallbackQuery
)

logger = logging.getLogger(__name__)

# ==========================================
# 🚨 GLOBAL DEBUG BREADCRUMB
# ==========================================
@Client.on_message(group=-1)
async def global_debug_logger(client: Client, message: Message):
    logger.info("========================================")
    logger.info(f"🚨 DEBUG BREADCRUMB: Bot received a message!")
    logger.info(f"🚨 Chat ID: {message.chat.id} | Type: {message.chat.type}")
    logger.info(f"🚨 Message Text: {message.text or 'No Text (Media/Event)'}")
    logger.info("========================================")
# ==========================================

# Start Menu Markup Template
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

@Client.on_message(filters.command("start") & filters.private)
async def start_menu_handler(client: Client, message: Message):
    # Only show the menu if there is NO deep-link data (like file_ or ref_)
    if len(message.command) > 1:
        return
        
    username = message.from_user.username or message.from_user.first_name or "User"
    welcome_text = (
        f"👋 **Welcome to the Cloud Auto-Filter Bot, {username}!**\n\n"
        f"✨ **Use the interactive buttons below to explore my built-in commands:**"
    )
    await message.reply_text(
        text=welcome_text,
        reply_markup=get_start_markup()
    )

@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):
    help_text = (
        "🛠 **How to Use the Auto-Filter Bot:**\n\n"
        "• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n"
        "• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n"
        "• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n"
        "• `/history`: Displays your 10 most recent searches.\n"
        "• `/clear_history`: Wipes your query history records clean.\n"
        "• `/premium`: Check VIP upgrades and status tracker."
    )
    await message.reply_text(
        text=help_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]])
    )

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
    about_text = (
        "ℹ️ **About This Bot:**\n\n"
        "• **Engine:** Advanced Asynchronous Pyrogram V2\n"
        "• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n"
        "• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
        "• **Primary Deployment:** Ready for Hugging Face Spaces free-tier hosting with aiohttp daemon\n"
        "• **Self-Protection:** Custom 24H self-destructing Ghost Mode links."
    )
    await message.reply_text(
        text=about_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]])
    )

@Client.on_message(filters.command("source") & filters.private)
async def source_command_handler(client: Client, message: Message):
    source_text = (
        "👨‍💻 **Open Source Repository Details:**\n\n"
        "This application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n"
        "• **Developer:** Google AI Studio Build Architect\n"
        "• **License:** Open Source MIT\n"
        "• **Credits:** Pyrogram & MongoDB Motor Driver"
    )
    await message.reply_text(
        text=source_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]])
    )

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
        await callback.message.edit_text(
            text=welcome_text,
            reply_markup=get_start_markup()
        )
        await callback.answer()
        return

    # Help Menu Text
    if target == "help":
        help_text = (
            "🛠 **How to Use the Auto-Filter Bot:**\n\n"
            "• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n"
            "• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n"
            "• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n"
            "• `/history`: Displays your 10 most recent searches.\n"
            "• `/clear_history`: Wipes your query history records clean.\n"
            "• `/premium`: Check VIP upgrades and status tracker."
        )
        await callback.message.edit_text(
            text=help_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]])
        )

    # About Menu Text
    elif target == "about":
        about_text = (
            "ℹ️ **About This Bot:**\n\n"
            "• **Engine:** Advanced Asynchronous Pyrogram V2\n"
            "• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n"
            "• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
            "• **Primary Deployment:** Ready for Hugging Face Spaces free-tier hosting with aiohttp daemon\n"
            "• **Self-Protection:** Custom 24H self-destructing Ghost Mode links."
        )
        await callback.message.edit_text(
            text=about_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]])
        )

    # Source Menu Text
    elif target == "source":
        source_text = (
            "👨‍💻 **Open Source Repository Details:**\n\n"
            "This application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n"
            "• **Developer:** Google AI Studio Build Architect\n"
            "• **License:** Open Source MIT\n"
            "• **Credits:** Pyrogram & MongoDB Motor Driver"
        )
        await callback.message.edit_text(
            text=source_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]])
        )

    # Features Menu Text
    elif target == "features":
        features_text = (
            "✨ **Bot Feature Profile (50+ Custom Integrations):**\n\n"
            "• **Asynchronous Scaling:** Motor-driven multi-DB load array.\n"
            "• **Search Enhancers:** Levenshtein-distance spelling suggestions.\n"
            "• **Scraping Indexer:** Seamless background channel media grabber.\n"
            "• **Monetization Engine:** GPLinks shortener + double force subscription lock.\n"
            "• **Admin Dashboard:** Mass system-wide broadcasting, dynamic shard lane rotation, and one-click database JSON backup."
        )
        await callback.message.edit_text(
            text=features_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]])
        )

    await callback.answer()
