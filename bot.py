import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Configure Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# File Paths for Persistence
DATA_FILE = "store_data.json"

# Default schema structure to avoid initialization errors
DEFAULT_DATA = {
    "bases": {},      # e.g., {"base_1": {"name": "UK Leads", "price": 10.0}}
    "stock_files": {} # e.g., {"base_1": ["line1", "line2"]}
}

def load_data():
    """Loads the store data from the local JSON file."""
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump(DEFAULT_DATA, f, indent=4)
        return DEFAULT_DATA
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading data file: {e}")
        return DEFAULT_DATA

def save_data(data):
    """Saves the store data back to the local JSON file."""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving data file: {e}")

def calculate_total_stock(data):
    """Dynamically calculates total store stock across all active bases."""
    total = 0
    stock_files = data.get("stock_files", {})
    for base_id, lines in stock_files.items():
        if isinstance(lines, list):
            total += len(lines)
    return total

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and displays the dynamic store stock."""
    data = load_data()
    total_stock = calculate_total_stock(data)
    
    # Building a clean store front interface
    welcome_text = (
        "👋 Welcome to the Store Bot!\n\n"
        f"🛍️ **Current Total Stock:** {total_stock} lines available.\n\n"
        "Use the menu options below or type an admin command to manage items."
    )
    
    keyboard = [[InlineKeyboardButton("View Available Categories", callback_data="view_categories")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def add_base(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin Command: /addbase <base_id> <name> <price>
    Updates or creates a base safely without wiping out any associated stock file data.
    """
    # Simple check (Replace with your actual Admin ID validation logic if needed)
    # if update.effective_user.id != ADMIN_ID: return
    
    if len(context.args) < 3:
        await update.message.reply_text("❌ Usage: `/addbase <base_id> <name> <price>`", parse_mode="Markdown")
        return

    base_id = context.args[0]
    price_str = context.args[-1]
    # Reconstruct name if it contains spaces
    name = " ".join(context.args[1:-1])

    try:
        price = float(price_str)
    except ValueError:
        await update.message.reply_text("❌ Price must be a valid number.")
        return

    data = load_data()
    
    # Initialize internal dictionaries safely if they don't exist
    if "bases" not in data:
        data["bases"] = {}
    if "stock_files" not in data:
        data["stock_files"] = {}

    # Update or add base details
    data["bases"][base_id] = {
        "name": name,
        "price": price
    }
    
    # FIX: Ensure existing stock line entries are never cleared or deleted during updates
    if base_id not in data["stock_files"]:
        data["stock_files"][base_id] = []

    save_data(data)
    
    current_lines = len(data["stock_files"][base_id])
    await update.message.reply_text(
        f"✅ **Base Updated Successfully!**\n\n"
        f"🆔 **ID:** `{base_id}`\n"
        f"📦 **Name:** {name}\n"
        f"💰 **Price:** ${price:.2f}\n"
        f"📊 **Existing Retained Stock:** {current_lines} lines",
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline menu selection actions."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "view_categories":
        data = load_data()
        bases = data.get("bases", {})
        
        if not bases:
            await query.edit_message_text("🚫 No categories or bases are currently available.")
            return
            
        response = "📁 **Available Categories:**\n\n"
        for b_id, info in bases.items():
            lines_count = len(data.get("stock_files", {}).get(b_id, []))
            response += f"🔹 **{info['name']}** (`{b_id}`) - ${info['price']:.2f} | Stock: {lines_count}\n"
            
        await query.edit_message_text(response, parse_mode="Markdown")

def main():
    """Initializes and launches the Telegram Bot Application."""
    # Retrieve the Token from Railway Environment Variables
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is missing!")
        return

    # Build the application setup
    application = Application.builder().token(BOT_TOKEN).build()

    # Register Bot Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addbase", add_base))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Run the bot until manually interrupted
    logger.info("Bot application started successfully.")
    application.run_polling()

if __name__ == '__main__':
    main()
    main()
