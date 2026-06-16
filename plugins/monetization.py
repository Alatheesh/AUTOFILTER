import aiohttp
import logging
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserNotParticipant
from config import Config
from database.multi_db import db

logger = logging.getLogger(__name__)

VIP_USERS = set()
REFERRAL_POINTS = {}
USER_REFERRER = {}

# Memory Tracker for the Returning User History wipe warning
WARNED_USERS = set()

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
    except Exception as e: 
        logger.error(f"Shortener API failed: {e}")
        
    return long_url

@Client.on_message(filters.command("start") & filters.private, group=1)
async def monetization_start_handler(client: Client, message: Message):
    user_id = message.from_user.id

    # --- LATHU'S RETURNING USER DETECTOR ---
    if user_id not in WARNED_USERS:
        WARNED_USERS.add(user_id)
        if message.id > 15:
            warning_text = (
                "⚠️ **Notice for Returning Users:**\n\n"
                "We have completely upgraded our bot engine to a faster, safer database! "
                "Because of this, any old download buttons currently visible in this chat will no longer work.\n\n"
                "🧹 **To get the best experience, please clear this chat history and search for your movies again!**"
            )
            await message.reply_text(warning_text)
    # ---------------------------------------

    # THE FIX: Tell Pyrogram to pass normal /start messages to ui_menus.py
    if len(message.command) <= 1: 
        raise ContinuePropagation

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined:
        buttons = []
        for idx, channel in enumerate(Config.FSUB_CHANNELS[:2], start=1):
            try:
                chat = await client.get_chat(channel)
                invite_link = chat.invite_link if chat.invite_link else await client.export_chat_invite_link(channel)
            except Exception: invite_link = "https://t.me/telegram"
            buttons.append([InlineKeyboardButton(text=f"Join Channel #{idx}", url=invite_link)])
        
        buttons.append([InlineKeyboardButton(text="🔄 Request Verification", callback_data="check_membership_retry")])
        await message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels.", reply_markup=InlineKeyboardMarkup(buttons))
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

    # --- MAIN DOWNLOAD PAYLOAD ---
    elif payload.startswith("getfile_"):
        try:
            db_id = payload.split("getfile_")[1]
            file_data = await db.get_file(db_id)
            
            if not file_data:
                return await message.reply_text("❌ **Error:** File not found in database. It may have been deleted.")
                
            file_id = file_data.get("file_id")
            settings = await db.get_settings()
            
            if user_id in VIP_USERS or not settings.get("shortener_enabled", False):
                try: 
                    await client.send_cached_media(chat_id=message.chat.id, file_id=file_id, caption="✨ Here is your requested file.")
                except Exception as send_err: 
                    await message.reply_text(f"❌ **Delivery Error:** Telegram rejected the file.\n`{str(send_err)}`")
                return

            me = await client.get_me()
            original_url = f"https://t.me/{me.username}?start=verify_{db_id}"
            shortened_url = await get_shortened_url(original_url)
            
            if not shortened_url or not shortened_url.startswith("http"):
                shortened_url = original_url

            await message.reply_text(
                f"📥 **Your File Download Link is Ready:**\n\n🔗 **Download Link:** {shortened_url}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="⚡ Click to Unlock", url=shortened_url)]])
            )
        except Exception as e:
            await message.reply_text(f"❌ **System Crash:** Code broke before sending.\n`{str(e)}`")
        return

    # --- VERIFICATION AFTER SHORTLINK PAYLOAD ---
    elif payload.startswith("verify_"):
        try:
            db_id = payload.split("verify_")[1]
            file_data = await db.get_file(db_id)
            
            if not file_data:
                return await message.reply_text("❌ **Error:** File not found in database.")
                
            file_id = file_data.get("file_id")
            try: 
                await client.send_cached_media(chat_id=message.chat.id, file_id=file_id, caption="✨ Premium delivery complete! Here is your requested file.")
            except Exception as send_err: 
                await message.reply_text(f"❌ **Delivery Error:** Telegram rejected the file.\n`{str(send_err)}`")
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
