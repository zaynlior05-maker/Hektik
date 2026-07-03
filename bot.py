import os
import json
import logging
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# NEW: Minimum balance required to purchase items (editable via Railway vars)
MIN_PURCHASE_BALANCE = int(os.environ.get("MIN_PURCHASE_BALANCE", 150))

# Private channel setup — two variables:
#   JOIN_CHANNEL     = your channel's numeric ID, e.g. -1001234567890
#                      (forward any message from your channel to @userinfobot to get it)
#   JOIN_CHANNEL_URL = your private invite link, e.g. https://t.me/+aBcDeFgHiJk
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

# ── Store Data  (NOTE: base keys must NOT contain the | character) ─────────────
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

# ── Leads Country & Carrier Data ─────────────────────────────────────────────
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
    "ET": {"flag":"🇪🇪","name":"Estonia",        "carriers":{"Telia":430_000,"Elisa":380_000,"Tele2":290_000}},
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

DEFAULT_LEADS = _copy.deepcopy(LEADS)
DEFAULT_STORE = None

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
                for carrier, stock in d["carriers"].items():
                    if carrier not in LEADS[cc]["carriers"]:
                        LEADS[cc]["carriers"][carrier] = stock
    except Exception as e:
        logger.error(f"load_data failed: {e}")

async def log(app, text: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception as e:
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
    except Exception as e:
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
                return {"BTC": d["bitcoin"]["gbp"], "SOL": d["solana"]["gbp"], "LTC": d["litecoin"]["gbp"]}
    except Exception:
        return None

# ── Feature Helper ─────────────────────────────────────────────────────────────

def check_min_balance(balance, back_callback):
    """
    Checks if the user's current balance meets the MIN_PURCHASE_BALANCE requirement.
    Returns the block message text and keyboard if blocked, or None if permitted.
    """
    if balance < MIN_PURCHASE_BALANCE:
        text = (
            f"### 🛑 Order Blocked\n"
            f"⚠️ *Transaction Incomplete*\n"
            f"Your account balance does not meet the minimum deposit required for new users.\n"
            f" • 💰 *Current Balance:* £{balance:.2f}\n"
            f" • 📋 *Required Minimum:* £{MIN_PURCHASE_BALANCE:.2f}\n"
            f"💳 *Please fund your account to proceed.*"
        )
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Fund Account", callback_data="wallet")],
            [InlineKeyboardButton("⬅️ Back", callback_data=back_callback)]
        ])
        return text, kbd
    return None, None

# ── Keyboards ─────────────────────────────────────────────────────────────────

SCAN_CATS = {
    "all":      "All •",
    "socials":  "Socials",
    "crypto":   "Crypto",
    "shopping": "Shop...",
    "carrier":  "Carrier",
}

def scanner_items_for_cat(cat):
    if cat == "all":
        return list(enumerate(SCANNER_ITEMS))
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

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

def leads_pricing_text():
    lines = ["📊 *Pricing*"]
    for qty, price in LEADS_PRICING:
        k = qty // 1000
        lines.append(f"{k}k — £{price}")
    return "\n".join(lines)

def country_keyboard():
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        row = [InlineKeyboardButton(f"{d['flag']} {d['name']}", callback_data=f"lc|{cc}") for cc, d in countries[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def carrier_keyboard(cc):
    data = LEADS[cc]
    rows = []
    carriers = list(data["carriers"].items())
    for i in range(0, len(carriers), 2):
        row = [InlineKeyboardButton(f"{name} ({stock:,})", callback_data=f"lk|{cc}|{name}") for name, stock in carriers[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="leads")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, carrier):
    rows = []
    tiers = LEADS_PRICING
    for i in range(0, len(tiers), 2):
        row = [InlineKeyboardButton(f"{qty//1000}k — £{price}", callback_data=f"lq|{cc}|{carrier}|{qty}") for qty, price in tiers[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
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

# ── Commands ──────────────────────────────────────────────────────────────────

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
    await update.message.reply_text(f"💰 *Your Balance*\n\n🪪 ID: `{uid}`\n💷 Balance: *£{bal:.2f}*\n\n_Top up via the Wallet section._", parse_mode="Markdown")

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
        f"👤 Admin: @{SUPER_ADMIN}\n"
        f"🔹 Support 24/7: @{SUPPORT_USER}\n\n"
        f"_Tap a button below to open a chat._",
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
        "3️⃣ Pick an item and confirm — your balance is charged instantly\n"
        "4️⃣ After buying, you'll be told to contact the admin to receive your files\n\n"
        "*Useful commands:*\n"
        "/start — main menu\n"
        "/wallet — top up\n"
        "/balance — check your balance\n"
        "/targeted — targeted source leads\n"
        "/contact — reach the admin/support\n\n"
        f"Need help? Message @{SUPER_ADMIN}",
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

async def cmd_adminlogout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logged_in_admins.discard(update.effective_user.id)
    await update.message.reply_text("🔒 Logged out of admin access.")

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(
        "🛠 *Admin Commands*\n\n"
        "*Login*\n`/adminlogin <password>`\n`/adminlogout`\n\n"
        "*Balance*\n`/addbalance <user_id> <amount>`\n`/removebalance <user_id> <amount>`\n`/setbalance <user_id> <amount>`\n`/checkbalance <user_id>`\n\n"
        "*Stock*\n`/setstock leads <number>`\n\n"
        "*Vendors*\n`/addvendor <id> <label>`\n`/removevendor <id>`\n\n"
        "*Bases*\n`/addbase <vendor_id> <base_key> <price> <label>`\n`/removebase <vendor_id> <base_key>`\n\n"
        "*BINs*\n`/addbin <vendor_id> <base_key> <bin> <qty>`\n`/removebin <vendor_id> <base_key> <bin>`\n`/listbins <vendor_id> <base_key>`\n`/clearbase <vendor_id> <base_key>`\n\n"
        "*Users*\n`/listusers`\n`/broadcast <message>`",
        parse_mode="Markdown")

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
    except: return
    live_stock[key] = val; save_data()
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except: return
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
    try: vid = context.args[0]; bkey = context.args[1]; price = int(context.args[2]); label = " ".join(context.args[3:])
    except: return
    existing_bins = STORE[vid]["bases"][bkey].get("bins", {}) if bkey in STORE[vid]["bases"] else {}
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": existing_bins}
    save_data(); await update.message.reply_text(f"✅ Base added/updated", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; del STORE[vid]["bases"][bkey]; save_data()
    except: return
    await update.message.reply_text(f"✅ Removed base `{bkey}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid, bkey, bin_num, qty = context.args[0], context.args[1], context.args[2], int(context.args[3])
    except: return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty; save_data()
    await update.message.reply_text(f"✅ BIN *{bin_num}* = *{qty}*", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid, bkey, bin_num = context.args[0], context.args[1], context.args[2]
    except: return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None); save_data()
    await update.message.reply_text(f"✅ Removed BIN *{bin_num}*", parse_mode="Markdown")

async def cmd_listbins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; bins = STORE[vid]["bases"][bkey]["bins"]
    except: return
    lines = [f"📦 *Total:* {sum(bins.values())}\n"] + [f"`{b}` — {q}" for b, q in sorted(bins.items())]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_clearbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: vid = context.args[0]; bkey = context.args[1]; STORE[vid]["bases"][bkey]["bins"].clear(); save_data()
    except: return
    await update.message.reply_text(f"✅ Cleared")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    lines = ["👥 *All Users*\n"] + [f"`{u}` — £{b:.2f}" for u, b in sorted(user_balances.items(), key=lambda x: -x[1])]
    await update.message.reply_text("\n".join(lines[:50]), parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try: cc, carrier, stock = context.args[0].upper(), context.args[1], int(context.args[2])
    except: return
    if stock <= 0: LEADS[cc]["carriers"].pop(carrier, None)
    else: LEADS[cc]["carriers"][carrier] = stock
    save_data(); await update.message.reply_text(f"✅ Updated")

async def cmd_bulkbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    lines = update.message.text.split("\n")
    try: vid, bkey = lines[0].split()[1], lines[0].split()[2]
    except: return
    for line in lines[1:]:
        parts = line.replace("x", " ").replace("X", " ").split()
        if len(parts) >= 2:
            try: STORE[vid]["bases"][bkey]["bins"][parts[0]] = int(parts[1])
            except: pass
    save_data(); await update.message.reply_text(f"✅ Bulk added")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    msg = " ".join(context.args)
    if not msg: return
    for uid in list(agreed_users):
        try: await context.application.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
        except: pass

# ── Callback Handler ──────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid   = query.from_user.id
    data  = query.data

    if data == "agree_rules":
        try: is_member, reason = await check_channel_membership(context.bot, uid)
        except: is_member, reason = False, "error"
        if reason == "error": await query.answer("⚠️ Bot admin required.", show_alert=True); return
        if not is_member: await query.answer("⛔️ You haven't joined yet!", show_alert=True); return
        agreed_users.add(uid); channel_verified.add(uid); save_data(); await query.answer()
        await context.bot.send_message(chat_id=uid, text=main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    await query.answer()
    for _k in ("awaiting_custom", "awaiting_bin_search", "awaiting_qty"): context.user_data.pop(_k, None)

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return

    if data == "wallet":
        await query.edit_message_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown"); return

    if data.startswith("amt|"):
        amount = data.split("|")[1]
        await query.edit_message_text(f"🔶 *£{amount} Top-Up*\n\nChoose your payment method:", reply_markup=coin_select_keyboard(amount), parse_mode="Markdown"); return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text("💰 *Custom Amount*\n\nType the £ amount (minimum £70):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]), parse_mode="Markdown"); return

    if data.startswith("pay|"):
        _, coin, amount = data.split("|"); amount = int(amount)
        address = WALLETS.get(coin, "Address not configured")
        await query.edit_message_text(f"Send the equivalent of *£{amount}* in {coin}\n\n🏦 Address:\n`{address}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]), parse_mode="Markdown"); return

    if data == "store":
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown"); return

    if data.startswith("vendor|"):
        vid = data.split("|")[1]
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n\nSelect a base:", reply_markup=base_select_keyboard(vid), parse_mode="Markdown"); return

    if data.startswith("base|"):
        _, vid, bkey = data.split("|", 2)
        kbd, tp = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\nSelect BIN group:", reply_markup=kbd, parse_mode="Markdown"); return

    if data.startswith("bpage|"):
        _, vid, bkey, page = data.split("|", 3); page = int(page)
        kbd, tp = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\nSelect BIN group:", reply_markup=kbd, parse_mode="Markdown"); return

    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid; context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(f"🔍 *BIN Search*\n\nType the BIN number:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown"); return

    if data.startswith("buybin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        qty = STORE[vid]["bases"][bkey]["bins"].get(bin_num, 0)
        if qty == 0: await query.answer("Out of stock."); return
        context.user_data["buy_bin"] = {"vid": vid, "bkey": bkey, "bin_num": bin_num, "price": STORE[vid]["bases"][bkey]["price_per_card"], "available": qty}
        context.user_data["awaiting_qty"] = True
        await query.edit_message_text(f"Enter quantity (1-{qty}):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"bpage|{vid}|{bkey}|{page}")]]), parse_mode="Markdown"); return

    if data.startswith("cfmqty|"):
        _, vid, bkey, bin_num, qty_s = data.split("|", 4)
        buy_qty, base = int(qty_s), STORE[vid]["bases"][bkey]
        stock, price = base["bins"].get(bin_num, 0), base["price_per_card"]
        total, balance = round(price * buy_qty, 2), user_balances.get(uid, 0)

        if buy_qty > stock: await query.answer(f"Only {stock} available now.", show_alert=True); return
        
        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, f"vendor|{vid}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < total:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{total:.2f}\nYour balance: £{balance:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - total, 2)
        base["bins"][bin_num] = stock - buy_qty
        if base["bins"][bin_num] <= 0: del base["bins"][bin_num]
        save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n💳 BIN: *{bin_num}*\n🗂 Qty: *{buy_qty} fullz*\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown"); return

    if data == "deads":
        await query.edit_message_text("💀 *Deads — Unspoofed Files*\nSelect a file below:", reply_markup=deads_keyboard(), parse_mode="Markdown"); return

    if data.startswith("dbuy|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"dcfm|{key}"), InlineKeyboardButton("❌ Cancel", callback_data="deads")]]), parse_mode="Markdown"); return

    if data.startswith("dcfm|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: return
        label, price, _ = item; balance = user_balances.get(uid, 0)

        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, "deads")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < price:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{price:,}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data="deads")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n📁 *{label}*\nContact @{SUPER_ADMIN} for your files.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]), parse_mode="Markdown"); return

    if data == "leads":
        await query.edit_message_text(f"🌍 *Leads*\n\n{leads_pricing_text()}", reply_markup=country_keyboard(), parse_mode="Markdown"); return

    if data.startswith("lc|"):
        cc = data.split("|")[1]
        await query.edit_message_text(f"Available carriers:", reply_markup=carrier_keyboard(cc), parse_mode="Markdown"); return

    if data.startswith("lk|"):
        _, cc, carrier = data.split("|", 2)
        await query.edit_message_text(f"Select quantity:", reply_markup=qty_keyboard(cc, carrier), parse_mode="Markdown"); return

    if data.startswith("lq|"):
        _, cc, carrier, qty_str = data.split("|", 3)
        qty, price = int(qty_str), dict(LEADS_PRICING).get(int(qty_str), 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🗂 Quantity: *{qty:,}*\n💷 *Price: £{price}*\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{carrier}|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"lk|{cc}|{carrier}")]]), parse_mode="Markdown"); return

    if data.startswith("lb|"):
        _, cc, carrier, qty_str = data.split("|", 3)
        qty, price = int(qty_str), dict(LEADS_PRICING).get(int(qty_str), 0)
        balance = user_balances.get(uid, 0)

        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, f"lk|{cc}|{carrier}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < price:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{price}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=f"lk|{cc}|{carrier}")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - price, 2)
        if cc in LEADS and carrier in LEADS[cc]["carriers"]: LEADS[cc]["carriers"][carrier] = max(0, LEADS[cc]["carriers"][carrier] - qty)
        save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n🗂 *{qty:,} numbers*\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]), parse_mode="Markdown"); return

    if data == "scanner":
        await query.edit_message_text("🔍 *Scanner*", reply_markup=scanner_keyboard("all", 0), parse_mode="Markdown"); return

    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        await query.edit_message_text("🔍 *Scanner*", reply_markup=scanner_keyboard(cat, pg), parse_mode="Markdown"); return

    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        label, category, price = SCANNER_ITEMS[idx]
        await query.edit_message_text(f"🔍 *{label}*\n\nSelect quantity:", reply_markup=scanner_qty_keyboard(idx, category), parse_mode="Markdown"); return

    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|"); idx, qty_k = int(idx_s), int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n🔍 *{label}*\n🗂 Quantity: *{qty_k}k*\n💷 *Total: £{total_gbp:.2f}*\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"), InlineKeyboardButton("❌ Cancel", callback_data=f"sni|{idx}")]]), parse_mode="Markdown"); return

    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|"); idx, qty_k = int(idx_s), int(qty_s)
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp, balance = round(qty_k * price, 2), user_balances.get(uid, 0)

        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, f"sni|{idx}")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < total_gbp:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{total_gbp:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data=f"sni|{idx}")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - total_gbp, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\n🔍 *{label}*\nContact @{SUPER_ADMIN} to receive your data.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]), parse_mode="Markdown"); return

    if data == "tsource":
        await query.edit_message_text("🎯 *Targeted Source*\nSelect a category below:", reply_markup=tsource_main_keyboard(), parse_mode="Markdown"); return

    if data == "ts_aged":
        await query.edit_message_text("‼️ *Aged Leads / Bank-Targeted Leads*", reply_markup=ts_qty_keyboard(AGED_LEADS_PRICING, "tsaged"), parse_mode="Markdown"); return

    if data == "ts_crypto":
        await query.edit_message_text("🪙 *Crypto Leads*", reply_markup=ts_qty_keyboard(CRYPTO_LEADS_PRICING, "tscrypto"), parse_mode="Markdown"); return

    if data == "ts_services":
        await query.edit_message_text("🛠 *Additional Services*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown"); return

    if data.startswith("tsaged|"):
        qty = int(data.split("|")[1])
        price = dict(AGED_LEADS_PRICING).get(qty, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n💷 *Total: £{price}*\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tsaged_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_aged")]]), parse_mode="Markdown"); return

    if data.startswith("tsaged_confirm|"):
        qty = int(data.split("|")[1])
        price, balance = dict(AGED_LEADS_PRICING).get(qty, 0), user_balances.get(uid, 0)

        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, "ts_aged")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < price:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{price}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data="ts_aged")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown"); return

    if data.startswith("tscrypto|"):
        qty = int(data.split("|")[1])
        price = dict(CRYPTO_LEADS_PRICING).get(qty, 0)
        await query.edit_message_text(f"🛒 *Purchase Confirmation*\n\n💷 *Total: £{price}*\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"tscrypto_confirm|{qty}"), InlineKeyboardButton("❌ Cancel", callback_data="ts_crypto")]]), parse_mode="Markdown"); return

    if data.startswith("tscrypto_confirm|"):
        qty = int(data.split("|")[1])
        price, balance = dict(CRYPTO_LEADS_PRICING).get(qty, 0), user_balances.get(uid, 0)

        # FEATURE: Check minimum activation balance
        blocked_text, blocked_kbd = check_min_balance(balance, "ts_crypto")
        if blocked_text:
            await query.edit_message_text(blocked_text, reply_markup=blocked_kbd, parse_mode="Markdown")
            return

        if balance < price:
            await query.edit_message_text(f"❌ *Insufficient Balance*\nRequired: £{price}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Wallet", callback_data="wallet"), InlineKeyboardButton("⬅️ Back", callback_data="ts_crypto")]]), parse_mode="Markdown"); return
        
        user_balances[uid] = round(balance - price, 2); save_data()
        await query.edit_message_text(f"✅ *Purchase Successful!*\nContact @{SUPER_ADMIN} to receive your leads.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="tsource")]]), parse_mode="Markdown"); return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_qty"):
        info = context.user_data.get("buy_bin", {})
        text = update.message.text.strip()
        try: buy_qty = int(text)
        except ValueError: await update.message.reply_text("Please enter a valid number."); return

        available = info.get("available", 0)
        if buy_qty < 1 or buy_qty > available: await update.message.reply_text(f"Please enter a number between 1 and {available}."); return

        context.user_data["awaiting_qty"] = False
        vid, bkey, bin_num, price = info["vid"], info["bkey"], info["bin_num"], info["price"]
        total = round(price * buy_qty, 2)
        balance = user_balances.get(update.effective_user.id, 0)

        await update.message.reply_text(
            f"🛒 *Purchase Confirmation*\n\n💳 BIN: *{bin_num}*\n🗂 Quantity: *{buy_qty} fullz*\n💰 Per fullz: *£{price:.2f}*\n💷 *Total: £{total:.2f}*\n\nYour balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"cfmqty|{vid}|{bkey}|{bin_num}|{buy_qty}"), InlineKeyboardButton("❌ Cancel", callback_data=f"vendor|{vid}")]]),
            parse_mode="Markdown")
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
            await update.message.reply_text(f"🔍 *Search results for {bin_num}:*", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ BIN *{bin_num}* not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]), parse_mode="Markdown")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    load_data()
    app = Application.builder().token(BOT_TOKEN).build()
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
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot started ✅")

if __name__ == "__main__":
    main()
