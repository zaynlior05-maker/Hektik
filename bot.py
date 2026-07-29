import os
import json
import logging
import asyncio
import aiohttp
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

# ── Store Data ────────────────────────────────────────────────────────────────
STORE = {
    "8888": {
        "label": "Vendor 8888",
        "bases": {
            "15fresh": {
                "label": "£15 Base - Fresh Lives 🇬🇧",
                "price_per_card": 15,
                "bins": {
                    "371789": 6, "374288": 1, "377383": 3, "377390": 9,
                    "379006": 1, "402396": 1, "402399": 1, "404972": 2,
                    "416549": 9, "416598": 16, "446223": 1, "446261": 7,
                    "446278": 1, "446291": 1, "449352": 2, "449353": 2,
                    "450875": 1, "454313": 6, "454638": 2, "459647": 4,
                    "459661": 2, "462010": 3, "465941": 2, "470041": 1,
                    "471626": 5, "480038": 2, "484446": 1, "486490": 3,
                    "490581": 1, "491179": 2,
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
                    "400115": 4, "401178": 2, "402601": 3, "403628": 1,
                    "410076": 5, "411929": 2, "415530": 6, "419740": 1,
                    "422773": 3, "425938": 2,
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

# ── Scanner Items ─────────────────────────────────────────────────────────────
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
    ("Carrier · UK",          "carrier",  0.75),
    ("Carrier · US",          "carrier",  0.75),
]
SCANNER_PER_PAGE = 10
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]

LEADS_PRICING = [
    (1_000,   15),  (2_000,  30),  (3_000,   45),  (4_000,  50),
    (5_000,   60),  (6_000,  65),  (7_000,   70),  (8_000,  80),
    (10_000, 100),  (15_000,125),  (20_000, 150),  (25_000,175),
    (30_000, 200),  (50_000,300),  (100_000,600),
]

# ── FULLY POPULATED DATASET STRUCTURE FOR ALL COUNTRIES ──────────────────────
# Populated with 5 dynamic verticals (banks, crypto, biz, sim, ledger).
LEADS = {
    "AU": {
        "flag": "🇦🇺", "name": "Australia",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"AMP Bank": 210000, "ANZ Bank": 1250000, "Bank of Queensland": 420000, "BankSA": 310000, "Bankwest": 380000, "Bendigo Bank": 510000, "Commonwealth Bank (CBA)": 3100000, "HSBC Australia": 290000, "ING Australia": 620000, "Macquarie Bank": 890000, "ME Bank": 180000, "National Australia Bank (NAB)": 2400000, "Suncorp Bank": 450000, "Westpac": 2800000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Binance AU": 1100000, "BTC Markets": 450000, "CoinJar": 320000, "CoinSpot": 1500000, "Coinbase": 890000, "Crypto.com": 760000, "Independent Reserve": 340000, "Kraken AU": 520000, "Swyftx": 980000}},
            "biz": {"label": "🏢 Business Registries", "items": {"ABR Registered Entities": 1400000, "ASIC Corporate Index": 2100000, "GST Registered Businesses": 1800000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Telstra": 4200000, "Optus": 3100000, "Vodafone": 1800000, "Boost Mobile": 620000, "TPG": 430000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Validator Nodes": 120000, "Ethereum Staking Index": 340000, "Solana RPC Nodes": 210000}}
        }
    },
    "UK": {
        "flag": "🇬🇧", "name": "United Kingdom",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Barclays": 4500000, "HSBC": 3800000, "Lloyds": 5100000, "NatWest": 2900000, "Santander": 3200000, "Monzo": 1800000, "Revolut UK": 2100000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Binance UK": 1800000, "Coinbase": 2100000, "Kraken": 950000, "eToro": 1200000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Companies House Data": 4200000, "HMRC VAT Entities": 2800000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"EE": 3544000, "O2": 1831000, "Sky": 553000, "Three": 4515000, "Virgin": 114000, "Vodafone": 530000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"BTC UK Nodes": 150000, "ETH Stakers UK": 220000}}
        }
    },
    "US": {
        "flag": "🇺🇸", "name": "United States",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Chase": 8500000, "Bank of America": 7200000, "Wells Fargo": 6100000, "Citi": 4900000, "Capital One": 5200000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Coinbase US": 9500000, "Kraken US": 4200000, "Gemini": 2800000, "Binance.US": 3100000, "Crypto.com": 4500000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Delaware Corps": 5400000, "Nevada LLCs": 2100000, "Wyoming Entities": 1200000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"AT&T": 12800000, "Verizon": 11400000, "T-Mobile": 9700000, "Boost Mobile": 2100000, "Cricket": 1900000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"BTC US Nodes": 850000, "ETH US Nodes": 1100000, "Solana Validators": 420000}}
        }
    },
    "CA": {
        "flag": "🇨🇦", "name": "Canada",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"RBC": 2500000, "TD Bank": 2100000, "Scotiabank": 1800000, "BMO": 1500000, "CIBC": 1200000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Wealthsimple Crypto": 950000, "Coinberry": 420000, "NDAX": 310000, "Kraken CA": 520000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Federal Corps": 1800000, "Ontario Registries": 2100000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Rogers": 4100000, "Bell": 3800000, "Telus": 3500000, "Fido": 980000, "Koodo": 760000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"BTC Nodes CA": 120000, "ETH Stakers CA": 210000}}
        }
    },
    "DE": {
        "flag": "🇩🇪", "name": "Germany",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Deutsche Bank": 3100000, "Commerzbank": 2400000, "Sparkasse": 5200000, "N26": 1800000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Bitpanda DE": 1200000, "Coinbase DE": 1800000, "Kraken DE": 850000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Handelsregister": 4500000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Telekom": 8900000, "Vodafone": 7200000, "O2": 5800000, "1&1": 1400000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"BTC DE Nodes": 320000, "ETH DE Nodes": 450000}}
        }
    },
    "FR": {
        "flag": "🇫🇷", "name": "France",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"BNP Paribas": 2800000, "Credit Agricole": 3500000, "Societe Generale": 2100000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Binance FR": 1400000, "Coinhouse": 520000}},
            "biz": {"label": "🏢 Business Registries", "items": {"INSEE SIRENE": 3800000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Orange": 6200000, "SFR": 4800000, "Bouygues": 4100000, "Free Mobile": 3500000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Tezos Nodes": 150000, "ETH FR Nodes": 280000}}
        }
    },
    "IT": {
        "flag": "🇮🇹", "name": "Italy",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Intesa Sanpaolo": 3200000, "UniCredit": 2900000, "Poste Italiane": 4100000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Young Platform": 620000, "Binance IT": 1100000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Registro Imprese": 2800000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"TIM": 5900000, "Vodafone": 4200000, "WindTre": 5100000, "Iliad": 1800000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Algorand Nodes": 110000, "BTC IT Nodes": 140000}}
        }
    },
    "ES": {
        "flag": "🇪🇸", "name": "Spain",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Santander": 3800000, "BBVA": 3100000, "CaixaBank": 4200000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Bit2Me": 850000, "Binance ES": 1200000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Registro Mercantil": 2500000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Movistar": 7200000, "Orange": 5800000, "Vodafone": 4900000, "MásMóvil": 2100000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"ETH ES Nodes": 180000, "BTC ES Nodes": 120000}}
        }
    }
}

# Add default stub data for remaining countries to ensure NO empty dicts anywhere
_ADDITIONAL_COUNTRIES = {
    "AT": ["🇦🇹", "Austria"], "BH": ["🇧🇭", "Bahrain"], "BE": ["🇧🇪", "Belgium"],
    "BR": ["🇧🇷", "Brazil"], "BG": ["🇧🇬", "Bulgaria"], "CY": ["🇨🇾", "Cyprus"],
    "CZ": ["🇨🇿", "Czech Republic"], "DK": ["🇩🇰", "Denmark"], "EE": ["🇪🇪", "Estonia"],
    "FI": ["🇫🇮", "Finland"], "GR": ["🇬🇷", "Greece"], "HU": ["🇭🇺", "Hungary"],
    "IS": ["🇮🇸", "Iceland"], "IE": ["🇮🇪", "Ireland"], "LV": ["🇱🇻", "Latvia"],
    "LT": ["🇱🇹", "Lithuania"], "MY": ["🇲🇾", "Malaysia"], "MT": ["🇲🇹", "Malta"],
    "NL": ["🇳🇱", "Netherlands"], "NZ": ["🇳🇿", "New Zealand"], "NO": ["🇳🇴", "Norway"],
    "PL": ["🇵🇱", "Poland"], "PT": ["🇵🇹", "Portugal"], "PR": ["🇵🇷", "Puerto Rico"],
    "QA": ["🇶🇦", "Qatar"], "RO": ["🇷🇴", "Romania"], "SG": ["🇸🇬", "Singapore"],
    "SK": ["🇸🇰", "Slovakia"], "SI": ["🇸🇮", "Slovenia"], "ZA": ["🇿🇦", "South Africa"],
    "SE": ["🇸🇪", "Sweden"], "CH": ["🇨🇭", "Switzerland"], "TW": ["🇹🇼", "Taiwan"],
    "TR": ["🇹🇷", "Turkey"], "AE": ["🇦🇪", "UAE"], "UA": ["🇺🇦", "Ukraine"]
}

for _cc, _info in _ADDITIONAL_COUNTRIES.items():
    if _cc not in LEADS:
        LEADS[_cc] = {
            "flag": _info[0],
            "name": _info[1],
            "verticals": {
                "banks": {"label": "🏦 Banks & Financial", "items": {"National Bank": 500000, "Commercial Bank": 350000}},
                "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Local Crypto Exchange": 250000, "Binance Regional": 450000}},
                "biz": {"label": "🏢 Business Registries", "items": {"Corp Register": 600000, "Tax Entities": 400000}},
                "sim": {"label": "📡 Mobile Networks", "items": {"Telecom 1": 1200000, "Telecom 2": 950000}},
                "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Regional Nodes": 50000, "Stakers": 35000}}
            }
        }

# ── Dynamic MIX Generator Loop (125% of highest stock per vertical) ───────────
for _cc, _d in LEADS.items():
    for _vert_key, _vert_data in _d.get("verticals", {}).items():
        _items = _vert_data.get("items", {})
        if "MIX" not in _items and _items:
            _biggest = max(_items.values())
            _items["MIX"] = int(_biggest * 1.25)

DEFAULT_LEADS = _copy.deepcopy(LEADS)
DEFAULT_STORE = None

# ── Targeted Source Pricing ───────────────────────────────────────────────────
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
        with open(DATA_FILE) as f:
            data = json.load(f)
        user_balances    = {int(k): v for k, v in data.get("user_balances", {}).items()}
        agreed_users     = set(data.get("agreed_users", []))
        user_join_dates  = {int(k): v for k, v in data.get("user_join_dates", {}).items()}
        channel_verified = set(data.get("channel_verified", []))
        live_stock.update(data.get("live_stock", {}))
        
        if data.get("STORE"):
            STORE.clear(); STORE.update(data["STORE"])
        if data.get("LEADS"):
            LEADS.clear(); LEADS.update(data["LEADS"])

        for cc, d in DEFAULT_LEADS.items():
            if cc not in LEADS:
                LEADS[cc] = _copy.deepcopy(d)
            else:
                for v_key, v_data in d.get("verticals", {}).items():
                    if v_key not in LEADS[cc]["verticals"]:
                        LEADS[cc]["verticals"][v_key] = _copy.deepcopy(v_data)
                    else:
                        for item, stock in v_data.get("items", {}).items():
                            if item not in LEADS[cc]["verticals"][v_key]["items"]:
                                LEADS[cc]["verticals"][v_key]["items"][item] = stock

        logger.info("✅ Loaded saved data from disk.")
    except Exception as e:
        logger.error(f"load_data failed: {e}")

async def log(app, text: str):
    if not LOG_CHANNEL_ID: return
    try: await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception: pass

def is_admin(update) -> bool:
    uid = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

async def check_channel_membership(bot, user_id):
    if not JOIN_CHANNEL: return True, "ok"
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"): return True, "ok"
        return False, "not_joined"
    except Exception: return False, "error"

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
    except Exception: return None

def scanner_items_for_cat(cat):
    if cat == "all": return list(enumerate(SCANNER_ITEMS))
    return [(i, item) for i, item in enumerate(SCANNER_ITEMS) if item[1] == cat]

def scanner_keyboard(cat="all", page=0):
    SCAN_CATS = {"all": "All •", "socials": "Socials", "crypto": "Crypto", "shopping": "Shop...", "carrier": "Carrier"}
    items = scanner_items_for_cat(cat)
    total_pages = max(1, (len(items) + SCANNER_PER_PAGE - 1) // SCANNER_PER_PAGE)
    page_items = items[page * SCANNER_PER_PAGE : (page + 1) * SCANNER_PER_PAGE]

    rows = []
    tab_row = []
    for key, label in SCAN_CATS.items():
        display = f"› {label}" if key == cat else label
        tab_row.append(InlineKeyboardButton(display, callback_data=f"scan|{key}|0"))
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
        row = []
        for qty_k in SCANNER_QTYS[i:i+2]:
            total = qty_k * price
            row.append(InlineKeyboardButton(f"{qty_k}k — £{total:.2f}", callback_data=f"snq|{idx}|{qty_k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"scan|{cat}|{page}")])
    return InlineKeyboardMarkup(rows)

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

def leads_pricing_text():
    lines = ["📊 *Pricing*"]
    for qty, price in LEADS_PRICING:
        lines.append(f"{qty//1000}k — £{price}")
    return "\n".join(lines)

def country_keyboard():
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        row = [InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"lc|{cc}") for cc, d in countries[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def verticals_keyboard(cc):
    rows = [
        [InlineKeyboardButton("🪙 Crypto Exchanges", callback_data=f"lvert|{cc}|crypto")],
        [InlineKeyboardButton("🏦 Banks & Financial", callback_data=f"lvert|{cc}|banks")],
        [InlineKeyboardButton("🏢 Business Registries", callback_data=f"lvert|{cc}|biz")],
        [InlineKeyboardButton("📡 Mobile Networks", callback_data=f"lvert|{cc}|sim")],
        [InlineKeyboardButton("🔗 Ledgers & Nodes", callback_data=f"lvert|{cc}|ledger")],
        [InlineKeyboardButton("⬅️ Back to Directory", callback_data="leads")]
    ]
    return InlineKeyboardMarkup(rows)

def dataset_item_keyboard(cc, vert_key):
    items = list(LEADS[cc]["verticals"][vert_key]["items"].items())
    rows = []
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"lk|{cc}|{vert_key}|{name}") for name, stock in items[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, vert_key, item_name):
    rows = []
    for i in range(0, len(LEADS_PRICING), 2):
        row = [InlineKeyboardButton(f"{qty//1000}k — £{price}", callback_data=f"lq|{cc}|{vert_key}|{item_name}|{qty}") for qty, price in LEADS_PRICING[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lvert|{cc}|{vert_key}")])
    return InlineKeyboardMarkup(rows)

def tsource_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("‼️ Aged / Bank-Targeted Leads", callback_data="ts_aged")],
        [InlineKeyboardButton("🪙 Crypto Leads", callback_data="ts_crypto")],
        [InlineKeyboardButton("🛠 Additional Services", callback_data="ts_services")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")],
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

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads", callback_data="leads"), InlineKeyboardButton("🛍️ Store", callback_data="store")],
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("🔍 Scanner", callback_data="scanner")],
        [InlineKeyboardButton("🎯 Targeted Source", callback_data="tsource")],
    ])

def main_menu_text():
    dynamic_stock = calculate_dynamic_stock()
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Stock*\n"
        f"🌍 Leads: *{live_stock['leads']:,}*\n"
        f"🛍️ Stock: *{dynamic_stock}*\n\n"
        "_Choose a section below:_"
    )

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
        if len(row) == 2:
            rows.append(row); row = []
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
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def base_select_keyboard(vid):
    rows = [[InlineKeyboardButton(b["label"], callback_data=f"base|{vid}|{bk}")] for bk, b in STORE[vid]["bases"].items()]
    rows.append([InlineKeyboardButton("🔍 BIN Search", callback_data=f"bsearch|{vid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def bin_list_keyboard(vid, bkey, page=0):
    bins = list(STORE[vid]["bases"][bkey]["bins"].items())
    total_pages = max(1, (len(bins) + BINS_PER_PAGE - 1) // BINS_PER_PAGE)
    page_bins = bins[page * BINS_PER_PAGE : (page + 1) * BINS_PER_PAGE]
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

# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)
    if is_new:
        await log(context.application, f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if uid in agreed_users and uid in channel_verified:
        await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel to Continue", url=JOIN_CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Let Me In", callback_data="agree_rules")],
    ])
    await update.message.reply_text(RULES_TEXT, reply_markup=keyboard, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    await update.message.reply_text(f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*\n\n_Top up via the Wallet section._", parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

async def cmd_targeted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎯 *Targeted Source*\n\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")

SUPPORT_USER = os.environ.get("SUPPORT_USERNAME", "HekTikz")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 *Contact / Support*\n\nFor top-ups, orders, refunds or any help, message the admin directly:\n\n"
        f"👤 Admin: @{SUPER_ADMIN}\n🔹 Support 24/7: @{SUPPORT_USER}\n\n_Tap a button below to open a chat._",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👤 Message Admin", url=f"https://t.me/{SUPER_ADMIN}")],
            [InlineKeyboardButton(f"🔹 Message Support", url=f"https://t.me/{SUPPORT_USER}")],
        ]),
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How to use this bot*\n\n1️⃣ Top up your balance — /wallet\n2️⃣ Browse sections from /start:\n"
        "3️⃣ Pick an item and confirm\n4️⃣ After buying, contact admin\n\n*Commands:*\n/start\n/wallet\n/balance\n/targeted\n/contact",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")]]),
        parse_mode="Markdown"
    )

async def cmd_adminlogin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try: password = context.args[0]
    except IndexError: await update.message.reply_text("Usage: /adminlogin <password>"); return
    if password == ADMIN_PASSWORD:
        logged_in_admins.add(uid)
        await update.message.reply_text("✅ *Admin access granted!*\nSend /adminhelp to see all commands.", parse_mode="Markdown")
        await log(context.application, f"🔑 *Admin Login*\n👤 {user_tag(update)}\n🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    else:
        await update.message.reply_text("❌ Wrong password.")
        await log(context.application, f"⚠️ *Failed Admin Login*\n👤 {user_tag(update)}")

async def cmd_adminlogout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logged_in_admins.discard(update.effective_user.id)
    await update.message.reply_text("🔒 Logged out of admin access.")

ADMIN_HELP_TEXT = (
    "🛠 *Admin Commands*\n\n"
    "`/adminlogin <password>` | `/adminlogout`\n"
    "`/addbalance <uid> <amt>` | `/removebalance <uid> <amt>`\n"
    "`/setbalance <uid> <amt>` | `/checkbalance <uid>`\n"
    "`/setstock leads <number>`\n"
    "`/addvendor <id> <label>` | `/removevendor <id>`\n"
    "`/addbase <vid> <bkey> <price> <label>` | `/removebase <vid> <bkey>`\n"
    "`/addbin <vid> <bkey> <bin> <qty>` | `/removebin <vid> <bkey> <bin>`\n"
    "`/listbins <vid> <bkey>` | `/clearbase <vid> <bkey>`\n"
    "`/listusers` | `/broadcast <message>`\n"
    "`/updatelead <CC> <VerticalKey> <ItemName> <Stock>`\n"
    "`/bulkbin <vid> <bkey>`"
)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]])

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode="Markdown")

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except: await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2); save_data()
    await update.message.reply_text(f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except: await update.message.reply_text("Usage: /removebalance <user_id> <amount>"); return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2); save_data()
    await update.message.reply_text(f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except: await update.message.reply_text("Usage: /setbalance <user_id> <amount>"); return
    user_balances[tid] = round(amt, 2); save_data()
    await update.message.reply_text(f"✅ Set `{tid}` balance to *£{amt:.2f}*", parse_mode="Markdown")

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0])
    except: await update.message.reply_text("Usage: /checkbalance <user_id>"); return
    await update.message.reply_text(f"User `{tid}` balance: *£{user_balances.get(tid,0):.2f}*", parse_mode="Markdown")

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: key = context.args[0].lower(); val = int(context.args[1]); assert key in ("leads","stock")
    except: await update.message.reply_text("Usage: /setstock leads <number>"); return
    live_stock[key] = val; save_data()
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except: await update.message.reply_text("Usage: /addvendor <id> <label>"); return
    if vid in STORE: await update.message.reply_text(f"Vendor `{vid}` already exists."); return
    STORE[vid] = {"label": label, "bases": {}}; save_data()
    await update.message.reply_text(f"✅ Added vendor *{label}*", parse_mode="Markdown")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; assert vid in STORE
    except: await update.message.reply_text("Usage: /removevendor <vendor_id>"); return
    del STORE[vid]; save_data()
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]
        price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label and "|" not in bkey
    except:
        await update.message.reply_text("Usage: /addbase <vendor_id> <base_key> <price> <label>"); return
    existing_bins = {}
    if bkey in STORE[vid]["bases"]: existing_bins = STORE[vid]["bases"][bkey].get("bins", {})
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": existing_bins}; save_data()
    await update.message.reply_text(f"✅ Base *{label}* added/updated at £{price}/card.", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: await update.message.reply_text("Usage: /removebase <vendor_id> <base_key>"); return
    del STORE[vid]["bases"][bkey]; save_data()
    await update.message.reply_text(f"✅ Removed base `{bkey}` from vendor `{vid}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]; qty = int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /addbin <vid> <bkey> <bin> <qty>"); return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; save_data()
    await update.message.reply_text(f"✅ BIN *{bin_num}* = *{qty}* in `{vid}` / `{bkey}`", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: await update.message.reply_text("Usage: /removebin <vid> <bkey> <bin>"); return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None); save_data()
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: await update.message.reply_text("Usage: /listbins <vid> <bkey>"); return
    bins = STORE[vid]["bases"][bkey]["bins"]; label = STORE[vid]["bases"][bkey]["label"]
    if not bins: await update.message.reply_text(f"No BINs in *{label}*", parse_mode="Markdown"); return
    lines = [f"📦 *{label}* — {sum(bins.values())} total\n"]
    for b, q in sorted(bins.items()): lines.append(f"`{b}` — {q} cards")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: await update.message.reply_text("Usage: /clearbase <vid> <bkey>"); return
    STORE[vid]["bases"][bkey]["bins"].clear(); save_data()
    await update.message.reply_text(f"✅ Cleared all BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not user_balances: await update.message.reply_text("No users with balances yet."); return
    lines = ["👥 *All Users & Balances*\n"]
    for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1]):
        lines.append(f"`{uid}` — £{bal:.2f} (joined {user_join_dates.get(uid,'?')})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    full_text = update.message.text or ""
    parts = full_text.split(None, 1)
    msg = parts[1] if len(parts) > 1 else ""
    if not msg: await update.message.reply_text("Please provide a message."); return
    targets = set(user_join_dates.keys()) | set(user_balances.keys()) | agreed_users
    total_users = len(targets)
    status_msg = await update.message.reply_text("📢 *Sending to all users...*\n\nPlease wait.", parse_mode="Markdown")
    sent, failed = 0, 0
    for target_uid in targets:
        try:
            await context.application.bot.send_message(chat_id=target_uid, text=msg, parse_mode="Markdown")
            sent += 1
        except: failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"📢 *Broadcast Complete*\n\n✅ Sent: *{sent}*\n❌ Failed: {failed}\nTotal: *{total_users}* users", parse_mode="Markdown")

def get_blocked_message(balance, item_price, back_cb):
    if balance == 0:
        return ("❌ *Insufficient Balance!*\n\n"
                f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\nPlease top up your wallet first.",
                InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top Up Wallet", callback_data="wallet")]]))
    if balance < MIN_DEPOSIT_REQUIRED:
        return ("🛑 *Order Blocked*\n⚠️ *Transaction Incomplete*\n"
                "Your account balance does not meet the minimum deposit required for new users.\n"
                f" • 💰 *Current Balance:* £{balance:.2f}\n"
                f" • 📋 *Required Minimum:* £{MIN_DEPOSIT_REQUIRED:.2f}\n"
                "Please fund your account to proceed.",
                InlineKeyboardMarkup([[InlineKeyboardButton("➕ Top Up", callback_data="wallet")],
                                      [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)],
                                      [InlineKeyboardButton("🌍 Menu", callback_data="back")]]))
    if balance < item_price:
        return ("❌ *Insufficient Balance!*\n\n"
                f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\nPlease top up your wallet first.",
                InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                                      InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]]))
    return None, None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data

    if data == "agree_rules":
        try: is_member, reason = await check_channel_membership(context.bot, uid)
        except: is_member, reason = False, "error"
        if reason == "error":
            await query.edit_message_text("⚠️ Could not verify membership. Try again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Retry", callback_data="agree_rules")]]))
            return
        if not is_member:
            await query.edit_message_text("⛔️ You haven't joined yet! Tap 'Join Channel to Continue' first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=JOIN_CHANNEL_URL)], [InlineKeyboardButton("✅ I've Joined", callback_data="agree_rules")]]))
            return
        agreed_users.add(uid)
        channel_verified.add(uid)
        save_data()
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty"):
        context.user_data.pop(_k, None)

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "admin_menu":
        if not is_admin(update): return
        await query.edit_message_text(ADMIN_HELP_TEXT, parse_mode="Markdown")
        return

    if data == "wallet":
        await query.edit_message_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("amt|"):
        amount = data.split("|")[1]
        await query.edit_message_text(f"🔶 *£{amount} Top-Up*\n\nChoose your payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text("💰 *Custom Amount*\n\nType the £ amount (minimum £70):\nExample: `150`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]), parse_mode="Markdown")
        return

    if data.startswith("pay|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        address = WALLETS.get(coin, "Address not configured")
        await query.edit_message_text("⏳ Fetching live price...")
        prices = await get_crypto_prices()
        if prices and coin in prices:
            crypto_amt = round(amount / prices[coin], 6)
            price_line = f"Send *Exactly* `{crypto_amt}` {coin} to get *£{amount}* credit"
        else:
            price_line = f"Send the equivalent of *£{amount}* in {coin}"
        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n"
            f"‼️ Deposits are permanent and *non refundable*\n‼️ Double check the {coin} amount *before* sending\n"
            f"💠 Funded when transaction is confirmed\n\n_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID after sending_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]), parse_mode="Markdown")
        return

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
        total_qty = sum(base["bins"].values())
        kbd, total_pages = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n🗂 *Available:* {total_qty}\n\nSelect BIN group:\n_Page 1 of {total_pages}_", reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bpage|"):
        _, vid, bkey, page = data.split("|", 3); page = int(page)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n🗂 *Available:* {sum(base['bins'].values())}\n\nSelect BIN group:\n_Page {page+1} of {total_pages}_", reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid; context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(f"🔍 *BIN Search — {STORE[vid]['label']}*\n\nType the BIN number:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")
        return

    if data.startswith("buybin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        if qty == 0: return
        price = base["price_per_card"]
        context.user_data["buy_bin"] = {"vid": vid, "bkey": bkey, "bin_num": bin_num, "page": page, "price": price, "available": qty}
        context.user_data["awaiting_qty"] = True
        await query.edit_message_text(f"👤 *Vendor:* {STORE[vid]['label']}\n📦 *Base:* {base['label']}\n💳 *BIN:* {bin_num}\n🗂 *Available:* {qty} fullz\n\n💷 *Price:* £{price:.2f} per fullz\n\nEnter quantity (1-{qty}):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"bpage|{vid}|{bkey}|{page}")]]), parse_mode="Markdown")
        return

    if data.startswith("cfmqty|"):
        _, vid, bkey, bin_num, qty_s = data.split("|", 4)
        buy_qty = int(qty_s); base = STORE[vid]["bases"][bkey]; stock = base["bins"].get(bin_num, 0); price = base["price_per_card"]
        total = round(price * buy_qty, 2); balance = user_balances.get(uid, 0)
        if buy_qty > stock: return
        blocked_text, blocked_kbd = get_blocked_message(balance, total, f"vendor|{vid}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total, 2)
        base["bins"][bin_num] = stock - buy_qty
        if base["bins"][bin_num] <= 0: del base["bins"][bin_num]
        save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n💳 BIN: *{bin_num}*\n🗂 Qty: *{buy_qty} fullz*\n💷 Paid: *£{total:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    if data == "deads":
        await query.edit_message_text("💀 *Deads — Unspoofed Files*\n\n*Specific:*\n• 50+ Specific BIN, Gender & DOB — £225\n• 100+ Specific BIN, Gender & DOB — £350\n\n*Random:*\n• 50+ File — £100\n• 100+ File — £150\n• 500 File — £500\n• 1k File — £700\n• 2k File — £1,200", reply_markup=deads_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("dbuy|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"dcfm|{key}"), InlineKeyboardButton("❌ Cancel", callback_data="deads")]]), parse_mode="Markdown")
        return

    if data.startswith("dcfm|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "deads")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n📁 *{label}*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    if data == "leads":
        pricing = leads_pricing_text()
        await query.edit_message_text(f"🌍 *Leads*\n\n{pricing}\n\n_Select a country below:_.", reply_markup=country_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("lc|"):
        cc = data.split("|")[1]
        if cc not in LEADS: return
        d = LEADS[cc]
        total = sum(sum(v["items"].values()) for v in d.get("verticals", {}).values())
        await query.edit_message_text(f"*Country:* {d['flag']} {d['name']}\n*Stock:* {total:,} total records\n\nSelect a category hub:", reply_markup=verticals_keyboard(cc), parse_mode="Markdown")
        return

    if data.startswith("lvert|"):
        _, cc, vert_key = data.split("|", 2)
        if cc not in LEADS or vert_key not in LEADS[cc]["verticals"]: return
        d = LEADS[cc]
        vert_data = d["verticals"][vert_key]
        total = sum(vert_data["items"].values())
        await query.edit_message_text(f"*Country:* {d['flag']} {d['name']}\n*Category:* {vert_data['label']}\n*Available:* {total:,} records\n\nSelect a dataset item:", reply_markup=dataset_item_keyboard(cc, vert_key), parse_mode="Markdown")
        return

    if data.startswith("lk|"):
        _, cc, vert_key, item_name = data.split("|", 3)
        if cc not in LEADS: return
        stock = LEADS[cc]["verticals"][vert_key]["items"].get(item_name, 0)
        d = LEADS[cc]
        await query.edit_message_text(f"*Country:* {d['flag']} {d['name']}\n*Dataset:* {item_name}\n*Available:* {stock:,} records\n\nSelect quantity:", reply_markup=qty_keyboard(cc, vert_key, item_name), parse_mode="Markdown")
        return

    if data.startswith("lq|"):
        _, cc, vert_key, item_name, qty_str = data.split("|", 4)
        qty = int(qty_str); price = dict(LEADS_PRICING).get(qty, 0); d = LEADS[cc]
        stock = d["verticals"][vert_key]["items"].get(item_name, 0); balance = user_balances.get(uid, 0)
        if stock < qty: return
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🌍 *Country:* {d['flag']} {d['name']}\n📡 *Dataset:* {item_name}\n🗂 *Quantity:* {qty:,} records\n💷 *Price: £{price}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{vert_key}|{item_name}|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"lk|{cc}|{vert_key}|{item_name}")]]), parse_mode="Markdown")
        return

    if data.startswith("lb|"):
        _, cc, vert_key, item_name, qty_str = data.split("|", 4)
        qty = int(qty_str); price = dict(LEADS_PRICING).get(qty, 0); balance = user_balances.get(uid, 0); d = LEADS[cc]
        blocked_text, blocked_kbd = get_blocked_message(balance, price, f"lk|{cc}|{vert_key}|{item_name}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        d["verticals"][vert_key]["items"][item_name] = max(0, d["verticals"][vert_key]["items"][item_name] - qty)
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🌍 *{d['flag']} {d['name']}* — {item_name}\n🗂 *{qty:,} records*\n💷 Paid: *£{price}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your data.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]), parse_mode="Markdown")
        return

    if data == "scanner":
        await query.edit_message_text("🔍 *Scanner*\n\n👆 Select a scanner to verify your data.", reply_markup=scanner_keyboard("all", 0), parse_mode="Markdown")
        return

    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        await query.edit_message_text("🔍 *Scanner*\n\n👆 Select a scanner to verify your data.", reply_markup=scanner_keyboard(cat, pg), parse_mode="Markdown")
        return

    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🔍 *{label}*\n\n💰 Price: *${price:.2f} / k*\nYour balance: *£{balance:.2f}*\n\nSelect quantity:", reply_markup=scanner_qty_keyboard(idx, category), parse_mode="Markdown")
        return

    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]; total_gbp = round(qty_k * price, 2); balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🔍 *{label}*\n🗂 Quantity: *{qty_k}k*\n💷 *Total: £{total_gbp:.2f}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"), InlineKeyboardButton("❌ Cancel", callback_data=f"sni|{idx}")]]), parse_mode="Markdown")
        return

    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]; total_gbp = round(qty_k * price, 2); balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, total_gbp, f"sni|{idx}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total_gbp, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🔍 *{label}*\n🗂 *{qty_k}k records*\n💷 Paid: *£{total_gbp:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your data.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]), parse_mode="Markdown")
        return

    if data == "tsource":
        await query.edit_message_text("🎯 *Targeted Source*\n\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")
        return

    if data == "ts_aged":
        await query.edit_message_text("‼️ *Aged Leads / Bank-Targeted Leads*\n\n• Fresh leads added daily\n• Targeted bank leads available\n\n💰 *Pricing:*\n• 1k — £70\n• 5k — £300\n• 10k — £500\n• 25k — £1.1k\n\n_Select a quantity to purchase:_", reply_markup=ts_qty_keyboard(AGED_LEADS_PRICING, "tsaged"), parse_mode="Markdown")
        return

    if data == "ts_crypto":
        await query.edit_message_text("🪙 *Crypto Leads*\n\n*Available Platforms:*\n• KuCoin | Binance | CoinSpot | Crypto.com\n\n💰 *Pricing:*\n• 1k — £200\n• 5k — £800\n• 10k — £1.5k\n• 25k — £2.5k\n\n_Select a quantity to purchase:_", reply_markup=ts_qty_keyboard(CRYPTO_LEADS_PRICING, "tscrypto"), parse_mode="Markdown")
        return

    if data == "ts_services":
        await query.edit_message_text(f"🛠 *Additional Services*\n\n💬 *Sender Services:*\n• Book your SMS send-out\n\n📩 PM Admin @{SUPER_ADMIN} to discuss requirements.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}"), InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

    if data.startswith("tsaged|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0); k = qty // 1000; label = f"£{price//1000}k" if price >= 1000 else f"£{price}"; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n‼️ *Aged / Bank-Targeted Leads*\n🗂 Quantity: *{k}k leads*\n💷 *Total: {label}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tsaged_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_aged")]]), parse_mode="Markdown")
        return

    if data.startswith("tsaged_confirm|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0); k = qty // 1000; balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_aged")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n‼️ *Aged / Bank-Targeted Leads*\n🗂 *{k}k leads*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

    if data.startswith("tscrypto|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0); k = qty // 1000; label = f"£{price//1000}k" if price >= 1000 else f"£{price}"; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🪙 *Crypto Leads*\n🗂 Quantity: *{k}k leads*\n💷 *Total: {label}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tscrypto_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_crypto")]]), parse_mode="Markdown")
        return

    if data.startswith("tscrypto_confirm|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0); k = qty // 1000; balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_crypto")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🪙 *Crypto Leads*\n🗂 *{k}k leads*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_qty"):
        info = context.user_data.get("buy_bin", {})
        text = update.message.text.strip()
        try: buy_qty = int(text)
        except ValueError: await update.message.reply_text("Please enter a valid number."); return
        available = info.get("available", 0)
        if buy_qty < 1 or buy_qty > available: await update.message.reply_text(f"Please enter a number between 1 and {available}."); return
        context.user_data["awaiting_qty"] = False
        vid, bkey, bin_num = info["vid"], info["bkey"], info["bin_num"]; price = info["price"]
        total = round(price * buy_qty, 2); balance = user_balances.get(update.effective_user.id, 0)
        await update.message.reply_text(f"🛒 *Purchase Confirmation*\n\n💳 BIN: *{bin_num}*\n🗂 Quantity: *{buy_qty} fullz*\n💰 Per fullz: *£{price:.2f}*\n💷 *Total: £{total:.2f}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"cfmqty|{vid}|{bkey}|{bin_num}|{buy_qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_custom"):
        text = update.message.text.strip().replace("£","")
        try:
            amount = int(float(text))
            if amount < MIN_TOPUP: await update.message.reply_text(f"Minimum is £{MIN_TOPUP}."); return
        except ValueError: await update.message.reply_text("Enter a number e.g. 150"); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(f"🔶 *£{amount} Top-Up*\n\nChoose payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num = update.message.text.strip()
        vid = context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        buttons = []
        for bkey, base in STORE.get(vid, {}).get("bases", {}).items():
            qty = base["bins"].get(bin_num)
            if qty: buttons.append([InlineKeyboardButton(f"{base['label']} - {bin_num} ({qty})", callback_data=f"buybin|{vid}|{bkey}|{bin_num}|0")])
        if buttons:
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
            await update.message.reply_text(f"👤 *Vendor:* {STORE[vid]['label']}\n\n🔍 *Search results for {bin_num}:*\n\nTap a result below to purchase:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ BIN *{bin_num}* not found in {STORE.get(vid,{}).get('label','this vendor')}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /updatelead <CC> <VerticalKey> <ItemName> <Stock>"""
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cc = context.args[0].upper()
        vert_key = context.args[1].lower()
        stock = int(context.args[-1])
        item_name = " ".join(context.args[2:-1])
        assert cc in LEADS and vert_key in LEADS[cc]["verticals"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /updatelead <CC> <VerticalKey> <ItemName> <Stock>\nExample: /updatelead AU banks Westpac 3000000"); return
    
    if stock <= 0:
        LEADS[cc]["verticals"][vert_key]["items"].pop(item_name, None)
        save_data()
        await update.message.reply_text(f"✅ Removed *{item_name}* from {LEADS[cc]['flag']} {LEADS[cc]['name']} ({vert_key})", parse_mode="Markdown")
    else:
        LEADS[cc]["verticals"][vert_key]["items"][item_name] = stock
        save_data()
        await update.message.reply_text(f"✅ Updated *{item_name}* → *{stock:,}* in {LEADS[cc]['flag']} {LEADS[cc]['name']} ({vert_key})", parse_mode="Markdown")

async def cmd_bulkbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    lines = update.message.text.split("\n")
    first = lines[0].split()
    try: vid = first[1]; bkey = first[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: await update.message.reply_text("Usage: /bulkbin <vid> <bkey>\n374646 x1"); return
    added, skipped = 0, 0
    for line in lines[1:]:
        line = line.strip()
        if not line: continue
        parts = line.replace("x", " ").replace("X", " ").split()
        if len(parts) < 2: skipped += 1; continue
        try:
            bin_num = parts[0]; qty = int(parts[1])
            if qty <= 0: skipped += 1; continue
            STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; added += 1
        except ValueError: skipped += 1
    total = sum(STORE[vid]["bases"][bkey]["bins"].values()); save_data()
    await update.message.reply_text(f"✅ *Bulk Add Complete*\n\nVendor: `{vid}` / `{bkey}`\nAdded/updated: *{added}* BINs\nSkipped: *{skipped}* lines\nTotal stock now: *{total}* fullz", parse_mode="Markdown")

async def error_handler(update, context):
    logger.error("🔥 Unhandled exception:", exc_info=context.error)

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    load_data()
    
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    get_updates_request = HTTPXRequest(connect_timeout=30.0, read_timeout=45.0, write_timeout=30.0, pool_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(get_updates_request).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("targeted", cmd_targeted))
    app.add_handler(CommandHandler("contact", cmd_contact))
    app.add_handler(CommandHandler("support", cmd_contact))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("adminlogin", cmd_adminlogin))
    app.add_handler(CommandHandler("adminlogout", cmd_adminlogout))
    app.add_handler(CommandHandler("adminhelp", cmd_adminhelp))
    app.add_handler(CommandHandler("addbalance", cmd_addbalance))
    app.add_handler(CommandHandler("removebalance", cmd_removebalance))
    app.add_handler(CommandHandler("setbalance", cmd_setbalance))
    app.add_handler(CommandHandler("checkbalance", cmd_checkbalance))
    app.add_handler(CommandHandler("setstock", cmd_setstock))
    app.add_handler(CommandHandler("addvendor", cmd_addvendor))
    app.add_handler(CommandHandler("removevendor", cmd_removevendor))
    app.add_handler(CommandHandler("addbase", cmd_addbase))
    app.add_handler(CommandHandler("removebase", cmd_removebase))
    app.add_handler(CommandHandler("addbin", cmd_addbin))
    app.add_handler(CommandHandler("removebin", cmd_removebin))
    app.add_handler(CommandHandler("listbins", cmd_listbins))
    app.add_handler(CommandHandler("clearbase", cmd_clearbase))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("updatelead", cmd_updatelead))
    app.add_handler(CommandHandler("bulkbin", cmd_bulkbin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)
    
    logger.info("Bot started ✅")
    app.run_polling(timeout=30, drop_pending_updates=False)

if __name__ == "__main__":
    import time
    while True:
        try: main(); break
        except Exception:
            logger.exception("Fatal error — restarting bot in 5s")
            time.sleep(5)
