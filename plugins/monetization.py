import aiohttp
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from config import Config

logger = logging.getLogger(__name__)

# Premium / VIP In-Memory Register for demo/live tracking
VIP_USERS = set()
REFERRAL_POINTS = {}  # {user_id: points_count}
USER_REFERRER = {}    # {user_id: host_referrer_id}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    """
    Validates whether the user is joined to BOTH configured channels in FSUB_CHANNELS.
    Bypasses if user is premium/VIP or if no channels are configured.
    """
    if user_id in VIP_USERS:
        return True
        
    if not Config.FSUB_CHANNELS:
        return True

    # Check up to a maximum of two channels for a standard double FSub experience
    target_channels = Config.FSUB_CHANNELS[:2]
    for channel in target_channels:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status in ["kicked", "left"]:
                return False
        except UserNotParticipant:
            return False
        except Exception as e:
            logger.error(f"FSub channel membership lookup error for {channel}: {e}")
            # If the bot is not an admin, skip blocking to prevent lock-outs
            continue
    return True

async def get_shortened_url(long_url: str) -> str:
    """
    Contacts a shortening API dynamically to wrap files behind ads.
    Fails back elegantly if shorteners are disabled or request fails.
    """
    if not Config.USE_SHORTENERS:
        return long_url

    # Standard configuration parameters for shortener API integration
    api_endpoint = "https://gplinks.in/api"
    api_token = "5b8f729da248937bc38d15ff16ea49" # Example Token/Key
    
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
    if len(message.command) <= 1:
        return
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    
    # Check force joining of channels
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=f"https://t.me/{str(channel).replace('-100', '')}")])
        
        buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
        await message.reply_text(
            "🛑 **Lock Warning:**\n\n"
            "You must join our official distribution channels to unlock downloading capabilities. "
            "Click join buttons below, then verify to proceed.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Analyze start command parameters (Deep-links)
    if len(message.command) > 1:
        payload = message.command[1]
        
        # Referral Tracking
        if payload.startswith("ref_"):
            try:
                referrer_id = int(payload.split("_")[1])
                if referrer_id != user_id and user_id not in USER_REFERRER:
                    USER_REFERRER[user_id] = referrer_id
                    REFERRAL_POINTS[referrer_id] = REFERRAL_POINTS.get(referrer_id, 0) + 10  # 10 Points per invite
                    await message.reply_text(f"🎉 Welcome! You successfully registered via referral code from `{referrer_id}`.")
                    try:
                        await client.send_message(referrer_id, f"👤 **New Referral Recorded:**\nAn anonymous user registered using your link. You received **+10 Points**!")
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Referral processing exception: {e}")

        # Deep-link structural file distribution
        elif payload.startswith("file_"):
            file_id = payload.split("file_")[1]
            
            # If user has premium, skip intermediate shortening redirect sequences
            if user_id in VIP_USERS:
                await message.reply_cached_media(file_id, caption="✨ Premium delivery bypass complete! Here is your requested file.")
                return
                
            original_url = f"https://t.me/{client.me.username}?start=file_{file_id}"
            shortened_url = await get_shortened_url(original_url)
            
            # Custom Monetization message
            await message.reply_text(
                f"📥 **Your File Download Link is Ready:**\n\n"
                f"Click our secure links to download your file immediately. Premium users bypass this screen!\n\n"
                f"🔗 **Download Link:** {shortened_url}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(text="⚡ Click to Unlock", url=shortened_url)],
                    [InlineKeyboardButton(text="👑 Upgrade to Premium (Ad-free)", callback_data="upgrade_premium")]
                ])
            )
            return

    # Simple base private menu overview
    await message.reply_text(
        f"👋 **Greetings {username}!**\n\n"
        f"I am an advanced Multi-DB Auto-Filter Telegram application. "
        f"You can query titles inside groups or deep-link documents instantly.\n\n"
        f"👑 **Premium/VIP Status:** `{'Active' if user_id in VIP_USERS else 'Basic Standard'}`\n"
        f"⭐ **Referral Points:** `{REFERRAL_POINTS.get(user_id, 0)} pts`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(text="⭐ Invite Friends & Earn", callback_data="referral_menu")],
            [InlineKeyboardButton(text="👑 Premium Upgrade", callback_data="upgrade_premium")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^(referral_menu|upgrade_premium|activate_premium_demo)$"))
async def monetization_callbacks(client: Client, callback: Message):
    user_id = callback.from_user.id
    target = callback.data
    
    if target == "referral_menu":
        ref_link = f"https://t.me/{client.me.username}?start=ref_{user_id}"
        await callback.message.edit_text(
            f"👥 **Referral Hub:**\n\n"
            f"Invite files/movie downloaders to this bot and earn **10 points** per user. "
            f"Redeem points to purchase premium credits!\n\n"
            f"🔗 **Your Link:** `{ref_link}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Back", callback_data="monetization_home")]
            ])
        )
    elif target == "upgrade_premium":
        await callback.message.edit_text(
            f"👑 **Unlock Premium Priority:**\n\n"
            f"Benefits include:\n"
            f"• Completely ads-free results\n"
            f"• No shorteners / direct instant delivery\n"
            f"• Access to priority indexing servers\n\n"
            f"For trial purposes click below to enable premium simulation directly.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="⚡ Enable Trial Premium", callback_data="activate_premium_demo")],
                [InlineKeyboardButton(text="Back", callback_data="monetization_home")]
            ])
        )
    elif target == "activate_premium_demo":
        VIP_USERS.add(user_id)
        await callback.message.edit_text(
            "🎉 **Success!**\n\nYour account has been promoted to simulated VIP status inside Pyrogram's memory space.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="OK", callback_data="monetization_home")]
            ])
        )
