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

live_stock    = {"leads": 63_629_085} # Store stock is calculated dynamically
TOPUP_AMOUNTS = [70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 750, 1000]
BINS_PER_PAGE = 20   # 20 bins per page = 10 rows of 2

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

def get_category_pricing(cc):
    if cc in LEADS and "pricing" in LEADS[cc]:
        return sorted([(int(k), float(v)) for k, v in LEADS[cc]["pricing"].items()], key=lambda x: x[0])
    return LEADS_PRICING

def get_category_pricing_dict(cc):
    if cc in LEADS and "pricing" in LEADS[cc]:
        return {int(k): float(v) for k, v in LEADS[cc]["pricing"].items()}
    return dict(LEADS_PRICING)

# ── Full A-Z World Countries Data Structure (Crypto, Bank, Business, Network) ─
LEADS = {
    "AF": {"flag": "🇦🇫", "name": "Afghanistan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AF": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Afghanistan International Bank": 300000, "Azizi Bank": 250000}},
        "business": {"name": "🏢 Business", "items": {"Local Trade AF": 100000}},
        "network": {"name": "📡 Network", "items": {"Roshan": 800000, "MTN AF": 600000, "Etisalat AF": 500000}}
    }},
    "AL": {"flag": "🇦🇱", "name": "Albania", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AL": 200000}},
        "bank": {"name": "🏦 Banks", "items": {"Banka Kombëtare Tregtare": 400000, "Credins Bank": 300000}},
        "business": {"name": "🏢 Business", "items": {"Tirana Business Corp": 150000}},
        "network": {"name": "📡 Network", "items": {"Vodafone AL": 900000, "One Telecommunications": 800000}}
    }},
    "DZ": {"flag": "🇩🇿", "name": "Algeria", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance DZ": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Algeria": 1200000, "CPA": 900000}},
        "business": {"name": "🏢 Business", "items": {"Sonatrach Partner Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Mobilis": 3500000, "Djezzy": 3200000, "Ooredoo DZ": 2800000}}
    }},
    "AD": {"flag": "🇦🇩", "name": "Andorra", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Andorra Crypto Ex": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"Andbank": 80000, "Crèdit Andorrà": 75000}},
        "business": {"name": "🏢 Business", "items": {"Andorra Business Hub": 30000}},
        "network": {"name": "📡 Network", "items": {"Andorra Telecom": 90000}}
    }},
    "AO": {"flag": "🇦🇴", "name": "Angola", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AO": 180000}},
        "bank": {"name": "🏦 Banks", "items": {"BAI Angola": 600000, "BFA": 500000}},
        "business": {"name": "🏢 Business", "items": {"Luanda Trade Co": 200000}},
        "network": {"name": "📡 Network", "items": {"Unitel": 2100000, "Movicel": 800000}}
    }},
    "AR": {"flag": "🇦🇷", "name": "Argentina", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AR": 2100000, "Lemon Cash": 1800000, "Bitso AR": 1200000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Galicia": 2400000, "Banco Macro": 2100000, "BBVA Argentina": 1900000}},
        "business": {"name": "🏢 Business", "items": {"MercadoLibre Hub": 3500000, "Argentina Fintech": 1100000}},
        "network": {"name": "📡 Network", "items": {"Claro AR": 5800000, "Personal AR": 5200000, "Movistar AR": 4500000}}
    }},
    "AM": {"flag": "🇦🇲", "name": "Armenia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AM": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Ameriabank": 450000, "Acba Bank": 350000}},
        "business": {"name": "🏢 Business", "items": {"Yerevan Tech Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"Team Telecom Armenia": 800000, "Ucom": 700000, "Vivacell-MTS": 900000}}
    }},
    "AU": {"flag": "🇦🇺", "name": "Australia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AU": 1200000, "CoinSpot": 1500000, "Independent Reserve": 800000, "Swyftx": 950000}},
        "bank": {"name": "🏦 Banks", "items": {"CBA": 2900000, "Westpac": 2400000, "NAB": 2100000, "ANZ Bank": 1800000, "Macquarie Bank": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Wise Australia": 900000, "PayPal AU": 1800000, "Afterpay": 1400000, "Square AU": 750000}},
        "network": {"name": "📡 Network", "items": {"Telstra": 4200000, "Optus": 3100000, "Vodafone": 1800000, "Boost Mobile": 620000, "TPG": 430000}}
    }},
    "AT": {"flag": "🇦🇹", "name": "Austria", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitpanda": 1400000, "Binance AT": 800000}},
        "bank": {"name": "🏦 Banks", "items": {"Erste Bank": 1900000, "Raiffeisen Bank": 2100000, "BAWAG PSK": 950000}},
        "business": {"name": "🏢 Business", "items": {"Vienna Tech Corp": 600000}},
        "network": {"name": "📡 Network", "items": {"A1": 1540000, "Magenta": 890000, "Drei": 760000, "Spusu": 210000}}
    }},
    "AZ": {"flag": "🇦🇿", "name": "Azerbaijan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance AZ": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Kapital Bank": 1100000, "ABB Bank": 950000, "Pasha Bank": 600000}},
        "business": {"name": "🏢 Business", "items": {"Baku Business Group": 350000}},
        "network": {"name": "📡 Network", "items": {"Azercell": 2400000, "Bakcell": 1800000, "Nar Mobile": 1200000}}
    }},
    "BS": {"flag": "🇧🇸", "name": "Bahamas", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"FTX Legacy Hub": 200000, "Binance BS": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Commonwealth Bank BS": 180000, "RBC Bahamas": 220000}},
        "business": {"name": "🏢 Business", "items": {"Nassau Offshore Corp": 90000}},
        "network": {"name": "📡 Network", "items": {"BTC Bahamas": 250000, "Aliv": 180000}}
    }},
    "BH": {"flag": "🇧🇭", "name": "Bahrain", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Rain Crypto": 250000, "Binance BH": 200000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Bahrain": 450000, "Ahli United Bank": 400000}},
        "business": {"name": "🏢 Business", "items": {"Manama Enterprise": 180000}},
        "network": {"name": "📡 Network", "items": {"Batelco": 480000, "Zain": 390000, "STC": 210000}}
    }},
    "BD": {"flag": "🇧🇩", "name": "Bangladesh", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BD": 1100000}},
        "bank": {"name": "🏦 Banks", "items": {"BRAC Bank": 2500000, "Dutch-Bangla Bank": 2800000, "Eastern Bank": 1200000}},
        "business": {"name": "🏢 Business", "items": {"Dhaka Garments Hub": 900000}},
        "network": {"name": "📡 Network", "items": {"Grameenphone": 7500000, "Robi": 4800000, "Banglalink": 3900000, "Teletalk": 950000}}
    }},
    "BB": {"flag": "🇧🇧", "name": "Barbados", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BB": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"CIBC FirstCaribbean": 200000, "Republic Bank BB": 150000}},
        "business": {"name": "🏢 Business", "items": {"Bridgetown Trade": 70000}},
        "network": {"name": "📡 Network", "items": {"Flow Barbados": 220000, "Digicel BB": 190000}}
    }},
    "BY": {"flag": "🇧🇾", "name": "Belarus", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Currency.com Hub": 400000, "Binance BY": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Belarusbank": 2100000, "Belagroprombank": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Minsk Tech Park": 350000}},
        "network": {"name": "📡 Network", "items": {"A1 Belarus": 3200000, "MTS Belarus": 3500000, "life:) BY": 900000}}
    }},
    "BE": {"flag": "🇧🇪", "name": "Belgium", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BE": 750000}},
        "bank": {"name": "🏦 Banks", "items": {"BNP Paribas Fortis": 3100000, "KBC Bank": 2400000, "Belfius": 2100000}},
        "business": {"name": "🏢 Business", "items": {"Brussels Corporate Hub": 900000}},
        "network": {"name": "📡 Network", "items": {"Proximus": 1920000, "Orange": 1340000, "Base": 980000}}
    }},
    "BZ": {"flag": "🇧🇿", "name": "Belize", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BZ": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"Belize Bank": 120000, "Atlantic Bank": 100000}},
        "business": {"name": "🏢 Business", "items": {"Belize Offshore Corp": 80000}},
        "network": {"name": "📡 Network", "items": {"Digi Belize": 210000, "Smart Belize": 90000}}
    }},
    "BJ": {"flag": "🇧🇯", "name": "Benin", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BJ": 90000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Benin": 300000, "Orabank Benin": 200000}},
        "business": {"name": "🏢 Business", "items": {"Cotonou Trade Hub": 110000}},
        "network": {"name": "📡 Network", "items": {"MTN Benin": 2200000, "Moov Benin": 1500000}}
    }},
    "BT": {"flag": "🇧🇹", "name": "Bhutan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Druk Holding Mining Hub": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Bhutan": 250000, "Bhutan National Bank": 200000}},
        "business": {"name": "🏢 Business", "items": {"Thimphu Enterprise": 50000}},
        "network": {"name": "📡 Network", "items": {"TashiCell": 350000, "B-Mobile": 400000}}
    }},
    "BO": {"flag": "🇧🇴", "name": "Bolivia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BO": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Nacional de Bolivia": 600000, "Banco Mercantil Santa Cruz": 550000}},
        "business": {"name": "🏢 Business", "items": {"La Paz Trade Corp": 180000}},
        "network": {"name": "📡 Network", "items": {"Tigo Bolivia": 2400000, "Entel BO": 2200000, "Viva BO": 900000}}
    }},
    "BA": {"flag": "🇧🇦", "name": "Bosnia and Herzegovina", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BA": 120000}},
        "bank": {"name": "🏦 Banks", "items": {"UniCredit Bank BH": 500000, "Raiffeisen BH": 450000}},
        "business": {"name": "🏢 Business", "items": {"Sarajevo Business Hub": 140000}},
        "network": {"name": "📡 Network", "items": {"BH Telecom": 1200000, "m:tel": 900000, "Eronet": 400000}}
    }},
    "BW": {"flag": "🇧🇼", "name": "Botswana", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BW": 90000}},
        "bank": {"name": "🏦 Banks", "items": {"First National Bank Botswana": 400000, "Absa Botswana": 350000}},
        "business": {"name": "🏢 Business", "items": {"Gaborone Mining Hub": 150000}},
        "network": {"name": "📡 Network", "items": {"Mascom": 1100000, "Orange BW": 800000, "BTC Mobile": 450000}}
    }},
    "BR": {"flag": "🇧🇷", "name": "Brazil", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Mercado Bitcoin": 2900000, "Binance BR": 3500000, "Bitso BR": 1400000}},
        "bank": {"name": "🏦 Banks", "items": {"Itaú Unibanco": 6800000, "Banco Bradesco": 6100000, "Nubank": 9500000, "Banco do Brasil": 5400000}},
        "business": {"name": "🏢 Business", "items": {"Stone Pagamentos": 2100000, "PagSeguro": 2400000}},
        "network": {"name": "📡 Network", "items": {"Vivo": 7800000, "Claro": 6500000, "TIM": 5200000, "Oi": 2100000}}
    }},
    "BN": {"flag": "🇧🇳", "name": "Brunei", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BN": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"Baiduri Bank": 150000, "Standard Chartered BN": 100000}},
        "business": {"name": "🏢 Business", "items": {"Bandar Energy Corp": 70000}},
        "network": {"name": "📡 Network", "items": {"DST Brunei": 300000, "Progresif": 200000}}
    }},
    "BG": {"flag": "🇧🇬", "name": "Bulgaria", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BG": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"DSK Bank": 1200000, "UniCredit Bulbank": 1100000, "Fibank": 800000}},
        "business": {"name": "🏢 Business", "items": {"Sofia Tech Park Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"A1": 1100000, "Telenor": 890000, "Vivacom": 760000}}
    }},
    "BF": {"flag": "🇧🇫", "name": "Burkina Faso", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BF": 70000}},
        "bank": {"name": "🏦 Banks", "items": {"Coris Bank International": 350000, "Ecobank Burkina": 250000}},
        "business": {"name": "🏢 Business", "items": {"Ouagadougou Trade": 90000}},
        "network": {"name": "📡 Network", "items": {"Orange BF": 2400000, "Telmob": 1800000, "Moov BF": 1100000}}
    }},
    "BI": {"flag": "🇧🇮", "name": "Burundi", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance BI": 30000}},
        "bank": {"name": "🏦 Banks", "items": {"Banque Commerciale du Burundi": 120000, "Inter Bank Burundi": 90000}},
        "business": {"name": "🏢 Business", "items": {"Bujumbura Commerce": 40000}},
        "network": {"name": "📡 Network", "items": {"Econet Leo": 700000, "Lumitel": 900000}}
    }},
    "CV": {"flag": "🇨🇻", "name": "Cabo Verde", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CV": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Comercial do Atlântico": 100000, "Caixa Económica de Cabo Verde": 80000}},
        "business": {"name": "🏢 Business", "items": {"Praia Island Trade": 30000}},
        "network": {"name": "📡 Network", "items": {"CVMovél": 250000, "T+ Cabo Verde": 180000}}
    }},
    "KH": {"flag": "🇰🇭", "name": "Cambodia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KH": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"ABA Bank Cambodia": 1800000, "ACLEDA Bank": 1500000, "Canadia Bank": 950000}},
        "business": {"name": "🏢 Business", "items": {"Phnom Penh Fintech Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Smart Axiata": 4500000, "Cellcard": 3100000, "Metfone": 3800000}}
    }},
    "CM": {"flag": "🇨🇲", "name": "Cameroon", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CM": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"Afriland First Bank": 800000, "SG Cameroon": 650000, "Ecobank CM": 500000}},
        "business": {"name": "🏢 Business", "items": {"Douala Port Trading": 250000}},
        "network": {"name": "📡 Network", "items": {"MTN Cameroon": 5200000, "Orange CM": 4800000}}
    }},
    "CA": {"flag": "🇨🇦", "name": "Canada", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Shakepay": 950000, "Coinbase CA": 1100000, "Newton": 800000, "Kraken CA": 700000}},
        "bank": {"name": "🏦 Banks", "items": {"RBC": 2800000, "TD Bank": 2500000, "Scotiabank": 2100000, "BMO": 1800000, "CIBC": 1600000}},
        "business": {"name": "🏢 Business", "items": {"Shopify": 1800000, "Wise CA": 850000, "PayPal CA": 1500000}},
        "network": {"name": "📡 Network", "items": {"Rogers": 4100000, "Bell": 3800000, "Telus": 3500000, "Fido": 980000, "Koodo": 760000}}
    }},
    "CF": {"flag": "🇨🇫", "name": "Central African Republic", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Sango Coin Hub": 80000, "Binance CF": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"CBCA": 100000, "BCC CAR": 70000}},
        "business": {"name": "🏢 Business", "items": {"Bangui Commerce": 30000}},
        "network": {"name": "📡 Network", "items": {"Telecel Centrafrique": 300000, "Orange CF": 250000}}
    }},
    "TD": {"flag": "🇹🇩", "name": "Chad", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TD": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Chad": 200000, "Société Générale Tchad": 150000}},
        "business": {"name": "🏢 Business", "items": {"N'Djamena Trade": 60000}},
        "network": {"name": "📡 Network", "items": {"Airtel Chad": 1800000, "Moov Africa Chad": 1200000}}
    }},
    "CL": {"flag": "🇨🇱", "name": "Chile", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CL": 1100000, "Buda.com": 850000, "Orionx": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco de Chile": 2500000, "Banco Santander CL": 2200000, "BCI": 1800000}},
        "business": {"name": "🏢 Business", "items": {"Santiago Fintech Hub": 700000}},
        "network": {"name": "📡 Network", "items": {"Entel CL": 5100000, "Movistar CL": 4400000, "Claro Chile": 3800000, "Wom": 2100000}}
    }},
    "CN": {"flag": "🇨🇳", "name": "China", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"OKX China P2P": 5500000, "Binance CN P2P": 7200000}},
        "bank": {"name": "🏦 Banks", "items": {"ICBC": 15000000, "China Construction Bank": 13500000, "Agricultural Bank of China": 12800000, "Bank of China": 11000000}},
        "business": {"name": "🏢 Business", "items": {"Alibaba Cloud Corp": 8500000, "Tencent Hub": 9100000, "JD.com Corp": 4200000}},
        "network": {"name": "📡 Network", "items": {"China Mobile": 45000000, "China Unicom": 21000000, "China Telecom": 18500000}}
    }},
    "CO": {"flag": "🇨🇴", "name": "Colombia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CO": 2400000, "Bitso CO": 1100000, "Orionx CO": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"Bancolombia": 5200000, "Banco de Bogotá": 3100000, "Davivienda": 2800000}},
        "business": {"name": "🏢 Business", "items": {"Rappi Tech Hub": 2900000, "Bogota Enterprise": 1100000}},
        "network": {"name": "📡 Network", "items": {"Claro CO": 11200000, "Movistar CO": 6800000, "Tigo CO": 5900000, "Wom CO": 1800000}}
    }},
    "KM": {"flag": "🇰🇲", "name": "Comoros", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KM": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Banque Centrale des Comores": 50000}},
        "business": {"name": "🏢 Business", "items": {"Moroni Trade": 20000}},
        "network": {"name": "📡 Network", "items": {"Comores Telecom": 180000, "Huri": 120000}}
    }},
    "CG": {"flag": "🇨🇬", "name": "Congo (Republic)", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CG": 60000}},
        "bank": {"name": "🏦 Banks", "items": {"BGFI Bank Congo": 250000, "Ecobank Congo": 180000}},
        "business": {"name": "🏢 Business", "items": {"Brazzaville Trade": 90000}},
        "network": {"name": "📡 Network", "items": {"MTN Congo": 1500000, "Airtel Congo": 1100000}}
    }},
    "CD": {"flag": "🇨🇩", "name": "Congo (Democratic Republic)", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CD": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"Rawbank": 900000, "EquityBCDC": 850000, "TMB": 600000}},
        "business": {"name": "🏢 Business", "items": {"Kinshasa Commerce": 350000}},
        "network": {"name": "📡 Network", "items": {"Vodacom DRC": 6500000, "Airtel DRC": 5100000, "Orange RDC": 4200000}}
    }},
    "CR": {"flag": "🇨🇷", "name": "Costa Rica", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CR": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Nacional de Costa Rica": 1200000, "Banco de Costa Rica": 1100000, "BAC Credomatic": 950000}},
        "business": {"name": "🏢 Business", "items": {"San Jose Tech Hub": 350000}},
        "network": {"name": "📡 Network", "items": {"Kölbi": 1800000, "Movistar CR": 1400000, "Claro CR": 1100000}}
    }},
    "HR": {"flag": "🇭🇷", "name": "Croatia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Electrocoin": 400000, "Binance HR": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"Zagrebačka banka": 1400000, "Privredna banka Zagreb": 1200000, "Erste Bank HR": 900000}},
        "business": {"name": "🏢 Business", "items": {"Zagreb Innovation Hub": 350000}},
        "network": {"name": "📡 Network", "items": {"HT Zagreb": 1900000, "A1 Hrvatska": 1400000, "Telemach HR": 950000}}
    }},
    "CU": {"flag": "🇨🇺", "name": "Cuba", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"QvaPay Hub": 300000, "Binance CU": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Metropolitano SA": 800000, "Banco Popular de Ahorro": 700000}},
        "business": {"name": "🏢 Business", "items": {"Havana State Trade": 150000}},
        "network": {"name": "📡 Network", "items": {"ETECSA": 4500000}}
    }},
    "CY": {"flag": "🇨🇾", "name": "Cyprus", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance CY": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Cyprus": 950000, "Hellenic Bank": 750000}},
        "business": {"name": "🏢 Business", "items": {"Limassol Offshore Hub": 600000}},
        "network": {"name": "📡 Network", "items": {"Cyta": 340000, "MTN": 210000, "Epic": 180000}}
    }},
    "CZ": {"flag": "🇨🇿", "name": "Czech Republic", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Anycoin CZ": 350000, "Binance CZ": 800000}},
        "bank": {"name": "🏦 Banks", "items": {"Česká spořitelna": 2400000, "Komerční banka": 2100000, "ČSOB": 1900000}},
        "business": {"name": "🏢 Business", "items": {"Prague Tech Hub": 650000}},
        "network": {"name": "📡 Network", "items": {"T-Mobile CZ": 2100000, "O2 CZ": 1800000, "Vodafone CZ": 1400000}}
    }},
    "DK": {"flag": "🇩🇰", "name": "Denmark", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance DK": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Danske Bank": 2800000, "Jyske Bank": 1100000, "Nykredit": 950000}},
        "business": {"name": "🏢 Business", "items": {"Copenhagen Fintech": 500000}},
        "network": {"name": "📡 Network", "items": {"TDC": 1540000, "Telenor DK": 1100000, "Telia DK": 980000, "Tre": 760000}}
    }},
    "DJ": {"flag": "🇩🇯", "name": "Djibouti", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance DJ": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"East Africa Bank": 80000, "CAC Bank Djibouti": 70000}},
        "business": {"name": "🏢 Business", "items": {"Djibouti Port Hub": 60000}},
        "network": {"name": "📡 Network", "items": {"Djibouti Telecom": 350000}}
    }},
    "DM": {"flag": "🇩🇲", "name": "Dominica", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance DM": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Dominica": 50000}},
        "business": {"name": "🏢 Business", "items": {"Roseau Trade Corp": 20000}},
        "network": {"name": "📡 Network", "items": {"Flow Dominica": 70000, "Digicel DM": 60000}}
    }},
    "DO": {"flag": "🇩🇴", "name": "Dominican Republic", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance DO": 800000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco BHD": 1500000, "Banco Popular Dominicano": 1800000, "Banreservas": 2100000}},
        "business": {"name": "🏢 Business", "items": {"Santo Domingo Hub": 450000}},
        "network": {"name": "📡 Network", "items": {"Claro DO": 4200000, "Altice DO": 3100000, "Viva DO": 850000}}
    }},
    "EC": {"flag": "🇪🇨", "name": "Ecuador", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance EC": 950000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Pichincha": 2800000, "Banco Guayaquil": 1900000, "Produbanco": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Quito Commerce Hub": 350000}},
        "network": {"name": "📡 Network", "items": {"Conecel (Claro)": 5100000, "Otecel (Movistar)": 3800000, "CNT": 1400000}}
    }},
    "EG": {"flag": "🇪🇬", "name": "Egypt", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance EG": 3200000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Egypt": 9500000, "Banque Misr": 8200000, "CIB Egypt": 4100000}},
        "business": {"name": "🏢 Business", "items": {"Cairo Silicon Hub": 1800000}},
        "network": {"name": "📡 Network", "items": {"Vodafone Egypt": 24000000, "Orange EG": 14500000, "Etisalat Egypt": 12000000, "WE": 8500000}}
    }},
    "SV": {"flag": "🇸🇻", "name": "El Salvador", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Chivo Wallet Hub": 1500000, "Binance SV": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Agrícola": 1100000, "Cuscatlan": 900000}},
        "business": {"name": "🏢 Business", "items": {"Bitcoin City Corp": 300000}},
        "network": {"name": "📡 Network", "items": {"Tigo SV": 2400000, "Claro SV": 1900000, "Digicel SV": 1200000}}
    }},
    "GQ": {"flag": "🇬🇶", "name": "Equatorial Guinea", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GQ": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"BGFI Bank GE": 70000, "CCEI Bank": 90000}},
        "business": {"name": "🏢 Business", "items": {"Malabo Oil Hub": 50000}},
        "network": {"name": "📡 Network", "items": {"Gecomsa": 150000, "Orange GQ": 120000}}
    }},
    "ER": {"flag": "🇪🇷", "name": "Eritrea", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ER": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Commercial Bank of Eritrea": 80000}},
        "business": {"name": "🏢 Business", "items": {"Asmara Trade": 30000}},
        "network": {"name": "📡 Network", "items": {"EriTel": 300000}}
    }},
    "EE": {"flag": "🇪🇪", "name": "Estonia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"CoinMetro": 300000, "Binance EE": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"Swedbank EE": 950000, "SEB Pank": 850000, "LHV Pank": 600000}},
        "business": {"name": "🏢 Business", "items": {"e-Residency Hub": 1200000}},
        "network": {"name": "📡 Network", "items": {"Telia EE": 430000, "Elisa EE": 380000, "Tele2 EE": 290000}}
    }},
    "SZ": {"flag": "🇸🇿", "name": "Eswatini", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SZ": 30000}},
        "bank": {"name": "🏦 Banks", "items": {"Standard Bank Eswatini": 150000, "Nedbank Eswatini": 120000}},
        "business": {"name": "🏢 Business", "items": {"Mbabane Trade Hub": 50000}},
        "network": {"name": "📡 Network", "items": {"MTN Eswatini": 600000, "Eswatini Mobile": 250000}}
    }},
    "ET": {"flag": "🇪🇹", "name": "Ethiopia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ET": 850000}},
        "bank": {"name": "🏦 Banks", "items": {"Commercial Bank of Ethiopia": 5500000, "Dashen Bank": 1800000, "Awash Bank": 1600000}},
        "business": {"name": "🏢 Business", "items": {"Addis Ababa Trade Corp": 700000}},
        "network": {"name": "📡 Network", "items": {"Ethio Telecom": 24000000, "Safaricom Ethiopia": 4200000}}
    }},
    "FJ": {"flag": "🇫🇯", "name": "Fiji", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance FJ": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"ANZ Fiji": 200000, "BSP Fiji": 180000}},
        "business": {"name": "🏢 Business", "items": {"Suva Trade Hub": 60000}},
        "network": {"name": "📡 Network", "items": {"Vodafone Fiji": 550000, "Digicel Fiji": 480000}}
    }},
    "FI": {"flag": "🇫🇮", "name": "Finland", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Coinmotion": 350000, "Binance FI": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Nordea FI": 1900000, "OP Financial Group": 2200000, "Danske Bank FI": 850000}},
        "business": {"name": "🏢 Business", "items": {"Helsinki Tech Hub": 500000}},
        "network": {"name": "📡 Network", "items": {"Elisa": 1800000, "DNA": 1500000, "Telia FI": 1200000}}
    }},
    "FR": {"flag": "🇫🇷", "name": "France", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Coinhouse": 900000, "Binance FR": 2400000}},
        "bank": {"name": "🏦 Banks", "items": {"BNP Paribas": 6500000, "Crédit Agricole": 7200000, "Société Générale": 4800000, "Boursorama": 3100000}},
        "business": {"name": "🏢 Business", "items": {"Station F Tech Hub": 1800000}},
        "network": {"name": "📡 Network", "items": {"Orange": 6200000, "SFR": 4800000, "Bouygues": 4100000, "Free Mobile": 3500000}}
    }},
    "GA": {"flag": "🇬🇦", "name": "Gabon", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GA": 70000}},
        "bank": {"name": "🏦 Banks", "items": {"BGFI Bank Gabon": 300000, "UGB Gabon": 200000}},
        "business": {"name": "🏢 Business", "items": {"Libreville Trade": 90000}},
        "network": {"name": "📡 Network", "items": {"Gabon Télécom (Moov)": 950000, "Airtel Gabon": 800000}}
    }},
    "GM": {"flag": "🇬🇲", "name": "Gambia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GM": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"Trust Bank Gambia": 150000, "Ecobank Gambia": 100000}},
        "business": {"name": "🏢 Business", "items": {"Banjul Port Trade": 50000}},
        "network": {"name": "📡 Network", "items": {"Africell Gambia": 1200000, "Qcell": 800000}}
    }},
    "GE": {"flag": "🇬🇪", "name": "Georgia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GE": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Georgia": 1400000, "TBC Bank": 1500000, "Liberty Bank": 600000}},
        "business": {"name": "🏢 Business", "items": {"Tbilisi Startup Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"MagtiCom": 1800000, "Silknet": 1500000, "Cellfie": 700000}}
    }},
    "DE": {"flag": "🇩🇪", "name": "Germany", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bison App": 2100000, "Binance DE": 3900000, "Coinbase DE": 1800000}},
        "bank": {"name": "🏦 Banks", "items": {"Deutsche Bank": 7800000, "Commerzbank": 5100000, "Sparkasse": 9500000, "N26": 3200000}},
        "business": {"name": "🏢 Business", "items": {"Berlin Tech Hub": 2400000, "SAP Partner Network": 1500000}},
        "network": {"name": "📡 Network", "items": {"Telekom": 8900000, "Vodafone": 7200000, "O2": 5800000, "1&1": 1400000}}
    }},
    "GH": {"flag": "🇬🇭", "name": "Ghana", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GH": 1200000}},
        "bank": {"name": "🏦 Banks", "items": {"GCB Bank": 2100000, "Stanbic Ghana": 1100000, "Ecobank Ghana": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Accra Digital Hub": 500000}},
        "network": {"name": "📡 Network", "items": {"MTN Ghana": 8900000, "Vodafone GH": 3200000, "AirtelTigo": 2100000}}
    }},
    "GR": {"flag": "🇬🇷", "name": "Greece", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GR": 800000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Greece": 2400000, "Piraeus Bank": 2100000, "Alpha Bank": 1900000}},
        "business": {"name": "🏢 Business", "items": {"Athens Innovation Hub": 450000}},
        "network": {"name": "📡 Network", "items": {"Cosmote": 2800000, "Vodafone": 1900000, "Wind Hellas": 1400000, "Nova": 680000}}
    }},
    "GD": {"flag": "🇬🇩", "name": "Grenada", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GD": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Republic Bank Grenada": 60000}},
        "business": {"name": "🏢 Business", "items": {"St. George's Trade": 20000}},
        "network": {"name": "📡 Network", "items": {"Flow Grenada": 80000, "Digicel GD": 70000}}
    }},
    "GT": {"flag": "🇬🇹", "name": "Guatemala", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GT": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Industrial": 2400000, "BAC Guatemala": 1500000}},
        "business": {"name": "🏢 Business", "items": {"Guatemala City Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Tigo GT": 5100000, "Claro GT": 4200000}}
    }},
    "GN": {"flag": "🇬🇳", "name": "Guinea", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GN": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Guinea": 300000, "Société Générale Guinée": 250000}},
        "business": {"name": "🏢 Business", "items": {"Conakry Trade Hub": 110000}},
        "network": {"name": "📡 Network", "items": {"Orange GN": 3100000, "MTN Guinea": 2200000}}
    }},
    "GW": {"flag": "🇬🇼", "name": "Guinea-Bissau", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GW": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"BAO Guinea-Bissau": 60000}},
        "business": {"name": "🏢 Business", "items": {"Bissau Port Trade": 25000}},
        "network": {"name": "📡 Network", "items": {"MTN Guinea-Bissau": 350000, "Orange GW": 300000}}
    }},
    "GY": {"flag": "🇬🇾", "name": "Guyana", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance GY": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"Republic Bank Guyana": 150000, "GBTI": 120000}},
        "business": {"name": "🏢 Business", "items": {"Georgetown Oil Hub": 80000}},
        "network": {"name": "📡 Network", "items": {"GTT": 350000, "Digicel GY": 280000}}
    }},
    "HT": {"flag": "🇭🇹", "name": "Haiti", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance HT": 180000}},
        "bank": {"name": "🏦 Banks", "items": {"Sogebank": 700000, "Unibank HT": 800000}},
        "business": {"name": "🏢 Business", "items": {"Port-au-Prince Hub": 150000}},
        "network": {"name": "📡 Network", "items": {"Digicel Haiti": 3200000, "Natcom": 1100000}}
    }},
    "HN": {"flag": "🇭🇳", "name": "Honduras", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance HN": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Atlántida": 1400000, "BAC Honduras": 1200000}},
        "business": {"name": "🏢 Business", "items": {"San Pedro Sula Trade": 350000}},
        "network": {"name": "📡 Network", "items": {"Tigo HN": 3800000, "Claro HN": 2500000}}
    }},
    "HU": {"flag": "🇭🇺", "name": "Hungary", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance HU": 750000}},
        "bank": {"name": "🏦 Banks", "items": {"OTP Bank": 3100000, "K&H Bank": 1500000, "Erste Bank HU": 1200000}},
        "business": {"name": "🏢 Business", "items": {"Budapest Tech Hub": 550000}},
        "network": {"name": "📡 Network", "items": {"Telekom HU": 2100000, "Yettel": 1400000, "Vodafone HU": 980000}}
    }},
    "IS": {"flag": "🇮🇸", "name": "Iceland", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance IS": 80000}},
        "bank": {"name": "🏦 Banks", "items": {"Landsbankinn": 250000, "Arion Bank": 220000, "Íslandsbanki": 210000}},
        "business": {"name": "🏢 Business", "items": {"Reykjavik Data Center Hub": 90000}},
        "network": {"name": "📡 Network", "items": {"Siminn": 180000, "Vodafone IS": 140000, "Nova": 110000}}
    }},
    "IN": {"flag": "🇮🇳", "name": "India", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"WazirX": 8500000, "CoinDCX": 7900000, "Binance IN P2P": 14500000}},
        "bank": {"name": "🏦 Banks", "items": {"State Bank of India": 35000000, "HDFC Bank": 28000000, "ICICI Bank": 24000000, "Axis Bank": 15000000}},
        "business": {"name": "🏢 Business", "items": {"Reliance Jio Corp": 19000000, "Tata Consultancy Hub": 12000000, "Infosys Network": 8500000}},
        "network": {"name": "📡 Network", "items": {"Jio": 45000000, "Airtel": 38000000, "Vi (Vodafone Idea)": 21000000, "BSNL": 9500000}}
    }},
    "ID": {"flag": "🇮🇩", "name": "Indonesia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Tokocrypto": 3100000, "Indodax": 3800000, "Binance ID": 5100000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Central Asia (BCA)": 11500000, "Bank Mandiri": 10200000, "BRI": 9800000, "BNI": 7400000}},
        "business": {"name": "🏢 Business", "items": {"GoTo Fintech Hub": 6100000, "Tokopedia Partner": 4500000}},
        "network": {"name": "📡 Network", "items": {"Telkomsel": 24000000, "Indosat Ooredoo": 18000000, "XL Axiata": 14000000, "Smartfren": 6500000}}
    }},
    "IR": {"flag": "🇮🇷", "name": "Iran", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Nobitex": 1900000, "Binance IR P2P": 3100000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Melli Iran": 7500000, "Bank Mellat": 6800000, "Parsian Bank": 4200000}},
        "business": {"name": "🏢 Business", "items": {"Tehran Trade Hub": 1500000}},
        "network": {"name": "📡 Network", "items": {" همراه اول (MCI)": 22000000, "Irancell": 18000000, "Rightel": 3500000}}
    }},
    "IQ": {"flag": "🇮🇶", "name": "Iraq", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance IQ": 950000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Iraq": 1100000, "Dar Es Salaam Bank": 850000}},
        "business": {"name": "🏢 Business", "items": {"Baghdad Trade Center": 400000}},
        "network": {"name": "📡 Network", "items": {"Zain Iraq": 14000000, "Asiacell": 12500000, "Korek Telecom": 5100000}}
    }},
    "IE": {"flag": "🇮🇪", "name": "Ireland", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Coinbase IE": 700000, "Binance IE": 900000, "Kraken IE": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Ireland": 1800000, "AIB": 1500000, "Permanent TSB": 950000, "Revolut IE": 1200000}},
        "business": {"name": "🏢 Business", "items": {"Stripe IE": 1400000, "PayPal IE": 1600000}},
        "network": {"name": "📡 Network", "items": {"Eir": 833503, "Tesco Mobile": 520700, "Three A": 351645, "Three B": 861444, "Vodafone": 1720550}}
    }},
    "IL": {"flag": "🇮🇱", "name": "Israel", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bits of Gold": 450000, "Binance IL": 1100000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Hapoalim": 2100000, "Bank Leumi": 2300000, "Israel Discount Bank": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Tel Aviv Hi-Tech Hub": 1800000}},
        "network": {"name": "📡 Network", "items": {"Cellcom": 2800000, "Pelephone": 2600000, "Partner IL": 2200000, "Hot Mobile": 1500000}}
    }},
    "IT": {"flag": "🇮🇹", "name": "Italy", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Young Platform": 600000, "Binance IT": 2100000}},
        "bank": {"name": "🏦 Banks", "items": {"Intesa Sanpaolo": 6400000, "UniCredit": 5800000, "Banco BPM": 2100000, "FinecoBank": 1900000}},
        "business": {"name": "🏢 Business", "items": {"Milan Fintech Hub": 1100000}},
        "network": {"name": "📡 Network", "items": {"TIM": 5900000, "Vodafone": 4200000, "WindTre": 5100000, "Iliad": 1800000, "PosteMobile": 890000}}
    }},
    "JM": {"flag": "🇯🇲", "name": "Jamaica", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance JM": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"NCB Jamaica": 950000, "Scotiabank Jamaica": 750000, "JMMB": 500000}},
        "business": {"name": "🏢 Business", "items": {"Kingston Business Hub": 200000}},
        "network": {"name": "📡 Network", "items": {"Digicel Jamaica": 1900000, "Flow JM": 1100000}}
    }},
    "JP": {"flag": "🇯🇵", "name": "Japan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"bitFlyer": 2400000, "Coincheck": 2100000, "Binance JP": 1500000}},
        "bank": {"name": "🏦 Banks", "items": {"Mitsubishi UFJ (MUFG)": 11000000, "Sumitomo Mitsui (SMBC)": 8500000, "Mizuho Bank": 7800000, "Japan Post Bank": 12500000}},
        "business": {"name": "🏢 Business", "items": {"Rakuten Group Hub": 5200000, "SoftBank Corp": 6800000}},
        "network": {"name": "📡 Network", "items": {"NTT Docomo": 28000000, "KDDI (au)": 21000000, "SoftBank": 18500000, "Rakuten Mobile": 5100000}}
    }},
    "JO": {"flag": "🇯🇴", "name": "Jordan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance JO": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"Arab Bank": 1400000, "Housing Bank for Trade & Finance": 950000}},
        "business": {"name": "🏢 Business", "items": {"Amman Tech Oasis": 300000}},
        "network": {"name": "📡 Network", "items": {"Zain Jordan": 2800000, "Orange JO": 1900000, "Umniah": 1600000}}
    }},
    "KZ": {"flag": "🇰🇿", "name": "Kazakhstan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KZ": 1200000, "BTA Crypto Hub": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Halyk Bank": 3500000, "Kaspi Bank": 5100000, "Jusan Bank": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Astana Hub": 600000}},
        "network": {"name": "📡 Network", "items": {"Kcell": 5200000, "Beeline KZ": 5800000, "Tele2 KZ": 3100000}}
    }},
    "KE": {"flag": "🇰🇪", "name": "Kenya", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KE": 1800000, "Paxful KE Legacy": 900000}},
        "bank": {"name": "🏦 Banks", "items": {"KCB Bank Kenya": 3800000, "Equity Bank Kenya": 4200000, "Co-operative Bank": 2100000}},
        "business": {"name": "🏢 Business", "items": {"M-Pesa Safaricom Hub": 8500000, "Nairobi Garage": 400000}},
        "network": {"name": "📡 Network", "items": {"Safaricom": 16000000, "Airtel KE": 4500000, "Telkom Kenya": 1100000}}
    }},
    "KI": {"flag": "🇰🇮", "name": "Kiribati", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KI": 5000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Kiribati": 20000}},
        "business": {"name": "🏢 Business", "items": {"Tarawa Trade": 10000}},
        "network": {"name": "📡 Network", "items": {"Telecom Services Kiribati": 40000}}
    }},
    "KP": {"flag": "🇰🇵", "name": "Korea (North)", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"State Mining Hub": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"Central Bank of DPRK": 100000}},
        "business": {"name": "🏢 Business", "items": {"Pyongyang State Corp": 40000}},
        "network": {"name": "📡 Network", "items": {"Koryolink": 500000}}
    }},
    "KR": {"flag": "🇰🇷", "name": "Korea (South)", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Upbit": 6800000, "Bithumb": 4200000, "Korbit": 1100000, "Coinone": 1500000}},
        "bank": {"name": "🏦 Banks", "items": {"KB Kookmin Bank": 9500000, "Shinhan Bank": 8800000, "Woori Bank": 7200000, "KakaoBank": 8100000}},
        "business": {"name": "🏢 Business", "items": {"Samsung Electronics Hub": 11000000, "Naver Corp": 6500000}},
        "network": {"name": "📡 Network", "items": {"SK Telecom": 21000000, "KT Corp": 16500000, "LG Uplus": 12000000}}
    }},
    "KW": {"flag": "🇰🇼", "name": "Kuwait", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KW": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Kuwait": 1800000, "Kuwait Finance House": 2100000}},
        "business": {"name": "🏢 Business", "items": {"Kuwait Oil Hub": 500000}},
        "network": {"name": "📡 Network", "items": {"Zain KW": 2900000, "Ooredoo KW": 1800000, "STC Kuwait": 1400000}}
    }},
    "KG": {"flag": "🇰🇬", "name": "Kyrgyzstan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KG": 200000}},
        "bank": {"name": "🏦 Banks", "items": {"Optima Bank": 500000, "Demir Bank": 350000}},
        "business": {"name": "🏢 Business", "items": {"Bishkek Trade Hub": 150000}},
        "network": {"name": "📡 Network", "items": {"O! Kyrgyzstan": 1800000, "Beeline KG": 1500000, "Megacom": 1400000}}
    }},
    "LA": {"flag": "🇱🇦", "name": "Laos", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LA": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Banque pour le Commerce Extérieur Lao": 400000, "JDB Laos": 250000}},
        "business": {"name": "🏢 Business", "items": {"Vientiane Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"Unitel Laos": 1900000, "Lao Telecom": 1400000, "ETL": 500000}}
    }},
    "LV": {"flag": "🇱🇻", "name": "Latvia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LV": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Swedbank LV": 850000, "SEB Latvia": 650000, "Citadele Bank": 400000}},
        "business": {"name": "🏢 Business", "items": {"Riga Tech Hub": 250000}},
        "network": {"name": "📡 Network", "items": {"LMT": 540000, "Tele2 LV": 430000, "Bite": 320000}}
    }},
    "LB": {"flag": "🇱🇧", "name": "Lebanon", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LB": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Audi": 1100000, "Blom Bank": 950000, "Byblos Bank": 800000}},
        "business": {"name": "🏢 Business", "items": {"Beirut Business Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Alfa Lebanon": 2100000, "touch Lebanon": 2200000}}
    }},
    "LS": {"flag": "🇱🇸", "name": "Lesotho", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LS": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"Standard Lesotho Bank": 150000, "FNB Lesotho": 100000}},
        "business": {"name": "🏢 Business", "items": {"Maseru Trade Hub": 40000}},
        "network": {"name": "📡 Network", "items": {"Vodacom Lesotho": 950000, "Econet Lesotho": 450000}}
    }},
    "LR": {"flag": "🇱🇷", "name": "Liberia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LR": 30000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Liberia": 120000, "LBDI": 90000}},
        "business": {"name": "🏢 Business", "items": {"Monrovia Port Trade": 50000}},
        "network": {"name": "📡 Network", "items": {"Orange Liberia": 1100000, "Lonestar Cell MTN": 1300000}}
    }},
    "LY": {"flag": "🇱🇾", "name": "Libya", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LY": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"National Commercial Bank LY": 900000, "Gumhouria Bank": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Tripoli Oil Hub": 350000}},
        "network": {"name": "📡 Network", "items": {"Al-Madar Al-Jadeed": 3800000, "Libyana": 5100000}}
    }},
    "LI": {"flag": "🇱🇮", "name": "Liechtenstein", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"LCX Exchange": 200000, "Binance LI": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"LGT Bank": 150000, "Liechtensteinische Landesbank": 120000}},
        "business": {"name": "🏢 Business", "items": {"Vaduz Finance Hub": 80000}},
        "network": {"name": "📡 Network", "items": {"Telecom Liechtenstein": 60000}}
    }},
    "LT": {"flag": "🇱🇹", "name": "Lithuania", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LT": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"Swedbank LT": 1100000, "SEB Lietuva": 950000, "Šiaulių bankas": 400000}},
        "business": {"name": "🏢 Business", "items": {"Vilnius Fintech Hub": 800000}},
        "network": {"name": "📡 Network", "items": {"Tele2": 890000, "Bite": 760000, "Telia LT": 540000}}
    }},
    "LU": {"flag": "🇱🇺", "name": "Luxembourg", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitstamp Hub": 500000, "Binance LU": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"Spuerkeess": 600000, "BGL BNP Paribas": 550000}},
        "business": {"name": "🏢 Business", "items": {"Kirchberg Financial Hub": 700000}},
        "network": {"name": "📡 Network", "items": {"POST Luxembourg": 350000, "Tango": 250000, "Orange LU": 180000}}
    }},
    "MG": {"flag": "🇲🇬", "name": "Madagascar", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MG": 120000}},
        "bank": {"name": "🏦 Banks", "items": {"BNI Madagascar": 450000, "Société Générale Madagasikara": 350000}},
        "business": {"name": "🏢 Business", "items": {"Antananarivo Trade": 150000}},
        "network": {"name": "📡 Network", "items": {"Orange MG": 3200000, "Telma": 3800000, "Airtel MG": 2100000}}
    }},
    "MW": {"flag": "🇲🇼", "name": "Malawi", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MW": 70000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Malawi": 400000, "Standard Bank Malawi": 350000}},
        "business": {"name": "🏢 Business", "items": {"Lilongwe Trade Hub": 100000}},
        "network": {"name": "📡 Network", "items": {"TNM Malawi": 2800000, "Airtel Malawi": 3100000}}
    }},
    "MY": {"flag": "🇲🇾", "name": "Malaysia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"MX Global": 600000, "Binance MY P2P": 1900000}},
        "bank": {"name": "🏦 Banks", "items": {"Maybank": 6800000, "CIMB Bank": 5900000, "Public Bank Berhad": 5100000, "RHB Bank": 3200000}},
        "business": {"name": "🏢 Business", "items": {"Kuala Lumpur Tech Hub": 2100000}},
        "network": {"name": "📡 Network", "items": {"Maxis": 4200000, "Celcom": 3100000, "Digi": 3800000, "U Mobile": 1400000, "Unifi": 980000}}
    }},
    "MV": {"flag": "🇲🇻", "name": "Maldives", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MV": 30000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Maldives": 250000, "MIB Maldives": 100000}},
        "business": {"name": "🏢 Business", "items": {"Male Resort Hub": 80000}},
        "network": {"name": "📡 Network", "items": {"Dhiraagu": 350000, "Ooredoo Maldives": 310000}}
    }},
    "ML": {"flag": "🇲🇱", "name": "Mali", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ML": 90000}},
        "bank": {"name": "🏦 Banks", "items": {"BNDA Mali": 300000, "Ecobank Mali": 200000}},
        "business": {"name": "🏢 Business", "items": {"Bamako Trade": 110000}},
        "network": {"name": "📡 Network", "items": {"Orange Mali": 5100000, "Moov Africa Malitel": 3900000}}
    }},
    "MT": {"flag": "🇲🇹", "name": "Malta", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance Malta Hub": 400000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Valletta": 350000, "HSBC Malta": 250000}},
        "business": {"name": "🏢 Business", "items": {"Valletta Gaming Hub": 500000}},
        "network": {"name": "📡 Network", "items": {"GO": 180000, "Melita": 140000, "Epic": 110000}}
    }},
    "MH": {"flag": "🇲🇭", "name": "Marshall Islands", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"SOV Decentralized Hub": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Marshall Islands": 30000}},
        "business": {"name": "🏢 Business", "items": {"Majuro Maritime Hub": 15000}},
        "network": {"name": "📡 Network", "items": {"Namarag": 40000}}
    }},
    "MR": {"flag": "🇲🇷", "name": "Mauritania", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MR": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"BNM Mauritania": 120000, "Attijariwafa Bank Mauritanie": 90000}},
        "business": {"name": "🏢 Business", "items": {"Nouakchott Trade": 50000}},
        "network": {"name": "📡 Network", "items": {"Mauritel": 1400000, "Chinguitel": 900000, "Mattel": 600000}}
    }},
    "MU": {"flag": "🇲🇺", "name": "Mauritius", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MU": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"MCB Mauritius": 850000, "SBM Bank": 650000}},
        "business": {"name": "🏢 Business", "items": {"Cybercity Ebene Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"My.T (Mauritius Telecom)": 950000, "Emtel": 800000, "Chili": 200000}}
    }},
    "MX": {"flag": "🇲🇽", "name": "Mexico", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitso": 3800000, "Binance MX": 4200000}},
        "bank": {"name": "🏦 Banks", "items": {"BBVA Mexico": 12500000, "Banorte": 8900000, "Santander Mexico": 7400000, "Citibanamex": 9100000}},
        "business": {"name": "🏢 Business", "items": {"Kavak Tech Hub": 1900000, "Mexico Fintech Hub": 2400000}},
        "network": {"name": "📡 Network", "items": {"Telcel": 24000000, "Movistar MX": 11500000, "AT&T Mexico": 9800000, "Altán Redes": 2100000}}
    }},
    "FM": {"flag": "🇫🇲", "name": "Micronesia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance FM": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of the FSM": 40000}},
        "business": {"name": "🏢 Business", "items": {"Pohnpei Trade": 15000}},
        "network": {"name": "📡 Network", "items": {"FSM Telecom": 50000}}
    }},
    "MD": {"flag": "🇲🇩", "name": "Moldova", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MD": 200000}},
        "bank": {"name": "🏦 Banks", "items": {"maib": 1100000, "Victoriabank": 750000, "OTP Bank MD": 500000}},
        "business": {"name": "🏢 Business", "items": {"Chisinau IT Park": 300000}},
        "network": {"name": "📡 Network", "items": {"Orange Moldova": 1800000, "Moldcell": 1500000, "Moldtelecom": 900000}}
    }},
    "MC": {"flag": "🇲🇨", "name": "Monaco", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MC": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"CFM Indosuez": 120000, "CMP Banque": 90000}},
        "business": {"name": "🏢 Business", "items": {"Monte Carlo Luxury Corp": 150000}},
        "network": {"name": "📡 Network", "items": {"Monaco Telecom": 80000}}
    }},
    "MN": {"flag": "🇲🇳", "name": "Mongolia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MN": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Khan Bank": 1500000, "TDB Mongolia": 800000, "Golomt Bank": 750000}},
        "business": {"name": "🏢 Business", "items": {"Ulaanbaatar Mining Hub": 250000}},
        "network": {"name": "📡 Network", "items": {"Unitel MN": 1400000, "Mobicom": 1600000, "G-Mobile": 600000}}
    }},
    "ME": {"flag": "🇲🇪", "name": "Montenegro", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ME": 80000}},
        "bank": {"name": "🏦 Banks", "items": {"CKB Bank": 350000, "NLB Banka Podgorica": 300000}},
        "business": {"name": "🏢 Business", "items": {"Porto Montenegro Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"One Montenegro": 350000, "Telenor/A1 ME": 380000, "Telekom ME": 320000}}
    }},
    "MA": {"flag": "🇲🇦", "name": "Morocco", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MA": 1800000}},
        "bank": {"name": "🏦 Banks", "items": {"Attijariwafa Bank": 4800000, "Banque Centrale Populaire": 5100000, "Bank of Africa": 2900000}},
        "business": {"name": "🏢 Business", "items": {"Casablanca Finance City": 1200000}},
        "network": {"name": "📡 Network", "items": {"Maroc Telecom": 19000000, "Orange Morocco": 14200000, "Inwi": 11500000}}
    }},
    "MZ": {"flag": "🇲🇿", "name": "Mozambique", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MZ": 200000}},
        "bank": {"name": "🏦 Banks", "items": {"Millennium bim": 1400000, "Standard Bank Mozambique": 800000}},
        "business": {"name": "🏢 Business", "items": {"Maputo Trade Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Vodacom MZ": 6100000, "Movitel": 4800000, "Tmcel": 2100000}}
    }},
    "MM": {"flag": "🇲🇲", "name": "Myanmar", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance MM": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"KBZ Bank": 3500000, "AYA Bank": 1800000, "CB Bank": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Yangon Trade Hub": 600000}},
        "network": {"name": "📡 Network", "items": {"MPT": 19000000, "Atom (Telenor)": 1400000, "Ooredoo Myanmar": 9500000, "Mytel": 11000000}}
    }},
    "NA": {"flag": "🇳🇦", "name": "Namibia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NA": 70000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Windhoek": 350000, "Standard Bank Namibia": 300000}},
        "business": {"name": "🏢 Business", "items": {"Windhoek Mining Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"MTC Namibia": 1400000, "Telecom Namibia": 400000}}
    }},
    "NR": {"flag": "🇳🇷", "name": "Nauru", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NR": 5000}},
        "bank": {"name": "🏦 Banks", "items": {"Bendigo Bank Agency": 10000}},
        "business": {"name": "🏢 Business", "items": {"Nauru Phosphate Corp": 15000}},
        "network": {"name": "📡 Network", "items": {"Digicel Nauru": 10000}}
    }},
    "NP": {"flag": "🇳🇵", "name": "Nepal", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NP": 800000}},
        "bank": {"name": "🏦 Banks", "items": {"Global IME Bank": 2100000, "NIC Asia Bank": 2400000, "Nabil Bank": 1800000}},
        "business": {"name": "🏢 Business", "items": {"Kathmandu Tech Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Ncell": 11500000, "Nepal Telecom (NTC)": 14200000, "Smart Telecom": 1100000}}
    }},
    "NL": {"flag": "🇳🇱", "name": "Netherlands", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitvavo": 2800000, "Binance NL": 2100000}},
        "bank": {"name": "🏦 Banks", "items": {"ING Bank": 8500000, "Rabobank": 7100000, "ABN AMRO": 5900000, "Adyen": 1800000}},
        "business": {"name": "🏢 Business", "items": {"Amsterdam Tech Hub": 2200000}},
        "network": {"name": "📡 Network", "items": {"KPN": 3200000, "VodafoneZiggo": 2800000, "T-Mobile NL": 2100000, "Tele2": 890000}}
    }},
    "NZ": {"flag": "🇳🇿", "name": "New Zealand", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Easy Crypto": 600000, "Binance NZ": 550000}},
        "bank": {"name": "🏦 Banks", "items": {"ANZ New Zealand": 2400000, "ASB Bank": 2100000, "Bank of New Zealand (BNZ)": 1900000, "Westpac NZ": 1800000}},
        "business": {"name": "🏢 Business", "items": {"Auckland Tech Hub": 600000}},
        "network": {"name": "📡 Network", "items": {"Spark": 1800000, "One NZ": 1400000, "2degrees": 980000}}
    }},
    "NI": {"flag": "🇳🇮", "name": "Nicaragua", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NI": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Lafise": 600000, "BAC Nicaragua": 550000}},
        "business": {"name": "🏢 Business", "items": {"Managua Trade Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"Tigo NI": 2100000, "Claro NI": 2400000}}
    }},
    "NE": {"flag": "🇳🇪", "name": "Niger", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NE": 50000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Niger": 180000, "Orabank Niger": 120000}},
        "business": {"name": "🏢 Business", "items": {"Niamey Trade Hub": 70000}},
        "network": {"name": "📡 Network", "items": {"Airtel Niger": 3100000, "Moov Africa Niger": 2200000}}
    }},
    "NG": {"flag": "🇳🇬", "name": "Nigeria", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance NG P2P Hub": 12500000, "Quidax": 2400000, "Busha": 1900000}},
        "bank": {"name": "🏦 Banks", "items": {"Guaranty Trust Bank (GTB)": 14000000, "Zenith Bank": 12500000, "Access Bank": 15200000, "UBA": 11000000, "First Bank of Nigeria": 13100000}},
        "business": {"name": "🏢 Business", "items": {"Flutterwave Fintech Hub": 5200000, "Paystack Merchant Network": 4800000, "Jumia Nigeria": 3100000}},
        "network": {"name": "📡 Network", "items": {"MTN Nigeria": 45000000, "Airtel Nigeria": 28000000, "Globacom (Glo)": 21000000, "9mobile": 9500000}}
    }},
    "NO": {"flag": "🇳🇴", "name": "Norway", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Firi": 450000, "Binance NO": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"DNB ASA": 3100000, "Nordea Norge": 1200000, "Danske Bank NO": 700000}},
        "business": {"name": "🏢 Business", "items": {"Oslo Innovation Hub": 500000}},
        "network": {"name": "📡 Network", "items": {"Telenor": 2400000, "Telia NO": 1800000, "Ice": 760000}}
    }},
    "OM": {"flag": "🇴🇲", "name": "Oman", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance OM": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank Muscat": 1800000, "National Bank of Oman": 850000, "Bank Dhofar": 700000}},
        "business": {"name": "🏢 Business", "items": {"Muscat Business Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Omantel": 3400000, "Ooredoo Oman": 2800000, "Vodafone Oman": 950000}}
    }},
    "PK": {"flag": "🇵🇰", "name": "Pakistan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PK P2P": 9800000, "OKX Pakistan P2P": 4500000}},
        "bank": {"name": "🏦 Banks", "items": {"HBL Pakistan": 11500000, "Meezan Bank": 9200000, "National Bank of Pakistan": 7800000, "Alfalah": 6500000}},
        "business": {"name": "🏢 Business", "items": {"JazzCash Fintech Hub": 14000000, "Easypaisa Hub": 12500000}},
        "network": {"name": "📡 Network", "items": {"Jazz": 38000000, "Telenor PK": 24000000, "Zong 4G": 31000000, "Ufone": 18000000}}
    }},
    "PW": {"flag": "🇵🇼", "name": "Palau", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Palau RNS ID Crypto Hub": 20000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Guam Palau": 30000}},
        "business": {"name": "🏢 Business", "items": {"Koror Island Trade": 15000}},
        "network": {"name": "📡 Network", "items": {"PNCC Palau": 25000}}
    }},
    "PS": {"flag": "🇵🇸", "name": "Palestine", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PS": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Palestine": 900000, "Palestine Islamic Bank": 600000}},
        "business": {"name": "🏢 Business", "items": {"Ramallah Tech Hub": 200000}},
        "network": {"name": "📡 Network", "items": {"Jawwal": 2800000, "Wataniya Mobile (Ooredoo PS)": 1400000}}
    }},
    "PA": {"flag": "🇵🇦", "name": "Panama", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PA": 550000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco General": 1600000, "Global Bank": 950000, "Banistmo": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Panama Canal Trade Hub": 800000}},
        "network": {"name": "📡 Network", "items": {"Tigo Panama": 2100000, "+Movil (Cable & Wireless)": 2400000}}
    }},
    "PG": {"flag": "🇵🇬", "name": "Papua New Guinea", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PG": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"BSP Financial Group": 600000, "Kina Bank": 250000}},
        "business": {"name": "🏢 Business", "items": {"Port Moresby Mining Hub": 150000}},
        "network": {"name": "📡 Network", "items": {"Digicel PNG": 2400000, "Telikom PNG": 400000}}
    }},
    "PY": {"flag": "🇵🇾", "name": "Paraguay", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PY": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Itaú Paraguay": 1100000, "Sudameris Bank": 600000}},
        "business": {"name": "🏢 Business", "items": {"Asuncion Trade Hub": 250000}},
        "network": {"name": "📡 Network", "items": {"Tigo PY": 3500000, "Personal PY": 2200000, "Claro PY": 1400000}}
    }},
    "PE": {"flag": "🇵🇪", "name": "Peru", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PE": 1900000, "Buda PE": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco de Crédito del Perú (BCP)": 5800000, "Interbank": 4100000, "BBVA Peru": 3500000}},
        "business": {"name": "🏢 Business", "items": {"Lima Fintech Hub": 900000}},
        "network": {"name": "📡 Network", "items": {"Movistar PE": 9200000, "Claro PE": 7800000, "Entel PE": 4500000, "Bitel": 3100000}}
    }},
    "PH": {"flag": "🇵🇭", "name": "Philippines", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"PDAX": 1500000, "Coins.ph": 2800000, "Binance PH P2P": 7100000}},
        "bank": {"name": "🏦 Banks", "items": {"BDO Unibank": 11000000, "Bank of the Philippine Islands (BPI)": 9500000, "Land Bank of the Philippines": 6200000, "Metrobank": 7800000}},
        "business": {"name": "🏢 Business", "items": {"GCash Globe Fintech Hub": 18500000, "Maya Fintech Hub": 12000000}},
        "network": {"name": "📡 Network", "items": {"Globe Telecom": 35000000, "Smart Communications": 32000000, "DITO Telecommunity": 8500000}}
    }},
    "PL": {"flag": "🇵🇱", "name": "Poland", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Zonda Crypto": 900000, "Binance PL": 2900000}},
        "bank": {"name": "🏦 Banks", "items": {"PKO Bank Polski": 7500000, "Bank Pekao": 5200000, "Santander Bank Polska": 4800000, "mBank": 4100000}},
        "business": {"name": "🏢 Business", "items": {"Warsaw Tech Hub": 1900000}},
        "network": {"name": "📡 Network", "items": {"Orange": 4100000, "Play": 3800000, "Plus": 3200000, "T-Mobile PL": 2900000}}
    }},
    "PT": {"flag": "🇵🇹", "name": "Portugal", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance PT": 1400000}},
        "bank": {"name": "🏦 Banks", "items": {"Caixa Geral de Depósitos": 2800000, "Millennium bcp": 2400000, "Novo Banco": 1500000}},
        "business": {"name": "🏢 Business", "items": {"Lisbon Tech Hub": 900000}},
        "network": {"name": "📡 Network", "items": {"NOS": 2800000, "MEO": 2400000, "Vodafone PT": 1900000}}
    }},
    "QA": {"flag": "🇶🇦", "name": "Qatar", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance QA": 550000}},
        "bank": {"name": "🏦 Banks", "items": {"Qatar National Bank (QNB)": 2800000, "Doha Bank": 950000, "Commercial Bank of Qatar": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Doha Financial Hub": 600000}},
        "network": {"name": "📡 Network", "items": {"Ooredoo": 980000, "Vodafone Qatar": 760000}}
    }},
    "RO": {"flag": "🇷🇴", "name": "Romania", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance RO": 1800000}},
        "bank": {"name": "🏦 Banks", "items": {"Banca Comercială Română (BCR)": 3500000, "BRD Groupe Société Générale": 2800000, "Bancil Transilvania": 4200000}},
        "business": {"name": "🏢 Business", "items": {"Bucharest Tech Hub": 950000}},
        "network": {"name": "📡 Network", "items": {"Orange": 3200000, "Vodafone RO": 2800000, "Digi": 2100000, "Telekom": 1400000}}
    }},
    "RU": {"flag": "🇷🇺", "name": "Russia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance RU P2P Legacy": 12500000, "CommEX Hub": 4100000, "Garantex": 3500000}},
        "bank": {"name": "🏦 Banks", "items": {"Sberbank": 45000000, "Tinkoff Bank": 22000000, "VTB Bank": 18000000, "Alfa-Bank": 15000000}},
        "business": {"name": "🏢 Business", "items": {"Yandex Cloud Hub": 11000000, "VK Group Corp": 8500000}},
        "network": {"name": "📡 Network", "items": {"MTS": 38000000, "MegaFon": 31000000, "Beeline RU": 26000000, "Tele2 RU": 19000000}}
    }},
    "RW": {"flag": "🇷🇼", "name": "Rwanda", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance RW": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Kigali": 950000, "I&M Bank Rwanda": 450000}},
        "business": {"name": "🏢 Business", "items": {"Kigali Innovation City Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"MTN Rwanda": 3800000, "Airtel Rwanda": 1900000}}
    }},
    "KN": {"flag": "🇰🇳", "name": "Saint Kitts and Nevis", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance KN": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"St. Kitts-Nevis-Anguilla National Bank": 50000}},
        "business": {"name": "🏢 Business", "items": {"Basseterre Trade": 20000}},
        "network": {"name": "📡 Network", "items": {"Flow SKN": 40000, "Digicel SKN": 35000}}
    }},
    "LC": {"flag": "🇱🇨", "name": "Saint Lucia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LC": 15000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Saint Lucia": 80000}},
        "business": {"name": "🏢 Business", "items": {"Castries Trade": 25000}},
        "network": {"name": "📡 Network", "items": {"Flow LC": 90000, "Digicel LC": 80000}}
    }},
    "VC": {"flag": "🇻🇨", "name": "Saint Vincent and the Grenadines", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance VC": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Bank of Saint Vincent and the Grenadines": 60000}},
        "business": {"name": "🏢 Business", "items": {"Kingstown Trade": 20000}},
        "network": {"name": "📡 Network", "items": {"Flow SVG": 60000, "Digicel SVG": 50000}}
    }},
    "WS": {"flag": "🇼🇸", "name": "Samoa", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance WS": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Samoa": 50000}},
        "business": {"name": "🏢 Business", "items": {"Apia Trade Hub": 20000}},
        "network": {"name": "📡 Network", "items": {"Vodafone Samoa": 90000, "Digicel Samoa": 80000}}
    }},
    "SM": {"flag": "🇸🇲", "name": "San Marino", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SM": 15000}},
        "bank": {"name": "🏦 Banks", "items": {"Cassa di Risparmio di San Marino": 40000}},
        "business": {"name": "🏢 Business", "items": {"San Marino Corporate Hub": 20000}},
        "network": {"name": "📡 Network", "items": {"Telecom Italia San Marino": 30000}}
    }},
    "ST": {"flag": "🇸🇹", "name": "Sao Tome and Principe", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ST": 5000}},
        "bank": {"name": "🏦 Banks", "items": {"BGFI Bank STP": 30000}},
        "business": {"name": "🏢 Business", "items": {"Sao Tome Port Trade": 10000}},
        "network": {"name": "📡 Network", "items": {"CSTmóvel": 50000}}
    }},
    "SA": {"flag": "🇸🇦", "name": "Saudi Arabia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SA P2P": 3800000}},
        "bank": {"name": "🏦 Banks", "items": {"Al Rajhi Bank": 8500000, "National Commercial Bank (SNB)": 9200000, "Riyad Bank": 4500000, "Saudi British Bank": 3800000}},
        "business": {"name": "🏢 Business", "items": {"NEOM Tech Hub": 2100000, "Aramco Partner Network": 4500000}},
        "network": {"name": "📡 Network", "items": {"STC Saudi": 22000000, "Mobily": 14500000, "Zain KSA": 11000000}}
    }},
    "SN": {"flag": "🇸🇳", "name": "Senegal", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SN": 450000}},
        "bank": {"name": "🏦 Banks", "items": {"SG Sénégal": 950000, "Ecobank Sénégal": 800000, "Attijariwafa Bank Sénégal": 700000}},
        "business": {"name": "🏢 Business", "items": {"Dakar Tech Hub": 350000}},
        "network": {"name": "📡 Network", "items": {"Orange SN": 8500000, "Free Senegal": 4200000, "Expresso": 1800000}}
    }},
    "RS": {"flag": "🇷🇸", "name": "Serbia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Eldorado Crypto Hub": 250000, "Binance RS": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Banca Intesa Beograd": 1800000, "Komercijalna banka": 1500000, "UniCredit RS": 1100000}},
        "business": {"name": "🏢 Business", "items": {"Belgrade Tech Park": 450000}},
        "network": {"name": "📡 Network", "items": {"Telekom Srbija (MTS)": 3500000, "Yettel RS": 2400000, "A1 Serbia": 2100000}}
    }},
    "SC": {"flag": "🇸🇨", "name": "Seychelles", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"OKX Seychelles Hub": 600000, "KuCoin Hub": 700000, "Binance SC": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"MCB Seychelles": 120000, "Barclays SC": 90000}},
        "business": {"name": "🏢 Business", "items": {"Victoria Offshore Corp": 350000}},
        "network": {"name": "📡 Network", "items": {"Cable & Wireless Seychelles": 60000, "Airtel Seychelles": 50000}}
    }},
    "SL": {"flag": "🇸🇱", "name": "Sierra Leone", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SL": 60000}},
        "bank": {"name": "🏦 Banks", "items": {"Rokel Commercial Bank": 200000, "Sierra Leone Commercial Bank": 180000}},
        "business": {"name": "🏢 Business", "items": {"Freetown Port Trade": 80000}},
        "network": {"name": "📡 Network", "items": {"Orange SL": 2100000, "Africell SL": 2500000}}
    }},
    "SG": {"flag": "🇸🇬", "name": "Singapore", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Coinbase SG": 1900000, "Binance SG Hub": 2400000, "Crypto.com SG": 2100000}},
        "bank": {"name": "🏦 Banks", "items": {"DBS Bank": 4800000, "OCBC Bank": 3900000, "United Overseas Bank (UOB)": 3500000}},
        "business": {"name": "🏢 Business", "items": {"Marina Bay Fintech Hub": 3200000, "Grab Holdings Hub": 2900000}},
        "network": {"name": "📡 Network", "items": {"Singtel": 2100000, "StarHub": 1400000, "M1": 980000, "TPG": 320000}}
    }},
    "SK": {"flag": "🇸🇰", "name": "Slovakia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SK": 500000}},
        "bank": {"name": "🏦 Banks", "items": {"Slovenská sporiteľňa": 1800000, "VÚB Banka": 1500000, "Tatra banka": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Bratislava Tech Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Slovak Telekom": 1400000, "Orange SK": 1100000, "O2 SK": 760000}}
    }},
    "SI": {"flag": "🇸🇮", "name": "Slovenia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SI": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"NLB Banka": 900000, "NKBM": 700000}},
        "business": {"name": "🏢 Business", "items": {"Ljubljana Tech Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"A1": 540000, "Telekom SI": 430000, "T-2": 210000}}
    }},
    "SB": {"flag": "🇸🇧", "name": "Solomon Islands", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SB": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"BSP Solomon Islands": 80000}},
        "business": {"name": "🏢 Business", "items": {"Honiara Trade": 30000}},
        "network": {"name": "📡 Network", "items": {"Our Telekom": 70000, "Bmobile SB": 60000}}
    }},
    "SO": {"flag": "🇸🇴", "name": "Somalia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SO": 120000}},
        "bank": {"name": "🏦 Banks", "items": {"Salaam Somali Bank": 300000, "Dahabshiil Bank": 450000}},
        "business": {"name": "🏢 Business", "items": {"Mogadishu Trade Hub": 150000}},
        "network": {"name": "📡 Network", "items": {"Hormuud Telecom": 4200000, "Somtel": 1500000, "NationLink": 800000}}
    }},
    "ZA": {"flag": "🇿🇦", "name": "South Africa", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Luno": 2100000, "Binance ZA": 2400000, "VALR": 1100000}},
        "bank": {"name": "🏦 Banks", "items": {"Capitec Bank": 7800000, "Standard Bank": 6500000, "FirstRand (FNB)": 6900000, "Absa Bank": 5400000, "Nedbank": 4800000}},
        "business": {"name": "🏢 Business", "items": {"Johannesburg Fintech Hub": 1800000}},
        "network": {"name": "📡 Network", "items": {"Vodacom": 5200000, "MTN": 4800000, "Cell C": 2100000, "Telkom": 1400000}}
    }},
    "SS": {"flag": "🇸🇸", "name": "South Sudan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SS": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"Ivory Bank": 90000, "KCB Bank South Sudan": 120000}},
        "business": {"name": "🏢 Business", "items": {"Juba Oil Hub": 50000}},
        "network": {"name": "📡 Network", "items": {"MTN South Sudan": 1100000, "Zain SS": 950000}}
    }},
    "ES": {"flag": "🇪🇸", "name": "Spain", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bit2Me": 1400000, "Binance ES": 2900000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco Santander": 9500000, "BBVA": 8800000, "CaixaBank": 9100000, "Banco Sabadell": 3200000}},
        "business": {"name": "🏢 Business", "items": {"Madrid Tech Hub": 1800000, "Barcelona Innovation Hub": 1500000}},
        "network": {"name": "📡 Network", "items": {"Movistar": 7200000, "Orange": 5800000, "Vodafone": 4900000, "MásMóvil": 2100000, "Yoigo": 1400000}}
    }},
    "LK": {"flag": "🇱🇰", "name": "Sri Lanka", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance LK": 650000}},
        "bank": {"name": "🏦 Banks", "items": {"Commercial Bank of Ceylon": 2100000, "Hatton National Bank": 1800000, "Sampath Bank": 1600000}},
        "business": {"name": "🏢 Business", "items": {"Colombo IT Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Dialog Axiata": 8500000, "SLT-Mobitel": 5200000, "Hutch LK": 2100000, "Airtel Lanka": 1400000}}
    }},
    "SD": {"flag": "🇸🇩", "name": "Sudan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SD": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Khartoum Bank": 1800000, "Omdurman National Bank": 1400000}},
        "business": {"name": "🏢 Business", "items": {"Khartoum Trade Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"MTN Sudan": 7500000, "Zain SD": 11000000, "Sudani": 2100000}}
    }},
    "SR": {"flag": "🇸🇷", "name": "Suriname", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SR": 30000}},
        "bank": {"name": "🏦 Banks", "items": {"De Surinaamsche Bank": 120000, "Hakrinbank": 90000}},
        "business": {"name": "🏢 Business", "items": {"Paramaribo Trade": 40000}},
        "network": {"name": "📡 Network", "items": {"Telesur": 250000, "Digicel SR": 180000}}
    }},
    "SE": {"flag": "🇸🇪", "name": "Sweden", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Safello": 500000, "Binance SE": 1800000}},
        "bank": {"name": "🏦 Banks", "items": {"SEB": 2800000, "Swedbank": 3200000, "Nordea SE": 3100000, "Handelsbanken": 2400000}},
        "business": {"name": "🏢 Business", "items": {"Stockholm Tech Hub": 1600000, "Klarna Merchant Hub": 1900000}},
        "network": {"name": "📡 Network", "items": {"Telia": 3200000, "Tele2": 2800000, "Tre": 1900000, "Telenor": 1400000}}
    }},
    "CH": {"flag": "🇨🇭", "name": "Switzerland", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitcoin Suisse": 800000, "Sygnum Bank Hub": 500000, "Binance CH": 1200000}},
        "bank": {"name": "🏦 Banks", "items": {"UBS": 5200000, "Credit Suisse Legacy Hub": 3800000, "Raiffeisen Switzerland": 2900000, "Zürcher Kantonalbank": 1800000}},
        "business": {"name": "🏢 Business", "items": {"Zug Crypto Valley Hub": 1500000}},
        "network": {"name": "📡 Network", "items": {"Swisscom": 2800000, "Sunrise": 1900000, "Salt": 980000}}
    }},
    "SY": {"flag": "🇸🇾", "name": "Syria", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance SY": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Commercial Bank of Syria": 700000, "Bemo Saudi Fransi Bank": 300000}},
        "business": {"name": "🏢 Business", "items": {"Damascus Trade Hub": 200000}},
        "network": {"name": "📡 Network", "items": {"Syriatel": 6500000, "MTN Syria": 5200000}}
    }},
    "TW": {"flag": "🇹🇼", "name": "Taiwan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"MaiCoin": 1100000, "BitoPro": 950000, "Binance TW": 1400000}},
        "bank": {"name": "🏦 Banks", "items": {"CTBC Bank": 4800000, "Cathay United Bank": 4100000, "E.Sun Commercial Bank": 3500000}},
        "business": {"name": "🏢 Business", "items": {"TSMC Partner Network": 3900000, "Foxconn Enterprise Hub": 2800000}},
        "network": {"name": "📡 Network", "items": {"Chunghwa": 4100000, "Taiwan Mobile": 3200000, "FarEasTone": 2800000, "TSTAR": 1100000}}
    }},
    "TJ": {"flag": "🇹🇯", "name": "Tajikistan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TJ": 90000}},
        "bank": {"name": "🏦 Banks", "items": {"Orip Bank": 300000, "Spitamen Bank": 250000}},
        "business": {"name": "🏢 Business", "items": {"Dushanbe Trade Hub": 100000}},
        "network": {"name": "📡 Network", "items": {"Tcell": 2100000, "Babilon-M": 1400000, "Beeline TJ": 900000}}
    }},
    "TZ": {"flag": "🇹🇿", "name": "Tanzania", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TZ": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"CRDB Bank": 2100000, "NMB Bank Tanzania": 2400000, "Exim Bank TZ": 800000}},
        "business": {"name": "🏢 Business", "items": {"Dar es Salaam Tech Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Vodacom TZ": 8500000, "Airtel TZ": 5200000, "Tigo TZ": 4800000, "Halotel": 3100000}}
    }},
    "TH": {"flag": "🇹🇭", "name": "Thailand", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Bitkub": 3200000, "Binance TH": 2800000, "Zipmex TH Legacy": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Kasikornbank": 9100000, "Siam Commercial Bank (SCB)": 9500000, "Bangkok Bank": 8200000, "Krung Thai Bank": 7100000}},
        "business": {"name": "🏢 Business", "items": {"Bangkok Fintech Hub": 1900000}},
        "network": {"name": "📡 Network", "items": {"AIS Thailand": 26000000, "TrueMove H": 21000000, "DTAC": 14500000}}
    }},
    "TL": {"flag": "🇹🇱", "name": "Timor-Leste", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TL": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Belgium TL": 40000, "BNCTL": 60000}},
        "business": {"name": "🏢 Business", "items": {"Dili Port Trade": 20000}},
        "network": {"name": "📡 Network", "items": {"Telemor": 350000, "Telkomcel": 250000, "Timor Telecom": 180000}}
    }},
    "TG": {"flag": "🇹🇬", "name": "Togo", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TG": 70000}},
        "bank": {"name": "🏦 Banks", "items": {"Ecobank Transnational": 1100000, "Orabank Togo": 300000}},
        "business": {"name": "🏢 Business", "items": {"Lome Port Trade Hub": 250000}},
        "network": {"name": "📡 Network", "items": {"Togocom": 2400000, "Moov Africa Togo": 1800000}}
    }},
    "TO": {"flag": "🇹🇴", "name": "Tonga", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TO": 5000}},
        "bank": {"name": "🏦 Banks", "items": {"MBF Bank Tonga": 20000}},
        "business": {"name": "🏢 Business", "items": {"Nuku'alofa Trade": 10000}},
        "network": {"name": "📡 Network", "items": {"Digicel Tonga": 50000, "Tonga Communications Corp": 40000}}
    }},
    "TT": {"flag": "🇹🇹", "name": "Trinidad and Tobago", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TT": 120000}},
        "bank": {"name": "🏦 Banks", "items": {"Republic Bank": 650000, "Scotiabank Trinidad": 550000, "First Citizens Bank": 500000}},
        "business": {"name": "🏢 Business", "items": {"Port of Spain Energy Hub": 200000}},
        "network": {"name": "📡 Network", "items": {"Digicel TT": 850000, "TSTT (Blink/bmobile)": 750000}}
    }},
    "TN": {"flag": "🇹🇳", "name": "Tunisia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TN": 350000}},
        "bank": {"name": "🏦 Banks", "items": {"Banque Internationale Arabe de Tunisie": 1200000, "Attijari Bank TN": 900000}},
        "business": {"name": "🏢 Business", "items": {"Tunis Digital City Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Tunisie Télécom": 4500000, "Ooredoo Tunisia": 5100000, "Orange Tunisie": 3800000}}
    }},
    "TR": {"flag": "🇹🇷", "name": "Turkey", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"BtcTurk": 3800000, "Paribu": 3100000, "Binance TR": 5900000}},
        "bank": {"name": "🏦 Banks", "items": {"Garanti BBVA": 9100000, "İş Bankası": 9800000, "Akbank": 8500000, "Yapı Kredi": 8200000}},
        "business": {"name": "🏢 Business", "items": {"Istanbul Fintech Hub": 2400000}},
        "network": {"name": "📡 Network", "items": {"Turkcell": 35000000, "Vodafone TR": 24000000, "Türk Telekom": 18500000}}
    }},
    "TM": {"flag": "🇹🇲", "name": "Turkmenistan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TM": 40000}},
        "bank": {"name": "🏦 Banks", "items": {"State Commercial Bank TM": 200000}},
        "business": {"name": "🏢 Business", "items": {"Ashgabat State Trade": 80000}},
        "network": {"name": "📡 Network", "items": {"Altyn Asyr": 3500000}}
    }},
    "TV": {"flag": "🇹🇻", "name": "Tuvalu", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance TV": 2000}},
        "bank": {"name": "🏦 Banks", "items": {"National Bank of Tuvalu": 10000}},
        "business": {"name": "🏢 Business", "items": {"Funafuti Trade": 5000}},
        "network": {"name": "📡 Network", "items": {"Tuvalu Telecom": 10000}}
    }},
    "UG": {"flag": "🇺🇬", "name": "Uganda", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance UG": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"Stanbic Bank Uganda": 1800000, "Centenary Bank": 1500000, "Absa Bank Uganda": 750000}},
        "business": {"name": "🏢 Business", "items": {"Kampala Tech Hub": 450000}},
        "network": {"name": "📡 Network", "items": {"MTN Uganda": 11500000, "Airtel Uganda": 9800000}}
    }},
    "UA": {"flag": "🇺🇦", "name": "Ukraine", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Kuna Exchange": 900000, "Binance UA": 3400000}},
        "bank": {"name": "🏦 Banks", "items": {"PrivatBank": 14500000, "Monobank": 8900000, "Oschadbank": 5100000}},
        "business": {"name": "🏢 Business", "items": {"Kyiv IT Cluster Hub": 1800000}},
        "network": {"name": "📡 Network", "items": {"Kyivstar": 14200000, "Vodafone UA": 11500000, "lifecell": 7800000}}
    }},
    "AE": {"flag": "🇦🇪", "name": "UAE", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ADGM Hub": 3100000, "Kraken UAE": 1200000, "Bybit Dubai Hub": 2400000}},
        "bank": {"name": "🏦 Banks", "items": {"First Abu Dhabi Bank (FAB)": 3500000, "Emirates NBD": 4900000, "ADCB": 2800000, "Dubai Islamic Bank": 2100000}},
        "business": {"name": "🏢 Business", "items": {"Dubai Internet City Hub": 4500000, "DIFC Financial Hub": 3800000}},
        "network": {"name": "📡 Network", "items": {"Etisalat (e&)": 8500000, "du": 6200000}}
    }},
    "GB": {"flag": "🇬🇧", "name": "United Kingdom", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance UK": 1800000, "Coinbase UK": 1500000, "Kraken UK": 1100000, "Revolut Crypto": 2100000}},
        "bank": {"name": "🏦 Banks", "items": {"HSBC UK": 3500000, "Barclays": 3100000, "Lloyds Bank": 2800000, "NatWest": 2400000, "Monzo": 1900000}},
        "business": {"name": "🏢 Business", "items": {"Wise UK": 1900000, "Revolut Business": 2200000, "Checkout.com": 950000}},
        "network": {"name": "📡 Network", "items": {"EE": 3544000, "O2": 1831000, "Sky": 553000, "Three": 4515000, "Vodafone": 530000}}
    }},
    "US": {"flag": "🇺🇸", "name": "United States", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Coinbase US": 3500000, "Binance.US": 2200000, "Kraken US": 1900000, "Gemini": 1200000}},
        "bank": {"name": "🏦 Banks", "items": {"JPMorgan Chase": 4200000, "Bank of America": 3800000, "Citibank": 2900000, "Wells Fargo": 3100000, "Capital One": 2500000}},
        "business": {"name": "🏢 Business", "items": {"Stripe US": 3200000, "PayPal US": 5100000, "Square": 2800000, "Adyen US": 1100000}},
        "network": {"name": "📡 Network", "items": {"AT&T": 12800000, "Verizon": 11400000, "T-Mobile": 9700000, "Boost Mobile": 2100000, "Cricket": 1900000}}
    }},
    "UY": {"flag": "🇺🇾", "name": "Uruguay", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance UY": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Banco República (BROU)": 1100000, "Itau Uruguay": 700000}},
        "business": {"name": "🏢 Business", "items": {"Montevideo Tech Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"Antel": 1900000, "Movistar UY": 1100000, "Claro UY": 850000}}
    }},
    "UZ": {"flag": "🇺🇿", "name": "Uzbekistan", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Uzinfocom Crypto Hub": 300000, "Binance UZ": 600000}},
        "bank": {"name": "🏦 Banks", "items": {"NBU Uzbekistan": 1800000, "Kapitalbank UZ": 1200000, "Ipoteka Bank": 950000}},
        "business": {"name": "🏢 Business", "items": {"Tashkent IT Park": 400000}},
        "network": {"name": "📡 Network", "items": {"Ucell": 5200000, "Beeline UZ": 4100000, "Uzmobile": 3800000, "Humans": 1500000}}
    }},
    "VU": {"flag": "🇻🇺", "name": "Vanuatu", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance VU": 10000}},
        "bank": {"name": "🏦 Banks", "items": {"Vanuatu National Bank": 50000}},
        "business": {"name": "🏢 Business", "items": {"Port Vila Offshore Hub": 40000}},
        "network": {"name": "📡 Network", "items": {"Digicel Vanuatu": 60000, "Telecom Vanuatu": 40000}}
    }},
    "VA": {"flag": "🇻🇦", "name": "Vatican City", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Vatican Bank Hub": 1000}},
        "bank": {"name": "🏦 Banks", "items": {"Institute for the Works of Religion (IOR)": 5000}},
        "business": {"name": "🏢 Business", "items": {"Holy See Administration": 2000}},
        "network": {"name": "📡 Network", "items": {"Vatican Telephone Service": 3000}}
    }},
    "VE": {"flag": "🇻🇪", "name": "Venezuela", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance VE P2P Hub": 8500000, "Petro Hub Legacy": 1100000}},
        "bank": {"name": "🏦 Banks", "items": {"Banesco": 5200000, "Banco de Venezuela": 6100000, "BBVA Provincial": 3100000}},
        "business": {"name": "🏢 Business", "items": {"Caracas Trade Hub": 900000}},
        "network": {"name": "📡 Network", "items": {"Movistar VE": 8500000, "Digitel": 6200000, "Movilnet": 4100000}}
    }},
    "VN": {"flag": "🇻🇳", "name": "Vietnam", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance VN P2P": 9100000, "Remitano Hub": 3200000}},
        "bank": {"name": "🏦 Banks", "items": {"Vietcombank": 12500000, "Techcombank": 9800000, "BIDV": 11100000, "VPBank": 8500000}},
        "business": {"name": "🏢 Business", "items": {"Hanoi Tech Hub": 3100000, "Ho Chi Minh Fintech": 4500000}},
        "network": {"name": "📡 Network", "items": {"Viettel": 42000000, "Vinaphone": 24000000, "MobiFone": 18500000}}
    }},
    "YE": {"flag": "🇾🇪", "name": "Yemen", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance YE": 150000}},
        "bank": {"name": "🏦 Banks", "items": {"Yemen Kuwait Bank": 400000, "International Bank of Yemen": 350000}},
        "business": {"name": "🏢 Business", "items": {"Sana'a Trade Hub": 120000}},
        "network": {"name": "📡 Network", "items": {"MTN Yemen": 3100000, "Sabafon": 2400000, "Yemen Mobile": 4500000}}
    }},
    "ZM": {"flag": "🇿🇲", "name": "Zambia", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ZM": 250000}},
        "bank": {"name": "🏦 Banks", "items": {"Zanaco": 1400000, "Stanbic Bank Zambia": 850000, "FNB Zambia": 900000}},
        "business": {"name": "🏢 Business", "items": {"Lusaka Tech Hub": 300000}},
        "network": {"name": "📡 Network", "items": {"MTN Zambia": 6100000, "Airtel Zambia": 5800000, "Zamtel": 1800000}}
    }},
    "ZW": {"flag": "🇿🇼", "name": "Zimbabwe", "subcats": {
        "crypto": {"name": "🪙 Crypto", "items": {"Binance ZW P2P": 1100000, "Golix Hub Legacy": 300000}},
        "bank": {"name": "🏦 Banks", "items": {"CBZ Bank Zimbabwe": 1500000, "Stanbic Bank ZW": 700000, "CABS": 950000}},
        "business": {"name": "🏢 Business", "items": {"Harare Mining Hub": 400000}},
        "network": {"name": "📡 Network", "items": {"Econet Wireless": 8500000, "NetOne": 2400000, "Telecel ZW": 600000}}
    }}
}

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
        logger.info("No saved data file yet — starting fresh.")
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
            LEADS.clear()
            LEADS.update(data["LEADS"])

        logger.info("✅ Loaded saved data from disk.")
    except Exception as e:
        logger.error(f"load_data failed: {e}")

async def log(app, text: str):
    if not LOG_CHANNEL_ID: return
    try: await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception as e: logger.warning(f"Log failed: {e}")

def is_admin(update) -> bool:
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

async def check_channel_membership(bot, user_id):
    if not JOIN_CHANNEL: return True, "ok"
    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"): return True, "ok"
        return False, "not_joined"
    except Exception as e:
        logger.warning(f"Membership check error: {e}")
        return False, "error"

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

# ── Keyboards & Texts ─────────────────────────────────────────────────────────

SCAN_CATS = {"all": "All •", "socials": "Socials", "crypto": "Crypto", "shopping": "Shop...", "carrier": "Carrier"}

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

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

def leads_pricing_text(cc=None):
    pricing = get_category_pricing(cc) if cc else LEADS_PRICING
    lines = ["📊 *Pricing*"]
    for qty, price in pricing:
        k = qty // 1000 if qty >= 1000 else qty
        unit = "k" if qty >= 1000 else ""
        lines.append(f"{k}{unit} — £{price:g}")
    return "\n".join(lines)

def country_keyboard():
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        row = [InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"lc|{cc}") for cc, d in countries[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def subcat_keyboard(cc):
    data = LEADS[cc]
    rows = []
    for skey, sdata in data.get("subcats", {}).items():
        rows.append([InlineKeyboardButton(sdata["name"], callback_data=f"lsub|{cc}|{skey}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="leads")])
    return InlineKeyboardMarkup(rows)

def entity_keyboard(cc, subcat_key):
    items = LEADS[cc]["subcats"][subcat_key]["items"]
    rows = []
    items_list = list(items.items())
    for i in range(0, len(items_list), 2):
        row = [InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"lk|{cc}|{subcat_key}|{name}") for name, stock in items_list[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, subcat_key, entity_name):
    rows = []
    tiers = get_category_pricing(cc)
    for i in range(0, len(tiers), 2):
        row = []
        for qty, price in tiers[i:i+2]:
            k = qty // 1000 if qty >= 1000 else qty
            unit = "k" if qty >= 1000 else ""
            row.append(InlineKeyboardButton(f"{k}{unit} — £{price:g}", callback_data=f"lq|{cc}|{subcat_key}|{entity_name}|{qty}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lsub|{cc}|{subcat_key}")])
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

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads",            callback_data="leads"),
         InlineKeyboardButton("🛍️ Store",            callback_data="store")],
        [InlineKeyboardButton("💰 Wallet",           callback_data="wallet"),
         InlineKeyboardButton("🔍 Scanner",          callback_data="scanner")],
        [InlineKeyboardButton("🎯 Targeted Source",  callback_data="tsource")],
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

# ── User Commands ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)

    if is_new:
        await log(context.application,
            f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")

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
    await update.message.reply_text(f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*\n\n_Top up via Wallet._", parse_mode="Markdown")

async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")

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
    "`/resetprice <Category_Code>`\n\n"
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

def admin_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Menu", callback_data="admin_menu")]])

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
        await update.message.reply_text("Usage: /setprice <Category_Code> <Quantity> <Price>\nExample: `/setprice US 1000 15`", parse_mode="Markdown")
        return

    if "pricing" not in LEADS[cc]:
        LEADS[cc]["pricing"] = dict(LEADS_PRICING)

    LEADS[cc]["pricing"][str(qty)] = price
    save_data()

    await update.message.reply_text(
        f"✅ Updated pricing for *{LEADS[cc]['flag']} {LEADS[cc]['name']}*:\n"
        f"• *{qty:,} items* → *£{price:g}*",
        parse_mode="Markdown"
    )

async def cmd_resetprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        cc = context.args[0].upper()
        assert cc in LEADS
    except (IndexError, AssertionError):
        await update.message.reply_text("Usage: /resetprice <Category_Code>", parse_mode="Markdown")
        return

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
        vid = context.args[0]; bkey = context.args[1]
        price = int(context.args[2]); label = " ".join(context.args[3:])
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
        vid = context.args[0]; bkey = context.args[1]
        bin_num = context.args[2]; qty = int(context.args[3])
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

# ── Security & Order Block ────────────────────────────────────────────────────

def get_blocked_message(balance, item_price, back_cb):
    if balance == 0:
        text = f"❌ *Insufficient Balance!*\n\nThis item costs £{item_price:.2f} but your balance is £{balance:.2f}.\n\nPlease top up."
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top Up Wallet", callback_data="wallet")]])

    if balance < MIN_DEPOSIT_REQUIRED:
        text = (
            "🛑 *Order Blocked*\n⚠️ *Transaction Incomplete*\n"
            "Your account balance does not meet the minimum deposit required for new users.\n"
            f" • 💰 *Current Balance:* £{balance:.2f}\n"
            f" • 📋 *Required Minimum:* £{MIN_DEPOSIT_REQUIRED:.2f}\n"
            "Please fund your account to proceed."
        )
        return text, InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Top Up", callback_data="wallet")],
            [InlineKeyboardButton("⬅️ Back", callback_data=back_cb)],
        ])

    if balance < item_price:
        text = f"❌ *Insufficient Balance!*\n\nThis item costs £{item_price:.2f} but your balance is £{balance:.2f}."
        return text, InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]])

    return None, None

# ── Button Handler ────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data

    if data == "agree_rules":
        is_member, reason = await check_channel_membership(context.bot, uid)
        if not is_member:
            await query.answer("⛔️ You haven't joined yet! Tap 'Join Channel' first.", show_alert=True)
            return
        agreed_users.add(uid)
        channel_verified.add(uid)
        save_data()
        await query.answer()
        await context.bot.send_message(chat_id=uid, text=main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    await query.answer()

    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty"):
        context.user_data.pop(_k, None)

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "admin_menu":
        if not is_admin(update): return
        await query.edit_message_text(ADMIN_HELP_TEXT, parse_mode="Markdown")
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

    # ── Leads Categories Navigation ──────────────────────────────────────────
    if data == "leads":
        pricing_overview = leads_pricing_text()
        await query.edit_message_text(f"🌍 *Leads Category Menu*\n\n{pricing_overview}\n\n_Select a country below:_", reply_markup=country_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("lc|"):
        cc = data.split("|")[1]
        if cc not in LEADS: await query.answer("Not found."); return
        d = LEADS[cc]
        category_pricing = leads_pricing_text(cc)
        await query.edit_message_text(f"Category: *{d['flag']} {d['name']}*\n\n{category_pricing}\n\nSelect a category below:", reply_markup=subcat_keyboard(cc), parse_mode="Markdown")
        return

    if data.startswith("lsub|"):
        _, cc, subcat_key = data.split("|", 3)
        if cc not in LEADS or subcat_key not in LEADS[cc].get("subcats", {}): await query.answer("Not found."); return
        d = LEADS[cc]
        subcat_name = d["subcats"][subcat_key]["name"]
        await query.edit_message_text(f"{d['flag']} *{d['name']}* ➔ {subcat_name}\n\nSelect available item:", reply_markup=entity_keyboard(cc, subcat_key), parse_mode="Markdown")
        return

    if data.startswith("lk|"):
        _, cc, subcat_key, entity_name = data.split("|", 4)
        if cc not in LEADS: await query.answer("Not found."); return
        stock = LEADS[cc]["subcats"][subcat_key]["items"].get(entity_name, 0)
        d = LEADS[cc]
        await query.edit_message_text(f"Category: *{d['flag']} {d['name']}*\nEntity: *{entity_name}*\nAvailable: *{stock:,}*\n\nSelect quantity:", reply_markup=qty_keyboard(cc, subcat_key, entity_name), parse_mode="Markdown")
        return

    if data.startswith("lq|"):
        _, cc, subcat_key, entity_name, qty_str = data.split("|", 5)
        qty = int(qty_str)
        price = get_category_pricing_dict(cc).get(qty, 0)
        d = LEADS[cc]; stock = LEADS[cc]["subcats"][subcat_key]["items"].get(entity_name, 0); balance = user_balances.get(uid, 0)

        if stock < qty: await query.answer(f"Only {stock:,} available.", show_alert=True); return

        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\nCategory: *{d['flag']} {d['name']}*\nEntity: *{entity_name}*\nQuantity: *{qty:,}*\n💷 *Price: £{price:g}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{subcat_key}|{entity_name}|{qty}"),
                InlineKeyboardButton("❌ Cancel",  callback_data=f"lk|{cc}|{subcat_key}|{entity_name}")
            ]]),
            parse_mode="Markdown"
        )
        return

    if data.startswith("lb|"):
        _, cc, subcat_key, entity_name, qty_str = data.split("|", 5)
        qty = int(qty_str)
        price = get_category_pricing_dict(cc).get(qty, 0)
        balance = user_balances.get(uid, 0); d = LEADS[cc]

        blocked_text, blocked_kbd = get_blocked_message(balance, price, f"lk|{cc}|{subcat_key}|{entity_name}")
        if blocked_text: await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown"); return

        user_balances[uid] = round(balance - price, 2)
        LEADS[cc]["subcats"][subcat_key]["items"][entity_name] = max(0, LEADS[cc]["subcats"][subcat_key]["items"].get(entity_name, 0) - qty)
        save_data()

        await query.edit_message_text(f"✅ *Purchase Successful!*\n\n{d['flag']} *{d['name']}* — {entity_name}\nQty: *{qty:,}*\nPaid: *£{price:g}*\n\nContact @{SUPER_ADMIN} to receive.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]), parse_mode="Markdown")
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

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cc = context.args[0].upper(); subcat = context.args[1].lower(); item = context.args[2]; stock = int(context.args[3])
        assert cc in LEADS and subcat in LEADS[cc]["subcats"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /updatelead <CC> <subcat: crypto|bank|business|network> <ItemName> <stock>\nExample: `/updatelead US network AT&T 15000000`", parse_mode="Markdown"); return
    
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
