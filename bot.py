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
DATA_DIR  = os.environ.get("DATA_DIR", ".")
DATA_FILE = os.path.join(DATA_DIR, "botdata.json")

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN            = os.environ.get("BOT_TOKEN")
SUPER_ADMIN          = os.environ.get("ADMIN_USERNAME", "HekTikz")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "changeme123")
LOG_CHANNEL_ID       = os.environ.get("LOG_CHANNEL_ID")
MIN_TOPUP            = 70
MIN_DEPOSIT_REQUIRED = float(os.environ.get("MIN_DEPOSIT_REQUIRED", 150.00))

_raw = os.environ.get("JOIN_CHANNEL", "")
JOIN_CHANNEL     = _raw if _raw else None
JOIN_CHANNEL_URL = os.environ.get("JOIN_CHANNEL_URL", "https://t.me/+yourchannelinvitelink")

WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── Storage & Caching ─────────────────────────────────────────────────────────
user_balances    = {}
agreed_users     = set()
user_join_dates  = {}
logged_in_admins = set()
channel_verified = set()

live_stock       = {"leads": 63_629_085} # Legacy fallback, heavily bypassed by dynamic calculation
TOPUP_AMOUNTS    = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]
BINS_PER_PAGE    = 20

# Cached Totals (to prevent bot lag and eliminate nested sum() loops in callbacks)
CACHE_TOTAL_LEADS    = 0
CACHE_COUNTRY_TOTALS = {}
CACHE_VERT_TOTALS    = {}

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
    ("Binance · Email",       "crypto",   3.00), ("Binance · Filter",      "crypto",   1.50),
    ("CoinW · Email",         "crypto",   1.50), ("CoinW · Mobile",        "crypto",   1.50),
    ("HTX · Email",           "crypto",   1.50), ("HTX · Mobile",          "crypto",   1.50),
    ("KuCoin · Email",        "crypto",   1.50), ("KuCoin · Mobile",       "crypto",   1.00),
    ("OKX · Filter",          "crypto",   3.00), ("Robinhood · Check",     "crypto",   2.50),
    ("Facebook · Email",      "socials",  1.00), ("Instagram · Mobile",    "socials",  1.00),
    ("LinkedIn · Profile",    "socials",  15.00),("Signal",                "socials",  1.00),
    ("Snapchat",              "socials",  2.00), ("iMessage · Filter",     "socials",  0.35),
    ("DHL",                   "shopping", 1.50), ("Shein",                 "shopping", 15.00),
    ("Carrier · Any",         "carrier",  1.50), ("Carrier · UK",          "carrier",  0.75),
    ("Carrier · US",          "carrier",  0.75), ("Carrier · Germany",     "carrier",  0.75),
]
SCANNER_PER_PAGE = 10
SCANNER_QTYS     = [1, 5, 10, 25, 50, 100]

LEADS_PRICING = [
    (1_000, 15), (2_000, 30), (3_000, 45), (4_000, 50), (5_000, 60), (6_000, 65), 
    (7_000, 70), (8_000, 80), (10_000, 100), (15_000, 125), (20_000, 150), (25_000, 175),
    (30_000, 200), (50_000, 300), (100_000, 600),
]

# ── Dynamic Data Generation for LEADS ─────────────────────────────────────────
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
            "banks": {"label": "🏦 Banks & Financial", "items": {"Barclays": 4500000, "HSBC UK": 4100000, "Lloyds Bank": 5200000, "Monzo": 3100000, "NatWest": 3800000, "Revolut": 2900000, "Royal Bank of Scotland": 1800000, "Santander UK": 3400000, "Starling Bank": 1500000, "Virgin Money": 1200000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Binance UK": 3500000, "Coinbase Pro": 2800000, "Kraken UK": 1900000, "Gemini": 1200000, "KuCoin": 1500000, "Bitstamp": 850000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Companies House Direct": 6200000, "UK Corporate Officer Index": 4100000, "VAT Registered Businesses": 3500000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"EE": 3544000, "O2": 1831000, "Sky": 553000, "Three": 4515000, "Virgin": 114000, "Vodafone": 530000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Full Nodes": 320000, "Ethereum Validator Index": 510000, "XRP Ledger Nodes": 180000}}
        }
    },
    "US": {
        "flag": "🇺🇸", "name": "United States",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Bank of America": 12500000, "Capital One": 8100000, "Chase": 15200000, "Citigroup": 7500000, "PNC Bank": 4200000, "TD Bank": 5100000, "Truist": 3800000, "US Bank": 4900000, "Wells Fargo": 11200000, "Discover": 6500000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Coinbase": 14500000, "Binance.US": 4200000, "Kraken": 5800000, "Gemini": 3500000, "Crypto.com": 4800000, "Robinhood Crypto": 8900000, "KuCoin": 2100000}},
            "biz": {"label": "🏢 Business Registries", "items": {"SEC EDGAR Database": 18500000, "State Secretary Corporations Index": 22000000, "Delaware Corporate Directory": 4500000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"AT&T": 12800000, "Verizon": 11400000, "T-Mobile": 9700000, "Boost Mobile": 2100000, "Cricket": 1900000, "Metro by T-Mobile": 1700000, "US Cellular": 890000, "Mint Mobile": 640000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Full Nodes": 950000, "Ethereum Validator Index": 1850000, "Solana RPC Nodes": 650000, "Cardano Stake Pools": 320000}}
        }
    },
    "CA": {
        "flag": "🇨🇦", "name": "Canada",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"RBC Royal Bank": 4100000, "TD Bank": 3800000, "Scotiabank": 3100000, "BMO": 2700000, "CIBC": 2500000, "Tangerine": 1200000, "National Bank": 950000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Wealthsimple Crypto": 2100000, "Bitbuy": 850000, "Coinberry": 620000, "Kraken CA": 940000, "Coinbase": 1500000, "NDAX": 410000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Corporations Canada": 3100000, "CRA Business Numbers": 4200000, "Provincial Registries": 2800000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Rogers": 4100000, "Bell": 3800000, "Telus": 3500000, "Fido": 980000, "Koodo": 760000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Nodes CA": 210000, "ETH Staking Pools": 390000, "Solana Nodes": 115000}}
        }
    },
    "FR": {
        "flag": "🇫🇷", "name": "France",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"BNP Paribas": 4200000, "Credit Agricole": 3900000, "Societe Generale": 3100000, "BPCE": 2800000, "Boursorama": 2100000, "Credit Mutuel": 1900000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Coinhouse": 1200000, "Binance FR": 2900000, "Kraken": 1500000, "Paymium": 450000, "SwissBorg": 820000}},
            "biz": {"label": "🏢 Business Registries", "items": {"SIRENE Database": 5100000, "Infogreffe": 3200000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Orange": 6200000, "SFR": 4800000, "Bouygues": 4100000, "Free Mobile": 3500000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Nodes FR": 280000, "Tezos Bakers": 120000, "ETH Validators": 410000}}
        }
    },
    "DE": {
        "flag": "🇩🇪", "name": "Germany",
        "verticals": {
            "banks": {"label": "🏦 Banks & Financial", "items": {"Deutsche Bank": 5100000, "Commerzbank": 4200000, "Sparkasse": 7800000, "Volksbank": 6500000, "N26": 3200000, "ING DiBa": 4100000}},
            "crypto": {"label": "🪙 Crypto Exchanges", "items": {"Bison App": 1800000, "Bitwala/Nuri": 950000, "Binance DE": 3500000, "Kraken": 2100000, "Coinbase": 2400000}},
            "biz": {"label": "🏢 Business Registries", "items": {"Handelsregister": 4500000, "Unternehmensregister": 5200000}},
            "sim": {"label": "📡 Mobile Networks", "items": {"Telekom": 8900000, "Vodafone": 7200000, "O2": 5800000, "1&1": 1400000}},
            "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Nodes DE": 520000, "ETH Validators DE": 680000, "Polkadot Nodes": 140000}}
        }
    }
}

_ALL_OTHER_COUNTRIES = {
    "AT": {"flag": "🇦🇹", "name": "Austria", "sims": {"A1": 1540000, "Magenta": 890000, "Drei": 760000, "Spusu": 210000}},
    "BE": {"flag": "🇧🇪", "name": "Belgium", "sims": {"Proximus": 1920000, "Orange": 1340000, "Base": 980000}},
    "BR": {"flag": "🇧🇷", "name": "Brazil", "sims": {"Vivo": 7800000, "Claro": 6500000, "TIM": 5200000, "Oi": 2100000}},
    "BH": {"flag": "🇧🇭", "name": "Bahrain", "sims": {"Batelco": 480000, "Zain": 390000, "STC": 210000, "Viva": 170000}},
    "BG": {"flag": "🇧🇬", "name": "Bulgaria", "sims": {"A1": 1100000, "Telenor": 890000, "Vivacom": 760000}},
    "CY": {"flag": "🇨🇾", "name": "Cyprus", "sims": {"Cyta": 340000, "MTN": 210000, "Epic": 180000}},
    "CZ": {"flag": "🇨🇿", "name": "Czech Republic", "sims": {"T-Mobile": 2100000, "O2": 1800000, "Vodafone": 1400000}},
    "DK": {"flag": "🇩🇰", "name": "Denmark", "sims": {"TDC": 1540000, "Telenor": 1100000, "Telia": 980000, "Tre": 760000}},
    "ET": {"flag": "🇪🇪", "name": "Estonia", "sims": {"Telia": 430000, "Elisa": 380000, "Tele2": 290000}},
    "FI": {"flag": "🇫🇮", "name": "Finland", "sims": {"Elisa": 1800000, "DNA": 1500000, "Telia": 1200000}},
    "GR": {"flag": "🇬🇷", "name": "Greece", "sims": {"Cosmote": 2800000, "Vodafone": 1900000, "Wind Hellas": 1400000, "Nova": 680000}},
    "HU": {"flag": "🇭🇺", "name": "Hungary", "sims": {"Telekom": 2100000, "Yettel": 1400000, "Vodafone": 980000}},
    "IS": {"flag": "🇮🇸", "name": "Iceland", "sims": {"Siminn": 180000, "Vodafone": 140000, "Nova": 110000}},
    "IE": {"flag": "🇮🇪", "name": "Ireland", "sims": {"Eir": 833503, "Tesco Mobile": 520700, "Three": 1213089, "Vodafone": 1720550}},
    "IT": {"flag": "🇮🇹", "name": "Italy", "sims": {"TIM": 5900000, "Vodafone": 4200000, "WindTre": 5100000, "Iliad": 1800000, "PosteMobile": 890000}},
    "LV": {"flag": "🇱🇻", "name": "Latvia", "sims": {"LMT": 540000, "Tele2": 430000, "Bite": 320000}},
    "LT": {"flag": "🇱🇹", "name": "Lithuania", "sims": {"Tele2": 890000, "Bite": 760000, "Telia": 540000}},
    "MY": {"flag": "🇲🇾", "name": "Malaysia", "sims": {"Maxis": 4200000, "Celcom": 3100000, "Digi": 3800000, "U Mobile": 1400000, "Unifi": 980000}},
    "MT": {"flag": "🇲🇹", "name": "Malta", "sims": {"GO": 180000, "Melita": 140000, "Epic": 110000}},
    "NL": {"flag": "🇳🇱", "name": "Netherlands", "sims": {"KPN": 3200000, "VodafoneZiggo": 2800000, "T-Mobile": 2100000, "Tele2": 890000}},
    "NZ": {"flag": "🇳🇿", "name": "New Zealand", "sims": {"Spark": 1800000, "One NZ": 1400000, "2degrees": 980000}},
    "NO": {"flag": "🇳🇴", "name": "Norway", "sims": {"Telenor": 2400000, "Telia": 1800000, "Ice": 760000}},
    "PL": {"flag": "🇵🇱", "name": "Poland", "sims": {"Orange": 4100000, "Play": 3800000, "Plus": 3200000, "T-Mobile": 2900000}},
    "PT": {"flag": "🇵🇹", "name": "Portugal", "sims": {"NOS": 2800000, "MEO": 2400000, "Vodafone": 1900000}},
    "PR": {"flag": "🇵🇷", "name": "Puerto Rico", "sims": {"Claro": 1100000, "Liberty": 540000, "T-Mobile": 890000}},
    "QA": {"flag": "🇶🇦", "name": "Qatar", "sims": {"Ooredoo": 980000, "Vodafone Qatar": 760000}},
    "RO": {"flag": "🇷🇴", "name": "Romania", "sims": {"Orange": 3200000, "Vodafone": 2800000, "Digi": 2100000, "Telekom": 1400000}},
    "SG": {"flag": "🇸🇬", "name": "Singapore", "sims": {"Singtel": 2100000, "StarHub": 1400000, "M1": 980000, "TPG": 320000}},
    "SK": {"flag": "🇸🇰", "name": "Slovakia", "sims": {"Slovak Telekom": 1400000, "Orange": 1100000, "O2": 760000}},
    "SI": {"flag": "🇸🇮", "name": "Slovenia", "sims": {"A1": 540000, "Telekom SI": 430000, "T-2": 210000}},
    "ZA": {"flag": "🇿🇦", "name": "South Africa", "sims": {"Vodacom": 5200000, "MTN": 4800000, "Cell C": 2100000, "Telkom": 1400000}},
    "ES": {"flag": "🇪🇸", "name": "Spain", "sims": {"Movistar": 7200000, "Orange": 5800000, "Vodafone": 4900000, "MásMóvil": 2100000, "Yoigo": 1400000}},
    "SE": {"flag": "🇸🇪", "name": "Sweden", "sims": {"Telia": 3200000, "Tele2": 2800000, "Tre": 1900000, "Telenor": 1400000}},
    "CH": {"flag": "🇨🇭", "name": "Switzerland", "sims": {"Swisscom": 2800000, "Sunrise": 1900000, "Salt": 980000}},
    "TW": {"flag": "🇹🇼", "name": "Taiwan", "sims": {"Chunghwa": 4100000, "Taiwan Mobile": 3200000, "FarEasTone": 2800000, "TSTAR": 1100000}},
    "TR": {"flag": "🇹🇷", "name": "Turkey", "sims": {"Turkcell": 6800000, "Vodafone": 4900000, "Türk Telekom": 4200000}},
    "AE": {"flag": "🇦🇪", "name": "UAE", "sims": {"Etisalat (e&)": 2400000, "du": 1800000}},
    "UA": {"flag": "🇺🇦", "name": "Ukraine", "sims": {"Kyivstar": 4800000, "Vodafone": 3200000, "lifecell": 2100000}},
}

# Auto-populate remaining countries with rich, realistic non-empty generic values
for cc, info in _ALL_OTHER_COUNTRIES.items():
    if cc not in LEADS:
        c_name = info["name"]
        LEADS[cc] = {
            "flag": info["flag"],
            "name": c_name,
            "verticals": {
                "banks": {"label": "🏦 Banks & Financial", "items": {f"National Bank of {c_name}": 1200000, f"Standard Chartered {cc}": 850000, f"First Commercial {c_name}": 650000, f"HSBC {cc}": 1100000, "Digital Bank": 450000}},
                "crypto": {"label": "🪙 Crypto Exchanges", "items": {f"Binance {cc}": 1500000, "Coinbase Global": 980000, f"Kraken {cc}": 650000, "KuCoin": 540000, "OKX": 710000, "Bybit": 850000}},
                "biz": {"label": "🏢 Business Registries", "items": {f"{c_name} Business Registry": 1250000, "Corporate Index": 950000, "Chamber of Commerce Data": 650000, "VAT Database": 1100000}},
                "sim": {"label": "📡 Mobile Networks", "items": _copy.deepcopy(info["sims"])},
                "ledger": {"label": "🔗 Ledgers & Nodes", "items": {"Bitcoin Full Nodes": 85000, "Ethereum Validators": 120000, "Solana RPC": 45000, "Cardano Pools": 25000, "Polygon Nodes": 35000}}
            }
        }

# ── Auto-add a "MIX" option to EVERY vertical in EVERY country ───────────────
for _cc, _d in LEADS.items():
    for vert_key, vert_data in _d["verticals"].items():
        if "MIX" not in vert_data["items"] and vert_data["items"]:
            _biggest = max(vert_data["items"].values())
            vert_data["items"]["MIX"] = int(_biggest * 1.25)

DEFAULT_LEADS = _copy.deepcopy(LEADS)
DEFAULT_STORE = None

# ── Targeted Source Pricing ───────────────────────────────────────────────────
AGED_LEADS_PRICING   = [(1_000, 70), (5_000, 300), (10_000, 500), (25_000, 1100)]
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

# ── Performance Optimization: Caching Helper ──────────────────────────────────
def rebuild_cache():
    """Pre-calculates dynamic totals to completely eliminate bot UI lag."""
    global CACHE_TOTAL_LEADS, CACHE_COUNTRY_TOTALS, CACHE_VERT_TOTALS
    CACHE_TOTAL_LEADS = 0
    CACHE_COUNTRY_TOTALS.clear()
    CACHE_VERT_TOTALS.clear()
    
    for cc, c_data in LEADS.items():
        c_tot = 0
        CACHE_VERT_TOTALS[cc] = {}
        for v_key, v_data in c_data["verticals"].items():
            v_tot = sum(v_data["items"].values())
            CACHE_VERT_TOTALS[cc][v_key] = v_tot
            c_tot += v_tot
        CACHE_COUNTRY_TOTALS[cc] = c_tot
        CACHE_TOTAL_LEADS += c_tot

def calculate_dynamic_stock():
    total = 0
    for vid, vdata in STORE.items():
        for bkey, bdata in vdata.get("bases", {}).items():
            total += sum(bdata.get("bins", {}).values())
    return total

# ── Persistence (save/load data) ──────────────────────────────────────────────
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
        logger.info("No saved data file yet — starting fresh.")
        rebuild_cache()
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

        # Merge defaults smoothly
        for cc, d in DEFAULT_LEADS.items():
            if cc not in LEADS:
                LEADS[cc] = _copy.deepcopy(d)
            else:
                if "carriers" in LEADS[cc]:
                    old_carriers = LEADS[cc].pop("carriers")
                    LEADS[cc]["verticals"] = _copy.deepcopy(d["verticals"])
                    LEADS[cc]["verticals"]["sim"]["items"].update(old_carriers)
                elif "verticals" not in LEADS[cc]:
                    LEADS[cc]["verticals"] = _copy.deepcopy(d["verticals"])

                for vert_key, vert_data in d["verticals"].items():
                    if vert_key not in LEADS[cc]["verticals"]:
                        LEADS[cc]["verticals"][vert_key] = _copy.deepcopy(vert_data)
                    else:
                        if vert_key == "sim" and "carriers" in LEADS[cc]["verticals"]["sim"]:
                            old_sim = LEADS[cc]["verticals"]["sim"].pop("carriers")
                            LEADS[cc]["verticals"]["sim"]["items"] = old_sim
                            
                        for item, stock in vert_data["items"].items():
                            if item not in LEADS[cc]["verticals"][vert_key].get("items", {}):
                                if "items" not in LEADS[cc]["verticals"][vert_key]:
                                    LEADS[cc]["verticals"][vert_key]["items"] = {}
                                LEADS[cc]["verticals"][vert_key]["items"][item] = stock
        
        rebuild_cache() # Optimize totals mapping instantly 
        logger.info("✅ Loaded saved data from disk.")
    except Exception as e:
        logger.error(f"load_data failed: {e}")

# ── Channel Logger ────────────────────────────────────────────────────────────
async def log(app, text: str):
    if not LOG_CHANNEL_ID: return
    try: await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception as e: logger.warning(f"Log failed: {e}")

# ── Admin check ───────────────────────────────────────────────────────────────
def is_admin(update) -> bool:
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

async def check_channel_membership(bot, user_id):
    if not JOIN_CHANNEL: return True, "ok"
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"):
            return True, "ok"
        return False, "not_joined"
    except Exception as e:
        logger.warning(f"Membership check error: {e}")
        return False, "error"

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

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

# ── Scanner keyboards ─────────────────────────────────────────────────────────
SCAN_CATS = {"all": "All •", "socials": "Socials", "crypto": "Crypto", "shopping": "Shop...", "carrier": "Carrier"}

def scanner_items_for_cat(cat):
    if cat == "all": return list(enumerate(SCANNER_ITEMS))
    return [(i, item) for i, item in enumerate(SCANNER_ITEMS) if item[1] == cat]

def scanner_keyboard(cat="all", page=0):
    items = scanner_items_for_cat(cat)
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

# ── UI Construction & Lightweight Keyboards ───────────────────────────────────
def leads_pricing_text():
    return "\n".join(["📊 *Pricing*"] + [f"{qty//1000}k — £{price}" for qty, price in LEADS_PRICING])

def country_keyboard():
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        rows.append([InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"lc|{cc}") for cc, d in countries[i:i+2]])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def vertical_keyboard(cc):
    """Hub keyboard displaying vertical choices for a country."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Crypto Exchanges", callback_data=f"lvert|{cc}|crypto")],
        [InlineKeyboardButton("🏦 Banks & Financial", callback_data=f"lvert|{cc}|banks")],
        [InlineKeyboardButton("🏢 Business Registries", callback_data=f"lvert|{cc}|biz")],
        [InlineKeyboardButton("📡 Mobile Networks", callback_data=f"lvert|{cc}|sim")],
        [InlineKeyboardButton("🔗 Ledgers & Nodes", callback_data=f"lvert|{cc}|ledger")],
        [InlineKeyboardButton("⬅️ Back to Directory", callback_data="leads")]
    ])

def item_keyboard(cc, vert):
    """Grid of items for a country's vertical, max 2 per row."""
    items = list(LEADS[cc]["verticals"][vert]["items"].items())
    rows = []
    for i in range(0, len(items), 2):
        rows.append([InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"lk|{cc}|{vert}|{name}") for name, stock in items[i:i+2]])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, vert, item):
    rows = []
    for i in range(0, len(LEADS_PRICING), 2):
        rows.append([InlineKeyboardButton(f"{qty//1000}k — £{price}", callback_data=f"lq|{cc}|{vert}|{item}|{qty}") for qty, price in LEADS_PRICING[i:i+2]])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lvert|{cc}|{vert}")])
    return InlineKeyboardMarkup(rows)

def tsource_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("‼️ Aged / Bank-Targeted Leads", callback_data="ts_aged")],
        [InlineKeyboardButton("🪙 Crypto Leads",               callback_data="ts_crypto")],
        [InlineKeyboardButton("🛠 Additional Services",        callback_data="ts_services")],
        [InlineKeyboardButton("⬅️ Back",                       callback_data="back")],
    ])

def ts_qty_keyboard(pricing, cb_prefix):
    rows = []
    for i in range(0, len(pricing), 2):
        row = []
        for qty, price in pricing[i:i+2]:
            label = f"£{price//1000}k" if price >= 1000 else f"£{price}"
            row.append(InlineKeyboardButton(f"{qty//1000}k — {label}", callback_data=f"{cb_prefix}|{qty}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tsource")])
    return InlineKeyboardMarkup(rows)

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads",            callback_data="leads"),
         InlineKeyboardButton("🛍️ Store",            callback_data="store")],
        [InlineKeyboardButton("💰 Wallet",           callback_data="wallet"),
         InlineKeyboardButton("🔍 Scanner",          callback_data="scanner")],
        [InlineKeyboardButton("🎯 Targeted Source",  callback_data="tsource")],
    ])

def main_menu_text():
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Stock*\n"
        f"🌍 Leads: *{CACHE_TOTAL_LEADS:,}*\n"
        f"🛍️ Store: *{calculate_dynamic_stock():,}*\n\n"
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
    vids = list(STORE.keys())
    rows = [[InlineKeyboardButton(v, callback_data=f"vendor|{v}") for v in vids[i:i+2]] for i in range(0, len(vids), 2)]
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

# ── Bot Commands ──────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)

    if is_new:
        await log(context.application, f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    if uid in agreed_users and uid in channel_verified:
        await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel to Continue", url=JOIN_CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Let Me In",  callback_data="agree_rules")],
    ])
    await update.message.reply_text(RULES_TEXT, reply_markup=keyboard, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    await update.message.reply_text(
        f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*\n\n_Top up via the Wallet section._",
        parse_mode="Markdown"
    )

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

async def cmd_targeted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎯 *Targeted Source*\n\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")

SUPPORT_USER = os.environ.get("SUPPORT_USERNAME", "HekTikz")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 *Contact / Support*\n\n"
        f"For top-ups, orders, refunds or any help, message the admin directly:\n\n"
        f"👤 Admin: @{SUPER_ADMIN}\n🔹 Support 24/7: @{SUPPORT_USER}\n\n_Tap a button below to open a chat._",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"👤 Message Admin", url=f"https://t.me/{SUPER_ADMIN}")], [InlineKeyboardButton(f"🔹 Message Support", url=f"https://t.me/{SUPPORT_USER}")]]),
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How to use this bot*\n\n1️⃣ Top up your balance — /wallet\n2️⃣ Browse sections from /start\n3️⃣ Pick an item and confirm\n4️⃣ Contact admin for files\n\nNeed help? Message @{SUPER_ADMIN}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")]]), parse_mode="Markdown"
    )

# ── Admin System ──────────────────────────────────────────────────────────────
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
    "`/adminlogin <password>` | `/adminlogout`\n\n"
    "*Balance*\n`/addbalance <uid> <amt>` | `/removebalance <uid> <amt>`\n`/setbalance <uid> <amt>` | `/checkbalance <uid>`\n\n"
    "*Store*\n`/addvendor <id> <label>` | `/removevendor <id>`\n`/addbase <vid> <bkey> <price> <label>` | `/removebase <vid> <bkey>`\n"
    "`/addbin <vid> <bkey> <bin> <qty>` | `/removebin <vid> <bkey> <bin>`\n`/bulkbin <vid> <bkey>` | `/listbins <vid> <bkey>`\n\n"
    "*Leads Data*\n`/updatelead <CC> <CategoryKey> <ItemName> <Stock>`\n(Example: `/updatelead AU banks Westpac 3000000`)\n\n"
    "*Users*\n`/listusers` | `/broadcast <message>`"
)

def admin_menu_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]])

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode="Markdown")

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2)
    save_data()
    await update.message.reply_text(f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except: return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2)
    save_data()
    await update.message.reply_text(f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except: return
    user_balances[tid] = round(amt, 2)
    save_data()
    await update.message.reply_text(f"✅ Set `{tid}` balance to *£{amt:.2f}*", parse_mode="Markdown")

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: tid = int(context.args[0])
    except: return
    await update.message.reply_text(f"User `{tid}` balance: *£{user_balances.get(tid,0):.2f}*", parse_mode="Markdown")

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
    except: return
    del STORE[vid]; save_data()
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]; price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label and "|" not in bkey
    except: await update.message.reply_text("Usage: /addbase <vendor_id> <base_key> <price> <label>"); return
    existing_bins = STORE[vid]["bases"][bkey].get("bins", {}) if bkey in STORE[vid]["bases"] else {}
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": existing_bins}; save_data()
    await update.message.reply_text(f"✅ Base *{label}* added/updated at £{price}/card.", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: return
    del STORE[vid]["bases"][bkey]; save_data()
    await update.message.reply_text(f"✅ Removed base `{bkey}` from vendor `{vid}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid, bkey, bin_num, qty = context.args[0], context.args[1], context.args[2], int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except: return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; save_data()
    await update.message.reply_text(f"✅ BIN *{bin_num}* = *{qty}*", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid, bkey, bin_num = context.args[0], context.args[1], context.args[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None); save_data()
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid, bkey = context.args[0], context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: return
    bins = STORE[vid]["bases"][bkey]["bins"]
    label = STORE[vid]["bases"][bkey]["label"]
    if not bins: await update.message.reply_text(f"No BINs in *{label}*", parse_mode="Markdown"); return
    lines = [f"📦 *{label}* — {sum(bins.values())} total\n"] + [f"`{b}` — {q} cards" for b, q in sorted(bins.items())]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid, bkey = context.args[0], context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except: return
    STORE[vid]["bases"][bkey]["bins"].clear(); save_data()
    await update.message.reply_text(f"✅ Cleared all BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not user_balances: await update.message.reply_text("No users with balances yet."); return
    lines = ["👥 *All Users & Balances*\n"] + [f"`{uid}` — £{bal:.2f} (joined {user_join_dates.get(uid,'?')})" for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1])]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    msg = update.message.text.split(None, 1)[1] if len(update.message.text.split(None, 1)) > 1 else ""
    if not msg: await update.message.reply_text("Please provide a message. Example: `/broadcast Bot under maintenance`", parse_mode="Markdown"); return
    targets = set(user_join_dates.keys()) | set(user_balances.keys()) | agreed_users
    status_msg = await update.message.reply_text("📢 *Sending...*\nPlease wait.", reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
    sent, failed = 0, 0
    for target_uid in targets:
        try:
            await context.application.bot.send_message(chat_id=target_uid, text=msg, parse_mode="Markdown")
            sent += 1
        except:
            try:
                plain = msg.replace("*", "").replace("_", "").replace("`", "")
                await context.application.bot.send_message(chat_id=target_uid, text=plain)
                sent += 1
            except: failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"📢 *Broadcast Complete*\n\n✅ Sent: *{sent}*\n❌ Failed: {failed}\nTotal: *{len(targets)}* users", reply_markup=admin_menu_keyboard(), parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cc    = context.args[0].upper()
        vert  = context.args[1].lower()
        stock = int(context.args[-1])
        item  = " ".join(context.args[2:-1])
        assert cc in LEADS and vert in LEADS[cc]["verticals"]
    except:
        await update.message.reply_text("Usage: /updatelead <CC> <CategoryKey> <ItemName> <Stock>\nExample: /updatelead AU banks Westpac 3000000\nCategories: banks, crypto, biz, sim, ledger"); return
            
    if stock <= 0:
        LEADS[cc]["verticals"][vert]["items"].pop(item, None)
    else:
        LEADS[cc]["verticals"][vert]["items"][item] = stock
        
    save_data()
    rebuild_cache()
    await update.message.reply_text(f"✅ Data for *{item}* updated in {LEADS[cc]['name']} ({vert}) to *{stock:,}*", parse_mode="Markdown")

async def cmd_bulkbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    lines = update.message.text.split("\n")
    try:
        vid, bkey = lines[0].split()[1], lines[0].split()[2]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage:\n/bulkbin <vendor> <base>\n374646 x1\n416598 50"); return

    added, skipped = 0, 0
    for line in lines[1:]:
        parts = line.strip().replace("x", " ").replace("X", " ").split()
        if len(parts) < 2: skipped += 1; continue
        try:
            bin_num, qty = parts[0], int(parts[1])
            if qty > 0:
                STORE[vid]["bases"][bkey]["bins"][bin_num] = qty
                added += 1
            else: skipped += 1
        except: skipped += 1

    save_data()
    await update.message.reply_text(f"✅ *Bulk Add Complete*\nAdded/updated: *{added}* BINs\nSkipped: *{skipped}* lines", parse_mode="Markdown")

# ── Order Validation ──────────────────────────────────────────────────────────
def get_blocked_message(balance, item_price, back_cb):
    if balance == 0:
        return ("❌ *Insufficient Balance!*\n\n"
                f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\n"
                "Please top up your wallet first.",
                InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top Up Wallet", callback_data="wallet")]]))
    if balance < MIN_DEPOSIT_REQUIRED:
        return ("🛑 *Order Blocked*\n⚠️ *Transaction Incomplete*\n"
                "Your account balance does not meet the minimum deposit required for new users.\n"
                f" • 💰 *Current Balance:* £{balance:.2f}\n • 📋 *Required Minimum:* £{MIN_DEPOSIT_REQUIRED:.2f}\n"
                "Please fund your account to proceed.",
                InlineKeyboardMarkup([[InlineKeyboardButton("➕ Top Up", callback_data="wallet")], [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)], [InlineKeyboardButton("🌍 Menu", callback_data="back")]]))
    if balance < item_price:
        return ("❌ *Insufficient Balance!*\n\n"
                f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\n"
                "Please top up your wallet first.",
                InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]]))
    return None, None

# ── Universal Button Handler ──────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data

    if data == "agree_rules":
        is_member, reason = await check_channel_membership(context.bot, uid)
        if reason == "error":
            await query.answer("⚠️ Could not verify. Make sure the bot is Admin in the channel.", show_alert=True)
            return
        if not is_member:
            await query.answer("⛔️ You haven't joined yet! Tap 'Join Channel to Continue' first.", show_alert=True)
            return
        agreed_users.add(uid); channel_verified.add(uid); save_data()
        await query.answer()
        await log(context.application, f"User verified: {user_tag(update)} ID {uid}")
        try: await context.bot.send_message(chat_id=uid, text=main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        except: await context.bot.send_message(chat_id=uid, text=main_menu_text().replace("*", "").replace("_", ""), reply_markup=main_menu_keyboard())
        return

    # PERFORMANCE FIX: INSTANTLY KILL TELEGRAM LOADING SPINNER
    await query.answer()

    # Clear lingering text inputs
    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty"):
        context.user_data.pop(_k, None)

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return
    if data == "admin_menu":
        if not is_admin(update): return
        await query.edit_message_text(ADMIN_HELP_TEXT, parse_mode="Markdown")
        return

    # ── Wallet ──────────────────────────────────────────
    if data == "wallet":
        await log(context.application, f"💰 *Opened Wallet*\n👤 {user_tag(update)}")
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
        price_line = f"Send *Exactly* `{round(amount / prices[coin], 6)}` {coin} to get *£{amount}* credit" if prices and coin in prices else f"Send the equivalent of *£{amount}* in {coin}"
        await log(context.application, f"💰 *Top-Up Requested*\n👤 {user_tag(update)}\n💷 £{amount} via {coin}")
        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n‼️ Deposits are permanent and *non refundable*\n‼️ Double check the {coin} amount *before* sending\n‼️ Anything UNDER or ABOVE = *Donation*\n\n💠 Funded when transaction is confirmed\n\n⚠️ *DO NOT SEND AS £ — only send as {coin}*\n‼️ One payment per wallet address\n\n_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID after sending_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]), parse_mode="Markdown")
        return

    # ── Store ───────────────────────────────────────────
    if data == "store":
        await log(context.application, f"🛍️ *Opened Store*\n👤 {user_tag(update)}")
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown")
        return
    if data.startswith("vendor|"):
        vid = data.split("|")[1]
        if vid not in STORE: return
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n\nSelect a base:", reply_markup=base_select_keyboard(vid), parse_mode="Markdown")
        return
    if data.startswith("base|") or data.startswith("bpage|"):
        parts = data.split("|")
        vid, bkey = parts[1], parts[2]
        page = 0 if len(parts) == 3 else int(parts[3])
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n🗂 *Available:* {sum(base['bins'].values())}\n\nSelect BIN group:\n_Page {page+1} of {total_pages}_", reply_markup=kbd, parse_mode="Markdown")
        return
    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid
        context.user_data["awaiting_bin_search"] = True
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
        buy_qty = int(qty_s)
        base    = STORE[vid]["bases"][bkey]
        stock   = base["bins"].get(bin_num, 0)
        price   = base["price_per_card"]
        total   = round(price * buy_qty, 2)
        balance = user_balances.get(uid, 0)
        if buy_qty > stock: return
        blocked_text, blocked_kbd = get_blocked_message(balance, total, f"vendor|{vid}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total, 2)
        base["bins"][bin_num] = stock - buy_qty
        if base["bins"][bin_num] <= 0: del base["bins"][bin_num]
        save_data()
        await log(context.application, f"🛒 *Purchase — BIN*\n👤 {user_tag(update)}\n🪪 `{uid}`\nVendor: {STORE[vid]['label']}\nBase: {base['label']}\nBIN: {bin_num} x{buy_qty}\n💷 Paid: £{total:.2f}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n💳 BIN: *{bin_num}*\n🗂 Qty: *{buy_qty} fullz*\n💷 Paid: *£{total:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    # ── Deads ───────────────────────────────────────────
    if data == "deads":
        await query.edit_message_text("💀 *Deads — Unspoofed Files*\n\n*Specific:*\n• 50+ Specific BIN, Gender & DOB — £225\n• 100+ Specific BIN, Gender & DOB — £350\n\n*Random:*\n• 50+ File — £100\n• 100+ File — £150\n• 500 File — £500\n• 1k File — £700\n• 2k File — £1,200", reply_markup=deads_keyboard(), parse_mode="Markdown")
        return
    if data.startswith("dbuy|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"dcfm|{key}"), InlineKeyboardButton("❌ Cancel",  callback_data="deads")]]), parse_mode="Markdown")
        return
    if data.startswith("dcfm|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "deads")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); save_data()
        await log(context.application, f"🛒 *Purchase — Deads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n📁 {label}\n💷 Paid: £{price:,}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n📁 *{label}*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    # ── Leads (Hierarchy) ───────────────────────────────
    if data == "leads":
        await log(context.application, f"🌍 *Opened Leads*\n👤 {user_tag(update)}")
        await query.edit_message_text(f"🌍 *Leads*\n\n{leads_pricing_text()}\n\n_Select a country below:_", reply_markup=country_keyboard(), parse_mode="Markdown")
        return
        
    if data.startswith("lc|"):
        cc = data.split("|")[1]
        if cc not in LEADS: return
        d = LEADS[cc]
        tot = CACHE_COUNTRY_TOTALS.get(cc, 0)
        await log(context.application, f"🌍 *Leads Hub — {d['name']}*\n👤 {user_tag(update)}")
        await query.edit_message_text(f"{d['flag']} *{d['name']} Data Hub*\n\nTotal Stock: {tot:,} items\n\nSelect a dynamic data vertical:", reply_markup=vertical_keyboard(cc), parse_mode="Markdown")
        return

    if data.startswith("lvert|"):
        _, cc, vert = data.split("|", 2)
        if cc not in LEADS or vert not in LEADS[cc]["verticals"]: return
        d = LEADS[cc]
        v_data = d["verticals"][vert]
        tot = CACHE_VERT_TOTALS.get(cc, {}).get(vert, 0)
        await log(context.application, f"🌍 *Leads — {d['name']} ({v_data['label']})*\n👤 {user_tag(update)}")
        await query.edit_message_text(f"Country: {d['flag']} {d['name']}\nCategory: {v_data['label']}\nStock: {tot:,} items\n\nAvailable options:", reply_markup=item_keyboard(cc, vert), parse_mode="Markdown")
        return

    if data.startswith("lk|"):
        _, cc, vert, item = data.split("|", 3)
        if cc not in LEADS: return
        stock = LEADS[cc]["verticals"][vert]["items"].get(item, 0)
        d = LEADS[cc]
        v_label = d["verticals"][vert]["label"]
        await log(context.application, f"📡 *Leads Selection — {d['name']} / {item}*\n👤 {user_tag(update)}")
        await query.edit_message_text(f"*Country:* {d['flag']} {d['name']}\n*Category:* {v_label}\n*Item:* {item}\n*Available:* {stock:,} items\n\nSelect quantity:", reply_markup=qty_keyboard(cc, vert, item), parse_mode="Markdown")
        return

    if data.startswith("lq|"):
        _, cc, vert, item, qty_str = data.split("|", 4)
        qty     = int(qty_str)
        price   = dict(LEADS_PRICING).get(qty, 0)
        d       = LEADS[cc]
        stock   = LEADS[cc]["verticals"][vert]["items"].get(item, 0)
        balance = user_balances.get(uid, 0)
        v_label = d["verticals"][vert]["label"]
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🌍 *Country:* {d['flag']} {d['name']}\n📡 *Category:* {v_label}\n📦 *Item:* {item}\n🗂 *Quantity:* {qty:,} items\n💷 *Price: £{price}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{vert}|{item}|{qty}"), InlineKeyboardButton("❌ Cancel",  callback_data=f"lk|{cc}|{vert}|{item}")]]), parse_mode="Markdown")
        return

    if data.startswith("lb|"):
        _, cc, vert, item, qty_str = data.split("|", 4)
        qty     = int(qty_str)
        price   = dict(LEADS_PRICING).get(qty, 0)
        balance = user_balances.get(uid, 0)
        d       = LEADS[cc]
        blocked_text, blocked_kbd = get_blocked_message(balance, price, f"lk|{cc}|{vert}|{item}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
            
        user_balances[uid] = round(balance - price, 2)
        if cc in LEADS and item in LEADS[cc]["verticals"][vert]["items"]:
            LEADS[cc]["verticals"][vert]["items"][item] = max(0, LEADS[cc]["verticals"][vert]["items"][item] - qty)
        
        save_data()
        rebuild_cache()
        await log(context.application, f"🛒 *Purchase — Leads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n🌍 {d['flag']} {d['name']} | {vert} | {item}\n🗂 {qty:,} items\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🌍 *{d['flag']} {d['name']}* — {item}\n🗂 *{qty:,} items*\n💷 Paid: *£{price}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]), parse_mode="Markdown")
        return

    # ── Scanner ─────────────────────────────────────────
    if data == "scanner":
        await log(context.application, f"🔍 *Opened Scanner*\n👤 {user_tag(update)}")
        await query.edit_message_text("🔍 *Scanner*\n\n👆 Select a scanner to verify your data.", reply_markup=scanner_keyboard("all", 0), parse_mode="Markdown")
        return
    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        await query.edit_message_text("🔍 *Scanner*\n\n👆 Select a scanner to verify your data.", reply_markup=scanner_keyboard(cat, pg), parse_mode="Markdown")
        return
    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        label, category, price = SCANNER_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🔍 *{label}*\n\n💰 Price: *${price:.2f} / k*\nYour balance: *£{balance:.2f}*\n\nSelect quantity:", reply_markup=scanner_qty_keyboard(idx, category), parse_mode="Markdown")
        return
    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|"); idx, qty_k = int(idx_s), int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🔍 *{label}*\n🗂 Quantity: *{qty_k}k*\n💷 *Total: £{total_gbp:.2f}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"), InlineKeyboardButton("❌ Cancel", callback_data=f"sni|{idx}")]]), parse_mode="Markdown")
        return
    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|"); idx, qty_k = int(idx_s), int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, total_gbp, f"sni|{idx}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total_gbp, 2); save_data()
        await log(context.application, f"🔍 *Purchase — Scanner*\n👤 {user_tag(update)}\n🪪 `{uid}`\nItem: {label} | {qty_k}k\n💷 Paid: £{total_gbp:.2f}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🔍 *{label}*\n🗂 *{qty_k}k records*\n💷 Paid: *£{total_gbp:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your data.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]), parse_mode="Markdown")
        return

    # ── Targeted Source ─────────────────────────────────
    if data == "tsource":
        await query.edit_message_text("🎯 *Targeted Source*\n\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown")
        return
    if data == "ts_aged":
        await query.edit_message_text("‼️ *Aged Leads / Bank-Targeted Leads*\n\n• Fresh leads added daily\n• Targeted bank leads available\n• Demographic filtering: Female (60+) & Male (60+)\n\n👵 *Age-Filtered Leads:*\n• Choose specific age groups (Male or Female)\n\n🏦 *Bank-Targeted Leads:*\n✉️ *Details Provided:*\n• Full Name\n• Bank Name\n• Card Type (Credit/Debit)\n• Phone Number\n• Address\n• Email\n\n💰 *Pricing:*\n• 1k — £70\n• 5k — £300\n• 10k — £500\n• 25k — £1.1k\n\n_Select a quantity to purchase:_", reply_markup=ts_qty_keyboard(AGED_LEADS_PRICING, "tsaged"), parse_mode="Markdown")
        return
    if data == "ts_crypto":
        await query.edit_message_text("🪙 *Crypto Leads* _(AVAILABLE IN STOCK)_\n\n*Available Platforms:*\n• KuCoin | Binance | CoinSpot | Crypto.com\n• Shakepay | Coinbase | OKX | MetaMask\n• USA iOS / Checked Crypto Leads — Verified & Crypto-Ready 24/7\n\n✉️ *Details Provided:*\n• Email | Phone | Full Name | DOB\n• Country | Full Address | IP\n\n💰 *Pricing:*\n• 1k — £200\n• 5k — £800\n• 10k — £1.5k\n• 25k — £2.5k\n\n_Select a quantity to purchase:_", reply_markup=ts_qty_keyboard(CRYPTO_LEADS_PRICING, "tscrypto"), parse_mode="Markdown")
        return
    if data == "ts_services":
        await query.edit_message_text(f"🛠 *Additional Services*\n\n💬 *Sender Services:*\n• Book your SMS send-out\n• Email send-outs also available\n\n💻 *Development Services:*\n• Systems, development panels, specialised pages\n• Script updates available upon request\n\n📩 PM Admin @{SUPER_ADMIN} to discuss your requirements.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")], [InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return
    if data.startswith("tsaged|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0)
        label = f"£{price//1000}k" if price >= 1000 else f"£{price}"
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n‼️ *Aged / Bank-Targeted Leads*\n🗂 Quantity: *{qty//1000}k leads*\n💷 *Total: {label}*\n\nYour balance: *£{user_balances.get(uid, 0):.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tsaged_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_aged")]]), parse_mode="Markdown")
        return
    if data.startswith("tsaged_confirm|"):
        qty = int(data.split("|")[1]); price = dict(AGED_LEADS_PRICING).get(qty, 0)
        blocked_text, blocked_kbd = get_blocked_message(user_balances.get(uid, 0), price, "ts_aged")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(user_balances.get(uid, 0) - price, 2); save_data()
        await log(context.application, f"🛒 *Purchase — Aged Leads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n🗂 {qty//1000}k leads\n💷 Paid: £{price:,}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n‼️ *Aged / Bank-Targeted Leads*\n🗂 *{qty//1000}k leads*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return
    if data.startswith("tscrypto|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0)
        label = f"£{price//1000}k" if price >= 1000 else f"£{price}"
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🪙 *Crypto Leads*\n🗂 Quantity: *{qty//1000}k leads*\n💷 *Total: {label}*\n\nYour balance: *£{user_balances.get(uid, 0):.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tscrypto_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_crypto")]]), parse_mode="Markdown")
        return
    if data.startswith("tscrypto_confirm|"):
        qty = int(data.split("|")[1]); price = dict(CRYPTO_LEADS_PRICING).get(qty, 0)
        blocked_text, blocked_kbd = get_blocked_message(user_balances.get(uid, 0), price, "ts_crypto")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(user_balances.get(uid, 0) - price, 2); save_data()
        await log(context.application, f"🛒 *Purchase — Crypto Leads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n🗂 {qty//1000}k leads\n💷 Paid: £{price:,}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n🪙 *Crypto Leads*\n🗂 *{qty//1000}k leads*\n💷 Paid: *£{price:,}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

# ── Message Handler ───────────────────────────────────────────────────────────
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_qty"):
        info = context.user_data.get("buy_bin", {})
        try: buy_qty = int(update.message.text.strip())
        except ValueError: await update.message.reply_text("Please enter a valid number."); return
        available = info.get("available", 0)
        if buy_qty < 1 or buy_qty > available: await update.message.reply_text(f"Please enter a number between 1 and {available}."); return
        context.user_data["awaiting_qty"] = False
        vid, bkey, bin_num, price = info["vid"], info["bkey"], info["bin_num"], info["price"]
        total = round(price * buy_qty, 2)
        await update.message.reply_text(f"🛒 *Purchase Confirmation*\n\n💳 BIN: *{bin_num}*\n🗂 Quantity: *{buy_qty} fullz*\n💰 Per fullz: *£{price:.2f}*\n💷 *Total: £{total:.2f}*\n\nYour balance: *£{user_balances.get(update.effective_user.id, 0):.2f}*\n\nConfirm purchase?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"cfmqty|{vid}|{bkey}|{bin_num}|{buy_qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_custom"):
        try: amount = int(float(update.message.text.strip().replace("£","")))
        except ValueError: await update.message.reply_text("Enter a number e.g. 150"); return
        if amount < MIN_TOPUP: await update.message.reply_text(f"Minimum is £{MIN_TOPUP}."); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(f"🔶 *£{amount} Top-Up*\n\nChoose payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num, vid = update.message.text.strip(), context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        buttons = []
        for bkey, base in STORE.get(vid, {}).get("bases", {}).items():
            qty = base["bins"].get(bin_num)
            if qty: buttons.append([InlineKeyboardButton(f"{base['label']} - {bin_num} ({qty})", callback_data=f"buybin|{vid}|{bkey}|{bin_num}|0")])
        if buttons:
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
            await update.message.reply_text(f"👤 *Vendor:* {STORE[vid]['label']}\n\n🔍 *Search results for {bin_num}:*\n\nTap a result below to purchase:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ BIN *{bin_num}* not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")
        return

# ── Main Runtime ──────────────────────────────────────────────────────────────
async def error_handler(update, context):
    logger.error("🔥 Unhandled exception while processing update:", exc_info=context.error)

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    load_data()

    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    get_updates_request = HTTPXRequest(connect_timeout=30.0, read_timeout=45.0, write_timeout=30.0, pool_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(get_updates_request).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("balance",       cmd_balance))
    app.add_handler(CommandHandler("wallet",        cmd_wallet))
    app.add_handler(CommandHandler("targeted",      cmd_targeted))
    app.add_handler(CommandHandler("contact",       cmd_contact))
    app.add_handler(CommandHandler("support",       cmd_contact))
    app.add_handler(CommandHandler("help",          cmd_help))
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
    app.add_handler(CommandHandler("updatelead",    cmd_updatelead))
    app.add_handler(CommandHandler("bulkbin",       cmd_bulkbin))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)
    
    logger.info("Bot started ✅")
    app.run_polling(timeout=30, drop_pending_updates=False)

if __name__ == "__main__":
    import time
    while True:
        try:
            main()
            break
        except Exception:
            logger.exception("Fatal error — restarting bot in 5s")
            time.sleep(5)
