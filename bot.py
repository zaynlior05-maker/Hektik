import os
import json
import logging
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
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
LOGS_FILE = os.path.join(DATA_DIR, "admin_activity.log")
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
user_last_active = {}
logged_in_admins = set()
channel_verified = set()

live_stock    = {"leads": 63_629_085} 
TOPUP_AMOUNTS = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]
BINS_PER_PAGE = 20   
ITEMS_PER_PAGE = 8

# External Data Cache
cached_external_apis = {
    "crypto": {}, "network": {}, "business": {}, "bank": {}, "nodes": {}
}

# ── Dynamic Pricing Configuration (Leads only, Scanner reverted to static) ────
DYNAMIC_LEADS_PRICING = {
    "network":  {1000: 15, 2000: 30, 3000: 45, 4000: 50, 5000: 60, 6000: 65, 7000: 70, 8000: 80, 10000: 100, 15000: 125, 20000: 150, 25000: 175, 30000: 200, 50000: 300, 100000: 600},
    "bank":     {1000: 20, 2000: 40, 5000: 80, 10000: 150, 25000: 350},
    "business": {1000: 25, 5000: 100, 10000: 175, 25000: 400},
    "crypto":   {1000: 30, 5000: 120, 10000: 200, 25000: 450},
    "nodes":    {1000: 40, 5000: 180, 10000: 300}
}

# ── Store Data (BINS) ─────────────────────────────────────────────────────────
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
                    "416549": 9, "416598": 16, "446223": 1, "446261": 7
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
                "bins": {"400115": 4, "401178": 2, "402601": 3, "403628": 1},
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

# ── OLD SCANNER MIGRATION ─────────────────────────────────────────────────────
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

SCAN_CATS = {"all": "All •", "socials": "Socials", "crypto": "Crypto", "shopping": "Shop...", "carrier": "Carrier"}
SCANNER_PER_PAGE = 10
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]

# ── OLD LEADS COUNTRY LIST MIGRATION ──────────────────────────────────────────
LEADS = {
    "AU": {"flag":"🇦🇺","name":"Australia",      "carriers":{"Telstra":4_200_000,"Optus":3_100_000,"Vodafone":1_800_000,"Boost Mobile":620_000,"TPG":430_000}},
    "AT": {"flag":"🇦🇹","name":"Austria",        "carriers":{"A1":1_540_000,"Magenta":890_000,"Drei":760_000,"Spusu":210_000}},
    "BH": {"flag":"🇧🇭","name":"Bahrain",        "carriers":{"Batelco":480_000,"Zain":390_000,"STC":210_000,"Viva":170_000}},
    "BE": {"flag":"🇧🇪","name":"Belgium",        "carriers":{"Proximus":1_920_000,"Orange":1_340_000,"Base":980_000}},
    "BR": {"flag":"🇧🇷","name":"Brazil",         "carriers":{"Vivo":7_800_000,"Claro":6_500_000,"TIM":5_200_000,"Oi":2_100_000}},
    "BG": {"flag":"🇧🇬","name":"Bulgaria",       "carriers":{"A1":1_100_000,"Telenor":890_000,"Vivacom":760_000}},
    "CA": {"flag":"🇨🇦","name":"Canada",         "carriers":{"Rogers":4_100_000,"Bell":3_800_000,"Telus":3_500_000,"Fido":980_000,"Koodo":760_000}},
    "CY": {"flag":"🇨🇾","name":"Cyprus",         "carriers":{"Cyta":340_000,"MTN":210_000,"Epic":180_000}},
    "CZ": {"flag":"🇨🇿","name":"Czech Republic", "carriers":{"T-Mobile":2_100_000,"O2":1_800_000,"Vodafone":1_400_000}},
    "DK": {"flag":"🇩🇰","name":"Denmark",        "carriers":{"TDC":1_540_000,"Telenor":1_100_000,"Telia":980_000,"Tre":760_000}},
    "EE": {"flag":"🇪🇪","name":"Estonia",        "carriers":{"Telia":430_000,"Elisa":380_000,"Tele2":290_000}},
    "FI": {"flag":"🇫🇮","name":"Finland",        "carriers":{"Elisa":1_800_000,"DNA":1_500_000,"Telia":1_200_000}},
    "FR": {"flag":"🇫🇷","name":"France",         "carriers":{"Orange":6_200_000,"SFR":4_800_000,"Bouygues":4_100_000,"Free Mobile":3_500_000}},
    "DE": {"flag":"🇩🇪","name":"Germany",        "carriers":{"Telekom":8_900_000,"Vodafone":7_200_000,"O2":5_800_000,"1&1":1_400_000}},
    "GR": {"flag":"🇬🇷","name":"Greece",         "carriers":{"Cosmote":2_800_000,"Vodafone":1_900_000,"Wind Hellas":1_400_000,"Nova":680_000}},
    "HU": {"flag":"🇭🇺","name":"Hungary",        "carriers":{"Telekom":2_100_000,"Yettel":1_400_000,"Vodafone":980_000}},
    "IS": {"flag":"🇮🇸","name":"Iceland",        "carriers":{"Siminn":180_000,"Vodafone":140_000,"Nova":110_000}},
    "IE": {"flag":"🇮🇪","name":"Ireland",        "carriers":{"Eir":833_503,"Tesco Mobile":520_700,"Three A":351_645,"Three B":861_444,"Vodafone":1_720_550}},
    "IT": {"flag":"🇮🇹","name":"Italy",          "carriers":{"TIM":5_900_000,"Vodafone":4_200_000,"WindTre":5_100_000,"Iliad":1_800_000,"PosteMobile":890_000}},
    "LV": {"flag":"🇱🇻","name":"Latvia",         "carriers":{"LMT":540_000,"Tele2":430_000,"Bite":320_000}},
    "LT": {"flag":"🇱🇹","name":"Lithuania",      "carriers":{"Tele2":890_000,"Bite":760_000,"Telia":540_000}},
    "MY": {"flag":"🇲🇾","name":"Malaysia",       "carriers":{"Maxis":4_200_000,"Celcom":3_100_000,"Digi":3_800_000,"U Mobile":1_400_000,"Unifi":980_000}},
    "MT": {"flag":"🇲🇹","name":"Malta",          "carriers":{"GO":180_000,"Melita":140_000,"Epic":110_000}},
    "NL": {"flag":"🇳🇱","name":"Netherlands",    "carriers":{"KPN":3_200_000,"VodafoneZiggo":2_800_000,"T-Mobile":2_100_000,"Tele2":890_000}},
    "NZ": {"flag":"🇳🇿","name":"New Zealand",    "carriers":{"Spark":1_800_000,"One NZ":1_400_000,"2degrees":980_000}},
    "NO": {"flag":"🇳🇴","name":"Norway",         "carriers":{"Telenor":2_400_000,"Telia":1_800_000,"Ice":760_000}},
    "PL": {"flag":"🇵🇱","name":"Poland",         "carriers":{"Orange":4_100_000,"Play":3_800_000,"Plus":3_200_000,"T-Mobile":2_900_000}},
    "PT": {"flag":"🇵🇹","name":"Portugal",       "carriers":{"NOS":2_800_000,"MEO":2_400_000,"Vodafone":1_900_000}},
    "PR": {"flag":"🇵🇷","name":"Puerto Rico",    "carriers":{"Claro":1_100_000,"Liberty":540_000,"T-Mobile":890_000}},
    "QA": {"flag":"🇶🇦","name":"Qatar",          "carriers":{"Ooredoo":980_000,"Vodafone Qatar":760_000}},
    "RO": {"flag":"🇷🇴","name":"Romania",        "carriers":{"Orange":3_200_000,"Vodafone":2_800_000,"Digi":2_100_000,"Telekom":1_400_000}},
    "SG": {"flag":"🇸🇬","name":"Singapore",      "carriers":{"Singtel":2_100_000,"StarHub":1_400_000,"M1":980_000,"TPG":320_000}},
    "SK": {"flag":"🇸🇰","name":"Slovakia",       "carriers":{"Slovak Telekom":1_400_000,"Orange":1_100_000,"O2":760_000}},
    "SI": {"flag":"🇸🇮","name":"Slovenia",       "carriers":{"A1":540_000,"Telekom SI":430_000,"T-2":210_000}},
    "ZA": {"flag":"🇿🇦","name":"South Africa",   "carriers":{"Vodacom":5_200_000,"MTN":4_800_000,"Cell C":2_100_000,"Telkom":1_400_000}},
    "ES": {"flag":"🇪🇸","name":"Spain",          "carriers":{"Movistar":7_200_000,"Orange":5_800_000,"Vodafone":4_900_000,"MásMóvil":2_100_000,"Yoigo":1_400_000}},
    "SE": {"flag":"🇸🇪","name":"Sweden",         "carriers":{"Telia":3_200_000,"Tele2":2_800_000,"Tre":1_900_000,"Telenor":1_400_000}},
    "CH": {"flag":"🇨🇭","name":"Switzerland",    "carriers":{"Swisscom":2_800_000,"Sunrise":1_900_000,"Salt":980_000}},
    "TW": {"flag":"🇹🇼","name":"Taiwan",         "carriers":{"Chunghwa":4_100_000,"Taiwan Mobile":3_200_000,"FarEasTone":2_800_000,"TSTAR":1_100_000}},
    "TR": {"flag":"🇹🇷","name":"Turkey",         "carriers":{"Turkcell":6_800_000,"Vodafone":4_900_000,"Türk Telekom":4_200_000}},
    "AE": {"flag":"🇦🇪","name":"UAE",            "carriers":{"Etisalat (e&)":2_400_000,"du":1_800_000}},
    "UA": {"flag":"🇺🇦","name":"Ukraine",        "carriers":{"Kyivstar":4_800_000,"Vodafone":3_200_000,"lifecell":2_100_000}},
    "UK": {"flag":"🇬🇧","name":"United Kingdom", "carriers":{"EE":3_544_000,"O2":1_831_000,"Sky":553_000,"Three":4_515_000,"Virgin":114_000,"Vodafone":530_000}},
    "US": {"flag":"🇺🇸","name":"United States",  "carriers":{"AT&T":12_800_000,"Verizon":11_400_000,"T-Mobile":9_700_000,"Boost Mobile":2_100_000,"Cricket":1_900_000,"Metro by T-Mobile":1_700_000,"US Cellular":890_000,"Mint Mobile":640_000}},
}

for _cc, _d in LEADS.items():
    if "MIX" not in _d["carriers"]:
        _biggest = max(_d["carriers"].values())
        _d["carriers"]["MIX"] = int(_biggest * 1.25)

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

# ── PRESERVED NEW LEADS DATA (WORLD_DATASETS) ─────────────────────────────────
WORLD_DATASETS = {
    "AU": {"bank": [{"name": "Commonwealth Bank", "stock": 5200000}, {"name": "Westpac", "stock": 2400000}, {"name": "ANZ", "stock": 2100000}, {"name": "NAB", "stock": 1800000}, {"name": "Macquarie", "stock": 1900000}], "business": [{"name": "ASIC Registry", "stock": 3500000}, {"name": "BHP Group", "stock": 1200000}], "crypto": [{"name": "CoinSpot", "stock": 2100000}, {"name": "Swyftx", "stock": 1800000}]},
    "AT": {"bank": [{"name": "Erste Bank", "stock": 1900000}, {"name": "Raiffeisen Bank International", "stock": 2100000}, {"name": "BAWAG PSK", "stock": 950000}], "business": [{"name": "Firmenbuch", "stock": 850000}, {"name": "OMV", "stock": 210000}], "crypto": [{"name": "Bitpanda", "stock": 1400000}, {"name": "Coinfinity", "stock": 350000}]},
    "BH": {"bank": [{"name": "National Bank of Bahrain", "stock": 420000}, {"name": "Ahli United Bank", "stock": 450000}], "business": [{"name": "MOIC Registry", "stock": 850000}], "crypto": [{"name": "Rain Crypto", "stock": 250000}, {"name": "CoinMENA", "stock": 180000}]},
    "BE": {"bank": [{"name": "BNP Paribas Fortis", "stock": 3100000}, {"name": "KBC Bank", "stock": 2400000}], "business": [{"name": "CBE Registry", "stock": 900000}], "crypto": [{"name": "Bitvavo BE", "stock": 750000}]},
    "BR": {"bank": [{"name": "Itaú Unibanco", "stock": 6800000}, {"name": "Banco do Brasil", "stock": 5400000}], "business": [{"name": "Petrobras", "stock": 1500000}], "crypto": [{"name": "Mercado Bitcoin", "stock": 2900000}]},
    "BG": {"bank": [{"name": "DSK Bank", "stock": 1200000}, {"name": "UniCredit Bulbank", "stock": 1100000}], "business": [{"name": "Bulgarian Commercial Register", "stock": 400000}], "crypto": [{"name": "Binance BG", "stock": 350000}]},
    "CA": {"bank": [{"name": "RBC", "stock": 2800000}, {"name": "TD Bank", "stock": 2500000}], "business": [{"name": "Corporations Canada", "stock": 1800000}], "crypto": [{"name": "Shakepay", "stock": 950000}, {"name": "Newton", "stock": 800000}]},
    "CY": {"bank": [{"name": "Bank of Cyprus", "stock": 950000}], "business": [{"name": "Cyprus Registrar of Companies", "stock": 600000}], "crypto": [{"name": "Binance CY", "stock": 300000}]},
    "CZ": {"bank": [{"name": "Česká spořitelna", "stock": 2400000}, {"name": "Komerční banka", "stock": 2100000}], "business": [{"name": "Czech Commercial Register", "stock": 650000}], "crypto": [{"name": "Anycoin CZ", "stock": 350000}]},
    "DK": {"bank": [{"name": "Danske Bank", "stock": 2800000}, {"name": "Jyske Bank", "stock": 1100000}], "business": [{"name": "Danish Business Authority", "stock": 500000}], "crypto": [{"name": "Binance DK", "stock": 600000}]},
    "EE": {"bank": [{"name": "Swedbank EE", "stock": 950000}, {"name": "SEB Pank", "stock": 850000}], "business": [{"name": "e-Residency Hub", "stock": 1200000}], "crypto": [{"name": "CoinMetro", "stock": 300000}]},
    "FI": {"bank": [{"name": "Nordea FI", "stock": 1900000}, {"name": "OP Financial Group", "stock": 2200000}], "business": [{"name": "Finnish Trade Register", "stock": 500000}], "crypto": [{"name": "Coinmotion", "stock": 350000}]},
    "FR": {"bank": [{"name": "BNP Paribas", "stock": 6500000}, {"name": "Crédit Agricole", "stock": 7200000}], "business": [{"name": "LVMH", "stock": 450000}], "crypto": [{"name": "Coinhouse", "stock": 900000}]},
    "DE": {"bank": [{"name": "Deutsche Bank", "stock": 7800000}, {"name": "Commerzbank", "stock": 5100000}], "business": [{"name": "Handelsregister", "stock": 3800000}], "crypto": [{"name": "Bison App", "stock": 2100000}]},
    "GR": {"bank": [{"name": "National Bank of Greece", "stock": 2400000}, {"name": "Piraeus Bank", "stock": 2100000}], "business": [{"name": "General Commercial Registry", "stock": 450000}], "crypto": [{"name": "Binance GR", "stock": 800000}]},
    "HU": {"bank": [{"name": "OTP Bank", "stock": 3100000}, {"name": "K&H Bank", "stock": 1500000}], "business": [{"name": "Hungarian Company Registry", "stock": 550000}], "crypto": [{"name": "Binance HU", "stock": 750000}]},
    "IS": {"bank": [{"name": "Landsbankinn", "stock": 250000}, {"name": "Arion Bank", "stock": 220000}], "business": [{"name": "Icelandic Enterprise Register", "stock": 90000}], "crypto": [{"name": "Binance IS", "stock": 80000}]},
    "IE": {"bank": [{"name": "Bank of Ireland", "stock": 1800000}, {"name": "AIB", "stock": 1500000}], "business": [{"name": "Companies Registration Office (CRO)", "stock": 1400000}], "crypto": [{"name": "Coinbase IE", "stock": 700000}]},
    "IT": {"bank": [{"name": "Intesa Sanpaolo", "stock": 6400000}, {"name": "UniCredit", "stock": 5800000}], "business": [{"name": "Registro Imprese", "stock": 1100000}], "crypto": [{"name": "Young Platform", "stock": 600000}]},
    "LV": {"bank": [{"name": "Swedbank LV", "stock": 850000}, {"name": "SEB Latvia", "stock": 650000}], "business": [{"name": "Register of Enterprises", "stock": 250000}], "crypto": [{"name": "Binance LV", "stock": 250000}]},
    "LT": {"bank": [{"name": "Swedbank LT", "stock": 1100000}, {"name": "SEB Lietuva", "stock": 950000}], "business": [{"name": "Centre of Registers", "stock": 800000}], "crypto": [{"name": "Binance LT", "stock": 450000}]},
    "MY": {"bank": [{"name": "Maybank", "stock": 6800000}, {"name": "CIMB Bank", "stock": 5900000}], "business": [{"name": "SSM", "stock": 2100000}], "crypto": [{"name": "Luno MY", "stock": 1900000}]},
    "MT": {"bank": [{"name": "Bank of Valletta", "stock": 350000}, {"name": "HSBC Malta", "stock": 250000}], "business": [{"name": "Malta Business Registry", "stock": 500000}], "crypto": [{"name": "Binance MT", "stock": 400000}]},
    "NL": {"bank": [{"name": "ING Bank", "stock": 8500000}, {"name": "Rabobank", "stock": 7100000}], "business": [{"name": "KVK", "stock": 2200000}], "crypto": [{"name": "Bitvavo", "stock": 2800000}]},
    "NZ": {"bank": [{"name": "ANZ New Zealand", "stock": 2400000}, {"name": "ASB Bank", "stock": 2100000}], "business": [{"name": "NZ Companies Office", "stock": 600000}], "crypto": [{"name": "Easy Crypto", "stock": 600000}]},
    "NO": {"bank": [{"name": "DNB ASA", "stock": 3100000}, {"name": "Nordea Norge", "stock": 1200000}], "business": [{"name": "Brønnøysund Register", "stock": 500000}], "crypto": [{"name": "Firi", "stock": 450000}]},
    "PL": {"bank": [{"name": "PKO Bank Polski", "stock": 7500000}, {"name": "Bank Pekao", "stock": 5200000}], "business": [{"name": "KRS", "stock": 1900000}], "crypto": [{"name": "Zonda Crypto", "stock": 900000}]},
    "PT": {"bank": [{"name": "Caixa Geral de Depósitos", "stock": 2800000}, {"name": "Millennium bcp", "stock": 2400000}], "business": [{"name": "Registo Nacional de Pessoas Coletivas", "stock": 900000}], "crypto": [{"name": "Binance PT", "stock": 1400000}]},
    "PR": {"bank": [{"name": "Banco Popular", "stock": 1500000}, {"name": "FirstBank", "stock": 1100000}], "business": [{"name": "PR Department of State", "stock": 400000}], "crypto": [{"name": "Coinbase PR", "stock": 500000}]},
    "QA": {"bank": [{"name": "Qatar National Bank (QNB)", "stock": 2800000}, {"name": "Doha Bank", "stock": 950000}], "business": [{"name": "Qatar Financial Centre", "stock": 600000}], "crypto": [{"name": "Rain QA", "stock": 550000}]},
    "RO": {"bank": [{"name": "Banca Comercială Română", "stock": 3500000}, {"name": "BRD", "stock": 2800000}], "business": [{"name": "ONRC", "stock": 950000}], "crypto": [{"name": "Binance RO", "stock": 1800000}]},
    "SG": {"bank": [{"name": "DBS Bank", "stock": 4800000}, {"name": "OCBC Bank", "stock": 3900000}], "business": [{"name": "ACRA", "stock": 3200000}], "crypto": [{"name": "Coinbase SG", "stock": 1900000}]},
    "SK": {"bank": [{"name": "Slovenská sporiteľňa", "stock": 1800000}, {"name": "VÚB Banka", "stock": 1500000}], "business": [{"name": "Business Register of SR", "stock": 400000}], "crypto": [{"name": "Binance SK", "stock": 500000}]},
    "SI": {"bank": [{"name": "NLB Banka", "stock": 900000}, {"name": "NKBM", "stock": 700000}], "business": [{"name": "AJPES", "stock": 300000}], "crypto": [{"name": "Binance SI", "stock": 350000}]},
    "ZA": {"bank": [{"name": "Standard Bank", "stock": 6500000}, {"name": "FirstRand (FNB)", "stock": 6900000}], "business": [{"name": "CIPC", "stock": 1800000}], "crypto": [{"name": "Luno", "stock": 2100000}]},
    "ES": {"bank": [{"name": "Banco Santander", "stock": 9500000}, {"name": "BBVA", "stock": 8800000}], "business": [{"name": "Registro Mercantil", "stock": 1800000}], "crypto": [{"name": "Bit2Me", "stock": 1400000}]},
    "SE": {"bank": [{"name": "SEB", "stock": 2800000}, {"name": "Swedbank", "stock": 3200000}], "business": [{"name": "Bolagsverket", "stock": 1600000}], "crypto": [{"name": "Safello", "stock": 500000}]},
    "CH": {"bank": [{"name": "UBS", "stock": 5200000}, {"name": "Raiffeisen", "stock": 2900000}], "business": [{"name": "Zefix", "stock": 1500000}], "crypto": [{"name": "Bitcoin Suisse", "stock": 800000}]},
    "TW": {"bank": [{"name": "CTBC Bank", "stock": 4800000}, {"name": "Cathay United Bank", "stock": 4100000}], "business": [{"name": "Department of Commerce", "stock": 3900000}], "crypto": [{"name": "MaiCoin", "stock": 1100000}]},
    "TR": {"bank": [{"name": "Garanti BBVA", "stock": 9100000}, {"name": "İş Bankası", "stock": 9800000}], "business": [{"name": "Trade Registry Gazette", "stock": 2400000}], "crypto": [{"name": "BtcTurk", "stock": 3800000}]},
    "AE": {"bank": [{"name": "First Abu Dhabi Bank", "stock": 3500000}, {"name": "Emirates NBD", "stock": 4900000}], "business": [{"name": "DED", "stock": 4500000}], "crypto": [{"name": "Binance UAE", "stock": 3100000}]},
    "UA": {"bank": [{"name": "PrivatBank", "stock": 14500000}, {"name": "Monobank", "stock": 8900000}], "business": [{"name": "Unified State Register", "stock": 1800000}], "crypto": [{"name": "Kuna Exchange", "stock": 900000}]},
    "GB": {"bank": [{"name": "HSBC UK", "stock": 12000000}, {"name": "Barclays", "stock": 11500000}, {"name": "Lloyds Bank", "stock": 14000000}, {"name": "NatWest", "stock": 9800000}, {"name": "Santander UK", "stock": 7200000}, {"name": "Monzo", "stock": 6500000}], "business": [{"name": "Companies House", "stock": 15000000}, {"name": "Tesco Stores", "stock": 1800000}], "crypto": [{"name": "Coinbase UK", "stock": 1500000}, {"name": "Kraken UK", "stock": 1100000}]},
    "US": {"bank": [{"name": "JPMorgan Chase", "stock": 45000000}, {"name": "Bank of America", "stock": 38000000}, {"name": "Wells Fargo", "stock": 32000000}, {"name": "Citibank", "stock": 28000000}, {"name": "Capital One", "stock": 21000000}], "business": [{"name": "Delaware Sec of State", "stock": 8500000}, {"name": "California Sec of State", "stock": 12000000}, {"name": "Walmart Inc.", "stock": 15000000}, {"name": "Apple Inc.", "stock": 5500000}], "crypto": [{"name": "Coinbase", "stock": 12500000}, {"name": "Kraken", "stock": 5800000}, {"name": "Gemini", "stock": 3200000}, {"name": "Binance.US", "stock": 4100000}]}
}

# ── Dynamic Fetchers & Auto-Sync Engine ───────────────────────────────────────
async def fetch_external_crypto(country_name: str) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/exchanges", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = []
                    for ex in data:
                        c = ex.get("country", "")
                        if c and country_name.lower() in c.lower():
                            results.append({"name": ex["name"], "stock": 450000})
                    return results
    except Exception: pass
    return []

async def fetch_external_network(iso2: str, country_name: str) -> list:
    try:
        url = "https://raw.githubusercontent.com/pbakondy/mcc-mnc-list/master/mcc-mnc-list.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    networks = set()
                    for entry in data:
                        if entry.get("countryCode", "").upper() == iso2.upper():
                            brand = entry.get("brand") or entry.get("operator")
                            if brand: networks.add(brand)
                    return [{"name": net, "stock": 150000} for net in networks]
    except Exception: pass
    return []

async def auto_sync_datasets():
    while True:
        try:
            logger.info("Executing background data sync...")
            for iso2 in LEADS.keys():
                c_name = LEADS[iso2]["name"]
                crypto_data = await fetch_external_crypto(c_name)
                if crypto_data: cached_external_apis["crypto"][iso2] = crypto_data
                
                net_data = await fetch_external_network(iso2, c_name)
                if net_data: cached_external_apis["network"][iso2] = net_data
                
                await asyncio.sleep(2)
            await asyncio.sleep(43200)
        except asyncio.CancelledError: break
        except Exception as e:
            logger.error(f"Sync error: {e}")
            await asyncio.sleep(3600)

def get_country_file_path(iso2: str, category: str) -> str:
    folder = os.path.join(COUNTRIES_DIR, iso2.lower())
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{category}.json")

async def fetch_dynamic_vertical(iso2: str, vertical: str) -> list:
    """
    Cascading 5-Tier Data Engine:
    1. Local Cached JSON file (from prior scrapes or admin sets)
    2. Embedded Authentic Database (WORLD_DATASETS)
    3. Original LEADS Old File mapping (For Networks specifically to satisfy preserving data)
    4. Cached External Auto-Sync Results
    5. Live External Dynamic Sync (CoinGecko, MCC-MNC)
    Returns [] if absolutely nothing is found. No fakes.
    """
    path = get_country_file_path(iso2, vertical)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0: return data
        except Exception: pass

    if iso2 in WORLD_DATASETS and vertical in WORLD_DATASETS[iso2]:
        if WORLD_DATASETS[iso2][vertical]:
            return WORLD_DATASETS[iso2][vertical]

    if vertical == "network" and iso2 in LEADS and "carriers" in LEADS[iso2]:
        return [{"name": name, "stock": stock} for name, stock in LEADS[iso2]["carriers"].items()]

    if iso2 in cached_external_apis.get(vertical, {}):
        return cached_external_apis[vertical][iso2]

    c_name = LEADS[iso2]["name"] if iso2 in LEADS else iso2
    fetched_items = []
    if vertical == "crypto": fetched_items = await fetch_external_crypto(c_name)
    elif vertical == "network": fetched_items = await fetch_external_network(iso2, c_name)
    
    if fetched_items:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(fetched_items, f, indent=4)
        except Exception: pass
        return fetched_items

    return []

# ── Admin Activity Logging ────────────────────────────────────────────────────
async def log_activity(user, action_type: str, details: str = ""):
    now = datetime.now()
    user_last_active[user.id] = now.isoformat()
    log_entry = {
        "timestamp": now.isoformat(), "user_id": user.id, "username": user.username,
        "first_name": user.first_name, "last_name": user.last_name,
        "action": action_type, "details": details
    }
    try:
        with open(LOGS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e: logger.error(f"Failed to write admin log: {e}")

# ── Dynamic Pricing Configuration ─────────────────────────────────────────────
def get_leads_pricing(category: str):
    pricing_dict = DYNAMIC_LEADS_PRICING.get(category, DYNAMIC_LEADS_PRICING["network"])
    return sorted([(int(k), float(v)) for k, v in pricing_dict.items()], key=lambda x: x[0])

# ── Persistence (save/load data) ──────────────────────────────────────────────
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
            "DYNAMIC_LEADS_PRICING": DYNAMIC_LEADS_PRICING
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(data, f)
        os.replace(tmp, DATA_FILE)
    except Exception as e: logger.error(f"save_data failed: {e}")

def load_data():
    global user_balances, agreed_users, user_join_dates, channel_verified, live_stock, STORE, DYNAMIC_LEADS_PRICING
    if not os.path.exists(DATA_FILE): return
    try:
        with open(DATA_FILE) as f: data = json.load(f)
        user_balances    = {int(k): v for k, v in data.get("user_balances", {}).items()}
        agreed_users     = set(data.get("agreed_users", []))
        user_join_dates  = {int(k): v for k, v in data.get("user_join_dates", {}).items()}
        channel_verified = set(data.get("channel_verified", []))
        live_stock.update(data.get("live_stock", {}))
        if data.get("DYNAMIC_LEADS_PRICING"): DYNAMIC_LEADS_PRICING = data["DYNAMIC_LEADS_PRICING"]
        if data.get("STORE"):
            STORE.clear(); STORE.update(data["STORE"])
    except Exception as e: logger.error(f"load_data failed: {e}")

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

# ── Old Scanner Keyboards ─────────────────────────────────────────────────────

def scanner_items_for_cat(cat):
    if cat == "all": return list(enumerate(SCANNER_ITEMS))
    return [(i, item) for i, item in enumerate(SCANNER_ITEMS) if item[1] == cat]

def scanner_keyboard(cat="all", page=0):
    items      = scanner_items_for_cat(cat)
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

# ── Leads Keyboards ───────────────────────────────────────────────────────────

def leads_pricing_text():
    lines = ["📊 *Pricing*"]
    for qty, price in LEADS_PRICING:
        k = qty // 1000
        lines.append(f"{k}k — £{price}")
    return "\n".join(lines)

def country_keyboard():
    # This exclusively builds from the LEADS dictionary provided in the old source.
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        row = [InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"c_dash|{cc}") for cc, d in countries[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
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
            row.append(InlineKeyboardButton(f"{name_display} ({stock:,})", callback_data=f"c_item|{iso2}|{vertical}|{name}"))
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

def dynamic_qty_keyboard(iso2: str, vertical: str, item_name: str):
    rows = []
    tiers = get_leads_pricing(vertical)
    for i in range(0, len(tiers), 2):
        row = []
        for qty, price in tiers[i:i+2]:
            k = f"{qty//1000}k" if qty >= 1000 else str(qty)
            row.append(InlineKeyboardButton(f"{k} — £{price:g}", callback_data=f"c_buy|{iso2}|{vertical}|{item_name}|{qty}|{price}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"c_vert|{iso2}|{vertical}")])
    return InlineKeyboardMarkup(rows)

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
    await log_activity(update.effective_user, "Command", "/start")
    
    if uid in agreed_users:
        await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return
    await update.message.reply_text(RULES_TEXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've Joined — Let Me In", callback_data="agree_rules")]]), parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await log_activity(update.effective_user, "Command", "/wallet")
    await update.message.reply_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = user_balances.get(uid, 0)
    await log_activity(update.effective_user, "Command", "/balance")
    await update.message.reply_text(f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*", parse_mode="Markdown")

async def cmd_targeted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await log_activity(update.effective_user, "Command", "/targeted")
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
        await log_activity(update.effective_user, "Action", "Agreed to Rules")
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty", "awaiting_search"):
        context.user_data.pop(_k, None)

    # ── Universal Leads Directory Routing ────────────────────────────────────
    if data == "leads":
        await log_activity(update.effective_user, "Navigation", "Opened Leads Directory")
        await query.edit_message_text("🌍 *Leads Directory*\n\nSelect a country below:", reply_markup=country_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("c_dash|"):
        iso2 = data.split("|")[1]
        if iso2 not in LEADS: await query.answer("Country not found."); return
        d = LEADS[iso2]
        c_name = d["name"]
        flag = d["flag"]
        await log_activity(update.effective_user, "Navigation", f"Opened Dashboard: {c_name} ({iso2})")
        await query.edit_message_text(f"{flag} *{c_name} Data Hub*\n\nSelect a dynamic data vertical:", reply_markup=country_vertical_keyboard(iso2), parse_mode="Markdown")
        return

    if data.startswith("c_vert|"):
        _, iso2, vertical = data.split("|")
        items = await fetch_dynamic_vertical(iso2, vertical)
        
        if iso2 not in LEADS: await query.answer("Country not found."); return
        d = LEADS[iso2]
        c_name = d["name"]
        flag = d["flag"]
        await log_activity(update.effective_user, "Navigation", f"Opened Vertical: {c_name} -> {vertical}")

        if not items:
            if vertical == "crypto": empty_msg = "No Crypto Exchanges Available"
            elif vertical == "nodes": empty_msg = "No Records Available"
            else: empty_msg = "No Data Available"
                
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

        if iso2 not in LEADS: await query.answer("Country not found."); return
        d = LEADS[iso2]
        c_name = d["name"]
        flag = d["flag"]

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
        parts = data.split("|")
        iso2, vertical, item_name = parts[1], parts[2], parts[3]
        
        if iso2 not in LEADS: await query.answer("Country not found."); return
        d = LEADS[iso2]
        c_name = d["name"]
        flag = d["flag"]
        
        await log_activity(update.effective_user, "Navigation", f"Selected Entity: {c_name} -> {item_name}")

        await query.edit_message_text(
            f"📦 *Entity:* {item_name}\n🌍 *Region:* {flag} {c_name}\n\nSelect volume quantity:",
            reply_markup=dynamic_qty_keyboard(iso2, vertical, item_name),
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
        
        await log_activity(update.effective_user, "Purchase", f"Bought Leads: {item_name} ({qty}) for £{price}")

        if iso2 not in LEADS: await query.answer("Country not found."); return
        d = LEADS[iso2]
        c_name = d["name"]
        flag = d["flag"]

        await query.edit_message_text(
            f"✅ *Export Order Confirmed!*\n\n"
            f"Category: *{vertical.title()}*\n"
            f"Region: {flag} *{c_name}*\n"
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
        await log_activity(update.effective_user, "Navigation", "Opened Wallet")
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
        
        await log_activity(update.effective_user, "Payment Attempt", f"Requested deposit of £{amount} via {coin}")

        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]),
            parse_mode="Markdown")
        return

    # Store
    if data == "store":
        await log_activity(update.effective_user, "Navigation", "Opened Store")
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
        
        await log_activity(update.effective_user, "Purchase", f"Bought BIN: {bin_num} ({buy_qty}) for £{total}")

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
        await log_activity(update.effective_user, "Purchase", f"Bought Deads: {label} for £{price}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n📁 *{label}*\n\nContact @{SUPER_ADMIN} for files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown")
        return

    # Scanner - Reverted to static functionality as per OLD python file
    if data == "scanner":
        await log_activity(update.effective_user, "Navigation", "Opened Scanner")
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
        await log_activity(update.effective_user, "Purchase", f"Bought Scanner: {label} ({qty_k}k) for £{total_gbp}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n{label} ({qty_k}k)\n\nContact @{SUPER_ADMIN} to receive.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]), parse_mode="Markdown")
        return

    # Targeted Source
    if data == "tsource":
        await log_activity(update.effective_user, "Navigation", "Opened Targeted Source")
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
        await log_activity(update.effective_user, "Purchase", f"Bought Targeted Aged Leads ({qty}) for £{price}")
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
        await log_activity(update.effective_user, "Purchase", f"Bought Targeted Crypto Leads ({qty}) for £{price}")
        await query.edit_message_text(f"✅ *Purchase Successful!*\n\nCrypto Leads ({qty//1000}k)\n\nContact @{SUPER_ADMIN}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown")
        return

# ── Message Handler ───────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Strict Country-Scoped Entity Search
    if context.user_data.get("awaiting_search"):
        query_text = update.message.text.strip().lower()
        iso2, vertical = context.user_data.get("search_target", ("US", "bank"))
        context.user_data["awaiting_search"] = False

        items = context.user_data.get(f"items_{iso2}_{vertical}")
        if not items: items = await fetch_dynamic_vertical(iso2, vertical)

        filtered = [item for item in items if query_text in item["name"].lower()]

        d = LEADS.get(iso2, {})
        c_name = d.get("name", iso2)

        await log_activity(update.effective_user, "Search", f"Searched {vertical} in {c_name} for: '{query_text}'")

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

# ── Admin System & Dynamic Pricing Configuration ──────────────────────────────

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
    "*Dynamic Pricing - Leads*\n"
    "`/setleadprice <network|bank|business|crypto|nodes> <qty> <price>`\n"
    "`/delleadprice <category> <qty>`\n\n"
    "*Balance Management*\n"
    "`/addbalance <user_id> <amount>`\n"
    "`/removebalance <user_id> <amount>`\n"
    "`/setbalance <user_id> <amount>`\n"
    "`/checkbalance <user_id>`\n\n"
    "*Activity Logs*\n"
    "`/adminlogs` (Downloads full user activity log file)\n\n"
    "*Leads & Stock*\n"
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

async def cmd_adminlogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    if not os.path.exists(LOGS_FILE):
        await update.message.reply_text("⚠️ No logs recorded yet.")
        return
    await update.message.reply_document(document=InputFile(LOGS_FILE), caption="📄 Full User Activity Logs")

# Leads Dynamic Pricing
async def cmd_setleadprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cat = context.args[0].lower()
        qty = int(context.args[1])
        price = float(context.args[2])
        if cat not in DYNAMIC_LEADS_PRICING:
            await update.message.reply_text("Category must be one of: network, bank, business, crypto, nodes")
            return
        DYNAMIC_LEADS_PRICING[cat][qty] = price
        save_data()
        await update.message.reply_text(f"✅ Set Leads Pricing for *{cat.title()}*:\n• *{qty:,}* = £{price:.2f}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/setleadprice <category> <qty> <price>`", parse_mode="Markdown")

async def cmd_delleadprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cat = context.args[0].lower()
        qty = int(context.args[1])
        if cat in DYNAMIC_LEADS_PRICING and qty in DYNAMIC_LEADS_PRICING[cat]:
            del DYNAMIC_LEADS_PRICING[cat][qty]
            save_data()
            await update.message.reply_text(f"✅ Removed tier *{qty}* from *{cat.title()}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("Tier not found.")
    except Exception:
        await update.message.reply_text("Usage: `/delleadprice <category> <qty>`", parse_mode="Markdown")


async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2)
    save_data()
    await log_activity(update.effective_user, "Admin Action", f"Added £{amt} to User {tid}")
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
    app.add_handler(CommandHandler("adminlogs",     cmd_adminlogs))
    app.add_handler(CommandHandler("setleadprice",  cmd_setleadprice))
    app.add_handler(CommandHandler("delleadprice",  cmd_delleadprice))
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
    app.add_handler(CommandHandler("bulkbin",       cmd_bulkbin))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    logger.info("Bot started successfully ✅")
    
    # Background auto-sync task for external registries
    loop = asyncio.get_event_loop()
    loop.create_task(auto_sync_datasets())
    
    app.run_polling(timeout=30, drop_pending_updates=False)

if __name__ == "__main__":
    main()
