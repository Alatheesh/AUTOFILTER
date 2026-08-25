import random
import asyncio
import datetime

from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    LinkPreviewOptions
)

from database.multi_db import db
from plugins.moderation import log_to_channel
from config import Config


# ==========================================
# 📝 DYNAMIC TEXT TEMPLATES
# ==========================================

START_TEXT = """👋 **𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 {bot_name}!**

I'm here to help you discover and find movies, series, and other available files. 🎬 Search for your favorites and explore content across different qualities and languages.

Enjoy your experience! ✨"""


MEDIA_MENU_TEXT = """🎬 **𝗠𝗘𝗗𝗜𝗔 𝗛𝗨𝗕**

Everything related to your searches is available here.

🕘 **Search History**
View and revisit your previous searches.

🎬 **Movie Requests**
Can't find something? Send a request and let us know."""


PROFILE_MENU_TEXT = """💎 **𝗠𝗬 𝗣𝗥𝗢𝗙𝗜𝗟𝗘**

Manage your account and view your personal information.

📊 Check your search activity
👑 View your VIP status
🛒 Explore available VIP plans"""


INFO_MENU_TEXT = """ℹ️ **𝗛𝗘𝗟𝗣 & 𝗜𝗡𝗙𝗢**

Need help or want to know more?

Here you can learn how to use the bot, read important information, and view our policies.

Choose a topic below."""


ADMIN_MENU_TEXT = """👨‍💻 **𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗 𝗖𝗘𝗡𝗧𝗘𝗥**

Welcome back! Here are some quick admin tools.

📢 `/broadcast` — Send a broadcast
✏️ `/broadcast_edit` — Edit a broadcast
🗑 `/broadcast_del` — Delete a broadcast
🎯 `/user_broadcast` — Message one user
🧹 `/delbroadcastuser` — Delete from one user
📊 `/info` — View user information

💡 Use **Bot Commands** for the complete command guide."""


BOT_COMMANDS_TEXT = """🤖 **𝗕𝗢𝗧 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦**

Browse all available commands in a simple and organized way.

Choose a category below to continue."""


USER_COMMANDS_TEXT = """👤 **𝗨𝗦𝗘𝗥 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦**

Explore commands available to you.

Commands are grouped by their purpose to make them easier to understand.

Choose a category below."""


ADMIN_COMMANDS_TEXT = """👨‍💻 **𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦**

Manage the bot using the available admin tools.

⚠️ These commands are restricted to authorized admins.

Choose a category below."""


SEARCH_COMMANDS_TEXT = """🔍 **𝗦𝗘𝗔𝗥𝗖𝗛 & 𝗗𝗜𝗦𝗖𝗢𝗩𝗘𝗥𝗬**

🔎 `/movie <name>`
Search for a movie or title.
**Example:** `/movie Avengers`

━━━━━━━━━━━━

🎬 `/plot <movie name>`
Get information about a movie.
**Example:** `/plot Interstellar`

━━━━━━━━━━━━

✨ `/font`
Open the text style generator.

━━━━━━━━━━━━

💡 **𝗤𝗨𝗜𝗖𝗞 𝗦𝗘𝗔𝗥𝗖**
Simply send the name of a movie or file to search directly."""


ACCOUNT_COMMANDS_TEXT = """👤 **𝗔𝗖𝗖𝗢𝗨𝗡𝗧 & 𝗩𝗜𝗣**

🏠 `/start`
Open the main menu.

🆔 `/id`
View your User ID and Chat ID.

ℹ️ `/info`
View your account information.

━━━━━━━━━━━━

💎 **𝗩𝗜𝗣 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦**

👑 `/checkvip`
Check your current VIP status.

🛒 `/buyvip`
View available VIP plans.

🎁 `/redeem <code>`
Redeem a VIP or promotional code.
**Example:** `/redeem ABC123`"""


SETTINGS_COMMANDS_TEXT = """⚙️ **𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦 & 𝗚𝗥𝗢𝗨𝗣𝗦**

⚙️ `/settings`
Open and manage your personal settings.

━━━━━━━━━━━━

👥 **𝗚𝗥𝗢𝗨𝗣 𝗖𝗢𝗡𝗡𝗘𝗖𝗧𝗜𝗢𝗡𝗦**

🔗 `/connect`
Connect the bot to a group.

🔌 `/disconnect`
Disconnect your linked group.

Use these commands to manage your group connection and preferences."""


REQUEST_COMMANDS_TEXT = """🎬 **𝗥𝗘𝗤𝗨𝗘𝗦𝗧𝗦 & 𝗛𝗜𝗦𝗧𝗢𝗥𝗬**

🎥 `/request <movie name>`
Request content that isn't available.
**Example:** `/request Avatar 3`

━━━━━━━━━━━━

🕘 `/history`
View your previous searches.

🗑 `/clear_history`
Delete your search history."""


TOOLS_COMMANDS_TEXT = """🛠 **𝗧𝗢𝗢𝗟𝗦 & 𝗜𝗡𝗙𝗢**

❓ `/help`
Learn how to use the bot.

🤖 `/about`
Learn more about the bot.

🆔 `/id`
Get User or Chat IDs.

ℹ️ `/info`
View account information."""


BROADCAST_COMMANDS_TEXT = """📢 **𝗕𝗥𝗢𝗔𝗗𝗖𝗔𝗦𝗧 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦**

📣 `/broadcast`
Open the Broadcast Wizard.

✏️ `/broadcast_edit`
Edit a previously sent broadcast.

🗑 `/broadcast_del`
Delete a broadcast.

🎯 `/user_broadcast`
Send a message to one user.

🧹 `/delbroadcastuser`
Delete a broadcast for a specific user.

💬 `/replybroadcast`
Reply to a user's broadcast response.

❌ `/cancelfollowup`
Cancel an active follow-up."""


MODERATION_COMMANDS_TEXT = """👥 **𝗨𝗦𝗘𝗥 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧**

Reply to a user or provide their User ID where required.

⚠️ `/warn` — Give a warning
✅ `/unwarn` — Remove a warning

🔇 `/mute` — Mute a user
🔊 `/unmute` — Unmute a user

🚫 `/ban` — Ban a user
🟢 `/unban` — Remove a ban

ℹ️ `/info <user_id>`
View detailed user information."""


STATS_COMMANDS_TEXT = """📊 **𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦 & 𝗠𝗢𝗡𝗜𝗧𝗢𝗥𝗜𝗡𝗚**

📈 `/stats`
View bot and system statistics.

👥 `/userstats`
View detailed user statistics.

ℹ️ `/info <user_id>`
View detailed information about a user."""


BACKUP_COMMANDS_TEXT = """💾 **𝗗𝗔𝗧𝗔𝗕𝗔𝗦𝗘 & 𝗕𝗔𝗖𝗞𝗨𝗣**

📦 `/backup`
Create a database backup.

⚠️ Use this command only when a backup is required.

━━━━━━━━━━━━

🧹 `/clear_job`
Clear an active background job."""


INDEX_COMMANDS_TEXT = """📥 **𝗜𝗡𝗗𝗘𝗫𝗜𝗡𝗚 & 𝗙𝗜𝗟𝗘𝗦**

📥 `/index`
Start indexing a source.

📦 `/batch`
Alternative indexing command.

❌ `/cancel_index`
Cancel the current indexing process.

📊 `/indexdata`
Manage or inspect indexed data.

━━━━━━━━━━━━

🗑 **𝗙𝗜𝗟𝗘 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧**

Reply to a file and use:

`/del` • `/delete` • `/remove`

━━━━━━━━━━━━

🧹 `/cleanjunk`
Clean unnecessary or junk data."""


VIP_ADMIN_COMMANDS_TEXT = """💎 **𝗩𝗜𝗣 𝗠𝗔𝗡𝗔𝗚𝗘𝗠𝗘𝗡𝗧**

👑 `/vippanel`

Open the complete VIP management panel.

From the panel, you can manage:

• VIP plans
• VIP users
• Payments
• Free trials
• VIP settings"""


SYSTEM_COMMANDS_TEXT = """⚙️ **𝗦𝗬𝗦𝗧𝗘𝗠 & 𝗚𝗥𝗢𝗨𝗣𝗦**

👨‍💻 `/admin`
Open the admin control panel.

🔗 `/setshort`
Configure the URL shortener.

🔄 `/refreshadmins`
Refresh cached group admin data.

💡 Use `/refreshadmins` inside the target group."""


ABOUT_TEXT = """🤖 **𝗔𝗕𝗢𝗨𝗧 {bot_name}**

{bot_name} helps you search for movies, series, and available files in a simple and convenient way. 🎬

🔎 Search for what you want
🎞 Explore available versions
🌐 Check available languages
📂 Access available results
💎 Explore VIP features

Everything is designed to make finding what you're looking for quick and easy."""


HELP_TEXT = """🛠 **𝗛𝗢𝗪 𝗧𝗢 𝗨𝗦𝗘 {bot_name}**

Getting started is simple. 👇

**① 🔎 Search**
Send the name of the movie, series, or file you're looking for.

**② 🎬 Choose**
Browse the available results and select the one you want.

**③ ⚙️ Select Options**
Choose from available quality, language, size, or other options.

**④ 📂 Access**
Follow the available buttons to continue with your selected result.

💎 You can also explore **My Profile** to check your activity and VIP status.

Need more help? Use the options below."""


SOURCE_TEXT = """🔒 **𝗦𝗢𝗨𝗥𝗖𝗘 𝗖𝗢𝗗𝗘**

The source code for this bot is private and is not publicly available.

For business inquiries, support, or other important matters, please contact the administrator."""


DISCLAIMER_TEXT = """⚠️ **𝗗𝗜𝗦𝗖𝗟𝗔𝗜𝗠𝗘𝗥**

This bot helps users search and access content available through Telegram.

The bot does not claim ownership of content uploaded or shared by third-party users or channels.

Users are responsible for how they use the content and services available through the bot."""


DMCA_TEXT = """⚖️ **𝗗𝗠𝗖𝗔 & 𝗧𝗔𝗞𝗘𝗗𝗢𝗪𝗡 𝗥𝗘𝗤𝗨𝗘𝗦𝗧𝗦**

If you are a copyright owner and would like to request the removal of specific content or links, please contact the administrator.

📩 **Contact:** [@ntmadminbot](https://t.me/ntmadminbot)

Please include enough information to identify the content in your request."""


PRIVACY_TEXT = """🔒 **𝗣𝗥𝗜𝗩𝗔𝗖𝗬 𝗣𝗢𝗟𝗜𝗖𝗬**

Your privacy matters to us.

The bot may store basic account and usage information required for its features and functionality.

Sensitive personal information is not intentionally collected through normal use of the bot.

By using the bot, you agree to the applicable terms and policies."""

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
# 🎛️ CATEGORY KEYBOARDS
# ==========================================

def get_start_markup(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                "➕ ADD ME TO YOUR GROUP",
                url=f"http://t.me/{bot_username}?startgroup=true",
                style=ButtonStyle.SUCCESS
            )
        ],
        [
            InlineKeyboardButton(
                "🎬 𝗠𝗘𝗗𝗜𝗔 𝗛𝗨𝗕",
                callback_data="ui_media_menu",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "💎 𝗠𝗬 𝗣𝗥𝗢𝗙𝗜𝗟𝗘",
                callback_data="ui_profile_menu",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ Settings",
                callback_data="ui_settings_menu",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "ℹ️ Help & Info",
                callback_data="ui_info_menu",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 BOT COMMANDS",
                callback_data="ui_commands_menu",
                style=ButtonStyle.SUCCESS
            )
        ],
        [
            InlineKeyboardButton(
                "🌐 VISIT OUR WEBSITE",
                url="https://alatheesh.github.io/NTMONLINE",
                style=ButtonStyle.PRIMARY
            )
        ]
    ]

    if user_id in Config.ADMINS:
        buttons.append([
            InlineKeyboardButton(
                "👨‍💻 𝗔𝗗𝗠𝗜𝗡 𝗖𝗢𝗠𝗠𝗔𝗡𝗗 𝗖𝗘𝗡𝗧𝗘𝗥",
                callback_data="ui_admin_menu",
                style=ButtonStyle.DANGER
            )
        ])

    return InlineKeyboardMarkup(buttons)


def info_category_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛠 Help Guide",
                callback_data="ui_help",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "🤖 About Bot",
                callback_data="ui_about",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "📝 Source Code",
                callback_data="ui_source",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "⚠️ Disclaimer",
                callback_data="ui_disclaimer",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "⚖️ DMCA",
                callback_data="ui_dmca",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "🔒 Privacy",
                callback_data="ui_privacy",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Main Menu",
                callback_data="ui_back",
                style=ButtonStyle.DANGER
            )
        ]
    ])


def profile_category_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 My Stats",
                callback_data="ui_stats",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "👑 VIP Status",
                callback_data="ui_vip",
                style=ButtonStyle.SUCCESS
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 Buy VIP",
                callback_data="ui_buyvip",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Main Menu",
                callback_data="ui_back",
                style=ButtonStyle.DANGER
            )
        ]
    ])


def media_category_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🕰 𝗦𝗘𝗔𝗥𝗖𝗛 𝗛𝗜𝗦𝗧𝗢𝗥𝗬",
                callback_data="ui_history",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "🔔 Request Movie",
                callback_data="ui_request",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Main Menu",
                callback_data="ui_back",
                style=ButtonStyle.DANGER
            )
        ]
    ])


# ==========================================
# 🤖 BOT COMMANDS KEYBOARDS
# ==========================================

def commands_menu_keyboard(user_id: int):
    buttons = [
        [
            InlineKeyboardButton(
                "👤 User Commands",
                callback_data="ui_user_commands",
                style=ButtonStyle.PRIMARY
            )
        ]
    ]

    if user_id in Config.ADMINS:
        buttons.append([
            InlineKeyboardButton(
                "👨‍💻 Admin Commands",
                callback_data="ui_admin_commands",
                style=ButtonStyle.DANGER
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 Back to Main Menu",
            callback_data="ui_back",
            style=ButtonStyle.DANGER
        )
    ])

    return InlineKeyboardMarkup(buttons)


def user_commands_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔍 Search & Discovery",
                callback_data="ui_cmd_search",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "👤 Account & VIP",
                callback_data="ui_cmd_account",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ Settings & Groups",
                callback_data="ui_cmd_settings",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "🎬 Requests & History",
                callback_data="ui_cmd_requests",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🛠 Tools & Information",
                callback_data="ui_cmd_tools",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Commands",
                callback_data="ui_commands_menu",
                style=ButtonStyle.DANGER
            )
        ]
    ])


def admin_commands_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="ui_admin_broadcast",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "👥 User Management",
                callback_data="ui_admin_moderation",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="ui_admin_stats",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "💾 Database & Backup",
                callback_data="ui_admin_backup",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "📥 Indexing & Files",
                callback_data="ui_admin_index",
                style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                "💎 VIP Management",
                callback_data="ui_admin_vip",
                style=ButtonStyle.SUCCESS
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ System & Groups",
                callback_data="ui_admin_system",
                style=ButtonStyle.PRIMARY
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to Commands",
                callback_data="ui_commands_menu",
                style=ButtonStyle.DANGER
            )
        ]
    ])


def commands_back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Back to User Commands",
                callback_data="ui_user_commands",
                style=ButtonStyle.DANGER
            )
        ]
    ])


def admin_commands_back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Back to Admin Commands",
                callback_data="ui_admin_commands",
                style=ButtonStyle.DANGER
            )
        ]
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

            btn = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Submit Formal Appeal",
                        callback_data=f"appeal_global_{p_type}",
                        style=ButtonStyle.PRIMARY
                    )
                ]
            ])

            await message.reply_text(
                f"⚖️ **Global {p_type.upper()} Appeal Center**\n\n"
                "Click the button below to officially submit your appeal to the Creator.",
                reply_markup=btn
            )

            raise StopPropagation

        return

    user_id = message.from_user.id

    user_exists = await db.users.find_one({
        "user_id": user_id
    })

    # ==========================================
    # 👤 NEW USER DETECTION + FREE TRIAL
    # ==========================================

    if not user_exists:

        await log_to_channel(
            client,
            f"#new_user\n"
            f"👤 Name: `{message.from_user.first_name}`\n"
            f"🆔 ID: `{user_id}`\n"
            f"🔗 Username: @{message.from_user.username or 'None'}"
        )

        await db.update_user_setting(
            user_id,
            "joined_date",
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        )

        settings = await db.get_settings()

        free_trial_enabled = settings.get(
            "free_trial_enabled",
            True
        )

        trial_plan = settings.get(
            "free_trial_plan",
            "gold"
        )

        trial_days = settings.get(
            "free_trial_days",
            7
        )

        # ==========================================
        # 🎁 GIVE FREE TRIAL IF ENABLED
        # ==========================================

        if free_trial_enabled and trial_days > 0:

            from plugins.vip_system import add_vip

            plan_names = {
                "gold": "🎁 Gold (Trial)",
                "silver": "🎁 Silver (Trial)",
                "bronze": "🎁 Bronze (Trial)"
            }

            selected_plan = plan_names.get(
                str(trial_plan).lower(),
                f"🎁 {str(trial_plan).title()} (Trial)"
            )

            await add_vip(
                user=message.from_user,
                plan_name=selected_plan,
                days=trial_days,
                method="Auto Free Trial",
                is_promo=True
            )

    # ==========================================
    # ⏳ START LOADING STICKER
    # ==========================================

    try:

        loading_msg = await message.reply_sticker(
            random.choice(START_STICKERS)
        )

        await asyncio.sleep(1)

        await loading_msg.delete()

    except Exception:
        pass

    # ==========================================
    # 🏠 START MENU
    # ==========================================

    bot_me = await client.get_me()

    formatted_start = START_TEXT.format(
        bot_name=bot_me.first_name
    )

    markup = get_start_markup(
        bot_me.username,
        user_id
    )

    try:

        await message.reply_photo(
            photo=random.choice(START_BANNER_IMAGES),
            caption=formatted_start,
            reply_markup=markup
        )

    except Exception:

        await message.reply_text(
            text=formatted_start,
            reply_markup=markup
        )

    raise StopPropagation


@Client.on_message(filters.command("help") & filters.private)
async def help_command_handler(client: Client, message: Message):

    await message.reply_text(
        text=HELP_TEXT,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Back to Info Hub",
                    callback_data="ui_info_menu",
                    style=ButtonStyle.DANGER
                )
            ]
        ])
    )

    raise StopPropagation


@Client.on_message(filters.command("about") & filters.private)
async def about_command_handler(client: Client, message: Message):

    bot_me = await client.get_me()

    await message.reply_text(
        text=ABOUT_TEXT.format(
            bot_name=bot_me.first_name
        ),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Back to Info Hub",
                    callback_data="ui_info_menu",
                    style=ButtonStyle.DANGER
                )
            ]
        ]),
        link_preview_options=LinkPreviewOptions(
            is_disabled=True
        )
    )

    raise StopPropagation


# ==========================================
# 🔍 UTILITY COMMANDS (/id & /info)
# ==========================================

@Client.on_message(filters.command("id"))
async def id_command_handler(client: Client, message: Message):

    if message.reply_to_message:

        reply = message.reply_to_message

        if reply.forward_from_chat:

            return await message.reply_text(
                f"📢 **Forwarded Chat ID:** "
                f"`{reply.forward_from_chat.id}`\n"
                f"**Name:** `{reply.forward_from_chat.title}`"
            )

        elif reply.forward_from:

            return await message.reply_text(
                f"👤 **Forwarded User ID:** "
                f"`{reply.forward_from.id}`\n"
                f"**Name:** `{reply.forward_from.first_name}`"
            )

        else:

            return await message.reply_text(
                f"👤 **Replied User ID:** "
                f"`{reply.from_user.id}`"
            )

    else:

        return await message.reply_text(
            f"👤 **Your ID:** `{message.from_user.id}`\n"
            f"💬 **Current Chat ID:** `{message.chat.id}`"
        )


@Client.on_message(filters.command("info"))
async def info_command_handler(client: Client, message: Message):

    target_user_id = message.from_user.id

    if len(message.command) > 1:

        try:
            target_user_id = int(
                message.command[1]
            )

        except ValueError:
            target_user_id = message.command[1]

    elif message.reply_to_message:

        target_user_id = (
            message.reply_to_message.from_user.id
        )

    try:

        user = await client.get_users(
            target_user_id
        )

    except Exception:

        return await message.reply_text(
            "❌ **Error:** Could not fetch data for that user."
        )

    name = user.first_name + (
        f" {user.last_name}"
        if user.last_name else ""
    )

    info_text = (
        f"👤 **USER INFORMATION**\n\n"
        f"**Name:** {name}\n"
        f"**ID:** `{user.id}`\n"
        f"**Profile:** [Direct Link](tg://user?id={user.id})\n"
    )

    if message.from_user.id in Config.ADMINS:

        u_sett = await db.get_user_settings(
            user.id
        )

        joined = u_sett.get(
            "joined_date",
            "Unknown"
        )

        searches = u_sett.get(
            "total_searches",
            0
        )

        punish_doc = await db.punishments.find_one({
            "_id": f"{user.id}_global"
        })

        warns = (
            punish_doc.get("warns", 0)
            if punish_doc else 0
        )

        p_type = (
            punish_doc.get(
                "type",
                "Clean"
            ).title()
            if punish_doc else "Clean"
        )

        info_text += (
            f"\n📊 **ADMIN DATABASE STATS:**\n"
            f"**Joined Date:** `{joined}`\n"
            f"**Total Searches:** `{searches}`\n"
            f"**Global Status:** `{p_type}`\n"
            f"**Warnings:** `{warns}`"
        )

    if user.photo:

        async for photo in client.get_chat_photos(
            user.id,
            limit=1
        ):

            await message.reply_photo(
                photo.file_id,
                caption=info_text
            )

            break

    else:

        await message.reply_text(
            info_text,
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            )
        )

    raise StopPropagation


# ==========================================
# 🔘 UI BUTTON LISTENER
# ==========================================

@Client.on_callback_query(filters.regex(r"^ui_"))
async def callback_ui_router(
    client: Client,
    callback: CallbackQuery
):

    target = callback.data.split(
        "_",
        1
    )[1]

    user_id = callback.from_user.id

    bot_me = await client.get_me()


    # ==========================================
    # 🏠 MAIN MENU
    # ==========================================

    if target in ["back", "features"]:

        await callback.message.edit_text(
            text=START_TEXT.format(
                bot_name=bot_me.first_name
            ),
            reply_markup=get_start_markup(
                bot_me.username,
                user_id
            ),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            )
        )


    # ==========================================
    # 📂 CATEGORY HUBS
    # ==========================================

    elif target == "info_menu":
    
        await callback.message.edit_text(
            text=INFO_MENU_TEXT.format(
                bot_name=bot_me.first_name
            ),
            reply_markup=info_category_keyboard()
        )

    elif target == "profile_menu":

        await callback.message.edit_text(
            text=PROFILE_MENU_TEXT,
            reply_markup=profile_category_keyboard()
        )


    elif target == "media_menu":

        await callback.message.edit_text(
            text=MEDIA_MENU_TEXT,
            reply_markup=media_category_keyboard()
        )


    elif target == "admin_menu" and user_id in Config.ADMINS:

        await callback.message.edit_text(
            text=ADMIN_MENU_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Main Menu",
                        callback_data="ui_back",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )


    # ==========================================
    # 🤖 BOT COMMANDS
    # ==========================================

    elif target == "commands_menu":

        await callback.message.edit_text(
            text=BOT_COMMANDS_TEXT,
            reply_markup=commands_menu_keyboard(
                user_id
            )
        )


    elif target == "user_commands":

        await callback.message.edit_text(
            text=USER_COMMANDS_TEXT,
            reply_markup=user_commands_keyboard()
        )


    elif (
        target == "admin_commands"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=ADMIN_COMMANDS_TEXT,
            reply_markup=admin_commands_keyboard()
        )


    # ==========================================
    # 👤 USER COMMAND CATEGORIES
    # ==========================================

    elif target == "cmd_search":

        await callback.message.edit_text(
            text=SEARCH_COMMANDS_TEXT,
            reply_markup=commands_back_keyboard()
        )


    elif target == "cmd_account":

        await callback.message.edit_text(
            text=ACCOUNT_COMMANDS_TEXT,
            reply_markup=commands_back_keyboard()
        )


    elif target == "cmd_settings":

        await callback.message.edit_text(
            text=SETTINGS_COMMANDS_TEXT,
            reply_markup=commands_back_keyboard()
        )


    elif target == "cmd_requests":

        await callback.message.edit_text(
            text=REQUEST_COMMANDS_TEXT,
            reply_markup=commands_back_keyboard()
        )


    elif target == "cmd_tools":

        await callback.message.edit_text(
            text=TOOLS_COMMANDS_TEXT,
            reply_markup=commands_back_keyboard()
        )


    # ==========================================
    # 👨‍💻 ADMIN COMMAND CATEGORIES
    # ==========================================

    elif (
        target == "admin_broadcast"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=BROADCAST_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_moderation"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=MODERATION_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_stats"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=STATS_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_backup"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=BACKUP_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_index"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=INDEX_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_vip"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=VIP_ADMIN_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    elif (
        target == "admin_system"
        and user_id in Config.ADMINS
    ):

        await callback.message.edit_text(
            text=SYSTEM_COMMANDS_TEXT,
            reply_markup=admin_commands_back_keyboard()
        )


    # ==========================================
    # 📄 INFORMATION PAGES
    # ==========================================

    elif target == "help":
    
        await callback.message.edit_text(
            text=HELP_TEXT.format(
                bot_name=bot_me.first_name
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )

    elif target == "about":

        await callback.message.edit_text(
            text=ABOUT_TEXT.format(
                bot_name=bot_me.first_name
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ]),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            )
        )


    elif target == "source":

        await callback.message.edit_text(
            text=SOURCE_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📞 Contact Admin",
                        url="https://t.me/ntmadminbot",
                        style=ButtonStyle.PRIMARY
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )


    elif target == "disclaimer":

        await callback.message.edit_text(
            text=DISCLAIMER_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )


    elif target == "dmca":

        await callback.message.edit_text(
            text=DMCA_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📞 Contact @ntmadminbot",
                        url="https://t.me/ntmadminbot",
                        style=ButtonStyle.PRIMARY
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ]),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            )
        )


    elif target == "privacy":

        await callback.message.edit_text(
            text=PRIVACY_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Info Hub",
                        callback_data="ui_info_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )


    # ==========================================
    # 📄 PROFILE & MEDIA
    # ==========================================

    elif target == "stats":

        u_sett = await db.get_user_settings(
            user_id
        )

        joined = u_sett.get(
            "joined_date",
            "Unknown"
        )

        total_searches = u_sett.get(
            "total_searches",
            0
        )

        mode = u_sett.get(
            "search_mode",
            "default"
        ).title()

        stats_text = (
            f"📊 **𝗬𝗢𝗨𝗥 𝗣𝗘𝗥𝗦𝗢𝗡𝗔𝗟 𝗦𝗧𝗔𝗧𝗜𝗦𝗧𝗜𝗖𝗦:**\n\n"
            f"👤 **Name:** {callback.from_user.first_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"📅 **Joined On:** `{joined}`\n"
            f"🔍 **Total Searches:** `{total_searches}`\n"
            f"⚙️ **Search Mode:** `{mode}`\n\n"
            f"*(Thank you for using {bot_me.first_name}!)*"
        )

        await callback.message.edit_text(
            text=stats_text,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Profile",
                        callback_data="ui_profile_menu",
                        style=ButtonStyle.DANGER
                    )
                ]
            ])
        )


    # ==========================================
    # 📊 ADMIN USER STATS
    # ==========================================

    elif (
        target == "userstats"
        and user_id in Config.ADMINS
    ):

        total_users = await db.users.count_documents({})

        total_muted = await db.punishments.count_documents({
            "type": "mute"
        })

        total_banned = await db.punishments.count_documents({
            "type": "ban"
        })

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

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Back to Settings",
                    callback_data="ui_settings_menu",
                    style=ButtonStyle.DANGER
                )
            ]
        ])

        await callback.message.edit_text(
            stats_text,
            reply_markup=markup
        )


    # ==========================================
    # ⚙️ SETTINGS MENU
    # ==========================================

    elif target == "settings_menu":

        keyboard = [
            [
                InlineKeyboardButton(
                    text="👤 Personal Search Settings",
                    callback_data="tier_user_home",
                    style=ButtonStyle.PRIMARY
                )
            ]
        ]

        if await db.get_connected_groups(user_id):

            keyboard.append([
                InlineKeyboardButton(
                    text="🛡️ Manage My Linked Groups",
                    callback_data="tier_group_list",
                    style=ButtonStyle.PRIMARY
                )
            ])

        if user_id in Config.ADMINS:

            keyboard.append([
                InlineKeyboardButton(
                    "📊 System Stats Dashboard",
                    callback_data="stats_home",
                    style=ButtonStyle.PRIMARY
                )
            ])

            keyboard.append([
                InlineKeyboardButton(
                    "📈 User Stats Dashboard",
                    callback_data="ui_userstats",
                    style=ButtonStyle.PRIMARY
                )
            ])

            keyboard.append([
                InlineKeyboardButton(
                    text="👑 Bot Creator Control Panel",
                    callback_data="set_home",
                    style=ButtonStyle.SUCCESS
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "🔙 Back to Main Menu",
                callback_data="ui_back",
                style=ButtonStyle.DANGER
            )
        ])

        settings_text = (
            "🎛️ **Central Command Settings Hub:**\n"
            "Select the access layer tier you wish to inspect or modify:"
        )

        await callback.message.edit_text(
            text=settings_text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )


    # ==========================================
    # 🔌 EXISTING FEATURE BRIDGES
    # ==========================================

    elif target == "history":

        callback.message.from_user = callback.from_user
        callback.message.text = "/history"
        callback.message.command = ["history"]

        from plugins.advanced import view_search_history

        await view_search_history(
            client,
            callback.message
        )


    elif target == "request":

        callback.message.from_user = callback.from_user
        callback.message.text = "/request"
        callback.message.command = ["request"]

        from plugins.request import request_command

        await request_command(
            client,
            callback.message
        )


    elif target == "vip":

        callback.message.from_user = callback.from_user
        callback.message.text = "/checkvip"
        callback.message.command = ["checkvip"]

        from plugins.vip_system import check_vip_cmd

        await check_vip_cmd(
            client,
            callback.message
        )


    elif target == "buyvip":

        callback.message.from_user = callback.from_user
        callback.message.text = "/buyvip"
        callback.message.command = ["buyvip"]

        from plugins.vip_system import buy_vip_command

        await buy_vip_command(
            client,
            callback.message
        )


    await callback.answer()
