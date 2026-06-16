import time
import aiohttp
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserNotParticipant
from config import Config
from database.multi_db import db

logger = logging.getLogger(__name__)

VIP_USERS = set()
REFERRAL_POINTS = {}
USER_REFERRER = {}

async def check_double_fsub(client: Client, user_id: int) -> bool:
    if user_id in VIP_USERS: return True
    if not Config.FSUB_CHANNELS: return True
    for channel in Config.FSUB_CHANNELS[:2]:
        try:
            member = await client.get_chat_member(channel, user_id)
            if member.status in ["kicked", "left"]: return False
        except UserNotParticipant: return False
        except Exception: continue
    return True

async def get_shortened_url(long_url: str) -> str:
    settings = await db.get_settings()
    if not settings.get("shortener_enabled", False): return long_url
    api_endpoint = settings.get("shortener_url", "https://gplinks.in/api")
    api_token = settings.get("shortener_api", "")
    if not api_token: return long_url
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_endpoint}?api={api_token}&url={long_url}") as response:
                if response.status == 200:
                    data = await response.json()
                    short_url = data.get("shortenedUrl", "")
                    if short_url and isinstance(short_url, str) and short_url.startswith("http"):
                        return short_url
    except Exception as e: logger.error(f"Shortener API failed: {e}")
    return long_url

@Client.on_message(filters.command("start") & filters.private, group=1)
async def monetization_start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    settings = await db.get_settings()

    # --- INSIDE FEATURE: WELCOME SCREEN PLACEMENT ---
    if len(message.command) <= 1: 
        if settings.get("inside_enabled", False) and settings.get("inside_placement", "welcome") == "welcome" and user_id not in VIP_USERS:
            user_data = await db.get_user_settings(user_id)
            if time.time() > user_data.get("inside_pass_expires", 0):
                from plugins.inside_verifier import get_target_post
                target_url = await get_target_post(client, settings)
                if target_url:
                    inside_times = settings.get("inside_times", 5) or 1
                    hours_per_pass = 24 / inside_times
                    await message.reply_text(
                        f"🔒 **Welcome! Security Verification Required**\n\n"
                        f"To prove you are human and unlock this bot for the next **{hours_per_pass:.1f} Hours**, please complete this quick task:\n\n"
                        f"1️⃣ Click the button below to go to our channel.\n"
                        f"2️⃣ Find the latest post containing our secret words.\n"
                        f"3️⃣ **Forward that exact message directly to me here!**",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                    )
                    raise StopPropagation # Stops the normal welcome menu from loading!
        
        is_joined = await check_double_fsub(client, user_id)
        if not is_joined:
            buttons = []
            for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
                try: chat = await client.get_chat(channel)
                except Exception: continue
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
                buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
            buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
            await message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels.", reply_markup=InlineKeyboardMarkup(buttons))
            raise StopPropagation
            
        raise ContinuePropagation

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        await message.reply_text("🛑 You must join the updates channel first. Type /start to see the links.")
        return

    payload = message.command[1]

    if payload.startswith("ref_"):
        try:
            referrer_id = int(payload.split("_")[1])
            if referrer_id != user_id and user_id not in USER_REFERRER:
                USER_REFERRER[user_id] = referrer_id
                REFERRAL_POINTS[referrer_id] = REFERRAL_POINTS.get(referrer_id, 0) + 10
                await message.reply_text(f"🎉 Welcome! Registered via `{referrer_id}`.")
        except Exception: pass

    elif payload.startswith("getfile_"):
        try:
            db_id = payload.split("getfile_")[1]
            file_data = await db.get_file(db_id)
            if not file_data: return await message.reply_text("❌ **Error:** File not found in database.")
            
            # --- INSIDE FEATURE: MOVIE UNLOCK PLACEMENT ---
            if settings.get("inside_enabled", False) and settings.get("inside_placement", "movie") == "movie" and user_id not in VIP_USERS:
                user_data = await db.get_user_settings(user_id)
                if time.time() > user_data.get("inside_pass_expires", 0):
                    from plugins.inside_verifier import get_target_post
                    target_url = await get_target_post(client, settings)
                    if target_url:
                        inside_times = settings.get("inside_times", 5) or 1
                        hours_per_pass = 24 / inside_times
                        return await message.reply_text(
                            f"🔒 **Security Verification Required!**\n\n"
                            f"To prove you are human and unlock **UNLIMITED** movie downloads for the next **{hours_per_pass:.1f} Hours**, please complete this quick task:\n\n"
                            f"1️⃣ Click the button below to go to our channel.\n"
                            f"2️⃣ Find the latest post containing our secret words.\n"
                            f"3️⃣ **Forward that exact message directly to me here!**",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                        )
            # ----------------------------------------------
                
            file_id = file_data.get("file_id")
            
            if user_id in VIP_USERS or not settings.get("shortener_enabled", False):
                try: await client.send_cached_media(chat_id=message.chat.id, file_id=file_id, caption="✨ Here is your requested file.")
                except Exception as send_err: await message.reply_text(f"❌ **Delivery Error:** Telegram rejected the file.\n`{str(send_err)}`")
                return

            me = await client.get_me()
            original_url = f"https://t.me/{me.username}?start=verify_{db_id}"
            shortened_url = await get_shortened_url(original_url)
            if not shortened_url or not shortened_url.startswith("http"): shortened_url = original_url

            await message.reply_text(
                f"📥 **Your File Download Link is Ready:**\n\n🔗 **Download Link:** {shortened_url}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="⚡ Click to Unlock", url=shortened_url)]])
            )
        except Exception as e:
            await message.reply_text(f"❌ **System Crash:** Code broke before sending.\n`{str(e)}`")
        return

    elif payload.startswith("verify_"):
        try:
            db_id = payload.split("verify_")[1]
            file_data = await db.get_file(db_id)
            if not file_data: return await message.reply_text("❌ **Error:** File not found in database.")
                
            file_id = file_data.get("file_id")
            try: await client.send_cached_media(chat_id=message.chat.id, file_id=file_id, caption="✨ Premium delivery complete! Here is your requested file.")
            except Exception as send_err: await message.reply_text(f"❌ **Delivery Error:** Telegram rejected the file.\n`{str(send_err)}`")
        except Exception as e:
            await message.reply_text(f"❌ **System Crash:**\n`{str(e)}`")
        return

@Client.on_callback_query(filters.regex(r"^(referral_menu|upgrade_premium|activate_premium_demo|check_membership_retry)$"))
async def monetization_callbacks(client: Client, callback: CallbackQuery):
    target = callback.data
    user_id = callback.from_user.id

    if target == "check_membership_retry":
        if await check_double_fsub(client, user_id):
            await callback.message.edit_text("✅ Verification successful! You can now request your files again.")
        else: await callback.answer("❌ You haven't joined all channels yet!", show_alert=True)
        return

    if target == "activate_premium_demo":
        VIP_USERS.add(user_id)
        await callback.message.edit_text("🎉 **Success!** VIP status active.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("OK", callback_data="monetization_home")]]))
