import os
import logging
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN")
SUPER_ADMIN    = os.environ.get("ADMIN_USERNAME", "HekTikz")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme123")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID")
MIN_TOPUP      = 70

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

live_stock    = {"leads": 63_629_085, "stock": 183}
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
# Format: (label, category, price_per_k_usd)
# Categories: all | socials | crypto | shopping | carrier
SCANNER_ITEMS = [
    # ── Crypto ───────────────────────────────────────────────────────────────
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
    # ── Socials ──────────────────────────────────────────────────────────────
    ("Facebook · Email",      "socials",  1.00),
    ("Instagram · Mobile",    "socials",  1.00),
    ("LinkedIn · Profile",    "socials",  15.00),
    ("Signal",                "socials",  1.00),
    ("Snapchat",              "socials",  2.00),
    ("iMessage · Filter",     "socials",  0.35),
    # ── Shopping ─────────────────────────────────────────────────────────────
    ("DHL",                   "shopping", 1.50),
    ("Shein",                 "shopping", 15.00),
    # ── Carrier ──────────────────────────────────────────────────────────────
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

SCANNER_PER_PAGE = 10   # items shown per page

# Scanner quantity tiers: (qty_k, label)
SCANNER_QTYS = [1, 5, 10, 25, 50, 100]   # in thousands


LEADS_PRICING = [
    (1_000,   15),  (2_000,  30),  (3_000,   45),  (4_000,  50),
    (5_000,   60),  (6_000,  65),  (7_000,   70),  (8_000,  80),
    (10_000, 100),  (15_000,125),  (20_000, 150),  (25_000,175),
    (30_000, 200),  (50_000,300),  (100_000,600),
]

# ── Leads Country & Carrier Data ─────────────────────────────────────────────
# Format: "CC": {"flag":"🏳️","name":"Country","carriers":{"Carrier":stock}}
# Admin: use /updatelead CC CarrierName stock  to change any value live
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
    "UK": {"flag":"🇬🇧","name":"United Kingdom", "carriers":{"EE":3_544_000,"MIX":221_000,"O2":1_831_000,"Sky":553_000,"Three":4_515_000,"Virgin":114_000,"Vodafone":530_000}},
}

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

# ── Channel Logger ────────────────────────────────────────────────────────────

async def log(app, text: str):
    if not LOG_CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=int(LOG_CHANNEL_ID), text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Log failed: {e}")

# ── Admin check ───────────────────────────────────────────────────────────────

def is_admin(update) -> bool:
    uid      = update.effective_user.id
    username = update.effective_user.username or ""
    return username == SUPER_ADMIN or uid in logged_in_admins

async def check_channel_membership(bot, user_id: int) -> tuple[bool, str]:
    """
    Always does a live API check — no caching so it's always accurate.
    Returns (is_member, reason): reason is 'ok', 'not_joined', or 'error'.
    """
    if not JOIN_CHANNEL:
        return True, "ok"          # no channel configured = open access

    try:
        member = await bot.get_chat_member(chat_id=JOIN_CHANNEL, user_id=user_id)
        status = member.status
        if status in ("member", "administrator", "creator", "restricted"):
            return True, "ok"
        else:
            return False, "not_joined"   # left or kicked
    except Exception as e:
        logger.warning(f"Membership check failed for {user_id}: {e}")
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

# ── Scanner keyboards ─────────────────────────────────────────────────────────

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
    """Category tabs + paginated item list."""
    items      = scanner_items_for_cat(cat)
    total_pages = max(1, (len(items) + SCANNER_PER_PAGE - 1) // SCANNER_PER_PAGE)
    page_items  = items[page * SCANNER_PER_PAGE : (page + 1) * SCANNER_PER_PAGE]

    rows = []

    # ── Category tab row ────────────────────────────────────────────────────
    tab_row = []
    for key, label in SCAN_CATS.items():
        display = f"› {label}" if key == cat else label
        tab_row.append(InlineKeyboardButton(display, callback_data=f"scan|{key}|0"))
    rows.append(tab_row)

    # ── Item buttons (1 per row, full width) ────────────────────────────────
    for idx, (label, category, price) in page_items:
        price_fmt = f"${price:.2f}" if price != int(price) else f"${int(price):.2f}"
        rows.append([InlineKeyboardButton(
            f"{label} — {price_fmt} / k",
            callback_data=f"sni|{idx}")])

    # ── Pagination row ───────────────────────────────────────────────────────
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
    """Quantity selector for a scanner item."""
    label, category, price = SCANNER_ITEMS[idx]
    rows = []
    for i in range(0, len(SCANNER_QTYS), 2):
        row = []
        for qty_k in SCANNER_QTYS[i:i+2]:
            total = qty_k * price
            row.append(InlineKeyboardButton(
                f"{qty_k}k — £{total:.2f}",
                callback_data=f"snq|{idx}|{qty_k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"scan|{cat}|{page}")])
    return InlineKeyboardMarkup(rows)

def user_tag(update):
    u = update.effective_user
    uname = f"@{u.username}" if u.username else f"ID:`{u.id}`"
    return f"{u.full_name or 'Unknown'} ({uname})"

# ── Leads keyboards ───────────────────────────────────────────────────────────

def leads_pricing_text():
    lines = ["📊 *Pricing*"]
    for qty, price in LEADS_PRICING:
        k = qty // 1000
        lines.append(f"{k}k — £{price}")
    return "\n".join(lines)

def country_keyboard():
    """Grid of all countries, 2 per row, alphabetical."""
    countries = sorted(LEADS.items(), key=lambda x: x[1]["name"])
    rows = []
    for i in range(0, len(countries), 2):
        row = [InlineKeyboardButton(
            f"{d['flag']} {d['name']}",
            callback_data=f"lc|{cc}")
            for cc, d in countries[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(rows)

def carrier_keyboard(cc):
    """Grid of carriers for a country, 2 per row."""
    data = LEADS[cc]
    rows = []
    carriers = list(data["carriers"].items())
    for i in range(0, len(carriers), 2):
        row = [InlineKeyboardButton(
            f"{name} ({stock:,})",
            callback_data=f"lk|{cc}|{name}")
            for name, stock in carriers[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="leads")])
    return InlineKeyboardMarkup(rows)

def qty_keyboard(cc, carrier):
    """Quantity/tier selection buttons, 2 per row."""
    rows = []
    tiers = LEADS_PRICING
    for i in range(0, len(tiers), 2):
        row = [InlineKeyboardButton(
            f"{qty//1000}k — £{price}",
            callback_data=f"lq|{cc}|{carrier}|{qty}")
            for qty, price in tiers[i:i+2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"lc|{cc}")])
    return InlineKeyboardMarkup(rows)

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Leads",   callback_data="leads"),
         InlineKeyboardButton("🛍️ Store",   callback_data="store")],
        [InlineKeyboardButton("💰 Wallet",  callback_data="wallet"),
         InlineKeyboardButton("🔍 Scanner", callback_data="scanner")],
    ])

def main_menu_text():
    return (
        "🏪 *Main Menu*\n\n"
        "*Live Stock*\n"
        f"🌍 Leads: *{live_stock['leads']:,}*\n"
        f"🛍️ Stock: *{live_stock['stock']}*\n\n"
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
        row.append(InlineKeyboardButton(f"💠 £{a} 💠", callback_data=f"amt|{a}"))
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
    rows = [[InlineKeyboardButton(b["label"], callback_data=f"base|{vid}|{bk}")]
            for bk, b in STORE[vid]["bases"].items()]
    rows.append([InlineKeyboardButton("🔍 BIN Search", callback_data=f"bsearch|{vid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

def bin_list_keyboard(vid, bkey, page=0):
    """20 BINs per page, 2 per row (10 rows)."""
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
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")])
    return InlineKeyboardMarkup(rows), total_pages

def deads_keyboard():
    rows = [[InlineKeyboardButton(f"{l} — £{p:,}", callback_data=f"dbuy|{k}")]
            for l, p, k in DEADS_ITEMS]
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="store")])
    return InlineKeyboardMarkup(rows)

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    is_new = uid not in user_join_dates
    get_join_date(uid)

    if is_new:
        await log(context.application,
            f"🆕 *New User*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Only skip welcome screen if BOTH agreed AND channel-verified
    if uid in agreed_users and uid in channel_verified:
        await update.message.reply_text(
            main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    # Show rules + join button every other time
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel to Continue", url=JOIN_CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Let Me In",  callback_data="agree_rules")],
    ])
    await update.message.reply_text(RULES_TEXT, reply_markup=keyboard, parse_mode="Markdown")

# ═════════════════════════════════════════════════════════════════════════════
# ADMIN LOGIN
# ═════════════════════════════════════════════════════════════════════════════

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
        await log(context.application,
            f"🔑 *Admin Login*\n👤 {user_tag(update)}\n🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    else:
        await update.message.reply_text("❌ Wrong password.")
        await log(context.application, f"⚠️ *Failed Admin Login*\n👤 {user_tag(update)}")

async def cmd_adminlogout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logged_in_admins.discard(update.effective_user.id)
    await update.message.reply_text("🔒 Logged out of admin access.")

async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ Use /adminlogin <password> first."); return
    await update.message.reply_text(
        "🛠 *Admin Commands*\n\n"
        "*Login*\n"
        "`/adminlogin <password>`\n`/adminlogout`\n\n"
        "*Balance*\n"
        "`/addbalance <user_id> <amount>`\n"
        "`/removebalance <user_id> <amount>`\n"
        "`/setbalance <user_id> <amount>`\n"
        "`/checkbalance <user_id>`\n\n"
        "*Stock*\n"
        "`/setstock leads <number>`\n"
        "`/setstock stock <number>`\n\n"
        "*Vendors*\n"
        "`/addvendor <id> <label>`\n"
        "`/removevendor <id>`\n\n"
        "*Bases*\n"
        "`/addbase <vendor_id> <base_key> <price> <label>`\n"
        "`/removebase <vendor_id> <base_key>`\n\n"
        "*BINs*\n"
        "`/addbin <vendor_id> <base_key> <bin> <qty>`\n"
        "`/removebin <vendor_id> <base_key> <bin>`\n"
        "`/listbins <vendor_id> <base_key>`\n"
        "`/clearbase <vendor_id> <base_key>`\n\n"
        "*Users*\n"
        "`/listusers`\n"
        "`/broadcast <message>`",
        parse_mode="Markdown")

# ═════════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /addbalance <user_id> <amount>"); return
    user_balances[tid] = round(user_balances.get(tid, 0) + amt, 2)
    await update.message.reply_text(f"✅ Added *£{amt:.2f}* to `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")
    await log(context.application, f"💳 *Balance Added*\nBy: {user_tag(update)}\nUser: `{tid}`\nAmount: £{amt:.2f}\nNew balance: £{user_balances[tid]:.2f}")

async def cmd_removebalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /removebalance <user_id> <amount>"); return
    user_balances[tid] = round(max(0, user_balances.get(tid, 0) - amt), 2)
    await update.message.reply_text(f"✅ Removed *£{amt:.2f}* from `{tid}`\nNew balance: *£{user_balances[tid]:.2f}*", parse_mode="Markdown")

async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: tid = int(context.args[0]); amt = float(context.args[1])
    except (IndexError, ValueError): await update.message.reply_text("Usage: /setbalance <user_id> <amount>"); return
    user_balances[tid] = round(amt, 2)
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
    await update.message.reply_text(f"✅ Updated *{key}* to *{val:,}*", parse_mode="Markdown")

async def cmd_addvendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; label = " ".join(context.args[1:]); assert vid and label
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /addvendor <id> <label>"); return
    if vid in STORE: await update.message.reply_text(f"Vendor `{vid}` already exists."); return
    STORE[vid] = {"label": label, "bases": {}}
    await update.message.reply_text(f"✅ Added vendor *{label}*", parse_mode="Markdown")

async def cmd_removevendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; assert vid in STORE
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removevendor <vendor_id>"); return
    del STORE[vid]
    await update.message.reply_text(f"✅ Removed vendor `{vid}`")

async def cmd_addbase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        price = int(context.args[2]); label = " ".join(context.args[3:])
        assert vid in STORE and label and "|" not in bkey
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /addbase <vendor_id> <base_key> <price> <label>\nNote: base_key must not contain | or spaces\nExample: /addbase 8888 20fresh 20 £20 Base Fresh 🇬🇧"); return
    STORE[vid]["bases"][bkey] = {"label": label, "price_per_card": price, "bins": {}}
    await update.message.reply_text(f"✅ Added base *{label}* at £{price}/card", parse_mode="Markdown")

async def cmd_removebase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removebase <vendor_id> <base_key>"); return
    del STORE[vid]["bases"][bkey]
    await update.message.reply_text(f"✅ Removed base `{bkey}` from vendor `{vid}`")

async def cmd_addbin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try:
        vid = context.args[0]; bkey = context.args[1]
        bin_num = context.args[2]; qty = int(context.args[3])
        assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("Usage: /addbin <vendor_id> <base_key> <bin_number> <quantity>\nExample: /addbin 8888 15fresh 416598 20"); return
    STORE[vid]["bases"][bkey]["bins"][bin_num] = qty
    await update.message.reply_text(f"✅ BIN *{bin_num}* = *{qty}* in `{vid}` / `{bkey}`", parse_mode="Markdown")

async def cmd_removebin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    try: vid = context.args[0]; bkey = context.args[1]; bin_num = context.args[2]; assert vid in STORE and bkey in STORE[vid]["bases"]
    except (IndexError, AssertionError): await update.message.reply_text("Usage: /removebin <vendor_id> <base_key> <bin_number>"); return
    STORE[vid]["bases"][bkey]["bins"].pop(bin_num, None)
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
    await update.message.reply_text(f"✅ Cleared all BINs from `{vid}` / `{bkey}`")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    if not user_balances: await update.message.reply_text("No users with balances yet."); return
    lines = ["👥 *All Users & Balances*\n"]
    for uid, bal in sorted(user_balances.items(), key=lambda x: -x[1]):
        lines.append(f"`{uid}` — £{bal:.2f} (joined {user_join_dates.get(uid,'?')})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): await update.message.reply_text("❌ Use /adminlogin <password>"); return
    msg = " ".join(context.args)
    if not msg: await update.message.reply_text("Usage: /broadcast <message>"); return
    sent = 0
    for uid in list(agreed_users):
        try: await context.application.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown"); sent += 1
        except Exception: pass
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

# ═════════════════════════════════════════════════════════════════════════════
# BUTTON HANDLER  — all store callbacks use | separator to avoid key clashes
# ═════════════════════════════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid  = query.from_user.id
    data = query.data

    # ── Welcome / join gate ───────────────────────────────────────────────────
    if data == "agree_rules":
        is_member, reason = await check_channel_membership(context.bot, uid)

        if reason == "error":
            # Bot isn't admin in channel or channel not set up correctly
            await query.answer(
                "⚠️ Could not verify membership. Make sure the bot is admin in the channel, then try again.",
                show_alert=True)
            return

        if not is_member:
            # User hasn't joined
            await query.answer(
                "⛔️ You haven't joined our channel yet!\n\nTap 'Join Channel' then come back and try again.",
                show_alert=True)
            return

        # Verified member — grant access
        agreed_users.add(uid)
        channel_verified.add(uid)
        await log(context.application,
            f"✅ *User Verified & Entered*\n👤 {user_tag(update)}\n🪪 ID: `{uid}`\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        await query.edit_message_text(
            main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if data == "back":
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    # ── Wallet ────────────────────────────────────────────────────────────────
    if data == "wallet":
        await query.edit_message_text(wallet_profile_text(uid), reply_markup=amount_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("amt|"):
        amount = data.split("|")[1]
        await query.edit_message_text(f"💠 *£{amount} Top-Up*\n\nChoose your payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if data == "custom_amount":
        context.user_data["awaiting_custom"] = True
        await query.edit_message_text("💰 *Custom Amount*\n\nType the £ amount (minimum £70):\nExample: `150`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="wallet")]]),
            parse_mode="Markdown")
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
        await log(context.application, f"💰 *Top-Up Requested*\n👤 {user_tag(update)}\n💷 £{amount} via {coin}")
        await query.edit_message_text(
            f"{price_line}\n\n🏦 Address:\n`{address}`\n\n"
            f"‼️ Deposits are permanent and *non refundable*\n"
            f"‼️ Double check the {coin} amount *before* sending\n"
            f"‼️ Anything UNDER or ABOVE = *Donation*\n\n"
            f"💠 Funded when transaction is confirmed\n\n"
            f"⚠️ *DO NOT SEND AS £ — only send as {coin}*\n"
            f"‼️ One payment per wallet address\n\n"
            f"_Your ID: `{uid}`_\n_DM @{SUPER_ADMIN} with TX ID after sending_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"amt|{amount}")]]),
            parse_mode="Markdown")
        return

    # ── Store ─────────────────────────────────────────────────────────────────
    if data == "store":
        await query.edit_message_text("👥 *Select a vendor:*", reply_markup=vendor_select_keyboard(), parse_mode="Markdown")
        return

    # Vendor
    if data.startswith("vendor|"):
        vid = data.split("|")[1]
        if vid not in STORE: await query.answer("Vendor not found."); return
        await query.edit_message_text(f"👤 *{STORE[vid]['label']}*\n\nSelect a base:",
            reply_markup=base_select_keyboard(vid), parse_mode="Markdown")
        return

    # Base — show BIN list page 0
    if data.startswith("base|"):
        _, vid, bkey = data.split("|", 2)
        base = STORE[vid]["bases"][bkey]
        total_qty = sum(base["bins"].values())
        kbd, total_pages = bin_list_keyboard(vid, bkey, 0)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n"
            f"📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {total_qty}\n\n"
            f"Select BIN group:\n_Page 1 of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    # Paginate BIN list
    if data.startswith("bpage|"):
        _, vid, bkey, page = data.split("|", 3); page = int(page)
        base = STORE[vid]["bases"][bkey]
        kbd, total_pages = bin_list_keyboard(vid, bkey, page)
        await query.edit_message_text(
            f"👤 *{STORE[vid]['label']}*\n"
            f"📦 *Base:* {base['label']}\n"
            f"🗂 *Available:* {sum(base['bins'].values())}\n\n"
            f"Select BIN group:\n_Page {page+1} of {total_pages}_",
            reply_markup=kbd, parse_mode="Markdown")
        return

    # BIN search prompt
    if data.startswith("bsearch|"):
        vid = data.split("|")[1]
        context.user_data["bin_search_vendor"] = vid
        context.user_data["awaiting_bin_search"] = True
        await query.edit_message_text(f"🔍 *BIN Search — {STORE[vid]['label']}*\n\nType the BIN number:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]),
            parse_mode="Markdown")
        return

    # BIN purchase confirm
    if data.startswith("buybin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        if qty == 0: await query.answer("Out of stock."); return
        total = base["price_per_card"] * qty; balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"👤 Vendor: *{STORE[vid]['label']}*\n"
            f"📦 Base: *{base['label']}*\n"
            f"💳 BIN: *{bin_num}*\n"
            f"🗂 Qty: *{qty} cards*\n"
            f"💰 Per card: *£{base['price_per_card']}*\n"
            f"💷 *Total: £{total}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"cfmbin|{vid}|{bkey}|{bin_num}|{page}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"bpage|{vid}|{bkey}|{page}")]]),
            parse_mode="Markdown")
        return

    # BIN purchase confirmed
    if data.startswith("cfmbin|"):
        _, vid, bkey, bin_num, page = data.split("|", 4)
        base = STORE[vid]["bases"][bkey]; qty = base["bins"].get(bin_num, 0)
        total = base["price_per_card"] * qty; balance = user_balances.get(uid, 0)
        if qty == 0: await query.answer("Out of stock."); return
        if balance < total:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{total}\nYour balance: £{balance:.2f}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back",   callback_data=f"bpage|{vid}|{bkey}|{page}")]]),
                parse_mode="Markdown"); return
        user_balances[uid] = round(balance - total, 2)
        del STORE[vid]["bases"][bkey]["bins"][bin_num]
        await log(context.application,
            f"🛒 *Purchase — BIN*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"Vendor: {STORE[vid]['label']}\nBase: {base['label']}\n"
            f"BIN: {bin_num} x{qty}\n💷 Paid: £{total}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\nBIN: *{bin_num}* | Qty: *{qty}* | Paid: *£{total}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]),
            parse_mode="Markdown")
        return

    # ── Deads ─────────────────────────────────────────────────────────────────
    if data == "deads":
        await query.edit_message_text(
            "💀 *Deads — Unspoofed Files*\n\n"
            "*Specific:*\n• 50+ Specific BIN, Gender & DOB — £225\n• 100+ Specific BIN, Gender & DOB — £350\n\n"
            "*Random:*\n• 50+ File — £100\n• 100+ File — £150\n• 500 File — £500\n• 1k File — £700\n• 2k File — £1,200",
            reply_markup=deads_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("dbuy|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n📁 *{label}*\n💷 *Price: £{price:,}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"dcfm|{key}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data="deads")]]),
            parse_mode="Markdown")
        return

    if data.startswith("dcfm|"):
        key = data.split("|")[1]
        item = next(((l,p,k) for l,p,k in DEADS_ITEMS if k==key), None)
        if not item: await query.answer("Not found."); return
        label, price, _ = item; balance = user_balances.get(uid, 0)
        if balance < price:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{price:,}\nYour balance: £{balance:.2f}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back", callback_data="deads")]]),
                parse_mode="Markdown"); return
        user_balances[uid] = round(balance - price, 2)
        await log(context.application,
            f"🛒 *Purchase — Deads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"📁 {label}\n💷 Paid: £{price:,}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n📁 *{label}*\n💷 Paid: *£{price:,}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\nContact @{SUPER_ADMIN} for your files.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Store", callback_data="store")]]),
            parse_mode="Markdown")
        return

    # ── Leads ─────────────────────────────────────────────────────────────────
    if data == "leads":
        total = sum(sum(d["carriers"].values()) for d in LEADS.values())
        pricing = leads_pricing_text()
        await query.edit_message_text(
            f"🌍 *Leads*\n\n"
            f"{pricing}\n\n"
            f"_Select a country below:_",
            reply_markup=country_keyboard(),
            parse_mode="Markdown")
        return

    # Country selected → show carriers
    if data.startswith("lc|"):
        cc = data.split("|")[1]
        if cc not in LEADS: await query.answer("Country not found."); return
        d = LEADS[cc]
        total = sum(d["carriers"].values())
        await query.edit_message_text(
            f"*Country:* {d['flag']} {d['name']}\n"
            f"*Stock:* {total:,} numbers\n\n"
            f"Available carriers:",
            reply_markup=carrier_keyboard(cc),
            parse_mode="Markdown")
        return

    # Carrier selected → show qty tiers
    if data.startswith("lk|"):
        _, cc, carrier = data.split("|", 2)
        if cc not in LEADS: await query.answer("Not found."); return
        stock = LEADS[cc]["carriers"].get(carrier, 0)
        d = LEADS[cc]
        await query.edit_message_text(
            f"*Country:* {d['flag']} {d['name']}\n"
            f"*Carrier:* {carrier}\n"
            f"*Available:* {stock:,} numbers\n\n"
            f"Select quantity:",
            reply_markup=qty_keyboard(cc, carrier),
            parse_mode="Markdown")
        return

    # Qty selected → confirm screen
    if data.startswith("lq|"):
        _, cc, carrier, qty_str = data.split("|", 3)
        qty     = int(qty_str)
        price   = dict(LEADS_PRICING).get(qty, 0)
        d       = LEADS[cc]
        stock   = LEADS[cc]["carriers"].get(carrier, 0)
        balance = user_balances.get(uid, 0)
        if stock < qty:
            await query.answer(f"Not enough stock. Only {stock:,} available.", show_alert=True)
            return
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"🌍 *Country:* {d['flag']} {d['name']}\n"
            f"📡 *Carrier:* {carrier}\n"
            f"🗂 *Quantity:* {qty:,} numbers\n"
            f"💷 *Price: £{price}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"lb|{cc}|{carrier}|{qty}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"lk|{cc}|{carrier}")]]),
            parse_mode="Markdown")
        return

    # Leads purchase confirmed
    if data.startswith("lb|"):
        _, cc, carrier, qty_str = data.split("|", 3)
        qty     = int(qty_str)
        price   = dict(LEADS_PRICING).get(qty, 0)
        balance = user_balances.get(uid, 0)
        d       = LEADS[cc]
        if balance < price:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{price}\nYour balance: £{balance:.2f}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back",   callback_data=f"lk|{cc}|{carrier}")]]),
                parse_mode="Markdown")
            return
        user_balances[uid] = round(balance - price, 2)
        # Deduct from carrier stock
        if cc in LEADS and carrier in LEADS[cc]["carriers"]:
            LEADS[cc]["carriers"][carrier] = max(0, LEADS[cc]["carriers"][carrier] - qty)
        await log(context.application,
            f"🛒 *Purchase — Leads*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"🌍 {d['flag']} {d['name']} | {carrier}\n"
            f"🗂 {qty:,} numbers\n💷 Paid: £{price}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n"
            f"🌍 *{d['flag']} {d['name']}* — {carrier}\n"
            f"🗂 *{qty:,} numbers*\n"
            f"💷 Paid: *£{price}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"Contact @{SUPER_ADMIN} to receive your leads.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Leads", callback_data="leads")]]),
            parse_mode="Markdown")
        return

    # ── Scanner ───────────────────────────────────────────────────────────────
    if data == "scanner":
        await query.edit_message_text(
            "🔍 *Scanner*\n\n"
            "👆 Select a scanner to verify your data.",
            reply_markup=scanner_keyboard("all", 0),
            parse_mode="Markdown")
        return

    # Category tab or page navigation
    if data.startswith("scan|"):
        _, cat, pg = data.split("|"); pg = int(pg)
        items = scanner_items_for_cat(cat)
        await query.edit_message_text(
            "🔍 *Scanner*\n\n"
            "👆 Select a scanner to verify your data.",
            reply_markup=scanner_keyboard(cat, pg),
            parse_mode="Markdown")
        return

    # Scanner item selected — show qty options
    if data.startswith("sni|"):
        idx = int(data.split("|")[1])
        if idx >= len(SCANNER_ITEMS): await query.answer("Item not found."); return
        label, category, price = SCANNER_ITEMS[idx]
        balance = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🔍 *{label}*\n\n"
            f"💰 Price: *${price:.2f} / k*\n"
            f"Your balance: *£{balance:.2f}*\n\n"
            f"Select quantity:",
            reply_markup=scanner_qty_keyboard(idx, category),
            parse_mode="Markdown")
        return

    # Quantity selected — confirm
    if data.startswith("snq|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): await query.answer("Not found."); return
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        await query.edit_message_text(
            f"🛒 *Purchase Confirmation*\n\n"
            f"🔍 *{label}*\n"
            f"🗂 Quantity: *{qty_k}k*\n"
            f"💷 *Total: £{total_gbp:.2f}*\n\n"
            f"Your balance: *£{balance:.2f}*\n\nConfirm purchase?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"snc|{idx}|{qty_k}"),
                 InlineKeyboardButton("❌ Cancel",  callback_data=f"sni|{idx}")]]),
            parse_mode="Markdown")
        return

    # Scanner purchase confirmed
    if data.startswith("snc|"):
        _, idx_s, qty_s = data.split("|"); idx = int(idx_s); qty_k = int(qty_s)
        if idx >= len(SCANNER_ITEMS): await query.answer("Not found."); return
        label, category, price = SCANNER_ITEMS[idx]
        total_gbp = round(qty_k * price, 2)
        balance   = user_balances.get(uid, 0)
        if balance < total_gbp:
            await query.edit_message_text(
                f"❌ *Insufficient Balance*\n\nRequired: £{total_gbp:.2f}\nYour balance: £{balance:.2f}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Wallet",  callback_data="wallet"),
                     InlineKeyboardButton("⬅️ Back",    callback_data=f"sni|{idx}")]]),
                parse_mode="Markdown")
            return
        user_balances[uid] = round(balance - total_gbp, 2)
        await log(context.application,
            f"🔍 *Purchase — Scanner*\n👤 {user_tag(update)}\n🪪 `{uid}`\n"
            f"Item: {label} | {qty_k}k\n💷 Paid: £{total_gbp:.2f}\n💰 Remaining: £{user_balances[uid]:.2f}")
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n"
            f"🔍 *{label}*\n"
            f"🗂 *{qty_k}k records*\n"
            f"💷 Paid: *£{total_gbp:.2f}*\n"
            f"💰 Remaining: *£{user_balances[uid]:.2f}*\n\n"
            f"Contact @{SUPER_ADMIN} to receive your data.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Scanner", callback_data="scanner")]]),
            parse_mode="Markdown")
        return

# ── Text message handler ──────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_custom"):
        text = update.message.text.strip().replace("£","")
        try:
            amount = int(float(text))
            if amount < MIN_TOPUP: await update.message.reply_text(f"Minimum is £{MIN_TOPUP}."); return
        except ValueError: await update.message.reply_text("Enter a number e.g. 150"); return
        context.user_data["awaiting_custom"] = False
        await update.message.reply_text(f"💠 *£{amount} Top-Up*\n\nChoose payment method:",
            reply_markup=coin_select_keyboard(amount), parse_mode="Markdown")
        return

    if context.user_data.get("awaiting_bin_search"):
        bin_num = update.message.text.strip()
        vid = context.user_data.get("bin_search_vendor")
        context.user_data["awaiting_bin_search"] = False
        results = []
        for bkey, base in STORE.get(vid,{}).get("bases",{}).items():
            qty = base["bins"].get(bin_num)
            if qty: results.append(f"📦 *{base['label']}* — {qty} @ £{base['price_per_card']}/card")
        msg = f"🔍 *BIN {bin_num}*\n\n" + "\n".join(results) if results else f"❌ BIN *{bin_num}* not found."
        await update.message.reply_text(msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"vendor|{vid}")]]),
            parse_mode="Markdown")

async def cmd_updatelead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /updatelead <CC> <CarrierName> <stock>
    Example: /updatelead UK EE 4000000
    Use 0 to remove a carrier."""
    if not is_admin(update): await update.message.reply_text("❌ Not authorised."); return
    try:
        cc      = context.args[0].upper()
        carrier = context.args[1]
        stock   = int(context.args[2])
        assert cc in LEADS
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text(
            "Usage: /updatelead <CC> <Carrier> <stock>\n"
            "Example: /updatelead UK EE 4000000\n"
            "Country codes: UK, IE, AU, DE, FR, ES..."); return
    if stock <= 0:
        LEADS[cc]["carriers"].pop(carrier, None)
        await update.message.reply_text(f"✅ Removed *{carrier}* from {LEADS[cc]['flag']} {LEADS[cc]['name']}", parse_mode="Markdown")
    else:
        LEADS[cc]["carriers"][carrier] = stock
        await update.message.reply_text(
            f"✅ Updated *{carrier}* → *{stock:,}* in {LEADS[cc]['flag']} {LEADS[cc]['name']}", parse_mode="Markdown")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN: raise ValueError("BOT_TOKEN is not set!")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",         cmd_start))
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
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
