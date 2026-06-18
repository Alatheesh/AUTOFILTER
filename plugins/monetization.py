import time
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

# Dictionary to hold the last caution message per user for cleanup
LAST_CAUTION_MSG = {}

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

async def get_shortened_url(long_url: str) -> tuple[str, str]:
    settings = await db.get_settings()
    if not settings.get("shortener_enabled", False): return long_url, ""
    api_endpoint = settings.get("shortener_url", "https://gplinks.in/api")
    api_token = settings.get("shortener_api", "")
    if not api_token: return long_url, "No API Token Configured"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_endpoint}?api={api_token}&url={long_url}") as response:
                if response.status == 200:
                    data = await response.json()
                    short_url = data.get("shortenedUrl", "")
                    if short_url and isinstance(short_url, str) and short_url.startswith("http"): 
                        return short_url, ""
                return long_url, f"API Response Error: HTTP {response.status}"
    except Exception as e: 
        logger.error(f"Shortener API failed: {e}")
        return long_url, str(e)
    return long_url, "Unknown Error"

async def execute_file_delivery(client: Client, chat_id: int, user_id: int, file_id: str):
    """Sends the file, handles caution cleanup, and sets self-destruct timers."""
    settings = await db.get_settings()
    
    try:
        sent_file = await client.send_cached_media(chat_id=chat_id, file_id=file_id, caption="✨ Here is your requested file.")
    except Exception as send_err:
        await client.send_message(chat_id, f"❌ **Delivery Error:** Telegram rejected the file.\n`{str(send_err)}`")
        return

    # AUTO DELETE GHOST MODE LOGIC
    if settings.get("file_delete_enabled", False):
        del_mins = settings.get("file_delete_time", 10)
        
        # 1. Delete old caution message if it exists
        if user_id in LAST_CAUTION_MSG:
            old = LAST_CAUTION_MSG[user_id]
            try: await client.delete_messages(old['chat'], old['msg'])
            except: pass

        # 2. Send the new caution message
        caution_msg = await client.send_message(
            chat_id,
            f"⏳ **Caution:** This file will be automatically deleted in **{del_mins} minutes** to protect against copyright flags.",
            reply_to_message_id=sent_file.id
        )
        LAST_CAUTION_MSG[user_id] = {'chat': chat_id, 'msg': caution_msg.id}

        # 3. Schedule the deletions using Ghost Tasks
        from plugins.advanced import trigger_ghost_self_destruct
        trigger_ghost_self_destruct(client, chat_id, sent_file.id, del_mins * 60)
        trigger_ghost_self_destruct(client, chat_id, caution_msg.id, del_mins * 60)


@Client.on_message(filters.command("start") & filters.private, group=1)
async def monetization_start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    settings = await db.get_settings()

    if len(message.command) <= 1: 
        if settings.get("inside_enabled", False) and settings.get("inside_placement", "movie").lower() == "welcome" and user_id not in VIP_USERS:
            user_data = await db.get_user_settings(user_id)
            if time.time() > user_data.get("inside_pass_expires", 0):
                from plugins.inside_verifier import get_target_post
                target_url = await get_target_post(client, settings)
                if target_url:
                    inside_times = settings.get("inside_times", 5) or 1
                    hours_per_pass = 24 / inside_times
                    await message.reply_text(
                        f"🔒 **Welcome! Security Verification Required**\n\n"
                        f"To prove you are human and unlock this bot for the next **{hours_per_pass:.1f} Hours**, please complete this task:\n\n"
                        f"1️⃣ Click the button below to go to our channel.\n"
                        f"2️⃣ Find the latest post containing our secret words.\n"
                        f"3️⃣ **Forward that exact message directly to me here!**",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                    )
                    return 
                else:
                    if user_id in Config.ADMINS: await message.reply_text("⚠️ **ADMIN DEBUG:** Inside Feature ON for Welcome, but MongoDB cache is empty. Post a new ad!")
                    return 

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
        raise ContinuePropagation

    is_joined = await check_double_fsub(client, user_id)
    if not is_joined: return await message.reply_text("🛑 You must join the updates channel first. Type /start to see the links.")

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
                
            if settings.get("inside_enabled", False) and settings.get("inside_placement", "movie").lower() == "movie" and user_id not in VIP_USERS:
                user_data = await db.get_user_settings(user_id)
                if time.time() > user_data.get("inside_pass_expires", 0):
                    from plugins.inside_verifier import get_target_post
                    target_url = await get_target_post(client, settings)
                    if target_url:
                        inside_times = settings.get("inside_times", 5) or 1
                        hours_per_pass = 24 / inside_times
                        return await message.reply_text(
                            f"🔒 **Security Verification Required!**\n\n"
                            f"To prove you are human and unlock **UNLIMITED** movie downloads for the next **{hours_per_pass:.1f} Hours**, please complete this task:\n\n"
                            f"1️⃣ Click the button below to go to our channel.\n"
                            f"2️⃣ Find the latest post containing our secret words.\n"
                            f"3️⃣ **Forward that exact message directly to me here!**",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Go to Channel Post", url=target_url)]])
                        )
                    else:
                        if user_id in Config.ADMINS: await message.reply_text("⚠️ **ADMIN DEBUG:** Inside Feature ON for Movies, but MongoDB cache is empty. Post a new ad in your channel!")
                        else: await message.reply_text("⏳ Verification system starting up. Try again later.")
                        return
                
            file_id = file_data.get("file_id")
            
            # DIRECT DELIVERY FOR VIP OR NO SHORTENER
            if user_id in VIP_USERS or not settings.get("shortener_enabled", False):
                return await execute_file_delivery(client, message.chat.id, user_id, file_id)

            me = await client.get_me()
            original_url = f"https://t.me/{me.username}?start=verify_{db_id}"
            
            # SHORTENER API CALL (WITH ERROR CATCHER)
            shortened_url, err_msg = await get_shortened_url(original_url)

            # FALLBACK IF SHORTENER FAILS
            if not shortened_url or not shortened_url.startswith("http") or shortened_url == original_url:
                if Config.ADMINS:
                    try: await client.send_message(Config.ADMINS[0], f"⚠️ **Shortener API Failed!**\n\nFailed to shorten link for file `{db_id}`.\n**Reason:** `{err_msg}`\n\n*The bot successfully bypassed the shortener and sent the file directly to the user to maintain user experience.*")
                    except: pass
                # Send directly to the user without breaking
                return await execute_file_delivery(client, message.chat.id, user_id, file_id)

            await message.reply_text(
                f"📥 **Your File Download Link is Ready:**\n\n🔗 **Download Link:** {shortened_url}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="⚡ Click to Unlock", url=shortened_url)]])
            )
        except Exception as e: await message.reply_text(f"❌ **System Crash:** Code broke before sending.\n`{str(e)}`")
        return

    elif payload.startswith("verify_"):
        try:
            db_id = payload.split("verify_")[1]
            file_data = await db.get_file(db_id)
            if not file_data: return await message.reply_text("❌ **Error:** File not found.")
            file_id = file_data.get("file_id")
            # Send file and run ghost triggers
            await execute_file_delivery(client, message.chat.id, user_id, file_id)
        except Exception as e: await message.reply_text(f"❌ **System Crash:**\n`{str(e)}`")
        return

@Client.on_callback_query(filters.regex(r"^(referral_menu|upgrade_premium|activate_premium_demo|check_membership_retry)$"))
async def monetization_callbacks(client: Client, callback: CallbackQuery):
    target = callback.data
    user_id = callback.from_user.id
    if target == "check_membership_retry":
        if await check_double_fsub(client, user_id): await callback.message.edit_text("✅ Verification successful! You can now request your files again.")
        else: await callback.answer("❌ You haven't joined all channels yet!", show_alert=True)
        return
    if target == "activate_premium_demo":
        VIP_USERS.add(user_id)
        await callback.message.edit_text("🎉 **Success!** VIP status active.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("OK", callback_data="monetization_home")]]))

# -----------------------------------------------------
# 🔥 HYBRID DIRECT FILE BUTTON LISTENER
# -----------------------------------------------------
@Client.on_callback_query(filters.regex(r"^sendfile_(.+)"))
async def direct_send_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    db_id = callback.data.split("_")[1]

    # Verify FSub (Since they bypassed /start)
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
        await callback.message.reply_text("🛑 **Lock Warning:**\nYou must join our official distribution channels before downloading files.", reply_markup=InlineKeyboardMarkup(buttons))
        return await callback.answer("You must join the channels first!", show_alert=True)

    file_data = await db.get_file(db_id)
    if not file_data:
        return await callback.answer("❌ Error: File not found in database.", show_alert=True)

    await callback.answer("Sending file...", show_alert=False)
    # Send file and run ghost triggers
    await execute_file_delivery(client, chat_id, user_id, file_data.get("file_id"))
