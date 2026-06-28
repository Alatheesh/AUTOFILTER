import random
import string
import datetime
import asyncio
from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ButtonStyle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db
from config import Config

# ==========================================
# ⚙️ VIP SYSTEM CONFIGURATION
# ==========================================
UPI_ID = "6303579515@ibl"      # Replace with your UPI ID
MERCHANT_NAME = "NTM GATEWAY"     # Replace with your Name

# Temporary State Storage for waiting inputs (UTR/Screenshots)
USER_STATES = {}

# Use the properly routed collections from multi_db.py
vip_users = db.vip_users
vip_orders = db.vip_orders
vip_coupons = db.vip_coupons
vip_settings = db.vip_settings

# Default Plans
PLANS = {
    "bronze": {"name": "🥉 Bronze", "days": 30, "price": 99},
    "silver": {"name": "🥈 Silver", "days": 90, "price": 249},
    "gold": {"name": "🥇 Gold", "days": 365, "price": 799},
    "lifetime": {"name": "💎 Lifetime", "days": 36500, "price": 1999}
}

# ==========================================
# 🛡️ HELPER FUNCTIONS
# ==========================================
def generate_order_id(plan):
    date_str = datetime.datetime.now().strftime("%y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"VIP-{date_str}-{random_str}"

async def add_vip(user_id, plan_name, days, method="Admin", gifted_by=None, order_id=None):
    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    data = {
        "user_id": user_id,
        "plan": plan_name,
        "status": "Active",
        "joined": datetime.datetime.now(),
        "expiry": expiry,
        "renewals": 1,
        "payment_method": method,
        "order_id": order_id,
        "gifted_by": gifted_by
    }
    
    existing = await vip_users.find_one({"user_id": user_id})
    if existing:
        new_expiry = max(existing["expiry"], datetime.datetime.now()) + datetime.timedelta(days=days)
        await vip_users.update_one(
            {"user_id": user_id},
            {"$set": {"expiry": new_expiry, "plan": plan_name}, "$inc": {"renewals": 1}}
        )
    else:
        await vip_users.insert_one(data)

async def check_vip_status(user_id):
    user = await vip_users.find_one({"user_id": user_id})
    if not user:
        return False, None
    if user["expiry"] < datetime.datetime.now():
        await vip_users.update_one({"user_id": user_id}, {"$set": {"status": "Expired"}})
        return False, None
    return True, user

# ==========================================
# 🎁 NEW USER TRIAL VIP FEATURE
# ==========================================
@Client.on_message(filters.command("setviptrial") & filters.user(Config.ADMINS), group=-1)
async def set_vip_trial(client, message):
    if len(message.command) != 2:
        return await message.reply("Usage: `/setviptrial <days>` (Use 0 to disable)")
    
    days = int(message.command[1])
    await vip_settings.update_one({"_id": "trial_settings"}, {"$set": {"days": days}}, upsert=True)
    await message.reply(f"✅ **New users will now automatically get {days} days of VIP.**")
    raise StopPropagation

async def apply_new_user_trial(user_id):
    setting = await vip_settings.find_one({"_id": "trial_settings"})
    if setting and setting.get("days", 0) > 0:
        days = setting["days"]
        await add_vip(user_id, "🎁 Trial", days, method="Welcome Gift")

# ==========================================
# 💳 PAYMENT & PURCHASE FLOW (USERS)
# ==========================================
@Client.on_message(filters.command("buyvip"), group=-1)
async def buy_vip_command(client, message):
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{p['name']} - ₹{p['price']} ({p['days']} Days)", callback_data=f"vip_buy_{k}", style=ButtonStyle.PRIMARY)] for k, p in PLANS.items()
    ])
    await message.reply("💎 **Choose a VIP Membership Plan:**", reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vip_buy_"))
async def vip_buy_callback(client, callback: CallbackQuery):
    import urllib.parse
    from pyrogram.types import LinkPreviewOptions
    
    plan_key = callback.data.split("_")[2]
    plan = PLANS[plan_key]
    order_id = generate_order_id(plan_key)
    
    # Create Order Session
    await vip_orders.insert_one({
        "order_id": order_id,
        "user_id": callback.from_user.id,
        "plan": plan_key,
        "amount": plan['price'],
        "status": "Created",
        "created_at": datetime.datetime.now(),
    })
    
    # Generate UPI Deep Link
    note = f"VIP-{callback.from_user.id}"
    upi_url = f"upi://pay?pa={UPI_ID}&pn={MERCHANT_NAME}&am={plan['price']}&tr={order_id}&cu=INR&tn={note}"
    
    # Generate a Live QR Code for the UPI Link
    encoded_upi = urllib.parse.quote(upi_url)
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_upi}"
    
    # We only keep the Callback buttons (No URL buttons)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I have Paid", callback_data=f"vip_paid_{order_id}", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("❌ Cancel Order", callback_data=f"vip_cancel_{order_id}", style=ButtonStyle.DANGER)]
    ])
    
    text = (
        f"💳 **Order ID:** `{order_id}`\n"
        f"📦 **Plan:** {plan['name']}\n"
        f"💵 **Amount:** ₹{plan['price']}\n\n"
        f"**🏦 PAYMENT OPTIONS:**\n\n"
        f"1️⃣ **Tap to Copy UPI ID:**\n`{UPI_ID}`\n\n"
        f"2️⃣ **Scan QR Code:**\n[Click Here to view QR Code]({qr_link})\n\n"
        f"⚠️ *Important: After sending exactly ₹{plan['price']} to the UPI ID above, you MUST click '✅ I have Paid' below.*"
    )
    
    # The LinkPreviewOptions will force Telegram to load the QR code image directly in the chat!
    await callback.message.edit_text(
        text, 
        reply_markup=markup, 
        link_preview_options=LinkPreviewOptions(is_disabled=False)
    )

@Client.on_callback_query(filters.regex(r"^vip_paid_"))
async def vip_paid_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    
    if not order:
        return await callback.answer("Order not found!", show_alert=True)
        
    time_diff = datetime.datetime.now() - order["created_at"]
    if time_diff.total_seconds() > 1800 and order["status"] == "Created":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, I Already Paid", callback_data=f"vip_recover_{order_id}", style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton("🔄 Create New Order", callback_data="vip_reorder", style=ButtonStyle.PRIMARY)]
        ])
        return await callback.message.edit_text("⚠️ **Your order has expired.**\n\nDid you already complete the payment for this order?", reply_markup=markup)

    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id}
    await callback.message.edit_text("📝 **Please send the 12-Digit UPI Reference Number (UTR) or a Screenshot of the payment.**")

@Client.on_callback_query(filters.regex(r"^vip_recover_"))
async def vip_recover_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": True}
    await callback.message.edit_text("🔄 **PAYMENT RECOVERY**\n\n📝 Please send the 12-Digit UPI Reference Number (UTR) or a Screenshot of the payment. Our admin will manually verify it.")

# ==========================================
# 📸 CATCH UTR / SCREENSHOTS (Absolute Priority)
# ==========================================
@Client.on_message(filters.private & ~filters.command(["start", "help"]), group=-1)
async def catch_payment_proof(client, message):
    state = USER_STATES.get(message.from_user.id)
    if not state or state.get("action") != "wait_utr":
        return message.continue_propagation()
        
    order_id = state["order_id"]
    order = await vip_orders.find_one({"order_id": order_id})
    utr = message.text if message.text else "Screenshot Provided"
    
    if message.text:
        dup = await vip_orders.find_one({"utr": message.text})
        if dup:
            await message.reply("❌ **This Reference Number has already been used.** If you believe this is an error, contact admin.")
            raise StopPropagation

    await vip_orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": "Under Review", "utr": utr, "submitted_at": datetime.datetime.now()}}
    )
    
    del USER_STATES[message.from_user.id]
    await message.reply("✅ **Payment Proof Submitted!**\n\nYour order is now under review. You will receive a notification once the admin approves it.")
    
    admin_text = (
        f"🚨 **NEW PAYMENT SUBMISSION**\n\n"
        f"👤 User: {message.from_user.mention} (`{message.from_user.id}`)\n"
        f"💳 Order ID: `{order_id}`\n"
        f"📦 Plan: {order['plan']}\n"
        f"💵 Amount: ₹{order['amount']}\n"
        f"🧾 UTR: `{utr}`"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"vip_approve_{order_id}", style=ButtonStyle.SUCCESS),
         InlineKeyboardButton("❌ Reject", callback_data=f"vip_reject_{order_id}", style=ButtonStyle.DANGER)]
    ])
    
    if message.photo:
        await client.send_photo(Config.ADMINS[0], message.photo.file_id, caption=admin_text, reply_markup=markup)
    else:
        await client.send_message(Config.ADMINS[0], admin_text, reply_markup=markup)
    
    raise StopPropagation

# ==========================================
# 👑 ADMIN APPROVAL SYSTEM
# ==========================================
@Client.on_callback_query(filters.regex(r"^vip_approve_") & filters.user(Config.ADMINS))
async def admin_approve(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    
    if order["status"] == "Approved":
        return await callback.answer("Already approved!", show_alert=True)
        
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Approved", "approved_by": callback.from_user.id, "approved_at": datetime.datetime.now()}})
    
    plan = PLANS[order["plan"]]
    await add_vip(order["user_id"], plan["name"], plan["days"], method="UPI", order_id=order_id)
    
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVED", callback_data="noop", style=ButtonStyle.SUCCESS)]]))
    await client.send_message(order["user_id"], f"🎉 **Payment Approved!**\n\nYour {plan['name']} VIP Membership is now Active! Thank you for your support.")

@Client.on_callback_query(filters.regex(r"^vip_reject_") & filters.user(Config.ADMINS))
async def admin_reject(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Rejected"}})
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("❌ REJECTED", callback_data="noop", style=ButtonStyle.DANGER)]]))
    await client.send_message(order["user_id"], f"❌ **Payment Rejected**\n\nYour payment for Order `{order_id}` could not be verified. Please contact admin if this is a mistake.")

# ==========================================
# 🛠️ ADMIN VIP COMMANDS
# ==========================================
@Client.on_message(filters.command("addvip") & filters.user(Config.ADMINS), group=-1)
async def admin_add_vip(client, message):
    args = message.text.split()
    if len(args) < 4:
        return await message.reply("Usage: `/addvip <user_id> <Plan> <days>d`")
    
    user_id = int(args[1])
    plan = args[2]
    days = int(args[3].replace("d", ""))
    
    await add_vip(user_id, plan, days, method="Admin Added")
    await message.reply(f"✅ Added {days} days of {plan} VIP to `{user_id}`.")
    raise StopPropagation

@Client.on_message(filters.command("checkvip"), group=-1)
async def check_vip_cmd(client, message):
    target = message.from_user.id
    if len(message.command) > 1 and message.from_user.id in Config.ADMINS:
        target = int(message.command[1])
        
    is_vip, user = await check_vip_status(target)
    if not is_vip:
        await message.reply("❌ **No Active VIP Membership.**\nUse /buyvip to get one!")
        raise StopPropagation
        
    rem = user['expiry'] - datetime.datetime.now()
    text = (
        f"💎 **VIP MEMBERSHIP STATUS**\n\n"
        f"📦 **Plan:** {user['plan']}\n"
        f"🟢 **Status:** {user['status']}\n"
        f"📅 **Joined:** {user['joined'].strftime('%Y-%m-%d')}\n"
        f"⏳ **Expiry:** {user['expiry'].strftime('%Y-%m-%d')}\n"
        f"⏱ **Remaining:** {rem.days} Days\n"
        f"🔄 **Renewals:** {user['renewals']}\n"
        f"💳 **Method:** {user['payment_method']}"
    )
    await message.reply(text)
    raise StopPropagation

@Client.on_message(filters.command("listvip") & filters.user(Config.ADMINS), group=-1)
async def list_vip_placeholder(client, message):
    await message.reply("⚙️ **VIP List Module is under construction.**")
    raise StopPropagation

@Client.on_message(filters.command("freevip") & filters.user(Config.ADMINS), group=-1)
async def free_vip_placeholder(client, message):
    await message.reply("⚙️ **Free VIP / Promo Wizard is under construction.**")
    raise StopPropagation
