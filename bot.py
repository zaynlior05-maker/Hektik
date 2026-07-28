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

# ── Config & Persistence Paths ────────────────────────────────────────────────
DATA_DIR  = os.environ.get("DATA_DIR", ".")
DATA_FILE = os.path.join(DATA_DIR, "botdata.json")
COUNTRIES_DIR = os.path.join(DATA_DIR, "countries")

BOT_TOKEN            = os.environ.get("BOT_TOKEN")
SUPER_ADMIN          = os.environ.get("ADMIN_USERNAME", "HekTikz")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "changeme123")
LOG_CHANNEL_ID       = os.environ.get("LOG_CHANNEL_ID")
MIN_TOPUP            = 70
MIN_DEPOSIT_REQUIRED = float(os.environ.get("MIN_DEPOSIT_REQUIRED", 150.00))

JOIN_CHANNEL     = os.environ.get("JOIN_CHANNEL", "") if os.environ.get("JOIN_CHANNEL", "") else None
JOIN_CHANNEL_URL = os.environ.get("JOIN_CHANNEL_URL", "https://t.me/+yourchannelinvitelink")

WALLETS = {
    "BTC": os.environ.get("WALLET_BTC", "YOUR_BTC_ADDRESS_HERE"),
    "SOL": os.environ.get("WALLET_SOL", "YOUR_SOL_ADDRESS_HERE"),
    "LTC": os.environ.get("WALLET_LTC", "YOUR_LTC_ADDRESS_HERE"),
}

# ── Global Storage State ──────────────────────────────────────────────────────
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

# ── Store & Scanner Modules ───────────────────────────────────────────────────
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
    ("Carrier · UK",          "carrier",  0.75),
    ("Carrier · US",          "carrier",  0.75),
    ("Carrier · Australia",   "carrier",  0.75),
    ("Carrier · Nigeria",     "carrier",  0.75),
]

SCANNER_PER_PAGE = 10
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]

LEADS_PRICING = [
    (1_000,   15),  (2_000,  30),  (3_000,   45),  (4_000,  50),
    (5_000,   60),  (6_000,  65),  (7_000,   70),  (8_000,  80),
    (10_000, 100),  (15_000,125),  (20_000, 150),  (25_000,175),
    (30_000, 200),  (50_000,300),  (100_000,600),
]

AGED_LEADS_PRICING = [(1_000, 70), (5_000, 300), (10_000, 500), (25_000, 1100)]
CRYPTO_LEADS_PRICING = [(1_000, 200), (5_000, 800), (10_000, 1500), (25_000, 2500)]

RULES_TEXT = (
    "🛍 *Welcome to HekTik's Store!*\n\n"
    "To access the store, you are required to join our channel below.\n\n"
    "*Refund Rules*\n"
    "• /refund to submit refunds\n"
    "• Screen recording proof of pay.google.com only, 5 mins refund time\n"
    "• If the card is live but phone number is incorrect, no refund\n\n"
    "🔹 Support 24/7 @HekTikz.\n\n"
    "By continuing, you agree to the rules."
)

# ── EMBEDDED MASTER COUNTRY DATASETS (Authentic, verified data ONLY) ──────────
WORLD_DATASETS = {
    "AR": {
        "network": [
            {"name": "Claro Argentina", "stock": 5800000, "price": 15.0},
            {"name": "Personal", "stock": 5200000, "price": 15.0},
            {"name": "Movistar Argentina", "stock": 4500000, "price": 15.0}
        ],
        "bank": [
            {"name": "Banco de la Nación Argentina", "stock": 5200000, "price": 20.0},
            {"name": "Banco Galicia", "stock": 2400000, "price": 20.0},
            {"name": "Banco Macro", "stock": 2100000, "price": 20.0},
            {"name": "Santander Río", "stock": 1800000, "price": 20.0},
            {"name": "BBVA Argentina", "stock": 1900000, "price": 20.0},
            {"name": "Banco Provincia", "stock": 1500000, "price": 20.0},
            {"name": "Banco Ciudad", "stock": 950000, "price": 20.0}
        ],
        "business": [
            {"name": "Mercado Libre", "stock": 3500000, "price": 25.0},
            {"name": "YPF", "stock": 1200000, "price": 25.0},
            {"name": "Globant", "stock": 850000, "price": 25.0},
            {"name": "Despegar", "stock": 650000, "price": 25.0},
            {"name": "Aerolíneas Argentinas", "stock": 550000, "price": 25.0},
            {"name": "Telecom Argentina", "stock": 920000, "price": 25.0},
            {"name": "Arcor", "stock": 780000, "price": 25.0},
            {"name": "Coto", "stock": 1100000, "price": 25.0},
            {"name": "Cencosud Argentina", "stock": 890000, "price": 25.0},
            {"name": "Hospital Italiano de Buenos Aires", "stock": 120000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Ripio", "stock": 2100000, "price": 30.0},
            {"name": "Lemon Cash", "stock": 1800000, "price": 30.0},
            {"name": "Bitso Argentina", "stock": 1200000, "price": 30.0},
            {"name": "Buenbit", "stock": 950000, "price": 30.0},
            {"name": "SatoshiTango", "stock": 610000, "price": 30.0},
            {"name": "Binance Argentina", "stock": 3500000, "price": 30.0},
            {"name": "OKX Argentina", "stock": 850000, "price": 30.0}
        ],
        "nodes": []
    },
    "AT": {
        "network": [
            {"name": "A1 Austria", "stock": 1540000, "price": 15.0},
            {"name": "Magenta Telekom", "stock": 890000, "price": 15.0},
            {"name": "Drei Austria", "stock": 760000, "price": 15.0},
            {"name": "Spusu", "stock": 210000, "price": 15.0},
            {"name": "HoT Hofer Telekom", "stock": 310000, "price": 15.0}
        ],
        "bank": [
            {"name": "Erste Bank", "stock": 1900000, "price": 20.0},
            {"name": "Raiffeisen Bank International", "stock": 2100000, "price": 20.0},
            {"name": "BAWAG PSK", "stock": 950000, "price": 20.0},
            {"name": "Bank Austria (UniCredit)", "stock": 1400000, "price": 20.0},
            {"name": "Oberbank", "stock": 620000, "price": 20.0},
            {"name": "Volksbank", "stock": 780000, "price": 20.0},
            {"name": "Hypo Vorarlberg", "stock": 280000, "price": 20.0}
        ],
        "business": [
            {"name": "Firmenbuch (Commercial Register)", "stock": 850000, "price": 25.0},
            {"name": "OMV", "stock": 210000, "price": 25.0},
            {"name": "Red Bull GmbH", "stock": 450000, "price": 25.0},
            {"name": "Swarovski", "stock": 310000, "price": 25.0},
            {"name": "Spar Österreich", "stock": 1200000, "price": 25.0},
            {"name": "REWE Group (Billa)", "stock": 1100000, "price": 25.0},
            {"name": "STRABAG", "stock": 350000, "price": 25.0},
            {"name": "Voestalpine", "stock": 180000, "price": 25.0},
            {"name": "Austrian Airlines", "stock": 550000, "price": 25.0},
            {"name": "Vienna General Hospital (AKH)", "stock": 95000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Bitpanda", "stock": 1400000, "price": 30.0},
            {"name": "Coinfinity", "stock": 350000, "price": 30.0},
            {"name": "Bybit Austria", "stock": 650000, "price": 30.0},
            {"name": "Kraken Austria", "stock": 420000, "price": 30.0},
            {"name": "Binance Austria", "stock": 800000, "price": 30.0}
        ],
        "nodes": []
    },
    "BD": {
        "network": [
            {"name": "Grameenphone", "stock": 7500000, "price": 15.0},
            {"name": "Robi", "stock": 4800000, "price": 15.0},
            {"name": "Banglalink", "stock": 3900000, "price": 15.0},
            {"name": "Teletalk", "stock": 950000, "price": 15.0}
        ],
        "bank": [
            {"name": "Sonali Bank", "stock": 3200000, "price": 20.0},
            {"name": "Dutch-Bangla Bank", "stock": 2800000, "price": 20.0},
            {"name": "BRAC Bank", "stock": 2500000, "price": 20.0},
            {"name": "Islami Bank Bangladesh", "stock": 3100000, "price": 20.0},
            {"name": "Eastern Bank", "stock": 1200000, "price": 20.0},
            {"name": "City Bank", "stock": 1400000, "price": 20.0},
            {"name": "Prime Bank", "stock": 980000, "price": 20.0},
            {"name": "Mutual Trust Bank", "stock": 850000, "price": 20.0},
            {"name": "Pubali Bank", "stock": 1100000, "price": 20.0},
            {"name": "Agrani Bank", "stock": 1500000, "price": 20.0},
            {"name": "Janata Bank", "stock": 1400000, "price": 20.0}
        ],
        "business": [
            {"name": "Beximco", "stock": 610000, "price": 25.0},
            {"name": "Square Pharmaceuticals", "stock": 450000, "price": 25.0},
            {"name": "PRAN-RFL Group", "stock": 520000, "price": 25.0},
            {"name": "Walton", "stock": 380000, "price": 25.0},
            {"name": "Bashundhara Group", "stock": 480000, "price": 25.0},
            {"name": "ACI Limited", "stock": 410000, "price": 25.0},
            {"name": "Akij Group", "stock": 350000, "price": 25.0},
            {"name": "Biman Bangladesh Airlines", "stock": 210000, "price": 25.0},
            {"name": "Square Hospital", "stock": 85000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Binance P2P BD", "stock": 1100000, "price": 30.0},
            {"name": "Bybit P2P BD", "stock": 750000, "price": 30.0},
            {"name": "OKX P2P BD", "stock": 510000, "price": 30.0}
        ],
        "nodes": []
    },
    "ZA": {
        "network": [
            {"name": "Vodacom", "stock": 5200000, "price": 15.0},
            {"name": "MTN South Africa", "stock": 4800000, "price": 15.0},
            {"name": "Telkom", "stock": 1400000, "price": 15.0},
            {"name": "Cell C", "stock": 2100000, "price": 15.0},
            {"name": "Rain", "stock": 850000, "price": 15.0}
        ],
        "bank": [
            {"name": "Standard Bank", "stock": 6500000, "price": 20.0},
            {"name": "FirstRand (FNB)", "stock": 6900000, "price": 20.0},
            {"name": "Absa", "stock": 5400000, "price": 20.0},
            {"name": "Nedbank", "stock": 4800000, "price": 20.0},
            {"name": "Capitec", "stock": 7800000, "price": 20.0},
            {"name": "Investec", "stock": 1200000, "price": 20.0},
            {"name": "Discovery Bank", "stock": 950000, "price": 20.0}
        ],
        "business": [
            {"name": "Naspers", "stock": 520000, "price": 25.0},
            {"name": "Shoprite", "stock": 1800000, "price": 25.0},
            {"name": "Woolworths SA", "stock": 1500000, "price": 25.0},
            {"name": "Sasol", "stock": 450000, "price": 25.0},
            {"name": "MTN Group", "stock": 980000, "price": 25.0},
            {"name": "Sanlam", "stock": 750000, "price": 25.0},
            {"name": "Discovery Limited", "stock": 650000, "price": 25.0},
            {"name": "Netcare Hospitals", "stock": 310000, "price": 25.0},
            {"name": "South African Airways", "stock": 280000, "price": 25.0},
            {"name": "Anglo American SA", "stock": 210000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Luno", "stock": 2100000, "price": 30.0},
            {"name": "VALR", "stock": 1100000, "price": 30.0},
            {"name": "Binance SA", "stock": 2400000, "price": 30.0},
            {"name": "AltCoinTrader", "stock": 850000, "price": 30.0},
            {"name": "Revix", "stock": 420000, "price": 30.0}
        ],
        "nodes": []
    },
    "BR": {
        "network": [
            {"name": "Vivo", "stock": 7800000, "price": 15.0},
            {"name": "Claro Brasil", "stock": 6500000, "price": 15.0},
            {"name": "TIM Brasil", "stock": 5200000, "price": 15.0}
        ],
        "bank": [
            {"name": "Itaú Unibanco", "stock": 11500000, "price": 20.0},
            {"name": "Banco do Brasil", "stock": 9800000, "price": 20.0},
            {"name": "Bradesco", "stock": 9100000, "price": 20.0},
            {"name": "Caixa Econômica Federal", "stock": 12500000, "price": 20.0},
            {"name": "Santander Brasil", "stock": 7400000, "price": 20.0},
            {"name": "Nubank", "stock": 14000000, "price": 20.0},
            {"name": "Banco Inter", "stock": 4500000, "price": 20.0},
            {"name": "BTG Pactual", "stock": 2100000, "price": 20.0}
        ],
        "business": [
            {"name": "Petrobras", "stock": 1500000, "price": 25.0},
            {"name": "Vale", "stock": 850000, "price": 25.0},
            {"name": "Ambev", "stock": 1200000, "price": 25.0},
            {"name": "JBS", "stock": 950000, "price": 25.0},
            {"name": "WEG", "stock": 420000, "price": 25.0},
            {"name": "Embraer", "stock": 310000, "price": 25.0},
            {"name": "Azul Linhas Aéreas", "stock": 650000, "price": 25.0},
            {"name": "Magazine Luiza", "stock": 2800000, "price": 25.0},
            {"name": "Hospital Albert Einstein", "stock": 150000, "price": 25.0},
            {"name": "Natura", "stock": 1100000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Mercado Bitcoin", "stock": 2900000, "price": 30.0},
            {"name": "Bitso Brasil", "stock": 1400000, "price": 30.0},
            {"name": "Foxbit", "stock": 850000, "price": 30.0},
            {"name": "Binance Brasil", "stock": 3500000, "price": 30.0},
            {"name": "NovaDAX", "stock": 620000, "price": 30.0},
            {"name": "Bitofertas", "stock": 210000, "price": 30.0}
        ],
        "nodes": []
    },
    "AE": {
        "network": [
            {"name": "Etisalat", "stock": 8500000, "price": 15.0},
            {"name": "du", "stock": 6200000, "price": 15.0},
            {"name": "Virgin Mobile UAE", "stock": 1100000, "price": 15.0}
        ],
        "bank": [
            {"name": "First Abu Dhabi Bank (FAB)", "stock": 3500000, "price": 20.0},
            {"name": "Emirates NBD", "stock": 4900000, "price": 20.0},
            {"name": "ADCB", "stock": 2800000, "price": 20.0},
            {"name": "Dubai Islamic Bank (DIB)", "stock": 2100000, "price": 20.0},
            {"name": "Mashreq", "stock": 1800000, "price": 20.0},
            {"name": "Abu Dhabi Islamic Bank (ADIB)", "stock": 1500000, "price": 20.0}
        ],
        "business": [
            {"name": "Emirates Group", "stock": 1200000, "price": 25.0},
            {"name": "Emaar Properties", "stock": 850000, "price": 25.0},
            {"name": "DP World", "stock": 650000, "price": 25.0},
            {"name": "Etihad Airways", "stock": 720000, "price": 25.0},
            {"name": "ADNOC", "stock": 450000, "price": 25.0},
            {"name": "Majid Al Futtaim", "stock": 1100000, "price": 25.0},
            {"name": "Landmark Group", "stock": 950000, "price": 25.0},
            {"name": "NMC Health", "stock": 320000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Binance UAE", "stock": 3100000, "price": 30.0},
            {"name": "Bybit Dubai", "stock": 2400000, "price": 30.0},
            {"name": "OKX UAE", "stock": 1800000, "price": 30.0},
            {"name": "Kraken UAE", "stock": 1200000, "price": 30.0},
            {"name": "BitOasis", "stock": 950000, "price": 30.0},
            {"name": "Rain UAE", "stock": 650000, "price": 30.0},
            {"name": "CoinMENA", "stock": 420000, "price": 30.0}
        ],
        "nodes": []
    },
    "SA": {
        "network": [
            {"name": "STC Saudi", "stock": 22000000, "price": 15.0},
            {"name": "Mobily", "stock": 14500000, "price": 15.0},
            {"name": "Zain KSA", "stock": 11000000, "price": 15.0}
        ],
        "bank": [
            {"name": "Al Rajhi Bank", "stock": 8500000, "price": 20.0},
            {"name": "SNB (Saudi National Bank)", "stock": 9200000, "price": 20.0},
            {"name": "Riyad Bank", "stock": 4500000, "price": 20.0},
            {"name": "SABB", "stock": 3800000, "price": 20.0},
            {"name": "Banque Saudi Fransi", "stock": 3100000, "price": 20.0},
            {"name": "Alinma Bank", "stock": 2900000, "price": 20.0},
            {"name": "Arab National Bank", "stock": 2400000, "price": 20.0}
        ],
        "business": [
            {"name": "Saudi Aramco", "stock": 1500000, "price": 25.0},
            {"name": "SABIC", "stock": 850000, "price": 25.0},
            {"name": "STC Group", "stock": 1200000, "price": 25.0},
            {"name": "Almarai", "stock": 950000, "price": 25.0},
            {"name": "Kingdom Holding", "stock": 420000, "price": 25.0},
            {"name": "Saudia Airlines", "stock": 1100000, "price": 25.0},
            {"name": "Al Othaim", "stock": 1400000, "price": 25.0},
            {"name": "Sulaiman Al Habib Medical", "stock": 350000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Rain KSA", "stock": 850000, "price": 30.0},
            {"name": "CoinMENA KSA", "stock": 620000, "price": 30.0},
            {"name": "Binance P2P SA", "stock": 3800000, "price": 30.0},
            {"name": "OKX P2P SA", "stock": 1500000, "price": 30.0}
        ],
        "nodes": []
    },
    "DE": {
        "network": [
            {"name": "Telekom Deutschland", "stock": 8900000, "price": 15.0},
            {"name": "Vodafone Germany", "stock": 7200000, "price": 15.0},
            {"name": "O2 Germany", "stock": 5800000, "price": 15.0},
            {"name": "1&1", "stock": 1400000, "price": 15.0},
            {"name": "Congstar", "stock": 1100000, "price": 15.0}
        ],
        "bank": [
            {"name": "Deutsche Bank", "stock": 7800000, "price": 20.0},
            {"name": "Commerzbank", "stock": 5100000, "price": 20.0},
            {"name": "KfW", "stock": 1200000, "price": 20.0},
            {"name": "DZ Bank", "stock": 3200000, "price": 20.0},
            {"name": "LBBW", "stock": 1800000, "price": 20.0},
            {"name": "BayernLB", "stock": 1500000, "price": 20.0},
            {"name": "N26", "stock": 3200000, "price": 20.0},
            {"name": "DKB", "stock": 2400000, "price": 20.0},
            {"name": "ING-DiBa", "stock": 2900000, "price": 20.0},
            {"name": "Sparkasse", "stock": 9500000, "price": 20.0}
        ],
        "business": [
            {"name": "Volkswagen", "stock": 1200000, "price": 25.0},
            {"name": "Siemens", "stock": 950000, "price": 25.0},
            {"name": "Allianz", "stock": 850000, "price": 25.0},
            {"name": "SAP", "stock": 720000, "price": 25.0},
            {"name": "BMW", "stock": 1100000, "price": 25.0},
            {"name": "Mercedes-Benz", "stock": 980000, "price": 25.0},
            {"name": "Bosch", "stock": 1400000, "price": 25.0},
            {"name": "Deutsche Post", "stock": 1800000, "price": 25.0},
            {"name": "Lufthansa", "stock": 1500000, "price": 25.0},
            {"name": "Bayer", "stock": 550000, "price": 25.0},
            {"name": "REWE", "stock": 2100000, "price": 25.0},
            {"name": "E.ON", "stock": 850000, "price": 25.0},
            {"name": "Charité", "stock": 120000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Bison App", "stock": 2100000, "price": 30.0},
            {"name": "Bitpanda Germany", "stock": 1400000, "price": 30.0},
            {"name": "Coinbase Germany", "stock": 1800000, "price": 30.0},
            {"name": "Kraken Germany", "stock": 1100000, "price": 30.0},
            {"name": "Binance Germany", "stock": 3900000, "price": 30.0},
            {"name": "Bitvavo", "stock": 850000, "price": 30.0}
        ],
        "nodes": []
    },
    "FR": {
        "network": [
            {"name": "Orange France", "stock": 6200000, "price": 15.0},
            {"name": "SFR", "stock": 4800000, "price": 15.0},
            {"name": "Bouygues Telecom", "stock": 4100000, "price": 15.0},
            {"name": "Free Mobile", "stock": 3500000, "price": 15.0},
            {"name": "Sosh", "stock": 1200000, "price": 15.0}
        ],
        "bank": [
            {"name": "BNP Paribas", "stock": 6500000, "price": 20.0},
            {"name": "Crédit Agricole", "stock": 7200000, "price": 20.0},
            {"name": "Société Générale", "stock": 4800000, "price": 20.0},
            {"name": "Groupe BPCE", "stock": 4100000, "price": 20.0},
            {"name": "Crédit Mutuel", "stock": 3800000, "price": 20.0},
            {"name": "Boursorama", "stock": 3100000, "price": 20.0},
            {"name": "Hello bank!", "stock": 1500000, "price": 20.0}
        ],
        "business": [
            {"name": "LVMH", "stock": 450000, "price": 25.0},
            {"name": "L'Oréal", "stock": 620000, "price": 25.0},
            {"name": "TotalEnergies", "stock": 850000, "price": 25.0},
            {"name": "Sanofi", "stock": 510000, "price": 25.0},
            {"name": "Airbus", "stock": 480000, "price": 25.0},
            {"name": "Renault", "stock": 1100000, "price": 25.0},
            {"name": "Carrefour", "stock": 2500000, "price": 25.0},
            {"name": "Danone", "stock": 890000, "price": 25.0},
            {"name": "Air France", "stock": 1200000, "price": 25.0},
            {"name": "AXA", "stock": 1500000, "price": 25.0},
            {"name": "Michelin", "stock": 650000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Coinhouse", "stock": 900000, "price": 30.0},
            {"name": "Paymium", "stock": 450000, "price": 30.0},
            {"name": "Binance France", "stock": 2400000, "price": 30.0},
            {"name": "Kraken France", "stock": 1100000, "price": 30.0},
            {"name": "Bitvavo", "stock": 750000, "price": 30.0}
        ],
        "nodes": []
    },
    "JP": {
        "network": [
            {"name": "NTT Docomo", "stock": 18000000, "price": 15.0},
            {"name": "KDDI (au)", "stock": 14000000, "price": 15.0},
            {"name": "SoftBank", "stock": 12000000, "price": 15.0},
            {"name": "Rakuten Mobile", "stock": 3500000, "price": 15.0},
            {"name": "Y!mobile", "stock": 2100000, "price": 15.0}
        ],
        "bank": [
            {"name": "Mitsubishi UFJ (MUFG)", "stock": 8500000, "price": 20.0},
            {"name": "Sumitomo Mitsui (SMBC)", "stock": 7800000, "price": 20.0},
            {"name": "Mizuho", "stock": 6900000, "price": 20.0},
            {"name": "Japan Post Bank", "stock": 9200000, "price": 20.0},
            {"name": "Resona", "stock": 3100000, "price": 20.0},
            {"name": "SBI Sumishin Net Bank", "stock": 2100000, "price": 20.0},
            {"name": "Sony Bank", "stock": 1500000, "price": 20.0}
        ],
        "business": [
            {"name": "Toyota", "stock": 2100000, "price": 25.0},
            {"name": "Sony", "stock": 1500000, "price": 25.0},
            {"name": "Honda", "stock": 1200000, "price": 25.0},
            {"name": "Mitsubishi Corp", "stock": 950000, "price": 25.0},
            {"name": "SoftBank Group", "stock": 1800000, "price": 25.0},
            {"name": "Nintendo", "stock": 650000, "price": 25.0},
            {"name": "Hitachi", "stock": 1100000, "price": 25.0},
            {"name": "Fast Retailing (Uniqlo)", "stock": 2400000, "price": 25.0},
            {"name": "ANA", "stock": 850000, "price": 25.0},
            {"name": "Japan Airlines", "stock": 780000, "price": 25.0},
            {"name": "Seven & i Holdings", "stock": 3500000, "price": 25.0}
        ],
        "crypto": [
            {"name": "bitFlyer", "stock": 2400000, "price": 30.0},
            {"name": "Coincheck", "stock": 2100000, "price": 30.0},
            {"name": "bitbank", "stock": 1200000, "price": 30.0},
            {"name": "GMO Coin", "stock": 1100000, "price": 30.0},
            {"name": "DMM Bitcoin", "stock": 850000, "price": 30.0},
            {"name": "Zaif", "stock": 610000, "price": 30.0}
        ],
        "nodes": []
    },
    "IN": {
        "network": [
            {"name": "Jio", "stock": 24000000, "price": 15.0},
            {"name": "Airtel", "stock": 19000000, "price": 15.0},
            {"name": "Vi (Vodafone Idea)", "stock": 11000000, "price": 15.0},
            {"name": "BSNL", "stock": 4500000, "price": 15.0}
        ],
        "bank": [
            {"name": "State Bank of India (SBI)", "stock": 15000000, "price": 20.0},
            {"name": "HDFC Bank", "stock": 12000000, "price": 20.0},
            {"name": "ICICI Bank", "stock": 9800000, "price": 20.0},
            {"name": "Axis Bank", "stock": 6500000, "price": 20.0},
            {"name": "Kotak Mahindra Bank", "stock": 4100000, "price": 20.0},
            {"name": "Punjab National Bank", "stock": 7200000, "price": 20.0},
            {"name": "Bank of Baroda", "stock": 5800000, "price": 20.0},
            {"name": "IndusInd Bank", "stock": 3200000, "price": 20.0}
        ],
        "business": [
            {"name": "Reliance Industries", "stock": 3500000, "price": 25.0},
            {"name": "Tata Consultancy Services (TCS)", "stock": 1200000, "price": 25.0},
            {"name": "Infosys", "stock": 950000, "price": 25.0},
            {"name": "HDFC Corp", "stock": 1800000, "price": 25.0},
            {"name": "Hindustan Unilever", "stock": 2100000, "price": 25.0},
            {"name": "Bharti Airtel", "stock": 2500000, "price": 25.0},
            {"name": "ITC Limited", "stock": 1900000, "price": 25.0},
            {"name": "Wipro", "stock": 850000, "price": 25.0},
            {"name": "Larsen & Toubro", "stock": 1100000, "price": 25.0},
            {"name": "Apollo Hospitals", "stock": 450000, "price": 25.0},
            {"name": "Taj Hotels", "stock": 310000, "price": 25.0}
        ],
        "crypto": [
            {"name": "WazirX", "stock": 3800000, "price": 30.0},
            {"name": "CoinDCX", "stock": 3500000, "price": 30.0},
            {"name": "ZebPay", "stock": 1800000, "price": 30.0},
            {"name": "Bitbns", "stock": 950000, "price": 30.0},
            {"name": "Giottus", "stock": 610000, "price": 30.0}
        ],
        "nodes": []
    },
    "CA": {
        "network": [
            {"name": "Rogers Wireless", "stock": 11500000, "price": 15.0},
            {"name": "Bell Mobility", "stock": 10500000, "price": 15.0},
            {"name": "Telus Mobility", "stock": 9800000, "price": 15.0},
            {"name": "Fido", "stock": 3500000, "price": 15.0},
            {"name": "Koodo", "stock": 2800000, "price": 15.0},
            {"name": "Virgin Plus", "stock": 2100000, "price": 15.0},
            {"name": "Freedom Mobile", "stock": 1900000, "price": 15.0},
            {"name": "Videotron", "stock": 1500000, "price": 15.0}
        ],
        "bank": [
            {"name": "RBC", "stock": 4800000, "price": 20.0},
            {"name": "TD Bank", "stock": 4500000, "price": 20.0},
            {"name": "Scotiabank", "stock": 3900000, "price": 20.0},
            {"name": "BMO", "stock": 3200000, "price": 20.0},
            {"name": "CIBC", "stock": 2900000, "price": 20.0},
            {"name": "National Bank of Canada", "stock": 1500000, "price": 20.0},
            {"name": "Tangerine", "stock": 1200000, "price": 20.0},
            {"name": "Simplii", "stock": 850000, "price": 20.0},
            {"name": "Desjardins", "stock": 2100000, "price": 20.0}
        ],
        "business": [
            {"name": "Shopify", "stock": 450000, "price": 25.0},
            {"name": "Lululemon", "stock": 850000, "price": 25.0},
            {"name": "Air Canada", "stock": 1200000, "price": 25.0},
            {"name": "Magna International", "stock": 320000, "price": 25.0},
            {"name": "Enbridge", "stock": 210000, "price": 25.0},
            {"name": "Thomson Reuters", "stock": 180000, "price": 25.0},
            {"name": "Rogers Communications", "stock": 2100000, "price": 25.0},
            {"name": "Bell Canada", "stock": 1900000, "price": 25.0},
            {"name": "Canadian Tire", "stock": 3500000, "price": 25.0},
            {"name": "Suncor", "stock": 110000, "price": 25.0},
            {"name": "WestJet", "stock": 950000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Wealthsimple Crypto", "stock": 2100000, "price": 30.0},
            {"name": "NDAX", "stock": 650000, "price": 30.0},
            {"name": "Bitbuy", "stock": 550000, "price": 30.0},
            {"name": "Newton", "stock": 700000, "price": 30.0},
            {"name": "Kraken CA", "stock": 900000, "price": 30.0},
            {"name": "Coinbase CA", "stock": 1200000, "price": 30.0},
            {"name": "Shakepay", "stock": 1100000, "price": 30.0},
            {"name": "Coinsquare", "stock": 800000, "price": 30.0}
        ],
        "nodes": []
    },
    "US": {
        "network": [
            {"name": "AT&T", "stock": 85000000, "price": 15.0},
            {"name": "Verizon", "stock": 92000000, "price": 15.0},
            {"name": "T-Mobile", "stock": 88000000, "price": 15.0},
            {"name": "Boost Mobile", "stock": 12000000, "price": 15.0},
            {"name": "Cricket", "stock": 11500000, "price": 15.0},
            {"name": "Metro by T-Mobile", "stock": 14000000, "price": 15.0},
            {"name": "UScellular", "stock": 4500000, "price": 15.0},
            {"name": "Mint Mobile", "stock": 3800000, "price": 15.0}
        ],
        "bank": [
            {"name": "JPMorgan Chase", "stock": 45000000, "price": 20.0},
            {"name": "Bank of America", "stock": 38000000, "price": 20.0},
            {"name": "Wells Fargo", "stock": 32000000, "price": 20.0},
            {"name": "Citibank", "stock": 28000000, "price": 20.0},
            {"name": "Capital One", "stock": 21000000, "price": 20.0},
            {"name": "PNC Bank", "stock": 11000000, "price": 20.0},
            {"name": "Truist", "stock": 9500000, "price": 20.0},
            {"name": "US Bank", "stock": 15000000, "price": 20.0},
            {"name": "TD Bank USA", "stock": 12000000, "price": 20.0},
            {"name": "Fifth Third Bank", "stock": 6500000, "price": 20.0},
            {"name": "Regions Bank", "stock": 5800000, "price": 20.0},
            {"name": "Huntington Bank", "stock": 4200000, "price": 20.0},
            {"name": "Ally Financial", "stock": 8500000, "price": 20.0},
            {"name": "Discover Bank", "stock": 14000000, "price": 20.0}
        ],
        "business": [
            {"name": "Delaware Sec of State", "stock": 8500000, "price": 25.0},
            {"name": "California Sec of State", "stock": 12000000, "price": 25.0},
            {"name": "Texas Sec of State", "stock": 9500000, "price": 25.0},
            {"name": "Florida Div of Corporations", "stock": 8100000, "price": 25.0},
            {"name": "Walmart Inc.", "stock": 15000000, "price": 25.0},
            {"name": "Target Corporation", "stock": 8500000, "price": 25.0},
            {"name": "Costco Wholesale", "stock": 6200000, "price": 25.0},
            {"name": "Apple Inc.", "stock": 5500000, "price": 25.0},
            {"name": "Microsoft", "stock": 4800000, "price": 25.0},
            {"name": "Alphabet (Google)", "stock": 4200000, "price": 25.0},
            {"name": "Amazon.com", "stock": 12000000, "price": 25.0},
            {"name": "Mayo Clinic", "stock": 450000, "price": 25.0},
            {"name": "UnitedHealth Group", "stock": 1100000, "price": 25.0},
            {"name": "Hilton", "stock": 2100000, "price": 25.0},
            {"name": "Marriott", "stock": 2500000, "price": 25.0},
            {"name": "Ford Motor Company", "stock": 3500000, "price": 25.0},
            {"name": "Tesla", "stock": 450000, "price": 25.0},
            {"name": "Delta Air Lines", "stock": 520000, "price": 25.0},
            {"name": "FedEx", "stock": 750000, "price": 25.0}
        ],
        "crypto": [
            {"name": "Coinbase", "stock": 12500000, "price": 30.0},
            {"name": "Kraken", "stock": 5800000, "price": 30.0},
            {"name": "Gemini", "stock": 3200000, "price": 30.0},
            {"name": "Binance.US", "stock": 4100000, "price": 30.0}
        ],
        "nodes": []
    }
}

COUNTRY_ALIASES = {
    "UK": "GB",
    "USA": "US",
    "NIGERIA": "NG",
    "AUSTRALIA": "AU",
    "AUSTRIA": "AT",
    "BANGLADESH": "BD",
    "GERMANY": "DE",
    "INDIA": "IN",
    "JAPAN": "JP",
    "CHINA": "CN",
    "BAHRAIN": "BH",
    "BRAZIL": "BR",
    "SOUTH AFRICA": "ZA",
    "ARGENTINA": "AR"
}

ALL_COUNTRIES = sorted(list(pycountry.countries), key=lambda x: x.name)

def resolve_iso2(code_or_alias: str) -> str:
    cleaned = code_or_alias.upper().strip()
    return COUNTRY_ALIASES.get(cleaned, cleaned)

def get_country_flag(country_alpha_2: str) -> str:
    iso2 = resolve_iso2(country_alpha_2)
    try:
        return chr(ord(iso2[0]) + 127397) + chr(ord(iso2[1]) + 127397)
    except Exception:
        return "🌐"

def get_country_file_path(iso2: str, category: str) -> str:
    folder = os.path.join(COUNTRIES_DIR, iso2.lower())
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{category}.json")

def load_country_data(iso2: str, category: str) -> list:
    """
    STRICT DATA LOADING RULES:
    1. Loads from custom modular JSON if the file exists.
    2. Falls back to verified embedded `WORLD_DATASETS`.
    3. Returns EMPTY LIST `[]` to explicitly trigger "No Data Available".
       NO FAKE PLACEHOLDERS (e.g. no "Central Bank of [Country]").
    """
    iso2_clean = resolve_iso2(iso2)
    path = get_country_file_path(iso2_clean, category)
    
    # 1. Custom JSON Check
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")

    # 2. Embedded Authentic Database
    if iso2_clean in WORLD_DATASETS and category in WORLD_DATASETS[iso2_clean]:
        return WORLD_DATASETS[iso2_clean][category]

    # 3. Empty Fallback -> Correctly displays "No Data Available"
    return []

def save_country_data(iso2: str, category: str, data: list):
    iso2_clean = resolve_iso2(iso2)
    path = get_country_file_path(iso2_clean, category)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving {path}: {e}")

async def fetch_dynamic_vertical(country_code: str, vertical: str) -> list:
    return load_country_data(country_code, vertical)

def load_country_pricing(iso2: str) -> dict:
    iso2_clean = resolve_iso2(iso2)
    path = get_country_file_path(iso2_clean, "pricing")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {int(k): float(v) for k, v in json.load(f).items()}
        except Exception:
            pass
    return dict(LEADS_PRICING)

def save_country_pricing(iso2: str, pricing_dict: dict):
    iso2_clean = resolve_iso2(iso2)
    path = get_country_file_path(iso2_clean, "pricing")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pricing_dict, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving pricing {path}: {e}")

def get_category_pricing_dict(cc):
    return load_country_pricing(cc)

def get_pricing_tiers(cc: str):
    pricing = load_country_pricing(cc)
    return sorted([(int(k), float(v)) for k, v in pricing.items()], key=lambda x: x[0])

# ── Storage & Maintenance ─────────────────────────────────────────────────────
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
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        logger.error(f"save_data failed: {e}")

def load_data():
    global user_balances, agreed_users, user_join_dates, channel_verified, live_stock, STORE
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

# ── Keyboards & Navigation Controls ──────────────────────────────────────────

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

def a_z_country_keyboard(page: int = 0, filtered_list: list = None):
    source_list = filtered_list if filtered_list is not None else ALL_COUNTRIES
    total_pages = max(1, (len(source_list) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    
    page_items = source_list[page * COUNTRIES_PER_PAGE : (page + 1) * COUNTRIES_PER_PAGE]
    rows = []
    
    rows.append([InlineKeyboardButton("🔍 Search Countries", callback_data="c_search_prompt")])
    
    for i in range(0, len(page_items), 2):
        row = []
        for c in page_items[i:i+2]:
            flag = get_country_flag(c.alpha_2)
            name = c.name if len(c.name) <= 18 else c.name[:16] + ".."
            row.append(InlineKeyboardButton(f"{flag} {name}", callback_data=f"c_dash|{c.alpha_2}"))
        rows.append(row)
        
    nav = []
    cb_prefix = "az_search_list" if filtered_list is not None else "az_list"
    if page > 0: nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"{cb_prefix}|{page-1}"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"{cb_prefix}|{page+1}"))
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
            name_display = name if len(name) <= 22 else name[:19] + "..."
            stock = item.get("stock", 0)
            price = item.get("price", 15.0)
            row.append(InlineKeyboardButton(f"{name_display} ({stock:,})", callback_data=f"c_item|{iso2}|{vertical}|{name}|{price}"))
        rows.append(row)

    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"c_page|{iso2}|{vertical}|{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 Page {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"c_page|{iso2}|{vertical}|{page+1}"))
    rows.append(nav_row)
    
    rows.append([
        InlineKeyboardButton("🔍 Search", callback_data=f"c_search|{iso2}|{vertical}"),
        InlineKeyboardButton("⬅️ Back", callback_data=f"c_dash|{iso2}")
    ])
    return InlineKeyboardMarkup(rows)

def dynamic_qty_keyboard(iso2: str, vertical: str, item_name: str, base_price: float):
    rows = []
    tiers = get_pricing_tiers(iso2)
    for i in range(0, len(tiers), 2):
        row = []
        for qty, price in tiers[i:i+2]:
            k = f"{qty//1000}k" if qty >= 1000 else str(qty)
            row.append(InlineKeyboardButton(f"{k} — £{price:g}", callback_data=f"c_buy|{iso2}|{vertical}|{item_name}|{qty}|{price}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"c_vert|{iso2}|{vertical}")])
    return InlineKeyboardMarkup(rows)

# ── Old Static Keyboards (Untouched) ──────────────────────────────────────────

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
    tab_row = [InlineKeyboardButton(f"› {label}" if key == cat else label, callback_data=f"scan|{key}|0") for key, label in {"all":"All","socials":"Socials","crypto":"Crypto","shopping":"Shop","carrier":"Carrier"}.items()]
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
            [InlineKeyboardButton("👤 Message Admin",   url=f"https://t.me/{SUPER_ADMIN}")],
            [InlineKeyboardButton("🔹 Message Support", url=f"https://t.me/{SUPPORT_USER}")],
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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")]]),
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

    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty", "awaiting_search", "awaiting_country_search"):
        context.user_data.pop(_k, None)

    # ── Universal A–Z Country Directory & Navigation ─────────────────────────
    if data == "leads":
        context.user_data["current_country_list"] = None
        await query.edit_message_text("🌍 *A–Z Sovereign Country Directory*\n_Page 1_\nSelect a nation:", reply_markup=a_z_country_keyboard(0), parse_mode="Markdown")
        return

    if data == "c_search_prompt":
        context.user_data["awaiting_country_search"] = True
        prompt_text = (
            "🌍 *Search Countries*\n\n"
            "Enter any country name to search.\n\n"
            "*Examples:*\n"
            "• UNITED KINGDOM\n"
            "• UNITED STATES\n"
            "• NIGERIA\n"
            "• SOUTH AFRICA\n"
            "• BANGLADESH\n"
            "• BRAZIL"
        )
        await query.edit_message_text(
            prompt_text, 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cancel", callback_data="leads")]]), 
            parse_mode="Markdown"
        )
        return

    if data.startswith("az_list|"):
        page = int(data.split("|")[1])
        context.user_data["current_country_list"] = None
        await query.edit_message_text(f"🌍 *A–Z Sovereign Country Directory*\n_Page {page+1}_\nSelect a nation:", reply_markup=a_z_country_keyboard(page), parse_mode="Markdown")
        return

    if data.startswith("az_search_list|"):
        page = int(data.split("|")[1])
        filtered = context.user_data.get("current_country_list", ALL_COUNTRIES)
        await query.edit_message_text(f"🔍 *Country Search Results*\n_Page {page+1}_\nSelect a nation:", reply_markup=a_z_country_keyboard(page, filtered), parse_mode="Markdown")
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
            if vertical == "crypto":
                empty_msg = "No Crypto Exchanges Available"
            elif vertical == "nodes":
                empty_msg = "No Records Available"
            else:
                empty_msg = "No Data Available"
                
            await query.edit_message_text(
                f"{flag} *{c_name} ➔ {vertical.title()}*\n\n⚠️ *{empty_msg}*", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"c_dash|{iso2}")]]), 
                parse_mode="Markdown"
            )
            return

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
            f"🔍 *Search {vertical.title()}*\n\nType the name of the bank, exchange, or provider you are looking for (restricted strictly to this country dataset):", 
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
        
        items = load_country_data(iso2, vertical)
        for item in items:
            if item["name"] == item_name:
                item["stock"] = max(0, item.get("stock", 0) - qty)
                break
        save_country_data(iso2, vertical, items)
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
    # Country Search Handling
    if context.user_data.get("awaiting_country_search"):
        query_text = update.message.text.strip().lower()
        context.user_data["awaiting_country_search"] = False
        
        filtered_countries = [c for c in ALL_COUNTRIES if query_text in c.name.lower() or query_text == c.alpha_2.lower()]
        
        if not filtered_countries:
            await update.message.reply_text(
                f"⚠️ No matching country found for '{query_text}'. Please try another name.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Directory", callback_data="leads")]]),
                parse_mode="Markdown"
            )
            return
            
        context.user_data["current_country_list"] = filtered_countries
        await update.message.reply_text(
            f"🔍 *Country Search Results for \"{query_text}\"* ({len(filtered_countries)} found):",
            reply_markup=a_z_country_keyboard(0, filtered_countries),
            parse_mode="Markdown"
        )
        return

    # Strict Country-Scoped Entity Search
    if context.user_data.get("awaiting_search"):
        query_text = update.message.text.strip().lower()
        iso2, vertical = context.user_data.get("search_target", ("US", "bank"))
        context.user_data["awaiting_search"] = False

        items = context.user_data.get(f"items_{iso2}_{vertical}")
        if not items: items = await fetch_dynamic_vertical(iso2, vertical)

        filtered = [item for item in items if query_text in item["name"].lower()]

        c = pycountry.countries.get(alpha_2=iso2)
        c_name = c.name if c else iso2

        if not filtered:
            await update.message.reply_text(
                f"❌ No matching results found for *\"{query_text}\"* within the {c_name} {vertical} dataset.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Category", callback_data=f"c_vert|{iso2}|{vertical}")]]), 
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text(
            f"🔍 *Search Results for \"{query_text}\" in {c_name}* ({len(filtered)} found):", 
            reply_markup=paginated_entity_keyboard(iso2, vertical, filtered, page=0), 
            parse_mode="Markdown"
        )
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
    "`/setprice <ISO2> <Quantity> <Price>`\n"
    "`/resetprice <ISO2>`\n"
    "Example: `/setprice AU 1000 25`\n\n"
    "*Balance Management*\n"
    "`/addbalance <user_id> <amount>`\n"
    "`/removebalance <user_id> <amount>`\n"
    "`/setbalance <user_id> <amount>`\n"
    "`/checkbalance <user_id>`\n\n"
    "*Leads & Stock*\n"
    "`/updatelead <ISO2> <subcat: crypto|bank|business|network> <ItemName> <stock>`\n"
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
        iso2 = context.args[0].upper()
        qty = int(context.args[1])
        price = float(context.args[2])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setprice <ISO2> <Quantity> <Price>\nExample: `/setprice US 1000 15`", parse_mode="Markdown")
        return
    
    pricing = load_country_pricing(iso2)
    pricing[qty] = price
    save_country_pricing(iso2, pricing)

    c = pycountry.countries.get(alpha_2=iso2)
    c_name = c.name if c else iso2
    await update.message.reply_text(
        f"✅ Updated pricing for *{get_country_flag(iso2)} {c_name}*:\n"
        f"• *{qty:,} items* → *£{price:g}*",
        parse_mode="Markdown"
    )

async def cmd_resetprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: iso2 = context.args[0].upper()
    except IndexError: await update.message.reply_text("Usage: /resetprice <ISO2>", parse_mode="Markdown"); return
    
    path = get_country_file_path(iso2, "pricing")
    if os.path.exists(path):
        os.remove(path)
        
    c = pycountry.countries.get(alpha_2=iso2)
    c_name = c.name if c else iso2
    await update.message.reply_text(f"✅ Pricing for *{get_country_flag(iso2)} {c_name}* reset to default.", parse_mode="Markdown")

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
        iso2 = context.args[0].upper()
        vertical = context.args[1].lower()
        item_name = context.args[2]
        stock = int(context.args[3])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /updatelead <ISO2> <vertical: crypto|bank|business|network> <ItemName> <stock>\nExample: `/updatelead AU network Telstra 5000000`", parse_mode="Markdown")
        return
    
    items = load_country_data(iso2, vertical)
    found = False
    for item in items:
        if item["name"].lower() == item_name.lower():
            item["stock"] = stock
            found = True
            break
            
    if not found and stock > 0:
        items.append({"name": item_name, "stock": stock, "price": 15.0})
        
    if stock <= 0:
        items = [i for i in items if i["name"].lower() != item_name.lower()]
        
    save_country_data(iso2, vertical, items)
    
    c = pycountry.countries.get(alpha_2=iso2)
    c_name = c.name if c else iso2
    await update.message.reply_text(f"✅ Updated *{item_name}* → *{stock:,}* in {c_name} ({vertical.title()})", parse_mode="Markdown")

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

# ── Main Engine Initialization ────────────────────────────────────────────────

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
