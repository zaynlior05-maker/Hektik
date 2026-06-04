import os
import logging
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN")
SUPER_ADMIN      = os.environ.get("ADMIN_USERNAME", "HekTikz")   # main owner
ADMIN_PASSWORD   = os.environ.get("ADMIN_PASSWORD", "changeme123") # shared admin PIN
LOG_CHANNEL_ID   = os.environ.get("LOG_CHANNEL_ID")               # e.g. -1001234567890
JOIN_CHANNEL     = os.environ.get("JOIN_CHANNEL")                  # e.g. @hektikstore or -1001234567890
JOIN_CHANNEL_URL = os.environ.get("JOIN_CHANNEL_URL", "https://t.me/yourchannel")
MIN_TOPUP        = 70   # minimum top-up amount (not an access gate anymore)

WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── Storage ───────────────────────────────────────────────────────────────────
user_balances    = {}
agreed_users     = set()
user_join_dates  = {}
logged_in_admins = set()   # user IDs who have authenticated with admin password

live_stock = {"leads": 63_629_085, "stock": 183}
TOPUP_AMOUNTS = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]
BINS_PER_PAGE = 10

# ── Store Data ────────────────────────────────────────────────────────────────
STORE = {
    "8888": {
        "label": "Vendor 8888",
        "bases": {
            "15_fresh": {
                "label": "£15 Base - Fresh Lives 🇬🇧",
                "price_per_card": 15,
                "bins": {
                    "371789": 6,  "374288": 1,  "377383": 3,  "377390": 9,
                    "379006": 1,  "402396": 1,  "402399": 1,  "404972": 2,
                    "416549": 9,  "416598": 16, "446223": 1,  "446261": 7,
                    "446278": 1,  "446291": 1,  "449352": 2,  "449353": 2,
                    "450875": 1,  "454313": 6,  "454638": 2,  "459647": 4,
                },
            }
        },
    },
    "1717": {
        "label": "Vendor 1717",
        "bases": {
            "10_fresh": {
                "label": "£10 Base - Fresh Lives 🇬🇧",
                "price_per_card": 10,
                "bins": {
                    "400115": 4,  "401178": 2,  "402601": 3,  "403628": 1,
                    "410076": 5,  "411929": 2,  "415530": 6,  "419740": 1,
                    "422773": 3,  "425938": 2,
                },
            }
        },
    },
}

DEADS_ITEMS = [
    ("50+ Specific BIN, Gender & DOB File",  225,  "dead_spec_50"),
    ("100+ Specific BIN, Gender & DOB File", 350,  "dead_spec_100"),
    ("50+ Random File",                      100,  "dead_rand_50"),
    ("100+ Random File",                     150,  "dead_rand_100"),
    ("500 Random File",                      500,  "dead_rand_500"),
    ("1k Random File",                       700,  "dead_rand_1k"),
    ("2k Random File",                       1200, "dead_rand_2k"),
]

RULES_TEXT = (
    "🛍 *Welcome to HekTik's Store!*\n\n"
    "To access the store, a minimum top-up of *£70* is required.\n\n"
    "*Refund Rules*\n"
    "• /refund to submit refunds\n"
    "• Screen recording proof of pay.google.com only, 5 mins refund time\n"
    "• If the card is live but phone number is incorrect, no refund\n\n"
    "*Spam source Rules*\n"
    "• The scan balance is separate from the rest of the bot — will not transfer over\n\n"
    "*Keep in Mind:* *(£10 & £5 BASES ARE NOT REFUNDABLE)*\n\n"
    "⛔️ *NOTE* ⛔️\n"
    "ANYONE NEED BULK SMS/EMAIL BLAST WITH SID 100% LANDING (NO BOUNCE) CODING\n"
    "• Centers, panels, pages & scripts available pm\n\n"
    "🔹 Support 24/7 @EXCELV3.\n\n"
    "By continuing, you agree to the rules.\n"
    "Note: withdrawals can be made at any time!"
)

# ── Channel Logger ────────────────────────────────────────────────────────────

async def log(app, text: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Log failed: {e}")

# ── Channel membership check ──────────────────────────────────────────────────

async def has_joined_channel(bot, user_id: int) -> bool:
    """Returns True if user is a member of the required channel."""
    if not JOIN_CHANNEL:
        return True   # no channel set = open access
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        return member.status in [
            ChatMember.MEMBER,
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER,
        ]
    except Exception:
        return False

# ── Admin auth ────────────────────────────────────────────────────────────────

def is_admin(update) -> bool:
    """Super admin (by username) OR any user who logged in with the password."""
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_join_date(uid):
    if uid not in user_join_dates:
        user_join_dates[uid] = datetime.now().strftime("%m-%d-%Y")
    return user_join_dates[uid]

async def get_crypto_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana,litecoin&vs_currencies=gbp"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
                return {"BTC": d["bitcoin"]["gbp"], "SOL": d["solana"]["gbp"], "LTC": d["litecoin"]["gbp"]}
    except Exception:
        return None

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads",   callback_data="leads"),
         InlineKeyboardButton("🛍️ Store",   callback_data="store")],
        [InlineKeyboardButton("💰 Wallet",  callback_data="wallet"),
         InlineKeyboardButton("🔍 Scanner", callback_data="scanner")],
    ])

def main_menu_text():
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Stock*\n"
        f"🌍 Leads: *{live_stock['leads']:,}*\n"
        f"🛍️ Stock: *{live_stock['stock']}*\n\n"
        "_Choose a section below:_"
    )

def not_joined_text():
    return (
        "🔒 *Access Restricted*\n\n"
        "You must join our channel to access the store.\n\n"
        f"👉 [Join Here]({JOIN_CHANNEL_URL})\n\n"
        "Once joined, tap the button below to continue."
    )

def not_joined_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=JOIN_CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Check Again", callback_data="check_joined")],
    ])

def wallet_profile_text(uid):
    bal = user_balances.get(uid, 0)
    return (
        f"============================\n"
        f"🪪 *ID:* `{uid}`\n"
        f"💰 *Balance:* £{bal:.2f}\n"
        f"📅 *Join Date:* {get_join_date(uid)}\n"
        f"============================\n\n"
        f"Select a top-up amount below:\n_Minimum top-up: £{MIN_TOPUP}_"
    )

def amount_keyboard():
    rows, row = [], []
    for a in TOPUP_AMOUNTS:
        row.append(InlineKeyboardButton(f"💠 £{a} 💠", callback_data=f"amount_{a}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("💰 Custom Amount", callback_data="custom_amount")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def coin_select_keyboard(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("₿ BTC", callback_data=f"pay_BTC_{amount}")],
        [InlineKeyboardButton("◎ SOL", callback_data=f"pay_SOL_{amount}")],
        [InlineKeyboardButton("Ł LTC", callback_data=f"pay_LTC_{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="wallet")],
    ])

def vendor_select_keyboard():
    rows = []
    vendor_ids = list(STORE.keys())
    for i in range(0, len(vendor_ids), 2):
        rows.append([InlineKeyboardButton(v, callback_data=f"vendor_{v}") for v in vendor_ids[i:i+2]])
    rows.append([InlineKeyboardButton("💀 Deads", callback_data="deads")])
    rows.append([InlineKeyboardButton("⬅️ Back",  callback_data="back")])
    return InlineKeyboardMarkup(rows)

def base_select_keyboard(vid):
    rows = [[InlineKeyboardButton(b["label"], callback_data=f"base_{vid}_{bk}")]
            for bk, b in STORE[vid]["bases"].items()]
    rows.append([InlineKeyboardButton("🔍 BIN Search", callback_data=f"binsearch_{vid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def bin_list_keyboard(vid, bkey, page=0):
    bins        = list(STORE[vid]["bases"][bkey]["bins"].items())
    total_pages = max(1, (len(bins) + BINS_PER_PAGE - 1) // BINS_PER_PAGE)
    page_bins   = bins[page * BINS_PER_PAGE:(page + 1) * BINS_PER_PAGE]
    rows = []
    for i in range(0, len(page_bins), 2):
        rows.append([InlineKeyboardButton(
            f"{b} ({q})", callback_data=f"buybin_{vid}_{bkey}_{b}_{page}")
            for b, q in page_bins[i:i+2]])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"binpage_{vid}_{bkey}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"binpage_{vid}_{bkey}_{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor_{vid}")])
    return InlineKeyboardMarkup(rows), total_pages

def deads_keyboard():
    rows = [[InlineKeyboardButton(f"{l} — £{p:,}", callback_data=f"deadbuy_{k}")]
            for l, p, k in DEADS_ITEMS]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)

    if is_new:
        await log(context.application,
            f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    if uid in agreed_users:
        await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    await update.message.reply_text(
        RULES_TEXT,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Continue", callback_data="agree_rules")]]),
        parse_mode="Markdown",
    )

# ═════════════════════════════════════════════════════════════════════════════
# ADMIN LOGIN / LOGOUT
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_adminlogin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any user runs /adminlogin <password> to gain admin access."""
    uid = update.effective_user.id
    try:
        password = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /adminlogin <password>")
        return

    if password == ADMIN_PASSWORD:
        logged_in_admins.add(uid)
        await update.message.reply_text(
            "✅ *Admin access granted!*\n\nYou can now use all admin commands.\n"
            "Send /adminhelp to see them all.\n\n"
            "_Run /adminlogout when done._",
            parse_mode="Markdown"
        )
        await log(context.application,
            f"🔑 *Admin Login*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    else:
        await update.message.reply_text("❌ Wrong password.")
        await log(context.application,
            f"⚠️ *Failed Admin Login Attempt*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`")

async def cmd_adminlogout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logged_in_admins.discard(uid)
    await update.message.reply_text("🔒 Logged out of admin access.")

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ You need admin access. Use /adminlogin <password>")
        return
    await update.message.reply_text(
        "🛠 *Admin Commands*\n\n"
        "*Login*\n"
        "`/adminlogin <password>` — Login as admin\n"
        "`/adminlogout` — Logout\n\n"
        "*Balance*\n"
        "`/addbalance <user_id> <amount>`\n"
        "`/removebalance <user_id> <amount>`\n"
        "`/setbalance <user_id> <amount>`\n"
        "`/checkbalance <user_id>`\n\n"
        "*Stock*\n"
        "`/setstock leads <number>`\n"
        "`/setstock stock <number>`\n\n"
        "*Vendors*\n"
        "`/addvendor <id> <label>`\n"
        "`/removevendor <id>`\n\n"
        "*Bases*\n"
        "`/addbase <vendor_id> <base_key> <price> <label>`\n"
        "`/removebase <vendor_id> <base_key>`\n\n"
        "*BINs*\n"
        "`/addbin <vendor_id> <base_key> <bin> <qty>`\n"
        "`/removebin <vendor_id> <base_key> <bin>`\n"
        "`/listbins <vendor_id> <base_key>`\n"
        "`/clearbase <vendor_id> <base_key>`\n\n"
        "*Users*\n"
        "`/listusers`\n"
        "`/broadcast <message>`",
        parse_mode="Markdown"
    )

# ═════════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2)
    await update.message.reply_text(
        f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*",
        parse_mode="Markdown")
    await log(context.application,
        f"💳 *Balance Added*\nBy: {user_tag(update)}\nUser: `{tid}`\n"
        f"Amount: £{amt:.2f}\nNew balance: £{user_balances[tid]:.2f}")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /removebalance <user_id> <amount>"); return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2)
    await update.message.reply_text(
        f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*",
        parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setbalance <user_id> <amount>"); return
    user_balances[tid] = round(amt, 2)
    await update.message.reply_text(f"✅ Set `{tid}` balance to *£{amt:.2f}*", parse_mode="Markdown")

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        tid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /checkbalance <user_id>"); return
    await update.message.reply_text(
        f"User `{tid}` balance: *£{user_balances.get(tid,0):.2f}*", parse_mode="Markdown")

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        key = context.args[0].lower(); val = int(context.args[1])
        assert key in ("leads", "stock")
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /setstock leads <number>"); return
    live_stock[key] = val
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /addvendor <id> <label>"); return
    if vid in STORE:
        await update.message.reply_text(f"Vendor `{vid}` already exists."); return
    STORE[vid] = {"label": label, "bases": {}}
    await update.message.reply_text(f"✅ Added vendor *{label}*", parse_mode="Markdown")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; assert vid in STORE
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /removevendor <vendor_id>"); return
    del STORE[vid]
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text(
            "Usage: /addbase <vendor_id> <base_key> <price> <label>\n"
            "Example: /addbase 8888 20_fresh 20 £20 Base Fresh 🇬🇧"); return
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": {}}
    await update.message.reply_text(f"✅ Added base *{label}* at £{price}/card", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /removebase <vendor_id> <base_key>"); return
    del STORE[vid]["bases"][bkey]
    await update.message.reply_text(f"✅ Removed base `{bkey}` from vendor `{vid}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        bin_num = context.args[2]; qty = int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text(
            "Usage: /addbin <vendor_id> <base_key> <bin_number> <quantity>\n"
            "Example: /addbin 8888 15_fresh 416598 20"); return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty
    await update.message.reply_text(
        f"✅ BIN *{bin_num}* set to *{qty}* in `{vid}` / `{bkey}`", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /removebin <vendor_id> <base_key> <bin_number>"); return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None)
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /listbins <vendor_id> <base_key>"); return
    bins  = STORE[vid]["bases"][bkey]["bins"]
    label = STORE[vid]["bases"][bkey]["label"]
    if not bins:
        await update.message.reply_text(f"No BINs in *{label}*", parse_mode="Markdown"); return
    lines = [f"📦 *{label}* — {sum(bins.values())} total\n"]
    for b, q in sorted(bins.items()):
        lines.append(f"`{b}` — {q} cards")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /clearbase <vendor_id> <base_key>"); return
    STORE[vid]["bases"][bkey]["bins"].clear()
    await update.message.reply_text(f"✅ Cleared all BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    if not user_balances:
        await update.message.reply_text("No users with balances yet."); return
    lines = ["👥 *All Users & Balances*\n"]
    for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1]):
        joined = user_join_dates.get(uid, "Unknown")
        lines.append(f"`{uid}` — £{bal:.2f} (joined {joined})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised. Use /adminlogin <password>"); return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /broadcast <message>"); return
    sent = 0
    for uid in list(agreed_users):
        try:
            await context.application.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

# ═════════════════════════════════════════════════════════════════════════════
# BUTTON HANDLER
# ═════════════════════════════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    # Welcome / agree rules
    if data == "agree_rules":
        agreed_users.add(uid)
        await log(context.application, f"✅ *User Agreed to Rules*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`")
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    # Check channel membership for store/leads/scanner
    if data in ("store", "leads", "scanner"):
        joined = await has_joined_channel(context.bot, uid)
        if not joined:
            await log(context.application,
                f"🔒 *Channel Not Joined*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\nTried: {data}")
            await query.edit_message_text(
                not_joined_text(),
                reply_markup=not_joined_keyboard(),
                parse_mode="Markdown",
                disable_web_page_preview=True)
            return

    # Check joined button
    if data == "check_joined":
        joined = await has_joined_channel(context.bot, uid)
        if joined:
            await query.edit_message_text(
                main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        else:
            await query.answer("❌ You haven't joined yet. Please join first.", show_alert=True)
        return

    # ── Wallet ────────────────────────────────────────────────────────────────
    if data == "wallet":
        await query.edit_message_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("amount_"):
        amount = data.split("_")[1]
        await query.edit_message_text(
            f"💠 *£{amount} Top-Up*\n\nChoose your payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text(
            "💰 *Custom Amount*\n\nType the £ amount (minimum £70):\nExample: `150`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]),
            parse_mode="Markdown")
        return

    if data.startswith("pay_"):
        parts = data.split("_"); coin = parts[1]; amount = int(parts[2])
        address = WALLETS.get(coin, "Address not configured")
        await query.edit_message_text("⏳ Fetching live price...")
        prices = await get_crypto_prices()
        if prices and coin in prices:
            crypto_amt = round(amount / prices[coin], 6)
            price_line = f"Send *Exactly* `{crypto_amt}` {coin} to get *£{amount}* credit"
        else:
            price_line = f"Send the equivalent of *£{amount}* in {coin}"
        await log(context.application,
            f"💰 *Top-Up Requested*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n💷 £{amount} via {coin}")
        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n"
            f"‼️ Deposits are permanent and *non refundable*\n"
            f"‼️ Double check the {coin} amount *before* sending\n"
            f"‼️ Anything UNDER or ABOVE = *Donation*\n\n"
            f"💠 You will be funded when transaction is confirmed\n\n"
            f"⚠️ *DO NOT SEND AS £ — only send as {coin}*\n"
            f"‼️ One payment per wallet address\n\n"
            f"_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID after sending_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amount_{amount}")]]),
            parse_mode="Markdown")
        return

    # ── Store ─────────────────────────────────────────────────────────────────
    if data == "store":
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("vendor_"):
        vid = data.split("_", 1)[1]
        if vid not in STORE: await query.answer("Vendor not found."); return
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n\nSelect a base:",
            reply_markup=base_select_keyboard(vid), parse_mode="Markdown")
        return

    if data.startswith("base_"):
        _, vid, bkey = data.split("_", 2)
        base = STORE[vid]["bases"][bkey]
        total_qty = sum(base["bins"].values())
        kbd, total_pages = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {total_qty}\n\nSelect BIN group:\n_Page 1 of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("binpage_"):
        _, vid, bkey, page = data.split("_", 3); page = int(page)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {sum(base['bins'].values())}\n\nSelect BIN group:\n_Page {page+1} of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("binsearch_"):
        vid = data.split("_", 1)[1]
        context.user_data["bin_search_vendor"] = vid
        context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(
            f"🔍 *BIN Search — {STORE[vid]['label']}*\n\nType the BIN number:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor_{vid}")]]),
            parse_mode="Markdown")
        return

    if data.startswith("buybin_"):
        parts = data.split("_", 4); _, vid, bkey, bin_num, page = parts
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        if qty == 0: await query.answer("Out of stock."); return
        total = base["price_per_card"] * qty; balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"👤 Vendor: *{STORE[vid]['label']}*\n📦 Base: *{base['label']}*\n"
            f"💳 BIN: *{bin_num}*\n🗂 Qty: *{qty} cards*\n"
            f"💰 Per card: *£{base['price_per_card']}*\n💷 *Total: £{total}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"confirmbin_{vid}_{bkey}_{bin_num}_{page}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"binpage_{vid}_{bkey}_{page}")]]),
            parse_mode="Markdown")
        return

    if data.startswith("confirmbin_"):
        parts = data.split("_", 4); _, vid, bkey, bin_num, page = parts
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        total = base["price_per_card"] * qty; balance = user_balances.get(uid, 0)
        if qty == 0: await query.answer("Out of stock."); return
        if balance < total:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{total}\nYour balance: £{balance:.2f}\n\nTop up your wallet.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back", callback_data=f"binpage_{vid}_{bkey}_{page}")]]),
                parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total, 2)
        del STORE[vid]["bases"][bkey]["bins"][bin_num]
        await log(context.application,
            f"🛒 *Purchase — BIN*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"Vendor: {STORE[vid]['label']}\nBase: {base['label']}\n"
            f"BIN: {bin_num} x{qty}\n💷 Paid: £{total}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\nBIN: *{bin_num}* | Qty: *{qty}* | Paid: *£{total}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]),
            parse_mode="Markdown")
        return

    # ── Deads ─────────────────────────────────────────────────────────────────
    if data == "deads":
        await query.edit_message_text(
            "💀 *Deads — Unspoofed Files*\n\n"
            "*Specific:*\n• 50+ Specific BIN, Gender & DOB — £225\n• 100+ Specific BIN, Gender & DOB — £350\n\n"
            "*Random:*\n• 50+ File — £100\n• 100+ File — £150\n• 500 File — £500\n• 1k File — £700\n• 2k File — £1,200\n\n"
            "_Select to purchase:_",
            reply_markup=deads_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("deadbuy_"):
        key = data.replace("deadbuy_", "")
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"deadconfirm_{key}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data="deads")]]),
            parse_mode="Markdown")
        return

    if data.startswith("deadconfirm_"):
        key = data.replace("deadconfirm_", "")
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        if balance < price:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{price:,}\nYour balance: £{balance:.2f}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back", callback_data="deads")]]),
                parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2)
        await log(context.application,
            f"🛒 *Purchase — Deads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"📁 {label}\n💷 Paid: £{price:,}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n📁 *{label}*\n💷 Paid: *£{price:,}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]),
            parse_mode="Markdown")
        return

    # ── Leads / Scanner ───────────────────────────────────────────────────────
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])
    if data == "leads":
        await query.edit_message_text(
            f"🌍 *Leads*\n\nAvailable: *{live_stock['leads']:,}*\n\nContact @{SUPER_ADMIN}.",
            reply_markup=back_btn, parse_mode="Markdown")
    elif data == "scanner":
        await query.edit_message_text(
            f"🔍 *Scanner*\n\nContact @{SUPER_ADMIN} with the value to scan.",
            reply_markup=back_btn, parse_mode="Markdown")

# ── Text handler ──────────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_custom"):
        text = update.message.text.strip().replace("£","")
        try:
            amount = int(float(text))
            if amount < MIN_TOPUP:
                await update.message.reply_text(f"Minimum top-up is £{MIN_TOPUP}."); return
        except ValueError:
            await update.message.reply_text("Enter a valid number e.g. 150"); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(
            f"💠 *£{amount} Top-Up*\n\nChoose payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num = update.message.text.strip()
        vid = context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        results = []
        for bkey, base in STORE.get(vid,{}).get("bases",{}).items():
            qty = base["bins"].get(bin_num)
            if qty:
                results.append(f"📦 *{base['label']}* — {qty} @ £{base['price_per_card']}/card")
        if results:
            await update.message.reply_text(
                f"🔍 *BIN {bin_num}*\n\n" + "\n".join(results),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor_{vid}")]]),
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ BIN *{bin_num}* not found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor_{vid}")]]),
                parse_mode="Markdown")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("adminlogin",    cmd_adminlogin))
    app.add_handler(CommandHandler("adminlogout",   cmd_adminlogout))
    app.add_handler(CommandHandler("adminhelp",     cmd_adminhelp))
    app.add_handler(CommandHandler("addbalance",    cmd_addbalance))
    app.add_handler(CommandHandler("removebalance", cmd_removebalance))
    app.add_handler(CommandHandler("setbalance",    cmd_setbalance))
    app.add_handler(CommandHandler("checkbalance",  cmd_checkbalance))
    app.add_handler(CommandHandler("setstock",      cmd_setstock))
    app.add_handler(CommandHandler("addvendor",     cmd_addvendor))
    app.add_handler(CommandHandler("removevendor",  cmd_removevendor))
    app.add_handler(CommandHandler("addbase",       cmd_addbase))
    app.add_handler(CommandHandler("removebase",    cmd_removebase))
    app.add_handler(CommandHandler("addbin",        cmd_addbin))
    app.add_handler(CommandHandler("removebin",     cmd_removebin))
    app.add_handler(CommandHandler("listbins",      cmd_listbins))
    app.add_handler(CommandHandler("clearbase",     cmd_clearbase))
    app.add_handler(CommandHandler("listusers",     cmd_listusers))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
