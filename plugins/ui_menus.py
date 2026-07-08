import random
import asyncio
import datetime
from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ButtonStyle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LinkPreviewOptions
from database.multi_db import db
from plugins.moderation import log_to_channel
from config import Config

# ==========================================
# 📝 DYNAMIC TEXT TEMPLATES
# ==========================================
START_TEXT = """👋 **Welcome to {bot_name}!**

I am a highly-optimized Telegram repository search system. I help you instantly find movies, files, and data by indexing available public channels.

✨ Use the category hubs below to explore my features:"""

MEDIA_MENU_TEXT = """🎬 **Media Hub**

Everything you need to find and track your favorite movies.
• View your past search history
• Request movies that aren't in the database"""

PROFILE_MENU_TEXT = """💎 **My Profile**

Manage your personal account, check your search stats, or upgrade to a VIP plan for premium features."""

INFO_MENU_TEXT = """ℹ️ **Information Hub**

Select a topic below to read more about my policies, how to use my commands, and my source code."""

ADMIN_MENU_TEXT = """👨‍💻 **Admin Command Center**

Welcome back, Boss! Here are your quick-reference system commands:

📢 `/broadcast` - Mass deploy messages
👻 `/broadcast_edit` - Silently update an active broadcast
🗑 `/broadcast_del` - Erase a broadcast from the Vault
🎯 `/user_broadcast` - Secure 1-on-1 direct message
🧹 `/delbroadcastuser` - Scrub an ad from a single user
📊 `/info` - Check user database stats

*(Use the settings menu for database/optimization controls)*"""

ABOUT_TEXT = """🤖 **Bot Name:** {bot_name}
🧑‍💻 **Creator:** [LATHEESH](https://t.me/LATHEESH)
⚙️ **Engine:** Kurigram (Python)
📊 **Status:** Active & Running"""

HELP_TEXT = """🛠 **How to Use This Bot:**

**1.** Add me to your group using the button on the main menu.
**2.** Make me an admin so I can read messages.
**3.** Simply type the name of the movie or file you want.
**4.** I will automatically reply with the matching files!"""

SOURCE_TEXT = "🔒 **Source Code Status:**\n\nThis bot's source code is strictly **private** and will not be published publicly. If you have business inquiries, contact the admin."
DISCLAIMER_TEXT = "⚠️ **Disclaimer:**\n\nThis bot only indexes data that is publicly uploaded on Telegram by other users. The creator holds no responsibility for user-generated content."
DMCA_TEXT = "⚖️ **DMCA & Takedown Requests:**\n\nIf you are a copyright owner and wish to place a request to remove a specific file or link from our database, please contact our admin directly.\n\n**Contact:** [@ntmadminbot](https://t.me/ntmadminbot)"
PRIVACY_TEXT = "🔒 **Privacy Policy:**\n\nWe respect your privacy. This bot only collects basic usage statistics to optimize search performance. We do not store sensitive personal information."

# ==========================================
# 🎨 STICKER & MEDIA PACKS
# ==========================================
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

# ==========================================
# 🎛️ CATEGORY KEYBOARDS (HUB & SPOKE)
# ==========================================
def get_start_markup(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP", url=f"http://t.me/{bot_username}?startgroup=true", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🎬 Media Hub", callback_data="ui_media_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("💎 My Profile", callback_data="ui_profile_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚙️ Settings", callback_data="ui_settings_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("ℹ️ Help & Info", callback_data="ui_info_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🌐 VISIT OUR WEBSITE", url="https://alatheesh.github.io/NTMONLINE", style=ButtonStyle.PRIMARY)]
    ]
    # 🔥 Admin Secret Button!
    if user_id in Config.ADMINS:
        buttons.append([InlineKeyboardButton("👨‍💻 Admin Command Center", callback_data="ui_admin_menu", style=ButtonStyle.DANGER)])
    return InlineKeyboardMarkup(buttons)

def info_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Help Guide", callback_data="ui_help", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🤖 About Bot", callback_data="ui_about", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("📝 Source Code", callback_data="ui_source", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⚠️ Disclaimer", callback_data="ui_disclaimer", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚖️ DMCA", callback_data="ui_dmca", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🔒 Privacy", callback_data="ui_privacy", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back", style=ButtonStyle.DANGER)]
    ])

def profile_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 My Stats", callback_data="ui_stats", style=ButtonStyle.PRIMARY), InlineKeyboardButton("👑 VIP Status", callback_data="vip_panel_router", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back", style=ButtonStyle.DANGER)]
    ])

def media_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕰 Search History", callback_data="ui_history", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🔔 Request Movie", callback_data="ui_request", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back", style=ButtonStyle.DANGER)]
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
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("Submit Formal Appeal", callback_data=f"appeal_global_{p_type}", style=ButtonStyle.PRIMARY)]])
            await message.reply_text(f"⚖️ **Global {p_type.upper()} Appeal Center**\n\nClick the button below to officially submit your appeal to the Creator.", reply_markup=btn)
            raise StopPropagation
        return 

    user_id = message.from_user.id
    user_exists = await db.users.find_one({"user_id": user_id})
    if not user_exists:
        await log_to_channel(client, f"#new_user\n👤 Name: `{message.from_user.first_name}`\n🆔 ID: `{user_id}`\n🔗 Username: @{message.from_user.username or 'None'}")
        await db.update_user_setting(user_id, "joined_date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        
        settings = await db.get_settings()
        trial_days = settings.get("free_trial_days", 0)
        if trial_days > 0:
            from plugins.vip_system import add_vip
            await add_vip(user=message.from_user, plan_name="🎁 Gold (Trial)", days=trial_days, method="Auto Free Trial", is_promo=True)

    try:
        loading_msg = await message.reply_sticker(random.choice(START_STICKERS))
        await asyncio.sleep(1)
        await loading_msg.delete()
    except Exception: pass
        
    bot_me = await client.get_me()
    formatted_start = START_TEXT.format(bot_name=bot_me.first_name)
    markup = get_start_markup(bot_me.username, user_id)
    
    try: await message.reply_photo(photo=random.choice(START_BANNER_IMAGES), caption=formatted_start, reply_markup=markup)
    except Exception: await message.reply_text(text=formatted_start, reply_markup=markup)
    raise StopPropagation


@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):
    await message.reply_text(text=HELP_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    raise StopPropagation

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
    bot_me = await client.get_me()
    await message.reply_text(text=ABOUT_TEXT.format(bot_name=bot_me.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    raise StopPropagation

# ==========================================
# 🔍 UTILITY COMMANDS (/id & /info)
# ==========================================
@Client.on_message(filters.command("id"))
async def id_command_handler(client: Client, message: Message):
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            return await message.reply_text(f"📢 **Forwarded Chat ID:** `{reply.forward_from_chat.id}`\n**Name:** `{reply.forward_from_chat.title}`")
        elif reply.forward_from:
            return await message.reply_text(f"👤 **Forwarded User ID:** `{reply.forward_from.id}`\n**Name:** `{reply.forward_from.first_name}`")
        else:
            return await message.reply_text(f"👤 **Replied User ID:** `{reply.from_user.id}`")
    else:
        return await message.reply_text(f"👤 **Your ID:** `{message.from_user.id}`\n💬 **Current Chat ID:** `{message.chat.id}`")
        
@Client.on_message(filters.command("info"))
async def info_command_handler(client: Client, message: Message):
    target_user_id = message.from_user.id
    if len(message.command) > 1:
        try: target_user_id = int(message.command[1])
        except ValueError: target_user_id = message.command[1]
    elif message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        
    try: user = await client.get_users(target_user_id)
    except Exception: return await message.reply_text("❌ **Error:** Could not fetch data for that user.")
        
    name = user.first_name + (f" {user.last_name}" if user.last_name else "")
    info_text = f"👤 **USER INFORMATION**\n\n**Name:** {name}\n**ID:** `{user.id}`\n**Profile:** [Direct Link](tg://user?id={user.id})\n"
    
    if message.from_user.id in Config.ADMINS:
        u_sett = await db.get_user_settings(user.id)
        joined = u_sett.get("joined_date", "Unknown")
        searches = u_sett.get("total_searches", 0)
        punish_doc = await db.punishments.find_one({"_id": f"{user.id}_global"})
        warns = punish_doc.get("warns", 0) if punish_doc else 0
        p_type = punish_doc.get("type", "Clean").title() if punish_doc else "Clean"
        info_text += f"\n📊 **ADMIN DATABASE STATS:**\n**Joined Date:** `{joined}`\n**Total Searches:** `{searches}`\n**Global Status:** `{p_type}`\n**Warnings:** `{warns}`"
        
    if user.photo:
        async for photo in client.get_chat_photos(user.id, limit=1):
            await message.reply_photo(photo.file_id, caption=info_text)
            break
    else:
        await message.reply_text(info_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    raise StopPropagation


# ==========================================
# 🔘 UI BUTTON LISTENER (THE ROUTER)
# ==========================================
@Client.on_callback_query(filters.regex(r"^ui_"))
async def callback_ui_router(client: Client, callback: CallbackQuery):
    target = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    bot_me = await client.get_me()
    
    # 🏠 MAIN MENU
    if target == "back":
        await callback.message.edit_text(text=START_TEXT.format(bot_name=bot_me.first_name), reply_markup=get_start_markup(bot_me.username, user_id), link_preview_options=LinkPreviewOptions(is_disabled=True))
        
    # 📂 CATEGORY HUBS
    elif target == "info_menu":
        await callback.message.edit_text(text=INFO_MENU_TEXT, reply_markup=info_category_keyboard())
    elif target == "profile_menu":
        await callback.message.edit_text(text=PROFILE_MENU_TEXT, reply_markup=profile_category_keyboard())
    elif target == "media_menu":
        await callback.message.edit_text(text=MEDIA_MENU_TEXT, reply_markup=media_category_keyboard())
    elif target == "admin_menu" and user_id in Config.ADMINS:
        await callback.message.edit_text(text=ADMIN_MENU_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back", style=ButtonStyle.DANGER)]]))

    # 📄 SUB-MENU PAGES (Information)
    elif target == "help":
        await callback.message.edit_text(text=HELP_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "about":
        await callback.message.edit_text(text=ABOUT_TEXT.format(bot_name=bot_me.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "source":
        await callback.message.edit_text(text=SOURCE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 Contact Admin", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "disclaimer":
        await callback.message.edit_text(text=DISCLAIMER_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "dmca":
        await callback.message.edit_text(text=DMCA_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 Contact @ntmadminbot", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "privacy":
        await callback.message.edit_text(text=PRIVACY_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Info Hub", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
        
    # 📄 SUB-MENU PAGES (Profile & Media)
    elif target == "stats":
        u_sett = await db.get_user_settings(user_id)
        joined = u_sett.get("joined_date", "Unknown")
        total_searches = u_sett.get("total_searches", 0)
        mode = u_sett.get("search_mode", "default").title()
        
        stats_text = (
            f"📊 **Your Personal Statistics:**\n\n"
            f"👤 **Name:** {callback.from_user.first_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"📅 **Joined On:** `{joined}`\n"
            f"🔍 **Total Searches:** `{total_searches}`\n"
            f"⚙️ **Search Mode:** `{mode}`\n\n"
            f"*(Thank you for using {bot_me.first_name}!)*"
        )
        await callback.message.edit_text(text=stats_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="ui_profile_menu", style=ButtonStyle.DANGER)]]))
        
    elif target == "settings_menu":
        keyboard = [[InlineKeyboardButton(text="👤 Personal Search Settings", callback_data="tier_user_home", style=ButtonStyle.PRIMARY)]]
        if await db.get_connected_groups(user_id):
            keyboard.append([InlineKeyboardButton(text="🛡️ Manage My Linked Groups", callback_data="tier_group_list", style=ButtonStyle.PRIMARY)])
        if user_id in Config.ADMINS:
            keyboard.append([InlineKeyboardButton("📊 System Stats Dashboard", callback_data="stats_home", style=ButtonStyle.PRIMARY)])
            keyboard.append([InlineKeyboardButton(text="👑 Bot Creator Control Panel", callback_data="set_home", style=ButtonStyle.PRIMARY)])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="ui_back", style=ButtonStyle.DANGER)])
        
        settings_text = "🎛️ **Central Command Settings Hub:**\nSelect the access layer tier you wish to inspect or modify:"
        await callback.message.edit_text(text=settings_text, reply_markup=InlineKeyboardMarkup(keyboard))
        
    # 🔌 SEAMLESS BRIDGES TO YOUR EXISTING CODE
    elif target == "history":
        await callback.message.delete()
        callback.message.from_user = callback.from_user
        callback.message.text = "/history"
        from plugins.advanced import view_search_history
        await view_search_history(client, callback.message)

    elif target == "request":
        await callback.message.delete()
        callback.message.from_user = callback.from_user
        callback.message.text = "/request"
        from plugins.request import request_command
        await request_command(client, callback.message)
        
    await callback.answer()
