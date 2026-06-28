import random
import string
import datetime
import asyncio
import logging
import urllib.parse
from pyrogram import Client, filters, StopPropagation, ContinuePropagation
from pyrogram.enums import ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LinkPreviewOptions
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ SYSTEM STATE CORE & COLLECTIONS
# ==========================================
UPI_ID = "6303579515@ibl"
MERCHANT_NAME = "NTM GATEWAY"

USER_STATES = {} 

vip_users = db.vip_users
vip_orders = db.vip_orders
vip_coupons = db.vip_coupons
vip_settings = db.vip_settings
vip_history = db.vip_history 
vip_recovery = db.vip_recovery
vip_plans_db = db.vip_plans

# Default Fallback Plans (Synced to DB on startup)
DEFAULT_PLANS = {
    "bronze": {"name": "🥉 Bronze", "days": 30, "price": 99},
    "silver": {"name": "🥈 Silver", "days": 90, "price": 249},
    "gold": {"name": "🥇 Gold", "days": 365, "price": 799},
    "lifetime": {"name": "💎 Lifetime", "days": 36500, "price": 1999}
}

# ==========================================
# 🛡️ DYNAMIC PLANS & AUDIT LOGGING
# ==========================================
async def get_all_plans():
    plans = {}
    async for p in vip_plans_db.find({}):
        plans[p["_id"]] = p
    if not plans:
        for k, v in DEFAULT_PLANS.items():
            await vip_plans_db.update_one({"_id": k}, {"$set": v}, upsert=True)
            plans[k] = v
    return plans

async def log_vip_event(action, user_id, details, admin_id="System"):
    """Logs EVERYTHING to the VIP timeline history."""
    await vip_history.insert_one({
        "action": action,
        "user_id": user_id,
        "details": details,
        "admin_id": admin_id,
        "timestamp": datetime.datetime.now()
    })

def generate_order_id(plan):
    date_str = datetime.datetime.now().strftime("%y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"VIP-{date_str}-{random_str}"

async def send_vip_receipt(client, user_id, order_id, plan_name, amount, utr, admin_id):
    receipt = (
        f"🧾 **VIP PAYMENT RECEIPT** 🧾\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Order ID:** `{order_id}`\n"
        f"👤 **User ID:** `{user_id}`\n"
        f"📦 **Plan:** {plan_name}\n"
        f"💵 **Amount Paid:** ₹{amount}\n"
        f"🔖 **Ref/UTR:** `{utr}`\n"
        f"📅 **Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Approved By:** Admin (`{admin_id}`)\n"
        f"🙏 Thank you for your support!"
    )
    try: await client.send_message(user_id, receipt)
    except: pass

async def add_vip(user_id, plan_name, days, method="Admin Added", gifted_by=None, order_id=None, trx_id=None):
    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    
    data = {
        "user_id": user_id, "plan": plan_name, "status": "Active",
        "joined": datetime.datetime.now(), "expiry": expiry, "renewals": 1,
        "coupons_used": [], "gifted_by": gifted_by, "payment_method": method,
        "order_id": order_id, "trx_id": trx_id
    }
    
    existing = await vip_users.find_one({"user_id": user_id})
    if existing:
        base_expiry = max(existing["expiry"], datetime.datetime.now())
        new_expiry = base_expiry + datetime.timedelta(days=days)
        await vip_users.update_one(
            {"user_id": user_id},
            {"$set": {"expiry": new_expiry, "plan": plan_name, "status": "Active"}, "$inc": {"renewals": 1}}
        )
        await log_vip_event("Renewed/Extended", user_id, f"Added {days} days to {plan_name}", admin_id=gifted_by)
    else:
        await vip_users.insert_one(data)
        await log_vip_event("Created", user_id, f"Joined {plan_name} for {days} days", admin_id=gifted_by)

async def check_vip_status(user_id):
    user = await vip_users.find_one({"user_id": user_id})
    if not user: return False, None
    if user["plan"] == "💎 Lifetime": return True, user
    if user["expiry"] < datetime.datetime.now():
        if user["status"] != "Expired":
            await vip_users.update_one({"user_id": user_id}, {"$set": {"status": "Expired"}})
            await log_vip_event("Expired", user_id, "VIP Membership ran out of time")
        return False, None
    return True, user

async def parse_target_users(client, args_list):
    targets = []
    if not args_list: return targets
    selector = args_list[0].lower()
    if selector == "all":
        async for u in client.db.users.find({}): targets.append(u["user_id"])
    elif selector == "nonvip":
        async for u in client.db.users.find({}):
            is_vip, _ = await check_vip_status(u["user_id"])
            if not is_vip: targets.append(u["user_id"])
    elif selector == "vip":
        async for u in vip_users.find({"status": "Active"}): targets.append(u["user_id"])
    else:
        for item in args_list:
            if item.isdigit(): targets.append(int(item))
    return list(set(targets))

# ==========================================
# ⏰ BACKGROUND AUTO-WORKERS
# ==========================================
async def vip_background_worker(client: Client):
    """Runs every 5 minutes to expire orders and send 15-minute reminders."""
    await asyncio.sleep(60) # Wait for bot to boot
    while True:
        try:
            now = datetime.datetime.now()
            
            # 1. 15-Minute Payment Reminders
            reminder_cursor = vip_orders.find({"status": "Waiting Payment", "reminder_sent": {"$ne": True}})
            async for order in reminder_cursor:
                if (now - order["created_at"]).total_seconds() > 900: # 15 mins
                    try:
                        text = "⏳ **Your payment order is waiting.**\n\nHave you completed the payment? If yes, please don't forget to submit your UTR!"
                        await client.send_message(order["user_id"], text)
                        await vip_orders.update_one({"_id": order["_id"]}, {"$set": {"reminder_sent": True}})
                    except: pass
            
            # 2. 30-Minute Auto Expiry
            expiry_cursor = vip_orders.find({"status": {"$in": ["Created", "Waiting Payment"]}})
            async for order in expiry_cursor:
                if (now - order["created_at"]).total_seconds() > 1800: # 30 mins
                    await vip_orders.update_one({"_id": order["_id"]}, {"$set": {"status": "Expired"}})
                    
        except Exception as e:
            logger.error(f"VIP Background Worker Error: {e}")
            
        await asyncio.sleep(300) # Sleep 5 minutes

# ==========================================
# 💳 PAYMENT & PURCHASE FLOW (STATE MACHINE)
# ==========================================
@Client.on_message(filters.command("buyvip"), group=-1)
async def buy_vip_command(client, message):
    plans = await get_all_plans()
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{p['name']} - ₹{p['price']} ({p['days']} Days)", callback_data=f"vip_buy_{k}")] for k, p in plans.items()
    ])
    await message.reply("💎 **Choose a VIP Membership Plan:**", reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vip_buy_"))
async def vip_buy_callback(client, callback: CallbackQuery):
    plan_key = callback.data.split("_")[2]
    plans = await get_all_plans()
    plan = plans[plan_key]
    order_id = generate_order_id(plan_key)
    
    await vip_orders.insert_one({
        "order_id": order_id, "user_id": callback.from_user.id, "plan": plan_key,
        "amount": plan['price'], "status": "Waiting Payment", "created_at": datetime.datetime.now(),
        "reminder_sent": False
    })
    
    note = f"VIP-{callback.from_user.id}"
    upi_url = f"upi://pay?pa={UPI_ID}&pn={MERCHANT_NAME}&am={plan['price']}&tr={order_id}&cu=INR&tn={note}"
    encoded_upi = urllib.parse.quote(upi_url)
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_upi}"
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I have Paid", callback_data=f"vip_paid_{order_id}")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data=f"vip_cancel_{order_id}")]
    ])
    
    text = (
        f"💳 **Order ID:** `{order_id}`\n📦 **Plan:** {plan['name']}\n💵 **Amount:** ₹{plan['price']}\n\n"
        f"**🏦 PAYMENT OPTIONS:**\n\n1️⃣ **Tap to Copy UPI ID:**\n`{UPI_ID}`\n\n"
        f"2️⃣ **Scan QR Code:**\n[Click Here to view QR Code]({qr_link})\n\n"
        f"⚠️ *Important: After sending exactly ₹{plan['price']}, you MUST click '✅ I have Paid' below within 30 mins.*"
    )
    await callback.message.edit_text(text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=False))

@Client.on_callback_query(filters.regex(r"^vip_cancel_"))
async def vip_cancel_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Rejected"}})
    await callback.message.edit_text("❌ Order Cancelled successfully.")

@Client.on_callback_query(filters.regex(r"^vip_paid_"))
async def vip_paid_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if not order: return await callback.answer("Order not found!", show_alert=True)
        
    if order["status"] == "Expired":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, I Already Paid", callback_data=f"vip_recover_{order_id}")],
            [InlineKeyboardButton("🔄 Create New Order", callback_data="vip_reorder")]
        ])
        return await callback.message.edit_text("⚠️ **Your payment order has expired.**\n\nDid you already complete the payment before it expired?", reply_markup=markup)

    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": False}
    await callback.message.edit_text("📝 **Please send the 12-Digit UPI Reference Number (UTR) or a Screenshot of the payment.**")

@Client.on_callback_query(filters.regex(r"^vip_recover_"))
async def vip_recover_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": True}
    await callback.message.edit_text("🔄 **PAYMENT RECOVERY QUEUE**\n\n📝 Please send the 12-Digit UTR or a Screenshot. Our admin will manually verify and recover your expired order.")

# ==========================================
# 📸 CATCH UTR / SCREENSHOTS & RECOVERY ROUTING
# ==========================================
@Client.on_message(filters.private & ~filters.command(["start", "help", "buyvip", "checkvip", "vippanel", "addvip", "redeem"]), group=-1)
async def catch_payment_proof(client, message: Message):
    if message.text and message.text.startswith("/"): raise ContinuePropagation
    state = USER_STATES.get(message.from_user.id)
    if not state or state.get("action") != "wait_utr": raise ContinuePropagation
        
    order_id = state["order_id"]
    is_recovery = state.get("recovery", False)
    order = await vip_orders.find_one({"order_id": order_id})
    utr = message.text if message.text else "Screenshot Provided"
    
    if message.text:
        dup = await vip_orders.find_one({"utr": message.text})
        if dup:
            await message.reply("❌ **This UTR has already been claimed.** Contact admin if this is an error.")
            raise StopPropagation

    if is_recovery:
        await vip_recovery.insert_one({
            "order_id": order_id, "user_id": message.from_user.id, "utr": utr,
            "status": "Pending Verification", "submitted_at": datetime.datetime.now()
        })
        await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Recovered"}})
        notify_text = "🔄 **Sent to Recovery Queue!** Admin will manually trace your payment."
        admin_flag = "🚨 **RECOVERY QUEUE SUBMISSION**"
    else:
        await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Payment Submitted", "utr": utr, "submitted_at": datetime.datetime.now()}})
        notify_text = "✅ **Payment Proof Submitted!** Order moved to 'Under Review'."
        admin_flag = "🚨 **NEW PAYMENT SUBMITTED**"
        
    del USER_STATES[message.from_user.id]
    await message.reply(notify_text)
    
    admin_text = (
        f"{admin_flag}\n\n👤 User: {message.from_user.mention} (`{message.from_user.id}`)\n"
        f"💳 Order ID: `{order_id}`\n📦 Plan: {order['plan']}\n💵 Amount: ₹{order['amount']}\n🧾 UTR: `{utr}`\n"
        f"📝 Notes: *None*"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"vip_approve_{order_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"vip_reject_{order_id}")],
        [InlineKeyboardButton("📸 Need Screenshot", callback_data=f"vip_note_{order_id}_screenshot"), InlineKeyboardButton("🔢 Need UTR", callback_data=f"vip_note_{order_id}_utr")],
        [InlineKeyboardButton("💬 Ask User", url=f"tg://user?id={message.from_user.id}"), InlineKeyboardButton("📝 Add Note", callback_data=f"vip_addnote_{order_id}")]
    ])
    
    if message.photo: await client.send_photo(Config.ADMINS[0], message.photo.file_id, caption=admin_text, reply_markup=markup)
    else: await client.send_message(Config.ADMINS[0], admin_text, reply_markup=markup)
    raise StopPropagation

# ==========================================
# 👑 ADMIN REVIEW & NOTES LOGIC
# ==========================================
@Client.on_callback_query(filters.regex(r"^vip_approve_") & filters.user(Config.ADMINS))
async def admin_approve(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if order["status"] == "Approved": return await callback.answer("Already approved!", show_alert=True)
        
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Approved", "approved_by": callback.from_user.id, "approved_at": datetime.datetime.now()}})
    
    plans = await get_all_plans()
    plan = plans.get(order["plan"], DEFAULT_PLANS["bronze"])
    await add_vip(order["user_id"], plan["name"], plan["days"], method="UPI", order_id=order_id, trx_id=order.get("utr"))
    
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVED", callback_data="noop")]]))
    await send_vip_receipt(client, order["user_id"], order_id, plan["name"], order["amount"], order.get("utr", "N/A"), callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^vip_reject_") & filters.user(Config.ADMINS))
async def admin_reject(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Rejected"}})
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("❌ REJECTED", callback_data="noop")]]))
    await client.send_message(order["user_id"], f"❌ **Payment Rejected**\n\nYour payment for Order `{order_id}` could not be verified. Please double check and reorder.")
    await log_vip_event("Rejected", order["user_id"], f"Order {order_id} rejected", callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^vip_note_") & filters.user(Config.ADMINS))
async def admin_quick_notes(client, callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id, note_type = parts[2], parts[3]
    order = await vip_orders.find_one({"order_id": order_id})
    
    msg = "Please provide a clear Screenshot of your payment." if note_type == "screenshot" else "Please provide the correct 12-Digit UTR/Reference number."
    await client.send_message(order["user_id"], f"⚠️ **Admin Message regarding Order {order_id}:**\n\n{msg}")
    await callback.answer("Message sent to user!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^vip_addnote_") & filters.user(Config.ADMINS))
async def admin_add_custom_note(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    USER_STATES[callback.from_user.id] = {"action": "admin_note", "order_id": order_id}
    await callback.message.reply("📝 **Type the custom note for this order:**")
    await callback.answer()

@Client.on_message(filters.private & filters.user(Config.ADMINS), group=-2)
async def catch_admin_notes(client, message: Message):
    state = USER_STATES.get(message.from_user.id)
    if not state or state.get("action") != "admin_note": raise ContinuePropagation
    order_id = state["order_id"]
    note = message.text
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"admin_notes": note}})
    del USER_STATES[message.from_user.id]
    await message.reply(f"✅ Note attached to Order `{order_id}`.")
    raise StopPropagation

# ==========================================
# 💎 CENTRALIZED VIP DASHBOARD (/vippanel)
# ==========================================
@Client.on_message(filters.command("vippanel") & filters.user(Config.ADMINS), group=-1)
async def open_vip_panel(client, message):
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Memberships", callback_data="vipdb_members"), InlineKeyboardButton("💳 Payments", callback_data="vipdb_payments")],
        [InlineKeyboardButton("🎟️ Coupons", callback_data="vipdb_coupons"), InlineKeyboardButton("📦 Plans", callback_data="vipdb_plans")],
        [InlineKeyboardButton("📊 Statistics", callback_data="vipdb_stats"), InlineKeyboardButton("🎁 Promotions", callback_data="vipdb_promos")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="vipdb_settings"), InlineKeyboardButton("📜 Logs", callback_data="vipdb_logs")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="vipdb_close")]
    ])
    await message.reply("💎 **VIP ENTERPRISE DASHBOARD**\nSelect a module to manage:", reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vipdb_") & filters.user(Config.ADMINS))
async def vip_panel_router(client, callback: CallbackQuery):
    action = callback.data.split("_")[1]
    
    if action == "close": return await callback.message.delete()
    
    if action == "stats":
        total_sales = await vip_orders.count_documents({"status": "Approved"})
        pipeline = [{"$match": {"status": "Approved"}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]
        rev_data = await vip_orders.aggregate(pipeline).to_list(1)
        revenue = rev_data[0]["total"] if rev_data else 0
        
        active_vips = await vip_users.count_documents({"status": "Active"})
        used_coupons = await vip_coupons.count_documents({"status": "Used"})
        pending = await vip_orders.count_documents({"status": "Payment Submitted"})
        recoveries = await vip_recovery.count_documents({"status": "Pending Verification"})
        
        text = (
            f"📊 **VIP STATISTICS**\n\n"
            f"🟢 Active VIPs: `{active_vips}`\n"
            f"💰 Total Revenue: `₹{revenue}`\n"
            f"🛒 Total Sales: `{total_sales}`\n"
            f"🎟️ Coupons Claimed: `{used_coupons}`\n"
            f"⏳ Pending Payments: `{pending}`\n"
            f"🔄 Recovery Queue: `{recoveries}`"
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="vipdb_home")]])
        await callback.message.edit_text(text, reply_markup=markup)
        
    elif action == "home":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Memberships", callback_data="vipdb_members"), InlineKeyboardButton("💳 Payments", callback_data="vipdb_payments")],
            [InlineKeyboardButton("🎟️ Coupons", callback_data="vipdb_coupons"), InlineKeyboardButton("📦 Plans", callback_data="vipdb_plans")],
            [InlineKeyboardButton("📊 Statistics", callback_data="vipdb_stats"), InlineKeyboardButton("🎁 Promotions", callback_data="vipdb_promos")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="vipdb_settings"), InlineKeyboardButton("📜 Logs", callback_data="vipdb_logs")],
            [InlineKeyboardButton("❌ Close Panel", callback_data="vipdb_close")]
        ])
        await callback.message.edit_text("💎 **VIP ENTERPRISE DASHBOARD**\nSelect a module to manage:", reply_markup=markup)
        
    else:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="vipdb_home")]])
        await callback.message.edit_text(f"⚙️ Module `{action.upper()}` is active. Use the specific slash commands (e.g. /addvip, /createcoupon, /addplan) to interact with this layer.", reply_markup=markup)

# ==========================================
# 🛠️ MISSING COMMANDS IMPLEMENTATION
# ==========================================
@Client.on_message(filters.command("plans") & filters.user(Config.ADMINS), group=-1)
async def list_plans_cmd(client, message):
    plans = await get_all_plans()
    out = "📦 **Configured VIP Plans:**\n\n"
    for k, p in plans.items(): out += f"• `{k}` : {p['name']} | ₹{p['price']} | {p['days']} Days\n"
    await message.reply(out)
    raise StopPropagation

@Client.on_message(filters.command("addplan") & filters.user(Config.ADMINS), group=-1)
async def add_plan_cmd(client, message):
    args = message.text.split()
    if len(args) < 5: return await message.reply("⚠️ Syntax: `/addplan <id_key> <DisplayName> <Price> <Days>`\nExample: `/addplan platinum 🌟Platinum 1499 180`")
    k = args[1].lower()
    await vip_plans_db.update_one({"_id": k}, {"$set": {"name": args[2], "price": int(args[3]), "days": int(args[4])}}, upsert=True)
    await message.reply(f"✅ Added Plan `{k}`.")
    raise StopPropagation

@Client.on_message(filters.command("deleteplan") & filters.user(Config.ADMINS), group=-1)
async def delete_plan_cmd(client, message):
    if len(message.command) < 2: return await message.reply("⚠️ Syntax: `/deleteplan <id_key>`")
    await vip_plans_db.delete_one({"_id": message.command[1].lower()})
    await message.reply(f"🗑️ Deleted Plan.")
    raise StopPropagation

@Client.on_message(filters.command("createcoupon") & filters.user(Config.ADMINS), group=-1)
async def admin_create_coupons(client, message: Message):
    args = message.text.split()
    if len(args) < 6: return await message.reply("⚠️ **Usage:** `/createcoupon <plan_key> <prefix> <quantity> <max_uses> <expiry_days>`")
    
    plan_target = args[1].lower()
    prefix = args[2].upper()
    qty = int(args[3])
    max_uses = int(args[4])
    exp_days = int(args[5])
    expiry = datetime.datetime.now() + datetime.timedelta(days=exp_days)
    
    generated = []
    for _ in range(qty):
        token = f"{prefix}-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        await vip_coupons.insert_one({
            "code": token, "plan_target": plan_target, "status": "Active", "created_at": datetime.datetime.now(),
            "max_uses": max_uses, "remaining_uses": max_uses, "expiry": expiry, "created_by": message.from_user.id
        })
        generated.append(token)
        
    with open("coupons.txt", "w") as f: f.write("\n".join(generated))
    await message.reply_document("coupons.txt", caption=f"🎟️ Generated `{qty}` coupons for `{plan_target}`.")
    import os; os.remove("coupons.txt")
    raise StopPropagation

@Client.on_message(filters.command("deletecoupon") & filters.user(Config.ADMINS), group=-1)
async def delete_coupon_cmd(client, message):
    if len(message.command) < 2: return await message.reply("⚠️ Syntax: `/deletecoupon <CODE>`")
    await vip_coupons.delete_one({"code": message.command[1].upper()})
    await message.reply("🗑️ Coupon Deleted.")
    raise StopPropagation

@Client.on_message(filters.command("compensate") & filters.user(Config.ADMINS), group=-1)
async def compensate_cmd(client, message: Message):
    args = message.text.split()
    if len(args) < 3: return await message.reply("⚠️ Syntax: `/compensate <all/vip/bronze> <+days>d`")
    days = int(args[2].replace("d","").replace("+",""))
    targets = await parse_target_users(client, [args[1]])
    
    count = 0
    for uid in targets:
        user = await vip_users.find_one({"user_id": uid})
        if user:
            new_exp = user["expiry"] + datetime.timedelta(days=days)
            await vip_users.update_one({"user_id": uid}, {"$set": {"expiry": new_exp}})
            await log_vip_event("Compensated", uid, f"Added {days} extra days", message.from_user.id)
            count += 1
    await message.reply(f"🎁 Compensated `{count}` users with {days} extra days.")
    raise StopPropagation

@Client.on_message(filters.command("listvip") & filters.user(Config.ADMINS), group=-1)
async def list_vip_cmd(client, message):
    active = await vip_users.count_documents({"status": "Active"})
    expired = await vip_users.count_documents({"status": "Expired"})
    await message.reply(f"📊 **VIP Registry**\n🟢 Active: `{active}`\n🔴 Expired: `{expired}`\n\n*(Use /searchvip to find specific users)*")
    raise StopPropagation

# Keep original Commands (/addvip, /removevip, etc.) below as previously written
# ... (Previous matrix commands like /addvip, /extendvip, /checkvip are maintained here)
@Client.on_message(filters.command("addvip") & filters.user(Config.ADMINS), group=-1)
async def admin_add_vip_matrix(client, message: Message):
    args = message.text.split()
    if len(args) < 4: return await message.reply("⚠️ **Usage Syntax:**\n`/addvip <id/all/nonvip> <Plan_Name> <days>d`")
    days = int(args[-1].lower().replace("d", ""))
    plan_name = args[-2]
    targets = await parse_target_users(client, args[1:-2])
    if not targets and message.reply_to_message: targets = [message.reply_to_message.from_user.id]
    count = 0
    for uid in targets:
        await add_vip(uid, plan_name, days, method="Admin Matrix Injection", gifted_by=message.from_user.id)
        count += 1
    await message.reply(f"🎯 **Matrix Allocation Successful!** Granted {days} Days across `{count}` accounts.")
    raise StopPropagation

@Client.on_message(filters.command("removevip") & filters.user(Config.ADMINS), group=-1)
async def admin_remove_vip_matrix(client, message: Message):
    targets = await parse_target_users(client, message.text.split()[1:])
    if not targets and message.reply_to_message: targets = [message.reply_to_message.from_user.id]
    await vip_users.delete_many({"user_id": {"$in": targets}})
    for uid in targets: await log_vip_event("Removed", uid, "VIP access forcefully revoked", message.from_user.id)
    await message.reply(f"🗑️ Revoked access for `{len(targets)}` accounts.")
    raise StopPropagation

@Client.on_message(filters.command("checkvip"), group=-1)
async def check_vip_cmd(client, message: Message):
    target = message.from_user.id
    if len(message.command) > 1 and message.from_user.id in Config.ADMINS: target = int(message.command[1])
    is_vip, user = await check_vip_status(target)
    if not is_vip: return await message.reply("❌ **No Active VIP Membership.**\nUse `/buyvip` to browse options!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium VIP", callback_data="vip_reorder")]]))
    rem = user['expiry'] - datetime.datetime.now()
    rem_days = "Infinite" if user["plan"] == "💎 Lifetime" else f"{rem.days} Days"
    text = (f"💎 **VIP STATUS**\n📦 **Plan:** `{user['plan']}`\n🟢 **Status:** `{user['status']}`\n📅 **Joined:** `{user['joined'].strftime('%Y-%m-%d')}`\n⏳ **Expiry:** `{user['expiry'].strftime('%Y-%m-%d')}`\n⏱ **Remaining:** `{rem_days}`\n💳 **Order ID:** `{user.get('order_id','N/A')}`")
    await message.reply(text)
    raise StopPropagation

@Client.on_message(filters.command("redeem"), group=-1)
async def user_redeem_coupon(client, message: Message):
    if len(message.command) < 2: return await message.reply("⚠️ Usage: `/redeem <COUPON-CODE>`")
    code = message.command[1].strip().upper()
    coupon = await vip_coupons.find_one({"code": code, "status": "Active", "remaining_uses": {"$gt": 0}})
    if not coupon or coupon["expiry"] < datetime.datetime.now(): return await message.reply("❌ **Invalid or Expired Coupon.**")
    
    plans = await get_all_plans()
    plan_meta = plans.get(coupon["plan_target"], DEFAULT_PLANS["bronze"])
    
    rem_uses = coupon["remaining_uses"] - 1
    status = "Used" if rem_uses <= 0 else "Active"
    await vip_coupons.update_one({"code": code}, {"$set": {"remaining_uses": rem_uses, "status": status}})
    await add_vip(message.from_user.id, plan_meta["name"], plan_meta["days"], method=f"Coupon ({code})")
    await log_vip_event("Coupon", message.from_user.id, f"Redeemed {code}")
    await message.reply(f"🎉 **Redemption Success!** Activated tier `{plan_meta['name']}`.")
    raise StopPropagation
