import asyncio
import random
import time
import logging
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ChatType, ChatMemberStatus, ChatMembersFilter
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

CODE_STICKERS = [
    "CAACAgIAAxkBAAERavNqNXnoQwKwPnhWsEL5QXglsmRieAACwVsAAhKjgUg7UdLO-nt4VjwE",
    "CAACAgIAAxkBAAERavVqNXpmmnxWeKfo-qv-kP8WdLuqkwACShcAAutrqUl9AevFXbjHDzwE",
    "CAACAgEAAxkBAAERavFqNXnOCL7UtEeSAe3-1MHnnBpLPAACMQIAAoKgIEQHCzBVrLHGhzwE"
]

# Dictionary to track users expected to input group ID data
# Format: {user_id: {"action": "connect" or "disconnect", "message_id": prompt_id, "timestamp": time}}
WAITING_FOR_CONNECTION = {}

# ==========================================
# CORE LOGIC HELPER FUNCTIONS
# ==========================================

async def process_connect(client: Client, message: Message, user_id: int, target_chat_input: str, prompt_msg_id: int = None):
    try:
        target_chat = int(target_chat_input)
    except ValueError:
        target_chat = target_chat_input 
        
    try:
        chat = await client.get_chat(target_chat)
        target_chat_id = chat.id
        chat_title = chat.title
    except Exception as e:
        text = f"❌ **Error:** Could not find that group. Make sure I am added to it as an Admin first!\n`{e}`"
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    # 2. Verify User Permissions
    try:
        user_member = await client.get_chat_member(target_chat_id, user_id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            text = "🛑 You don't have enough permissions to connect this bot to the group."
            return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)
    except Exception:
        text = "🛑 You don't have enough permissions to connect this bot to the group."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    # 3. Verify Bot Permissions
    try:
        me = await client.get_me()
        bot_member = await client.get_chat_member(target_chat_id, me.id)
        if not bot_member.privileges or not bot_member.privileges.can_delete_messages:
            text = "❌ **Bot Permission Error:** I must be an Admin with `Delete Messages` rights to connect!"
            return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)
    except Exception:
        text = "❌ Could not verify my permissions. Ensure I am an admin in the group."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    # 4. Check if Already Connected
    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    
    if connected_by:
        text = "⚠️ This group is already connected by you!" if connected_by == user_id else "⚠️ This group is already connected to the database by another administrator."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    # 🔓 Send Hacker Unlock Sticker Animation
    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    # 5. Build the Admin Registry
    group_admins = []
    async for admin in client.get_chat_members(target_chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not admin.user.is_bot:
            group_admins.append(admin.user.id)

    # 6. Save Details to Database
    await db.update_group_setting(target_chat_id, "admins", group_admins)
    await db.update_group_setting(target_chat_id, "title", chat_title)
    await db.update_group_setting(target_chat_id, "connected_by", user_id)

    success_text = (
        f"✅ **Successfully Connected!**\n\n"
        f"**Group:** `{chat_title}`\n"
        f"**Admins Logged:** `{len(group_admins)}`\n"
        f"You are now registered as the **Primary Connector**. Only you have the authority to change this group's layout and themes!"
    )
    if prompt_msg_id:
        await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
    else:
        await message.reply_text(success_text)


async def process_disconnect(client: Client, message: Message, user_id: int, target_chat_input: str, prompt_msg_id: int = None):
    try:
        target_chat = int(target_chat_input)
    except ValueError:
        target_chat = target_chat_input
        
    try:
        chat = await client.get_chat(target_chat)
        target_chat_id = chat.id
        chat_title = chat.title
    except Exception:
        text = "❌ **Error:** Could not find that group."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    
    if not connected_by:
        text = "⚠️ This group is not currently connected to any administrator."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    if connected_by != user_id and user_id not in Config.ADMINS:
        text = "🛑 **Access Denied:** Only the Primary Connector who linked this group can disconnect it."
        return await client.edit_message_text(message.chat.id, prompt_msg_id, text) if prompt_msg_id else await message.reply_text(text)

    try:
        loading_msg = await message.reply_sticker(random.choice(CODE_STICKERS))
        await asyncio.sleep(3)
        await loading_msg.delete()
    except Exception: pass

    await db.update_group_setting(target_chat_id, "connected_by", None)
    await db.update_group_setting(target_chat_id, "admins", [])

    success_text = (
        f"🔌 **Successfully Disconnected!**\n\n"
        f"**Group:** `{chat_title}`\n"
        f"This group has been unlinked from your account. The settings dashboard is now completely locked until an admin sends `/connect` again."
    )
    if prompt_msg_id:
        await client.edit_message_text(message.chat.id, prompt_msg_id, success_text)
    else:
        await message.reply_text(success_text)


# ==========================================
# COMMAND HANDLERS
# ==========================================

@Client.on_message(filters.command("connect"))
async def connect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_input = str(message.chat.id)
        await process_connect(client, message, user_id, target_chat_input)
    else:
        if len(message.command) < 2:
            prompt = await message.reply_text(
                "🔗 **Connection Setup**\n\n"
                "Please send the **Group ID** or **Username** you want to connect to the bot database.\n\n"
                "*(Or click Cancel to abort)*",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_connection_flow")]])
            )
            WAITING_FOR_CONNECTION[user_id] = {"action": "connect", "message_id": prompt.id, "timestamp": time.time()}
            return
        
        target_chat_input = message.command[1]
        await process_connect(client, message, user_id, target_chat_input)
    raise StopPropagation

@Client.on_message(filters.command("disconnect"))
async def disconnect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_input = str(message.chat.id)
        await process_disconnect(client, message, user_id, target_chat_input)
    else:
        if len(message.command) < 2:
            prompt = await message.reply_text(
                "🔌 **Disconnection Setup**\n\n"
                "Please send the **Group ID** or **Username** you wish to disconnect.\n\n"
                "*(Or click Cancel to abort)*",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_connection_flow")]])
            )
            WAITING_FOR_CONNECTION[user_id] = {"action": "disconnect", "message_id": prompt.id, "timestamp": time.time()}
            return
            
        target_chat_input = message.command[1]
        await process_disconnect(client, message, user_id, target_chat_input)
    raise StopPropagation

# 🚀 NEW FEATURE: Sync Admins without disconnecting
@Client.on_message(filters.command("refreshadmins") & (filters.group | filters.supergroup))
async def refresh_admins_command(client: Client, message: Message):
    user_id = message.from_user.id
    target_chat_id = message.chat.id
    
    # Verify Permissions
    try:
        user_member = await client.get_chat_member(target_chat_id, user_id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return await message.reply_text("🛑 Only group admins can refresh the admin list.")
    except Exception: return

    # Rescrape Admins
    group_admins = []
    async for admin in client.get_chat_members(target_chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not admin.user.is_bot:
            group_admins.append(admin.user.id)
            
    # Update Database
    await db.update_group_setting(target_chat_id, "admins", group_admins)
    await message.reply_text(f"🔄 **Admin List Updated!**\n\nSuccessfully synced `{len(group_admins)}` active admins into the database for Emergency Reports.")
    raise StopPropagation


# ==========================================
# INTERACTIVE STATE LISTENER
# ==========================================

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
        await client.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text="⚠️ **Session Expired.**\n\nThis prompt is older than 48 hours. Please run the command again.")
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
    await callback.message.edit_text("❌ **Operation Cancelled.**\n\nYou can start over whenever you're ready.")
    await callback.answer("Cancelled", show_alert=False)
