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
# 📝 DYNAMIC TEXT TEMPLATES (Zero-Processing Fonts)
# ==========================================
START_TEXT = """👋 **𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 {bot_name}!**

𝖨 𝖺𝗆 𝖺 𝗁𝗂𝗀𝗁𝗅𝗒-𝗈𝗉𝗍𝗂𝗆𝗂𝗓𝖾𝖽 𝖳𝖾𝗅𝖾𝗀𝗋𝖺𝗆 𝗋𝖾𝗉𝗈𝗌𝗂𝗍𝗈𝗋𝗒 𝗌𝖾𝖺𝗋𝖼𝗁 𝗌𝗒𝗌𝗍𝖾𝗆. 𝖨 𝗁𝖾𝗅𝗉 𝗒𝗈𝗎 𝗂𝗇𝗌𝗍𝖺𝗇𝗍𝗅𝗒 𝖿𝗂𝗇𝖽 𝗆𝗈𝗏𝗂𝖾𝗌, 𝖿𝗂𝗅𝖾𝗌, 𝖺𝗇𝖽 𝖽𝖺𝗍𝖺 𝖻𝗒 𝗂𝗇𝖽𝖾𝗑𝗂𝗇𝗀 𝖺𝗏𝖺𝗂𝗅𝖺𝖻𝗅𝖾 𝗉𝗎𝖻𝗅𝗂𝖼 𝖼𝗁𝖺𝗇𝗇𝖾𝗅𝗌.

✨ 𝖴𝗌𝖾 𝗍𝗁𝖾 𝖼𝖺𝗍𝖾𝗀𝗈𝗋𝗒 𝗁𝗎𝖻𝗌 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝖾𝗑𝗉𝗅𝗈𝗋𝖾 𝗆𝗒 𝖿𝖾𝖺𝗍𝗎𝗋𝖾𝗌:"""

MEDIA_MENU_TEXT = """🎬 **𝗠𝗲𝗱𝗶𝗮 𝗛𝘂𝗯**

𝖤𝗏𝖾𝗋𝗒𝗍𝗁𝗂𝗇𝗀 𝗒𝗈𝗎 𝗇𝖾𝖾𝖽 𝗍𝗈 𝖿𝗂𝗇𝖽 𝖺𝗇𝖽 𝗍𝗋𝖺𝖼𝗄 𝗒𝗈𝗎𝗋 𝖿𝖺𝗏𝗈𝗋𝗂𝗍𝖾 𝗆𝗈𝗏𝗂𝖾𝗌.
• 𝖵𝗂𝖾𝗐 𝗒𝗈𝗎𝗋 𝗉𝖺𝗌𝗍 𝗌𝖾𝖺𝗋𝖼𝗁 𝗁𝗂𝗌𝗍𝗈𝗋𝗒
• 𝖱𝖾𝗊𝗎𝖾𝗌𝗍 𝗆𝗈𝗏𝗂𝖾𝗌 𝗍𝗁𝖺𝗍 𝖺𝗋𝖾𝗇'𝗍 𝗂𝗇 𝗍𝗁𝖾 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾"""

PROFILE_MENU_TEXT = """💎 **𝗠𝘆 𝗣𝗿𝗼𝗳𝗶𝗹𝗲**

𝖬𝖺𝗇𝖺𝗀𝖾 𝗒𝗈𝗎𝗋 𝗉𝖾𝗋𝗌𝗈𝗇𝖺𝗅 𝖺𝖼𝖼𝗈𝗎𝗇𝗍, 𝖼𝗁𝖾𝖼𝗄 𝗒𝗈𝗎𝗋 𝗌𝖾𝖺𝗋𝖼𝗁 𝗌𝗍𝖺𝗍𝗌, 𝗈𝗋 𝗎𝗉𝗀𝗋𝖺𝖽𝖾 𝗍𝗈 𝖺 𝖵𝖨𝖯 𝗉𝗅𝖺𝗇 𝖿𝗈𝗋 𝗉𝗋𝖾𝗆𝗂𝗎𝗆 𝖿𝖾𝖺𝗍𝗎𝗋𝖾𝗌."""

INFO_MENU_TEXT = """ℹ️ **𝗜𝗻𝗳𝗼𝗿𝗺𝗮𝘁𝗶𝗼𝗻 𝗛𝘂𝗯**

𝖲𝖾𝗅𝖾𝖼𝗍 𝖺 𝗍𝗈𝗉𝗂𝖼 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝗋𝖾𝖺𝖽 𝗆𝗈𝗋𝖾 𝖺𝖻𝗈𝗎𝗍 𝗆𝗒 𝗉𝗈𝗅𝗂𝖼𝗂𝖾𝗌, 𝗁𝗈𝗐 𝗍𝗈 𝗎𝗌𝖾 𝗆𝗒 𝖼𝗈𝗆𝗆𝖺𝗇𝖽𝗌, 𝖺𝗇𝖽 𝗆𝗒 𝗌𝗈𝗎𝗋𝖼𝖾 𝖼𝗈𝖽𝖾."""

ADMIN_MENU_TEXT = """👨‍💻 **𝗔𝗱𝗺𝗶𝗻 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 𝗖𝗲𝗻𝘁𝗲𝗿**

𝖶𝖾𝗅𝖼𝗈𝗆𝖾 𝖻𝖺𝖼𝗄, 𝖡𝗈𝗌𝗌! 𝖧𝖾𝗋𝖾 𝖺𝗋𝖾 𝗒𝗈𝗎𝗋 𝗊𝗎𝗂𝖼𝗄-𝗋𝖾𝖿𝖾𝗋𝖾𝗇𝖼𝖾 𝗌𝗒𝗌𝗍𝖾𝗆 𝖼𝗈𝗆𝗆𝖺𝗇𝖽𝗌:

📢 `/broadcast` - 𝖬𝖺𝗌𝗌 𝖽𝖾𝗉𝗅𝗈𝗒 𝗆𝖾𝗌𝗌𝖺𝗀𝖾𝗌
👻 `/broadcast_edit` - 𝖲𝗂𝗅𝖾𝗇𝗍𝗅𝗒 𝗎𝗉𝖽𝖺𝗍𝖾 𝖺𝗇 𝖺𝖼𝗍𝗂𝗏𝖾 𝖻𝗋𝗈𝖺𝖽𝖼𝖺𝗌𝗍
🗑 `/broadcast_del` - 𝖤𝗋𝖺𝗌𝖾 𝖺 𝖻𝗋𝗈𝖺𝖽𝖼𝖺𝗌𝗍 𝖿𝗋𝗈𝗆 𝗍𝗁𝖾 𝖵𝖺𝗎𝗅𝗍
🎯 `/user_broadcast` - 𝖲𝖾𝖼𝗎𝗋𝖾 𝟣-𝗈𝗇-𝟣 𝖽𝗂𝗋𝖾𝖼𝗍 𝗆𝖾𝗌𝗌𝖺𝗀𝖾
🧹 `/delbroadcastuser` - 𝖲𝖼𝗋𝗎𝖻 𝖺𝗇 𝖺𝖽 𝖿𝗋𝗈𝗆 𝖺 𝗌𝗂𝗇𝗀𝗅𝖾 𝗎𝗌𝖾𝗋
📊 `/info` - 𝖢𝗁𝖾𝖼𝗄 𝗎𝗌𝖾𝗋 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾 𝗌𝗍𝖺𝗍𝗌

*(𝖴𝗌𝖾 𝗍𝗁𝖾 𝗌𝖾𝗍𝗍𝗂𝗇𝗀𝗌 𝗆𝖾𝗇𝗎 𝖿𝗈𝗋 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾/𝗈𝗉𝗍𝗂𝗆𝗂𝗓𝖺𝗍𝗂𝗈𝗇 𝖼𝗈𝗇𝗍𝗋𝗈𝗅𝗌)*"""

ABOUT_TEXT = """🤖 **𝗕𝗼𝘁 𝗡𝗮𝗺𝗲:** {bot_name}
🧑‍💻 **𝗖𝗿𝗲𝗮𝘁𝗼𝗿:** [𝗟𝗔𝗧𝗛𝗘𝗘𝗦𝗛](https://t.me/LATHEESH)
⚙️ **𝗘𝗻𝗴𝗶𝗻𝗲:** 𝖪𝗎𝗋𝗂𝗀𝗋𝖺𝗆 (𝖯𝗒𝗍𝗁𝗈𝗇)
📊 **𝗦𝘁𝗮𝘁𝘂𝘀:** 𝖠𝖼𝗍𝗂𝗏𝖾 & 𝖱𝗎𝗇𝗇𝗂𝗇𝗀"""

HELP_TEXT = """🛠 **𝗛𝗼𝘄 𝘁𝗼 𝗨𝘀𝗲 𝗧𝗵𝗶𝘀 𝗕𝗼𝘁:**

**1.** 𝖠𝖽𝖽 𝗆𝖾 𝗍𝗈 𝗒𝗈𝗎𝗋 𝗀𝗋𝗈𝗎𝗉 𝗎𝗌𝗂𝗇𝗀 𝗍𝗁𝖾 𝖻𝗎𝗍𝗍𝗈𝗇 𝗈𝗇 𝗍𝗁𝖾 𝗆𝖺𝗂𝗇 𝗆𝖾𝗇𝗎.
**2.** 𝖬𝖺𝗄𝖾 𝗆𝖾 𝖺𝗇 𝖺𝖽𝗆𝗂𝗇 𝗌𝗈 𝖨 𝖼𝖺𝗇 𝗋𝖾𝖺𝖽 𝗆𝖾𝗌𝗌𝖺𝗀𝖾𝗌.
**3.** 𝖲𝗂𝗆𝗉𝗅𝗒 𝗍𝗒𝗉𝖾 𝗍𝗁𝖾 𝗇𝖺𝗆𝖾 𝗈𝖿 𝗍𝗁𝖾 𝗆𝗈𝗏𝗂𝖾 𝗈𝗋 𝖿𝗂𝗅𝖾 𝗒𝗈𝗎 𝗐𝖺𝗇𝗍.
**4.** 𝖨 𝗐𝗂𝗅𝗅 𝖺𝗎𝗍𝗈𝗆𝖺𝗍𝗂𝖼𝖺𝗅𝗅𝗒 𝗋𝖾𝗉𝗅𝗒 𝗐𝗂𝗍𝗁 𝗍𝗁𝖾 𝗆𝖺𝗍𝖼𝗁𝗂𝗇𝗀 𝖿𝗂𝗅𝖾𝗌!"""

SOURCE_TEXT = "🔒 **𝗦𝗼𝘂𝗿𝗰𝗲 𝗖𝗼𝗱𝗲 𝗦𝘁𝗮𝘁𝘂𝘀:**\n\n𝖳𝗁𝗂𝗌 𝖻𝗈𝗍'𝗌 𝗌𝗈𝗎𝗋𝖼𝖾 𝖼𝗈𝖽𝖾 𝗂𝗌 𝗌𝗍𝗋𝗂𝖼𝗍𝗅𝗒 **𝗉𝗋𝗂𝗏𝖺𝗍𝖾** 𝖺𝗇𝖽 𝗐𝗂𝗅𝗅 𝗇𝗈𝗍 𝖻𝖾 𝗉𝗎𝖻𝗅𝗂𝗌𝗁𝖾𝖽 𝗉𝗎𝖻𝗅𝗂𝖼𝗅𝗒. 𝖨𝖿 𝗒𝗈𝗎 𝗁𝖺𝗏𝖾 𝖻𝗎𝗌𝗂𝗇𝖾𝗌𝗌 𝗂𝗇𝗊𝗎𝗂𝗋𝗂𝖾𝗌, 𝖼𝗈𝗇𝗍𝖺𝖼𝗍 𝗍𝗁𝖾 𝖺𝖽𝗆𝗂𝗇."
DISCLAIMER_TEXT = "⚠️ **𝗗𝗶𝘀𝗰𝗹𝗮𝗶𝗺𝗲𝗿:**\n\n𝖳𝗁𝗂𝗌 𝖻𝗈𝗍 𝗈𝗇𝗅𝗒 𝗂𝗇𝖽𝖾𝗑𝖾𝗌 𝖽𝖺𝗍𝖺 𝗍𝗁𝖺𝗍 𝗂𝗌 𝗉𝗎𝖻𝗅𝗂𝖼𝗅𝗒 𝗎𝗉𝗅𝗈𝖺𝖽𝖾𝖽 𝗈𝗇 𝖳𝖾𝗅𝖾𝗀𝗋𝖺𝗆 𝖻𝗒 𝗈𝗍𝗁𝖾𝗋 𝗎𝗌𝖾𝗋𝗌. 𝖳𝗁𝖾 𝖼𝗋𝖾𝖺𝗍𝗈𝗋 𝗁𝗈𝗅𝖽𝗌 𝗇𝗈 𝗋𝖾𝗌𝗉𝗈𝗇𝗌𝗂𝖻𝗂𝗅𝗂𝗍𝗒 𝖿𝗈𝗋 𝗎𝗌𝖾𝗋-𝗀𝖾𝗇𝖾𝗋𝖺𝗍𝖾𝖽 𝖼𝗈𝗇𝗍𝖾𝗇𝗍."
DMCA_TEXT = "⚖️ **𝗗𝗠𝗖𝗔 & 𝗧𝗮𝗸𝗲𝗱𝗼𝘄𝗻 𝗥𝗲𝗾𝘂𝗲𝘀𝘁𝘀:**\n\n𝖨𝖿 𝗒𝗈𝗎 𝖺𝗋𝖾 𝖺 𝖼𝗈𝗉𝗒𝗋𝗂𝗀𝗁𝗍 𝗈𝗐𝗇𝖾𝗋 𝖺𝗇𝖽 𝗐𝗂𝗌𝗁 𝗍𝗈 𝗉𝗅𝖺𝖼𝖾 𝖺 𝗋𝖾𝗊𝗎𝖾𝗌𝗍 𝗍𝗈 𝗋𝖾𝗆𝗈𝗏𝖾 𝖺 𝗌𝗉𝖾𝖼𝗂𝖿𝗂𝖼 𝖿𝗂𝗅𝖾 𝗈𝗋 𝗅𝗂𝗇𝗄 𝖿𝗋𝗈𝗆 𝗈𝗎𝗋 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾, 𝗉𝗅𝖾𝖺𝗌𝖾 𝖼𝗈𝗇𝗍𝖺𝖼𝗍 𝗈𝗎𝗋 𝖺𝖽𝗆𝗂𝗇 𝖽𝗂𝗋𝖾𝖼𝗍𝗅𝗒.\n\n**𝗖𝗼𝗻𝘁𝗮𝗰𝘁:** [@ntmadminbot](https://t.me/ntmadminbot)"
PRIVACY_TEXT = "🔒 **𝗣𝗿𝗶𝘃𝗮𝗰𝘆 𝗣𝗼𝗹𝗶𝗰𝘆:**\n\n𝖶𝖾 𝗋𝖾𝗌𝗉𝖾𝖼𝗍 𝗒𝗈𝗎𝗋 𝗉𝗋𝗂𝗏𝖺𝖼𝗒. 𝖳𝗁𝗂𝗌 𝖻𝗈𝗍 𝗈𝗇𝗅𝗒 𝖼𝗈𝗅𝗅𝖾𝖼𝗍𝗌 𝖻𝖺𝗌𝗂𝖼 𝗎𝗌𝖺𝗀𝖾 𝗌𝗍𝖺𝗍𝗂𝗌𝗍𝗂𝖼𝗌 𝗍𝗈 𝗈𝗉𝗍𝗂𝗆𝗂𝗓𝖾 𝗌𝖾𝖺𝗋𝖼𝗁 𝗉𝖾𝗋𝖿𝗈𝗋𝗆𝖺𝗇𝖼𝖾. 𝖶𝖾 𝖽𝗈 𝗇𝗈𝗍 𝗌𝗍𝗈𝗋𝖾 𝗌𝖾𝗇𝗌𝗂𝗍𝗂𝗏𝖾 𝗉𝖾𝗋𝗌𝗈𝗇𝖺𝗅 𝗂𝗇𝖿𝗈𝗋𝗆𝖺𝗍𝗂𝗈𝗇."

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
        [InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣", url=f"http://t.me/{bot_username}?startgroup=true", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("🎬 𝗠𝗲𝗱𝗶𝗮 𝗛𝘂𝗯", callback_data="ui_media_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("💎 𝗠𝘆 𝗣𝗿𝗼𝗳𝗶𝗹𝗲", callback_data="ui_profile_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚙️ 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", callback_data="ui_settings_menu", style=ButtonStyle.PRIMARY), InlineKeyboardButton("ℹ️ 𝗛𝗲𝗹𝗽 & 𝗜𝗻𝗳𝗼", callback_data="ui_info_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🌐 𝗩𝗜𝗦𝗜𝗧 𝗢𝗨𝗥 𝗪𝗘𝗕𝗦𝗜𝗧𝗘", url="https://alatheesh.github.io/NTMONLINE", style=ButtonStyle.PRIMARY)]
    ]
    if user_id in Config.ADMINS:
        buttons.append([InlineKeyboardButton("👨‍💻 𝗔𝗱𝗺𝗶𝗻 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 𝗖𝗲𝗻𝘁𝗲𝗿", callback_data="ui_admin_menu", style=ButtonStyle.DANGER)])
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

# ==========================================
# 📢 USER COMMAND HANDLERS
# ==========================================
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
    except Exception:
        pass
        
    bot_me = await client.get_me()
    formatted_start = START_TEXT.format(bot_name=bot_me.first_name)
    markup = get_start_markup(bot_me.username, user_id)
    
    try:
        await message.reply_photo(photo=random.choice(START_BANNER_IMAGES), caption=formatted_start, reply_markup=markup)
    except Exception:
        await message.reply_text(text=formatted_start, reply_markup=markup)
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

# ==========================================
# 🔍 UTILITY COMMANDS (/id & /info)
# ==========================================
@Client.on_message(filters.command("id"))
async def id_command_handler(client: Client, message: Message):
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            return await message.reply_text(f"📢 **𝗙𝗼𝗿𝘄𝗮𝗿𝗱𝗲𝗱 𝗖𝗵𝗮𝘁 𝗜𝗗:** `{reply.forward_from_chat.id}`\n**𝗡𝗮𝗺𝗲:** `{reply.forward_from_chat.title}`")
        elif reply.forward_from:
            return await message.reply_text(f"👤 **𝗙𝗼𝗿𝘄𝗮𝗿𝗱𝗲𝗱 𝗨𝘀𝗲𝗿 𝗜𝗗:** `{reply.forward_from.id}`\n**𝗡𝗮𝗺𝗲:** `{reply.forward_from.first_name}`")
        else:
            return await message.reply_text(f"👤 **𝗥𝗲𝗽𝗹𝗶𝗲𝗱 𝗨𝘀𝗲𝗿 𝗜𝗗:** `{reply.from_user.id}`")
    else:
        return await message.reply_text(f"👤 **𝗬𝗼𝘂𝗿 𝗜𝗗:** `{message.from_user.id}`\n💬 **𝗖𝘂𝗿𝗿𝗲𝗻𝘁 𝗖𝗵𝗮𝘁 𝗜𝗗:** `{message.chat.id}`")
        
@Client.on_message(filters.command("info"))
async def info_command_handler(client: Client, message: Message):
    target_user_id = message.from_user.id
    if len(message.command) > 1:
        try:
            target_user_id = int(message.command[1])
        except ValueError:
            target_user_id = message.command[1]
    elif message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        
    try:
        user = await client.get_users(target_user_id)
    except Exception:
        return await message.reply_text("❌ **𝐄𝐫𝐫𝐨𝐫:** 𝖢𝗈𝗎𝗅𝖽 𝗇𝗈𝗍 𝖿𝖾𝗍𝖼𝗁 𝖽𝖺𝗍𝖺 𝖿𝗈𝗋 𝗍𝗁𝖺𝗍 𝗎𝗌𝖾𝗋.")
        
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
        await callback.message.edit_text(text=ADMIN_MENU_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)]]))

    # 📄 SUB-MENU PAGES (Information)
    elif target == "help":
        await callback.message.edit_text(text=HELP_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "about":
        await callback.message.edit_text(text=ABOUT_TEXT.format(bot_name=bot_me.first_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "source":
        await callback.message.edit_text(text=SOURCE_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗔𝗱𝗺𝗶𝗻", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "disclaimer":
        await callback.message.edit_text(text=DISCLAIMER_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
    elif target == "dmca":
        await callback.message.edit_text(text=DMCA_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 @ntmadminbot", url="https://t.me/ntmadminbot", style=ButtonStyle.PRIMARY)], [InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]), link_preview_options=LinkPreviewOptions(is_disabled=True))
    elif target == "privacy":
        await callback.message.edit_text(text=PRIVACY_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗜𝗻𝗳𝗼 𝗛𝘂𝗯", callback_data="ui_info_menu", style=ButtonStyle.DANGER)]]))
        
    # 📄 SUB-MENU PAGES (Profile & Media)
    elif target == "stats":
        u_sett = await db.get_user_settings(user_id)
        joined = u_sett.get("joined_date", "Unknown")
        total_searches = u_sett.get("total_searches", 0)
        mode = u_sett.get("search_mode", "default").title()
        
        stats_text = (
            f"📊 **𝗬𝗼𝘂𝗿 𝗣𝗲𝗿𝘀𝗼𝗻𝗮𝗹 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀:**\n\n"
            f"👤 **𝗡𝗮𝗺𝗲:** {callback.from_user.first_name}\n"
            f"🆔 **𝗜𝗗:** `{user_id}`\n"
            f"📅 **𝗝𝗼𝗶𝗻𝗲𝗱 𝗢𝗻:** `{joined}`\n"
            f"🔍 **𝗧𝗼𝘁𝗮𝗹 𝗦𝗲𝗮𝗿𝗰𝗵𝗲𝘀:** `{total_searches}`\n"
            f"⚙️ **𝗦𝗲𝗮𝗿𝗰𝗵 𝗠𝗼𝗱𝗲:** `{mode}`\n\n"
            f"*(𝖳𝗁𝖺𝗇𝗄 𝗒𝗈𝗎 𝖿𝗈𝗋 𝗎𝗌𝗂𝗇𝗀 {bot_me.first_name}!)*"
        )
        await callback.message.edit_text(text=stats_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗣𝗿𝗼𝗳𝗶𝗹𝗲", callback_data="ui_profile_menu", style=ButtonStyle.DANGER)]]))
        
    elif target == "settings_menu":
        keyboard = [[InlineKeyboardButton(text="👤 𝗣𝗲𝗿𝘀𝗼𝗻𝗮𝗹 𝗦𝗲𝗮𝗿𝗰𝗵 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", callback_data="tier_user_home", style=ButtonStyle.PRIMARY)]]
        if await db.get_connected_groups(user_id):
            keyboard.append([InlineKeyboardButton(text="🛡️ 𝗠𝗮𝗻𝗮𝗴𝗲 𝗠𝘆 𝗟𝗶𝗻𝗸𝗲𝗱 𝗚𝗿𝗼𝘂𝗽𝘀", callback_data="tier_group_list", style=ButtonStyle.PRIMARY)])
        if user_id in Config.ADMINS:
            keyboard.append([InlineKeyboardButton("📊 𝗦𝘆𝘀𝘁𝗲𝗺 𝗦𝘁𝗮𝘁𝘀 𝗗𝗮𝘀𝗵𝗯𝗼𝗮𝗿𝗱", callback_data="stats_home", style=ButtonStyle.PRIMARY)])
            keyboard.append([InlineKeyboardButton(text="👑 𝗕𝗼𝘁 𝗖𝗿𝗲𝗮𝘁𝗼𝗿 𝗖𝗼𝗻𝘁𝗿𝗼𝗹 𝗣𝗮𝗻𝗲𝗹", callback_data="set_home", style=ButtonStyle.PRIMARY)])
            
        keyboard.append([InlineKeyboardButton("🔙 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂", callback_data="ui_back", style=ButtonStyle.DANGER)])
        
        settings_text = "🎛️ **𝗖𝗲𝗻𝘁𝗿𝗮𝗹 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀 𝗛𝘂𝗯:**\n𝖲𝖾𝗅𝖾𝖼𝗍 𝗍𝗁𝖾 𝖺𝖼𝖼𝖾𝗌𝗌 𝗅𝖺𝗒𝖾𝗋 𝗍𝗂𝖾𝗋 𝗒𝗈𝗎 𝗐𝗂𝗌𝗁 𝗍𝗈 𝗂𝗇𝗌𝗉𝖾𝖼𝗍 𝗈𝗋 𝗆𝗈𝖽𝗂𝖿𝗒:"
        await callback.message.edit_text(text=settings_text, reply_markup=InlineKeyboardMarkup(keyboard))
        
    # 🔌 SEAMLESS BRIDGES TO YOUR EXISTING CODE (NO DELETIONS!)
    elif target == "history":
        callback.message.from_user = callback.from_user
        callback.message.text = "/history"
        callback.message.command = ["history"]
        from plugins.advanced import view_search_history
        await view_search_history(client, callback.message)

    elif target == "request":
        callback.message.from_user = callback.from_user
        callback.message.text = "/request"
        callback.message.command = ["request"]
        from plugins.request import request_command
        await request_command(client, callback.message)
        
    elif target == "vip":
        callback.message.from_user = callback.from_user
        callback.message.text = "/checkvip"
        callback.message.command = ["checkvip"]
        from plugins.vip_system import check_vip_cmd
        await check_vip_cmd(client, callback.message)
        
    elif target == "buyvip":
        callback.message.from_user = callback.from_user
        callback.message.text = "/buyvip"
        callback.message.command = ["buyvip"]
        from plugins.vip_system import buy_vip_command
        await buy_vip_command(client, callback.message)
        
    await callback.answer()
