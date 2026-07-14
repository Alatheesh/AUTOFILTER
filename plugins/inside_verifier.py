import time
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ButtonStyle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)
VERIFIER_STATE = {}

@Client.on_message(filters.channel, group=4)
async def live_channel_listener(client: Client, message: Message):
    settings = await db.get_settings()
    if not settings.get("inside_enabled", False): return

    channels = settings.get("inside_channels", [])
    words = [w.lower().strip(',.') for w in settings.get("inside_words", [])]
    chat_id_str = str(message.chat.id)
    chat_username = f"@{message.chat.username}" if message.chat.username else ""

    if chat_id_str in channels or chat_username in channels:
        text = message.text or message.caption or ""
        
        if any(word in text.lower() for word in words):
            if message.chat.username: url = f"https://t.me/{message.chat.username}/{message.id}"
            else:
                private_id = str(message.chat.id).replace("-100", "")
                url = f"https://t.me/c/{private_id}/{message.id}"
            
            await db.update_settings({"inside_target_url": url})
            logger.info(f"✅ Cached new Help Us post to Database: {url}")

async def get_target_post(client: Client, settings: dict) -> str:
    return settings.get("inside_target_url")

@Client.on_callback_query(filters.regex(r"^help_us_menu$"))
async def help_us_menu(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    target_url = await get_target_post(client, settings)
    
    if not target_url:
        if callback.from_user.id in Config.ADMINS: return await callback.answer("⚠️ 𝐀𝐝𝐦𝐢𝐧: 𝐍𝐨 𝐭𝐚𝐫𝐠𝐞𝐭 𝐔𝐑𝐋 𝐜𝐚𝐜𝐡𝐞𝐝 𝐲𝐞𝐭. 𝐏𝐨𝐬𝐭 𝐚 𝐦𝐞𝐬𝐬𝐚𝐠𝐞 𝐰𝐢𝐭𝐡 𝐭𝐡𝐞 𝐬𝐞𝐜𝐫𝐞𝐭 𝐰𝐨𝐫𝐝𝐬.", show_alert=True)
        return await callback.answer("🙏 𝗧𝗵𝗮𝗻𝗸 𝘆𝗼𝘂 𝗳𝗼𝗿 𝘄𝗮𝗻𝘁𝗶𝗻𝗴 𝘁𝗼 𝗵𝗲𝗹𝗽! 𝗪𝗲 𝗱𝗼𝗻'𝘁 𝗵𝗮𝘃𝗲 𝗮𝗻 𝗮𝗰𝘁𝗶𝘃𝗲 𝘁𝗮𝘀𝗸 𝗿𝗶𝗴𝗵𝘁 𝗻𝗼𝘄.", show_alert=True)

    text = (
        "🤝 **𝗦𝘂𝗽𝗽𝗼𝗿𝘁 𝗢𝘂𝗿 𝗕𝗼𝘁!**\n\n"
        "𝖳𝗈 𝗄𝖾𝖾𝗉 𝗈𝗎𝗋 𝗌𝖾𝗋𝗏𝖾𝗋𝗌 𝗋𝗎𝗇𝗇𝗂𝗇𝗀 𝖺𝗇𝖽 𝗍𝗁𝖾 𝖻𝗈𝗍 𝖿𝗋𝖾𝖾, 𝗒𝗈𝗎 𝖼𝖺𝗇 𝖺𝗌𝗌𝗂𝗌𝗍 𝗎𝗌 𝖻𝗒 𝖿𝗈𝗋𝗐𝖺𝗋𝖽𝗂𝗇𝗀 𝖺 𝗌𝗉𝖾𝖼𝗂𝖿𝗂𝖼 𝗉𝗈𝗌𝗍 𝖿𝗋𝗈𝗆 𝗈𝗎𝗋 𝖼𝗁𝖺𝗇𝗇𝖾𝗅.\n\n"
        "𝖶𝗈𝗎𝗅𝖽 𝗒𝗈𝗎 𝖻𝖾 𝗐𝗂𝗅𝗅𝗂𝗇𝗀 𝗍𝗈 𝗁𝖾𝗅𝗉 𝗎𝗌 𝗈𝗎𝗍 𝗋𝗂𝗀𝗁𝗍 𝗇𝗈𝗐?"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 𝗜 𝘄𝗶𝗹𝗹 𝗵𝗲𝗹𝗽", callback_data="help_us_start", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="help_us_cancel", style=ButtonStyle.DANGER)]
    ])
    await callback.message.edit_text(text, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"^help_us_start$"))
async def help_us_start(client: Client, callback: CallbackQuery):
    settings = await db.get_settings()
    target_url = await get_target_post(client, settings)
    
    text = (
        "🙏 **𝗧𝗵𝗮𝗻𝗸 𝘆𝗼𝘂 𝗳𝗼𝗿 𝘆𝗼𝘂𝗿 𝘀𝘂𝗽𝗽𝗼𝗿𝘁!**\n\n"
        "𝖯𝗅𝖾𝖺𝗌𝖾 𝖿𝗈𝗅𝗅𝗈𝗐 𝗍𝗁𝖾𝗌𝖾 𝖾𝖺𝗌𝗒 𝗌𝗍𝖾𝗉𝗌:\n"
        "1️⃣ 𝖢𝗅𝗂𝖼𝗄 𝗍𝗁𝖾 𝖻𝗎𝗍𝗍𝗈𝗇 𝖻𝖾𝗅𝗈𝗐 𝗍𝗈 𝗀𝗈 𝗍𝗈 𝗈𝗎𝗋 𝖼𝗁𝖺𝗇𝗇𝖾𝗅.\n"
        "2️⃣ **𝗙𝗼𝗿𝘄𝗮𝗿𝗱 𝘁𝗵𝗮𝘁 𝗲𝘅𝗮𝗰𝘁 𝗽𝗼𝘀𝘁 𝗯𝗮𝗰𝗸 𝘁𝗼 𝗺𝗲 𝗵𝗲𝗿𝗲.**\n\n"
        "𝖨 𝖺𝗆 𝗐𝖺𝗂𝗍𝗂𝗇𝗀 𝖿𝗈𝗋 𝗒𝗈𝗎𝗋 𝖿𝗈𝗋𝗐𝖺𝗋𝖽𝖾𝖽 𝗆𝖾𝗌𝗌𝖺𝗀𝖾..."
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 𝗚𝗼 𝘁𝗼 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗣𝗼𝘀𝘁", url=target_url, style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="help_us_cancel", style=ButtonStyle.DANGER)]
    ])
    msg = await callback.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    VERIFIER_STATE[callback.from_user.id] = {"msg_id": msg.id, "timestamp": time.time()}

@Client.on_callback_query(filters.regex(r"^help_us_cancel$"))
async def help_us_cancel(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in VERIFIER_STATE: del VERIFIER_STATE[user_id]
    await callback.message.edit_text("❌ **𝐇𝐞𝐥𝐩 𝐚𝐜𝐭𝐢𝐨𝐧 𝐜𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝.**\n\n𝖭𝗈 𝗐𝗈𝗋𝗋𝗂𝖾𝗌! 𝖸𝗈𝗎 𝖼𝖺𝗇 𝖼𝗈𝗇𝗍𝗂𝗇𝗎𝖾 𝗎𝗌𝗂𝗇𝗀 𝗍𝗁𝖾 𝖻𝗈𝗍 𝗍𝗈 𝗋𝖾𝗊𝗎𝖾𝗌𝗍 𝖺𝗇𝖽 𝖽𝗈𝗐𝗇𝗅𝗈𝖺𝖽 𝗆𝗈𝗏𝗂𝖾𝗌 𝐚𝐬 𝐮𝐬𝐮𝐚𝐥.")

@Client.on_message(filters.private & filters.forwarded, group=-8)
async def catch_forwarded_verification(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in VERIFIER_STATE: raise ContinuePropagation 
        
    state = VERIFIER_STATE[user_id]
    prompt_msg_id = state["msg_id"]
    timestamp = state["timestamp"]
    
    if time.time() - timestamp > 172800:
        del VERIFIER_STATE[user_id]
        try: await message.delete()
        except Exception: pass
        expired_text = "⚠️ **𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐄𝐱𝐩𝐢𝐫𝐞𝐝.**\n\n𝐘𝐨𝐮𝐫 𝐡𝐞𝐥𝐩 𝐬𝐞𝐬𝐬𝐢𝐨𝐧 𝐭𝐢𝐦𝐞𝐝 𝐨𝐮𝐭. 𝐘𝐨𝐮 𝐜𝐚𝐧 𝐜𝐥𝐢𝐜𝐤 𝐭𝐡𝐞 '𝐇𝐞𝐥𝐩 𝐔𝐬' 𝐛𝐮𝐭𝐭𝐨𝐧 𝐚𝐠𝐚𝐢𝐧 𝐚𝐧𝐲𝐭𝐢𝐦𝐞!"
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, expired_text)
        except Exception: await message.reply_text(expired_text)
        raise StopPropagation
        
    settings = await db.get_settings()
    user_text = message.text or message.caption or ""
    words = [w.lower().strip(',.') for w in settings.get("inside_words", [])]
    
    try: await message.delete()
    except Exception: pass
    
    if any(w in user_text.lower() for w in words):
        del VERIFIER_STATE[user_id]
        await db.grant_verification_pass(user_id)
        
        success_text = (
            f"🎉 **𝗧𝗵𝗮𝗻𝗸 𝘆𝗼𝘂 𝘀𝗼 𝗺𝘂𝗰𝗵!**\n\n"
            f"𝖸𝗈𝗎𝗋 𝗌𝗎𝗉𝗉𝗈𝗋𝗍 𝗆𝖾𝖺𝗇𝗌 𝗍𝗁𝖾 𝗐𝗈𝗋𝗅𝖽 𝗍𝗈 𝗎𝗌 𝖺𝗇𝖽 𝗁𝖾𝗅𝗉𝗌 𝗄𝖾𝖾𝗉 𝗍𝗁𝗂𝗌 𝖻𝗈𝗍 𝖺𝗅𝗂𝗏𝖾.\n\n"
            f"**✅ 𝗥𝗲𝘄𝗮𝗿𝗱 𝗨𝗻𝗹𝗼𝗰𝗸𝗲𝗱:** 𝖸𝗈𝗎 𝗇𝗈𝗐 𝗁𝖺𝗏𝖾 𝗍𝖾𝗆𝗉𝗈𝗋𝖺𝗋𝗒 𝗎𝗇𝗅𝗂𝗆𝗂𝗍𝖾𝖽 𝖺𝖼𝖼𝖾𝗌𝗌 𝗍𝗈 𝖽𝗂𝗋𝖾𝖼𝗍 𝖿𝗂𝗅𝖾𝗌!\n\n"
            f"𝖤𝗇𝗃𝗈𝗒 𝗒𝗈𝗎𝗋 𝗆𝗈𝗏𝗂𝖾𝗌! 🍿"
        )
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
        except Exception: await message.reply_text(success_text)
        
    else:
        target_url = settings.get("inside_target_url", "")
        fail_text = (
            f"❌ **𝐓𝐡𝐚𝐭 𝐰𝐚𝐬𝐧'𝐭 𝐪𝐮𝐢𝐭𝐞 𝐫𝐢𝐠𝐡𝐭.**\n\n"
            f"𝐏𝐥𝐞𝐚𝐬𝐞 𝐦𝐚𝐤𝐞 𝐬𝐮𝐫𝐞 𝐲𝐨𝐮 𝐟𝐨𝐫𝐰𝐚𝐫𝐝 𝐭𝐡𝐞 𝐞𝐱𝐚𝐜𝐭 𝐩𝐨𝐬𝐭 𝐟𝐫𝐨𝐦 𝐭𝐡𝐞 𝐜𝐡𝐚𝐧𝐧𝐞𝐥 𝐝𝐢𝐫𝐞𝐜𝐭𝐥𝐲 𝐭𝐨 𝐦𝐞.\n\n"
            f"👉 **𝐓𝐫𝐲 𝐚𝐠𝐚𝐢𝐧 𝐮𝐬𝐢𝐧𝐠 𝐭𝐡𝐢𝐬 𝐥𝐢𝐧𝐤:** {target_url}"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 𝗢𝗽𝗲𝗻 𝗖𝗼𝗿𝗿𝗲𝗰𝘁 𝗣𝗼𝘀𝘁", url=target_url, style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="help_us_cancel", style=ButtonStyle.DANGER)]
        ]) if target_url else None
        
        try: await client.edit_message_text(message.chat.id, prompt_msg_id, fail_text, reply_markup=markup)
        except Exception: await message.reply_text(fail_text, reply_markup=markup)
        
    raise StopPropagation
