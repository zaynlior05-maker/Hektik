import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ── Logging (shows errors in Railway logs) ──────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ.get("BOT_TOKEN")       # Set this in Railway
ADMIN_USER   = os.environ.get("ADMIN_USERNAME", "hek")   # Your Telegram username (no @)
MIN_BALANCE  = 70  # £70 minimum to access sections

# ── Crypto wallet addresses – change these to YOUR real addresses ─────────────
WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── In-memory storage (resets on restart – good enough for starting out) ─────
user_balances: dict[int, float] = {}   # { user_id: balance_gbp }
agreed_users:  set[int]         = set()  # users who clicked Continue on welcome screen

# ── Welcome / Rules message ───────────────────────────────────────────────────
# Edit the rules text below to whatever you want to show users
RULES_TEXT = (
    "🛍 *Welcome to HekTik's Store\!*\n\n"
    "Here are the following rules:\n\n"
    "To access the store, a minimum top\-up of £70 is required\.\n\n"
    "*Refund Rules*\n"
    "• /refund to submit refunds\n"
    "• Screen recording proof of pay\.google\.com only, 5 mins refund time\n"
    "• If the card is live, but phone number is incorrect, this doesn't qualify for a refund\n\n"
    "*Spam source Rules*\n"
    "• The balance to scan data, is separate to the rest of the bot\. "
    "It will not transfer over, vice versa\n"
    "Please be assured that\n\n"
    "*Keep in Mind:*\n\n"
    "*\(£10 & £5 BASES ARE NOT REFUNDABLE\)*\n\n"
    "⛔️ *NOTE* ⛔️\n\n"
    "ANYONE NEED BULK SMS/EMAIL BLAST WITH SID 100% LANDING \(NO BOUNCE\) CODING\n"
    "FOR YOUR\n"
    "• Centers, panels, pages & scripts available pm\n\n"
    "🔹Support account is available 24/7 @EXCELV3\.\n\n"
    "By continuing, you agree to the rules,\n"
    "Note: withdrawals can be made at any time\.\!"
)

live_stock = {
    "leads": 63_629_085,
    "stock": 183,
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def has_access(user_id: int) -> bool:
    return user_balances.get(user_id, 0) >= MIN_BALANCE


def main_menu_keyboard() -> InlineKeyboardMarkup:
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


def main_menu_text() -> str:
    return (
        "🏪 *Main Menu*\n\n"
        "📊 *Live Stock*\n"
        f"🌍 Leads: *{live_stock['leads']:,}*\n"
        f"🛍️ Stock: *{live_stock['stock']}*\n\n"
        "_Choose a section below:_"
    )


def denied_text(section: str) -> str:
    return (
        f"Access denied⛔️\n\n"
        f"To access the {section}, a minimum top-up of £{MIN_BALANCE} is required.\n\n"
        f"Use the wallet to top up the bot 🤖\n"
        f"===============\n"
        f"Managed by @{ADMIN_USER}"
    )


def back_keyboard(target: str = "back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Wallet",  callback_data="wallet"),
            InlineKeyboardButton("⬅️ Back",    callback_data=target),
        ]
    ])

# ─────────────────────────────────────────────────────────────────────────────
# Command: /start
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    # If user already agreed to rules, go straight to main menu
    if user_id in agreed_users:
        await update.message.reply_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # First time — show welcome + rules screen with Continue button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Continue", callback_data="agree_rules")]
    ])
    await update.message.reply_text(
        RULES_TEXT,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

# ─────────────────────────────────────────────────────────────────────────────
# Command: /addbalance  (admin only)
# Usage:  /addbalance <user_id> <amount>
# Example: /addbalance 123456789 100
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("❌ Unauthorised.")
        return

    try:
        target_id = int(context.args[0])
        amount    = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Usage: `/addbalance <user_id> <amount>`\n"
            "Example: `/addbalance 123456789 70`",
            parse_mode="Markdown",
        )
        return

    user_balances[target_id] = round(user_balances.get(target_id, 0) + amount, 2)
    await update.message.reply_text(
        f"✅ Added £{amount:.2f} to user `{target_id}`.\n"
        f"New balance: *£{user_balances[target_id]:.2f}*",
        parse_mode="Markdown",
    )

# ─────────────────────────────────────────────────────────────────────────────
# Command: /setstock  (admin only)
# Usage:  /setstock leads <number>  OR  /setstock stock <number>
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("❌ Unauthorised.")
        return

    try:
        key   = context.args[0].lower()   # "leads" or "stock"
        value = int(context.args[1])
        assert key in ("leads", "stock")
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text(
            "Usage: `/setstock leads <number>` or `/setstock stock <number>`",
            parse_mode="Markdown",
        )
        return

    live_stock[key] = value
    await update.message.reply_text(f"✅ Updated *{key}* to *{value:,}*", parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────────────────────
# Command: /checkbalance  (admin only)
# Usage:  /checkbalance <user_id>
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.username != ADMIN_USER:
        await update.message.reply_text("❌ Unauthorised.")
        return

    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/checkbalance <user_id>`", parse_mode="Markdown")
        return

    bal = user_balances.get(target_id, 0)
    await update.message.reply_text(
        f"User `{target_id}` balance: *£{bal:.2f}*", parse_mode="Markdown"
    )

# ─────────────────────────────────────────────────────────────────────────────
# Button handler (inline keyboard clicks)
# ─────────────────────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    await query.answer()                 # removes the "loading" spinner

    user_id = query.from_user.id
    data    = query.data

    # ── User clicks Continue on welcome screen ───────────────────────────────
    if data == "agree_rules":
        agreed_users.add(user_id)
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Back → Main Menu ────────────────────────────────────────────────────
    if data == "back":
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Wallet (always accessible) ───────────────────────────────────────────
    if data == "wallet":
        bal = user_balances.get(user_id, 0)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("₿  BTC",  callback_data="pay_btc")],
            [InlineKeyboardButton("◎  SOL",  callback_data="pay_sol")],
            [InlineKeyboardButton("Ł  LTC",  callback_data="pay_ltc")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back")],
        ])
        await query.edit_message_text(
            f"💰 *Wallet*\n\n"
            f"Your balance: *£{bal:.2f}*\n\n"
            f"Minimum required: *£{MIN_BALANCE}*\n\n"
            f"Top up using a crypto option below 👇",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # ── Crypto top-up address display ────────────────────────────────────────
    if data.startswith("pay_"):
        symbol  = data.split("_")[1].upper()
        address = WALLETS.get(symbol, "Address not configured")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Wallet", callback_data="wallet")]
        ])
        await query.edit_message_text(
            f"💳 *Top Up with {symbol}*\n\n"
            f"Send to this address:\n`{address}`\n\n"
            f"After sending, contact @{ADMIN_USER} with your *transaction ID* "
            f"and your Telegram *user ID* (`{user_id}`) to get your balance credited.\n\n"
            f"_Your user ID: `{user_id}`_",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    # ── Access-gated sections ────────────────────────────────────────────────
    section_names = {
        "leads":   "Leads section",
        "store":   "Store",
        "scanner": "Scanner",
    }
    section_label = section_names.get(data, data.capitalize())

    if not has_access(user_id):
        await query.edit_message_text(
            denied_text(section_label),
            reply_markup=back_keyboard("back"),
        )
        return

    # ── Paid content (customise each section below) ──────────────────────────
    if data == "leads":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back")]
        ])
        await query.edit_message_text(
            f"🌍 *Leads*\n\n"
            f"Total available: *{live_stock['leads']:,}*\n\n"
            f"Contact @{ADMIN_USER} to purchase.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    elif data == "store":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back")]
        ])
        await query.edit_message_text(
            f"🛍️ *Store*\n\n"
            f"Items in stock: *{live_stock['stock']}*\n\n"
            f"Contact @{ADMIN_USER} to browse and purchase.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    elif data == "scanner":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back")]
        ])
        await query.edit_message_text(
            f"🔍 *Scanner*\n\n"
            f"Send a value to scan and @{ADMIN_USER} will process it for you.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", cmd_start))

    # Admin commands
    app.add_handler(CommandHandler("addbalance",   cmd_addbalance))
    app.add_handler(CommandHandler("setstock",     cmd_setstock))
    app.add_handler(CommandHandler("checkbalance", cmd_checkbalance))

    # Button clicks
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
