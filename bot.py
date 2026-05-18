import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
ADMIN_USER  = os.environ.get("ADMIN_USERNAME", "hektik")
MIN_BALANCE = 70

# ── Crypto wallet addresses ──────────────────────────────────────────────────
WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── In-memory storage ────────────────────────────────────────────────────────
user_balances = {}
agreed_users  = set()

live_stock = {
    "leads": 63_629_085,
    "stock": 183,
}

# ── Welcome / Rules message ──────────────────────────────────────────────────
RULES_TEXT = (
    "🛍 *Welcome to HekTik's Store!*\n\n"
    "Here are the following rules:\n\n"
    "To access the store, a minimum top-up of *£70* is required.\n\n"
    "*Refund Rules*\n"
    "• /refund to submit refunds\n"
    "• Screen recording proof of pay.google.com only, 5 mins refund time\n"
    "• If the card is live, but phone number is incorrect, this doesn't qualify for a refund\n\n"
    "*Spam source Rules*\n"
    "• The balance to scan data, is separate to the rest of the bot. It will not transfer over, vice versa\n"
    "Please be assured that\n\n"
    "*Keep in Mind:*\n\n"
    "*(£10 & £5 BASES ARE NOT REFUNDABLE)*\n\n"
    "⛔️ *NOTE* ⛔️\n\n"
    "ANYONE NEED BULK SMS/EMAIL BLAST WITH SID 100% LANDING (NO BOUNCE) CODING\n"
    "FOR YOUR\n"
    "• Centers, panels, pages & scripts available pm\n\n"
    "🔹 Support account is available 24/7 @HekTikz.\n\n"
    "By continuing, you agree to the rules,\n"
    "Note: withdrawals can be made at any time.!"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def has_access(user_id):
    return user_balances.get(user_id, 0) >= MIN_BALANCE


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌍 Leads",   callback_data="leads"),
            InlineKeyboardButton("🛍️ Store",   callback_data="store"),
        ],
        [
            InlineKeyboardButton("💰 Wallet",  callback_data="wallet"),
            InlineKeyboardButton("🔍 Scanner", callback_data="scanner"),
        ],
    ])


def main_menu_text():
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Stock*\n"
        f"🌍 Leads: *{live_stock['leads']:,}*\n"
        f"🛍️ Stock: *{live_stock['stock']}*\n\n"
        "_Choose a section below:_"
    )


def denied_text(section):
    return (
        f"Access denied⛔️\n\n"
        f"To access the {section}, a minimum top-up of £{MIN_BALANCE} is required.\n\n"
        f"Use the wallet to top up the bot 🤖\n"
        f"===============\n"
        f"Managed by @{ADMIN_USER}"
    )

# ── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in agreed_users:
        await update.message.reply_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Continue", callback_data="agree_rules")]
    ])
    await update.message.reply_text(
        RULES_TEXT,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

# ── Admin: /addbalance ───────────────────────────────────────────────────────

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("Unauthorised.")
        return
    try:
        target_id = int(context.args[0])
        amount    = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
        return

    user_balances[target_id] = round(user_balances.get(target_id, 0) + amount, 2)
    await update.message.reply_text(
        f"Added £{amount:.2f} to user {target_id}. New balance: £{user_balances[target_id]:.2f}"
    )

# ── Admin: /setstock ─────────────────────────────────────────────────────────

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("Unauthorised.")
        return
    try:
        key   = context.args[0].lower()
        value = int(context.args[1])
        assert key in ("leads", "stock")
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /setstock leads <number>")
        return

    live_stock[key] = value
    await update.message.reply_text(f"Updated {key} to {value:,}")

# ── Admin: /checkbalance ─────────────────────────────────────────────────────

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("Unauthorised.")
        return
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /checkbalance <user_id>")
        return

    bal = user_balances.get(target_id, 0)
    await update.message.reply_text(f"User {target_id} balance: £{bal:.2f}")

# ── Button handler ───────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data    = query.data

    if data == "agree_rules":
        agreed_users.add(user_id)
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "back":
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "wallet":
        bal = user_balances.get(user_id, 0)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("BTC", callback_data="pay_btc")],
            [InlineKeyboardButton("SOL", callback_data="pay_sol")],
            [InlineKeyboardButton("LTC", callback_data="pay_ltc")],
            [InlineKeyboardButton("Back", callback_data="back")],
        ])
        await query.edit_message_text(
            f"💰 *Wallet*\n\nYour balance: *£{bal:.2f}*\n\nMinimum required: *£{MIN_BALANCE}*\n\nTop up using a crypto option below 👇",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    if data.startswith("pay_"):
        symbol  = data.split("_")[1].upper()
        address = WALLETS.get(symbol, "Address not configured yet")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Back to Wallet", callback_data="wallet")]
        ])
        await query.edit_message_text(
            f"💳 *Top Up with {symbol}*\n\nSend to this address:\n`{address}`\n\nAfter sending, DM @{ADMIN_USER} with your transaction ID and your user ID: `{user_id}`",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    section_names = {
        "leads":   "Leads section",
        "store":   "Store",
        "scanner": "Scanner",
    }
    section_label = section_names.get(data, data.capitalize())

    if not has_access(user_id):
        await query.edit_message_text(
            denied_text(section_label),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                    InlineKeyboardButton("Back",      callback_data="back"),
                ]
            ]),
        )
        return

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])

    if data == "leads":
        await query.edit_message_text(
            f"🌍 *Leads*\n\nTotal available: *{live_stock['leads']:,}*\n\nContact @{ADMIN_USER} to purchase.",
            reply_markup=back_btn,
            parse_mode="Markdown",
        )
    elif data == "store":
        await query.edit_message_text(
            f"🛍️ *Store*\n\nItems in stock: *{live_stock['stock']}*\n\nContact @{ADMIN_USER} to browse and purchase.",
            reply_markup=back_btn,
            parse_mode="Markdown",
        )
    elif data == "scanner":
        await query.edit_message_text(
            f"🔍 *Scanner*\n\nContact @{ADMIN_USER} with the value you want scanned.",
            reply_markup=back_btn,
            parse_mode="Markdown",
        )

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("addbalance",   cmd_addbalance))
    app.add_handler(CommandHandler("setstock",     cmd_setstock))
    app.add_handler(CommandHandler("checkbalance", cmd_checkbalance))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
