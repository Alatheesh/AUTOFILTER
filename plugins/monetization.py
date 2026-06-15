import aiohttp
import logging
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant
from config import Config

logger = logging.getLogger(__name__)

VIP_USERS = set()
REFERRAL_POINTS = {}
USER_REFERRER = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    if user_id in VIP_USERS:
        return True
    if not Config.FSUB_CHANNELS:
        return True

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
            continue
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

@Client.on_message(filters.command("start") & filters.private, group=1) # Set to group 1
async def monetization_start_handler(client: Client, message: Message):
    # If there is NO deep-link data, stop immediately (don't interfere with UI menu)
    if len(message.command) <= 1:
        return
        
    user_id = message.from_user.id
    # ... keep the rest of your existing logic here (FSub check, File distribution, etc)
    # The logic you have for file_id and ref_ is perfect.
    
    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            try:
                # Dynamically fetch the real invite link for private channels
                chat = await client.get_chat(channel)
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
            except Exception as e:
                logger.error(f"Could not get invite link for {channel}: {e}")
                invite_link = "https://t.me/telegram" # Safe fallback to prevent crashes

            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
        
        buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
        await message.reply_text(
            "🛑 **Lock Warning:**\n\n"
            "You must join our official distribution channels to unlock downloading capabilities.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    payload = message.command[1]
    
    if payload.startswith("ref_"):
        try:
            referrer_id = int(payload.split("_")[1])
            if referrer_id != user_id and user_id not in USER_REFERRER:
                USER_REFERRER[user_id] = referrer_id
                REFERRAL_POINTS[referrer_id] = REFERRAL_POINTS.get(referrer_id, 0) + 10
                await message.reply_text(f"🎉 Welcome! You successfully registered via referral code from `{referrer_id}`.")
                try:
                    await client.send_message(referrer_id, f"👤 **New Referral Recorded:**\nAn anonymous user registered using your link. You received **+10 Points**!")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Referral processing exception: {e}")

    elif payload.startswith("file_"):
        file_id = payload.split("file_")[1]
        
        if user_id in VIP_USERS:
            await message.reply_cached_media(file_id, caption="✨ Premium delivery bypass complete! Here is your requested file.")
            return
            
        original_url = f"https://t.me/{client.me.username}?start=file_{file_id}"
        shortened_url = await get_shortened_url(original_url)
        
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

@Client.on_callback_query(filters.regex(r"^(referral_menu|upgrade_premium|activate_premium_demo)$"))
async def monetization_callbacks(client: Client, callback: Message):
    user_id = callback.from_user.id
    target = callback.data
    
    if target == "referral_menu":
        ref_link = f"https://t.me/{client.me.username}?start=ref_{user_id}"
        await callback.message.edit_text(
            f"👥 **Referral Hub:**\n\n"
            f"Invite friends and earn **10 points** per user.\n\n"
            f"🔗 **Your Link:** `{ref_link}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="monetization_home")]])
        )
    elif target == "upgrade_premium":
        await callback.message.edit_text(
            f"👑 **Unlock Premium Priority:**\n\n"
            f"Benefits include:\n"
            f"• Completely ads-free results\n"
            f"• Direct instant delivery\n\n"
            f"Click below to enable premium simulation.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(text="⚡ Enable Trial Premium", callback_data="activate_premium_demo")],
                [InlineKeyboardButton(text="Back", callback_data="monetization_home")]
            ])
        )
    elif target == "activate_premium_demo":
        VIP_USERS.add(user_id)
        await callback.message.edit_text(
            "🎉 **Success!**\n\nYour account has been promoted to VIP status.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("OK", callback_data="monetization_home")]])
        )
