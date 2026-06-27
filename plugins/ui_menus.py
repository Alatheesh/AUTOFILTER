import random
import asyncio
import datetime
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from plugins.moderation import log_to_channel

# --- STICKER & MEDIA PACKS ---
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
    "CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE"
]
START_BANNER_IMAGES = [
    "https://telegra.ph/file/c4ddf6a9d136cb1735bb1.jpg",
    "https://telegra.ph/file/b36685221ce5ac41ad667.jpg",
    "https://telegra.ph/file/7f59377ace528148d15bd.jpg",
    "https://telegra.ph/file/e006737306ad1c5c16192.jpg",
    "https://telegra.ph/file/f8b495d98fd4d89c99150.jpg",
    "https://telegra.ph/file/320cdc500bc7e3d1c9e94.jpg",
    "https://telegra.ph/file/90ea7771a7c61e2d45d72.jpg"
]

def get_start_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Help", callback_data="ui_help"), InlineKeyboardButton("ℹ️ About", callback_data="ui_about")],
        [InlineKeyboardButton("👨‍💻 Source", callback_data="ui_source"), InlineKeyboardButton("✨ Features", callback_data="ui_features")]
    ])

# ==========================================
# 📢 USER COMMAND HANDLERS
# ==========================================
@Client.on_message(filters.command("start"))
async def start_menu_handler(client: Client, message: Message):
    if len(message.command) > 1: 
        cmd = message.command[1]
        if cmd.startswith("appeal_"):
            p_type = cmd.split("_")[1]
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Formal Appeal", callback_data=f"appeal_global_{p_type}")]])
            await message.reply_text(f"⚖️ **Global {p_type.upper()} Appeal Center**\n\nClick the button below to officially submit your appeal to the Creator.", reply_markup=btn)
            raise StopPropagation
        return 

    user_id = message.from_user.id
    user_exists = await db.users.find_one({"user_id": user_id})
    if not user_exists:
        await log_to_channel(client, f"#new_user\n👤 Name: `{message.from_user.first_name}`\n🆔 ID: `{user_id}`\n🔗 Username: @{message.from_user.username or 'None'}")
        await db.update_user_setting(user_id, "joined_date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    try:
        loading_msg = await message.reply_sticker(random.choice(START_STICKERS))
        await asyncio.sleep(1)
        await loading_msg.delete()
    except Exception: pass
        
    hr = datetime.datetime.now().hour
    greeting = "🌅 Good Morning" if 5 <= hr < 12 else "☀️ Good Afternoon" if 12 <= hr < 17 else "🌆 Good Evening" if 17 <= hr < 21 else "🌃 Good Night"
    welcome_text = f"**{greeting}, {message.from_user.first_name}!**\n\nWelcome to the **Cloud Auto-Filter Bot**.\n\n✨ **Use the buttons below to explore my commands:**"
    
    try: await message.reply_photo(photo=random.choice(START_BANNER_IMAGES), caption=welcome_text, reply_markup=get_start_markup())
    except Exception: await message.reply_text(text=welcome_text, reply_markup=get_start_markup())
    raise StopPropagation

@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(ROBO_STICKERS))
        await asyncio.sleep(2); await loading_msg.delete()
    except Exception: pass
    help_text = "🛠 **How to Use the Auto-Filter Bot:**\n\n• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n• `/connect`: Link your group and become the Primary Connector.\n• `/plot <movie>`: Generates a beautiful AI-powered movie plot summary.\n• `/history`: Displays your 10 most recent searches.\n• `/settings`: Open the advanced configuration dashboard."
    await message.reply_text(text=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))
    raise StopPropagation

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(ROBO_STICKERS))
        await asyncio.sleep(2); await loading_msg.delete()
    except Exception: pass
    about_text = "ℹ️ **About This Bot:**\n\n• **Engine:** Advanced Asynchronous Pyrogram V2\n• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
    await message.reply_text(text=about_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))
    raise StopPropagation

@Client.on_message(filters.command("source") & filters.private)
async def source_command_handler(client: Client, message: Message):
    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(2); await loading_msg.delete()
    except Exception: pass
    source_text = "👨‍💻 **Open Source Repository Details:**\n\nThis application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n• **Developer:** Google AI Studio Build Architect\n• **Credits:** Pyrogram & MongoDB Motor Driver"
    await message.reply_text(text=source_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back")]]))
    raise StopPropagation

# ==========================================
# 🔘 UI BUTTON LISTENER
# ==========================================
@Client.on_callback_query(filters.regex(r"^ui_(help|about|source|features|back)$"))
async def callback_ui_router(client: Client, callback: CallbackQuery):
    target = callback.data.split("_")[1]
    if target == "back":
        welcome_text = f"👋 **Welcome to the Cloud Auto-Filter Bot, {callback.from_user.username or 'User'}!**\n\nI am a highly-optimized, multi-sharded Telegram repository search system. Send me any movie or file query and I'll find it instantly across our high-performing MongoDB clusters.\n\n✨ **Use the interactive buttons below to explore my built-in commands/specifications:**"
        await callback.message.edit_text(text=welcome_text, reply_markup=get_start_markup())
    elif target == "help":
        help_text = "🛠 **How to Use the Auto-Filter Bot:**\n\n• **In Groups:** Just drop the title of any movie or document and I will automatically look it up.\n• **In DMs:** Send any text keyword (directly to my PM) to trigger the multi-DB file search instantly.\n• `/connect`: Link your group and become the Primary Connector.\n• `/settings`: Open the advanced configuration dashboard."
        await callback.message.edit_text(text=help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))
    elif target == "about":
        about_text = "ℹ️ **About This Bot:**\n\n• **Engine:** Advanced Asynchronous Pyrogram V2\n• **Core Framework:** Python 3.10 with `asyncio` parallel multi-shard pooling\n• **Database Backend:** Scalable multi-cluster MongoDB connection routing\n"
        await callback.message.edit_text(text=about_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))
    elif target == "source":
        source_text = "👨‍💻 **Open Source Repository Details:**\n\nThis application is modularly crafted to separate route dispatchers, active sharding layers, and smart monetization tasks.\n\n• **Developer:** Google AI Studio Build Architect\n• **Credits:** Pyrogram & MongoDB Motor Driver"
        await callback.message.edit_text(text=source_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))
    elif target == "features":
        features_text = "✨ **Bot Feature Profile:**\n\n• **Dynamic UI:** 3-Tier Default vs Interactive Search Engine.\n• **Monetization Engine:** GPLinks shortener + double force subscription lock.\n• **Admin Dashboard:** Mass system-wide broadcasting."
        await callback.message.edit_text(text=features_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="ui_back")]]))
    await callback.answer()
