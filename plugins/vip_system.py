import random
import string
import datetime
import asyncio
import logging
import urllib.parse
from pyrogram import Client, filters, StopPropagation, ContinuePropagation
from pyrogram.enums import ButtonStyle, ChatType
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LinkPreviewOptions
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ SYSTEM STATE CORE & COLLECTIONS
# ==========================================
UPI_ID = "6303579515@ibl"
MERCHANT_NAME = "NTM GATEWAY"

USER_STATES = {} # Memory buffer for text/media wizards

vip_users = db.vip_users
vip_orders = db.vip_orders
vip_coupons = db.vip_coupons
vip_settings = db.vip_settings
vip_history = db.vip_history # Forever audit log collection

PLANS = {
    "bronze": {"name": "🥉 Bronze", "days": 30, "price": 99},
    "silver": {"name": "🥈 Silver", "days": 90, "price": 249},
    "gold": {"name": "🥇 Gold", "days": 365, "price": 799},
    "lifetime": {"name": "💎 Lifetime", "days": 36500, "price": 1999}
}

# ==========================================
# 🛡️ HELPER LOGIC ENGINE
# ==========================================
def generate_order_id(plan):
    date_str = datetime.datetime.now().strftime("%y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"VIP-{date_str}-{random_str}"

async def add_vip(user_id, plan_name, days, method="Admin Added", gifted_by=None, order_id=None, trx_id=None):
    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    
    history_entry = {
        "order_id": order_id or f"MANUAL-{generate_order_id('MANUAL')}",
        "user_id": user_id,
        "plan": plan_name,
        "amount": 0,
        "utr": trx_id or "N/A",
        "status": "Approved",
        "created_at": datetime.datetime.now(),
        "approved_at": datetime.datetime.now(),
        "approved_by": gifted_by or "System/Admin"
    }
    await vip_history.insert_one(history_entry)

    data = {
        "user_id": user_id,
        "plan": plan_name,
        "status": "Active",
        "joined": datetime.datetime.now(),
        "expiry": expiry,
        "renewals": 1,
        "coupons_used": [],
        "gifted_by": gifted_by,
        "payment_method": method,
        "order_id": order_id,
        "trx_id": trx_id
    }
    
    existing = await vip_users.find_one({"user_id": user_id})
    if existing:
        base_expiry = max(existing["expiry"], datetime.datetime.now())
        new_expiry = base_expiry + datetime.timedelta(days=days)
        await vip_users.update_one(
            {"user_id": user_id},
            {"$set": {"expiry": new_expiry, "plan": plan_name, "status": "Active"}, "$inc": {"renewals": 1}}
        )
    else:
        await vip_users.insert_one(data)

async def check_vip_status(user_id):
    user = await vip_users.find_one({"user_id": user_id})
    if not user: return False, None
    if user["plan"] == "💎 Lifetime": return True, user
    if user["expiry"] < datetime.datetime.now():
        await vip_users.update_one({"user_id": user_id}, {"$set": {"status": "Expired"}})
        return False, None
    return True, user

async def parse_target_users(client, args_list):
    """Parses user target specifiers like 'all', 'nonvip', 'vip', lists of IDs, or replies."""
    targets = []
    if not args_list: return targets
    
    selector = args_list[0].lower()
    if selector == "all":
        cursor = client.db.users.find({}) # cross references core database users
        async for u in cursor: targets.append(u["user_id"])
    elif selector == "nonvip":
        cursor = client.db.users.find({})
        async for u in cursor:
            is_vip, _ = await check_vip_status(u["user_id"])
            if not is_vip: targets.append(u["user_id"])
    elif selector == "vip":
        cursor = vip_users.find({"status": "Active"})
        async for u in cursor: targets.append(u["user_id"])
    elif selector in ["bronze", "silver", "gold", "lifetime"]:
        cursor = vip_users.find({"status": "Active", "plan": {"$regex": selector, "$options": "i"}})
        async for u in cursor: targets.append(u["user_id"])
    else:
        for item in args_list:
            if item.isdigit(): targets.append(int(item))
    return list(set(targets))

# ==========================================
# 🛠️ 2. POWER VIP MEMBERSHIP ADMINISTRATIVE ENGINE
# ==========================================
@Client.on_message(filters.command("addvip") & filters.user(Config.ADMINS), group=-1)
async def admin_add_vip_matrix(client, message: Message):
    args = message.text.split()
    if len(args) < 4:
        return await message.reply("⚠️ **Usage Syntax:**\n`/addvip <id1 id2... / all / nonvip> <Plan_Name> <days>d`")
    
    days_str = args[-1].lower().replace("d", "")
    if not days_str.isdigit(): return await message.reply("❌ Days parameter must be numeric (e.g. `30d`)")
    days = int(days_str)
    plan_name = args[-2]
    
    target_tokens = args[1:-2]
    targets = await parse_target_users(client, target_tokens)
    
    if not targets and message.reply_to_message:
        targets = [message.reply_to_message.from_user.id]
        
    if not targets: return await message.reply("❌ No valid user target structures discovered.")
    
    success_count = 0
    for uid in targets:
        try:
            await add_vip(uid, plan_name, days, method="Admin Matrix Injection", gifted_by=message.from_user.id)
            success_count += 1
        except Exception: pass
        
    await message.reply(f"🎯 **Matrix Allocation Successful!**\nGranted {days} Days of VIP Plan `{plan_name}` across `{success_count}` active accounts.")
    raise StopPropagation

@Client.on_message(filters.command("removevip") & filters.user(Config.ADMINS), group=-1)
async def admin_remove_vip_matrix(client, message: Message):
    args = message.text.split()
    if len(args) < 2: return await message.reply("⚠️ **Usage Syntax:**\n`/removevip <id1 id2... / all / Plan_Name>`")
    
    if args[1].lower() in ["all", "gold", "silver", "bronze", "lifetime"] and not message.text.endswith("-confirm"):
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Wipe Database - Confirm Action", callback_data=f"confirm_wipe_vip_{args[1].lower()}")].copy()])
        return await message.reply("⚠️ **CRITICAL CLEAR WARNING!**\nThis operation will run mass structural data deletions on your VIP registry database layers.", reply_markup=markup)
        
    targets = await parse_target_users(client, args[1:])
    if not targets and message.reply_to_message: targets = [message.reply_to_message.from_user.id]
    if not targets and args[1].lower() in ["gold", "silver", "bronze", "lifetime"]:
        await vip_users.update_many({"plan": {"$regex": args[1], "$options": "i"}}, {"$set": {"status": "Expired", "expiry": datetime.datetime.now()}})
        return await message.reply(f"🗑️ Terminated all active profiles matching plan: `{args[1]}`")

    await vip_users.delete_many({"user_id": {"$in": targets}})
    await message.reply(f"🗑️ Revoked access matrices for `{len(targets)}` accounts safely.")
    raise StopPropagation

@Client.on_message(filters.command(["extendvip", "reducevip"]) & filters.user(Config.ADMINS), group=-1)
async def admin_modify_vip_duration(client, message: Message):
    cmd = message.command[0].lower()
    args = message.text.split()
    if len(args) < 3: return await message.reply(f"⚠️ **Usage Syntax:**\n`/{cmd} <id / all / Plan> <+/- days>d`")
    
    mod_str = args[-1].lower().replace("d", "").replace("+", "").replace("-", "")
    if not mod_str.isdigit(): return await message.reply("❌ Invalid time change parameter modifier token.")
    days_delta = int(mod_str)
    if cmd == "reducevip": days_delta = -days_delta
    
    targets = await parse_target_users(client, args[1:-1])
    if not targets: return await message.reply("❌ No valid profile accounts matched criteria parameters.")
    
    mutated = 0
    async for user in vip_users.find({"user_id": {"$in": targets}}):
        new_expiry = user["expiry"] + datetime.timedelta(days=days_delta)
        await vip_users.update_one({"_id": user["_id"]}, {"$set": {"expiry": new_expiry}})
        mutated += 1
        
    await message.reply(f"⚡ Modified duration profile arrays for `{mutated}` active registrations.")
    raise StopPropagation

@Client.on_message(filters.command("setvip") & filters.user(Config.ADMINS), group=-1)
async def admin_set_vip_override(client, message: Message):
    args = message.text.split()
    if len(args) < 4: return await message.reply("⚠️ **Usage:** `/setvip <user_id> <Plan> <days>d` (Hard Replace)")
    uid = int(args[1])
    plan = args[2]
    days = int(args[3].replace("d",""))
    expiry = datetime.datetime.now() + datetime.timedelta(days=days)
    
    await vip_users.update_one(
        {"user_id": uid},
        {"$set": {"plan": plan, "expiry": expiry, "status": "Active", "joined": datetime.datetime.now()}},
        upsert=True
    )
    await message.reply(f"📝 Hard overwritten account parameters configuration for user token `{uid}`.")
    raise StopPropagation

@Client.on_message(filters.command("checkvip"), group=-1)
async def check_vip_profile_dump(client, message: Message):
    target = message.from_user.id
    if len(message.command) > 1 and message.from_user.id in Config.ADMINS:
        if message.command[1].isdigit(): target = int(message.command[1])
        
    is_vip, user = await check_vip_status(target)
    if not is_vip:
        return await message.reply("❌ **No Active VIP Membership.**\nUse `/buyvip` to browse options!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium VIP", callback_data="vip_reorder")]]))
        
    rem = user['expiry'] - datetime.datetime.now()
    rem_days = "Infinite" if user["plan"] == "💎 Lifetime" else f"{rem.days} Days"
    expiry_str = "Never" if user["plan"] == "💎 Lifetime" else user['expiry'].strftime('%Y-%m-%d %I:%M %p')

    text = (
        f"💎 **VIP ACCOUNT MEMBERSHIP CREDENTIALS**\n\n"
        f"📦 **Plan Tier:** `{user['plan']}`\n"
        f"🟢 **Status State:** `{user['status']}`\n"
        f"📅 **Registration Joined:** `{user['joined'].strftime('%Y-%m-%d')}`\n"
        f"⏳ **Access Expiration:** `{expiry_str}`\n"
        f"⏱ **Remaining Airtime:** `{rem_days}`\n"
        f"🔄 **Database Renewal Metrics:** `{user.get('renewals', 1)}`\n"
        f"🎟️ **Coupons Redeemed:** `{len(user.get('coupons_used', []))}`\n"
        f"🎁 **Sponsor / Gifted By:** `{user.get('gifted_by') or 'Self-Purchased'}`\n"
        f"💳 **Gateway Clearing Engine:** `{user.get('payment_method','Direct Clearing')}`\n"
        f"🆔 **Internal Order ID Reference:** `{user.get('order_id','N/A')}`\n"
        f"🧾 **Clearance Transaction Hash:** `{user.get('trx_id','N/A')}`"
    )
    await message.reply(text)
    raise StopPropagation

@Client.on_message(filters.command("searchvip") & filters.user(Config.ADMINS), group=-1)
async def admin_search_vip_regex(client, message: Message):
    if len(message.command) < 2: return await message.reply("⚠️ Syntax: `/searchvip <Query>` (ID/Username/Order/Hash)")
    q = message.command[1]
    
    criteria = {"$or": []}
    if q.isdigit(): criteria["$or"].append({"user_id": int(q)})
    criteria["$or"].extend([
        {"plan": {"$regex": q, "$options": "i"}},
        {"order_id": {"$regex": q, "$options": "i"}},
        {"trx_id": {"$regex": q, "$options": "i"}}
    ])
    
    results = await vip_users.find(criteria).to_list(length=15)
    if not results: return await message.reply("🔍 No data records found matching query filter signature.")
    
    out = "🔍 **VIP Registry Node Matches:**\n\n"
    for r in results:
        out += f"👤 Profile: `{r['user_id']}` | Tier: *{r['plan']}* | Exp: `{r['expiry'].strftime('%m-%d') if isinstance(r['expiry'], datetime.datetime) else 'Lifetime'}`\n"
    await message.reply(out)
    raise StopPropagation

# ==========================================
# 🎟️ 3. CRYPTOGRAPHIC COUPON SYSTEM ENGINE
# ==========================================
@Client.on_message(filters.command("createcoupon") & filters.user(Config.ADMINS), group=-1)
async def admin_create_coupons(client, message: Message):
    args = message.text.split()
    if len(args) < 4: return await message.reply("⚠️ **Usage:** `/createcoupon <plan_bronze/silver/gold/lifetime> <prefix> <quantity>`")
    
    plan_target = args[1].lower().replace("vip_", "")
    prefix = args[2].upper()
    qty = int(args[3])
    
    generated = []
    for _ in range(qty):
        token = f"{prefix}-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        coupon_doc = {
            "code": token,
            "plan_target": plan_target,
            "status": "Active",
            "created_at": datetime.datetime.now(),
            "used_by": None,
            "used_at": None
        }
        await vip_coupons.insert_one(coupon_doc)
        generated.append(token)
        
    with open("coupons_export.txt", "w") as f: f.write("\n".join(generated))
    await message.reply_document("coupons_export.txt", caption=f"🎟️ Successfully printed `{qty}` unique coupon vectors for tier `{plan_target}`.")
    try: os.remove("coupons_export.txt")
    except: pass
    raise StopPropagation

@Client.on_message(filters.command("redeem"), group=-1)
async def user_redeem_coupon(client, message: Message):
    if len(message.command) < 2: return await message.reply("⚠️ Usage: `/redeem <COUPON-CODE>`")
    code = message.command[1].strip().upper()
    
    coupon = await vip_coupons.find_one({"code": code, "status": "Active"})
    if not coupon: return await message.reply("❌ **Invalid, Expired, or Double-Claimed Coupon Code Signature.**")
    
    plan_key = coupon["plan_target"]
    plan_meta = PLANS.get(plan_key, PLANS["bronze"])
    
    await vip_coupons.update_one({"code": code}, {"$set": {"status": "Used", "used_by": message.from_user.id, "used_at": datetime.datetime.now()}})
    await add_vip(message.from_user.id, plan_meta["name"], plan_meta["days"], method=f"Coupon Vector ({code})")
    await vip_users.update_one({"user_id": message.from_user.id}, {"$push": {"coupons_used": code}})
    
    await message.reply(f"🎉 **Redemption Authentication Success!**\nActivated premium metadata tier `{plan_meta['name']}` configuration array for your account matrix context.")
    raise StopPropagation

# ==========================================
# 💳 4. DYNAMIC CHECKOUT STATE-MACHINE
# ==========================================
@Client.on_message(filters.command("buyvip"), group=-1)
async def buy_vip_command(client, messageMessage):
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{p['name']} - ₹{p['price']} ({p['days']} Days)", callback_data=f"vip_buy_{k}", style=ButtonStyle.PRIMARY)] for k, p in PLANS.items()
    ])
    await messageMessage.reply("💎 **Choose a VIP Membership Plan:**", reply_markup=markup)
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vip_buy_"))
async def vip_buy_callback(client, callback: CallbackQuery):
    plan_key = callback.data.split("_")[2]
    plan = PLANS[plan_key]
    order_id = generate_order_id(plan_key)
    
    await vip_orders.insert_one({
        "order_id": order_id,
        "user_id": callback.from_user.id,
        "plan": plan_key,
        "amount": plan['price'],
        "status": "Created",
        "created_at": datetime.datetime.now(),
    })
    
    note = f"VIP-{callback.from_user.id}"
    upi_url = f"upi://pay?pa={UPI_ID}&pn={MERCHANT_NAME}&am={plan['price']}&tr={order_id}&cu=INR&tn={note}"
    encoded_upi = urllib.parse.quote(upi_url)
    qr_link = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded_upi}"
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I have Paid", callback_data=f"vip_paid_{order_id}", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("❌ Cancel Order", callback_data=f"vip_cancel_{order_id}", style=ButtonStyle.DANGER)]
    ])
    
    text = (
        f"💳 **Order ID Session Matrix:** `{order_id}`\n"
        f"📦 **Selected Configuration Pool:** {plan['name']}\n"
        f"💵 **Clearing Total Required:** ₹{plan['price']}\n\n"
        f"**🏦 NATIVE GATEWAY DISPATCH CHANNELS:**\n\n"
        f"1️⃣ **Tap/Copy Interbank Address ID:**\n`{UPI_ID}`\n\n"
        f"2️⃣ **Dynamic Matrix Resolution Graphic QR:**\n[Render Live Verification Image Embed]({qr_link})\n\n"
        f"⚠️ *Enforcement Rule: After transmitting exactly ₹{plan['price']} matching session target criteria to endpoint above, execute registration click authorization '✅ I have Paid' below within 30 minutes.*"
    )
    await callback.message.edit_text(text, reply_markup=markup, link_preview_options=LinkPreviewOptions(is_disabled=False))

@Client.on_callback_query(filters.regex(r"^vip_paid_"))
async def vip_paid_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if not order: return await callback.answer("Transaction routing pointer dropped.", show_alert=True)
        
    time_diff = datetime.datetime.now() - order["created_at"]
    if time_diff.total_seconds() > 1800 and order["status"] == "Created":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, I Already Transmitted Funds", callback_data=f"vip_recover_{order_id}", style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton("🔄 Re-initialize Order Array", callback_data="vip_reorder", style=ButtonStyle.PRIMARY)]
        ])
        return await callback.message.edit_text("⚠️ **Session Execution TTL Expired (30 Min Allocation).**\n\nHas a funds packet clearing sequence already executed before server state rotation timeout?", reply_markup=markup)

    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id}
    await callback.message.edit_text("📝 **Clearing Queue Locked.**\n\nPlease submit your 12-Digit Interbank Bank Clearing Ref Code (UTR) or upload data verification image capture.")

@Client.on_callback_query(filters.regex(r"^vip_recover_"))
async def vip_recover_callback(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    USER_STATES[callback.from_user.id] = {"action": "wait_utr", "order_id": order_id, "recovery": True}
    await callback.message.edit_text("🔄 **PAYMENT RECOVERY PIPELINE ENFORCED**\n\n📝 Submit your 12-Digit clearing transaction UTR or receipt imagery capture context. State router will index it for manual audit resolution tracking.")

# ==========================================
# 📸 5. SYSTEM ISOLATION CATCH ENGINE (Group -1)
# ==========================================
@Client.on_message(filters.private, group=-1)
async def catch_payment_proof(client, message: Message):
    if message.text and message.text.startswith("/"): raise ContinuePropagation
    state = USER_STATES.get(message.from_user.id)
    if not state or state.get("action") != "wait_utr": raise ContinuePropagation
        
    order_id = state["order_id"]
    order = await vip_orders.find_one({"order_id": order_id})
    utr = message.text if message.text else f"IMG-VERIFY-VECTOR-{random.randint(100,999)}"
    
    if message.text and len(message.text) == 12 and message.text.isdigit():
        dup = await vip_orders.find_one({"utr": message.text})
        if dup:
            await message.reply("❌ **Clearing Registry Error:** Transaction trace matrix key already fully claimed. Duplication sequence terminated.")
            raise StopPropagation

    await vip_orders.update_one(
        {"order_id": order_id},
        {"$set": {"status": "Under Review", "utr": utr, "submitted_at": datetime.datetime.now()}}
    )
    
    del USER_STATES[message.from_user.id]
    await message.reply("✅ **Payload Indexed Under Audit Layer.**\n\nClearing operations array sent to master control deck. Evaluation notification will route context shortly.")
    
    admin_text = (
        f"🚨 **PAYMENT SECURE CLEARED BLOCK AUDIT RECORD**\n\n"
        f"👤 Account: {message.from_user.mention} (`{message.from_user.id}`)\n"
        f"💳 Registry Link Reference: `{order_id}`\n"
        f"📦 Destination Specifier: `{order['plan']}`\n"
        f"💵 Volume: `₹{order['amount']}`\n"
        f"🧾 Hash Identity String: `{utr}`"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Validate & Clear VIP", callback_data=f"vip_approve_{order_id}", style=ButtonStyle.SUCCESS),
         InlineKeyboardButton("❌ Void & Purge Session", callback_data=f"vip_reject_{order_id}", style=ButtonStyle.DANGER)]
    ])
    
    if message.photo: await client.send_photo(Config.ADMINS[0], message.photo.file_id, caption=admin_text, reply_markup=markup)
    else: await client.send_message(Config.ADMINS[0], admin_text, reply_markup=markup)
    raise StopPropagation

# ==========================================
# 👑 6. CLEARANCE ARCHITECTURE ACTIONS
# ==========================================
@Client.on_callback_query(filters.regex(r"^vip_approve_") & filters.user(Config.ADMINS))
async def admin_approve(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    order = await vip_orders.find_one({"order_id": order_id})
    if order["status"] == "Approved": return await callback.answer("State node already mutation closed.", show_alert=True)
        
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Approved", "approved_by": callback.from_user.id, "approved_at": datetime.datetime.now()}})
    
    plan = PLANS[order["plan"]]
    await add_vip(order["user_id"], plan["name"], plan["days"], method="UPI Gateway Clearing", order_id=order_id, trx_id=order.get("utr"))
    
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("✅ CLEARANCE PASSED", callback_data="noop", style=ButtonStyle.SUCCESS)]]))
    await client.send_message(order["user_id"], f"🎉 **Clearance Complete! Verified!**\n\nYour premium system environment parameters are compiled. Tier `{plan['name']}` initialized successfully.")

@Client.on_callback_query(filters.regex(r"^vip_reject_") & filters.user(Config.ADMINS))
async def admin_reject(client, callback: CallbackQuery):
    order_id = callback.data.split("_")[2]
    await vip_orders.update_one({"order_id": order_id}, {"$set": {"status": "Rejected"}})
    await callback.message.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("❌ ENTRY REJECTED / DISMISSED", callback_data="noop", style=ButtonStyle.DANGER)]]))
    raise StopPropagation

# ==========================================
# 📢 7. PROMOTIONS & SYSTEM SWEER WIZARDS
# ==========================================
@Client.on_message(filters.command("freevip") & filters.user(Config.ADMINS), group=-1)
async def admin_promo_wizard(client, message: Message):
    args = message.text.split()
    if len(args) < 4: return await message.reply("⚠️ Syntax: `/freevip <target_all/nonvip> <Plan> <days>d` (Mass Gift Promo)")
    
    target_selector = args[1]
    plan_name = args[2]
    days = int(args[3].replace("d",""))
    
    targets = await parse_target_users(client, [target_selector])
    await message.reply(f"🚀 **Promo Sweep Initialized.** Deploying VIP payload vectors across `{len(targets)}` accounts in background framework thread...")
    
    count = 0
    for uid in targets:
        try:
            await add_vip(uid, plan_name, days, method="System Promotional Air-Drop", gifted_by=message.from_user.id)
            count += 1
            if count % 30 == 0: await asyncio.sleep(2) # Flood avoidance logic
        except: pass
        
    await message.reply(f"📢 **Promotional Drop Complete!** Operational array modifications injected into `{count}` matching database models successfully.")
    raise StopPropagation

@Client.on_callback_query(filters.regex(r"^vip_reorder$"))
async def callback_reorder_reset(client, callback: CallbackQuery):
    await buy_vip_command(client, callback.message)
    try: await callback.message.delete()
    except: pass

@Client.on_callback_query(filters.regex(r"^confirm_wipe_vip_"))
async def callback_mass_wipe_handler(client, callback: CallbackQuery):
    selector = callback.data.replace("confirm_wipe_vip_", "")
    if selector == "all":
        await vip_users.delete_many({})
        await callback.message.edit_text("🗑️ **Database Core Formatted:** Terminated all records inside user collection array context completely.")
    else:
        await vip_users.delete_many({"plan": {"$regex": selector, "$options": "i"}})
        await callback.message.edit_text(f"🗑️ **Database Cleaned:** Flushed all matching instances of target subset: `{selector}`")
