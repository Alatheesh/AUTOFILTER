import aiohttp
import logging
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from config import Config

logger = logging.getLogger(__name__)

VIP_USERS = set()
REFERRAL_POINTS = {}
USER_REFERRER = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    logger.info(f"[DEBUG] Starting Force Sub check for User: {user_id}")
    
    if user_id in VIP_USERS:
        return True
        
    if not Config.FSUB_CHANNELS:
        logger.info("[DEBUG] No FSUB_CHANNELS configured in secrets. Skipping check.")
        return True

    target_channels = Config.FSUB_CHANNELS[:2]
    for channel in target_channels:
        logger.info(f"[DEBUG] Verifying membership in channel ID: {channel}")
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status in ["kicked", "left"]:
                return False
        except UserNotParticipant:
            logger.info(f"[DEBUG] User {user_id} has not joined {channel}.")
            return False
        except ChatAdminRequired:
            logger.error(f"[CRITICAL] Bot is NOT an Admin in channel {channel}! I cannot check users.")
            # We return False so you actually see the error happening instead of freezing
            return False
        except Exception as e:
            logger.error(f"[CRITICAL] FSub connection error for {channel}: {e}")
            return False
            
    logger.info("[DEBUG] Force Sub check passed successfully.")
    return True

async def get_shortened_url(long_url: str) -> str:
    if not Config.USE_SHORTENERS:
        return long_url
    api_endpoint = "https://gplinks.in/api"
    api_token = "5b8f729da248937bc38d15ff16ea49" 
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_endpoint}?api={api_token}&url={long_url}") as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success" or "shortenedUrl" in data:
                        return data.get("shortenedUrl", long_url)
    except Exception as e:
        logger.error(f"Failed to generate monetized shortlink: {e}")
    return long_url

@Client.on_message(filters.command("start") & filters.private)
async def monetization_start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    logger.info(f"[DEBUG] ====== /START COMMAND RECEIVED FROM {user_id} ======")
    logger.info(f"[DEBUG] Full Command Text: {message.text}")
    
    try:
        # 1. Force Sub Check
        is_joined = await check_double_fsub(client, user_id)
        if not is_joined:
            logger.info("[DEBUG] Sending Force Sub Lock Screen to user.")
            buttons = []
            for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=f"https://t.me/{str(channel).replace('-100', '')}")])
            buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
            
            await message.reply_text(
                "🛑 **Lock Warning:**\n\nYou must join our official distribution channels to unlock downloading capabilities.\n\n"
                "*(Note: If you are the owner and seeing this, ensure the bot is an ADMIN in your channels!)*",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return

        # 2. Deep-Links Check
        if len(message.command) > 1:
            logger.info("[DEBUG] Deep link detected. Processing payload...")
            payload = message.command[1]
            if payload.startswith("ref_"):
                pass # Referral logic hidden for brevity
            elif payload.startswith("file_"):
                pass # File logic hidden for brevity
            return

        # 3. Bridge to Main Menu
        logger.info("[DEBUG] Normal /start. Passing to UI Menu (ui_menus.py)...")
        raise ContinuePropagation

    except ContinuePropagation:
        logger.info("[DEBUG] Bridge activated successfully.")
        raise
    except Exception as e:
        logger.error(f"[FATAL ERROR] The bot crashed during /start: {e}")
        await message.reply_text(f"⚠️ **System Crash Detected:**\n`{e}`\n\nCheck Hugging Face Logs immediately.")


@Client.on_callback_query(filters.regex(r"^(referral_menu|upgrade_premium|activate_premium_demo)$"))
async def monetization_callbacks(client: Client, callback: Message):
    pass # Keep your existing callback code here if needed
