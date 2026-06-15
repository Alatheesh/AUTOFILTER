import aiohttp
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from config import Config

logger = logging.getLogger(__name__)

async def check_fsub(client: Client, user_id: int) -> bool:
    if not Config.FSUB_CHANNELS:
        return True
    
    for channel in Config.FSUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status in ["kicked", "banned", "left"]:
                return False
        except UserNotParticipant:
            return False
        except Exception as e:
            logger.error(f"FSub check error on channel {channel}: {e}")
            # If bot not admin in fsub channel, ignore fsub block to avoid locking out.
            continue
    return True

async def generate_short_link(long_url: str) -> str:
    # Dummy shortener logic to comply with requirements 
    # Usually you'd integrate API logic like bit.ly, ouo.io, etc.
    if not Config.USE_SHORTENERS:
        return long_url
        
    api_url = f"https://shortener-api.example.com/api?api=YOUR_API_KEY&url={long_url}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                if data.get("status") == "success":
                    return data.get("shortenedUrl")
    except Exception as e:
        logger.error(f"Shortener generation failed: {e}")
    return long_url

@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 1. Check FSub (Double FSub technically if length of array > 1)
    is_participant = await check_fsub(client, user_id)
    if not is_participant:
        buttons = []
        for ch in Config.FSUB_CHANNELS:
            buttons.append([InlineKeyboardButton(text="Join Channel", url=f"https://t.me/c/{str(ch).replace('-100', '')}")])
            
        await message.reply(
            "🛑 You must join our channels to use this bot!",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Payload Check (Referral system check or File link)
    if len(message.command) > 1:
        payload = message.command[1]
        
        # Referral Registration
        if payload.startswith("ref_"):
            referrer_id = payload.split("_")[1]
            await message.reply(f"You have been referred by {referrer_id}! Welcome to the VIP System.")
            # Code to increment referrals in a user_db would go here.
            
        # File Delivery Endpoint (Linked with search generation)
        elif payload.startswith("file_"):
            file_id = payload.split("file_")[1]
            await message.reply_cached_media(file_id, caption="Here is your requested file.")
            return

    # Base start message
    await message.reply(
        "Welcome to AutoFilter Bot! 🚀\n"
        "Send me any movie or file name to search across our massive multi-shard database."
    )

@Client.on_message(filters.command("premium"))
async def premium_info(client: Client, message: Message):
    # VIP / Premium info block
    if not Config.PREMIUM_TIER:
        await message.reply("Premium features are currently disabled.")
        return
        
    text = (
        "👑 **Premium Tier Benefits:**\n"
        "- Ads-free search\n"
        "- Bypass URL shorteners\n"
        "- Priority subtitle fetching\n"
        "- Ghost mode adjustments (Links stay alive longer)\n\n"
        "Contact Admins to upgrade!"
    )
    await message.reply(text)
