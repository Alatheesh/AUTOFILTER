import random
import string
import datetime
import asyncio
import logging
import urllib.parse
import io
from pyrogram import Client, filters, StopPropagation, ContinuePropagation
from pyrogram.enums import ChatType, ButtonStyle
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
vip_subscriptions = db.vip_subscriptions
# 🚀 NEW: Dynamic Limits Registry (Replacing old boolean features)

DEFAULT_PLANS = {
    "bronze": {
        "name": "🥉 Bronze", "days": 30, "price": 99,
        "limits": {"shortlink_bypass": True, "multi_search_limit": 3, "bulk_select_limit": 50, "movie_request_cooldown": 30, "group_connect_limit": 2}
    },
    "silver": {
        "name": "🥈 Silver", "days": 90, "price": 249,
        "limits": {"shortlink_bypass": True, "multi_search_limit": 5, "bulk_select_limit": 100, "movie_request_cooldown": 15, "group_connect_limit": 5}
    },
    "gold": {
        "name": "🥇 Gold", "days": 365, "price": 799,
        "limits": {"shortlink_bypass": True, "multi_search_limit": 10, "bulk_select_limit": 500, "movie_request_cooldown": 5, "group_connect_limit": 15}
    },
    "lifetime": {
        "name": "💎 Lifetime", "days": 36500, "price": 1999,
        "limits": {"shortlink_bypass": True, "multi_search_limit": 20, "bulk_select_limit": 1000, "movie_request_cooldown": 0, "group_connect_limit": 50}
    }
}

FREE_USER_LIMITS = {
    "shortlink_bypass": False,
    "multi_search_limit": 1,
    "bulk_select_limit": 10,
    "movie_request_cooldown": 60,
    "group_connect_limit": 1
}

# ==========================================
# 🛡️ FEATURE REGISTRY & DYNAMIC PLANS
# ==========================================
async def get_all_plans():
    plans = {}
    async for p in vip_plans_db.find({}): plans[p["_id"]] = p
    if not plans:
        for k, v in DEFAULT_PLANS.items():
            await vip_plans_db.update_one({"_id": k}, {"$set": v}, upsert=True)
            plans[k] = v
    return plans

async def log_vip_event(action, user_id, details, admin_id="System"):
    await vip_history.insert_one({"action": action, "user_id": user_id, "details": details, "admin_id": admin_id, "timestamp": datetime.datetime.now()})

async def update_order_state(order_id, new_status, extra_data=None):
    update = {"$set": {"status": new_status, "updated_at": datetime.datetime.now()}}
    if extra_data: update["$set"].update(extra_data)
    update["$push"] = {"timeline": {"status": new_status, "time": datetime.datetime.now()}}
    await vip_orders.update_one({"order_id": order_id}, update)

def generate_order_id(plan):
    date_str = datetime.datetime.now().strftime("%y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"VIP-{date_str}-{random_str}"

async def send_vip_receipt(client, user_id, order_id, plan_name, amount, utr, admin_id):
    receipt = (
        f"🧾 **VIP PAYMENT RECEIPT** 🧾\n━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Order ID:** `{order_id}`\n👤 **User ID:** `{user_id}`\n"
        f"📦 **Plan:** {plan_name}\n💵 **Amount Paid:** ₹{amount}\n🔖 **Ref/UTR:** `{utr}`\n"
        f"📅 **Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n━━━━━━━━━━━━━━━━━━━\n"
        f"✅ **Approved By:** Admin (`{admin_id}`)\n🙏 Thank you for your support!"
    )
    try: await client.send_message(user_id, receipt)
    except: pass

async def add_vip(user, plan_name, days, method="Admin Added", gifted_by=None, order_id=None, trx_id=None):
    user_id = user.id if hasattr(user, 'id') else user
    username = f"@{user.username}" if hasattr(user, 'username') and user.username else "N/A"
    first_name = user.first_name if hasattr(user, 'first_name') else "Unknown"

    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    
    await vip_subscriptions.insert_one({
        "user_id": user_id, "plan": plan_name, "days": days, "method": method,
        "order_id": order_id, "trx_id": trx_id, "activated_at": datetime.datetime.now(), "expires_at": expiry
    })

    existing = await vip_users.find_one({"user_id": user_id})
    if existing:
        base_expiry = max(existing["expiry"], datetime.datetime.now())
        new_expiry = base_expiry + datetime.timedelta(days=days)
        await vip_users.update_one(
            {"user_id": user_id},
            {"$set": {"expiry": new_expiry, "plan": plan_name, "status": "Active", "username": username, "first_name": first_name, "notice_24h": False}, "$inc": {"renewals": 1}}
        )
        await log_vip_event("Renewed/Extended", user_id, f"Added {days} days to {plan_name}", admin_id=gifted_by)
    else:
        await vip_users.insert_one({
            "user_id": user_id, "username": username, "first_name": first_name, "plan": plan_name, "status": "Active",
            "joined": datetime.datetime.now(), "expiry": expiry, "renewals": 1, "coupons_used": [], "notice_24h": False
        })
        await log_vip_event("Created", user_id, f"Joined {plan_name} for {days} days", admin_id=gifted_by)

async def check_vip_status(user_id):
    user = await vip_users.find_one({"user_id": user_id})
    if not user: return False, None
    if user["plan"] == "💎 Lifetime": return True, user
    if user["expiry"] < datetime.datetime.now():
        if user["status"] != "Expired":
            await vip_users.update_one({"user_id": user_id}, {"$set": {"status": "Expired"}})
            await log_vip_event("Expired", user_id, "VIP Membership expired natively")
        return False, None
    return True, user

async def parse_target_users(client, args_list):
    targets = []
    if not args_list: return targets
    selector = args_list[0].lower()
    if selector == "all":
        async for u in db.users.find({}): targets.append(u["user_id"])
    elif selector == "nonvip":
        async for u in db.users.find({}):
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
    await asyncio.sleep(60)
    while True:
        try:
            now = datetime.datetime.now()
            reminder_cursor = vip_orders.find({"status": "Waiting Payment", "reminder_sent": {"$ne": True}})
            async for order in reminder_cursor:
                if (now - order["created_at"]).total_seconds() > 900:
                    try:
                        await client.send_message(order["user_id"], f"⏳ **Order Reminder:** Your VIP payment order `{order['order_id']}` is waiting. Have you completed the payment? Please submit your UTR if you have!")
                        await update_order_state(order["order_id"], "Reminder Sent", {"reminder_sent": True})
                    except: pass
            
            expiry_cursor = vip_orders.find({"status": {"$in": ["Created", "Waiting Payment", "Reminder Sent"]}})
            async for order in expiry_cursor:
                if (now - order["created_at"]).total_seconds() > 1800:
                    await update_order_state(order["order_id"], "Expired")

            tomorrow = now + datetime.timedelta(days=1)
            warn_cursor = vip_users.find({"status": "Active", "expiry": {"$lte": tomorrow, "$gte": now}, "notice_24h": {"$ne": True}})
            async for v in warn_cursor:
                try:
                    await client.send_message(v["user_id"], f"⚠️ **VIP EXPIRING SOON!**\n\nYour `{v['plan']}` membership will expire in less than 24 hours. Use `/buyvip` to renew your access!")
                    await vip_users.update_one({"_id": v["_id"]}, {"$set": {"notice_24h": True}})
                except: pass
        except Exception as e: logger.error(f"VIP Worker Error: {e}")
        await asyncio.sleep(300)

# ==========================================
# 💳 PAYMENT & PURCHASE FLOW (USERS)
# ==========================================
@Client.on_message(filters.command("buyvip"), group=-1)
async def buy_vip_command(client, message):
    plans = await get_all_plans()
    out = "💎 **PREMIUM VIP MEMBERSHIPS**\n\n"
    for k, p in plans.items():
        limits = p.get("limits", {})
        feat_str = (
            f"  ✓ No Ads / Direct Files\n"
            f"  ✓ Multi-Search: {limits.get('multi_search_limit', 1)} Movies\n"
            f"  ✓ Bulk Download: {limits.get('bulk_select_limit', 10)} Files\n"
            f"  ✓ Connect Groups: {limits.get('group_connect_limit', 1)}\n"
            f"  ✓ Request Cooldown: {limits.get('movie_request_cooldown', 60)} Mins"
        )
        out += f"**{p['name']}** - ₹{p['price']} ({p['days']} Days)\n{feat_str}\n\n"
        
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(f"🛒 Buy {p['name']} (₹{p['price']})", callback_data=f"vip_buy_{k}", style=ButtonStyle.PRIMARY)] for k, p in plans.items()])
    await message.reply(out + "👇 **Select a plan below to securely generate your order:**", reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vip_buy_"))
async def vip_buy_callback(client, callback: CallbackQuery):
    plan_key = callback.data.split("_")[2]
    plans = await get_all_plans()
    plan = plans[plan_key]
    order_id = generate_order_id(plan_key)
    
    await vip_orders.insert_one({
        "order_id": order_id, "user_id": callback.from_user.id, "plan": plan_key, "amount": plan['price'], 
        "status": "Waiting Payment", "created_at": datetime.datetime.now(), "admin_notes": [],
        "timeline": [{"status": "Created", "time": datetime.datetime.now()}]
    })
    
    # 🚀 FIX 1: Removing spaces from the Transaction Note. 
    # PhonePe & GPay scanners drop the note if it contains spaces or %20.
    encoded_name = urllib.parse.quote(MERCHANT_NAME)
    clean_note = f"VIP_Order_{order_id}"
    
    upi_url = f"upi://pay?pa={UPI_ID}&pn={encoded_name}&am={plan['price']}&tr={order_id}&cu=INR&tn={clean_note}"
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={urllib.parse.quote(upi_url)}"
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I have Paid", callback_data=f"vip_paid_{order_id}", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("❌ Cancel Order", callback_data=f"vip_cancel_{order_id}", style=ButtonStyle.DANGER)]
    ])
    
    text = (
        f"💳 **Order ID:** `{order_id}`\n📦 **Plan:** {plan['name']}\n💵 **Amount:** ₹{plan['price']}\n\n"
        f"**🏦 HOW TO PAY:**\n\n"
        f"📱 **Mobile Users:** [👉 TAP HERE TO PAY DIRECTLY]({upi_url})\n*(Opens GPay, PhonePe, Paytm automatically)*\n\n" # 🚀 FIX 2: Mobile Deep Link!
        f"1️⃣ **Tap to Copy UPI ID:**\n`{UPI_ID}`\n\n       **(OR)**        \n\n"
        f"2️⃣ **Scan QR Code:**\n[Click Here to view QR Code image]({qr_link})\n\n"
        f"⚠️ *After sending exactly ₹{plan['price']}, you MUST click '✅ I have Paid' within 30 mins.*"
    )
    await callback.message.edit_text(text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=False))

@Client.on_callback_query(filters.regex(r"^vip_cancel_"))
async def vip_cancel_callback(client, callback: CallbackQuery):
    USER_STATES.pop(callback.from_user.id, None) # Clear any state
    order_id = callback.data.split("_")[2]
    await update_order_state(order_id, "Rejected")
    await callback.message.edit_text("❌ Order Cancelled successfully.")

@Client.on_callback_query(filters.regex(r"^vip_paid_"))
async def vip_paid_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if not order: return await callback.answer("Order not found!", show_alert=True)
        
    if order["status"] == "Expired":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, I Already Paid", callback_data=f"vip_recover_{order_id}", style=ButtonStyle.SUCCESS)], [InlineKeyboardButton("🔄 Create New Order", callback_data="vip_reorder", style=ButtonStyle.PRIMARY)]])
        return await callback.message.edit_text("⚠️ **Your payment order has expired.**\n\nDid you already complete the payment before it expired?", reply_markup=markup)

    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": False}
    await callback.message.edit_text("📝 **Please send the 12-Digit UPI Reference Number (UTR) or a Screenshot of the payment.**")

@Client.on_callback_query(filters.regex(r"^vip_recover_"))
async def vip_recover_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": True}
    await callback.message.edit_text("🔄 **PAYMENT RECOVERY QUEUE**\n\n📝 Please send the 12-Digit UTR or a Screenshot. Our admin will manually verify and recover your expired order.")


# ==========================================
# 💎 UNIVERSAL VIP ENTERPRISE DASHBOARD (/vippanel)
# ==========================================
def get_dashboard_main_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Memberships", callback_data="vipdb_members", style=ButtonStyle.PRIMARY), InlineKeyboardButton("💳 Payments", callback_data="vipdb_payments", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🎟️ Coupons", callback_data="vipdb_coupons", style=ButtonStyle.PRIMARY), InlineKeyboardButton("📦 Plans", callback_data="vipdb_plans", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("📊 Statistics", callback_data="vipdb_stats", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🎁 Promotions", callback_data="vipdb_promos", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("⚙️ Settings", callback_data="vipdb_settings", style=ButtonStyle.PRIMARY), InlineKeyboardButton("📜 Logs", callback_data="vipdb_logs", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("🔍 Universal Search", callback_data="vipdb_search", style=ButtonStyle.SUCCESS), InlineKeyboardButton("⚡ Live Activity", callback_data="vipdb_live", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("❌ Close Panel", callback_data="vipdb_close", style=ButtonStyle.DANGER)]
    ])

@Client.on_message(filters.command("vippanel") & filters.user(Config.ADMINS), group=-1)
async def open_vip_panel(client, message):
    USER_STATES.pop(message.from_user.id, None) # Clear state on panel open
    await message.reply("💎 **VIP ENTERPRISE DASHBOARD**\nSelect a module to manage:", reply_markup=get_dashboard_main_markup())
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vipdb_") & filters.user(Config.ADMINS))
async def vip_panel_router(client, callback: CallbackQuery):
    # 🔥 CRITICAL FIX: ALWAYS clear active text wizards if an admin clicks a dashboard button
    USER_STATES.pop(callback.from_user.id, None)
    
    action = callback.data.split("_")[1]
    
    if action == "close": 
        return await callback.message.delete()
        
    elif action == "home":
        await callback.message.edit_text("💎 **VIP ENTERPRISE DASHBOARD**\nSelect a module to manage:", reply_markup=get_dashboard_main_markup())
        
    elif action == "members":
        active = await vip_users.count_documents({"status": "Active"})
        expired = await vip_users.count_documents({"status": "Expired"})
        bronze = await vip_users.count_documents({"plan": "🥉 Bronze", "status": "Active"})
        silver = await vip_users.count_documents({"plan": "🥈 Silver", "status": "Active"})
        gold = await vip_users.count_documents({"plan": "🥇 Gold", "status": "Active"})
        lifetime = await vip_users.count_documents({"plan": "💎 Lifetime", "status": "Active"})
        
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + datetime.timedelta(days=1)
        day_after = tomorrow + datetime.timedelta(days=1)
        
        new_vip = await vip_users.count_documents({"joined": {"$gte": today}})
        expiring_today = await vip_users.count_documents({"expiry": {"$gte": today, "$lt": tomorrow}, "status": "Active"})
        expiring_tom = await vip_users.count_documents({"expiry": {"$gte": tomorrow, "$lt": day_after}, "status": "Active"})
        
        text = (
            "👥 **Membership Center**\n\n"
            f"🟢 Active VIP: `{active}`\n🔴 Expired: `{expired}`\n\n"
            f"🥉 Bronze: `{bronze}`\n🥈 Silver: `{silver}`\n🥇 Gold: `{gold}`\n💎 Lifetime: `{lifetime}`\n"
            "━━━━━━━━━━\n"
            f"🌟 Today's New VIP: `{new_vip}`\n"
            f"⏳ Expiring Today: `{expiring_today}`\n"
            f"⌛ Expiring Tomorrow: `{expiring_tom}`\n"
            "━━━━━━━━━━"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add VIP", callback_data="vipwiz_addvip_init", style=ButtonStyle.SUCCESS), InlineKeyboardButton("➖ Remove VIP", callback_data="vipwiz_remvip_init", style=ButtonStyle.DANGER)],
            [InlineKeyboardButton("⏫ Extend", callback_data="vipwiz_extvip_init", style=ButtonStyle.PRIMARY), InlineKeyboardButton("⏬ Reduce", callback_data="vipwiz_redvip_init", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔄 Set VIP", callback_data="vipwiz_setvip_init", style=ButtonStyle.PRIMARY), InlineKeyboardButton("🔍 Search VIP", callback_data="vipdb_search", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_members", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

    elif action == "payments":
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        this_month = today.replace(day=1)
        
        pending = await vip_orders.count_documents({"status": "Waiting Payment"})
        app_today = await vip_orders.count_documents({"status": "Approved", "approved_at": {"$gte": today}})
        rejected = await vip_orders.count_documents({"status": "Rejected"})
        recovery = await vip_recovery.count_documents({"status": "Pending Verification"})
        
        rev_today_cur = await vip_orders.aggregate([{"$match": {"status": "Approved", "approved_at": {"$gte": today}}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]).to_list(1)
        rev_today = rev_today_cur[0]["total"] if rev_today_cur else 0
        
        rev_month_cur = await vip_orders.aggregate([{"$match": {"status": "Approved", "approved_at": {"$gte": this_month}}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]).to_list(1)
        rev_month = rev_month_cur[0]["total"] if rev_month_cur else 0
        
        rev_life_cur = await vip_orders.aggregate([{"$match": {"status": "Approved"}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]).to_list(1)
        rev_life = rev_life_cur[0]["total"] if rev_life_cur else 0
        
        text = (
            "💳 **Payment Center**\n\n"
            f"⏳ Pending: `{pending}`\n✅ Approved Today: `{app_today}`\n❌ Rejected: `{rejected}`\n🔄 Recovery Queue: `{recovery}`\n"
            "━━━━━━━━━━\n"
            f"💵 Today's Revenue: `₹{rev_today:,}`\n"
            f"📅 This Month: `₹{rev_month:,}`\n"
            f"🏦 Lifetime Revenue: `₹{rev_life:,}`\n"
            "━━━━━━━━━━"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Search Order/UTR", callback_data="vipdb_search", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_payments", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

    elif action == "coupons":
        active = await vip_coupons.count_documents({"status": "Active"})
        used = await vip_coupons.count_documents({"status": "Used"})
        expired = await vip_coupons.count_documents({"status": "Expired"})
        
        gold = await vip_coupons.count_documents({"plan_target": "gold"})
        silver = await vip_coupons.count_documents({"plan_target": "silver"})
        
        text = (
            "🎟️ **Coupon Center**\n\n"
            f"🟢 Active: `{active}`\n🔴 Used: `{used:,}`\n🕰️ Expired: `{expired}`\n"
            "━━━━━━━━━━\n"
            f"🥇 Gold Coupons: `{gold}`\n🥈 Silver Coupons: `{silver}`\n"
            "━━━━━━━━━━"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Create", callback_data="vipwiz_addcoup_init", style=ButtonStyle.SUCCESS), InlineKeyboardButton("➖ Delete", callback_data="vipwiz_delcoup_init", style=ButtonStyle.DANGER)],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_coupons", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)
        
    elif action == "plans":
        plans = await get_all_plans()
        text = "📦 **Plans Configuration**\n\n"
        for k, p in plans.items():
            lims = p.get("limits", {})
            text += f"**{p['name']}**\n₹{p['price']} | {p['days']} Days\nLimits: Multi:{lims.get('multi_search_limit',1)} | Bulk:{lims.get('bulk_select_limit',10)}\n━━━━━━━━━━\n"
            
        markup = InlineKeyboardMarkup([
            # 🚀 UPGRADE: Added "Edit Plan" Button next to Add Plan
            [InlineKeyboardButton("➕ Add Plan", callback_data="vipwiz_addplan_init", style=ButtonStyle.SUCCESS), InlineKeyboardButton("✏️ Edit Plan", callback_data="vipwiz_editplan_init", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("➖ Delete Plan", callback_data="vipwiz_delplan_init", style=ButtonStyle.DANGER)],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_plans", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)
        
    elif action == "stats":
        active_vips = await vip_users.count_documents({"status": "Active"})
        expired_vips = await vip_users.count_documents({"status": "Expired"})
        orders = await vip_orders.count_documents({})
        revenue_cur = await vip_orders.aggregate([{"$match": {"status": "Approved"}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]).to_list(1)
        revenue = revenue_cur[0]["total"] if revenue_cur else 0
        
        text = (
            "📊 **VIP Statistics**\n\n"
            f"👥 Active VIP: `{active_vips}`\n🔴 Expired VIP: `{expired_vips}`\n"
            f"💵 Total Revenue: `₹{revenue:,}`\n🛒 Total Orders: `{orders}`\n"
            "━━━━━━━━━━\n"
            "📈 *Detailed tracking and conversion rate analytics are running in the background.*"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_stats", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

    elif action == "promos":
        text = "🎁 **Promotion Center**\n\nManage compensation, holiday events, and free access blasts."
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Compensate Users", callback_data="vipwiz_comp_init", style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_promos", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

    elif action == "settings":
        text = (
            "⚙ **VIP Settings**\n\n"
            f"🏦 **UPI ID:** `{UPI_ID}`\n"
            f"🏢 **Merchant Name:** `{MERCHANT_NAME}`\n"
            "⏱ **Payment Timeout:** `30 Mins`\n"
            "⏳ **Reminder Time:** `15 Mins`\n"
            "🔄 **Recovery Queue:** `Enabled`\n"
            "🌐 **Timezone:** `IST`"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)
        
    elif action == "logs":
        today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        logs_today = await vip_history.count_documents({"timestamp": {"$gte": today}})
        pays_today = await vip_orders.count_documents({"status": "Approved", "approved_at": {"$gte": today}})
        
        text = (
            "📜 **VIP Logs**\n\n"
            f"📝 Today's Actions: `{logs_today}`\n"
            f"💳 Payments: `{pays_today}`\n"
            f"🔄 Recent Recoveries & Compensations tracked.\n"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_logs", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

    elif action == "search":
        USER_STATES[callback.from_user.id] = {"action": "wiz_search", "msg_id": callback.message.id}
        await callback.message.edit_text("🔍 **Wizard: Universal Search**\n\nReply with any User ID, Username, Order ID, UTR, or Coupon code to scan the entire system.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_home", style=ButtonStyle.DANGER)]]))

    elif action == "live":
        history = await vip_history.find({}).sort("timestamp", -1).limit(10).to_list(10)
        text = "⚡ **Live Activity Stream**\n\n"
        for h in history:
            time_str = h["timestamp"].strftime("%H:%M:%S")
            text += f"`{time_str}` | {h['action']} | `{h['user_id']}`\n"
        if not history: text += "No recent activity."
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.DANGER), InlineKeyboardButton("🔄 Refresh", callback_data="vipdb_live", style=ButtonStyle.SUCCESS)]
        ])
        await callback.message.edit_text(text, reply_markup=markup)

# ==========================================
# 🧙‍♂️ INTERACTIVE WIZARDS (Button-Driven Flows)
# ==========================================
@Client.on_callback_query(filters.regex(r"^vipwiz_") & filters.user(Config.ADMINS))
async def admin_wizards_router(client, callback: CallbackQuery):
    action = callback.data.replace("vipwiz_", "")
    msg_id = callback.message.id
    
    # --- UNIVERSAL SEARCH WIZARD ---
    if action == "search_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_search", "msg_id": msg_id}
        await callback.message.edit_text("🔍 **Wizard: Universal Search**\n\nReply with any ID, Username, Order ID, UTR, or Coupon.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_home", style=ButtonStyle.DANGER)]]))

    # --- ADD VIP WIZARD ---
    elif action == "addvip_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_addvip_uid", "msg_id": msg_id}
        await callback.message.edit_text("👤 **Wizard: Add VIP**\n\nPlease reply with the **User ID** you want to upgrade.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    elif action.startswith("addvip_plan_"):
        parts = action.split("_")
        target = parts[2]
        plan_key = parts[3]
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("7 Days", callback_data=f"vipwiz_addvip_exec_{target}_{plan_key}_7", style=ButtonStyle.PRIMARY), InlineKeyboardButton("30 Days", callback_data=f"vipwiz_addvip_exec_{target}_{plan_key}_30", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("90 Days", callback_data=f"vipwiz_addvip_exec_{target}_{plan_key}_90", style=ButtonStyle.PRIMARY), InlineKeyboardButton("365 Days", callback_data=f"vipwiz_addvip_exec_{target}_{plan_key}_365", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]
        ])
        await callback.message.edit_text(f"👤 Target: `{target}`\n📦 Plan: `{plan_key.capitalize()}`\n\n⏱️ **Select Duration:**", reply_markup=markup)

    elif action.startswith("addvip_exec_"):
        parts = action.split("_")
        target, plan_key, days = parts[2], parts[3], int(parts[4])
        try: user_obj = await client.get_users(int(target))
        except: user_obj = int(target)
        plans = await get_all_plans()
        plan_name = plans[plan_key]["name"]
        
        await add_vip(user_obj, plan_name, days, method="Wizard Injection", gifted_by=callback.from_user.id)
        await callback.message.edit_text(f"✅ **Success!**\n\nAdded {days} Days of {plan_name} to `{target}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Memberships", callback_data="vipdb_members", style=ButtonStyle.PRIMARY)]]))

    # --- REMOVE VIP WIZARD ---
    elif action == "remvip_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_remvip", "msg_id": msg_id}
        await callback.message.edit_text("➖ **Wizard: Remove VIP**\n\nReply with the **User ID** to revoke.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    # --- EXTEND VIP WIZARD ---
    elif action == "extvip_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_extvip", "msg_id": msg_id}
        await callback.message.edit_text("⏫ **Wizard: Extend VIP**\n\nReply with the **User ID**.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    elif action.startswith("extvip_exec_"):
        parts = action.split("_")
        target, days = int(parts[2]), int(parts[3])
        user = await vip_users.find_one({"user_id": target})
        if user:
            new_exp = user["expiry"] + datetime.timedelta(days=days)
            await vip_users.update_one({"user_id": target}, {"$set": {"expiry": new_exp}})
            await log_vip_event("Extended", target, f"Added {days} days", callback.from_user.id)
            await callback.message.edit_text(f"✅ Added {days} days to `{target}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Memberships", callback_data="vipdb_members", style=ButtonStyle.PRIMARY)]]))
        else:
            await callback.message.edit_text("❌ User is not an active VIP.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    # --- REDUCE VIP WIZARD ---
    elif action == "redvip_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_redvip", "msg_id": msg_id}
        await callback.message.edit_text("⏬ **Wizard: Reduce VIP**\n\nReply with the **User ID**.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    elif action.startswith("redvip_exec_"):
        parts = action.split("_")
        target, days = int(parts[2]), int(parts[3])
        user = await vip_users.find_one({"user_id": target})
        if user:
            new_exp = user["expiry"] - datetime.timedelta(days=days)
            await vip_users.update_one({"user_id": target}, {"$set": {"expiry": new_exp}})
            await log_vip_event("Reduced", target, f"Removed {days} days", callback.from_user.id)
            await callback.message.edit_text(f"✅ Removed {days} days from `{target}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Memberships", callback_data="vipdb_members", style=ButtonStyle.PRIMARY)]]))
        else:
            await callback.message.edit_text("❌ User is not an active VIP.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    # --- SET VIP WIZARD ---
    elif action == "setvip_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_setvip_uid", "msg_id": msg_id}
        await callback.message.edit_text("🔄 **Wizard: Set VIP (Overwrite)**\n\nReply with the **User ID**.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]]))

    # --- ADD PLAN WIZARD ---
    elif action == "addplan_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_addplan", "msg_id": msg_id}
        prompt = (
            "📦 **Wizard: Add New Plan**\n\n"
            "Reply with 8 values separated by commas:\n"
            "`Plan_ID, Price, Days, Name, MultiSearch, BulkLimit, RequestCooldown, GroupLimit`\n\n"
            "**Example:** `platinum, 1499, 180, 🌟 Platinum, 15, 1000, 0, 10`"
        )
        await callback.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_plans", style=ButtonStyle.DANGER)]]))

    # 🚀 UPGRADE: --- EDIT PLAN WIZARD ---
    elif action == "editplan_init":
        plans = await get_all_plans()
        markup = [[InlineKeyboardButton(f"✏️ Edit {p['name']}", callback_data=f"vipwiz_editplan_sel_{k}", style=ButtonStyle.PRIMARY)] for k, p in plans.items()]
        markup.append([InlineKeyboardButton("❌ Cancel", callback_data="vipdb_plans", style=ButtonStyle.DANGER)])
        await callback.message.edit_text("📦 **Wizard: Edit Plan**\n\nSelect a plan to modify:", reply_markup=InlineKeyboardMarkup(markup))

    elif action.startswith("editplan_sel_"):
        plan_key = action.split("_")[2]
        plans = await get_all_plans()
        p = plans[plan_key]
        USER_STATES[callback.from_user.id] = {"action": "wiz_editplan", "msg_id": msg_id, "plan_key": plan_key}
        
        prompt = (
            f"✏️ **Editing Plan:** `{p['name']}`\n"
            f"Current Price: ₹{p['price']} | Days: {p['days']}\n\n"
            "Reply with 7 new values separated by commas:\n"
            "`Price, Days, Name, MultiSearch, BulkLimit, RequestCooldown, GroupLimit`\n\n"
            "**Example:** `199, 30, 🌟 Premium Bronze, 5, 100, 15, 2`"
        )
        await callback.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_plans", style=ButtonStyle.DANGER)]]))

    # --- DELETE PLAN WIZARD ---
    elif action == "delplan_init":
        plans = await get_all_plans()
        markup = [[InlineKeyboardButton(f"🗑️ Delete {p['name']}", callback_data=f"vipwiz_delplan_exec_{k}", style=ButtonStyle.DANGER)] for k, p in plans.items()]
        markup.append([InlineKeyboardButton("❌ Cancel", callback_data="vipdb_plans", style=ButtonStyle.PRIMARY)])
        await callback.message.edit_text("📦 **Wizard: Delete Plan**\n\nSelect a plan to delete completely:", reply_markup=InlineKeyboardMarkup(markup))

    elif action.startswith("delplan_exec_"):
        plan_key = action.split("_")[2]
        await vip_plans_db.delete_one({"_id": plan_key})
        await callback.message.edit_text(f"✅ Deleted Plan `{plan_key}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Plans", callback_data="vipdb_plans", style=ButtonStyle.PRIMARY)]]))

    # --- CREATE COUPON WIZARD ---
    elif action == "addcoup_init":
        plans = await get_all_plans()
        markup = [[InlineKeyboardButton(p["name"], callback_data=f"vipwiz_addcoup_plan_{k}", style=ButtonStyle.PRIMARY)] for k, p in plans.items()]
        markup.append([InlineKeyboardButton("❌ Cancel", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)])
        await callback.message.edit_text("🎟️ **Wizard: Create Coupon**\n\n📦 **Select Target Plan:**", reply_markup=InlineKeyboardMarkup(markup))

    elif action.startswith("addcoup_plan_"):
        plan_key = action.split("_")[2]
        USER_STATES[callback.from_user.id] = {"action": "wiz_addcoup_prefix", "msg_id": msg_id, "plan": plan_key}
        await callback.message.edit_text(f"📦 Plan: `{plan_key.capitalize()}`\n\n🔡 **Please reply with a short Prefix (e.g., GLD):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)]]))

    elif action.startswith("addcoup_qty_"):
        parts = action.split("_")
        plan, prefix, qty = parts[2], parts[3], int(parts[4])
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Day", callback_data=f"vipwiz_addcoup_exec_{plan}_{prefix}_{qty}_1", style=ButtonStyle.PRIMARY), InlineKeyboardButton("7 Days", callback_data=f"vipwiz_addcoup_exec_{plan}_{prefix}_{qty}_7", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("30 Days", callback_data=f"vipwiz_addcoup_exec_{plan}_{prefix}_{qty}_30", style=ButtonStyle.PRIMARY), InlineKeyboardButton("Never", callback_data=f"vipwiz_addcoup_exec_{plan}_{prefix}_{qty}_36500", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)]
        ])
        await callback.message.edit_text(f"📦 Plan: `{plan.capitalize()}`\n🔢 Qty: `{qty}`\n\n⏳ **Select when unused codes expire:**", reply_markup=markup)

    elif action.startswith("addcoup_exec_"):
        parts = action.split("_")
        plan_target, prefix, qty, exp_days = parts[2], parts[3], int(parts[4]), int(parts[5])
        
        expiry = datetime.datetime.now() + datetime.timedelta(days=exp_days)
        generated = []
        for _ in range(qty):
            token = f"{prefix}-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            await vip_coupons.insert_one({
                "code": token, "plan_target": plan_target, "status": "Active", "created_at": datetime.datetime.now(),
                "max_uses": 1, "remaining_uses": 1, "expiry": expiry, "created_by": callback.from_user.id
            })
            generated.append(token)
            
        file_buffer = io.BytesIO("\n".join(generated).encode('utf-8'))
        file_buffer.name = f"{prefix}_Coupons.txt"
        await callback.message.reply_document(file_buffer, caption=f"🎟️ **Batch Generation Complete!**\nTarget: `{plan_target.capitalize()}` | Qty: `{qty}`")
        await callback.message.edit_text("✅ Coupons generated successfully.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Coupons", callback_data="vipdb_coupons", style=ButtonStyle.PRIMARY)]]))

    # --- DELETE COUPON WIZARD ---
    elif action == "delcoup_init":
        USER_STATES[callback.from_user.id] = {"action": "wiz_delcoup", "msg_id": msg_id}
        await callback.message.edit_text("➖ **Wizard: Delete Coupon**\n\nReply with the exact **Coupon Code** to delete.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)]]))

    # --- COMPENSATE WIZARD ---
    elif action == "comp_init":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("All Users", callback_data="vipwiz_comp_targ_all", style=ButtonStyle.PRIMARY), InlineKeyboardButton("Active VIPs", callback_data="vipwiz_comp_targ_vip", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Bronze VIPs", callback_data="vipwiz_comp_targ_bronze", style=ButtonStyle.PRIMARY), InlineKeyboardButton("Gold VIPs", callback_data="vipwiz_comp_targ_gold", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_promos", style=ButtonStyle.DANGER)]
        ])
        await callback.message.edit_text("🎁 **Wizard: Compensate**\n\n👥 **Select Target Group:**", reply_markup=markup)

    elif action.startswith("comp_targ_"):
        target = action.split("_")[2]
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("+1 Day", callback_data=f"vipwiz_comp_exec_{target}_1", style=ButtonStyle.PRIMARY), InlineKeyboardButton("+3 Days", callback_data=f"vipwiz_comp_exec_{target}_3", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("+7 Days", callback_data=f"vipwiz_comp_exec_{target}_7", style=ButtonStyle.PRIMARY), InlineKeyboardButton("+15 Days", callback_data=f"vipwiz_comp_exec_{target}_15", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_promos", style=ButtonStyle.DANGER)]
        ])
        await callback.message.edit_text(f"👥 Target: `{target.capitalize()}`\n\n⏱️ **Select Days to Add:**", reply_markup=markup)

    elif action.startswith("comp_exec_"):
        parts = action.split("_")
        target, days = parts[2], int(parts[3])
        
        target_list = await parse_target_users(client, [target])
        count = 0
        for uid in target_list:
            user = await vip_users.find_one({"user_id": uid})
            if user:
                new_exp = user["expiry"] + datetime.timedelta(days=days)
                await vip_users.update_one({"user_id": uid}, {"$set": {"expiry": new_exp}})
                await log_vip_event("Compensated", uid, f"Added {days} extra days via Wizard", callback.from_user.id)
                count += 1
                
        await callback.message.edit_text(f"✅ **Compensation Complete!**\n\nAdded {days} days to `{count}` active accounts.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Promos", callback_data="vipdb_promos", style=ButtonStyle.PRIMARY)]]))


# ==========================================
# 📸 CATCH USER INPUT (UTR & TEXT WIZARDS)
# ==========================================
@Client.on_message(filters.private & ~filters.regex(r"^/"), group=-1)
async def catch_payment_proof(client, message: Message):
    state = USER_STATES.get(message.from_user.id)
    if not state: raise ContinuePropagation
    
    action = state.get("action")
    
    # --- ADMIN WIZARD INPUT CATCHERS (CRASH-PROOFED) ---
    if action.startswith("wiz_"):
        try: await message.delete() # Keep chat clean
        except: pass
        
        msg_id = state["msg_id"]
        
        try:
            if action == "wiz_search":
                q = message.text.strip()
                criteria = {"$or": []}
                if q.isdigit(): criteria["$or"].append({"user_id": int(q)})
                criteria["$or"].extend([
                    {"username": {"$regex": q, "$options": "i"}},
                    {"first_name": {"$regex": q, "$options": "i"}},
                    {"order_id": {"$regex": q, "$options": "i"}},
                    {"trx_id": {"$regex": q, "$options": "i"}}
                ])
                results = await vip_users.find(criteria).to_list(length=10)
                out = f"🔍 **Search Results for:** `{q}`\n\n"
                for r in results:
                    out += f"👤 `{r['user_id']}` ({r.get('username','N/A')})\nTier: {r['plan']} | Exp: {r['expiry'].strftime('%Y-%m-%d')}\n\n"
                if not results: out += "❌ No user records found."
                
                await client.edit_message_text(message.chat.id, msg_id, out, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="vipdb_home", style=ButtonStyle.PRIMARY)]]))

            elif action == "wiz_addvip_uid" or action == "wiz_setvip_uid":
                target = message.text.strip()
                plans = await get_all_plans()
                markup = []
                for k, p in plans.items():
                    call_data = f"vipwiz_addvip_plan_{target}_{k}"
                    markup.append([InlineKeyboardButton(p["name"], callback_data=call_data, style=ButtonStyle.PRIMARY)])
                markup.append([InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)])
                
                await client.edit_message_text(message.chat.id, msg_id, f"👤 **Target:** `{target}`\n\n📦 **Select Plan:**", reply_markup=InlineKeyboardMarkup(markup))
                
            elif action == "wiz_remvip":
                target = int(message.text.strip())
                await vip_users.delete_many({"user_id": target})
                await log_vip_event("Removed", target, "VIP access forcefully revoked via Wizard", message.from_user.id)
                await client.edit_message_text(message.chat.id, msg_id, f"✅ Revoked VIP access from `{target}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Memberships", callback_data="vipdb_members", style=ButtonStyle.PRIMARY)]]))

            elif action == "wiz_extvip" or action == "wiz_redvip":
                target = int(message.text.strip()) # Enforce int check
                prefix = "extvip" if action == "wiz_extvip" else "redvip"
                sign = "+" if action == "wiz_extvip" else "-"
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{sign}7 Days", callback_data=f"vipwiz_{prefix}_exec_{target}_7", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{sign}15 Days", callback_data=f"vipwiz_{prefix}_exec_{target}_15", style=ButtonStyle.PRIMARY)],
                    [InlineKeyboardButton(f"{sign}30 Days", callback_data=f"vipwiz_{prefix}_exec_{target}_30", style=ButtonStyle.PRIMARY), InlineKeyboardButton(f"{sign}90 Days", callback_data=f"vipwiz_{prefix}_exec_{target}_90", style=ButtonStyle.PRIMARY)],
                    [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_members", style=ButtonStyle.DANGER)]
                ])
                await client.edit_message_text(message.chat.id, msg_id, f"👤 Target: `{target}`\n\n⏱️ Select days to adjust:", reply_markup=markup)

            elif action == "wiz_addplan":
                parts = [p.strip() for p in message.text.split(",")]
                if len(parts) >= 8:
                    k, price, days, name = parts[0].lower(), int(parts[1]), int(parts[2]), parts[3]
                    multi_l, bulk_l, req_c, grp_l = int(parts[4]), int(parts[5]), int(parts[6]), int(parts[7])
                    
                    new_limits = {
                        "shortlink_bypass": True, "multi_search_limit": multi_l,
                        "bulk_select_limit": bulk_l, "movie_request_cooldown": req_c,
                        "group_connect_limit": grp_l
                    }
                    
                    await vip_plans_db.update_one({"_id": k}, {"$set": {"name": name, "price": price, "days": days, "limits": new_limits}}, upsert=True)
                    await client.edit_message_text(message.chat.id, msg_id, f"✅ Added New Plan `{name}`.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Plans", callback_data="vipdb_plans", style=ButtonStyle.PRIMARY)]]))
                else:
                    await client.edit_message_text(message.chat.id, msg_id, "❌ Error parsing format. Please provide all 8 values.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Plans", callback_data="vipdb_plans", style=ButtonStyle.DANGER)]]))

            # 🚀 UPGRADE: --- EDIT PLAN CATCHER ---
            elif action == "wiz_editplan":
                plan_key = state["plan_key"]
                parts = [p.strip() for p in message.text.split(",")]
                if len(parts) >= 7:
                    price, days, name = int(parts[0]), int(parts[1]), parts[2]
                    multi_l, bulk_l, req_c, grp_l = int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
                    
                    new_limits = {
                        "shortlink_bypass": True, "multi_search_limit": multi_l,
                        "bulk_select_limit": bulk_l, "movie_request_cooldown": req_c,
                        "group_connect_limit": grp_l
                    }
                    
                    await vip_plans_db.update_one({"_id": plan_key}, {"$set": {"name": name, "price": price, "days": days, "limits": new_limits}}, upsert=True)
                    await client.edit_message_text(message.chat.id, msg_id, f"✅ Successfully updated Plan `{name}` with new dynamic limits.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Plans", callback_data="vipdb_plans", style=ButtonStyle.PRIMARY)]]))
                else:
                    await client.edit_message_text(message.chat.id, msg_id, "❌ Error parsing format. Please provide all 7 values separated by commas.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Plans", callback_data="vipdb_plans", style=ButtonStyle.DANGER)]]))

            elif action == "wiz_delcoup":
                code = message.text.strip().upper()
                res = await vip_coupons.delete_one({"code": code})
                if res.deleted_count > 0:
                    await client.edit_message_text(message.chat.id, msg_id, f"✅ Coupon `{code}` deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Coupons", callback_data="vipdb_coupons", style=ButtonStyle.PRIMARY)]]))
                else:
                    await client.edit_message_text(message.chat.id, msg_id, f"❌ Coupon not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Coupons", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)]]))

            elif action == "wiz_addcoup_prefix":
                prefix = message.text.strip().upper()
                plan = state.get("plan")
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("1", callback_data=f"vipwiz_addcoup_qty_{plan}_{prefix}_1", style=ButtonStyle.PRIMARY), InlineKeyboardButton("5", callback_data=f"vipwiz_addcoup_qty_{plan}_{prefix}_5", style=ButtonStyle.PRIMARY)],
                    [InlineKeyboardButton("10", callback_data=f"vipwiz_addcoup_qty_{plan}_{prefix}_10", style=ButtonStyle.PRIMARY), InlineKeyboardButton("50", callback_data=f"vipwiz_addcoup_qty_{plan}_{prefix}_50", style=ButtonStyle.PRIMARY)],
                    [InlineKeyboardButton("❌ Cancel", callback_data="vipdb_coupons", style=ButtonStyle.DANGER)]
                ])
                await client.edit_message_text(message.chat.id, msg_id, f"🎟️ **Prefix:** `{prefix}`\n\n🔢 **Select Quantity to Generate:**", reply_markup=markup)

        except ValueError:
            await client.send_message(message.chat.id, "❌ **Input Error:** You entered text when a Number (ID) was expected. Wizard cancelled.")
        except Exception as e:
            await client.send_message(message.chat.id, f"❌ **Wizard Error:** {e}")
        finally:
            # 🔥 CRITICAL FIX: ALWAYS clear the state so you don't get trapped deleting messages!
            USER_STATES.pop(message.from_user.id, None)
            raise StopPropagation

    # --- UTR PAYMENT CATCHER ---
    if action == "wait_utr":
        try:
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
                await vip_recovery.insert_one({"order_id": order_id, "user_id": message.from_user.id, "utr": utr, "status": "Pending Verification", "submitted_at": datetime.datetime.now()})
                await update_order_state(order_id, "Recovery Queued", {"utr": utr})
                notify_text = "🔄 **Sent to Recovery Queue!** Admin will manually trace your payment."
                admin_flag = "🚨 **RECOVERY QUEUE SUBMISSION**"
            else:
                await update_order_state(order_id, "Payment Submitted", {"utr": utr, "submitted_at": datetime.datetime.now()})
                notify_text = "✅ **Payment Proof Submitted!** Order moved to 'Under Review'."
                admin_flag = "🚨 **NEW PAYMENT SUBMITTED**"
                
            await message.reply(notify_text)
            
            admin_text = (
                f"{admin_flag}\n\n👤 User: {message.from_user.mention} (`{message.from_user.id}`)\n"
                f"💳 Order ID: `{order_id}`\n📦 Plan: {order['plan']}\n💵 Amount: ₹{order['amount']}\n🧾 UTR: `{utr}`\n"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"vip_approve_{order_id}", style=ButtonStyle.SUCCESS), InlineKeyboardButton("❌ Reject", callback_data=f"vip_reject_{order_id}", style=ButtonStyle.DANGER)],
                [InlineKeyboardButton("💬 Ask User", url=f"tg://user?id={message.from_user.id}", style=ButtonStyle.PRIMARY)]
            ])
            
            if message.photo: await client.send_photo(Config.ADMINS[0], message.photo.file_id, caption=admin_text, reply_markup=markup)
            else: await client.send_message(Config.ADMINS[0], admin_text, reply_markup=markup)
        except Exception as e:
            await message.reply(f"❌ **Error Submitting Payment:** {e}")
        finally:
            USER_STATES.pop(message.from_user.id, None)
            raise StopPropagation

# ==========================================
# 👑 ADMIN REVIEW LOGIC
# ==========================================
@Client.on_callback_query(filters.regex(r"^vip_approve_") & filters.user(Config.ADMINS))
async def admin_approve(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if order["status"] == "Approved": return await callback.answer("Already approved!", show_alert=True)
        
    await update_order_state(order_id, "Approved", {"approved_by": callback.from_user.id, "approved_at": datetime.datetime.now()})
    
    plans = await get_all_plans()
    plan = plans.get(order["plan"], DEFAULT_PLANS["bronze"])
    
    try: user_obj = await client.get_users(order["user_id"])
    except: user_obj = order["user_id"]
    
    await add_vip(user_obj, plan["name"], plan["days"], method="UPI", order_id=order_id, trx_id=order.get("utr"))
    
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVED", callback_data="noop", style=ButtonStyle.SUCCESS)]]))
    await send_vip_receipt(client, order["user_id"], order_id, plan["name"], order["amount"], order.get("utr", "N/A"), callback.from_user.id)

@Client.on_callback_query(filters.regex(r"^vip_reject_") & filters.user(Config.ADMINS))
async def admin_reject(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    await update_order_state(order_id, "Rejected")
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("❌ REJECTED", callback_data="noop", style=ButtonStyle.DANGER)]]))
    await client.send_message(order["user_id"], f"❌ **Payment Rejected**\n\nYour payment for Order `{order_id}` could not be verified. Please double check and reorder.")
    await log_vip_event("Rejected", order["user_id"], f"Order {order_id} rejected", callback.from_user.id)

# ==========================================
# 🙋‍♂️ USER REDEEM & CHECK COMMANDS
# ==========================================
@Client.on_message(filters.command("checkvip"), group=-1)
async def check_vip_cmd(client, message: Message):
    target = message.from_user.id
    if len(message.command) > 1 and message.from_user.id in Config.ADMINS: target = int(message.command[1])
    is_vip, user = await check_vip_status(target)
    if not is_vip: return await message.reply("❌ **No Active VIP Membership.**\nUse `/buyvip` to browse options!")
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
    await add_vip(message.from_user, plan_meta["name"], plan_meta["days"], method=f"Coupon ({code})")
    await log_vip_event("Coupon", message.from_user.id, f"Redeemed {code}")
    await message.reply(f"🎉 **Redemption Success!** Activated tier `{plan_meta['name']}`.")
    raise StopPropagation

# ==========================================
# 🎁 FREE TRIAL COMMAND
# ==========================================
@Client.on_message(filters.command("freetrial") & filters.user(Config.ADMINS))
async def set_free_trial_command(client: Client, message: Message):
    if len(message.command) < 2:
        settings = await db.get_settings()
        current = settings.get("free_trial_days", 7)
        status = f"{current} Days" if current > 0 else "Disabled"
        return await message.reply_text(f"🎁 **Free Trial Settings**\n\nCurrent Trial: `{status}`\n\nTo change, use:\n`/freetrial <days>` (e.g., `/freetrial 7`)\n`/freetrial 0` (to disable completely)")
    
    try:
        days = int(message.command[1])
        await db.update_settings({"free_trial_days": days})
        if days == 0:
            await message.reply_text("🚫 Free trial for new users has been **disabled**.")
        else:
            await message.reply_text(f"✅ New users will now automatically receive a **{days}-day Free Gold VIP Trial**.")
    except ValueError:
        await message.reply_text("❌ Please provide a valid number of days.")
    raise StopPropagation
