import asyncio
import random
import time
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ChatType, ChatMemberStatus, ChatMembersFilter, ButtonStyle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

CODE_STICKERS = [
    "CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE",
    "CAACAgIAAxkBAAERavVqNXpmmnxWeKfo-qv-kP8WdLuqkwACShcAAutrqUl9AevFXbjHDzwE",
    "CAACAgEAAxkBAAERavFqNXnOCL7UtEeSAe3-1MHnnBpLPAACMQIAAoKgIEQHCzBVrLHGhzwE"
]

WAITING_FOR_CONNECTION = {}

async def process_connect(client: Client, message: Message, user_id: int, target_chat_input: str, prompt_msg_id: int = None):
    try: target_chat = int(target_chat_input)
    except ValueError: target_chat = target_chat_input 
        
    try:
        chat = await client.get_chat(target_chat)
        target_chat_id = chat.id
        chat_title = chat.title
    except Exception as e:
        text = f"❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐂𝐨𝐮𝐥𝐝 𝐧𝐨𝐭 𝐟𝐢𝐧𝐝 𝐭𝐡𝐚𝐭 𝐠𝐫𝐨𝐮𝐩. 𝐌𝐚𝐤𝐞 𝐬𝐮𝐫𝐞 𝐈 𝐚𝐦 𝐚𝐝𝐝𝐞𝐝 𝐭𝐨 𝐢𝐭 𝐚𝐬 𝐚𝐧 𝐀𝐝𝐦𝐢𝐧 𝐟𝐢𝐫𝐬𝐭!\n`{e}`"
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    try:
        user_member = await client.get_chat_member(target_chat_id, user_id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            text = "🛑 𝐘𝐨𝐮 𝐝𝐨𝐧'𝐭 𝐡𝐚𝐯𝐞 𝐞𝐧𝐨𝐮𝐠𝐡 𝐩𝐞𝐫𝐦𝐢𝐬𝐬𝐢𝐨𝐧𝐬 𝐭𝐨 𝐜𝐨𝐧𝐧𝐞𝐜𝐭 𝐭𝐡𝐢𝐬 𝐛𝐨𝐭 𝐭𝐨 𝐭𝐡𝐞 𝐠𝐫𝐨𝐮𝐩."
            return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)
    except Exception:
        text = "🛑 𝐘𝐨𝐮 𝐝𝐨𝐧'𝐭 𝐡𝐚𝐯𝐞 𝐞𝐧𝐨𝐮𝐠𝐡 𝐩𝐞𝐫𝐦𝐢𝐬𝐬𝐢𝐨𝐧𝐬 𝐭𝐨 𝐜𝐨𝐧𝐧𝐞𝐜𝐭 𝐭𝐡𝐢𝐬 𝐛𝐨𝐭 𝐭𝐨 𝐭𝐡𝐞 𝐠𝐫𝐨𝐮𝐩."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    try:
        me = await client.get_me()
        bot_member = await client.get_chat_member(target_chat_id, me.id)
        if not bot_member.privileges or not bot_member.privileges.can_delete_messages:
            text = "❌ **𝐁𝐨𝐭 𝐏𝐞𝐫𝐦𝐢𝐬𝐬𝐢𝐨𝐧 𝐄𝐫𝐫𝐨𝐫:** 𝐈 𝐦𝐮𝐬𝐭 𝐛𝐞 𝐚𝐧 𝐀𝐝𝐦𝐢𝐧 𝐰𝐢𝐭𝐡 `𝐃𝐞𝐥𝐞𝐭𝐞 𝐌𝐞𝐬𝐬𝐚𝐠𝐞𝐬` 𝐫𝐢𝐠𝐡𝐭𝐬 𝐭𝐨 𝐜𝐨𝐧𝐧𝐞𝐜𝐭!"
            return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)
    except Exception:
        text = "❌ 𝐂𝐨𝐮𝐥𝐝 𝐧𝐨𝐭 𝐯𝐞𝐫𝐢𝐟𝐲 𝐦𝐲 𝐩𝐞𝐫𝐦𝐢𝐬𝐬𝐢𝐨𝐧𝐬. 𝐄𝐧𝐬𝐮𝐫𝐞 𝐈 𝐚𝐦 𝐚𝐧 𝐚𝐝𝐦𝐢𝐧 𝐢𝐧 𝐭𝐡𝐞 𝐠𝐫𝐨𝐮𝐩."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    if connected_by:
        text = "⚠️ 𝐓𝐡𝐢𝐬 𝐠𝐫𝐨𝐮𝐩 𝐢𝐬 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐜𝐨𝐧𝐧𝐞𝐜𝐭𝐞𝐝 𝐛𝐲 𝐲𝐨𝐮!" if connected_by == user_id else "⚠️ 𝐓𝐡𝐢𝐬 𝐠𝐫𝐨𝐮𝐩 𝐢𝐬 𝐚𝐥𝐫𝐞𝐚𝐝𝐲 𝐜𝐨𝐧𝐧𝐞𝐜𝐭𝐞𝐝 𝐭𝐨 𝐭𝐡𝐞 𝐝𝐚𝐭𝐚𝐛𝐚𝐬𝐞 𝐛𝐲 𝐚𝐧𝐨𝐭𝐡𝐞𝐫 𝐚𝐝𝐦𝐢𝐧𝐢𝐬𝐭𝐫𝐚𝐭𝐨𝐫."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    from plugins.vip_system import DEFAULT_PLANS, FREE_USER_LIMITS
    active_plan = await db.get_active_vip_plan(user_id)
    user_limits = DEFAULT_PLANS.get(active_plan, {}).get("limits", FREE_USER_LIMITS) if active_plan else FREE_USER_LIMITS
    max_groups = user_limits.get("group_connect_limit", 1)
    
    current_groups = await db.get_connected_groups(user_id)
    if len(current_groups) >= max_groups:
        limit_text = f"🛑 **𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐢𝐨𝐧 𝐋𝐢𝐦𝐢𝐭 𝐑𝐞𝐚𝐜𝐡𝐞𝐝!**\n\n𝐘𝐨𝐮𝐫 𝐜𝐮𝐫𝐫𝐞𝐧𝐭 𝐩𝐥𝐚𝐧 𝐨𝐧𝐥𝐲 𝐚𝐥𝐥𝐨𝐰𝐬 𝐲𝐨𝐮 𝐭𝐨 𝐜𝐨𝐧𝐧𝐞𝐜𝐭 **{max_groups}** 𝐠𝐫𝐨𝐮𝐩(𝐬).\n\n_𝐏𝐥𝐞𝐚𝐬𝐞 𝐮𝐩𝐠𝐫𝐚𝐝𝐞 𝐲𝐨𝐮𝐫 𝐕𝐈𝐏 𝐩𝐥𝐚𝐧 𝐭𝐨 𝐜𝐨𝐧𝐧𝐞𝐜𝐭 𝐦𝐨𝐫𝐞 𝐠𝐫𝐨𝐮𝐩𝐬._"
        return await client.edit_message_text(message.chat.id, prompt_msg_id, limit_text) if prompt_msg_id else await message.reply_text(limit_text)

    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    group_admins = []
    async for admin in client.get_chat_members(target_chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not admin.user.is_bot: group_admins.append(admin.user.id)

    await db.update_group_setting(target_chat_id, "admins", group_admins)
    await db.update_group_setting(target_chat_id, "title", chat_title)
    await db.update_group_setting(target_chat_id, "connected_by", user_id)

    success_text = (
        f"✅ **𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗲𝗱!**\n\n"
        f"**𝗚𝗿𝗼𝘂𝗽:** `{chat_title}`\n"
        f"**𝗔𝗱𝗺𝗶𝗻𝘀 𝗟𝗼𝗴𝗴𝗲𝗱:** `{len(group_admins)}`\n"
        f"𝖸𝗈𝗎 𝖺𝗋𝖾 𝗇𝗈𝗐 𝗋𝖾𝗀𝗂𝗌𝗍𝖾𝗋𝖾𝖽 𝖺𝗌 𝗍𝗁𝖾 **𝗣𝗿𝗶𝗺𝗮𝗿𝘆 𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗼𝗿**. 𝖮𝗇𝗅𝗒 𝗒𝗈𝗎 𝗁𝖺𝗏𝖾 𝗍𝗁𝖾 𝖺𝗎𝗍𝗁𝗈𝗋𝗂𝗍𝗒 𝗍𝗈 𝖼𝗁𝖺𝗇𝗀𝖾 𝗍𝗁𝗂𝗌 𝗀𝗋𝗈𝗎𝗉'𝗌 𝗅𝖺𝗒𝗈𝗎𝗍 𝖺𝗇𝖽 𝗍𝗁𝖾𝗆𝖾𝗌!"
    )
    if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
    else: await message.reply_text(success_text)

async def process_disconnect(client: Client, message: Message, user_id: int, target_chat_input: str, prompt_msg_id: int = None):
    try: target_chat = int(target_chat_input)
    except ValueError: target_chat = target_chat_input
        
    try:
        chat = await client.get_chat(target_chat)
        target_chat_id = chat.id
        chat_title = chat.title
    except Exception:
        text = "❌ **𝐄𝐫𝐫𝐨𝐫:** 𝐂𝐨𝐮𝐥𝐝 𝐧𝐨𝐭 𝐟𝐢𝐧𝐝 𝐭𝐡𝐚𝐭 𝐠𝐫𝐨𝐮𝐩."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    
    if not connected_by:
        text = "⚠️ 𝐓𝐡𝐢𝐬 𝐠𝐫𝐨𝐮𝐩 𝐢𝐬 𝐧𝐨𝐭 𝐜𝐮𝐫𝐫𝐞𝐧𝐭𝐥𝐲 𝐜𝐨𝐧𝐧𝐞𝐜𝐭𝐞𝐝 𝐭𝐨 𝐚𝐧𝐲 𝐚𝐝𝐦𝐢𝐧𝐢𝐬𝐭𝐫𝐚𝐭𝐨𝐫."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    if connected_by != user_id and user_id not in Config.ADMINS:
        text = "🛑 **𝐀𝐜𝐜𝐞𝐬𝐬 𝐃𝐞𝐧𝐢𝐞𝐝:** 𝐎𝐧𝐥𝐲 𝐭𝐡𝐞 𝐏𝐫𝐢𝐦𝐚𝐫𝐲 𝐂𝐨𝐧𝐧𝐞𝐜𝐭𝐨𝐫 𝐰𝐡𝐨 𝐥𝐢𝐧𝐤𝐞𝐝 𝐭𝐡𝐢𝐬 𝐠𝐫𝐨𝐮𝐩 𝐜𝐚𝐧 𝐝𝐢𝐬𝐜𝐨𝐧𝐧𝐞𝐜𝐭 𝐢𝐭."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    await db.update_group_setting(target_chat_id, "connected_by", None)
    await db.update_group_setting(target_chat_id, "admins", [])

    success_text = (
        f"🔌 **𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗗𝗶𝘀𝗰𝗼𝗻𝗻𝗲𝗰𝘁𝗲𝗱!**\n\n"
        f"**𝗚𝗿𝗼𝘂𝗽:** `{chat_title}`\n"
        f"𝖳𝗁𝗂𝗌 𝗀𝗋𝗈𝗎𝗉 𝗁𝖺𝗌 𝖻𝖾𝖾𝗇 𝗎𝗇𝗅𝗂𝗇𝗄𝖾𝖽 𝖿𝗋𝗈𝗆 𝗒𝗈𝗎𝗋 𝖺𝖼𝖼𝗈𝗎𝗇𝗍. 𝖳𝗁𝖾 𝗌𝖾𝗍𝗍𝗂𝗇𝗀𝗌 𝖽𝖺𝗌𝗁𝖻𝗈𝖺𝗋𝖽 𝗂𝗌 𝗇𝗈𝗐 𝖼𝗈𝗆𝗉𝗅𝖾𝗍𝖾𝗅𝗒 𝗅𝗈𝖼𝗄𝖾𝖽 𝗎𝗇𝗍𝗂𝗅 𝖺𝗇 𝖺𝖽𝗆𝗂𝗇 𝗌𝖾𝗇𝖽𝗌 `/connect` 𝖺𝗀𝖺𝗂𝗇."
    )
    if prompt_msg_id: await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
    else: await message.reply_text(success_text)

@Client.on_message(filters.command("connect"))
async def connect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await process_connect(client, message, user_id, str(message.chat.id))
    else:
        if len(message.command) < 2:
            prompt = await message.reply_text(
                "🔗 **𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻 𝗦𝗲𝘁𝘂𝗽**\n\n"
                "𝖯𝗅𝖾𝖺𝗌𝖾 𝗌𝖾𝗇𝖽 𝗍𝗁𝖾 **𝗚𝗿𝗼𝘂𝗽 𝗜𝗗** 𝗈𝗋 **𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲** 𝗒𝗈𝗎 𝗐𝖺𝗇𝗍 𝗍𝗈 𝖼𝗈𝗇𝗇𝖾𝖼𝗍 𝗍𝗈 𝗍𝗁𝖾 𝖻𝗈𝗍 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾.\n\n"
                "*(𝖮𝗋 𝖼𝗅𝗂𝖼𝗄 𝖢𝖺𝗇𝖼𝖾𝗅 𝗍𝗈 𝖺𝖻𝗈𝗋𝗍)*",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="cancel_connection_flow", style=ButtonStyle.DANGER)]])
            )
            WAITING_FOR_CONNECTION[user_id] = {"action": "connect", "message_id": prompt.id, "timestamp": time.time()}
            return
        await process_connect(client, message, user_id, message.command[1])
    raise StopPropagation

@Client.on_message(filters.command("disconnect"))
async def disconnect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await process_disconnect(client, message, user_id, str(message.chat.id))
    else:
        if len(message.command) < 2:
            prompt = await message.reply_text(
                "🔌 **𝗗𝗶𝘀𝗰𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻 𝗦𝗲𝘁𝘂𝗽**\n\n"
                "𝖯𝗅𝖾𝖺𝗌𝖾 𝗌𝖾𝗇𝖽 𝗍𝗁𝖾 **𝗚𝗿𝗼𝘂𝗽 𝗜𝗗** 𝗈𝗋 **𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲** 𝗒𝗈𝗎 𝗐𝗂𝗌𝗁 𝗍𝗈 𝖽𝗂𝗌𝖼𝗈𝗇𝗇𝖾𝖼𝗍.\n\n"
                "*(𝖮𝗋 𝖼𝗅𝗂𝖼𝗄 𝖢𝖺𝗇𝖼𝖾𝗅 𝗍𝗈 𝖺𝖻𝗈𝗋𝗍)*",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="cancel_connection_flow", style=ButtonStyle.DANGER)]])
            )
            WAITING_FOR_CONNECTION[user_id] = {"action": "disconnect", "message_id": prompt.id, "timestamp": time.time()}
            return
        await process_disconnect(client, message, user_id, message.command[1])
    raise StopPropagation

@Client.on_message(filters.command("refreshadmins") & filters.group)
async def refresh_admins_command(client: Client, message: Message):
    user_id = message.from_user.id
    target_chat_id = message.chat.id
    
    try:
        user_member = await client.get_chat_member(target_chat_id, user_id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return await message.reply_text("🛑 𝐎𝐧𝐥𝐲 𝐠𝐫𝐨𝐮𝐩 𝐚𝐝𝐦𝐢𝐧𝐬 𝐜𝐚𝐧 𝐫𝐞𝐟𝐫𝐞𝐬𝐡 𝐭𝐡𝐞 𝐚𝐝𝐦𝐢𝐧 𝐥𝐢𝐬𝐭.")
    except Exception: return

    group_admins = []
    async for admin in client.get_chat_members(target_chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not admin.user.is_bot: group_admins.append(admin.user.id)
            
    await db.update_group_setting(target_chat_id, "admins", group_admins)
    await message.reply_text(f"🔄 **𝗔𝗱𝗺𝗶𝗻 𝗟𝗶𝘀𝘁 𝗨𝗽𝗱𝗮𝘁𝗲𝗱!**\n\n𝖲𝗎𝖼𝖼𝖾𝗌𝗌𝖿𝗎𝗅𝗅𝗒 𝗌𝗒𝗇𝖼𝖾𝖽 `{len(group_admins)}` 𝖺𝖼𝗍𝗂𝗏𝖾 𝖺𝖽𝗆𝗂𝗇𝗌 𝗂𝗇𝗍𝗈 𝗍𝗁𝖾 𝖽𝖺𝗍𝖺𝖻𝖺𝗌𝖾 𝖿𝗈𝗋 𝖤𝗆𝖾𝗋𝗀𝖾𝗇𝖼𝗒 𝖱𝖾𝗉𝗈𝗋𝗍𝗌.")
    raise StopPropagation

@Client.on_message(filters.text & filters.private, group=-2)
async def interactive_connection_listener(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in WAITING_FOR_CONNECTION: raise ContinuePropagation
    if message.text.startswith("/"):
        del WAITING_FOR_CONNECTION[user_id]
        raise ContinuePropagation
        
    state = WAITING_FOR_CONNECTION[user_id]
    prompt_msg_id = state["message_id"]
    timestamp = state["timestamp"]
    action = state["action"]
    
    del WAITING_FOR_CONNECTION[user_id]
    if time.time() - timestamp > 172800:
        await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text="⚠️ **𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐄𝐱𝐩𝐢𝐫𝐞𝐝.**\n\n𝐓𝐡𝐢𝐬 𝐩𝐫𝐨𝐦𝐩𝐭 𝐢𝐬 𝐨𝐥𝐝𝐞𝐫 𝐭𝐡𝐚𝐧 𝟒𝟖 𝐡𝐨𝐮𝐫𝐬. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐫𝐮𝐧 𝐭𝐡𝐞 𝐜𝐨𝐦𝐦𝐚𝐧𝐝 𝐚𝐠𝐚𝐢𝐧.")
        try: await message.delete() 
        except Exception: pass
        return
        
    target_chat_input = message.text.strip()
    try: await message.delete() 
    except Exception: pass

    if action == "connect": await process_connect(client, message, user_id, target_chat_input, prompt_msg_id)
    elif action == "disconnect": await process_disconnect(client, message, user_id, target_chat_input, prompt_msg_id)
    raise StopPropagation

@Client.on_callback_query(filters.regex("^cancel_connection_flow$"))
async def cancel_connection_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in WAITING_FOR_CONNECTION:
        del WAITING_FOR_CONNECTION[user_id]
    await callback.message.edit_text("❌ **𝐎𝐩𝐞𝐫𝐚𝐭𝐢𝐨𝐧 𝐂𝐚𝐧𝐜𝐞𝐥𝐥𝐞𝐝.**\n\n𝐘𝐨𝐮 𝐜𝐚𝐧 𝐬𝐭𝐚𝐫𝐭 𝐨𝐯𝐞𝐫 𝐰𝐡𝐞𝐧𝐞𝐯𝐞𝐫 𝐲𝐨𝐮'𝐫𝐞 𝐫𝐞𝐚𝐝𝐲.")
    await callback.answer("𝖢𝖺𝗇𝖼𝖾𝗅𝗅𝖾𝖽", show_alert=False)
