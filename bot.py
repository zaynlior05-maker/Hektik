import os
import logging
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
ADMIN_USER  = os.environ.get("ADMIN_USERNAME", "hektik")
MIN_BALANCE = 70

WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── In-memory storage ────────────────────────────────────────────────────────
user_balances  = {}   # { user_id: float }
agreed_users   = set()
user_join_dates = {}  # { user_id: date string }

live_stock = {
    "leads": 63_629_085,
    "stock": 183,
}

# Top-up amounts shown in wallet (starting from £70 minimum)
TOPUP_AMOUNTS = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]

# ── Rules text ───────────────────────────────────────────────────────────────
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
    "🔹 Support account is available 24/7 @EXCELV3.\n\n"
    "By continuing, you agree to the rules,\n"
    "Note: withdrawals can be made at any time.!"
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def has_access(user_id):
    return user_balances.get(user_id, 0) >= MIN_BALANCE


def get_join_date(user_id):
    if user_id not in user_join_dates:
        user_join_dates[user_id] = datetime.now().strftime("%m-%d-%Y")
    return user_join_dates[user_id]


async def get_crypto_prices():
    """Fetch live GBP prices for BTC, SOL, LTC from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana,litecoin&vs_currencies=gbp"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return {
                    "BTC": data["bitcoin"]["gbp"],
                    "SOL": data["solana"]["gbp"],
                    "LTC": data["litecoin"]["gbp"],
                }
    except Exception:
        return None


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


def wallet_profile_text(user_id):
    bal       = user_balances.get(user_id, 0)
    join_date = get_join_date(user_id)
    return (
        f"============================\n"
        f"🪪 *ID:* `{user_id}`\n"
        f"💰 *Balance:* £{bal:.2f}\n"
        f"📅 *Join Date:* {join_date}\n"
        f"============================\n\n"
        f"Select a top-up amount below:\n"
        f"_Minimum top-up: £{MIN_BALANCE}_"
    )


def amount_keyboard():
    """Build the grid of amount buttons, 2 per row."""
    buttons = []
    row = []
    for i, amount in enumerate(TOPUP_AMOUNTS):
        row.append(InlineKeyboardButton(f"💠 £{amount} 💠", callback_data=f"amount_{amount}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("💰 Custom Amount", callback_data="custom_amount")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


def coin_select_keyboard(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("₿ BTC", callback_data=f"pay_BTC_{amount}")],
        [InlineKeyboardButton("◎ SOL", callback_data=f"pay_SOL_{amount}")],
        [InlineKeyboardButton("Ł LTC", callback_data=f"pay_LTC_{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="wallet")],
    ])

# ── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_join_date(user_id)  # record join date on first /start

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

# ── Admin commands ────────────────────────────────────────────────────────────

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
        f"Added £{amount:.2f} to {target_id}. New balance: £{user_balances[target_id]:.2f}"
    )


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

# ── Button handler ────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data

    # Welcome screen Continue
    if data == "agree_rules":
        agreed_users.add(user_id)
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Back to main menu
    if data == "back":
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # Wallet — show profile + amount grid
    if data == "wallet":
        await query.edit_message_text(
            wallet_profile_text(user_id),
            reply_markup=amount_keyboard(),
            parse_mode="Markdown",
        )
        return

    # User tapped an amount — show coin selection
    if data.startswith("amount_"):
        amount = data.split("_")[1]
        await query.edit_message_text(
            f"💠 *£{amount} Top-Up*\n\nChoose your payment method:",
            reply_markup=coin_select_keyboard(amount),
            parse_mode="Markdown",
        )
        return

    # Custom amount — ask user to type it
    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text(
            "💰 *Custom Amount*\n\nType the amount in £ you want to top up (minimum £70):\n\nExample: `150`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]),
            parse_mode="Markdown",
        )
        return

    # Coin selected — fetch live price and show address + instructions
    if data.startswith("pay_"):
        parts  = data.split("_")   # pay_BTC_100
        coin   = parts[1]
        amount = int(parts[2])
        address = WALLETS.get(coin, "Address not configured")

        await query.edit_message_text("⏳ Fetching live price...")

        prices = await get_crypto_prices()
        if prices and coin in prices:
            crypto_price   = prices[coin]
            crypto_amount  = round(amount / crypto_price, 6)
            price_line     = f"Send *Exactly* `{crypto_amount}` {coin} to get *£{amount}* credit"
        else:
            price_line = f"Send the equivalent of *£{amount}* in {coin}"

        text = (
            f"{price_line}\n\n"
            f"🏦 Address:\n`{address}`\n\n"
            f"‼️ Deposits are permanent and *non refundable*\n"
            f"‼️ Double check the {coin} amount *before* sending\n"
            f"‼️ Anything UNDER or ABOVE the amount will be considered a *Donation*\n\n"
            f"💠 You will be funded when your transaction is confirmed\n\n"
            f"⚠️ By sending you agree to the above\n"
            f"⚠️ *DO NOT SEND AS £ — only send as {coin}*\n"
            f"‼️ One payment per wallet address\n"
            f"‼️ Anything else will Not be credited\n\n"
            f"_Your user ID: `{user_id}`_\n"
            f"_DM @{ADMIN_USER} with your TX ID after sending_"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data=f"amount_{amount}")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    # Access-gated sections
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
                    InlineKeyboardButton("⬅️ Back",   callback_data="back"),
                ]
            ]),
        )
        return

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back")]])

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

# ── Custom amount message handler ─────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_custom"):
        return

    text = update.message.text.strip().replace("£", "")
    try:
        amount = int(float(text))
        if amount < MIN_BALANCE:
            await update.message.reply_text(
                f"Minimum top-up is £{MIN_BALANCE}. Please enter a higher amount."
            )
            return
    except ValueError:
        await update.message.reply_text("Please enter a valid number, e.g. 150")
        return

    context.user_data["awaiting_custom"] = False
    await update.message.reply_text(
        f"💠 *£{amount} Top-Up*\n\nChoose your payment method:",
        reply_markup=coin_select_keyboard(amount),
        parse_mode="Markdown",
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("addbalance",   cmd_addbalance))
    app.add_handler(CommandHandler("setstock",     cmd_setstock))
    app.add_handler(CommandHandler("checkbalance", cmd_checkbalance))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
