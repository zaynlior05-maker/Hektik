import os
import json
import logging
import asyncio
import aiohttp
import pycountry
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
import copy as _copy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Where data is saved. Set DATA_DIR=/data in Railway (with a Volume mounted at /data)
# so it survives restarts AND redeploys.
DATA_DIR  = os.environ.get("DATA_DIR", ".")
DATA_FILE = os.path.join(DATA_DIR, "botdata.json")

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN            = os.environ.get("BOT_TOKEN")
SUPER_ADMIN          = os.environ.get("ADMIN_USERNAME", "HekTikz")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "changeme123")
LOG_CHANNEL_ID       = os.environ.get("LOG_CHANNEL_ID")
MIN_TOPUP            = 70

# Minimum required balance a user must have to make a purchase.
MIN_DEPOSIT_REQUIRED = float(os.environ.get("MIN_DEPOSIT_REQUIRED", 150.00))

# Private channel setup
_raw = os.environ.get("JOIN_CHANNEL", "")
JOIN_CHANNEL     = _raw if _raw else None
JOIN_CHANNEL_URL = os.environ.get("JOIN_CHANNEL_URL", "https://t.me/+yourchannelinvitelink")

WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── Storage ───────────────────────────────────────────────────────────────────
user_balances    = {}
agreed_users     = set()
user_join_dates  = {}
logged_in_admins = set()
channel_verified = set()

live_stock    = {"leads": 63_629_085} 
TOPUP_AMOUNTS = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]
BINS_PER_PAGE = 20   
COUNTRIES_PER_PAGE = 20
ITEMS_PER_PAGE = 8

# ── Store Data ────────────────────────────────────────────────────────────────
STORE = {
    "8888": {
        "label": "Vendor 8888",
        "bases": {
            "15fresh": {
                "label": "£15 Base - Fresh Lives 🇬🇧",
                "price_per_card": 15,
                "bins": {
                    "371789": 6,  "374288": 1,  "377383": 3,  "377390": 9,
                    "379006": 1,  "402396": 1,  "402399": 1,  "404972": 2,
                    "416549": 9,  "416598": 16, "446223": 1,  "446261": 7,
                    "446278": 1,  "446291": 1,  "449352": 2,  "449353": 2,
                    "450875": 1,  "454313": 6,  "454638": 2,  "459647": 4,
                    "459661": 2,  "462010": 3,  "465941": 2,  "470041": 1,
                    "471626": 5,  "480038": 2,  "484446": 1,  "486490": 3,
                    "490581": 1,  "491179": 2,
                },
            }
        },
    },
    "1717": {
        "label": "Vendor 1717",
        "bases": {
            "10fresh": {
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
    ("50+ Specific BIN, Gender & DOB File",  225,  "dspec50"),
    ("100+ Specific BIN, Gender & DOB File", 350,  "dspec100"),
    ("50+ Random File",                      100,  "drand50"),
    ("100+ Random File",                     150,  "drand100"),
    ("500 Random File",                      500,  "drand500"),
    ("1k Random File",                       700,  "drand1k"),
    ("2k Random File",                       1200, "drand2k"),
]

SCANNER_ITEMS = [
    ("Binance · Email",       "crypto",   3.00),
    ("Binance · Filter",      "crypto",   1.50),
    ("CoinW · Email",         "crypto",   1.50),
    ("CoinW · Mobile",        "crypto",   1.50),
    ("HTX · Email",           "crypto",   1.50),
    ("HTX · Mobile",          "crypto",   1.50),
    ("KuCoin · Email",        "crypto",   1.50),
    ("KuCoin · Mobile",       "crypto",   1.00),
    ("OKX · Filter",          "crypto",   3.00),
    ("Robinhood · Check",     "crypto",   2.50),
    ("Facebook · Email",      "socials",  1.00),
    ("Instagram · Mobile",    "socials",  1.00),
    ("LinkedIn · Profile",    "socials",  15.00),
    ("Signal",                "socials",  1.00),
    ("Snapchat",              "socials",  2.00),
    ("iMessage · Filter",     "socials",  0.35),
    ("DHL",                   "shopping", 1.50),
    ("Shein",                 "shopping", 15.00),
    ("Carrier · Any",         "carrier",  1.50),
    ("Carrier · Bangladesh",  "carrier",  0.75),
    ("Carrier · Belgium",     "carrier",  0.75),
    ("Carrier · Brazil",      "carrier",  0.75),
    ("Carrier · France",      "carrier",  0.75),
    ("Carrier · Germany",     "carrier",  0.75),
    ("Carrier · HK",          "carrier",  0.75),
    ("Carrier · Indonesia",   "carrier",  0.75),
    ("Carrier · Italy",       "carrier",  0.75),
    ("Carrier · Japan",       "carrier",  0.75),
    ("Carrier · Pakistan",    "carrier",  0.75),
    ("Carrier · Portugal",    "carrier",  0.75),
    ("Carrier · Russia",      "carrier",  0.75),
    ("Carrier · Spain",       "carrier",  0.75),
    ("Carrier · Sweden",      "carrier",  0.75),
    ("Carrier · UK",          "carrier",  0.75),
    ("Carrier · US",          "carrier",  0.75),
    ("Carrier · Ukraine",     "carrier",  0.75),
    ("Carrier · Uzbekistan",  "carrier",  0.75),
    ("Carrier · Vietnam",     "carrier",  0.75),
]

SCANNER_PER_PAGE = 10
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]

LEADS_PRICING = [
    (1_000,   15),  (2_000,  30),  (3_000,   45),  (4_000,  50),
    (5_000,   60),  (6_000,  65),  (7_000,   70),  (8_000,  80),
    (10_000, 100),  (15_000,125),  (20_000, 150),  (25_000,175),
    (30_000, 200),  (50_000,300),  (100_000,600),
]

def get_category_pricing_dict(cc):
    if cc in LEADS and "pricing" in LEADS[cc]:
        return {int(k): float(v) for k, v in LEADS[cc]["pricing"].items()}
    return dict(LEADS_PRICING)

# ── FULL LEADS DICTIONARY (Kept fully intact) ─────────────────────────────────
LEADS = {
    "US": {
        "flag": "🇺🇸", "name": "United States",
        "subcats": {
            "crypto": {"name": "🪙 Crypto", "items": {"Coinbase US": 3500000, "Binance.US": 2200000, "Kraken US": 1900000, "Gemini": 1200000}},
            "bank": {"name": "🏦 Banks", "items": {"JPMorgan Chase": 4200000, "Bank of America": 3800000, "Citibank": 2900000, "Wells Fargo": 3100000, "Capital One": 2500000}},
            "business": {"name": "🏢 Business", "items": {"Stripe US": 3200000, "PayPal US": 5100000, "Square": 2800000, "Adyen US": 1100000}},
            "network": {"name": "📡 Network", "items": {"AT&T": 12800000, "Verizon": 11400000, "T-Mobile": 9700000, "Boost Mobile": 2100000, "Cricket": 1900000}}
        }
    },
    "UK": {
        "flag": "🇬🇧", "name": "United Kingdom",
        "subcats": {
            "crypto": {"name": "🪙 Crypto", "items": {"Binance UK": 1800000, "Coinbase UK": 1500000, "Kraken UK": 1100000, "Revolut Crypto": 2100000}},
            "bank": {"name": "🏦 Banks", "items": {"HSBC UK": 3500000, "Barclays": 3100000, "Lloyds Bank": 2800000, "NatWest": 2400000, "Monzo": 1900000}},
            "business": {"name": "🏢 Business", "items": {"Wise UK": 1900000, "Revolut Business": 2200000, "Checkout.com": 950000}},
            "network": {"name": "📡 Network", "items": {"EE": 3544000, "O2": 1831000, "Sky": 553000, "Three": 4515000, "Vodafone": 530000}}
        }
    },
    "AU": {
        "flag": "🇦🇺", "name": "Australia",
        "subcats": {
            "crypto": {"name": "🪙 Crypto", "items": {"Binance AU": 1200000, "CoinSpot": 1500000, "Independent Reserve": 800000, "Swyftx": 950000}},
            "bank": {"name": "🏦 Banks", "items": {"CBA": 2900000, "Westpac": 2400000, "NAB": 2100000, "ANZ Bank": 1800000, "Macquarie Bank": 1100000}},
            "business": {"name": "🏢 Business", "items": {"Wise Australia": 900000, "PayPal AU": 1800000, "Afterpay": 1400000, "Square AU": 750000}},
            "network": {"name": "📡 Network", "items": {"Telstra": 4200000, "Optus": 3100000, "Vodafone": 1800000, "Boost Mobile": 620000, "TPG": 430000}}
        }
    },
    "CA": {
        "flag": "🇨🇦", "name": "Canada",
        "subcats": {
            "crypto": {"name": "🪙 Crypto", "items": {"Shakepay": 950000, "Coinbase CA": 1100000, "Newton": 800000, "Kraken CA": 700000}},
            "bank": {"name": "🏦 Banks", "items": {"RBC": 2800000, "TD Bank": 2500000, "Scotiabank": 2100000, "BMO": 1800000, "CIBC": 1600000}},
            "business": {"name": "🏢 Business", "items": {"Shopify": 1800000, "Wise CA": 850000, "PayPal CA": 1500000}},
            "network": {"name": "📡 Network", "items": {"Rogers": 4100000, "Bell": 3800000, "Telus": 3500000, "Fido": 980000, "Koodo": 760000}}
        }
    },
    "IE": {
        "flag": "🇮🇪", "name": "Ireland",
        "subcats": {
            "crypto": {"name": "🪙 Crypto", "items": {"Coinbase IE": 700000, "Binance IE": 900000, "Kraken IE": 600000}},
            "bank": {"name": "🏦 Banks", "items": {"Bank of Ireland": 1800000, "AIB": 1500000, "Permanent TSB": 950000, "Revolut IE": 1200000}},
            "business": {"name": "🏢 Business", "items": {"Stripe IE": 1400000, "PayPal IE": 1600000}},
            "network": {"name": "📡 Network", "items": {"Eir": 833503, "Tesco Mobile": 520700, "Three A": 351645, "Three B": 861444, "Vodafone": 1720550}}
        }
    }
}
LEADS["GLOBAL"] = {
    "flag": "🌍", "name": "Global / Generic",
    "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance Global": 2500000, "Kraken Global": 1800000, "OKX": 1500000, "KuCoin": 1200000}},
        "business": {"name": "🏢 Big Tech", "items": {"Apple": 4500000, "Amazon": 3800000, "Google": 3400000, "Meta": 2100000}}
    }
}
for _cc, _d in LEADS.items():
    if "network" in _d.get("subcats", {}):
        net_dict = _d["subcats"]["network"]["items"]
        if "MIX" not in net_dict:
            _biggest = max(net_dict.values()) if net_dict else 100000
            net_dict["MIX"] = int(_biggest * 1.25)

DEFAULT_LEADS = _copy.deepcopy(LEADS)

AGED_LEADS_PRICING = [(1_000, 70), (5_000, 300), (10_000, 500), (25_000, 1100)]
CRYPTO_LEADS_PRICING = [(1_000, 200), (5_000, 800), (10_000, 1500), (25_000, 2500)]

RULES_TEXT = (
    "🛍 *Welcome to HekTik's Store!*\n\n"
    "To access the store, you are required to join our channel below.\n\n"
    "*Refund Rules*\n"
    "• /refund to submit refunds\n"
    "• Screen recording proof of pay.google.com only, 5 mins refund time\n"
    "• If the card is live but phone number is incorrect, no refund\n\n"
    "*Spam source Rules*\n"
    "• The scan balance is separate from the rest of the bot — will not transfer over\n\n"
    "*Keep in Mind:* *(£10 & £5 BASES ARE NOT REFUNDABLE)*\n\n"
    "🔴 *NOTE* 🔴\n"
    "ANYONE NEED BULK SMS/EMAIL BLAST WITH SID 100% LANDING (NO BOUNCE) CODING\n"
    "• Centers, panels, pages & scripts available pm\n\n"
    "🔹 Support 24/7 @HekTikz.\n\n"
    "By continuing, you agree to the rules.\n"
    "Note: withdrawals can be made at any time!"
)

# ── Dynamic A–Z Sovereign Country Dataset ─────────────────────────────────────
ALL_COUNTRIES = sorted(list(pycountry.countries), key=lambda x: x.name)

def get_country_flag(country_alpha_2: str) -> str:
    try:
        return chr(ord(country_alpha_2[0].upper()) + 127397) + chr(ord(country_alpha_2[1].upper()) + 127397)
    except Exception:
        return "🌐"

# ── Dynamic API Bridge & Aggregator ────────────────────────────────────────────
async def fetch_dynamic_vertical(country_code: str, vertical: str) -> list:
    """
    Acts as a bridge: First checks if the data exists in your static LEADS dictionary.
    If it does, it loads it. If not, it generates dynamic fallback data.
    """
    iso2 = country_code.upper()
    items = []

    # 1. Check for legacy data in LEADS
    if iso2 in LEADS and "subcats" in LEADS[iso2] and vertical in LEADS[iso2]["subcats"]:
        static_items = LEADS[iso2]["subcats"][vertical]["items"]
        pricing_dict = get_category_pricing_dict(iso2)
        base_price = pricing_dict.get(1000, 15.0) # Default 15 per 1k if missing
        for name, stock in static_items.items():
            items.append({"name": name, "stock": stock, "price": base_price})
    
    # 2. If no legacy data found, inject dynamic data
    if not items:
        country_obj = pycountry.countries.get(alpha_2=iso2)
        c_name = country_obj.name if country_obj else iso2
        base_price = 15.0

        if vertical == "crypto":
            items = [
                {"name": f"Binance {iso2} P2P", "stock": 1250000, "price": 45.0},
                {"name": f"Coinbase {iso2}", "stock": 850000, "price": 40.0},
                {"name": f"Kraken {iso2}", "stock": 620000, "price": 35.0},
                {"name": f"Local Exchange ({c_name})", "stock": 300000, "price": 30.0},
            ]
        elif vertical == "bank":
            items = [
                {"name": f"{c_name} National Bank", "stock": 2100000, "price": 60.0},
                {"name": f"Central Commercial Bank ({iso2})", "stock": 1400000, "price": 50.0},
                {"name": f"First Premier Bank ({c_name})", "stock": 950000, "price": 45.0},
                {"name": f"International Banking Hub ({iso2})", "stock": 600000, "price": 40.0},
            ]
        elif vertical == "business":
            items = [
                {"name": f"{c_name} OpenCorporates Registry", "stock": 450000, "price": 100.0},
                {"name": f"{c_name} Corporate Tax Index", "stock": 250000, "price": 85.0},
                {"name": f"Trade & Enterprise DB ({iso2})", "stock": 180000, "price": 75.0},
            ]
        elif vertical == "network":
            items = [
                {"name": f"Carrier · {c_name} (Primary)", "stock": 4500000, "price": 25.0},
                {"name": f"Mobile Operator B ({iso2})", "stock": 2800000, "price": 20.0},
                {"name": f"Telecom Operator C ({iso2})", "stock": 1900000, "price": 18.0},
            ]
        elif vertical == "nodes":
            items = [
                {"name": f"{c_name} Regional RPC Nodes", "stock": 45000, "price": 150.0},
                {"name": f"{iso2} Blockchain Validator Hub", "stock": 12000, "price": 200.0},
                {"name": f"Local Web3 Node Cluster", "stock": 8500, "price": 180.0},
            ]
            
    return items

def get_pricing_tiers(base_price: float):
    return [
        (1_000, base_price), (5_000, round(base_price * 4, 2)),
        (10_000, round(base_price * 7.5, 2)), (25_000, round(base_price * 15, 2)),
    ]

# ── Data Storage Engine ───────────────────────────────────────────────────────
def calculate_dynamic_stock():
    total = 0
    for vid, vdata in STORE.items():
        for bkey, bdata in vdata.get("bases", {}).items():
            for qty in bdata.get("bins", {}).values():
                total += qty
    return total

def save_data():
    try:
        data = {
            "user_balances":   {str(k): v for k, v in user_balances.items()},
            "agreed_users":    list(agreed_users),
            "user_join_dates": {str(k): v for k, v in user_join_dates.items()},
            "channel_verified":list(channel_verified),
            "live_stock":      live_stock,
            "STORE":           STORE,
            "LEADS":           LEADS,
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        logger.error(f"save_data failed: {e}")

def load_data():
    global user_balances, agreed_users, user_join_dates, channel_verified, live_stock, STORE, LEADS
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE) as f: data = json.load(f)
        user_balances    = {int(k): v for k, v in data.get("user_balances", {}).items()}
        agreed_users     = set(data.get("agreed_users", []))
        user_join_dates  = {int(k): v for k, v in data.get("user_join_dates", {}).items()}
        channel_verified = set(data.get("channel_verified", []))
        live_stock.update(data.get("live_stock", {}))
        if data.get("STORE"):
            STORE.clear(); STORE.update(data["STORE"])
        if data.get("LEADS"):
            sample_key = list(data["LEADS"].keys())[0]
            if "subcats" not in data["LEADS"][sample_key]:
                LEADS.clear(); LEADS.update(DEFAULT_LEADS)
            else:
                LEADS.clear(); LEADS.update(data["LEADS"])
    except Exception as e:
        logger.error(f"load_data failed: {e}")

async def log(app, text: str):
    if not LOG_CHANNEL_ID: return
    try: await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception: pass

def is_admin(update) -> bool:
    uid = update.effective_user.id
    return (update.effective_user.username == SUPER_ADMIN) or (uid in logged_in_admins)

async def check_channel_membership(bot, user_id):
    if not JOIN_CHANNEL: return True, "ok"
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"): return True, "ok"
        return False, "not_joined"
    except Exception: return False, "error"

def get_join_date(uid):
    if uid not in user_join_dates: user_join_dates[uid] = datetime.now().strftime("%m-%d-%Y")
    return user_join_dates[uid]

async def get_crypto_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana,litecoin&vs_currencies=gbp"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
                return {"BTC": d["bitcoin"]["gbp"], "SOL": d["solana"]["gbp"], "LTC": d["litecoin"]["gbp"]}
    except Exception: return None

# ── Dynamic Navigation & Paginated Keyboards ──────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads Directory",  callback_data="leads"),
         InlineKeyboardButton("🛍️ Store",            callback_data="store")],
        [InlineKeyboardButton("💰 Wallet",           callback_data="wallet"),
         InlineKeyboardButton("🔍 Scanner",          callback_data="scanner")],
        [InlineKeyboardButton("🎯 Targeted Source",  callback_data="tsource")],
    ])

def main_menu_text():
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Inventory*\n"
        f"🌍 Global Directory: *195+ Countries Active*\n"
        f"⚡️ Live System Stock: *{live_stock['leads']:,}*\n"
        f"🛍️ Store Stock: *{calculate_dynamic_stock():,}*\n\n"
        "_Choose a section below:_"
    )

def a_z_country_keyboard(page: int = 0):
    total_pages = max(1, (len(ALL_COUNTRIES) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)
    page_items = ALL_COUNTRIES[page * COUNTRIES_PER_PAGE : (page + 1) * COUNTRIES_PER_PAGE]
    rows = []
    for i in range(0, len(page_items), 2):
        row = []
        for c in page_items[i:i+2]:
            flag = get_country_flag(c.alpha_2)
            name = c.name if len(c.name) <= 18 else c.name[:16] + ".."
            row.append(InlineKeyboardButton(f"{flag} {name}", callback_data=f"c_dash|{c.alpha_2}"))
        rows.append(row)
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"az_list|{page-1}"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"az_list|{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back to Main", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def country_vertical_keyboard(iso2: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Crypto Exchanges",    callback_data=f"c_vert|{iso2}|crypto")],
        [InlineKeyboardButton("🏦 Banks & Financial",   callback_data=f"c_vert|{iso2}|bank")],
        [InlineKeyboardButton("🏢 Business Registries", callback_data=f"c_vert|{iso2}|business")],
        [InlineKeyboardButton("📡 Mobile Networks",     callback_data=f"c_vert|{iso2}|network")],
        [InlineKeyboardButton("🔗 Ledgers & Nodes",     callback_data=f"c_vert|{iso2}|nodes")],
        [InlineKeyboardButton("⬅️ Back to Directory",   callback_data="leads")],
    ])

def paginated_entity_keyboard(iso2: str, vertical: str, items: list, page: int = 0, total_items: int = None):
    if total_items is None: total_items = len(items)
    total_pages = max(1, (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ITEMS_PER_PAGE
    page_items = items[start_idx : start_idx + ITEMS_PER_PAGE]

    rows = []
    for i in range(0, len(page_items), 2):
        row = []
        for item in page_items[i:i+2]:
            name = item["name"]
            stock = item.get("stock", 0)
            price = item.get("price", 15.0)
            row.append(InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"c_item|{iso2}|{vertical}|{name}|{price}"))
        rows.append(row)

    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"c_page|{iso2}|{vertical}|{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"c_page|{iso2}|{vertical}|{page+1}"))
    rows.append(nav_row)
    
    rows.append([
        InlineKeyboardButton("🔍 Search", callback_data=f"c_search|{iso2}|{vertical}"),
        InlineKeyboardButton("⬅️ Back", callback_data=f"c_dash|{iso2}")
    ])
    return InlineKeyboardMarkup(rows)

def dynamic_qty_keyboard(iso2: str, vertical: str, item_name: str, base_price: float):
    rows = []
    tiers = get_pricing_tiers(base_price)
    for i in range(0, len(tiers), 2):
        row = []
        for qty, price in tiers[i:i+2]:
            k = f"{qty//1000}k" if qty >= 1000 else str(qty)
            row.append(InlineKeyboardButton(f"{k} — £{price:g}", callback_data=f"c_buy|{iso2}|{vertical}|{item_name}|{qty}|{price}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"c_vert|{iso2}|{vertical}")])
    return InlineKeyboardMarkup(rows)

# ── Old Static Keyboards (Kept completely intact) ──────────────────────────────

def wallet_profile_text(uid):
    return (
        f"============================\n"
        f"🪪 *ID:* `{uid}`\n"
        f"💰 *Balance:* £{user_balances.get(uid,0):.2f}\n"
        f"📅 *Join Date:* {get_join_date(uid)}\n"
        f"============================\n\n"
        f"Select a top-up amount below:\n_Minimum top-up: £{MIN_TOPUP}_"
    )

def amount_keyboard():
    rows, row = [], []
    for a in TOPUP_AMOUNTS:
        row.append(InlineKeyboardButton(f"🔶 £{a} 🔶", callback_data=f"amt|{a}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("💰 Custom Amount", callback_data="custom_amount")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def coin_select_keyboard(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("₿ BTC", callback_data=f"pay|BTC|{amount}")],
        [InlineKeyboardButton("◎ SOL", callback_data=f"pay|SOL|{amount}")],
        [InlineKeyboardButton("Ł LTC", callback_data=f"pay|LTC|{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="wallet")],
    ])

def vendor_select_keyboard():
    rows = []
    vids = list(STORE.keys())
    for i in range(0, len(vids), 2):
        rows.append([InlineKeyboardButton(v, callback_data=f"vendor|{v}") for v in vids[i:i+2]])
    rows.append([InlineKeyboardButton("💀 Deads", callback_data="deads")])
    rows.append([InlineKeyboardButton("⬅️ Back",  callback_data="back")])
    return InlineKeyboardMarkup(rows)

def base_select_keyboard(vid):
    rows = [[InlineKeyboardButton(b["label"], callback_data=f"base|{vid}|{bk}")] for bk, b in STORE[vid]["bases"].items()]
    rows.append([InlineKeyboardButton("🔍 BIN Search", callback_data=f"bsearch|{vid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def bin_list_keyboard(vid, bkey, page=0):
    bins        = list(STORE[vid]["bases"][bkey]["bins"].items())
    total_pages = max(1, (len(bins) + BINS_PER_PAGE - 1) // BINS_PER_PAGE)
    page_bins   = bins[page * BINS_PER_PAGE : (page + 1) * BINS_PER_PAGE]
    rows = []
    for i in range(0, len(page_bins), 2):
        rows.append([InlineKeyboardButton(f"{b} ({q})", callback_data=f"buybin|{vid}|{bkey}|{b}|{page}") for b, q in page_bins[i:i+2]])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bpage|{vid}|{bkey}|{page-1}"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"bpage|{vid}|{bkey}|{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
    return InlineKeyboardMarkup(rows), total_pages

def deads_keyboard():
    rows = [[InlineKeyboardButton(f"{l} — £{p:,}", callback_data=f"dbuy|{k}")] for l, p, k in DEADS_ITEMS]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def scanner_items_for_cat(cat):
    if cat == "all": return list(enumerate(SCANNER_ITEMS))
    return [(i, item) for i, item in enumerate(SCANNER_ITEMS) if item[1] == cat]

def scanner_keyboard(cat="all", page=0):
    items      = scanner_items_for_cat(cat)
    total_pages = max(1, (len(items) + SCANNER_PER_PAGE - 1) // SCANNER_PER_PAGE)
    page_items  = items[page * SCANNER_PER_PAGE : (page + 1) * SCANNER_PER_PAGE]
    rows = []
    tab_row = [InlineKeyboardButton(f"› {label}" if key == cat else label, callback_data=f"scan|{key}|0") for key, label in SCAN_CATS.items()]
    rows.append(tab_row)
    for idx, (label, category, price) in page_items:
        price_fmt = f"${price:.2f}" if price != int(price) else f"${int(price):.2f}"
        rows.append([InlineKeyboardButton(f"{label} — {price_fmt} / k", callback_data=f"sni|{idx}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("← Prev", callback_data=f"scan|{cat}|{page-1}"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton("Next →", callback_data=f"scan|{cat}|{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def scanner_qty_keyboard(idx, cat="all", page=0):
    label, category, price = SCANNER_ITEMS[idx]
    rows = []
    for i in range(0, len(SCANNER_QTYS), 2):
        row = [InlineKeyboardButton(f"{qty_k}k — £{qty_k * price:.2f}", callback_data=f"snq|{idx}|{qty_k}") for qty_k in SCANNER_QTYS[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"scan|{cat}|{page}")])
    return InlineKeyboardMarkup(rows)

def tsource_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("‼️ Aged / Bank-Targeted Leads", callback_data="ts_aged")],
        [InlineKeyboardButton("🪙 Crypto Leads",               callback_data="ts_crypto")],
        [InlineKeyboardButton("🛠 Additional Services",         callback_data="ts_services")],
        [InlineKeyboardButton("⬅️ Back",                        callback_data="back")],
    ])

def ts_qty_keyboard(pricing, cb_prefix):
    rows = []
    for i in range(0, len(pricing), 2):
        row = []
        for qty, price in pricing[i:i+2]:
            k = qty // 1000
            label = f"£{price//1000}k" if price >= 1000 else f"£{price}"
            row.append(InlineKeyboardButton(f"{k}k — {label}", callback_data=f"{cb_prefix}|{qty}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tsource")])
    return InlineKeyboardMarkup(rows)

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

def get_blocked_message(balance, item_price, back_cb):
    if balance == 0:
        return f"❌ *Insufficient Balance!*\nThis item costs £{item_price:.2f}.", InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top Up Wallet", callback_data="wallet")]])
    if balance < MIN_DEPOSIT_REQUIRED:
        return f"🛑 *Order Blocked*\nAccount balance below minimum deposit requirement (£{MIN_DEPOSIT_REQUIRED:.2f}).", InlineKeyboardMarkup([[InlineKeyboardButton("➕ Top Up", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]])
    if balance < item_price:
        return f"❌ *Insufficient Balance!*\nThis item costs £{item_price:.2f} but you have £{balance:.2f}.", InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]])
    return None, None

# ── User Commands ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_join_dates: user_join_dates[uid] = datetime.now().strftime("%m-%d-%Y")
    
    if uid in agreed_users:
        await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return
    await update.message.reply_text(RULES_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've Joined — Let Me In", callback_data="agree_rules")]]), parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    await update.message.reply_text(f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*", parse_mode="Markdown")

async def cmd_targeted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎯 *Targeted Source*\n\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")

SUPPORT_USER = os.environ.get("SUPPORT_USERNAME", "HekTikz")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 *Contact / Support*\n\n"
        f"👤 Admin: @{SUPER_ADMIN}\n"
        f"🔹 Support 24/7: @{SUPPORT_USER}\n\n",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👤 Message Admin",   url=f"https://t.me/{SUPER_ADMIN}")],
            [InlineKeyboardButton(f"🔹 Message Support", url=f"https://t.me/{SUPPORT_USER}")],
        ]),
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How to use this bot*\n\n"
        "1️⃣ Top up your balance — /wallet (crypto: BTC, SOL, LTC)\n"
        "2️⃣ Browse sections from /start:\n"
        "   🌍 Leads · 🛍️ Store · 🔍 Scanner · 🎯 Targeted Source\n"
        "3️⃣ Pick an item and confirm\n\n"
        "*Commands:*\n/start · /wallet · /balance · /targeted · /contact",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")]        ]),
        parse_mode="Markdown"
    )

# ── Callback Query Router ─────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data
    await query.answer()

    if data == "noop": return

    if data == "agree_rules":
        agreed_users.add(uid); channel_verified.add(uid); save_data()
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty", "awaiting_search"):
        context.user_data.pop(_k, None)

    # ── Universal A–Z Country Directory & Navigation (Fully Paginated) ──────
    if data == "leads":
        await query.edit_message_text("🌍 *A–Z Sovereign Country Directory*\n_Page 1_\nSelect a nation:", reply_markup=a_z_country_keyboard(0), parse_mode="Markdown")
        return

    if data.startswith("az_list|"):
        page = int(data.split("|")[1])
        await query.edit_message_text(f"🌍 *A–Z Sovereign Country Directory*\n_Page {page+1}_\nSelect a nation:", reply_markup=a_z_country_keyboard(page), parse_mode="Markdown")
        return

    if data.startswith("c_dash|"):
        iso2 = data.split("|")[1]
        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2
        flag = get_country_flag(iso2)
        await query.edit_message_text(f"{flag} *{c_name} Data Hub*\n\nSelect a dynamic data vertical:", reply_markup=country_vertical_keyboard(iso2), parse_mode="Markdown")
        return

    if data.startswith("c_vert|"):
        _, iso2, vertical = data.split("|")
        items = await fetch_dynamic_vertical(iso2, vertical)
        
        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2
        flag = get_country_flag(iso2)

        if not items:
            await query.edit_message_text(
                f"⚠️ No items available for *{c_name}* under {vertical.title()}.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"c_dash|{iso2}")]]), 
                parse_mode="Markdown"
            )
            return

        # Store items in context for fast pagination/search
        context.user_data[f"items_{iso2}_{vertical}"] = items

        await query.edit_message_text(
            f"{flag} *{c_name} ➔ {vertical.title()}*\nSelect an available entity:", 
            reply_markup=paginated_entity_keyboard(iso2, vertical, items, page=0), 
            parse_mode="Markdown"
        )
        return

    if data.startswith("c_page|"):
        _, iso2, vertical, page_str = data.split("|")
        page = int(page_str)
        
        items = context.user_data.get(f"items_{iso2}_{vertical}")
        if not items:
            items = await fetch_dynamic_vertical(iso2, vertical)
            context.user_data[f"items_{iso2}_{vertical}"] = items

        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2
        flag = get_country_flag(iso2)

        await query.edit_message_text(
            f"{flag} *{c_name} ➔ {vertical.title()}*\n_Page {page+1}_", 
            reply_markup=paginated_entity_keyboard(iso2, vertical, items, page=page), 
            parse_mode="Markdown"
        )
        return

    if data.startswith("c_search|"):
        _, iso2, vertical = data.split("|")
        context.user_data["search_target"] = (iso2, vertical)
        context.user_data["awaiting_search"] = True
        
        await query.edit_message_text(
            f"🔍 *Search {vertical.title()}*\n\nType the name of the bank, exchange, or provider you are looking for:", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancel", callback_data=f"c_vert|{iso2}|{vertical}")]]), 
            parse_mode="Markdown"
        )
        return

    if data.startswith("c_item|"):
        _, iso2, vertical, item_name, price_str = data.split("|")
        price = float(price_str)
        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2
        
        await query.edit_message_text(
            f"📦 *Entity:* {item_name}\n🌍 *Region:* {get_country_flag(iso2)} {c_name}\n\nSelect volume quantity:",
            reply_markup=dynamic_qty_keyboard(iso2, vertical, item_name, price),
            parse_mode="Markdown"
        )
        return

    if data.startswith("c_buy|"):
        _, iso2, vertical, item_name, qty_str, price_str = data.split("|")
        qty, price = int(qty_str), float(price_str)
        balance = user_balances.get(uid, 0)

        err, kbd = get_blocked_message(balance, price, f"c_vert|{iso2}|{vertical}")
        if err:
            await query.edit_message_text(err, reply_markup=kbd, parse_mode="Markdown")
            return

        user_balances[uid] = round(balance - price, 2)
        save_data()
        await query.edit_message_text(
            f"✅ *Export Order Confirmed!*\n\n"
            f"Category: *{vertical.title()}*\n"
            f"Region: {get_country_flag(iso2)} *{iso2}*\n"
            f"Entity: *{item_name}*\n"
            f"Quantity: *{qty:,}*\n"
            f"Paid: *£{price:g}*\n\n"
            f"Contact @{SUPER_ADMIN} to receive the export package.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Main", callback_data="back")]]),
            parse_mode="Markdown"
        )
        return

    # Wallet
    if data == "wallet":
        await query.edit_message_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("amt|"):
        amount = data.split("|")[1]
        await query.edit_message_text(f"🔶 *£{amount} Top-Up*\n\nChoose payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text("💰 *Custom Amount*\n\nType the £ amount (minimum £70):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]), parse_mode="Markdown")
        return

    if data.startswith("pay|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        address = WALLETS.get(coin, "Address not configured")
        prices = await get_crypto_prices()
        price_line = f"Send *Exactly* `{round(amount / prices[coin], 6)}` {coin}" if (prices and coin in prices) else f"Send equivalent of *£{amount}* in {coin}"
        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]),
            parse_mode="Markdown")
        return

    # Store
    if data == "store":
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("vendor|"):
        vid = data.split("|")[1]
        if vid not in STORE: return
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n\nSelect a base:", reply_markup=base_select_keyboard(vid), parse_mode="Markdown")
        return

    if data.startswith("base|"):
        _, vid, bkey = data.split("|", 2)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(f"📦 *Base:* {base['label']}\nSelect BIN group:\n_Page 1 of {total_pages}_", reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bpage|"):
        _, vid, bkey, page = data.split("|", 3); page = int(page)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(f"📦 *Base:* {base['label']}\nSelect BIN group:\n_Page {page+1} of {total_pages}_", reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid
        context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(f"🔍 *BIN Search*\n\nType the BIN number:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")
        return

    if data.startswith("buybin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        if qty == 0: await query.answer("Out of stock."); return
        price = base["price_per_card"]
        context.user_data["buy_bin"] = {"vid": vid, "bkey": bkey, "bin_num": bin_num, "page": page, "price": price, "available": qty}
        context.user_data["awaiting_qty"] = True
        await query.edit_message_text(f"💳 *BIN:* {bin_num}\n💷 *Price:* £{price:.2f}\nEnter quantity (1-{qty}):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"bpage|{vid}|{bkey}|{page}")]]) , parse_mode="Markdown")
        return

    if data.startswith("cfmqty|"):
        _, vid, bkey, bin_num, qty_s = data.split("|", 4)
        buy_qty = int(qty_s); base = STORE[vid]["bases"][bkey]; stock = base["bins"].get(bin_num, 0)
        price = base["price_per_card"]; total = round(price * buy_qty, 2); balance = user_balances.get(uid, 0)
        
        blocked_text, blocked_kbd = get_blocked_message(balance, total, f"vendor|{vid}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return

        user_balances[uid] = round(balance - total, 2)
        base["bins"][bin_num] = stock - buy_qty
        if base["bins"][bin_num] <= 0: del base["bins"][bin_num]
        save_data()

        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n💳 BIN: *{bin_num}*\n🗂 Qty: *{buy_qty} fullz*\n💷 Paid: *£{total:.2f}*\n\nContact @{SUPER_ADMIN} for files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    if data == "deads":
        await query.edit_message_text("💀 *Deads — Unspoofed Files*", reply_markup=deads_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("dbuy|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirm", callback_data=f"dcfm|{key}"),
                InlineKeyboardButton("❌ Cancel",  callback_data="deads")
            ]]),
            parse_mode="Markdown"
        )
        return

    if data.startswith("dcfm|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)

        blocked_text, blocked_kbd = get_blocked_message(balance, price, "deads")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return

        user_balances[uid] = round(balance - price, 2)
        save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n📁 *{label}*\n\nContact @{SUPER_ADMIN} for files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    # Scanner
    if data == "scanner":
        await query.edit_message_text("🔍 *Scanner*", reply_markup=scanner_keyboard("all", 0), parse_mode="Markdown")
        return

    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        await query.edit_message_text("🔍 *Scanner*", reply_markup=scanner_keyboard(cat, pg), parse_mode="Markdown")
        return

    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        label, category, price = SCANNER_ITEMS[idx]
        await query.edit_message_text(f"🔍 *{label}*\nPrice: *${price:.2f} / k*\nSelect quantity:", reply_markup=scanner_qty_keyboard(idx, category), parse_mode="Markdown")
        return

    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2); balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Confirmation*\n\n{label}\nQty: *{qty_k}k*\nTotal: *£{total_gbp:.2f}*\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"), InlineKeyboardButton("❌ Cancel", callback_data=f"sni|{idx}")]]) , parse_mode="Markdown")
        return

    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2); balance = user_balances.get(uid, 0)

        blocked_text, blocked_kbd = get_blocked_message(balance, total_gbp, f"sni|{idx}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return

        user_balances[uid] = round(balance - total_gbp, 2)
        save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n{label} ({qty_k}k)\n\nContact @{SUPER_ADMIN} to receive.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]), parse_mode="Markdown")
        return

    # Targeted Source
    if data == "tsource":
        await query.edit_message_text("🎯 *Targeted Source*", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")
        return

    if data == "ts_aged":
        await query.edit_message_text("‼️ *Aged / Bank-Targeted Leads*\nSelect quantity:", reply_markup=ts_qty_keyboard(AGED_LEADS_PRICING, "tsaged"), parse_mode="Markdown")
        return

    if data == "ts_crypto":
        await query.edit_message_text("🪙 *Crypto Leads*\nSelect quantity:", reply_markup=ts_qty_keyboard(CRYPTO_LEADS_PRICING, "tscrypto"), parse_mode="Markdown")
        return

    if data == "ts_services":
        await query.edit_message_text(f"🛠 *Additional Services*\n\nContact @{SUPER_ADMIN}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")], [InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

    if data.startswith("tsaged|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0); balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Confirmation*\n\nAged Leads ({qty//1000}k)\nPrice: £{price}\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tsaged_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_aged")]]), parse_mode="Markdown")
        return

    if data.startswith("tsaged_confirm|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0); balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_aged")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\nAged Leads ({qty//1000}k)\n\nContact @{SUPER_ADMIN}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

    if data.startswith("tscrypto|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0); balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Confirmation*\n\nCrypto Leads ({qty//1000}k)\nPrice: £{price}\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tscrypto_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_crypto")]]), parse_mode="Markdown")
        return

    if data.startswith("tscrypto_confirm|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0); balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_crypto")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\nCrypto Leads ({qty//1000}k)\n\nContact @{SUPER_ADMIN}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

# ── Message Handler ───────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Live Search Functionality
    if context.user_data.get("awaiting_search"):
        query_text = update.message.text.strip().lower()
        iso2, vertical = context.user_data.get("search_target", ("US", "bank"))
        context.user_data["awaiting_search"] = False

        items = context.user_data.get(f"items_{iso2}_{vertical}")
        if not items: items = await fetch_dynamic_vertical(iso2, vertical)

        filtered = [item for item in items if query_text in item["name"].lower()]

        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2
        flag = get_country_flag(iso2)

        if not filtered:
            await update.message.reply_text(f"❌ No matching items found for *\"{query_text}\"* in {c_name}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Category", callback_data=f"c_vert|{iso2}|{vertical}")]]), parse_mode="Markdown")
            return

        await update.message.reply_text(f"🔍 *Search Results for \"{query_text}\"* ({len(filtered)} found):", reply_markup=paginated_entity_keyboard(iso2, vertical, filtered, page=0), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_qty"):
        info = context.user_data.get("buy_bin", {})
        try: buy_qty = int(update.message.text.strip())
        except ValueError: await update.message.reply_text("Enter a valid number."); return
        available = info.get("available", 0)
        if buy_qty < 1 or buy_qty > available: await update.message.reply_text(f"Enter 1-{available}."); return

        context.user_data["awaiting_qty"] = False
        vid, bkey, bin_num = info["vid"], info["bkey"], info["bin_num"]
        price = info["price"]; total = round(price * buy_qty, 2); balance = user_balances.get(update.effective_user.id, 0)

        await update.message.reply_text(f"🛒 *Purchase Confirmation*\n\nBIN: *{bin_num}*\nQty: *{buy_qty}*\nTotal: *£{total:.2f}*\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"cfmqty|{vid}|{bkey}|{bin_num}|{buy_qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"vendor|{vid}")]]) , parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_custom"):
        try: amount = int(float(update.message.text.strip().replace("£","")))
        except ValueError: await update.message.reply_text("Enter a valid number."); return
        if amount < MIN_TOPUP: await update.message.reply_text(f"Minimum is £{MIN_TOPUP}."); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(f"🔶 *£{amount} Top-Up*\nSelect payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num = update.message.text.strip(); vid = context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        buttons = []
        for bkey, base in STORE.get(vid, {}).get("bases", {}).items():
            if bin_num in base["bins"]:
                buttons.append([InlineKeyboardButton(f"{base['label']} - {bin_num} ({base['bins'][bin_num]})", callback_data=f"buybin|{vid}|{bkey}|{bin_num}|0")])
        if buttons:
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
            await update.message.reply_text("🔍 Search results:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ BIN not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")


# ── Admin System ──────────────────────────────────────────────────────────────

async def cmd_adminlogin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try: password = context.args[0]
    except IndexError: await update.message.reply_text("Usage: /adminlogin <password>"); return
    if password == ADMIN_PASSWORD:
        logged_in_admins.add(uid)
        await update.message.reply_text("✅ *Admin access granted!*\nSend /adminhelp to see all commands.", parse_mode="Markdown")
        await log(context.application, f"🔑 *Admin Login*\n👤 {user_tag(update)}")
    else: await update.message.reply_text("❌ Wrong password.")

async def cmd_adminlogout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logged_in_admins.discard(update.effective_user.id)
    await update.message.reply_text("🔒 Logged out.")

ADMIN_HELP_TEXT = (
    "🛠 *Admin Commands*\n\n"
    "*Category Pricing*\n"
    "`/setprice <Category_Code> <Quantity> <Price>`\n"
    "`/resetprice <Category_Code>`\n"
    "Example: `/setprice AU 1000 25`\n\n"
    "*Balance Management*\n"
    "`/addbalance <user_id> <amount>`\n"
    "`/removebalance <user_id> <amount>`\n"
    "`/setbalance <user_id> <amount>`\n"
    "`/checkbalance <user_id>`\n\n"
    "*Leads & Stock*\n"
    "`/updatelead <CC> <subcat: crypto|bank|business|network> <ItemName> <stock>`\n"
    "`/setstock leads <number>`\n\n"
    "*Store BINS*\n"
    "`/addvendor <id> <label>` | `/removevendor <id>`\n"
    "`/addbase <vendor_id> <base_key> <price> <label>`\n"
    "`/addbin <vendor_id> <base_key> <bin> <qty>`\n"
    "`/bulkbin <vendor_id> <base_key>`\n\n"
    "*Broadcast*\n"
    "`/broadcast <message>`"
)

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode="Markdown")

async def cmd_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        cc = context.args[0].upper()
        qty = int(context.args[1])
        price = float(context.args[2])
        assert cc in LEADS
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /setprice <Category_Code> <Quantity> <Price>", parse_mode="Markdown")
        return
    if "pricing" not in LEADS[cc]: LEADS[cc]["pricing"] = dict(LEADS_PRICING)
    LEADS[cc]["pricing"][str(qty)] = price
    save_data()
    await update.message.reply_text(f"✅ Updated pricing for *{LEADS[cc]['flag']} {LEADS[cc]['name']}*:\n• *{qty:,} items* → *£{price:g}*", parse_mode="Markdown")

async def cmd_resetprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: cc = context.args[0].upper(); assert cc in LEADS
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /resetprice <Category_Code>", parse_mode="Markdown"); return
    LEADS[cc].pop("pricing", None)
    save_data()
    await update.message.reply_text(f"✅ Pricing for *{LEADS[cc]['flag']} {LEADS[cc]['name']}* reset to default.", parse_mode="Markdown")

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2)
    save_data()
    await update.message.reply_text(f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /removebalance <user_id> <amount>"); return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2)
    save_data()
    await update.message.reply_text(f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /setbalance <user_id> <amount>"); return
    user_balances[tid] = round(amt, 2)
    save_data()
    await update.message.reply_text(f"✅ Set `{tid}` balance to *£{amt:.2f}*", parse_mode="Markdown")

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /checkbalance <user_id>"); return
    await update.message.reply_text(f"User `{tid}` balance: *£{user_balances.get(tid,0):.2f}*", parse_mode="Markdown")

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: key = context.args[0].lower(); val = int(context.args[1]); assert key in ("leads","stock")
    except (IndexError, ValueError, AssertionError): await update.message.reply_text("Usage: /setstock leads <number>"); return
    live_stock[key] = val
    save_data()
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /addvendor <id> <label>"); return
    if vid in STORE: await update.message.reply_text(f"Vendor `{vid}` already exists."); return
    STORE[vid] = {"label": label, "bases": {}}
    save_data()
    await update.message.reply_text(f"✅ Added vendor *{label}*", parse_mode="Markdown")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; assert vid in STORE
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removevendor <vendor_id>"); return
    del STORE[vid]
    save_data()
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]; price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label and "|" not in bkey
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /addbase <vendor_id> <base_key> <price> <label>"); return
    existing_bins = STORE[vid]["bases"].get(bkey, {}).get("bins", {})
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": existing_bins}
    save_data()
    await update.message.reply_text(f"✅ Base *{label}* added/updated.", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removebase <vendor_id> <base_key>"); return
    del STORE[vid]["bases"][bkey]
    save_data()
    await update.message.reply_text(f"✅ Removed base `{bkey}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]; qty = int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /addbin <vendor_id> <base_key> <bin_number> <quantity>"); return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty
    save_data()
    await update.message.reply_text(f"✅ BIN *{bin_num}* = *{qty}*", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removebin <vendor_id> <base_key> <bin_number>"); return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None)
    save_data()
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /listbins <vendor_id> <base_key>"); return
    bins  = STORE[vid]["bases"][bkey]["bins"]
    label = STORE[vid]["bases"][bkey]["label"]
    if not bins: await update.message.reply_text(f"No BINs in *{label}*", parse_mode="Markdown"); return
    lines = [f"📦 *{label}* — {sum(bins.values())} total\n"]
    for b, q in sorted(bins.items()): lines.append(f"`{b}` — {q} cards")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /clearbase <vendor_id> <base_key>"); return
    STORE[vid]["bases"][bkey]["bins"].clear()
    save_data()
    await update.message.reply_text(f"✅ Cleared BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    if not user_balances: await update.message.reply_text("No users with balances."); return
    lines = ["👥 *All Users & Balances*\n"]
    for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1]):
        lines.append(f"`{uid}` — £{bal:.2f} (joined {user_join_dates.get(uid,'?')})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cc = context.args[0].upper(); subcat = context.args[1].lower(); item = context.args[2]; stock = int(context.args[3])
        assert cc in LEADS and subcat in LEADS[cc]["subcats"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /updatelead <CC> <subcat: crypto|bank|business|network> <ItemName> <stock>\nExample: `/updatelead AU network Telstra 5000000`", parse_mode="Markdown"); return
    
    if stock <= 0: LEADS[cc]["subcats"][subcat]["items"].pop(item, None)
    else: LEADS[cc]["subcats"][subcat]["items"][item] = stock
    save_data()
    await update.message.reply_text(f"✅ Updated *{item}* → *{stock:,}* in {LEADS[cc]['name']}", parse_mode="Markdown")

async def cmd_bulkbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    lines = update.message.text.split("\n"); first = lines[0].split()
    try: vid = first[1]; bkey = first[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage:\n/bulkbin <vendor_id> <base_key>\n374646 x1"); return

    added = 0
    for line in lines[1:]:
        line = line.strip().replace("x", " ").replace("X", " ")
        parts = line.split()
        if len(parts) >= 2:
            try:
                bin_num, qty = parts[0], int(parts[1])
                if qty > 0: STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; added += 1
            except ValueError: pass
    save_data()
    await update.message.reply_text(f"✅ Added {added} BINs.", parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    full_text = update.message.text or ""
    parts = full_text.split(None, 1)
    msg = parts[1] if len(parts) > 1 else ""
    if not msg: await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown"); return

    targets = set(user_join_dates.keys()) | set(user_balances.keys()) | agreed_users
    status_msg = await update.message.reply_text("📢 *Sending broadcast...*", parse_mode="Markdown")

    sent, failed = 0, 0
    for target_uid in targets:
        try:
            await context.application.bot.send_message(chat_id=target_uid, text=msg, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(f"📢 *Broadcast Complete*\n\n✅ Sent: *{sent}*\n❌ Failed: {failed}", parse_mode="Markdown")

async def error_handler(update, context):
    logger.error("🔥 Error caught:", exc_info=context.error)

# ── Main Engine ───────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    load_data()

    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    get_updates_request = HTTPXRequest(connect_timeout=30.0, read_timeout=45.0, write_timeout=30.0, pool_timeout=30.0)

    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(get_updates_request).build()

    # User commands
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("balance",       cmd_balance))
    app.add_handler(CommandHandler("wallet",        cmd_wallet))
    app.add_handler(CommandHandler("targeted",      cmd_targeted))
    app.add_handler(CommandHandler("contact",       cmd_contact))
    app.add_handler(CommandHandler("support",       cmd_contact))
    app.add_handler(CommandHandler("help",          cmd_help))

    # Admin commands
    app.add_handler(CommandHandler("adminlogin",    cmd_adminlogin))
    app.add_handler(CommandHandler("adminlogout",   cmd_adminlogout))
    app.add_handler(CommandHandler("adminhelp",     cmd_adminhelp))
    app.add_handler(CommandHandler("setprice",      cmd_setprice))
    app.add_handler(CommandHandler("resetprice",    cmd_resetprice))
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
    app.add_handler(CommandHandler("updatelead",    cmd_updatelead))
    app.add_handler(CommandHandler("bulkbin",       cmd_bulkbin))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    logger.info("Bot started successfully ✅")
    app.run_polling(timeout=30, drop_pending_updates=False)

if __name__ == "__main__":
    main()
