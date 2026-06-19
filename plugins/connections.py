import logging
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus, ChatMembersFilter
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("connect"))
async def connect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 1. Determine Target Chat (PM vs Group)
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = message.chat.id
        chat_title = message.chat.title
    else:
        if len(message.command) < 2:
            return await message.reply_text(
                "❌ **Usage in PM:** `/connect <group_id_or_username>`\n"
                "*(Or just send `/connect` directly inside your group!)*"
            )
        target_chat_input = message.command[1]
        try:
            chat = await client.get_chat(target_chat_input)
            target_chat_id = chat.id
            chat_title = chat.title
        except Exception as e:
            return await message.reply_text(f"❌ **Error:** Could not find that group. Make sure I am added to it as an Admin first!\n`{e}`")

    # 2. Verify User Permissions First
    try:
        user_member = await client.get_chat_member(target_chat_id, user_id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            return await message.reply_text("🛑 You don't have enough permissions to connect this bot to the group.")
    except Exception:
        return await message.reply_text("🛑 You don't have enough permissions to connect this bot to the group.")

    # 3. Verify Bot Permissions
    try:
        me = await client.get_me()
        bot_member = await client.get_chat_member(target_chat_id, me.id)
        if not bot_member.privileges or not bot_member.privileges.can_delete_messages:
            return await message.reply_text("❌ **Bot Permission Error:** I must be an Admin with `Delete Messages` rights to connect!")
    except Exception:
        return await message.reply_text("❌ Could not verify my permissions. Ensure I am an admin in the group.")

    # 4. Check if Already Connected & Verify Primary Connector
    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    
    if connected_by:
        if connected_by == user_id:
            return await message.reply_text("⚠️ This group is already connected by you!")
        else:
            return await message.reply_text("⚠️ This group is already connected to the database by another administrator.")

    status_msg = await message.reply_text("🔄 **Verifying and linking group...**")

    # 5. Build the Admin Registry for future features
    group_admins = []
    async for admin in client.get_chat_members(target_chat_id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not admin.user.is_bot:
            group_admins.append(admin.user.id)

    # 6. Save Details to Database
    await db.update_group_setting(target_chat_id, "admins", group_admins)
    await db.update_group_setting(target_chat_id, "title", chat_title)
    await db.update_group_setting(target_chat_id, "connected_by", user_id) # The Primary Connector!

    await status_msg.edit_text(
        f"✅ **Successfully Connected!**\n\n"
        f"**Group:** `{chat_title}`\n"
        f"You are now registered as the **Primary Connector**. Only you have the authority to change this group's layout and themes!"
    )

@Client.on_message(filters.command("disconnect"))
async def disconnect_group_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # 1. Determine Target Chat (PM vs Group)
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        target_chat_id = message.chat.id
        chat_title = message.chat.title
    else:
        if len(message.command) < 2:
            return await message.reply_text(
                "❌ **Usage in PM:** `/disconnect <group_id_or_username>`\n"
                "*(Or just send `/disconnect` directly inside your group!)*"
            )
        target_chat_input = message.command[1]
        try:
            chat = await client.get_chat(target_chat_input)
            target_chat_id = chat.id
            chat_title = chat.title
        except Exception:
            return await message.reply_text("❌ **Error:** Could not find that group.")

    # 2. Fetch the current group connection status
    g_sett = await db.get_group_settings(target_chat_id)
    connected_by = g_sett.get("connected_by")
    
    if not connected_by:
        return await message.reply_text("⚠️ This group is not currently connected to any administrator.")

    # 3. Security Gatekeeper: Only the Primary Connector (or Bot Creator) can disconnect
    if connected_by != user_id and user_id not in Config.ADMINS:
        return await message.reply_text("🛑 **Access Denied:** Only the Primary Connector who linked this group can disconnect it.")

    # 4. Erase the connection data from the database
    await db.update_group_setting(target_chat_id, "connected_by", None)
    await db.update_group_setting(target_chat_id, "admins", [])

    await message.reply_text(
        f"🔌 **Successfully Disconnected!**\n\n"
        f"**Group:** `{chat_title}`\n"
        f"This group has been unlinked from your account. The settings dashboard is now completely locked until an admin sends `/connect` again."
    )
