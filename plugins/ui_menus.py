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
# 📝 DYNAMIC TEXT TEMPLATES (Native Telegram Markdown)
# ==========================================
START_TEXT = """👋 **Welcome to {bot_name}!**

I am a highly-optimized Telegram repository search system. I help you instantly find movies, files, and data by indexing available public channels.

✨ **Use the category hubs below to explore my features:**"""

MEDIA_MENU_TEXT = """🎬 **Media Hub**

Everything you need to find and track your favorite movies.
• **View** your past search history.
• **Request** movies that aren't in the database."""

PROFILE_MENU_TEXT = """💎 **My Profile**

Manage your personal account, check your search stats, or upgrade to a **VIP plan** for premium features."""

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

_(Use the settings menu for database and optimization controls)_"""

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

START_STICKERS = ["CAACAgUAAxkBAAERawdqNXyW6Tqft1iZtgABiTVGhBohxgIAApwAA8iUZBRzjwAB89rFhfw8BA", "CAACAgIAAxkBAAERawlqNXy1AwABuumeSFheCDM2d624y90AAiYPAAL7WShJIl_khPeHLac8BA"]
ROBO_STICKERS = ["CAACAgUAAxkBAAERautqNXbvA3JLjJg-U_LbOgNmBXLApQACahIAAvYiyVZikUGUoRZynzwE", "CAACAgIAAxkBAAERawFqNXvcF78c77WjPHAAAbL9Yk55HMAAAk4CAAJWnb0KMP5rbYEyA288BA", "CAACAgIAAxkBAAERawNqNXvnj-tDUwXqJGB_6BYXFfIn-QACwGoAAjg5aUn8Q0qGpRajKzwE"]
CODE_STICKERS = ["CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE"]
START_BANNER_IMAGES = ["https://telegra.ph/file/c4ddf6a9d136cb1735bb1.jpg", "https://telegra.ph/file/b36685221ce5ac41ad667.jpg", "https://telegra.ph/file/7f59377ace528148d15bd.jpg", "https://telegra.ph/file/e006737306ad1c5c16192.jpg", "https://telegra.ph/file/f8b495d98fd4d89c99150.jpg", "https://telegra.ph/file/320cdc500bc7e3d1c9e94.jpg", "https://telegra.ph/file/90ea7771a7c61e2d45d72.jpg"]

def get_start_markup(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣", url=f"http://t.me/{bot_username}?startgroup=true", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🎬 𝗠𝗲𝗱𝗶𝗮 𝗛𝘂𝗯", callback_data="ui_media_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("💎 𝗠𝘆 𝗣𝗿𝗼𝗳𝗶𝗹𝗲", callback_data="ui_profile_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚙️ 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", callback_data="ui_settings_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("ℹ️ 𝗛𝗲𝗹𝗽 & 𝗜𝗻𝗳𝗼", callback_data="ui_info_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🌐 𝗩𝗜𝗦𝗜𝗧 𝗢𝗨𝗥 𝗪𝗘𝗕𝗦𝗜𝗧𝗘", url="https://alatheesh.github.io/NTMONLINE", style=ButtonStyle.PRIMARY)]
    ]
    if user_id in Config.ADMINS: buttons.append([InlineKeyboardButton("👨‍💻 𝗔𝗱𝗺𝗶𝗻 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 𝗖𝗲𝗻𝘁𝗲𝗿", callback_data="ui_admin_menu", style=ButtonStyle.DANGER)])
    return InlineKeyboardMarkup(buttons)

def info_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 𝗛𝗲𝗹𝗽 𝗚𝘂𝗶𝗱𝗲", callback_data="ui_help", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🤖 𝗔𝗯𝗼𝘂𝘁 𝗕𝗼𝘁", callback_data="ui_about", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("📝 𝗦𝗼𝘂𝗿𝗰𝗲 𝗖𝗼𝗱𝗲", callback_data="ui_source", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⚠️ 𝗗𝗶𝘀𝗰𝗹𝗮𝗶𝗺𝗲𝗿", callback_data="ui_disclaimer", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚖️ 𝗗𝗠𝗖𝗔", callback_data="ui_dmca", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🔒 𝗣𝗿𝗶𝘃𝗮𝗰𝘆", callback_data="ui_privacy", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)]
    ])

def profile_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 𝗠𝘆 𝗦𝘁𝗮𝘁𝘀", callback_data="ui_stats", style=ButtonStyle.PRIMARY), InlineKeyboardButton("👑 𝗩𝗜𝗣 𝗦𝘁𝗮𝘁𝘂𝘀", callback_data="ui_vip", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🛒 𝗕𝘂𝘆 𝗩𝗜𝗣", callback_data="ui_buyvip", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)]
    ])

def media_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕰 𝗦𝗲𝗮𝗿𝗰𝗵 𝗛𝗶𝘀𝘁𝗼𝗿𝘆", callback_data="ui_history", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🔔 𝗥𝗲𝗾𝘂𝗲𝘀𝘁 𝗠𝗼𝘃𝗶𝗲", callback_data="ui_request", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)]
    ])

@Client.on_message(filters.command("start"))
async def start_menu_handler(client: Client, message: Message):
    if len(message.command) > 1: 
        cmd = message.command[1]
        if cmd.startswith("appeal_"):
            p_type = cmd.split("_")[1]
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("𝗦𝘂𝗯𝗺𝗶𝘁 𝗙𝗼𝗿𝗺𝗮𝗹 𝗔𝗽𝗽𝗲𝗮𝗹", callback_data=f"appeal_global_{p_type}", style=ButtonStyle.PRIMARY)]])
            await message.reply_text(f"⚖️ **𝗚𝗹𝗼𝗯𝗮𝗹 {p_type.upper()} 𝗔𝗽𝗽𝗲𝗮𝗹 𝗖𝗲𝗻𝘁𝗲𝗿**\n\n𝖢𝗅𝗂𝖼𝗄 𝗍𝗁𝖾 𝖻𝗎𝗍𝗍𝗈𝗇 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝗈𝖿𝖿𝗂𝖼𝗂𝖺𝗅𝗅𝗒 𝗌𝗎𝖻𝗆𝗂𝗍 𝗒𝗈𝗎𝗋 𝖺𝗉𝗉𝖾𝖺𝗅 𝗍𝗈 𝗍𝗁𝖾 𝖢𝗋𝖾𝖺𝗍𝗈𝗋.", reply_markup=btn)
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
    await message.reply_text(text=HELP_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    raise StopPropagation

@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):
    bot_me = await client.get_me()
    await message.reply_text(text=ABOUT_TEXT.format(bot_name=bot_me.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    raise StopPropagation

@Client.on_message(filters.command("id"))
async def id_command_handler(client: Client, message: Message):
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat: return await message.reply_text(f"📢 **𝗙𝗼𝗿𝘄𝗮𝗿𝗱𝗲𝗱 𝗖𝗵𝗮𝘁 𝗜𝗗:** monospace\n**𝗡𝗮𝗺𝗲:** `{reply.forward_from_chat.title}`")
        elif reply.forward_from: return await message.reply_text(f"👤 **𝗙𝗼𝗿𝘄𝗮𝗿𝗱𝗲𝗱 𝗨𝘀𝗲𝗿 𝗜𝗗:** `{reply.forward_from.id}`\n**𝗡𝗮𝗺𝗲:** `{reply.forward_from.first_name}`")
        else: return await message.reply_text(f"👤 **𝗥𝗲𝗽𝗹𝗶𝗲𝗱 𝗨𝘀𝗲𝗿 𝗜𝗗:** `{reply.from_user.id}`")
    else: return await message.reply_text(f"👤 **𝗬𝗼𝘂𝗿 𝗜𝗗:** `{message.from_user.id}`\n💬 **𝗖𝘂𝗿𝗿𝗲𝗻𝘁 𝗖𝗵𝗮𝘁 𝗜𝗗:** `{message.chat.id}`")
        
@Client.on_message(filters.command("info"))
async def info_command_handler(client: Client, message: Message):
    target_user_id = message.from_user.id
    if len(message.command) > 1:
        try: target_user_id = int(message.command[1])
        except ValueError: target_user_id = message.command[1]
    elif message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        
    try: user = await client.get_users(target_user_id)
    except Exception: return await message.reply_text("❌ **𝐄𝐫𝐫𝐨𝐫:** 𝖢𝗈𝗎𝗅𝖽 𝗇𝗈𝗍 𝖿𝖾𝗍𝖼𝗁 𝖽𝖺𝗍𝖺 𝖿𝗈𝗋 𝗍𝗁𝖺𝗍 𝗎𝗌𝖾𝗋.")
        
    name = user.first_name + (f" {user.last_name}" if user.last_name else "")
    info_text = f"👤 **𝗨𝗦𝗘𝗥 𝗜𝗡𝗙𝗢𝗥𝗠𝗔𝗧𝗜𝗢𝗡**\n\n**𝗡𝗮𝗺𝗲:** {name}\n**𝗜𝗗:** `{user.id}`\n**𝗣𝗿𝗼𝗳𝗶𝗹𝗲:** [𝗗𝗶𝗿𝗲𝗰𝘁 𝗟𝗶𝗻𝗸](tg://user?id={user.id})\n"
    
    if message.from_user.id in Config.ADMINS:
        u_sett = await db.get_user_settings(user.id)
        joined = u_sett.get("joined_date", "Unknown")
        searches = u_sett.get("total_searches", 0)
        punish_doc = await db.punishments.find_one({"_id": f"{user.id}_global"})
        warns = punish_doc.get("warns", 0) if punish_doc else 0
        p_type = punish_doc.get("type", "Clean").title() if punish_doc else "Clean"
        info_text += f"\n📊 **𝗔𝗗𝗠𝗜𝗡 𝗗𝗔𝗧𝗔𝗕𝗔𝗦𝗘 𝗦𝗧𝗔𝗧𝗦:**\n**𝗝𝗼𝗶𝗻𝗲𝗱 𝗗𝗮𝘁𝗲:** `{joined}`\n**𝗧𝗼𝘁𝗮𝗹 𝗦𝗲𝗮𝗿𝗰𝗵𝗲𝘀:** `{searches}`\n**𝗚𝗹𝗼𝗯𝗮𝗹 𝗦𝘁𝗮𝘁𝘂𝘀:** `{p_type}`\n**𝗪𝗮𝗿𝗻𝗶𝗻𝗴𝘀:** `{warns}`"
        
    if user.photo:
        async for photo in client.get_chat_photos(user.id, limit=1):
            await message.reply_photo(photo.file_id, caption=info_text)
            break
    else: await message.reply_text(info_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^ui_"))
async def callback_ui_router(client: Client, callback: CallbackQuery):
    target = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    bot_me = await client.get_me()
    
    if target == "back": await callback.message.edit_text(text=START_TEXT.format(bot_name=bot_me.first_name), reply_markup=get_start_markup(bot_me.username, user_id), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "info_menu": await callback.message.edit_text(text=INFO_MENU_TEXT, reply_markup=info_category_keyboard())
    elif target == "profile_menu": await callback.message.edit_text(text=PROFILE_MENU_TEXT, reply_markup=profile_category_keyboard())
    elif target == "media_menu": await callback.message.edit_text(text=MEDIA_MENU_TEXT, reply_markup=media_category_keyboard())
    elif target == "admin_menu" and user_id in Config.ADMINS: await callback.message.edit_text(text=ADMIN_MENU_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)]]))
    elif target == "help": await callback.message.edit_text(text=HELP_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "about": await callback.message.edit_text(text=ABOUT_TEXT.format(bot_name=bot_me.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "source": await callback.message.edit_text(text=SOURCE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗔𝗱𝗺𝗶𝗻", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "disclaimer": await callback.message.edit_text(text=DISCLAIMER_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "dmca": await callback.message.edit_text(text=DMCA_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 @ntmadminbot", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "privacy": await callback.message.edit_text(text=PRIVACY_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "stats":
        u_sett = await db.get_user_settings(user_id)
        stats_text = (
            f"📊 **𝗬𝗼𝘂𝗿 𝗣𝗲𝗿𝘀𝗼𝗻𝗮𝗹 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀:**\n\n"
            f"👤 **𝗡𝗮𝗺𝗲:** {callback.from_user.first_name}\n"
            f"🆔 **𝗜𝗗:** `{user_id}`\n"
            f"📅 **𝗝𝗼𝗶𝗻𝗲𝗱 𝗢𝗻:** `{u_sett.get('joined_date', 'Unknown')}`\n"
            f"🔍 **𝗧𝗼𝘁𝗮𝗹 𝗦𝗲𝗮𝗿𝗰𝗵𝗲𝘀:** `{u_sett.get('total_searches', 0)}`\n"
            f"⚙️ **𝗦𝗲𝗮𝗿𝗰𝗵 𝗠𝗼𝗱𝗲:** `{u_sett.get('search_mode', 'default').title()}`\n\n"
            f"*(𝖳𝗁𝖺𝗇𝗄 𝗒𝗈𝗎 𝖿𝗈𝗋 𝗎𝗌𝗂𝗇𝗀 {bot_me.first_name}!)*"
        )
        await callback.message.edit_text(text=stats_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗣𝗿𝗼𝗳𝗶𝗹𝗲", callback_data="ui_profile_menu", style=ButtonStyle.DANGER)]]))
        
    elif target == "settings_menu":
        keyboard = [[InlineKeyboardButton(text="👤 𝗣𝗲𝗿𝘀𝗼𝗻𝗮𝗹 𝗦𝗲𝗮𝗿𝗰𝗵 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", callback_data="tier_user_home", style=ButtonStyle.PRIMARY)]]
        if await db.get_connected_groups(user_id): keyboard.append([InlineKeyboardButton(text="🛡️ 𝗠𝗮𝗻𝗮𝗴𝗲 𝗠𝘆 𝗟𝗶𝗻𝗸𝗲𝗱 𝗚𝗿𝗼𝘂𝗽𝘀", callback_data="tier_group_list", style=ButtonStyle.PRIMARY)])
        if user_id in Config.ADMINS:
            keyboard.append([InlineKeyboardButton("📊 𝗦𝘆𝘀𝘁𝗲𝗺 𝗦𝘁𝗮𝘁𝘀 𝗗𝗮𝘀𝗵𝗯𝗼𝗮𝗿𝗱", callback_data="stats_home", style=ButtonStyle.PRIMARY)])
            keyboard.append([InlineKeyboardButton(text="👑 𝗕𝗼𝘁 𝗖𝗿𝗲𝗮𝘁𝗼𝗿 𝗖𝗼𝗻𝘁𝗿𝗼𝗹 𝗣𝗮𝗻𝗲𝗹", callback_data="set_home", style=ButtonStyle.PRIMARY)])
        keyboard.append([InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)])
        await callback.message.edit_text(text="🎛️ **𝗖𝗲𝗻𝘁𝗿𝗮𝗹 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀 𝗛𝘂𝗯:**\n𝖲𝖾𝗅𝖾𝖼𝗍 𝗍𝗁𝖾 𝖺𝖼𝖼𝖾𝗌𝗌 𝗅𝖺𝗒𝖾𝗋 𝗍𝗂𝖾𝗋 𝗒𝗈𝗎 𝗐𝗂𝗌𝗁 𝗍𝗈 𝗂𝗇𝗌𝗉𝖾𝖼𝗍 𝗈𝗋 𝗆𝗈𝖽𝗂𝖿𝗒:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif target == "history":
        callback.message.from_user = callback.from_user
        callback.message.text, callback.message.command = "/history", ["history"]
        from plugins.advanced import view_search_history
        await view_search_history(client, callback.message)

    elif target == "request":
        callback.message.from_user = callback.from_user
        callback.message.text, callback.message.command = "/request", ["request"]
        from plugins.request import request_command
        await request_command(client, callback.message)
        
    elif target == "vip":
        callback.message.from_user = callback.from_user
        callback.message.text, callback.message.command = "/checkvip", ["checkvip"]
        from plugins.vip_system import check_vip_cmd
        await check_vip_cmd(client, callback.message)
        
    elif target == "buyvip":
        callback.message.from_user = callback.from_user
        callback.message.text, callback.message.command = "/buyvip", ["buyvip"]
        from plugins.vip_system import buy_vip_command
        await buy_vip_command(client, callback.message)
        
    await callback.answer()
