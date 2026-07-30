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
pending_orders      = {}   # uid → delivery caption stored after each purchase
delivery_timestamps = {}   # uid → datetime (UTC) when order file was delivered to user

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

# ── Scanner Items ─────────────────────────────────────────────────────────────
SCANNER_ITEMS = [
    ("Binance · Email",       "crypto",   30.00),
    ("Binance · Filter",      "crypto",   30.50),
    ("CoinW · Email",         "crypto",   25.50),
    ("CoinW · Mobile",        "crypto",   25.50),
    ("HTX · Email",           "crypto",   25.50),
    ("HTX · Mobile",          "crypto",   25.50),
    ("KuCoin · Email",        "crypto",   30.50),
    ("KuCoin · Mobile",       "crypto",   30.00),
    ("OKX · Filter",          "crypto",   30.00),
    ("Robinhood · Check",     "crypto",   15.50),
    ("Facebook · Email",      "socials",   4.00),
    ("Instagram · Mobile",    "socials",   5.00),
    ("LinkedIn · Profile",    "socials",  20.00),
    ("Signal",                "socials",   5.00),
    ("Snapchat",              "socials",   5.00),
    ("iMessage · Filter",     "socials",   3.35),
    ("DHL",                   "shopping", 11.50),
    ("Shein",                 "shopping", 15.00),
    ("Carrier · Any",         "carrier",   5.50),
    ("Carrier · UK",          "carrier",   7.75),
    ("Carrier · US",          "carrier",   6.75),
]
SCANNER_PER_PAGE = 10
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]

LEADS_PRICING = [
    (1_000,   15),  (2_000,  30),  (3_000,   45),  (4_000,  50),
    (5_000,   60),  (6_000,  65),  (7_000,   70),  (8_000,  80),
    (10_000, 100),  (15_000,125),  (20_000, 150),  (25_000,175),
    (30_000, 200),  (50_000,300),  (100_000,600),
]

# ── Per-vertical pricing (edit each independently) ────────────────────────────
CRYPTO_VERT_PRICING = [
    (1_000,   200),  (2_000,  395),  (3_000,  590),  (4_000,   785),
    (5_000,   800),  (6_000,  990),  (7_000, 1190),  (8_000,  1380),
    (10_000, 1500),  (15_000,2300),  (20_000,2300),  (25_000, 3450),
    (30_000, 4200),  (50_000,5900),  (100_000,10000),
]

BANKS_VERT_PRICING = [
    (1_000,    90),  (2_000,  175),  (3_000,  260),  (4_000,   345),
    (5_000,   350),  (6_000,  435),  (7_000,  525),  (8_000,   610),
    (10_000,  660),  (15_000,1010),  (20_000,1010),  (25_000, 1515),
    (30_000, 1845),  (50_000,2595),  (100_000,4400),
]

BIZ_VERT_PRICING = [
    (1_000,    60),  (2_000,  115),  (3_000,  170),  (4_000,   225),
    (5_000,   230),  (6_000,  285),  (7_000,  345),  (8_000,   400),
    (10_000,  435),  (15_000, 665),  (20_000, 665),  (25_000,  995),
    (30_000, 1215),  (50_000,1705),  (100_000,2890),
]

SIM_VERT_PRICING = [
    (1_000,    25),  (2_000,   48),  (3_000,   71),  (4_000,    94),
    (5_000,    96),  (6_000,  119),  (7_000,  144),  (8_000,   167),
    (10_000,  181),  (15_000, 277),  (20_000, 277),  (25_000,  415),
    (30_000,  506),  (50_000, 711),  (100_000,1205),
]

LEDGER_VERT_PRICING = [
    (1_000,    250),  (2_000,   480),  (3_000,   710),  (4_000,    940),
    (5_000,    960),  (6_000,  1190),  (7_000,  1440),  (8_000,   1670),
    (10_000,  1810),  (15_000, 2770),  (20_000, 2770),  (25_000,  4150),
    (30_000,  5060),  (50_000, 7110),  (100_000,12050),
]

VERT_PRICING = {
    "crypto": CRYPTO_VERT_PRICING,
    "banks":  BANKS_VERT_PRICING,
    "biz":    BIZ_VERT_PRICING,
    "sim":    SIM_VERT_PRICING,
    "ledger": LEDGER_VERT_PRICING,
}

# ══════════════════════════════════════════════════════════════════════════════
# LEADS — Full dataset for all 44 countries, 5 verticals each.
# NO generic placeholders. All carrier/bank/crypto/biz data is authentic.
# ══════════════════════════════════════════════════════════════════════════════
LEADS = {

    # ── Australia ────────────────────────────────────────────────────────────
    "AU": {
        "flag": "🇦🇺", "name": "Australia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "AMP Bank":                     210_000,
                    "ANZ Bank":                   1_250_000,
                    "Bank of Queensland":           420_000,
                    "BankSA":                       310_000,
                    "Bankwest":                     380_000,
                    "Bendigo Bank":                 510_000,
                    "Commonwealth Bank (CBA)":    3_100_000,
                    "HSBC Australia":               290_000,
                    "ING Australia":                620_000,
                    "Macquarie Bank":               890_000,
                    "ME Bank":                      180_000,
                    "National Australia Bank (NAB)":2_400_000,
                    "Suncorp Bank":                 450_000,
                    "Westpac":                    2_800_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance AU":          1_100_000,
                    "BTC Markets":           450_000,
                    "CoinJar":               320_000,
                    "CoinSpot":            1_500_000,
                    "Coinbase AU":           890_000,
                    "Crypto.com AU":         760_000,
                    "Independent Reserve":   340_000,
                    "Kraken AU":             520_000,
                    "Swyftx":                980_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "ABR Registered Entities":   1_400_000,
                    "ASIC Corporate Index":       2_100_000,
                    "GST Registered Businesses":  1_800_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telstra":      4_200_000,
                    "Optus":        3_100_000,
                    "Vodafone AU":  1_800_000,
                    "Boost Mobile":   620_000,
                    "TPG":            430_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Validator Nodes AU":  120_000,
                    "Ethereum Staking Index AU":   340_000,
                    "Solana RPC Nodes AU":         210_000,
                },
            },
        },
    },

    # ── Austria ──────────────────────────────────────────────────────────────
    "AT": {
        "flag": "🇦🇹", "name": "Austria",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Bank Austria (UniCredit)": 1_200_000,
                    "Bawag P.S.K.":              760_000,
                    "Erste Bank":              1_800_000,
                    "Hypo Vorarlberg":           180_000,
                    "N26 AT":                    540_000,
                    "Raiffeisen Bank AT":       2_100_000,
                    "Volksbank AT":              420_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance AT":   480_000,
                    "Bitpanda":     920_000,
                    "Coinbase AT":  310_000,
                    "Kraken AT":    210_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Firmenbuch (Austrian Business Register)": 980_000,
                    "WKO Member Entities":                     760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "A1":      1_540_000,
                    "Magenta":   890_000,
                    "Drei":      760_000,
                    "Spusu":     210_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes AT":       42_000,
                    "Ethereum Stakers AT":    95_000,
                },
            },
        },
    },

    # ── Bahrain ──────────────────────────────────────────────────────────────
    "BH": {
        "flag": "🇧🇭", "name": "Bahrain",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Ahli United Bank":   310_000,
                    "Al Salam Bank":      180_000,
                    "Arab Bank BH":       140_000,
                    "Bank of Bahrain":    420_000,
                    "Gulf International Bank": 95_000,
                    "HSBC Bahrain":       210_000,
                    "Ithmaar Bank":       160_000,
                    "National Bank of Bahrain": 380_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance BH":     180_000,
                    "CoinMENA":       120_000,
                    "Rain Financial":  95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Ministry of Industry & Commerce Entities": 210_000,
                    "Bahrain CR Registered Firms":              180_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Batelco":   480_000,
                    "Zain BH":   390_000,
                    "STC BH":    210_000,
                    "Viva BH":   170_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes BH":    12_000,
                    "Ethereum Stakers BH": 28_000,
                },
            },
        },
    },

    # ── Belgium ──────────────────────────────────────────────────────────────
    "BE": {
        "flag": "🇧🇪", "name": "Belgium",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Argenta":          680_000,
                    "AXA Bank BE":      420_000,
                    "Belfius":        1_900_000,
                    "BNP Paribas Fortis": 2_400_000,
                    "Bpost Bank":       540_000,
                    "Crelan":           380_000,
                    "ING Belgium":    1_600_000,
                    "KBC Bank":       2_100_000,
                    "Nagelmackers":     160_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance BE":   620_000,
                    "Bit4You":       95_000,
                    "Bitlocus BE":   72_000,
                    "Coinbase BE":  480_000,
                    "Kraken BE":    310_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Crossroads Bank for Enterprises": 1_200_000,
                    "Belgian VAT Registered Entities":   890_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Proximus":  1_920_000,
                    "Orange BE": 1_340_000,
                    "Base":        980_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes BE":      65_000,
                    "Ethereum Stakers BE":  140_000,
                },
            },
        },
    },

    # ── Brazil ───────────────────────────────────────────────────────────────
    "BR": {
        "flag": "🇧🇷", "name": "Brazil",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Banco do Brasil":      8_200_000,
                    "Banco Inter":          3_400_000,
                    "Bradesco":             7_100_000,
                    "BTG Pactual":          1_200_000,
                    "C6 Bank":              2_100_000,
                    "Caixa Econômica":      9_800_000,
                    "Itaú Unibanco":       10_500_000,
                    "Nubank":              12_000_000,
                    "Santander BR":         5_600_000,
                    "XP Investimentos":     2_800_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance BR":    4_200_000,
                    "Bitso BR":        980_000,
                    "Bitcoin Market":  760_000,
                    "Coinbase BR":     540_000,
                    "Foxbit":          420_000,
                    "Mercado Bitcoin": 2_100_000,
                    "Novadax":         380_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "CNPJ Registered Entities":  18_000_000,
                    "Receita Federal Tax Base":  12_000_000,
                    "JUCESP Corporations":        4_200_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Vivo":   7_800_000,
                    "Claro":  6_500_000,
                    "TIM BR": 5_200_000,
                    "Oi":     2_100_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes BR":      380_000,
                    "Ethereum Stakers BR":   520_000,
                    "Solana Validators BR":  180_000,
                },
            },
        },
    },

    # ── Bulgaria ─────────────────────────────────────────────────────────────
    "BG": {
        "flag": "🇧🇬", "name": "Bulgaria",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Allianz Bank BG":   180_000,
                    "Bulgarian Development Bank": 95_000,
                    "DSK Bank":          940_000,
                    "First Investment Bank": 620_000,
                    "Municipal Bank":    210_000,
                    "Postbank BG":       540_000,
                    "Raiffeisenbank BG": 480_000,
                    "UniCredit BG":      760_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance BG":   320_000,
                    "Coinbase BG":  180_000,
                    "Nexo":         540_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Bulgarian Trade Register":  980_000,
                    "BULSTAT Registry":          760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "A1 BG":       1_100_000,
                    "Telenor BG":    890_000,
                    "Vivacom":       760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes BG":     28_000,
                    "Ethereum Stakers BG":  55_000,
                },
            },
        },
    },

    # ── Canada ───────────────────────────────────────────────────────────────
    "CA": {
        "flag": "🇨🇦", "name": "Canada",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "BMO Bank":                 1_500_000,
                    "CIBC":                     1_200_000,
                    "EQ Bank":                    480_000,
                    "HSBC Canada":                420_000,
                    "National Bank of Canada":    980_000,
                    "RBC Royal Bank":           2_500_000,
                    "Scotiabank":               1_800_000,
                    "Simplii Financial":          620_000,
                    "TD Bank":                  2_100_000,
                    "Tangerine":                  540_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Bitbuy":               210_000,
                    "Coinberry":            420_000,
                    "Coinbase CA":          760_000,
                    "Coinsquare":           310_000,
                    "Kraken CA":            520_000,
                    "NDAX":                 280_000,
                    "Newton":               380_000,
                    "Wealthsimple Crypto":  950_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Corporations Canada Federal":  1_800_000,
                    "Ontario Business Registry":    2_100_000,
                    "BC Registry Services":           980_000,
                    "Alberta Corporate Registry":     760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Rogers":  4_100_000,
                    "Bell":    3_800_000,
                    "Telus":   3_500_000,
                    "Fido":      980_000,
                    "Koodo":     760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes CA":      120_000,
                    "Ethereum Stakers CA":   210_000,
                    "Solana Validators CA":   85_000,
                },
            },
        },
    },

    # ── Cyprus ───────────────────────────────────────────────────────────────
    "CY": {
        "flag": "🇨🇾", "name": "Cyprus",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Alpha Bank Cyprus":   210_000,
                    "AstroBank":           180_000,
                    "Bank of Cyprus":      480_000,
                    "Eurobank Cyprus":     160_000,
                    "Hellenic Bank":       320_000,
                    "RCB Bank":             95_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance CY":   120_000,
                    "Coinbase CY":   80_000,
                    "eToro CY":     160_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Registrar of Companies CY":  420_000,
                    "VAT Registered Entities CY": 280_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Cyta":     340_000,
                    "MTN CY":   210_000,
                    "Epic CY":  180_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes CY":    8_500,
                    "Ethereum Stakers CY": 18_000,
                },
            },
        },
    },

    # ── Czech Republic ───────────────────────────────────────────────────────
    "CZ": {
        "flag": "🇨🇿", "name": "Czech Republic",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Air Bank":              420_000,
                    "Ceska Sporitelna":    2_100_000,
                    "CSOB":                1_800_000,
                    "Fio Bank":              540_000,
                    "Komerční banka":      1_600_000,
                    "mBank CZ":              310_000,
                    "Moneta Money Bank":     980_000,
                    "Raiffeisenbank CZ":     760_000,
                    "UniCredit CZ":          640_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Anycoin CZ":   210_000,
                    "Binance CZ":   480_000,
                    "Coinbase CZ":  280_000,
                    "Coinmate":     160_000,
                    "Kraken CZ":    180_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Czech Business Register (OR)": 1_200_000,
                    "ARES Registered Entities":     2_800_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "T-Mobile CZ":  2_100_000,
                    "O2 CZ":        1_800_000,
                    "Vodafone CZ":  1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes CZ":      78_000,
                    "Ethereum Stakers CZ":  145_000,
                },
            },
        },
    },

    # ── Denmark ──────────────────────────────────────────────────────────────
    "DK": {
        "flag": "🇩🇰", "name": "Denmark",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Arbejdernes Landsbank": 380_000,
                    "Danske Bank":         2_400_000,
                    "Jyske Bank":            920_000,
                    "Lunar Bank":            340_000,
                    "Nordea DK":           1_600_000,
                    "Nykredit":              760_000,
                    "Spar Nord":             420_000,
                    "Sydbank":               540_000,
                    "Vestjysk Bank":         210_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance DK":   380_000,
                    "Coinbase DK":  290_000,
                    "Kraken DK":    210_000,
                    "MyCointainer":  95_000,
                    "NordikCoin":    72_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Danish CVR Business Register": 1_100_000,
                    "SKAT Registered Entities":       760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "TDC":      1_540_000,
                    "Telenor DK": 1_100_000,
                    "Telia DK":   980_000,
                    "Tre DK":     760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes DK":     52_000,
                    "Ethereum Stakers DK": 110_000,
                },
            },
        },
    },

    # ── Estonia ──────────────────────────────────────────────────────────────
    "EE": {
        "flag": "🇪🇪", "name": "Estonia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Coop Pank":      180_000,
                    "LHV Bank":       310_000,
                    "Luminor EE":     420_000,
                    "SEB EE":         540_000,
                    "Swedbank EE":    680_000,
                    "Bigbank EE":     120_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance EE":   210_000,
                    "Coinbase EE":  140_000,
                    "Kraken EE":     95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Estonian Business Register":  380_000,
                    "e-Residency Company Index":   120_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telia EE":  430_000,
                    "Elisa EE":  380_000,
                    "Tele2 EE":  290_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes EE":    18_000,
                    "Ethereum Stakers EE": 42_000,
                },
            },
        },
    },

    # ── Finland ──────────────────────────────────────────────────────────────
    "FI": {
        "flag": "🇫🇮", "name": "Finland",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Aktia Bank":          310_000,
                    "Ålandsbanken":         95_000,
                    "Danske Bank FI":      420_000,
                    "Handelsbanken FI":    380_000,
                    "Nordea FI":         1_800_000,
                    "OP Cooperative":    3_200_000,
                    "POP Bank":            210_000,
                    "S-Bank":              540_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance FI":   480_000,
                    "Coinbase FI":  280_000,
                    "Coinmotion":    95_000,
                    "Kraken FI":    180_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Finnish Trade Register (PRH)": 980_000,
                    "YTJ Business Registry":        760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Elisa FI": 1_800_000,
                    "DNA FI":   1_500_000,
                    "Telia FI": 1_200_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes FI":     62_000,
                    "Ethereum Stakers FI": 130_000,
                },
            },
        },
    },

    # ── France ───────────────────────────────────────────────────────────────
    "FR": {
        "flag": "🇫🇷", "name": "France",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "BNP Paribas":         7_200_000,
                    "Boursorama":          3_400_000,
                    "CIC":                 2_800_000,
                    "Crédit Agricole":     8_100_000,
                    "Crédit Mutuel":       6_500_000,
                    "Fortuneo":              540_000,
                    "Hello bank!":           760_000,
                    "La Banque Postale":   4_200_000,
                    "LCL":                 2_100_000,
                    "Lydia":               1_200_000,
                    "N26 FR":                980_000,
                    "Revolut FR":          2_400_000,
                    "Société Générale":    5_900_000,
                    "Sumeria (Lydia)":       640_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance FR":    2_400_000,
                    "Bitpanda FR":     380_000,
                    "Coinbase FR":   1_600_000,
                    "Coinhouse":       320_000,
                    "Kraken FR":       760_000,
                    "Paymium":         180_000,
                    "Swissborg FR":    420_000,
                    "Zebitex":         140_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "INPI SIRENE Register":      4_800_000,
                    "French VAT (TVA) Entities": 3_200_000,
                    "Registre du Commerce (RCS)":2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Orange FR":      6_200_000,
                    "SFR":            4_800_000,
                    "Bouygues":       4_100_000,
                    "Free Mobile":    3_500_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes FR":      320_000,
                    "Ethereum Stakers FR":   540_000,
                    "Solana Validators FR":  180_000,
                },
            },
        },
    },

    # ── Germany ──────────────────────────────────────────────────────────────
    "DE": {
        "flag": "🇩🇪", "name": "Germany",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Commerzbank":       4_200_000,
                    "Comdirect":         1_800_000,
                    "Deutsche Bank":     7_600_000,
                    "DKB":               2_400_000,
                    "ING-DiBa DE":       3_200_000,
                    "N26":               2_100_000,
                    "Postbank":          3_800_000,
                    "Revolut DE":        1_400_000,
                    "Santander DE":      1_100_000,
                    "Sparkasse":        11_000_000,
                    "Volksbank/Raiffeisenbank": 9_400_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance DE":    3_400_000,
                    "Bitstamp DE":     420_000,
                    "Bitpanda DE":     890_000,
                    "Coinbase DE":   2_100_000,
                    "Kraken DE":     1_200_000,
                    "Nuri (old)":      340_000,
                    "Trade Republic":1_800_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Handelsregister (HRB)":        4_200_000,
                    "German VAT (USt-IdNr.) Entities":3_800_000,
                    "Bundesanzeiger Entities":       2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telekom DE":  8_900_000,
                    "Vodafone DE": 7_200_000,
                    "O2 DE":       5_800_000,
                    "1&1":         1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes DE":      680_000,
                    "Ethereum Stakers DE": 1_200_000,
                    "Solana Validators DE":  320_000,
                },
            },
        },
    },

    # ── Greece ───────────────────────────────────────────────────────────────
    "GR": {
        "flag": "🇬🇷", "name": "Greece",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Alpha Bank":       1_200_000,
                    "Attica Bank":        280_000,
                    "Eurobank":         1_400_000,
                    "National Bank of Greece": 1_800_000,
                    "Piraeus Bank":     1_600_000,
                    "Viva Wallet GR":     420_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance GR":   480_000,
                    "Coinbase GR":  280_000,
                    "Kraken GR":    160_000,
                    "Liquid GR":     95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "GEMI Greek Business Registry": 1_100_000,
                    "TAXIS Registered Entities":      760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Cosmote":      2_800_000,
                    "Vodafone GR":  1_900_000,
                    "Wind Hellas":  1_400_000,
                    "Nova GR":        680_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes GR":     48_000,
                    "Ethereum Stakers GR":  95_000,
                },
            },
        },
    },

    # ── Hungary ──────────────────────────────────────────────────────────────
    "HU": {
        "flag": "🇭🇺", "name": "Hungary",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Budapest Bank":    540_000,
                    "CIB Bank HU":      480_000,
                    "Erste Bank HU":    760_000,
                    "K&H Bank":         640_000,
                    "Magyar Takarék":   380_000,
                    "MKB Bank":         420_000,
                    "OTP Bank":       3_200_000,
                    "Raiffeisen HU":    540_000,
                    "UniCredit HU":     680_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance HU":    380_000,
                    "Coinbase HU":   210_000,
                    "Kraken HU":     120_000,
                    "Coinberry HU":   75_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Hungarian Company Information (Céginfo)": 980_000,
                    "NAV Tax Registered Entities":             760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telekom HU": 2_100_000,
                    "Yettel HU":  1_400_000,
                    "Vodafone HU":  980_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes HU":     42_000,
                    "Ethereum Stakers HU":  88_000,
                },
            },
        },
    },

    # ── Iceland ──────────────────────────────────────────────────────────────
    "IS": {
        "flag": "🇮🇸", "name": "Iceland",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Arion Bank":     180_000,
                    "Íslandsbanki":   160_000,
                    "Kvika Bank":      45_000,
                    "Landsbankinn":   210_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance IS":    45_000,
                    "Coinbase IS":   28_000,
                    "Mimir IS":      18_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Firmaskrá (IS Company Register)": 95_000,
                    "RSK (Tax Authority Register)":    72_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Siminn IS":  180_000,
                    "Vodafone IS":140_000,
                    "Nova IS":    110_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes IS":    8_200,
                    "Ethereum Stakers IS": 16_000,
                },
            },
        },
    },

    # ── Ireland ──────────────────────────────────────────────────────────────
    "IE": {
        "flag": "🇮🇪", "name": "Ireland",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "AIB (Allied Irish Banks)": 1_900_000,
                    "An Post Money":              310_000,
                    "Bank of Ireland":          2_100_000,
                    "EBS":                        420_000,
                    "KBC Ireland":                540_000,
                    "N26 IE":                     380_000,
                    "Permanent TSB":              760_000,
                    "Revolut IE":               1_200_000,
                    "Ulster Bank":                680_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance IE":   480_000,
                    "BitIreland":    62_000,
                    "Coinbase IE":  620_000,
                    "Kraken IE":    280_000,
                    "eToro IE":     310_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Companies Registration Office (CRO)": 980_000,
                    "Irish Revenue Tax Entities":          760_000,
                    "Revenue VAT Registered Entities":     540_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Eir":          833_503,
                    "Tesco Mobile IE": 520_700,
                    "Three IE A":   351_645,
                    "Three IE B":   861_444,
                    "Vodafone IE":1_720_550,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes IE":     62_000,
                    "Ethereum Stakers IE": 140_000,
                },
            },
        },
    },

    # ── Italy ────────────────────────────────────────────────────────────────
    "IT": {
        "flag": "🇮🇹", "name": "Italy",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Banco BPM":             2_100_000,
                    "Banca Mediolanum":      1_200_000,
                    "Banca Sella":             540_000,
                    "BPER Banca":            1_400_000,
                    "Chebanca!":               380_000,
                    "Crédit Agricole IT":    1_100_000,
                    "Fineco Bank":           1_600_000,
                    "Hype":                    760_000,
                    "Intesa Sanpaolo":      10_200_000,
                    "N26 IT":                  980_000,
                    "Revolut IT":            1_800_000,
                    "Unicredit IT":          7_400_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance IT":    1_900_000,
                    "Bitfinex IT":     420_000,
                    "Coinbase IT":   1_200_000,
                    "Kraken IT":       760_000,
                    "Young Platform":  540_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Registro Imprese CCIAA":  4_800_000,
                    "Italian VAT (P.IVA) Entities": 3_200_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "TIM":          5_900_000,
                    "Vodafone IT":  4_200_000,
                    "WindTre":      5_100_000,
                    "Iliad IT":     1_800_000,
                    "PosteMobile":    890_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes IT":      280_000,
                    "Ethereum Stakers IT":   480_000,
                    "Solana Validators IT":  160_000,
                },
            },
        },
    },

    # ── Latvia ───────────────────────────────────────────────────────────────
    "LV": {
        "flag": "🇱🇻", "name": "Latvia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Citadele Bank":  280_000,
                    "Luminor LV":     340_000,
                    "Rietumu Bank":   160_000,
                    "SEB LV":         420_000,
                    "Swedbank LV":    540_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance LV":   180_000,
                    "Coinbase LV":  110_000,
                    "Kraken LV":     75_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Latvian Enterprise Register":  280_000,
                    "VID Tax Entities":             210_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "LMT":      540_000,
                    "Tele2 LV": 430_000,
                    "Bite LV":  320_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes LV":    12_000,
                    "Ethereum Stakers LV": 28_000,
                },
            },
        },
    },

    # ── Lithuania ────────────────────────────────────────────────────────────
    "LT": {
        "flag": "🇱🇹", "name": "Lithuania",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Luminor LT":     480_000,
                    "Medicinos Bankas": 120_000,
                    "Revolut LT":     380_000,
                    "SEB LT":         620_000,
                    "Šiaulių Bankas": 210_000,
                    "Swedbank LT":    760_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance LT":   280_000,
                    "Coinbase LT":  160_000,
                    "Coingate LT":  120_000,
                    "Kraken LT":     95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Lithuanian JAR Register":  420_000,
                    "VMI Tax Registered Entities": 380_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Tele2 LT": 890_000,
                    "Bite LT":  760_000,
                    "Telia LT": 540_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes LT":    18_000,
                    "Ethereum Stakers LT": 38_000,
                },
            },
        },
    },

    # ── Malaysia ─────────────────────────────────────────────────────────────
    "MY": {
        "flag": "🇲🇾", "name": "Malaysia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Affin Bank":      540_000,
                    "Alliance Bank":   760_000,
                    "AmBank":          980_000,
                    "CIMB Bank":     3_800_000,
                    "Hong Leong Bank": 1_600_000,
                    "Maybank":        6_200_000,
                    "OCBC Malaysia":   980_000,
                    "Public Bank":    3_200_000,
                    "RHB Bank":       2_100_000,
                    "Standard Chartered MY": 640_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance MY":    980_000,
                    "Coinbase MY":   420_000,
                    "Luno MY":     1_200_000,
                    "MX Global":     210_000,
                    "SINEGY":        160_000,
                    "Tokenize MY":   280_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "SSM Registered Companies":   2_400_000,
                    "LHDN Tax Entities":          1_800_000,
                    "MyCoID Company Index":         980_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Maxis":    4_200_000,
                    "Digi":     3_800_000,
                    "Celcom":   3_100_000,
                    "U Mobile": 1_400_000,
                    "Unifi MY":   980_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes MY":     120_000,
                    "Ethereum Stakers MY":  210_000,
                    "Solana Validators MY":  85_000,
                },
            },
        },
    },

    # ── Malta ────────────────────────────────────────────────────────────────
    "MT": {
        "flag": "🇲🇹", "name": "Malta",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "APS Bank":         95_000,
                    "Bank of Valletta": 210_000,
                    "FIMBank":           62_000,
                    "HSBC Malta":       160_000,
                    "Lombard Bank":      72_000,
                    "Revolut MT":       120_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance MT":    95_000,
                    "Coinbase MT":   62_000,
                    "OKX MT":        48_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "MFSA Registry of Companies": 120_000,
                    "Malta Tax & Customs (CFR)":   88_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "GO Malta":    180_000,
                    "Melita":      140_000,
                    "Epic MT":     110_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes MT":    4_800,
                    "Ethereum Stakers MT": 9_500,
                },
            },
        },
    },

    # ── Netherlands ──────────────────────────────────────────────────────────
    "NL": {
        "flag": "🇳🇱", "name": "Netherlands",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "ABN AMRO":            3_800_000,
                    "ASN Bank":              420_000,
                    "bunq":                  680_000,
                    "ING Netherlands":     5_200_000,
                    "Knab":                  310_000,
                    "N26 NL":                480_000,
                    "Rabobank":            5_800_000,
                    "Revolut NL":          1_100_000,
                    "RegioBank":             280_000,
                    "SNS Bank":              760_000,
                    "Triodos Bank":          380_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Bitvavo":           1_200_000,
                    "Binance NL":          980_000,
                    "Bitonic":             280_000,
                    "Coinbase NL":         760_000,
                    "Kraken NL":           480_000,
                    "Satos":               160_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "KVK Dutch Chamber of Commerce": 2_800_000,
                    "Dutch VAT (BTW) Entities":      2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "KPN":             3_200_000,
                    "VodafoneZiggo":   2_800_000,
                    "T-Mobile NL":     2_100_000,
                    "Tele2 NL":          890_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes NL":      210_000,
                    "Ethereum Stakers NL":   380_000,
                    "Solana Validators NL":  120_000,
                },
            },
        },
    },

    # ── New Zealand ──────────────────────────────────────────────────────────
    "NZ": {
        "flag": "🇳🇿", "name": "New Zealand",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "ANZ NZ":              1_400_000,
                    "ASB Bank":            1_100_000,
                    "Bank of New Zealand": 1_200_000,
                    "Heartland Bank":        160_000,
                    "Kiwibank":              680_000,
                    "Rabobank NZ":           120_000,
                    "TSB Bank NZ":           210_000,
                    "Westpac NZ":            980_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance NZ":      380_000,
                    "BitPrime":         95_000,
                    "Coinbase NZ":     280_000,
                    "Easy Crypto NZ":  420_000,
                    "Kraken NZ":       160_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "NZ Companies Office Register":  680_000,
                    "IRD GST Registered Entities":   540_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Spark NZ": 1_800_000,
                    "One NZ":   1_400_000,
                    "2degrees":   980_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes NZ":    28_000,
                    "Ethereum Stakers NZ": 55_000,
                },
            },
        },
    },

    # ── Norway ───────────────────────────────────────────────────────────────
    "NO": {
        "flag": "🇳🇴", "name": "Norway",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "DNB Bank":        3_400_000,
                    "Handelsbanken NO":  380_000,
                    "Nordea NO":       2_100_000,
                    "Sbanken":           540_000,
                    "SpareBank 1":     2_800_000,
                    "Sparebanken Vest":  620_000,
                    "Storebrand Bank":   310_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance NO":     480_000,
                    "Coinbase NO":    310_000,
                    "Firi (Miraiex)": 160_000,
                    "Kraken NO":      210_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Brønnøysund Register Centre": 980_000,
                    "Skatteetaten Entities":        760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telenor NO": 2_400_000,
                    "Telia NO":   1_800_000,
                    "Ice NO":       760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes NO":     82_000,
                    "Ethereum Stakers NO": 160_000,
                },
            },
        },
    },

    # ── Poland ───────────────────────────────────────────────────────────────
    "PL": {
        "flag": "🇵🇱", "name": "Poland",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Alior Bank":     1_200_000,
                    "Bank Millennium": 1_600_000,
                    "Bank Pekao":     3_800_000,
                    "BNP Paribas PL": 1_400_000,
                    "ING Bank PL":    2_800_000,
                    "mBank PL":       2_100_000,
                    "Nest Bank":        420_000,
                    "PKO Bank Polski": 8_400_000,
                    "Santander PL":   2_400_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance PL":    1_200_000,
                    "BitBay (Zonda)": 760_000,
                    "Coinbase PL":     480_000,
                    "Egera":           120_000,
                    "Kraken PL":       310_000,
                    "Kanga Exchange":  180_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "KRS National Court Register": 2_800_000,
                    "CEIDG Business Registry":     4_200_000,
                    "Polish VAT (NIP) Entities":   3_600_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Orange PL": 4_100_000,
                    "Play PL":   3_800_000,
                    "Plus PL":   3_200_000,
                    "T-Mobile PL": 2_900_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes PL":      180_000,
                    "Ethereum Stakers PL":   320_000,
                    "Solana Validators PL":   95_000,
                },
            },
        },
    },

    # ── Portugal ─────────────────────────────────────────────────────────────
    "PT": {
        "flag": "🇵🇹", "name": "Portugal",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Activobank":        320_000,
                    "Banco BPI":         980_000,
                    "Banco Montepio":    420_000,
                    "Bankinter PT":      540_000,
                    "Caixa Geral":     2_800_000,
                    "Millennium BCP":  2_100_000,
                    "N26 PT":            380_000,
                    "Novo Banco":      1_100_000,
                    "Revolut PT":        760_000,
                    "Santander PT":    1_400_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance PT":    480_000,
                    "Coinbase PT":   310_000,
                    "Criptoloja":     62_000,
                    "Kraken PT":     180_000,
                    "Luno PT":        95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "IRN Registo Comercial": 1_100_000,
                    "AT Portuguese Tax Register":  760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "NOS":         2_800_000,
                    "MEO":         2_400_000,
                    "Vodafone PT": 1_900_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes PT":     88_000,
                    "Ethereum Stakers PT": 160_000,
                },
            },
        },
    },

    # ── Puerto Rico ──────────────────────────────────────────────────────────
    "PR": {
        "flag": "🇵🇷", "name": "Puerto Rico",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Banco Popular de PR":  1_200_000,
                    "FirstBankPR":            540_000,
                    "Oriental Bank PR":       380_000,
                    "Eurobank PR":            160_000,
                    "Scotiabank PR":          280_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance PR":   210_000,
                    "Coinbase PR":  340_000,
                    "Gemini PR":    160_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Puerto Rico State Dept Corporations": 420_000,
                    "PR Treasury Tax Entities":            310_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Claro PR":    1_100_000,
                    "T-Mobile PR":   890_000,
                    "Liberty PR":    540_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes PR":    22_000,
                    "Ethereum Stakers PR": 48_000,
                },
            },
        },
    },

    # ── Qatar ────────────────────────────────────────────────────────────────
    "QA": {
        "flag": "🇶🇦", "name": "Qatar",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Al Khaliji Commercial Bank":  180_000,
                    "Ahli Bank QA":                210_000,
                    "Barwa Bank":                  280_000,
                    "Commercial Bank of Qatar":    540_000,
                    "Doha Bank":                   380_000,
                    "HSBC Qatar":                  160_000,
                    "Masraf Al Rayan":             420_000,
                    "Qatar Islamic Bank":          680_000,
                    "Qatar National Bank (QNB)":   980_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance QA":     180_000,
                    "CoinMENA QA":    120_000,
                    "Rain QA":         88_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Qatar MEC Business Registry":  320_000,
                    "QFC Registered Entities":      160_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Ooredoo QA":      980_000,
                    "Vodafone Qatar":  760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes QA":    22_000,
                    "Ethereum Stakers QA": 48_000,
                },
            },
        },
    },

    # ── Romania ──────────────────────────────────────────────────────────────
    "RO": {
        "flag": "🇷🇴", "name": "Romania",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Alpha Bank RO":         640_000,
                    "Banca Transilvania":  2_800_000,
                    "BRD (SocGen RO)":     1_800_000,
                    "CEC Bank":              980_000,
                    "Exim Bank RO":          320_000,
                    "ING Bank RO":         1_200_000,
                    "OTP Bank RO":           540_000,
                    "Raiffeisen RO":       1_400_000,
                    "UniCredit RO":          760_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance RO":     620_000,
                    "Coinbase RO":    310_000,
                    "Kraken RO":      180_000,
                    "Nexo RO":        420_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "ONRC Trade Register RO":  1_600_000,
                    "ANAF Tax Entities":       2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Orange RO":    3_200_000,
                    "Vodafone RO":  2_800_000,
                    "Digi RO":      2_100_000,
                    "Telekom RO":   1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes RO":      88_000,
                    "Ethereum Stakers RO":  160_000,
                },
            },
        },
    },

    # ── Singapore ────────────────────────────────────────────────────────────
    "SG": {
        "flag": "🇸🇬", "name": "Singapore",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Citi Singapore":     640_000,
                    "DBS Bank":         3_800_000,
                    "GrabFinance":        420_000,
                    "HSBC Singapore":     760_000,
                    "Maybank SG":         980_000,
                    "OCBC Bank":        2_800_000,
                    "Standard Chartered SG": 1_100_000,
                    "Trust Bank SG":      380_000,
                    "UOB":              2_400_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance SG":     980_000,
                    "Coinbase SG":    640_000,
                    "Crypto.com SG":  760_000,
                    "Gemini SG":      280_000,
                    "Independent Reserve SG": 180_000,
                    "Sygnum Bank SG": 120_000,
                    "Zipmex SG":      160_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "ACRA Bizfile Registry":  980_000,
                    "IRAS GST Registered Entities": 760_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Singtel":  2_100_000,
                    "StarHub":  1_400_000,
                    "M1 SG":      980_000,
                    "TPG SG":     320_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes SG":      95_000,
                    "Ethereum Stakers SG":  180_000,
                    "Solana Validators SG":  72_000,
                },
            },
        },
    },

    # ── Slovakia ─────────────────────────────────────────────────────────────
    "SK": {
        "flag": "🇸🇰", "name": "Slovakia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "365.bank":          320_000,
                    "Česká sporiteľňa SK": 540_000,
                    "mBank SK":           280_000,
                    "Postova Banka":      380_000,
                    "Prima Banka":        420_000,
                    "Slovenská sporiteľňa": 1_200_000,
                    "Tatra Banka":        980_000,
                    "UniCredit SK":       640_000,
                    "VÚB Banka":          860_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance SK":   280_000,
                    "Coinbase SK":  160_000,
                    "Kraken SK":     95_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Slovak Business Register (ORSR)": 620_000,
                    "Slovak Trade Register (ZRSR)":    480_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Slovak Telekom": 1_400_000,
                    "Orange SK":      1_100_000,
                    "O2 SK":            760_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes SK":    32_000,
                    "Ethereum Stakers SK": 65_000,
                },
            },
        },
    },

    # ── Slovenia ─────────────────────────────────────────────────────────────
    "SI": {
        "flag": "🇸🇮", "name": "Slovenia",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Abanka":              280_000,
                    "Addiko Bank SI":      160_000,
                    "Delavska Hranilnica":  95_000,
                    "Nova KBM":            380_000,
                    "NLB Bank":            540_000,
                    "SKB Bank":            210_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance SI":   160_000,
                    "Coinbase SI":   95_000,
                    "Kraken SI":     72_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "AJPES Business Register SI": 280_000,
                    "FURS Tax Entities":          210_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "A1 SI":         540_000,
                    "Telekom SI":    430_000,
                    "T-2 SI":        210_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes SI":    12_000,
                    "Ethereum Stakers SI": 26_000,
                },
            },
        },
    },

    # ── South Africa ─────────────────────────────────────────────────────────
    "ZA": {
        "flag": "🇿🇦", "name": "South Africa",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Absa Bank":                   2_400_000,
                    "African Bank":                  680_000,
                    "Bidvest Bank":                  210_000,
                    "Capitec Bank":                3_800_000,
                    "Discovery Bank":                650_000,
                    "First National Bank (FNB)":   3_200_000,
                    "Investec":                      410_000,
                    "Nedbank":                     2_100_000,
                    "Standard Bank":               2_900_000,
                    "TymeBank":                    1_200_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "AltCoinTrader":  420_000,
                    "Binance ZA":     980_000,
                    "Luno ZA":      1_800_000,
                    "VALR":         1_200_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "CIPC Registered Businesses": 1_100_000,
                    "SARS Tax Registered Entities": 890_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Vodacom":  5_200_000,
                    "MTN ZA":   4_800_000,
                    "Cell C":   2_100_000,
                    "Telkom ZA":1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Validator Index ZA": 85_000,
                    "Ethereum Staking Nodes ZA":  120_000,
                },
            },
        },
    },

    # ── Spain ────────────────────────────────────────────────────────────────
    "ES": {
        "flag": "🇪🇸", "name": "Spain",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Banco Sabadell":      2_400_000,
                    "Banco Santander ES": 10_800_000,
                    "Bankinter":           1_600_000,
                    "BBVA ES":             8_200_000,
                    "CaixaBank":           9_800_000,
                    "ING Direct ES":       1_400_000,
                    "Kutxabank":             760_000,
                    "N26 ES":                980_000,
                    "Openbank":              540_000,
                    "Unicaja Banco":       1_200_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance ES":    2_100_000,
                    "Bit2Me":          640_000,
                    "Coinbase ES":   1_400_000,
                    "Kraken ES":       760_000,
                    "Swissborg ES":    280_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Spanish BORME Registry":     3_200_000,
                    "Spanish VAT (NIF) Entities": 4_800_000,
                    "RCSM Mercantile Register":   2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Movistar":  7_200_000,
                    "Orange ES": 5_800_000,
                    "Vodafone ES":4_900_000,
                    "MásMóvil":  2_100_000,
                    "Yoigo":     1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes ES":      280_000,
                    "Ethereum Stakers ES":   480_000,
                    "Solana Validators ES":  160_000,
                },
            },
        },
    },

    # ── Sweden ───────────────────────────────────────────────────────────────
    "SE": {
        "flag": "🇸🇪", "name": "Sweden",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Avanza Bank":     1_200_000,
                    "Danske Bank SE":    420_000,
                    "Handelsbanken":   2_800_000,
                    "ICA Banken":        540_000,
                    "Klarna Bank":     2_100_000,
                    "Länsförsäkringar":  680_000,
                    "Nordea SE":       3_400_000,
                    "SEB":             2_600_000,
                    "Swedbank":        4_200_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance SE":     760_000,
                    "Coinbase SE":    480_000,
                    "Kraken SE":      310_000,
                    "Safello":        120_000,
                    "Swissborg SE":   280_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Swedish Bolagsverket Register": 1_200_000,
                    "Skatteverket Tax Entities":       980_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Telia SE":   3_200_000,
                    "Tele2 SE":   2_800_000,
                    "Tre SE":     1_900_000,
                    "Telenor SE": 1_400_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes SE":      160_000,
                    "Ethereum Stakers SE":   290_000,
                    "Solana Validators SE":   98_000,
                },
            },
        },
    },

    # ── Switzerland ──────────────────────────────────────────────────────────
    "CH": {
        "flag": "🇨🇭", "name": "Switzerland",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Credit Suisse":    3_200_000,
                    "Julius Baer":        680_000,
                    "Migros Bank":        760_000,
                    "Neon Bank":          420_000,
                    "PostFinance":      2_400_000,
                    "Raiffeisen CH":    2_100_000,
                    "Revolut CH":         540_000,
                    "St. Galler KB":      380_000,
                    "UBS":              5_800_000,
                    "Zürcher Kantonalbank": 1_600_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Bitcoin Suisse":   640_000,
                    "Binance CH":       380_000,
                    "Crypto Finance":   210_000,
                    "Swissborg":        760_000,
                    "Lykke":            120_000,
                    "Sygnum Bank CH":   180_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Swiss ZEFIX Commercial Register": 1_400_000,
                    "Swiss VAT (MWST) Entities":         980_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Swisscom": 2_800_000,
                    "Sunrise":  1_900_000,
                    "Salt CH":    980_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes CH":      180_000,
                    "Ethereum Stakers CH":   310_000,
                    "Solana Validators CH":   95_000,
                },
            },
        },
    },

    # ── Taiwan ───────────────────────────────────────────────────────────────
    "TW": {
        "flag": "🇹🇼", "name": "Taiwan",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Bank of Taiwan":        2_800_000,
                    "CTBC Bank":             2_400_000,
                    "E.SUN Bank":            1_600_000,
                    "First Commercial Bank": 1_800_000,
                    "Fubon Financial":       2_100_000,
                    "Hua Nan Bank":          1_400_000,
                    "Land Bank TW":          1_200_000,
                    "Mega Bank":             1_600_000,
                    "Taipei Fubon Bank":     1_400_000,
                    "Taiwan Cooperative Bank": 2_200_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Ace Exchange":    420_000,
                    "Binance TW":      980_000,
                    "BitoPro":         640_000,
                    "Coinbase TW":     380_000,
                    "MAX Exchange":    760_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "MOEA Company Register TW":  2_100_000,
                    "MOF Tax Registered Entities": 1_800_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Chunghwa Telecom":   4_100_000,
                    "Taiwan Mobile":      3_200_000,
                    "FarEasTone":         2_800_000,
                    "TSTAR":              1_100_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes TW":      140_000,
                    "Ethereum Stakers TW":   260_000,
                    "Solana Validators TW":   88_000,
                },
            },
        },
    },

    # ── Turkey ───────────────────────────────────────────────────────────────
    "TR": {
        "flag": "🇹🇷", "name": "Turkey",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Akbank":           4_800_000,
                    "Denizbank":        2_400_000,
                    "Garanti BBVA TR":  5_200_000,
                    "Halkbank":         3_400_000,
                    "ING Bank TR":      1_600_000,
                    "Isbank":           7_800_000,
                    "Papara":           3_200_000,
                    "QNB Finansbank":   2_100_000,
                    "Vakıfbank":        4_100_000,
                    "Yapı Kredi":       4_600_000,
                    "Ziraat Bank":      6_800_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance TR":   3_800_000,
                    "BtcTurk":      2_100_000,
                    "Coinbase TR":    760_000,
                    "Kraken TR":      480_000,
                    "Paribu":       1_600_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "MERSIS Turkish Trade Register": 3_400_000,
                    "GIB Tax Number Entities":       5_800_000,
                    "TOBB Chamber Entities":         2_100_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Turkcell":      6_800_000,
                    "Vodafone TR":   4_900_000,
                    "Türk Telekom":  4_200_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes TR":      280_000,
                    "Ethereum Stakers TR":   420_000,
                    "Solana Validators TR":  160_000,
                },
            },
        },
    },

    # ── UAE ──────────────────────────────────────────────────────────────────
    "AE": {
        "flag": "🇦🇪", "name": "UAE",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Abu Dhabi Commercial Bank (ADCB)": 1_400_000,
                    "Abu Dhabi Islamic Bank (ADIB)":    1_200_000,
                    "Commercial Bank of Dubai":           540_000,
                    "Dubai Islamic Bank":               1_600_000,
                    "Emirates Islamic":                   760_000,
                    "Emirates NBD":                     3_200_000,
                    "FAB (First Abu Dhabi Bank)":        2_800_000,
                    "Mashreq Bank":                     1_100_000,
                    "RAK Bank":                           640_000,
                    "Wio Bank":                           380_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance AE":     1_200_000,
                    "BitOasis":         480_000,
                    "Bybit UAE":        760_000,
                    "CoinMENA AE":      280_000,
                    "Crypto.com UAE":   640_000,
                    "Rain AE":          320_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "DED Dubai Business Registry": 1_200_000,
                    "DIFC Registered Entities":      540_000,
                    "ADCD Abu Dhabi Registry":       760_000,
                    "RAKEZ Free Zone Entities":      380_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Etisalat (e&)": 2_400_000,
                    "du":            1_800_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes AE":     120_000,
                    "Ethereum Stakers AE":  210_000,
                    "Solana Validators AE":  85_000,
                },
            },
        },
    },

    # ── Ukraine ──────────────────────────────────────────────────────────────
    "UA": {
        "flag": "🇺🇦", "name": "Ukraine",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Alfa-Bank UA":       980_000,
                    "Credit Agricole UA": 640_000,
                    "Monobank":         4_200_000,
                    "OTP Bank UA":        540_000,
                    "Oschadbank":       3_800_000,
                    "PrivatBank":      12_000_000,
                    "Raiffeisen UA":      760_000,
                    "PUMB":             1_400_000,
                    "Ukrsibbank":         980_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance UA":      1_400_000,
                    "Coinbase UA":       480_000,
                    "Kraken UA":         310_000,
                    "Kuna Exchange":     760_000,
                    "WhiteBIT":        1_200_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Ukrainian EDRU Business Register": 2_800_000,
                    "State Tax Service Entities":       3_400_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "Kyivstar":  4_800_000,
                    "Vodafone UA":3_200_000,
                    "lifecell":  2_100_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Nodes UA":      180_000,
                    "Ethereum Stakers UA":   320_000,
                    "Solana Validators UA":  120_000,
                },
            },
        },
    },

    # ── United Kingdom ───────────────────────────────────────────────────────
    "UK": {
        "flag": "🇬🇧", "name": "United Kingdom",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Bank of Scotland":           1_100_000,
                    "Barclays":                   3_400_000,
                    "Cater Allen":                  180_000,
                    "Co-operative Bank":            420_000,
                    "Coutts":                       120_000,
                    "First Direct":                 650_000,
                    "Halifax":                    2_800_000,
                    "HSBC UK":                    3_100_000,
                    "Lloyds Bank":                3_900_000,
                    "Metro Bank":                   520_000,
                    "Monzo":                      2_100_000,
                    "NatWest":                    3_200_000,
                    "Nationwide":                 2_600_000,
                    "Revolut UK":                 2_400_000,
                    "Royal Bank of Scotland (RBS)":1_800_000,
                    "Sainsbury's Bank":             340_000,
                    "Santander UK":               2_900_000,
                    "Starling Bank":              1_400_000,
                    "Tesco Bank":                   480_000,
                    "TSB Bank":                   1_200_000,
                    "Virgin Money":                 950_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance UK":    1_800_000,
                    "Bitstamp UK":     420_000,
                    "Coinbase UK":   2_200_000,
                    "CoinJar UK":      210_000,
                    "Crypto.com UK": 1_400_000,
                    "eToro UK":      1_100_000,
                    "Gemini UK":       380_000,
                    "Kraken UK":       890_000,
                    "KuCoin UK":       650_000,
                    "Uphold UK":       510_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Companies House Active Directors": 2_800_000,
                    "UK Corporate Officer Index":       1_900_000,
                    "UK VAT Registered Entities":       1_400_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "EE":        3_544_000,
                    "O2 UK":     1_831_000,
                    "Sky UK":      553_000,
                    "Three UK": 4_515_000,
                    "Virgin UK":   114_000,
                    "Vodafone UK": 530_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Full Nodes (UK)":        140_000,
                    "Ethereum Staking Validators UK": 310_000,
                    "Solana RPC Endpoints UK":        180_000,
                },
            },
        },
    },

    # ── United States ────────────────────────────────────────────────────────
    "US": {
        "flag": "🇺🇸", "name": "United States",
        "verticals": {
            "banks": {
                "label": "🏦 Banks",
                "items": {
                    "Ally Bank":           1_200_000,
                    "Bank of America":     7_200_000,
                    "Capital One":         5_200_000,
                    "Charles Schwab Bank": 1_800_000,
                    "Chase":               8_500_000,
                    "Citi":                4_900_000,
                    "Discover Bank":       2_100_000,
                    "Marcus by Goldman":   1_400_000,
                    "Navy Federal CU":     1_600_000,
                    "PNC Bank":            3_400_000,
                    "Regions Bank":        1_800_000,
                    "SoFi Bank":             980_000,
                    "TD Bank US":          2_400_000,
                    "US Bank":             3_800_000,
                    "Wells Fargo":         6_100_000,
                },
            },
            "crypto": {
                "label": "🪙 Crypto",
                "items": {
                    "Binance.US":    3_100_000,
                    "Coinbase US":   9_500_000,
                    "Crypto.com US": 4_500_000,
                    "Gemini US":     2_800_000,
                    "Kraken US":     4_200_000,
                    "Robinhood Crypto": 5_800_000,
                    "Uphold US":     1_400_000,
                },
            },
            "biz": {
                "label": "🏢 Business",
                "items": {
                    "Delaware Corporation Index":  5_400_000,
                    "Nevada LLC Registry":         2_100_000,
                    "Wyoming Entity Register":     1_200_000,
                    "California SOS Business":     6_800_000,
                    "Texas SOS Entity Registry":   4_200_000,
                },
            },
            "sim": {
                "label": "📡 SMS",
                "items": {
                    "AT&T":               12_800_000,
                    "Verizon":            11_400_000,
                    "T-Mobile US":         9_700_000,
                    "Boost Mobile US":     2_100_000,
                    "Cricket Wireless":    1_900_000,
                    "Metro by T-Mobile":   1_700_000,
                    "US Cellular":           890_000,
                    "Mint Mobile":           640_000,
                },
            },
            "ledger": {
                "label": "🔗 Hardware",
                "items": {
                    "Bitcoin Full Nodes (US)":        850_000,
                    "Ethereum Staking Validators US": 1_100_000,
                    "Solana Validators US":             420_000,
                },
            },
        },
    },

}

# ── Auto-add MIX to every vertical in every country (125% of highest stock) ───
for _cc, _d in LEADS.items():
    for _vkey, _vdata in _d.get("verticals", {}).items():
        _items = _vdata.get("items", {})
        if _items and "MIX" not in _items:
            _biggest = max(_items.values())
            _items["MIX"] = int(_biggest * 1.25)

# ── Hardware Wallet Master List & Country Tier Map ────────────────────────────
_HW_FULL = [
    "Ledger Nano S Plus", "Ledger Nano X", "Ledger Flex", "Ledger Stax",
    "Trezor Model One",   "Trezor Safe 3", "Trezor Safe 5",
    "ELLIPAL Titan 2.0",  "ELLIPAL Titan Mini",
    "Keystone 3 Pro",     "NGRAVE ZERO",      "Blockstream Jade",
    "Foundation Passport","Coldcard Mk4",     "Coldcard Q",
    "SafePal S1",         "SafePal X1",
    "Tangem Card",        "Tangem Ring",
    "BitBox02",           "SecuX W20",        "SecuX V20",  "KeepKey",
    "CoolWallet Pro",     "CoolWallet S",
    "OneKey Classic",     "OneKey Touch",     "OneKey Pro",
]
# Mid tier: drop US-export-restricted Coldcard Mk4/Q, NGRAVE ZERO (very limited dist),
# Foundation Passport (US-only fulfilment issues)
_HW_MID = [w for w in _HW_FULL if w not in {
    "Coldcard Mk4", "Coldcard Q", "NGRAVE ZERO", "Foundation Passport",
}]
# Light tier: further drop BitBox02, KeepKey, SecuX W20/V20 (limited regional shipping)
_HW_LIGHT = [w for w in _HW_MID if w not in {
    "BitBox02", "KeepKey", "SecuX W20", "SecuX V20",
}]

_CC_HW_TIER = {
    **{cc: _HW_FULL for cc in [
        "AU","AT","BE","CA","CH","CZ","DE","DK","EE","ES","FI","FR",
        "GR","HU","IE","IS","IT","LT","LV","MT","NL","NO","NZ","PL",
        "PT","RO","SE","SI","SK","UK","US","PR",
    ]},
    **{cc: _HW_MID for cc in [
        "AE","BH","QA","CY","SG","MY","TW","ZA","BR","BG",
    ]},
    **{cc: _HW_LIGHT for cc in ["TR","UA"]},
}

_HW_STOCK = 500_000  # stock per hardware model

# Inject real hardware wallet items into every country's ledger vertical
for _cc, _models in _CC_HW_TIER.items():
    if _cc in LEADS and "ledger" in LEADS[_cc]["verticals"]:
        LEADS[_cc]["verticals"]["ledger"]["items"] = {m: _HW_STOCK for m in _models}

DEFAULT_LEADS = _copy.deepcopy(LEADS)
DEFAULT_STORE = None  # set after STORE is defined above

# ── Targeted Source Pricing ───────────────────────────────────────────────────
AGED_LEADS_PRICING = [
    (1_000,   70),
    (5_000,   300),
    (10_000,  500),
    (25_000,  1100),
]

CRYPTO_LEADS_PRICING = [
    (1_000,   200),
    (5_000,   800),
    (10_000,  1500),
    (25_000,  2500),
]

# ── Per-item target lists (name, fixed price £) ──────────────────────────────
TS_FULLZ_ITEMS = [
    ("NHS",                180),  ("Post Office",        210),
    ("DPD",                160),  ("DHL",                190),
    ("Apple",              290),  ("New Apple Pay",      210),
    ("O2",                 170),  ("My3",                150),
    ("Vodafone",           220),  ("EE",                 210),
    ("Sky",                180),  ("Netflix",            160),
    ("HMRC",               250),  ("DVLA",               200),
    ("iD Mobile",          150),  ("Virgin",             190),
    ("PayPal",             200),  ("NHS Omicron",        160),
    ("EVRi",               150),  ("PureGym",            140),
    ("Energy Scheme",      170),  ("Amazon",             220),
    ("Cost of Crisis",     150),  ("Spare1Bank",         200),
    ("BOI",                170),  ("AIB",                200),
    ("Ulster",             180),  ("NAB",                320),
    ("Westpac",            230),  ("Commonwealth",       200),
    ("ANZ AU",             190),  ("Bendigo",            170),
    ("St. George",         190),  ("Suncorp",            250),
    ("UBank",              210),  ("Macquarie",          140),
    ("BNZ",                180),  ("ASB",                170),
    ("ANZ NZ",             190),  ("Santander PT",       210),
    ("BBVA",               230),
]

TS_CRYPTO_ITEMS = [
    ("Trading212",  260),  ("Bunq",      200),
    ("KuCoin",      300),  ("Binance",   250),
    ("Bybit",       280),  ("OKX",       200),
    ("HTC",         250),  ("CoinSpot",  260),
    ("Shakepay",    300),  ("Coinbase",  280),
    ("Ledger",      200),  ("WEB3",      260),
    ("CoinGate",    300),  ("CoinJar",   250),
]

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

# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def calculate_dynamic_stock():
    total = 0
    for vid, vdata in STORE.items():
        for bkey, bdata in vdata.get("bases", {}).items():
            for qty in bdata.get("bins", {}).values():
                total += qty
    return total

def _save_data_sync():
    """Synchronous disk write — always call via the async await save_data() wrapper."""
    try:
        data = {
            "user_balances":    {str(k): v for k, v in user_balances.items()},
            "agreed_users":     list(agreed_users),
            "user_join_dates":  {str(k): v for k, v in user_join_dates.items()},
            "channel_verified": list(channel_verified),
            "live_stock":       live_stock,
            "STORE":            STORE,
            "LEADS":            LEADS,
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        logger.error(f"save_data failed: {e}")

async def save_data():
    """Non-blocking save — offloads the file write to a thread so the event
    loop (and every other user's handler) keeps running during the I/O."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _save_data_sync)

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

        # Merge in any new countries/verticals/items added to DEFAULT_LEADS
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
    if not LOG_CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception:
        pass

def log_bg(app, text: str):
    """Fire-and-forget log — never blocks the caller."""
    if not LOG_CHANNEL_ID:
        return
    try:
        asyncio.get_running_loop().create_task(log(app, text))
    except Exception:
        pass

async def log_purchase(app, text: str, buyer_uid: int):
    """Send a purchase log to the log channel with a Deliver File button."""
    if not LOG_CHANNEL_ID:
        return
    try:
        kbd = InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Deliver File", callback_data=f"deliver_to|{buyer_uid}")
        ]])
        await app.bot.send_message(
            chat_id=int(LOG_CHANNEL_ID), text=text,
            parse_mode="Markdown", reply_markup=kbd)
    except Exception:
        pass

def log_purchase_bg(app, text: str, buyer_uid: int):
    """Fire-and-forget purchase log — never blocks the caller."""
    if not LOG_CHANNEL_ID:
        return
    try:
        asyncio.get_running_loop().create_task(log_purchase(app, text, buyer_uid))
    except Exception:
        pass

def is_admin(update) -> bool:
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

async def check_channel_membership(bot, user_id):
    if not JOIN_CHANNEL:
        return True, "ok"
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"):
            return True, "ok"
        return False, "not_joined"
    except Exception:
        return False, "error"

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
                return {
                    "BTC": d["bitcoin"]["gbp"],
                    "SOL": d["solana"]["gbp"],
                    "LTC": d["litecoin"]["gbp"],
                }
    except Exception:
        return None

def scanner_items_for_cat(cat):
    if cat == "all":
        return list(enumerate(SCANNER_ITEMS))
    return [(i, item) for i, item in enumerate(SCANNER_ITEMS) if item[1] == cat]

# ═════════════════════════════════════════════════════════════════════════════
# KEYBOARD BUILDERS
# ═════════════════════════════════════════════════════════════════════════════

def scanner_keyboard(cat="all", page=0):
    SCAN_CATS = {
        "all":      "All •",
        "socials":  "Socials",
        "crypto":   "Crypto",
        "shopping": "Shop...",
        "carrier":  "Carrier",
    }
    items       = scanner_items_for_cat(cat)
    total_pages = max(1, (len(items) + SCANNER_PER_PAGE - 1) // SCANNER_PER_PAGE)
    page_items  = items[page * SCANNER_PER_PAGE : (page + 1) * SCANNER_PER_PAGE]

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
    if page > 0:
        nav.append(InlineKeyboardButton("← Prev", callback_data=f"scan|{cat}|{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next →", callback_data=f"scan|{cat}|{page+1}"))
    if nav:
        rows.append(nav)
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
    u     = update.effective_user
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
        row = [
            InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"lc|{cc}")
            for cc, d in countries[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def verticals_keyboard(cc):
    rows = [
        [InlineKeyboardButton("🪙 Crypto",    callback_data=f"lvert|{cc}|crypto")],
        [InlineKeyboardButton("🏦 Banks",   callback_data=f"lvert|{cc}|banks")],
        [InlineKeyboardButton("🏢 Business", callback_data=f"lvert|{cc}|biz")],
        [InlineKeyboardButton("📡 SMS",     callback_data=f"lvert|{cc}|sim")],
        [InlineKeyboardButton("🔗 Hardware",     callback_data=f"lvert|{cc}|ledger")],
        [InlineKeyboardButton("⬅️ Back to Directory",   callback_data="leads")],
    ]
    return InlineKeyboardMarkup(rows)

def dataset_item_keyboard(cc, vert_key):
    items = list(LEADS[cc]["verticals"][vert_key]["items"].items())
    rows  = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"lk|{cc}|{vert_key}|{name}")
            for name, stock in items[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

HW_PER_PAGE = 8  # 4 rows × 2 columns

def hw_keyboard(cc, page=0):
    """Paginated inline keyboard for the Hardware (ledger) vertical."""
    models     = list(LEADS[cc]["verticals"]["ledger"]["items"].keys())
    total_pages = max(1, (len(models) + HW_PER_PAGE - 1) // HW_PER_PAGE)
    page        = max(0, min(page, total_pages - 1))
    page_models = models[page * HW_PER_PAGE:(page + 1) * HW_PER_PAGE]
    rows = []
    for i in range(0, len(page_models), 2):
        row = []
        for j in range(i, min(i + 2, len(page_models))):
            name = page_models[j]
            row.append(InlineKeyboardButton(name, callback_data=f"lk|{cc}|ledger|{name}"))
        rows.append(row)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"lhwp|{cc}|{page-1}"))
        nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"lhwp|{cc}|{page+1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, vert_key, item_name):
    pricing = VERT_PRICING.get(vert_key, LEADS_PRICING)
    rows = []
    for i in range(0, len(pricing), 2):
        row = [
            InlineKeyboardButton(f"{qty//1000}k — £{price}", callback_data=f"lq|{cc}|{vert_key}|{item_name}|{qty}")
            for qty, price in pricing[i:i+2]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lvert|{cc}|{vert_key}")])
    return InlineKeyboardMarkup(rows)

def tsource_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 Bank Page",             callback_data="ts_aged")],
        [InlineKeyboardButton("🪙 Crypto Page",          callback_data="ts_crypto")],
        [InlineKeyboardButton("🛠 Additional Services", callback_data="ts_services")],
        [InlineKeyboardButton("⬅️ Back",                callback_data="back")],
    ])

def ts_qty_keyboard(pricing, cb_prefix):
    rows = []
    for i in range(0, len(pricing), 2):
        row = []
        for qty, price in pricing[i:i+2]:
            k     = qty // 1000
            label = f"£{price//1000}k" if price >= 1000 else f"£{price}"
            row.append(InlineKeyboardButton(f"{k}k — {label}", callback_data=f"{cb_prefix}|{qty}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tsource")])
    return InlineKeyboardMarkup(rows)

def ts_fullz_items_keyboard():
    rows = []
    for i in range(0, len(TS_FULLZ_ITEMS), 2):
        row = []
        for idx in range(i, min(i + 2, len(TS_FULLZ_ITEMS))):
            name, price = TS_FULLZ_ITEMS[idx]
            row.append(InlineKeyboardButton(f"{name} — £{price}", callback_data=f"tsfi|{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tsource")])
    return InlineKeyboardMarkup(rows)

def ts_crypto_items_keyboard():
    rows = []
    for i in range(0, len(TS_CRYPTO_ITEMS), 2):
        row = []
        for idx in range(i, min(i + 2, len(TS_CRYPTO_ITEMS))):
            name, price = TS_CRYPTO_ITEMS[idx]
            row.append(InlineKeyboardButton(f"{name} — £{price}", callback_data=f"tsci|{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="tsource")])
    return InlineKeyboardMarkup(rows)

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads",  callback_data="leads"),  InlineKeyboardButton("🛍️ Store",  callback_data="store")],
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("🔍 Scanner", callback_data="scanner")],
        [InlineKeyboardButton("📨 Spam Service", callback_data="tsource")],
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
        f"💰 *Balance:* £{user_balances.get(uid, 0):.2f}\n"
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
    if row:
        rows.append(row)
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
    rows = [
        [InlineKeyboardButton(b["label"], callback_data=f"base|{vid}|{bk}")]
        for bk, b in STORE[vid]["bases"].items()
    ]
    rows.append([InlineKeyboardButton("🔍 BIN Search", callback_data=f"bsearch|{vid}")])
    rows.append([InlineKeyboardButton("⬅️ Back",       callback_data="store")])
    return InlineKeyboardMarkup(rows)

def bin_list_keyboard(vid, bkey, page=0):
    bins        = list(STORE[vid]["bases"][bkey]["bins"].items())
    total_pages = max(1, (len(bins) + BINS_PER_PAGE - 1) // BINS_PER_PAGE)
    page_bins   = bins[page * BINS_PER_PAGE : (page + 1) * BINS_PER_PAGE]
    rows = []
    for i in range(0, len(page_bins), 2):
        rows.append([
            InlineKeyboardButton(f"{b} ({q})", callback_data=f"buybin|{vid}|{bkey}|{b}|{page}")
            for b, q in page_bins[i:i+2]
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"bpage|{vid}|{bkey}|{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"bpage|{vid}|{bkey}|{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
    return InlineKeyboardMarkup(rows), total_pages

def deads_keyboard():
    rows = [
        [InlineKeyboardButton(f"{l} — £{p:,}", callback_data=f"dbuy|{k}")]
        for l, p, k in DEADS_ITEMS
    ]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

# ═════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)
    if is_new:
        log_bg(context.application,
            f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    if uid in agreed_users and uid in channel_verified:
        log_bg(context.application,
            f"🔄 *Returning User /start*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        await update.message.reply_text(
            main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel to Continue", url=JOIN_CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Let Me In",  callback_data="agree_rules")],
    ])
    await update.message.reply_text(RULES_TEXT, reply_markup=keyboard, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    log_bg(context.application,
        f"💰 */balance*\n👤 {user_tag(update)}\n🪪 `{uid}`\n💷 Balance: £{bal:.2f}")
    await update.message.reply_text(
        f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*\n\n"
        f"_Top up via the Wallet section._",
        parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    log_bg(context.application,
        f"💳 */wallet*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
        f"💷 Balance: £{user_balances.get(uid, 0):.2f}")
    await update.message.reply_text(
        wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

async def cmd_targeted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📨 *Spam Service*\n\nSelect a category below:",
        reply_markup=tsource_main_keyboard(), parse_mode="Markdown")

SUPPORT_USER = os.environ.get("SUPPORT_USERNAME", "HekTikz")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📩 *Contact / Support*\n\n"
        f"For top-ups, orders, refunds or any help, message the admin directly:\n\n"
        f"👤 Admin: @{SUPER_ADMIN}\n🔹 Support 24/7: @{SUPPORT_USER}\n\n"
        f"_Tap a button below to open a chat._",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👤 Message Admin",   url=f"https://t.me/{SUPER_ADMIN}")],
            [InlineKeyboardButton(f"🔹 Message Support", url=f"https://t.me/{SUPPORT_USER}")],
        ]),
        parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *How to use this bot*\n\n"
        "1️⃣ Top up your balance — /wallet (crypto: BTC, SOL, LTC)\n"
        "2️⃣ Browse sections from /start:\n"
        "   🌍 Leads · 🛍️ Store · 🔍 Scanner · 📨 Spam Service\n"
        "3️⃣ Pick an item and confirm — your balance is charged instantly\n"
        "4️⃣ After buying, contact the admin to receive your files\n\n"
        "*Useful commands:*\n/start · /wallet · /balance · /targeted · /contact",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}")]
        ]),
        parse_mode="Markdown")

async def cmd_adminlogin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        password = context.args[0]
    except IndexError:
        await update.message.reply_text("Usage: /adminlogin <password>"); return
    if password == ADMIN_PASSWORD:
        logged_in_admins.add(uid)
        await update.message.reply_text(
            "✅ *Admin access granted!*\nSend /adminhelp to see all commands.",
            parse_mode="Markdown")
        log_bg(context.application,
            f"🔑 *Admin Login*\n👤 {user_tag(update)}\n🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    else:
        await update.message.reply_text("❌ Wrong password.")
        log_bg(context.application, f"⚠️ *Failed Admin Login*\n👤 {user_tag(update)}")

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
    "`/listusers`\n"
    "`/broadcast` — enter broadcast mode (send any message type)\n"
    "`/broadcast <text>` — quick text broadcast\n"
    "`/updatelead <CC> <VerticalKey> <ItemName> <Stock>`\n"
    "`/bulkbin <vid> <bkey>`\n"
    "`/deliver <user_id>` — set delivery target, then send the file to forward"
)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]])

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode="Markdown")

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except:
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2); await save_data()
    await update.message.reply_text(
        f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*",
        parse_mode="Markdown")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except:
        await update.message.reply_text("Usage: /removebalance <user_id> <amount>"); return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2); await save_data()
    await update.message.reply_text(
        f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*",
        parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        tid = int(context.args[0]); amt = float(context.args[1])
    except:
        await update.message.reply_text("Usage: /setbalance <user_id> <amount>"); return
    user_balances[tid] = round(amt, 2); await save_data()
    await update.message.reply_text(
        f"✅ Set `{tid}` balance to *£{amt:.2f}*", parse_mode="Markdown")

async def cmd_checkbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        tid = int(context.args[0])
    except:
        await update.message.reply_text("Usage: /checkbalance <user_id>"); return
    await update.message.reply_text(
        f"User `{tid}` balance: *£{user_balances.get(tid, 0):.2f}*", parse_mode="Markdown")

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        key = context.args[0].lower(); val = int(context.args[1])
        assert key in ("leads", "stock")
    except:
        await update.message.reply_text("Usage: /setstock leads <number>"); return
    live_stock[key] = val; await save_data()
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except:
        await update.message.reply_text("Usage: /addvendor <id> <label>"); return
    if vid in STORE:
        await update.message.reply_text(f"Vendor `{vid}` already exists."); return
    STORE[vid] = {"label": label, "bases": {}}; await save_data()
    await update.message.reply_text(f"✅ Added vendor *{label}*", parse_mode="Markdown")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; assert vid in STORE
    except:
        await update.message.reply_text("Usage: /removevendor <vendor_id>"); return
    del STORE[vid]; await save_data()
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid   = context.args[0]; bkey  = context.args[1]
        price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label and "|" not in bkey
    except:
        await update.message.reply_text("Usage: /addbase <vendor_id> <base_key> <price> <label>"); return
    existing_bins = {}
    if bkey in STORE[vid]["bases"]:
        existing_bins = STORE[vid]["bases"][bkey].get("bins", {})
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": existing_bins}
    await save_data()
    await update.message.reply_text(f"✅ Base *{label}* set in `{vid}`", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /removebase <vendor_id> <base_key>"); return
    del STORE[vid]["bases"][bkey]; await save_data()
    await update.message.reply_text(f"✅ Removed base `{bkey}` from `{vid}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid     = context.args[0]; bkey    = context.args[1]
        bin_num = context.args[2]; qty     = int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /addbin <vid> <bkey> <bin> <qty>"); return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; await save_data()
    await update.message.reply_text(
        f"✅ BIN *{bin_num}* = *{qty}* in `{vid}` / `{bkey}`", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid     = context.args[0]; bkey    = context.args[1]; bin_num = context.args[2]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /removebin <vid> <bkey> <bin>"); return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None); await save_data()
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /listbins <vid> <bkey>"); return
    bins  = STORE[vid]["bases"][bkey]["bins"]
    label = STORE[vid]["bases"][bkey]["label"]
    if not bins:
        await update.message.reply_text(f"No BINs in *{label}*", parse_mode="Markdown"); return
    lines = [f"📦 *{label}* — {sum(bins.values())} total\n"]
    for b, q in sorted(bins.items()):
        lines.append(f"`{b}` — {q} cards")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        vid = context.args[0]; bkey = context.args[1]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /clearbase <vid> <bkey>"); return
    STORE[vid]["bases"][bkey]["bins"].clear(); await save_data()
    await update.message.reply_text(f"✅ Cleared all BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    if not user_balances:
        await update.message.reply_text("No users with balances yet."); return
    lines = ["👥 *All Users & Balances*\n"]
    for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1]):
        lines.append(f"`{uid}` — £{bal:.2f} (joined {user_join_dates.get(uid, '?')})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_deliver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /deliver <user_id>  — then send a file to forward it to that user."""
    if not is_admin(update): return
    try:
        target_uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /deliver <user_id>\n\nThen send the file to forward."); return
    context.user_data["deliver_to"] = target_uid
    order_info  = pending_orders.get(target_uid, "")
    preview     = f"\n\n📋 Pending order:\n{order_info}" if order_info else ""
    await update.message.reply_text(
        f"📦 Delivery target set: `{target_uid}`{preview}\n\n_Now send the file._",
        parse_mode="Markdown")

async def cmd_refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User command: /refund — enforce 3-min window, 10-min auto-expiry."""
    uid = update.effective_user.id
    now = datetime.utcnow()
    ts  = delivery_timestamps.get(uid)

    back_kbd = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back")]])

    if ts is None:
        # Scenario C: never purchased / no delivery on record
        await update.message.reply_text(
            "❌ *No Recent Orders Found*\n\n"
            "You don't have any recent purchases.",
            reply_markup=back_kbd, parse_mode="Markdown")
        return

    elapsed = (now - ts).total_seconds()

    if elapsed > 600:
        # Scenario C: older than 10 mins — clean up and treat as no order
        delivery_timestamps.pop(uid, None)
        await update.message.reply_text(
            "❌ *No Recent Orders Found*\n\n"
            "You don't have any recent purchases.",
            reply_markup=back_kbd, parse_mode="Markdown")

    elif elapsed > 180:
        # Scenario B: 3–10 mins — window has closed
        await update.message.reply_text(
            "❌ *You are not eligible for a refund.*\n\n"
            "The 3-minute replacement window has expired.",
            parse_mode="Markdown")

    else:
        # Scenario A: within 3 mins — eligible
        remaining_secs = max(0, 180 - int(elapsed))
        remaining_mins = max(1, round(remaining_secs / 60))
        context.user_data["awaiting_refund_screenshot"] = True
        await update.message.reply_text(
            f"✅ *You're Eligible for a Refund*\n\n"
            f"⏱ Time remaining: approx. *{remaining_mins} minute(s)*\n\n"
            f"📸 Please send a screenshot of your issue below.\n"
            f"Our team will review and respond shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="refund_cancel")]]),
            parse_mode="Markdown")

async def file_delivery_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles photo/file uploads: payment screenshots from users, file delivery from admin."""
    uid = update.effective_user.id
    msg = update.message

    # ── Payment screenshot from a regular user ────────────────────────────────
    ss_info = context.user_data.get("awaiting_screenshot")
    if ss_info and msg.photo:
        coin   = ss_info["coin"]
        amount = ss_info["amount"]
        context.user_data.pop("awaiting_screenshot", None)
        photo_id = msg.photo[-1].file_id
        caption = (
            f"📸 *NEW PAYMENT SCREENSHOT*\n"
            f"👤 From: {user_tag(update)} (`{uid}`)\n"
            f"💰 *Expected Amount:* £{amount} via {coin}\n\n"
            f"⚠️ *Action required:* Verify and Accept/Reject."
        )
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Approve £{amount}", callback_data=f"approve_pay|{uid}|{amount}")],
            [InlineKeyboardButton("❌ Reject Payment",     callback_data=f"reject_pay|{uid}")],
        ])
        if LOG_CHANNEL_ID:
            try:
                await context.application.bot.send_photo(
                    chat_id=int(LOG_CHANNEL_ID),
                    photo=photo_id, caption=caption,
                    parse_mode="Markdown", reply_markup=kbd)
            except Exception:
                pass
        await msg.reply_text(
            "✅ *SCREENSHOT RECEIVED*\n— — — — — — — — — — — — —\n\n"
            "Your payment receipt has been successfully submitted to the system.\n"
            "⏳ Verification processing window is 1-15 minutes.",
            parse_mode="Markdown")
        return

    # ── Refund screenshot from user ──────────────────────────────────────────
    if context.user_data.get("awaiting_refund_screenshot") and msg.photo:
        context.user_data.pop("awaiting_refund_screenshot", None)
        delivery_timestamps.pop(uid, None)   # consume — one refund per order
        photo_id = msg.photo[-1].file_id
        caption  = (
            f"🔄 *REFUND REQUEST*\n"
            f"👤 {user_tag(update)} (`{uid}`)\n"
            f"📸 Screenshot submitted for review."
        )
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve Refund", callback_data=f"approve_refund|{uid}")],
            [InlineKeyboardButton("❌ Reject",         callback_data=f"reject_refund|{uid}")],
        ])
        if LOG_CHANNEL_ID:
            try:
                await context.application.bot.send_photo(
                    chat_id=int(LOG_CHANNEL_ID), photo=photo_id,
                    caption=caption, parse_mode="Markdown", reply_markup=kbd)
            except Exception:
                pass
        await msg.reply_text(
            "✅ *Refund Request Submitted*\n\n"
            "Your screenshot has been forwarded to our team.\n"
            "We'll review and respond shortly.",
            parse_mode="Markdown")
        return

    # ── Admin broadcast media capture ────────────────────────────────────────
    if is_admin(update) and context.user_data.get("awaiting_broadcast"):
        context.user_data.pop("awaiting_broadcast", None)
        if msg.document:
            btype, fid = "document", msg.document.file_id
            cap = msg.caption or ""
        elif msg.photo:
            btype, fid = "photo", msg.photo[-1].file_id
            cap = msg.caption or ""
        elif msg.video:
            btype, fid = "video", msg.video.file_id
            cap = msg.caption or ""
        elif msg.audio:
            btype, fid = "audio", msg.audio.file_id
            cap = msg.caption or ""
        else:
            await msg.reply_text("❌ Unsupported file type for broadcast.")
            return
        pending = {"type": btype, "file_id": fid, "caption": cap}
        context.user_data["pending_broadcast"] = pending
        await _show_broadcast_preview(msg, context, pending)
        return

    # ── Admin file delivery ───────────────────────────────────────────────────
    if not is_admin(update): return
    target_uid = context.user_data.get("deliver_to")
    if not target_uid: return
    msg = update.message

    if msg.document:
        file_type, file_id = "document", msg.document.file_id
        file_name = msg.document.file_name or "file"
    elif msg.photo:
        file_type, file_id = "photo", msg.photo[-1].file_id
        file_name = "photo"
    elif msg.video:
        file_type, file_id = "video", msg.video.file_id
        file_name = msg.video.file_name or "video"
    elif msg.audio:
        file_type, file_id = "audio", msg.audio.file_id
        file_name = msg.audio.file_name or "audio"
    else:
        await msg.reply_text("❌ Unsupported file type. Send a document, photo, video, or audio.")
        return

    # Hold the file — don't send yet
    context.user_data["pending_file"] = {"type": file_type, "file_id": file_id}

    order_info = pending_orders.get(target_uid, "")
    preview    = f"\n\n📋 *Order details:*\n`{order_info}`" if order_info else ""

    await msg.reply_text(
        f"📎 *File received:* `{file_name}`\n"
        f"👤 *Deliver to:* `{target_uid}`"
        f"{preview}\n\n"
        f"Send this file to the user?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Send", callback_data=f"confirm_deliver|{target_uid}"),
             InlineKeyboardButton("❌ Cancel",       callback_data="cancel_deliver")],
        ]),
        parse_mode="Markdown")

def _broadcast_targets() -> set:
    """All known user IDs across every data store."""
    return set(user_join_dates.keys()) | set(user_balances.keys()) | agreed_users

async def _do_broadcast(bot, status_msg, pending: dict) -> tuple[int, int]:
    """Send the pending broadcast to every known user. Returns (sent, failed)."""
    targets      = _broadcast_targets()
    sent, failed = 0, 0
    last_edit    = 0
    for i, target_uid in enumerate(targets, 1):
        try:
            btype = pending["type"]
            fid   = pending.get("file_id")
            cap   = pending.get("caption", "")
            txt   = pending.get("text", "")
            pm    = "Markdown"
            if btype == "text":
                await bot.send_message(chat_id=target_uid, text=txt, parse_mode=pm)
            elif btype == "photo":
                await bot.send_photo(chat_id=target_uid, photo=fid, caption=cap, parse_mode=pm)
            elif btype == "video":
                await bot.send_video(chat_id=target_uid, video=fid, caption=cap, parse_mode=pm)
            elif btype == "document":
                await bot.send_document(chat_id=target_uid, document=fid, caption=cap, parse_mode=pm)
            elif btype == "audio":
                await bot.send_audio(chat_id=target_uid, audio=fid, caption=cap, parse_mode=pm)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
        # Update progress every 20 users so admin can see it moving
        if i - last_edit >= 20:
            last_edit = i
            try:
                await status_msg.edit_text(
                    f"📢 *Broadcasting…*\n\n"
                    f"✅ Sent: *{sent}* / ❌ Failed: {failed}\n"
                    f"📊 Progress: *{i}/{len(targets)}*",
                    parse_mode="Markdown")
            except Exception:
                pass
    return sent, failed

async def _show_broadcast_preview(message, context, pending: dict):
    """Show a preview of the pending broadcast with confirm / cancel buttons."""
    count   = len(_broadcast_targets())
    btype   = pending["type"]
    txt     = pending.get("text", "")
    cap     = pending.get("caption", "")
    preview = txt or cap or f"[{btype} file]"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 Send to {count} users", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Cancel",                  callback_data="broadcast_cancel")],
    ])
    await message.reply_text(
        f"📢 *Broadcast Preview*\n\n"
        f"```\n{preview[:400]}\n```\n\n"
        f"Type: *{btype}* · Targets: *{count} users*\n"
        f"Tap *Send* to confirm.",
        reply_markup=kbd, parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    full_text  = update.message.text or ""
    parts      = full_text.split(None, 1)
    inline_msg = parts[1].strip() if len(parts) > 1 else ""

    if inline_msg:
        # Check if the last token is a numeric UID → single-user DM
        tokens    = inline_msg.split()
        last_tok  = tokens[-1]
        if last_tok.lstrip("-").isdigit() and len(tokens) > 1:
            target_uid = int(last_tok)
            msg_text   = " ".join(tokens[:-1])
            try:
                await context.application.bot.send_message(
                    chat_id=target_uid, text=msg_text, parse_mode="Markdown")
                await update.message.reply_text(
                    f"✅ *Message sent to* `{target_uid}`\n\n`{msg_text}`",
                    parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Failed to send to `{target_uid}`:\n`{e}`",
                    parse_mode="Markdown")
            return

        # No UID suffix — broadcast to everyone
        pending = {"type": "text", "text": inline_msg}
        context.user_data["pending_broadcast"] = pending
        await _show_broadcast_preview(update.message, context, pending)
    else:
        # Enter broadcast mode — next message the admin sends becomes the broadcast
        context.user_data["awaiting_broadcast"] = True
        context.user_data.pop("pending_broadcast", None)
        await update.message.reply_text(
            "📢 *Broadcast Mode*\n\n"
            "Send me the message you want to blast to all users.\n"
            "Supports: text, photo, video, document, audio.\n\n"
            "To DM one user: `/broadcast <message> <uid>`\n"
            "_Send /broadcast again to cancel._",
            parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /updatelead <CC> <VerticalKey> <ItemName> <Stock>"""
    if not is_admin(update):
        await update.message.reply_text("❌ Not authorised."); return
    try:
        cc       = context.args[0].upper()
        vert_key = context.args[1].lower()
        stock    = int(context.args[-1])
        item_name = " ".join(context.args[2:-1])
        assert cc in LEADS and vert_key in LEADS[cc]["verticals"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text(
            "Usage: /updatelead <CC> <VerticalKey> <ItemName> <Stock>\n"
            "Example: /updatelead AU banks Westpac 3000000"); return
    if stock <= 0:
        LEADS[cc]["verticals"][vert_key]["items"].pop(item_name, None); await save_data()
        await update.message.reply_text(
            f"✅ Removed *{item_name}* from {LEADS[cc]['flag']} {LEADS[cc]['name']} ({vert_key})",
            parse_mode="Markdown")
    else:
        LEADS[cc]["verticals"][vert_key]["items"][item_name] = stock; await save_data()
        await update.message.reply_text(
            f"✅ Updated *{item_name}* → *{stock:,}* in {LEADS[cc]['flag']} {LEADS[cc]['name']} ({vert_key})",
            parse_mode="Markdown")

async def cmd_bulkbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    lines = update.message.text.split("\n")
    first = lines[0].split()
    try:
        vid = first[1]; bkey = first[2]
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except:
        await update.message.reply_text("Usage: /bulkbin <vid> <bkey>\n374646 x1"); return
    added, skipped = 0, 0
    for line in lines[1:]:
        line = line.strip()
        if not line: continue
        parts = line.replace("x", " ").replace("X", " ").split()
        if len(parts) < 2:
            skipped += 1; continue
        try:
            bin_num = parts[0]; qty = int(parts[1])
            if qty <= 0:
                skipped += 1; continue
            STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; added += 1
        except ValueError:
            skipped += 1
    total = sum(STORE[vid]["bases"][bkey]["bins"].values()); await save_data()
    await update.message.reply_text(
        f"✅ *Bulk Add Complete*\n\nVendor: `{vid}` / `{bkey}`\n"
        f"Added/updated: *{added}* BINs\nSkipped: *{skipped}* lines\n"
        f"Total stock now: *{total}* fullz",
        parse_mode="Markdown")

# ═════════════════════════════════════════════════════════════════════════════
# SECURITY & ORDER BLOCK
# ═════════════════════════════════════════════════════════════════════════════

def get_blocked_message(balance, item_price, back_cb):
    if balance == 0:
        return (
            "❌ *Insufficient Balance!*\n\n"
            f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\n"
            "Please top up your wallet first.",
            InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top Up Wallet", callback_data="wallet")]]),
        )
    if balance < MIN_DEPOSIT_REQUIRED:
        return (
            "🛑 *Order Blocked*\n⚠️ *Transaction Incomplete*\n"
            "Your account balance does not meet the minimum deposit required for new users.\n"
            f" • 💰 *Current Balance:* £{balance:.2f}\n"
            f" • 📋 *Required Minimum:* £{MIN_DEPOSIT_REQUIRED:.2f}\n"
            "Please fund your account to proceed.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Top Up",  callback_data="wallet")],
                [InlineKeyboardButton("⬅️ Back",    callback_data=back_cb)],
                [InlineKeyboardButton("🌍 Menu",    callback_data="back")],
            ]),
        )
    if balance < item_price:
        return (
            "❌ *Insufficient Balance!*\n\n"
            f"This item costs £{item_price:.2f} but your wallet balance is £{balance:.2f}.\n\n"
            "Please top up your wallet first.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                InlineKeyboardButton("⬅️ Back",   callback_data=back_cb),
            ]]),
        )
    return None, None

# ═════════════════════════════════════════════════════════════════════════════
# BUTTON HANDLER — await query.answer() is the FIRST line (no-lag rule)
# ═════════════════════════════════════════════════════════════════════════════

_LOG_SKIP = {
    "back", "noop",               # pure navigation / no-op
    "broadcast_cancel",           # admin flow — not useful to log
    "refund_cancel",              # user flow — not useful to log
}
_LOG_SKIP_PREFIXES = (
    "bpage|", "lhwp|",            # pagination — too noisy
)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data

    # check_pay needs show_alert — must answer BEFORE the default answer() below
    if data.startswith("check_pay|"):
        await query.answer(
            "❌ Error: Payment not found on the blockchain.\n\n"
            "Please allow 5-15 minutes for confirmations,\n"
            "or use 'Send Screenshot' if you have already paid.",
            show_alert=True)
        return

    await query.answer()      # ← default answer for all other callbacks

    # ── Universal interaction log ────────────────────────────────────────────
    if data not in _LOG_SKIP and not data.startswith(_LOG_SKIP_PREFIXES):
        log_bg(context.application,
            f"🖱 *Button Press*\n👤 {user_tag(update)}\n🪪 `{uid}`\n📌 `{data}`")

    # ── Welcome / join gate ─────────────────────────────────────────────────
    if data == "agree_rules":
        try:
            is_member, reason = await check_channel_membership(context.bot, uid)
        except:
            is_member, reason = False, "error"
        if reason == "error":
            await query.edit_message_text(
                "⚠️ Could not verify membership. Try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Retry", callback_data="agree_rules")]]))
            return
        if not is_member:
            await query.edit_message_text(
                "⛔️ You haven't joined yet! Tap 'Join Channel to Continue' first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel", url=JOIN_CHANNEL_URL)],
                    [InlineKeyboardButton("✅ I've Joined",  callback_data="agree_rules")],
                ]))
            return
        agreed_users.add(uid)
        channel_verified.add(uid)
        await save_data()
        log_bg(context.application,
            f"✅ *Channel Verified*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        await query.edit_message_text(
            main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    # Clear any pending text-input modes
    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty"):
        context.user_data.pop(_k, None)

    # ── Broadcast confirm / cancel ───────────────────────────────────────────
    if data == "broadcast_confirm":
        if not is_admin(update): return
        pending = context.user_data.pop("pending_broadcast", None)
        context.user_data.pop("awaiting_broadcast", None)
        if not pending:
            await query.edit_message_text("❌ No pending broadcast found. Use /broadcast again.")
            return
        status_msg = await query.edit_message_text(
            "📢 *Broadcast starting…*", parse_mode="Markdown")
        bot  = context.application.bot
        sent, failed = await _do_broadcast(bot, status_msg, pending)
        total = len(_broadcast_targets())
        log_bg(context.application,
            f"📢 *Broadcast sent*\n👤 {user_tag(update)}\n"
            f"✅ Sent: {sent} / ❌ Failed: {failed} / 👥 Total: {total}")
        await status_msg.edit_text(
            f"📢 *Broadcast Complete!*\n\n"
            f"✅ Delivered: *{sent}*\n❌ Failed: *{failed}*\n👥 Total users: *{total}*",
            parse_mode="Markdown")
        return

    if data == "broadcast_cancel":
        if not is_admin(update): return
        context.user_data.pop("pending_broadcast", None)
        context.user_data.pop("awaiting_broadcast", None)
        await query.edit_message_text("❌ Broadcast cancelled.")
        return

    # ── Deliver file (tapped from log channel) ──────────────────────────────
    if data.startswith("deliver_to|"):
        if not is_admin(update): return
        target_uid = int(data.split("|")[1])
        context.user_data["deliver_to"] = target_uid
        context.user_data.pop("pending_file", None)
        order_info = pending_orders.get(target_uid, "")
        preview    = f"\n\n📋 *Pending order:*\n`{order_info}`" if order_info else ""
        await query.answer("📦 Delivery mode active", show_alert=False)
        await context.application.bot.send_message(
            chat_id=query.from_user.id,
            text=f"📦 *Delivery target set:* `{target_uid}`{preview}\n\n_Send the file to this chat._",
            parse_mode="Markdown")
        return

    if data.startswith("confirm_deliver|"):
        if not is_admin(update): return
        target_uid  = int(data.split("|")[1])
        file_info   = context.user_data.pop("pending_file", None)
        if not file_info:
            await query.edit_message_text("❌ No file found. Please send the file again.")
            return
        caption = pending_orders.pop(target_uid, "✅ Your order has been delivered.")
        bot     = context.application.bot
        try:
            ftype, fid = file_info["type"], file_info["file_id"]
            if   ftype == "document": await bot.send_document(chat_id=target_uid, document=fid, caption=caption)
            elif ftype == "photo":    await bot.send_photo(   chat_id=target_uid, photo=fid,    caption=caption)
            elif ftype == "video":    await bot.send_video(   chat_id=target_uid, video=fid,    caption=caption)
            elif ftype == "audio":    await bot.send_audio(   chat_id=target_uid, audio=fid,    caption=caption)
            delivery_timestamps[target_uid] = datetime.utcnow()
            context.user_data.pop("deliver_to", None)
            await query.edit_message_text(f"✅ *File delivered to* `{target_uid}`.", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Delivery failed: {e}")
        return

    if data == "cancel_deliver":
        if not is_admin(update): return
        context.user_data.pop("deliver_to",   None)
        context.user_data.pop("pending_file", None)
        await query.edit_message_text("❌ *Delivery cancelled.*", parse_mode="Markdown")
        return

    if data == "refund_cancel":
        context.user_data.pop("awaiting_refund_screenshot", None)
        await query.edit_message_text("❌ Refund request cancelled.")
        return

    if data.startswith("approve_refund|"):
        target_uid = int(data.split("|")[1])
        try:
            await context.application.bot.send_message(
                chat_id=target_uid,
                text="✅ *Refund Approved*\n\nYour replacement will be delivered shortly.",
                parse_mode="Markdown")
        except Exception:
            pass
        try:
            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n✅ *Refund APPROVED* by {user_tag(update)}",
                parse_mode="Markdown")
        except Exception:
            pass
        return

    if data.startswith("reject_refund|"):
        target_uid = int(data.split("|")[1])
        try:
            await context.application.bot.send_message(
                chat_id=target_uid,
                text="❌ *Refund Rejected*\n\nYour refund request could not be approved.\n"
                     "Please contact @HekTikz for further assistance.",
                parse_mode="Markdown")
        except Exception:
            pass
        try:
            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n❌ *Refund REJECTED* by {user_tag(update)}",
                parse_mode="Markdown")
        except Exception:
            pass
        return

    # ── Navigation ───────────────────────────────────────────────────────────
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
        await query.edit_message_text(
            f"🔶 *£{amount} Top-Up*\n\nChoose your payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text(
            "💰 *Custom Amount*\n\nType the £ amount (minimum £70):\nExample: `150`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]),
            parse_mode="Markdown")
        return

    if data.startswith("pay|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        address = WALLETS.get(coin, "Address not configured")
        await query.edit_message_text("⏳ Fetching live price...")
        prices = await get_crypto_prices()
        crypto_amt = round(amount / prices[coin], 6) if (prices and coin in prices) else "?"
        log_bg(context.application,
            f"💳 *Invoice Generated*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"💰 £{amount} via {coin}"
            + (f" = `{crypto_amt}` {coin}" if crypto_amt != "?" else "")
            + f"\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        amt_line = f"`{crypto_amt}` {coin} (£{amount})" if crypto_amt != "?" else f"£{amount} in {coin}"
        sep = "— — — — — — — — — — — — —"
        await query.edit_message_text(
            f"🗂 *PAYMENT INVOICE GENERATED*\n{sep}\n\n"
            f"🌐 *NETWORK:* {coin}\n"
            f"⚠️ *WARNING:* Send ONLY {coin}.\n\n"
            f"💰 *AMOUNT DUE:* {amt_line}\n"
            f"📬 *DEPOSIT ADDRESS:*\n`{address}`\n\n"
            f"{sep}\n\n"
            f"⏳ *Status:* Waiting for payment...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Payment",   callback_data=f"check_pay|{coin}|{amount}")],
                [InlineKeyboardButton("📸 Send Screenshot", callback_data=f"send_ss|{coin}|{amount}")],
                [InlineKeyboardButton("❌ Cancel",          callback_data=f"amt|{amount}")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("send_ss|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        context.user_data["awaiting_screenshot"] = {"coin": coin, "amount": amount}
        await query.edit_message_text(
            f"📸 *UPLOAD SCREENSHOT*\n— — — — — — — — — — — — —\n\n"
            f"Please send the transaction screenshot/receipt for *£{amount}* now.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_ss|{coin}|{amount}")]
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("cancel_ss|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        context.user_data.pop("awaiting_screenshot", None)
        await query.edit_message_text(
            f"🔶 *£{amount} Top-Up*\n\nChoose your payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data.startswith("approve_pay|"):
        _, buyer_uid, amount = data.split("|")
        buyer_uid, amount = int(buyer_uid), int(amount)
        user_balances[buyer_uid] = round(user_balances.get(buyer_uid, 0) + amount, 2)
        await save_data()
        try:
            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n✅ *APPROVED* by {user_tag(update)}",
                parse_mode="Markdown")
        except Exception:
            pass
        try:
            await context.application.bot.send_message(
                chat_id=buyer_uid,
                text=f"🎉 *PAYMENT APPROVED*\n— — — — — — — — — — — — —\n\n"
                     f"Your payment of *£{amount}* has been successfully verified "
                     f"and added to your balance.\n\n"
                     f"💷 *New Balance:* £{user_balances[buyer_uid]:.2f}",
                parse_mode="Markdown")
        except Exception:
            pass
        log_bg(context.application,
            f"✅ *Payment Approved*\n🪪 `{buyer_uid}`\n💷 £{amount} added\n"
            f"👤 Approved by {user_tag(update)}")
        return

    if data.startswith("reject_pay|"):
        buyer_uid = int(data.split("|")[1])
        try:
            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n❌ *REJECTED* by {user_tag(update)}",
                parse_mode="Markdown")
        except Exception:
            pass
        try:
            await context.application.bot.send_message(
                chat_id=buyer_uid,
                text=f"❌ *Payment Rejected*\n— — — — — — — — — — — — —\n\n"
                     f"Your top-up could not be verified. This may be due to an "
                     f"incomplete payment or missing transaction fees.\n\n"
                     f"Please contact @HekTikz for assistance.",
                parse_mode="Markdown")
        except Exception:
            pass
        log_bg(context.application,
            f"❌ *Payment Rejected*\n🪪 `{buyer_uid}`\n👤 Rejected by {user_tag(update)}")
        return

    # ── Store ────────────────────────────────────────────────────────────────
    if data == "store":
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("vendor|"):
        vid = data.split("|")[1]
        if vid not in STORE: return
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n\nSelect a base:",
            reply_markup=base_select_keyboard(vid), parse_mode="Markdown")
        return

    if data.startswith("base|"):
        _, vid, bkey = data.split("|", 2)
        base      = STORE[vid]["bases"][bkey]
        total_qty = sum(base["bins"].values())
        kbd, total_pages = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {total_qty}\n\nSelect BIN group:\n_Page 1 of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bpage|"):
        _, vid, bkey, page = data.split("|", 3); page = int(page)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {sum(base['bins'].values())}\n\nSelect BIN group:\n_Page {page+1} of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid
        context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(
            f"🔍 *BIN Search — {STORE[vid]['label']}*\n\nType the BIN number:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]),
            parse_mode="Markdown")
        return

    if data.startswith("buybin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        base  = STORE[vid]["bases"][bkey]
        qty   = base["bins"].get(bin_num, 0)
        if qty == 0: return
        price = base["price_per_card"]
        context.user_data["buy_bin"]     = {"vid": vid, "bkey": bkey, "bin_num": bin_num, "page": page, "price": price, "available": qty}
        context.user_data["awaiting_qty"] = True
        await query.edit_message_text(
            f"👤 *Vendor:* {STORE[vid]['label']}\n📦 *Base:* {base['label']}\n"
            f"💳 *BIN:* {bin_num}\n🗂 *Available:* {qty} fullz\n\n"
            f"💷 *Price:* £{price:.2f} per fullz\n\nEnter quantity (1-{qty}):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"bpage|{vid}|{bkey}|{page}")]]),
            parse_mode="Markdown")
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
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total, 2)
        base["bins"][bin_num] = stock - buy_qty
        if base["bins"][bin_num] <= 0:
            del base["bins"][bin_num]
        await save_data()
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"💳 BIN: {bin_num}\n🗂 Quantity: {buy_qty} fullz\n"
            f"💷 Price: £{total:.2f}\n💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — BIN*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"💳 BIN: {bin_num} | Qty: {buy_qty}\n💷 Paid: £{total:.2f}\n"
            f"💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n💳 BIN: *{bin_num}*\n🗂 *{buy_qty} fullz*\n"
            f"💷 Paid: *£{total:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]),
            parse_mode="Markdown")
        return

    if data == "deads":
        await query.edit_message_text("💀 *Deads*\n\nSelect a package:", reply_markup=deads_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("dbuy|"):
        key     = data.split("|")[1]
        item    = next(((l, p) for l, p, k in DEADS_ITEMS if k == key), None)
        if not item: return
        label, price = item
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n💀 *{label}*\n💷 *Price: £{price:,}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"dconf|{key}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data="deads")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("dconf|"):
        key  = data.split("|")[1]
        item = next(((l, p) for l, p, k in DEADS_ITEMS if k == key), None)
        if not item: return
        label, price = item
        balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "deads")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); await save_data()
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"💀 Item: {label}\n💷 Price: £{price:,}\n"
            f"💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — Deads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"💀 {label}\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n💀 *{label}*\n💷 Paid: *£{price:,}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\n📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="deads")]]),
            parse_mode="Markdown")
        return

    # ── Leads ────────────────────────────────────────────────────────────────
    if data == "leads":
        await query.edit_message_text(
            f"🌍 *Leads Directory*\n\nSelect a country:",
            reply_markup=country_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("lc|"):
        cc = data.split("|")[1]
        if cc not in LEADS: return
        d     = LEADS[cc]
        total = sum(sum(v["items"].values()) for v in d.get("verticals", {}).values())
        await query.edit_message_text(
            f"*Country:* {d['flag']} {d['name']}\n*Stock:* {total:,} total records\n\nSelect a category:",
            reply_markup=verticals_keyboard(cc), parse_mode="Markdown")
        return

    if data.startswith("lvert|"):
        _, cc, vert_key = data.split("|", 2)
        if cc not in LEADS or vert_key not in LEADS[cc]["verticals"]: return
        d         = LEADS[cc]
        vert_data = d["verticals"][vert_key]
        if vert_key == "ledger":
            n_models = len(vert_data["items"])
            await query.edit_message_text(
                f"*Country:* {d['flag']} {d['name']}\n*Category:* {vert_data['label']}\n"
                f"*Available:* {n_models} hardware wallet models\n\nSelect a device:",
                reply_markup=hw_keyboard(cc, 0), parse_mode="Markdown")
        else:
            total = sum(vert_data["items"].values())
            await query.edit_message_text(
                f"*Country:* {d['flag']} {d['name']}\n*Category:* {vert_data['label']}\n"
                f"*Available:* {total:,} records\n\nSelect a dataset item:",
                reply_markup=dataset_item_keyboard(cc, vert_key), parse_mode="Markdown")
        return

    if data.startswith("lhwp|"):
        _, cc, page_s = data.split("|", 2)
        if cc not in LEADS: return
        d         = LEADS[cc]
        vert_data = d["verticals"]["ledger"]
        n_models  = len(vert_data["items"])
        await query.edit_message_text(
            f"*Country:* {d['flag']} {d['name']}\n*Category:* {vert_data['label']}\n"
            f"*Available:* {n_models} hardware wallet models\n\nSelect a device:",
            reply_markup=hw_keyboard(cc, int(page_s)), parse_mode="Markdown")
        return

    if data == "noop":
        return

    if data.startswith("lk|"):
        _, cc, vert_key, item_name = data.split("|", 3)
        if cc not in LEADS: return
        stock = LEADS[cc]["verticals"][vert_key]["items"].get(item_name, 0)
        d     = LEADS[cc]
        await query.edit_message_text(
            f"*Country:* {d['flag']} {d['name']}\n*Dataset:* {item_name}\n"
            f"*Available:* {stock:,} records\n\nSelect quantity:",
            reply_markup=qty_keyboard(cc, vert_key, item_name), parse_mode="Markdown")
        return

    if data.startswith("lq|"):
        _, cc, vert_key, item_name, qty_str = data.split("|", 4)
        qty     = int(qty_str)
        price   = dict(VERT_PRICING.get(vert_key, LEADS_PRICING)).get(qty, 0)
        d       = LEADS[cc]
        stock   = d["verticals"][vert_key]["items"].get(item_name, 0)
        balance = user_balances.get(uid, 0)
        if stock < qty: return
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n🌍 *Country:* {d['flag']} {d['name']}\n"
            f"📡 *Dataset:* {item_name}\n🗂 *Quantity:* {qty:,} records\n💷 *Price: £{price}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{vert_key}|{item_name}|{qty}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"lk|{cc}|{vert_key}|{item_name}")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("lb|"):
        _, cc, vert_key, item_name, qty_str = data.split("|", 4)
        qty     = int(qty_str)
        price   = dict(VERT_PRICING.get(vert_key, LEADS_PRICING)).get(qty, 0)
        balance = user_balances.get(uid, 0)
        d       = LEADS[cc]
        blocked_text, blocked_kbd = get_blocked_message(balance, price, f"lk|{cc}|{vert_key}|{item_name}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); await save_data()
        d["verticals"][vert_key]["items"][item_name] = max(0, d["verticals"][vert_key]["items"][item_name] - qty)
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"🌍 Country: {d['name']}\n📂 Category: {vert_key.title()}\n"
            f"📄 Dataset: {item_name}\n🗂 Quantity: {qty:,} records\n"
            f"💷 Price: £{price}\n💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — Leads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"🌍 {d['flag']} {d['name']} | {vert_key} | {item_name}\n"
            f"🗂 {qty:,} records\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n🌍 *{d['flag']} {d['name']}* — {item_name}\n"
            f"🗂 *{qty:,} records*\n💷 Paid: *£{price}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]),
            parse_mode="Markdown")
        return

    # ── Scanner ──────────────────────────────────────────────────────────────
    if data == "scanner":
        await query.edit_message_text(
            "🔍 *Scanner*\n\n👆 Select a scanner to verify your data.",
            reply_markup=scanner_keyboard("all", 0), parse_mode="Markdown")
        return

    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        await query.edit_message_text(
            "🔍 *Scanner*\n\n👆 Select a scanner to verify your data.",
            reply_markup=scanner_keyboard(cat, pg), parse_mode="Markdown")
        return

    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🔍 *{label}*\n\n💰 Price: *${price:.2f} / k*\nYour balance: *£{balance:.2f}*\n\nSelect quantity:",
            reply_markup=scanner_qty_keyboard(idx, category), parse_mode="Markdown")
        return

    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|")
        idx   = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n🔍 *{label}*\n🗂 Quantity: *{qty_k}k*\n"
            f"💷 *Total: £{total_gbp:.2f}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"sni|{idx}")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|")
        idx   = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): return
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, total_gbp, f"sni|{idx}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total_gbp, 2); await save_data()
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"🔍 Scanner: {label}\n🗂 Quantity: {qty_k}k records\n"
            f"💷 Price: £{total_gbp:.2f}\n💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — Scanner*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"🔍 {label} | {qty_k}k\n💷 Paid: £{total_gbp:.2f}\n"
            f"💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n🔍 *{label}*\n🗂 *{qty_k}k records*\n"
            f"💷 Paid: *£{total_gbp:.2f}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]),
            parse_mode="Markdown")
        return

    # ── Targeted Source ──────────────────────────────────────────────────────
    if data == "tsource":
        await query.edit_message_text(
            "📨 *Spam Service*\n\nSelect a category below:",
            reply_markup=tsource_main_keyboard(), parse_mode="Markdown")
        return

    if data == "ts_aged":
        await query.edit_message_text(
            "🏦 *Bank Page — Fresh Page*\n\n"
            "📋 *Select a page below:*\n"
            "_Note: Anti-Red pages include encrypted results._",
            reply_markup=ts_fullz_items_keyboard(), parse_mode="Markdown")
        return

    if data == "ts_crypto":
        await query.edit_message_text(
            "🪙 *Crypto Page*\n\n"
            "📋 *Select a platform below:*",
            reply_markup=ts_crypto_items_keyboard(), parse_mode="Markdown")
        return

    if data == "ts_services":
        await query.edit_message_text(
            f"🛠 *Additional Services*\n\n"
            f"🌐 Book Sms/email sendouts Service (SID)\n"
            f"📥 My Page And Email/mobile Leads Or\n"
            f"   Your Hosted Page & Leads\n\n"
            f"💬 Want To Learn How To Spam Your Own Fullz\n\n"
            f"📩 PM Admin @{SUPER_ADMIN} to discuss requirements.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{SUPER_ADMIN}"),
                 InlineKeyboardButton("⬅️ Back", callback_data="tsource")],
            ]),
            parse_mode="Markdown")
        return

    # ── Fullz item selected → confirmation ───────────────────────────────────
    if data.startswith("tsfi|"):
        idx     = int(data.split("|")[1])
        if idx >= len(TS_FULLZ_ITEMS): return
        name, price = TS_FULLZ_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"🏦 *Bank Page — Fullz*\n"
            f"📄 *Page:* {name}\n"
            f"💷 *Price: £{price}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"tsfic|{idx}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data="ts_aged")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("tsfic|"):
        idx     = int(data.split("|")[1])
        if idx >= len(TS_FULLZ_ITEMS): return
        name, price = TS_FULLZ_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_aged")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); await save_data()
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"🏦 Bank Page: {name}\n💷 Price: £{price}\n"
            f"💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — Bank Page*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"‼️ Page: {name}\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n‼️ *{name}* Fullz Page\n"
            f"💷 Paid: *£{price}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]),
            parse_mode="Markdown")
        return

    # ── Crypto item selected → confirmation ───────────────────────────────────
    if data.startswith("tsci|"):
        idx     = int(data.split("|")[1])
        if idx >= len(TS_CRYPTO_ITEMS): return
        name, price = TS_CRYPTO_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"🪙 *Crypto Page*\n"
            f"📄 *Platform:* {name}\n"
            f"💷 *Price: £{price}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"tscic|{idx}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data="ts_crypto")],
            ]),
            parse_mode="Markdown")
        return

    if data.startswith("tscic|"):
        idx     = int(data.split("|")[1])
        if idx >= len(TS_CRYPTO_ITEMS): return
        name, price = TS_CRYPTO_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        blocked_text, blocked_kbd = get_blocked_message(balance, price, "ts_crypto")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2); await save_data()
        pending_orders[uid] = (
            f"✅ Purchase Successful!\n\n"
            f"🪙 Crypto Page: {name}\n💷 Price: £{price}\n"
            f"💰 Remaining balance: £{user_balances[uid]:.2f}\n\n"
            f"If there are any issues, type /refund within 3 minutes of delivery")
        log_purchase_bg(context.application,
            f"🛒 *Purchase — Crypto Page*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"🪙 Platform: {name}\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}", uid)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n🪙 *{name}* Crypto Page\n"
            f"💷 Paid: *£{price}*\n💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"📦 Your file will be delivered to you shortly.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]),
            parse_mode="Markdown")
        return

# ═════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ═════════════════════════════════════════════════════════════════════════════

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # ── Admin broadcast text capture ─────────────────────────────────────────
    if is_admin(update) and context.user_data.get("awaiting_broadcast"):
        context.user_data.pop("awaiting_broadcast", None)
        text = update.message.text or ""
        if not text.strip():
            await update.message.reply_text("❌ Empty message — broadcast cancelled.")
            return
        pending = {"type": "text", "text": text}
        context.user_data["pending_broadcast"] = pending
        await _show_broadcast_preview(update.message, context, pending)
        return

    if context.user_data.get("awaiting_qty"):
        info    = context.user_data.get("buy_bin", {})
        text    = update.message.text.strip()
        try:
            buy_qty = int(text)
        except ValueError:
            await update.message.reply_text("Please enter a valid number."); return
        available = info.get("available", 0)
        if buy_qty < 1 or buy_qty > available:
            await update.message.reply_text(f"Please enter a number between 1 and {available}."); return
        context.user_data["awaiting_qty"] = False
        vid, bkey, bin_num = info["vid"], info["bkey"], info["bin_num"]
        price = info["price"]
        total = round(price * buy_qty, 2)
        balance = user_balances.get(update.effective_user.id, 0)
        await update.message.reply_text(
            f"🛒 *Purchase Confirmation*\n\n💳 BIN: *{bin_num}*\n🗂 Quantity: *{buy_qty} fullz*\n"
            f"💰 Per fullz: *£{price:.2f}*\n💷 *Total: £{total:.2f}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"cfmqty|{vid}|{bkey}|{bin_num}|{buy_qty}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"vendor|{vid}")],
            ]),
            parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_custom"):
        text = update.message.text.strip().replace("£", "")
        try:
            amount = int(float(text))
            if amount < MIN_TOPUP:
                await update.message.reply_text(f"Minimum is £{MIN_TOPUP}."); return
        except ValueError:
            await update.message.reply_text("Enter a number e.g. 150"); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(
            f"🔶 *£{amount} Top-Up*\n\nChoose payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num = update.message.text.strip()
        vid     = context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        buttons = []
        for bkey, base in STORE.get(vid, {}).get("bases", {}).items():
            qty = base["bins"].get(bin_num)
            if qty:
                buttons.append([InlineKeyboardButton(
                    f"{base['label']} - {bin_num} ({qty})",
                    callback_data=f"buybin|{vid}|{bkey}|{bin_num}|0")])
        if buttons:
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
            await update.message.reply_text(
                f"👤 *Vendor:* {STORE[vid]['label']}\n\n🔍 *Results for {bin_num}:*",
                reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ BIN *{bin_num}* not found in {STORE.get(vid, {}).get('label', 'this vendor')}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]),
                parse_mode="Markdown")
        return

# ═════════════════════════════════════════════════════════════════════════════
# ERROR HANDLER & MAIN
# ═════════════════════════════════════════════════════════════════════════════

async def error_handler(update, context):
    logger.error("🔥 Unhandled exception:", exc_info=context.error)

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set!")
    load_data()

    # Larger connection pool so many concurrent Telegram API calls don't queue up.
    request = HTTPXRequest(
        connect_timeout=30.0, read_timeout=30.0,
        write_timeout=30.0,   pool_timeout=30.0,
        connection_pool_size=64,
    )
    get_updates_request = HTTPXRequest(
        connect_timeout=30.0, read_timeout=45.0,
        write_timeout=30.0,   pool_timeout=30.0,
        connection_pool_size=8,
    )
    app = (Application.builder()
           .token(BOT_TOKEN)
           .request(request)
           .get_updates_request(get_updates_request)
           # Process up to 256 updates simultaneously — each user's handler
           # runs in its own asyncio task so no one waits for anyone else.
           .concurrent_updates(256)
           .build())

    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("balance",         cmd_balance))
    app.add_handler(CommandHandler("wallet",          cmd_wallet))
    app.add_handler(CommandHandler("targeted",        cmd_targeted))
    app.add_handler(CommandHandler("contact",         cmd_contact))
    app.add_handler(CommandHandler("support",         cmd_contact))
    app.add_handler(CommandHandler("help",            cmd_help))
    app.add_handler(CommandHandler("adminlogin",      cmd_adminlogin))
    app.add_handler(CommandHandler("adminlogout",     cmd_adminlogout))
    app.add_handler(CommandHandler("adminhelp",       cmd_adminhelp))
    app.add_handler(CommandHandler("addbalance",      cmd_addbalance))
    app.add_handler(CommandHandler("removebalance",   cmd_removebalance))
    app.add_handler(CommandHandler("setbalance",      cmd_setbalance))
    app.add_handler(CommandHandler("checkbalance",    cmd_checkbalance))
    app.add_handler(CommandHandler("setstock",        cmd_setstock))
    app.add_handler(CommandHandler("addvendor",       cmd_addvendor))
    app.add_handler(CommandHandler("removevendor",    cmd_removevendor))
    app.add_handler(CommandHandler("addbase",         cmd_addbase))
    app.add_handler(CommandHandler("removebase",      cmd_removebase))
    app.add_handler(CommandHandler("addbin",          cmd_addbin))
    app.add_handler(CommandHandler("removebin",       cmd_removebin))
    app.add_handler(CommandHandler("listbins",        cmd_listbins))
    app.add_handler(CommandHandler("clearbase",       cmd_clearbase))
    app.add_handler(CommandHandler("listusers",       cmd_listusers))
    app.add_handler(CommandHandler("updatelead",      cmd_updatelead))
    app.add_handler(CommandHandler("bulkbin",         cmd_bulkbin))
    app.add_handler(CommandHandler("broadcast",       cmd_broadcast))
    app.add_handler(CommandHandler("deliver",         cmd_deliver))
    app.add_handler(CommandHandler("refund",          cmd_refund))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(
        (filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & ~filters.COMMAND,
        file_delivery_handler))
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
