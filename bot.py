"""
Telegram number/OTP bot (python-telegram-bot v20+).

Setup:
    pip install "python-telegram-bot>=20" httpx pyotp
    export BOT_TOKEN="..."            # from @BotFather
    export MESSAGES_URL="<Teleroutex endpoint that returns received SMS, with ?apiKey=NEW_KEY>"
    export ADMINS="123456789"         # comma separated
    python bot.py

Admin adds numbers by sending a .txt file (one number per line) to the bot
or with /addnumbers 2371234567 2379876543
Teleroutex -> Telegram group mode (SMS_SOURCE=group, default):
    1. Create a group (or channel), set Teleroutex to forward SMS into it.
    2. Add this bot to it (as admin for a channel; admin or privacy-mode off for a group).
    3. export SOURCE_GROUP_ID=-100xxxxxxxxxx   (use a different OTP_GROUP_ID for public posts)
"""
import asyncio
import html
import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pyotp
from urllib.parse import urlencode
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, Update)
from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, ContextTypes, MessageHandler, filters)

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs (bot token / API key) at INFO level: keep them out of the console
for _n in ("httpx", "httpcore"):
    logging.getLogger(_n).setLevel(logging.WARNING)
log = logging.getLogger("bot")

# ==================== CONFIG ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
# SMS_SOURCE=group : Teleroutex forwards SMS into a Telegram group/channel (SOURCE_GROUP_ID); bot reads it
# SMS_SOURCE=api   : bot polls MESSAGES_URL instead
SMS_SOURCE = os.environ.get("SMS_SOURCE", "api")
SOURCE_GROUP_ID = int(os.environ.get("SOURCE_GROUP_ID", "0"))
MESSAGES_URL = os.environ.get("MESSAGES_URL", "")
# API mode (SMS_SOURCE=api): either set TELEROUTEX_API_KEY (recommended) or a full MESSAGES_URL
TELEROUTEX_API_KEY = os.environ.get("TELEROUTEX_API_KEY", "").strip()
TELEROUTEX_URL = os.environ.get("TELEROUTEX_URL", "https://server.teleroutex.com/api/message-data-record/viewstats")
if SMS_SOURCE == "api" and not (MESSAGES_URL or TELEROUTEX_API_KEY):
    raise SystemExit("API mode needs TELEROUTEX_API_KEY (or MESSAGES_URL). Get the key from Teleroutex panel.")
ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split(",") if x.strip()]
if not ADMINS:
    raise SystemExit("ADMINS is empty: set your Telegram user ID in .env")
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
CHANNEL_LINK = os.environ["CHANNEL_LINK"]
def _int(v):
    try:
        return int(str(v).strip())
    except ValueError:
        return 0
OTP_GROUP_ID = _int(os.environ.get("OTP_GROUP_ID", "0"))   # optional: can be set from the bot with /setotpgroup
SUPPORT_LINK = os.environ.get("SUPPORT_LINK", CHANNEL_LINK)
# invite link of the public OTP group: the View OTP button opens it directly
OTP_GROUP_LINK = os.environ.get("OTP_GROUP_LINK", "").strip()
DEVELOPER_LINK = os.environ.get("DEVELOPER_LINK", SUPPORT_LINK)
TIMEZONE_HOURS = float(os.environ.get("TIMEZONE_HOURS", "6"))   # time shown in the public group (6 = Bangladesh)
OTP_RATE = float(os.environ.get("OTP_RATE", "0.80"))
# every OTP that arrives while the user holds the number is forwarded; 1 = pay for each, 0 = pay only the first
PAY_EVERY_OTP = os.environ.get("PAY_EVERY_OTP", "1") == "1"
# public OTP group: how many leading digits of the code stay visible (0 = fully hidden)
OTP_PUBLIC_VISIBLE_DIGITS = int(os.environ.get("OTP_PUBLIC_VISIBLE_DIGITS", "0"))
REFERRAL_PRICE = 0
MIN_WITHDRAW, MAX_WITHDRAW = 50, 10000
NUMBERS_PER_REQUEST = int(os.environ.get("NUMBERS_PER_REQUEST", "3"))   # numbers given per GET NUMBER tap
OTP_VALID_MINUTES = int(os.environ.get("OTP_VALID_MINUTES", "10"))       # how long each number waits for its OTP
KEEP_OLD_MINUTES = int(os.environ.get("KEEP_OLD_MINUTES", "0"))          # after Change Number, old numbers deliver OTPs this long (0 = no time limit)
POLL_SECONDS, POLL_TIMEOUT = 5, OTP_VALID_MINUTES * 60
DB_FILE = os.environ.get("DB_FILE", "db.json")

SERVICES = ["WHATSAPP", "TELEGRAM", "FACEBOOK", "INSTAGRAM", "TIKTOK"]
# Country calling code -> (ISO country, display name). Used for the country menu and for removing the code.
CALLING = {
    "1": ("US", "USA/Canada"), "7": ("RU", "Russia"), "20": ("EG", "Egypt"), "27": ("ZA", "South Africa"),
    "30": ("GR", "Greece"), "31": ("NL", "Netherlands"), "32": ("BE", "Belgium"), "33": ("FR", "France"),
    "34": ("ES", "Spain"), "36": ("HU", "Hungary"), "39": ("IT", "Italy"), "40": ("RO", "Romania"),
    "41": ("CH", "Switzerland"), "43": ("AT", "Austria"), "44": ("GB", "UK"), "45": ("DK", "Denmark"),
    "46": ("SE", "Sweden"), "47": ("NO", "Norway"), "48": ("PL", "Poland"), "49": ("DE", "Germany"),
    "51": ("PE", "Peru"), "52": ("MX", "Mexico"), "53": ("CU", "Cuba"), "54": ("AR", "Argentina"),
    "55": ("BR", "Brazil"), "56": ("CL", "Chile"), "57": ("CO", "Colombia"), "58": ("VE", "Venezuela"),
    "60": ("MY", "Malaysia"), "61": ("AU", "Australia"), "62": ("ID", "Indonesia"), "63": ("PH", "Philippines"),
    "64": ("NZ", "New Zealand"), "65": ("SG", "Singapore"), "66": ("TH", "Thailand"), "81": ("JP", "Japan"),
    "82": ("KR", "South Korea"), "84": ("VN", "Vietnam"), "86": ("CN", "China"), "90": ("TR", "Turkey"),
    "91": ("IN", "India"), "92": ("PK", "Pakistan"), "93": ("AF", "Afghanistan"), "94": ("LK", "Sri Lanka"),
    "95": ("MM", "Myanmar"), "98": ("IR", "Iran"), "211": ("SS", "South Sudan"), "212": ("MA", "Morocco"),
    "213": ("DZ", "Algeria"), "216": ("TN", "Tunisia"), "218": ("LY", "Libya"), "220": ("GM", "Gambia"),
    "221": ("SN", "Senegal"), "222": ("MR", "Mauritania"), "223": ("ML", "Mali"), "224": ("GN", "Guinea"),
    "225": ("CI", "Ivory Coast"), "226": ("BF", "Burkina Faso"), "227": ("NE", "Niger"), "228": ("TG", "Togo"),
    "229": ("BJ", "Benin"), "230": ("MU", "Mauritius"), "231": ("LR", "Liberia"), "232": ("SL", "Sierra Leone"),
    "233": ("GH", "Ghana"), "234": ("NG", "Nigeria"), "235": ("TD", "Chad"), "236": ("CF", "Central African Rep."),
    "237": ("CM", "Cameroon"), "238": ("CV", "Cape Verde"), "239": ("ST", "Sao Tome"), "240": ("GQ", "Equatorial Guinea"),
    "241": ("GA", "Gabon"), "242": ("CG", "Congo"), "243": ("CD", "DR Congo"), "244": ("AO", "Angola"),
    "245": ("GW", "Guinea-Bissau"), "248": ("SC", "Seychelles"), "249": ("SD", "Sudan"), "250": ("RW", "Rwanda"),
    "251": ("ET", "Ethiopia"), "252": ("SO", "Somalia"), "253": ("DJ", "Djibouti"), "254": ("KE", "Kenya"),
    "255": ("TZ", "Tanzania"), "256": ("UG", "Uganda"), "257": ("BI", "Burundi"), "258": ("MZ", "Mozambique"),
    "260": ("ZM", "Zambia"), "261": ("MG", "Madagascar"), "262": ("RE", "Reunion"), "263": ("ZW", "Zimbabwe"),
    "264": ("NA", "Namibia"), "265": ("MW", "Malawi"), "266": ("LS", "Lesotho"), "267": ("BW", "Botswana"),
    "268": ("SZ", "Eswatini"), "269": ("KM", "Comoros"), "351": ("PT", "Portugal"), "352": ("LU", "Luxembourg"),
    "353": ("IE", "Ireland"), "354": ("IS", "Iceland"), "355": ("AL", "Albania"), "356": ("MT", "Malta"),
    "357": ("CY", "Cyprus"), "358": ("FI", "Finland"), "359": ("BG", "Bulgaria"), "370": ("LT", "Lithuania"),
    "371": ("LV", "Latvia"), "372": ("EE", "Estonia"), "373": ("MD", "Moldova"), "374": ("AM", "Armenia"),
    "375": ("BY", "Belarus"), "380": ("UA", "Ukraine"), "381": ("RS", "Serbia"), "385": ("HR", "Croatia"),
    "386": ("SI", "Slovenia"), "387": ("BA", "Bosnia"), "389": ("MK", "North Macedonia"), "420": ("CZ", "Czechia"),
    "421": ("SK", "Slovakia"), "501": ("BZ", "Belize"), "502": ("GT", "Guatemala"), "503": ("SV", "El Salvador"),
    "504": ("HN", "Honduras"), "505": ("NI", "Nicaragua"), "506": ("CR", "Costa Rica"), "507": ("PA", "Panama"),
    "591": ("BO", "Bolivia"), "592": ("GY", "Guyana"), "593": ("EC", "Ecuador"), "595": ("PY", "Paraguay"),
    "597": ("SR", "Suriname"), "598": ("UY", "Uruguay"), "673": ("BN", "Brunei"), "855": ("KH", "Cambodia"),
    "856": ("LA", "Laos"), "880": ("BD", "Bangladesh"), "886": ("TW", "Taiwan"), "960": ("MV", "Maldives"),
    "961": ("LB", "Lebanon"), "962": ("JO", "Jordan"), "963": ("SY", "Syria"), "964": ("IQ", "Iraq"),
    "965": ("KW", "Kuwait"), "966": ("SA", "Saudi Arabia"), "967": ("YE", "Yemen"), "968": ("OM", "Oman"),
    "970": ("PS", "Palestine"), "971": ("AE", "UAE"), "972": ("IL", "Israel"), "973": ("BH", "Bahrain"),
    "974": ("QA", "Qatar"), "975": ("BT", "Bhutan"), "976": ("MN", "Mongolia"), "977": ("NP", "Nepal"),
    "992": ("TJ", "Tajikistan"), "993": ("TM", "Turkmenistan"), "994": ("AZ", "Azerbaijan"), "995": ("GE", "Georgia"),
    "996": ("KG", "Kyrgyzstan"), "998": ("UZ", "Uzbekistan"),
}
def _flag(iso):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in iso)
PREFIXES = {code: (_flag(iso), name) for code, (iso, name) in CALLING.items()}

T = {
    "en": {
        "welcome": "💎 <b>[ ACCESS GRANTED ]</b> 💎\n━━━━━━━━━━━━━━━━━━━━━━\n🟢 Connection: <code>SECURE</code>",
        "get": "💬 GET NUMBER", "traffic": "📟 TRAFFIC", "twofa": "🔐 2FA ONLINE",
        "profile": "👤 PROFILE", "refer": "🎁 Refer", "support": "👤 SUPPORT",
        "lang": "🌐 LANGUAGE", "admin": "⚙️ ADMIN PANEL",
        "banned": "🛑 YOU ARE BANNED!",
        "join": "🔔 Please join our channel to use the bot.", "btn_join": "🔔 Join Channel",
        "btn_cont": "❇️ Continue", "not_joined": "You haven't joined yet.",
        "pick_service": "📲 <b>[ GET ACTIVE NODE ]</b>\n\nSelect your target service:",
        "pick_country": "📲 <b>[ GET ACTIVE NODE ]</b>\n\n🎯 Service: <b>{sid}</b>\n🌍 Select country:",
        "no_numbers": "🛑 <b>No numbers available right now.</b>",
        "scanning": "🛰️ <b>[ NODE ALLOCATED ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🌍 <b>{country}</b>\n📱 <b>{sid}</b>\n\n📡 ⏳ Waiting for OTP... (valid {mins} min)",
        "success": "✅ <b>[ OTP RECEIVED ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🌍 <b>{country}</b>\n📱 <b>{sid}</b>\n📟 <code>{num}</code>\n🔑 <code>{otp}</code>\n\n💵 +{rate} BDT",
        "timeout": "⌛ <b>No OTP received.</b> Try another number.",
        "cc": "🌍 With country code", "nocc": "🔢 Without country code",
        "change": "🔄 Change Number", "view_otp": "📩 View OTP", "cancel": "❌ Cancel", "cancelled": "Cancelled.",
        "ask_2fa": "🔑 <b>Enter your 2FA Secret Key:</b>",
        "bad_2fa": "🛑 <b>INVALID SECRET KEY</b>",
        "code_2fa": "🔐 Code: <code>{c}</code>\n⏱ Valid for {s}s",
        "support_msg": "💬 <b>SUPPORT</b>\n\nTap a button to contact us.",
        "help": "💬 Help Center", "dev": "👨‍💻 Developer Support",
        "profile_msg": "👤 <b>USER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🏷️ <code>{name}</code>\n🗝️ ID: <code>{uid}</code>\n\n💵 Balance: <code>{bal:.2f} BDT</code>\n\n📊 Today: 📱 {tn} | 🔑 {to}\n🌐 Total: 📱 {an} | 🔑 {ao}",
        "withdraw": "💳 WITHDRAW",
        "wd_min": "📉 Balance: {bal:.2f} BDT. Minimum withdrawal is {m} BDT.",
        "wd_gateway": "💳 Select payment gateway:",
        "wd_amount": "🪙 Enter amount (Min {mn}, Max {mx} BDT):",
        "wd_bad_amount": "🛑 Invalid amount.",
        "wd_number": "📲 Send your receiving number (017XXXXXXXX):",
        "wd_bad_number": "🛑 Invalid number.",
        "wd_sent": "✅ Withdrawal request #{id} submitted.",
        "wd_paid": "✅ Withdrawal #{id} was paid.",
        "wd_rejected": "❌ Withdrawal #{id} was rejected and refunded.",
        "refer_msg": "🎁 <b>[ REFERRAL ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n👥 Invites: <code>{n}</code>\n🪙 Earned: <code>{r} BDT</code>\n\n🔗 <code>{link}</code>",
        "lang_msg": "🌐 <b>Select your language:</b>", "lang_set": "✅ Language updated.",
        "board": "🏆 <b>TOP 10 OTP LEADERBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n",
    },
    "bn": {
        "welcome": "💎 <b>[ নোড অ্যাক্সেস সফল ]</b> 💎\n━━━━━━━━━━━━━━━━━━━━━━\n🟢 সংযোগ: <code>সক্রিয়</code>",
        "get": "💬 নম্বর নিন", "traffic": "📟 লিডারবোর্ড", "twofa": "🔐 2FA অনলাইন",
        "profile": "👤 প্রোফাইল", "refer": "🎁 রেফার করুন", "support": "👤 সাপোর্ট",
        "lang": "🌐 ভাষা পরিবর্তন", "admin": "⚙️ অ্যাডমিন প্যানেল",
        "banned": "🛑 আপনি ব্যান হয়েছেন!",
        "join": "🔔 বট ব্যবহার করতে আমাদের চ্যানেলে জয়েন করুন।", "btn_join": "🔔 চ্যানেলে জয়েন করুন",
        "btn_cont": "❇️ Continue", "not_joined": "আপনি এখনো জয়েন করেননি।",
        "pick_service": "📲 <b>[ নম্বর নোড কানেকশন ]</b>\n\nসার্ভিস সিলেক্ট করুন:",
        "pick_country": "📲 <b>[ নম্বর নোড কানেকশন ]</b>\n\n🎯 সার্ভিস: <b>{sid}</b>\n🌍 দেশ সিলেক্ট করুন:",
        "no_numbers": "🛑 <b>এখন কোনো নম্বর নেই।</b>",
        "scanning": "🛰️ <b>[ নম্বর বরাদ্দ ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🌍 <b>{country}</b>\n📱 <b>{sid}</b>\n\n📡 ⏳ ওটিপি স্ক্যান করা হচ্ছে... ({mins} মিনিট বৈধ)",
        "success": "✅ <b>[ ওটিপি সফল ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🌍 <b>{country}</b>\n📱 <b>{sid}</b>\n📟 <code>{num}</code>\n🔑 <code>{otp}</code>\n\n💵 +{rate} BDT",
        "timeout": "⌛ <b>ওটিপি আসেনি।</b> অন্য নম্বর নিন।",
        "cc": "🌍 কান্ট্রি কোড সহ", "nocc": "🔢 কান্ট্রি কোড ছাড়া",
        "change": "🔄 নম্বর পরিবর্তন", "view_otp": "📩 ওটিপি দেখুন", "cancel": "❌ বাতিল", "cancelled": "বাতিল করা হয়েছে।",
        "ask_2fa": "🔑 <b>আপনার 2FA সিক্রেট কী পাঠান:</b>",
        "bad_2fa": "🛑 <b>ভুল সিক্রেট কী</b>",
        "code_2fa": "🔐 কোড: <code>{c}</code>\n⏱ মেয়াদ {s} সেকেন্ড",
        "support_msg": "💬 <b>সাপোর্ট</b>\n\nনিচের বাটনে ক্লিক করুন।",
        "help": "💬 হেল্প সেন্টার", "dev": "👨‍💻 ডেভলপার সাপোর্ট",
        "profile_msg": "👤 <b>ইউজার প্রোফাইল</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🏷️ <code>{name}</code>\n🗝️ ID: <code>{uid}</code>\n\n💵 ব্যালেন্স: <code>{bal:.2f} BDT</code>\n\n📊 আজ: 📱 {tn} | 🔑 {to}\n🌐 মোট: 📱 {an} | 🔑 {ao}",
        "withdraw": "💸 উইথড্র করুন",
        "wd_min": "📉 ব্যালেন্স: {bal:.2f} BDT। সর্বনিম্ন উইথড্র {m} BDT।",
        "wd_gateway": "💳 পেমেন্ট গেটওয়ে সিলেক্ট করুন:",
        "wd_amount": "🪙 পরিমাণ লিখুন (সর্বনিম্ন {mn}, সর্বোচ্চ {mx} BDT):",
        "wd_bad_amount": "🛑 ভুল পরিমাণ।",
        "wd_number": "📲 নম্বর পাঠান (017XXXXXXXX):",
        "wd_bad_number": "🛑 ভুল নম্বর।",
        "wd_sent": "✅ উইথড্র রিকোয়েস্ট #{id} জমা হয়েছে।",
        "wd_paid": "✅ উইথড্র #{id} পেমেন্ট হয়েছে।",
        "wd_rejected": "❌ উইথড্র #{id} বাতিল হয়েছে, টাকা ফেরত দেওয়া হয়েছে।",
        "refer_msg": "🎁 <b>[ রেফারেল ]</b>\n━━━━━━━━━━━━━━━━━━━━━━\n👥 সফল রেফার: <code>{n}</code>\n🪙 অর্জিত: <code>{r} BDT</code>\n\n🔗 <code>{link}</code>",
        "lang_msg": "🌐 <b>ভাষা সিলেক্ট করুন:</b>", "lang_set": "✅ ভাষা পরিবর্তন হয়েছে।",
        "board": "🏆 <b>টপ ১০ ওটিপি লিডারবোর্ড</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n",
    },
}
LABEL_ACTIONS = {}
for _l, _d in T.items():
    for _k in ("get", "traffic", "twofa", "profile", "refer", "support", "lang", "admin"):
        LABEL_ACTIONS[_d[_k]] = _k

# ==================== STORAGE ====================
db = {"users": {}, "pool": [], "pools": {}, "withdraws": {}, "wd_seq": 0}
if os.path.exists(DB_FILE):
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            db.update(json.load(f))
    except Exception as e:
        log.error("db load failed: %s", e)

db.setdefault("rates", {})
db.setdefault("held", {})      # old numbers (after Change Number) that keep delivering OTPs to their user
db.setdefault("pools", {})
# the service list lives in the database so the admin can add/remove services from the bot
if db.get("services"):
    SERVICES[:] = db["services"]
else:
    db["services"] = list(SERVICES)
for _s in SERVICES:
    db["pools"].setdefault(_s, [])

# public OTP group chosen inside the bot (/setotpgroup) overrides start.bat
_g = db.get("otp_group")
if _g:
    OTP_GROUP_ID = _int(_g.get("id"))
    OTP_GROUP_LINK = _g.get("link") or OTP_GROUP_LINK

def set_otp_group(chat_id, link=""):
    global OTP_GROUP_ID, OTP_GROUP_LINK
    OTP_GROUP_ID = int(chat_id)
    if link:
        OTP_GROUP_LINK = link
    db["otp_group"] = {"id": OTP_GROUP_ID, "link": OTP_GROUP_LINK}
    save()

def clean_service(raw):
    """Normalise an admin-typed service name; returns None if it is not allowed."""
    name = re.sub(r"\s+", " ", str(raw).upper()).strip()
    return name if re.fullmatch(r"[A-Z0-9][A-Z0-9 _&.\-]{1,19}", name) else None

def add_service(name):
    SERVICES.append(name)
    db["services"] = list(SERVICES)
    db["pools"].setdefault(name, [])
    save()

def del_service(name):
    SERVICES.remove(name)
    db["services"] = list(SERVICES)
    db["pools"].pop(name, None)
    db["rates"].pop(name, None)
    save()

def get_rate(sid):
    r = db["rates"]
    return float(r.get(sid, r.get("default", OTP_RATE)))

def rates_text_and_kb():
    """Build the OTP rates admin message + keyboard with +/- buttons."""
    lines = ["💵 <b>OTP RATES</b>", "━━━━━━━━━━━━━━━━━━━━━━",
             f"Default: <b>{get_rate('default'):.2f}</b> BDT"]
    for sv in SERVICES:
        lines.append(f"{sv}: <b>{get_rate(sv):.2f}</b> BDT")
    lines.append("\nTap ➖ / ➕ to change a rate.")
    rows = []
    # Default rate controls
    rows.append([
        InlineKeyboardButton("➖ Default", callback_data="adm:rate:default:-"),
        InlineKeyboardButton(f"Default {get_rate('default'):.2f}", callback_data="adm:rates"),
        InlineKeyboardButton("➕ Default", callback_data="adm:rate:default:+"),
    ])
    for sv in SERVICES:
        rows.append([
            InlineKeyboardButton(f"➖ {sv}", callback_data=f"adm:rate:{sv}:-"),
            InlineKeyboardButton(f"{sv} {get_rate(sv):.2f}", callback_data="adm:rates"),
            InlineKeyboardButton(f"➕ {sv}", callback_data=f"adm:rate:{sv}:+"),
        ])
    rows.append([InlineKeyboardButton("✏️ Set custom amount", callback_data="adm:ratecustom")])
    rows.append([InlineKeyboardButton("« Back", callback_data="adm:back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)

def save():
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, DB_FILE)

def get_user(tg_user):
    uid = str(tg_user.id)
    u = db["users"].get(uid)
    if not u:
        u = {"name": tg_user.full_name, "username": tg_user.username or "", "lang": "bn",
             "balance": 0.0, "nums": 0, "otps": 0, "day": str(date.today()), "dn": 0, "do": 0,
             "refs": 0, "ref_by": None, "banned": False}
        db["users"][uid] = u
    u["name"], u["username"] = tg_user.full_name, tg_user.username or ""
    if u["day"] != str(date.today()):
        u["day"], u["dn"], u["do"] = str(date.today()), 0, 0
    return u

def tr(u, key, **kw):
    s = T[u["lang"]][key]
    return s.format(**kw) if kw else s

def esc(s):
    return html.escape(str(s))

def is_admin(uid):
    return uid in ADMINS

# ==================== KEYBOARDS ====================
def main_menu(u, uid):
    t = T[u["lang"]]
    rows = [[t["get"]], [t["traffic"], t["twofa"]], [t["profile"], t["refer"]], [t["support"], t["lang"]]]
    if is_admin(uid):
        rows.append([t["admin"]])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def country_of(num):
    for p in sorted(PREFIXES, key=len, reverse=True):
        if num.startswith(p):
            return p, f"{PREFIXES[p][0]} {PREFIXES[p][1]}"
    return "", f"🌍 +{num[:3]}"

# ==================== OTP API ====================
# Response shape: {"data": {"docs": [{"_id","number","cli","message","createdAt"}, ...]}}, newest first
async def fetch_records():
    base = MESSAGES_URL or (TELEROUTEX_URL + "?" + urlencode({"apiKey": TELEROUTEX_API_KEY}))
    url = base + ("&" if "?" in base else "?") + "page=1"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json().get("data", {}).get("docs", [])

OTP_RE = re.compile(r"(?<!\d)(\d{3}[- ]\d{3}|\d{4,8})(?!\d)")
OTP_LONG_RE = re.compile(r"(?<!\d)(\d{4,10})(?!\d)")
seen_ids = set()

def parse_time(v):
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None

async def find_otp(number, since):
    """Newest SMS for exactly this number, created after `since`, not already used."""
    for rec in await fetch_records():
        if re.sub(r"\D", "", str(rec.get("number", ""))) != number or rec["_id"] in seen_ids:
            continue
        t = parse_time(rec.get("createdAt", ""))
        if t and t < since:
            continue
        text = rec.get("message", "")
        m = OTP_RE.search(text) or OTP_LONG_RE.search(text)
        if m:
            seen_ids.add(rec["_id"])
            return m.group(1), text
    return None, None

def parse_numbers(raw):
    """Accepts .txt or .csv: finds the phone-number column automatically, skips headers."""
    out = []
    for line in raw.splitlines():
        for field in re.split(r"[,;\t]", line):
            f = field.strip().strip('"').strip("'")
            if re.fullmatch(r"\+?[\d\s-]{8,18}", f):
                out.append(re.sub(r"\D", "", f))
                break
    return out

# ==================== HELPERS ====================
async def joined(bot, uid):
    try:
        m = await bot.get_chat_member(CHANNEL_ID, uid)
        return m.status in ("member", "administrator", "creator", "owner")
    except Exception:
        return True  # don't lock users out if bot can't check

async def send_join(update, u):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(u, "btn_join"), url=CHANNEL_LINK)],
                               [InlineKeyboardButton(tr(u, "btn_cont"), callback_data="chk")]])
    await update.effective_message.reply_text(tr(u, "join"), reply_markup=kb)

async def gate(update, ctx):
    """Returns user dict if allowed, else None (and replies)."""
    u = get_user(update.effective_user)
    uid = update.effective_user.id
    if u["banned"]:
        await update.effective_message.reply_text(tr(u, "banned"))
        return None
    if not is_admin(uid) and not await joined(ctx.bot, uid):
        await send_join(update, u)
        return None
    return u

# ==================== COMMANDS ====================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    new = uid not in db["users"]
    u = get_user(update.effective_user)
    if new and ctx.args and ctx.args[0].startswith("ref_"):
        ref = ctx.args[0][4:]
        if ref != uid and ref in db["users"]:
            u["ref_by"] = ref
            db["users"][ref]["refs"] += 1
            db["users"][ref]["balance"] += REFERRAL_PRICE
    save()
    u = await gate(update, ctx)
    if u:
        await update.message.reply_text(tr(u, "welcome"), parse_mode="HTML",
                                        reply_markup=main_menu(u, update.effective_user.id))

async def addnumbers(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    sid = ctx.args[0].upper() if ctx.args else ""
    if sid not in SERVICES:
        return await update.message.reply_text(
            "Usage: /addnumbers SERVICE N1 N2 ...\nExample: /addnumbers FACEBOOK 8801892345612\n"
            "Services: " + ", ".join(SERVICES))
    added = add_to_pool(parse_numbers("\n".join(ctx.args[1:])), sid)
    await update.message.reply_text(f"✅ Added {added} numbers to {sid}. {sid} pool: {len(db['pools'][sid])}")

def add_to_pool(nums, sid):
    """Add numbers to the pool of ONE service (WHATSAPP, FACEBOOK, ...)."""
    pool = db["pools"].setdefault(sid, [])
    have, added = set(pool), 0
    for n in nums:
        if 7 <= len(n) <= 15 and n not in have:
            pool.append(n)
            have.add(n)
            added += 1
    save()
    return added

def remove_from_pool(nums, sid):
    """Remove exact numbers from ONE service pool. Returns how many were removed."""
    pool = db["pools"].setdefault(sid, [])
    gone = set(nums) & set(pool)
    if gone:
        db["pools"][sid] = [n for n in pool if n not in gone]
        save()
    return len(gone)

def extract_numbers(raw):
    """Every phone-number-like token in a text/file (space, comma or line separated)."""
    return [re.sub(r"\D", "", x) for x in re.findall(r"\+?\d[\d-]{6,17}", raw)]

def detect_service(*texts):
    for t in texts:
        t = (t or "").upper()
        for sv in sorted(SERVICES, key=len, reverse=True):
            if sv in t:
                return sv
    return None

def pool_summary():
    return "\n".join(f"  {sv}: {len(db['pools'].get(sv, []))}" for sv in SERVICES)

async def on_document(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    doc = update.message.document
    if ctx.user_data.get("state") == "delnums":
        sid = ctx.user_data.pop("delsvc", None)
        ctx.user_data.pop("state")
        if sid in SERVICES:
            f = await doc.get_file()
            raw = (await f.download_as_bytearray()).decode("utf-8", "ignore")
            n = remove_from_pool(extract_numbers(raw), sid)
            await update.message.reply_text(f"🗑 Removed {n} numbers from {sid}. {sid} pool: {len(db['pools'][sid])}")
        return
    # service is taken from: caption > file name (e.g. facebook.txt) > service chosen in ADMIN PANEL
    sid = detect_service(update.message.caption, doc.file_name) or ctx.user_data.get("addsvc")
    if not sid:
        return await update.message.reply_text(
            "❓ Which service are these numbers for?\nOpen ADMIN PANEL and tap a service button, "
            "or name the file like facebook.txt, or add the service name as the file caption.")
    f = await doc.get_file()
    raw = (await f.download_as_bytearray()).decode("utf-8", "ignore")
    added = add_to_pool(parse_numbers(raw), sid)
    await update.message.reply_text(f"✅ Added {added} numbers to {sid}. {sid} pool: {len(db['pools'][sid])}")

async def admin_cmds(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    cmd = update.message.text.split()[0].lstrip("/").split("@")[0]
    a = ctx.args
    try:
        if cmd in ("ban", "unban"):
            db["users"][a[0]]["banned"] = cmd == "ban"
            save()
            await update.message.reply_text(f"✅ {cmd} {a[0]}")
        elif cmd == "addbal":
            db["users"][a[0]]["balance"] += float(a[1])
            save()
            await update.message.reply_text("✅ Balance updated")
        elif cmd == "setrate":
            # /setrate 0.5            -> default rate for all services
            # /setrate WHATSAPP 0.8   -> rate for one service
            key, val = ("default", a[0]) if len(a) == 1 else (a[0].upper(), a[1])
            if key != "default" and key not in SERVICES:
                raise ValueError
            val = float(val)
            if val < 0:
                raise ValueError
            db["rates"][key] = val
            save()
            await update.message.reply_text(f"✅ Rate for {key} = {val} BDT per OTP")
        elif cmd == "rates":
            lines = [f"default: {db['rates'].get('default', OTP_RATE)} BDT"]
            lines += [f"{sv}: {get_rate(sv)} BDT" for sv in SERVICES]
            await update.message.reply_text("💵 OTP rates\n" + "\n".join(lines))
        elif cmd == "setotpgroup":
            chat = update.effective_chat
            if a:
                target = int(a[0])
            elif chat.type in ("group", "supergroup"):
                target = chat.id
            else:
                return await update.message.reply_text(
                    "Send /setotpgroup inside your public OTP group (the bot must be admin there),\n"
                    "or here as: /setotpgroup -100xxxxxxxxxx")
            if target == SOURCE_GROUP_ID:
                return await update.message.reply_text("🛑 That is the source group. Use a different group.")
            link = ""
            try:
                link = await ctx.bot.export_chat_invite_link(target)
            except Exception:
                try:
                    c = await ctx.bot.get_chat(target)
                    link = f"https://t.me/{c.username}" if c.username else (c.invite_link or "")
                except Exception:
                    pass
            set_otp_group(target, link)
            fake = {"sid": "TEST SERVICE", "country": "🌍 Test"}
            try:
                await ctx.bot.send_message(target, public_text(fake, "8801700000000", "123456", "TestSender"), parse_mode="HTML")
                ok = "✅ Test notice posted."
            except Exception as ex:
                ok = f"⚠️ Saved, but cannot post there yet ({type(ex).__name__}: {ex}). Make the bot ADMIN in that group."
            await update.message.reply_text(
                f"✅ Public OTP group set: {target}\nView OTP link: {OTP_GROUP_LINK or '(none: set OTP_GROUP_LINK or give the bot invite rights)'}\n{ok}")
        elif cmd == "testgroup":
            if not OTP_GROUP_ID:
                return await update.message.reply_text("No public OTP group set. Send /setotpgroup inside the group.")
            fake = {"sid": "TEST SERVICE", "country": "🌍 Test"}
            try:
                await ctx.bot.send_message(OTP_GROUP_ID, public_text(fake, "8801700000000", "123456", "TestSender"),
                                           parse_mode="HTML")
                await update.message.reply_text(f"✅ Test message posted to the public OTP group ({OTP_GROUP_ID}).")
            except Exception as ex:
                await update.message.reply_text(
                    f"❌ Cannot post to the public OTP group ({OTP_GROUP_ID}):\n{type(ex).__name__}: {ex}\n\n"
                    "Fix: add the bot to that group as ADMIN and check OTP_GROUP_ID (starts with -100).")
        elif cmd == "delcountry":
            sid, code = a[0].upper(), re.sub(r"\D", "", a[1])
            if sid not in SERVICES or not code:
                raise ValueError
            n = remove_from_pool([x for x in db["pools"].get(sid, []) if x.startswith(code)], sid)
            await update.message.reply_text(f"🗑 Removed {n} numbers starting with {code} from {sid}. {sid} pool: {len(db['pools'][sid])}")
        elif cmd == "delnumbers":
            sid = a[0].upper()
            if sid not in SERVICES:
                raise ValueError
            n = remove_from_pool(extract_numbers(" ".join(a[1:])), sid)
            await update.message.reply_text(f"🗑 Removed {n} numbers from {sid}. {sid} pool: {len(db['pools'][sid])}")
        elif cmd == "addservice":
            name = clean_service(" ".join(a))
            if not name:
                raise ValueError
            if name in SERVICES:
                return await update.message.reply_text(f"{name} already exists.")
            add_service(name)
            await update.message.reply_text(f"✅ Service {name} added.")
        elif cmd == "delservice":
            name = clean_service(" ".join(a))
            if not name or name not in SERVICES:
                raise ValueError
            n = len(db["pools"].get(name, []))
            del_service(name)
            await update.message.reply_text(f"🗑 Service {name} removed ({n} numbers deleted).")
        elif cmd == "clearnumbers":
            sid = a[0].upper()
            if sid not in SERVICES:
                raise ValueError
            n = len(db["pools"].get(sid, []))
            db["pools"][sid] = []
            save()
            await update.message.reply_text(f"🗑 Cleared {n} numbers from {sid}")
        elif cmd == "assign":
            # moves numbers loaded before this update (old shared pool) into one service
            sid = a[0].upper()
            if sid not in SERVICES:
                raise ValueError
            old = list(db["pool"])
            db["pool"] = []
            added = add_to_pool(old, sid)
            await update.message.reply_text(f"✅ Moved {added} old numbers to {sid}")
        elif cmd == "broadcast":
            text = " ".join(a)
            ok = 0
            for uid in list(db["users"]):
                try:
                    await ctx.bot.send_message(int(uid), text)
                    ok += 1
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            await update.message.reply_text(f"📣 Sent to {ok} users")
    except (IndexError, KeyError, ValueError):
        await update.message.reply_text("Usage: /ban ID | /unban ID | /addbal ID AMOUNT | /setrate [SERVICE] AMOUNT | /rates | /delcountry SERVICE CODE | /delnumbers SERVICE N… | /addservice NAME | /delservice NAME | /clearnumbers SERVICE | /assign SERVICE | /broadcast TEXT")

# ==================== TEXT ROUTER ====================
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = await gate(update, ctx)
    if not u:
        return
    uid = update.effective_user.id
    text = update.message.text.strip()
    action = LABEL_ACTIONS.get(text)
    if action:
        ctx.user_data.pop("state", None)
        return await do_action(update, ctx, u, action)

    state = ctx.user_data.get("state")
    if state == "2fa":
        ctx.user_data.pop("state")
        try:
            totp = pyotp.TOTP(text.replace(" ", ""))
            code = totp.now()
            left = totp.interval - (int(__import__("time").time()) % totp.interval)
            await update.message.reply_text(tr(u, "code_2fa", c=code, s=left), parse_mode="HTML")
        except Exception:
            await update.message.reply_text(tr(u, "bad_2fa"), parse_mode="HTML")
    elif state == "delnums" and is_admin(uid):
        sid = ctx.user_data.pop("delsvc", None)
        ctx.user_data.pop("state")
        if sid not in SERVICES:
            return
        n = remove_from_pool(extract_numbers(text), sid)
        await update.message.reply_text(f"🗑 Removed {n} numbers from {sid}. {sid} pool: {len(db['pools'][sid])}")
    elif state == "newsvc" and is_admin(uid):
        ctx.user_data.pop("state")
        name = clean_service(text)
        if not name:
            return await update.message.reply_text("🛑 Invalid name. Use letters/numbers, 2-20 characters.")
        if name in SERVICES:
            return await update.message.reply_text(f"{name} already exists.")
        add_service(name)
        await update.message.reply_text(f"✅ Service {name} added. Open ADMIN PANEL → ➕ Add numbers: {name}.")
    elif state == "setrate" and is_admin(uid):
        ctx.user_data.pop("state")
        parts = text.strip().split()
        try:
            if len(parts) == 1:
                key, val = "default", float(parts[0])
            elif len(parts) == 2:
                key, val = parts[0].upper(), float(parts[1])
                if key not in SERVICES:
                    return await update.message.reply_text(f"🛑 Unknown service. Available: {', '.join(SERVICES)}")
            else:
                raise ValueError
            if val < 0:
                raise ValueError
            db["rates"][key] = val
            save()
            await update.message.reply_text(f"✅ Rate for <b>{key}</b> set to <b>{val:.2f}</b> BDT per OTP", parse_mode="HTML")
        except Exception:
            await update.message.reply_text("🛑 Invalid format.\nExamples:\n<code>0.80</code>\n<code>WHATSAPP 1.20</code>", parse_mode="HTML")
    elif state == "wd_amount":
        try:
            amt = float(text)
            assert MIN_WITHDRAW <= amt <= MAX_WITHDRAW and amt <= u["balance"]
        except Exception:
            return await update.message.reply_text(tr(u, "wd_bad_amount"))
        ctx.user_data.update(state="wd_number", wd_amount=amt)
        await update.message.reply_text(tr(u, "wd_number"))
    elif state == "wd_number":
        num = text.replace(" ", "")
        if not re.fullmatch(r"01\d{9}", num):
            return await update.message.reply_text(tr(u, "wd_bad_number"))
        amt, method = ctx.user_data.pop("wd_amount"), ctx.user_data.pop("wd_method")
        ctx.user_data.pop("state")
        if amt > u["balance"]:
            return await update.message.reply_text(tr(u, "wd_bad_amount"))
        u["balance"] -= amt
        db["wd_seq"] += 1
        wid = str(db["wd_seq"])
        db["withdraws"][wid] = {"uid": str(uid), "amount": amt, "method": method, "number": num, "status": "pending"}
        save()
        await update.message.reply_text(tr(u, "wd_sent", id=wid))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Paid", callback_data=f"wda:{wid}"),
                                    InlineKeyboardButton("❌ Reject", callback_data=f"wdr:{wid}")]])
        for a in ADMINS:
            try:
                await ctx.bot.send_message(
                    a, f"💸 Withdraw #{wid}\nUser: {esc(u['name'])} ({uid})\n{method}: {num}\nAmount: {amt} BDT",
                    reply_markup=kb)
            except Exception:
                pass

async def do_action(update, ctx, u, action):
    uid = update.effective_user.id
    m = update.message
    if action == "get":
        btns = [InlineKeyboardButton(sv, callback_data=f"svc:{sv}") for sv in SERVICES]
        kb = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        await m.reply_text(tr(u, "pick_service"), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    elif action == "traffic":
        top = sorted(db["users"].items(), key=lambda kv: kv[1]["otps"], reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = [f"{medals[i]} {esc(x['name'][:15])} — <code>{x['otps']}</code>" for i, (_, x) in enumerate(top)]
        await m.reply_text(tr(u, "board") + "\n".join(lines), parse_mode="HTML")
    elif action == "twofa":
        ctx.user_data["state"] = "2fa"
        await m.reply_text(tr(u, "ask_2fa"), parse_mode="HTML")
    elif action == "profile":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(u, "withdraw"), callback_data="wd")]])
        await m.reply_text(tr(u, "profile_msg", name=esc(u["name"]), uid=uid, bal=u["balance"], tn=u["dn"],
                              to=u["do"], an=u["nums"], ao=u["otps"]), parse_mode="HTML", reply_markup=kb)
    elif action == "refer":
        link = f"https://t.me/{ctx.bot.username}?start=ref_{uid}"
        await m.reply_text(tr(u, "refer_msg", n=u["refs"], r=u["refs"] * REFERRAL_PRICE, link=link),
                           parse_mode="HTML")
    elif action == "support":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(u, "help"), url=SUPPORT_LINK)],
                                   [InlineKeyboardButton(tr(u, "dev"), url=DEVELOPER_LINK)]])
        await m.reply_text(tr(u, "support_msg"), parse_mode="HTML", reply_markup=kb)
    elif action == "lang":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
                                    InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang:bn")]])
        await m.reply_text(tr(u, "lang_msg"), parse_mode="HTML", reply_markup=kb)
    elif action == "admin" and is_admin(uid):
        rows = [[InlineKeyboardButton("📊 Stats", callback_data="adm:stats")],
                [InlineKeyboardButton("💸 Pending withdrawals", callback_data="adm:pend")],
                [InlineKeyboardButton("💵 OTP Rates", callback_data="adm:rates")]]
        rows += [[InlineKeyboardButton(f"➕ Add numbers: {sv} ({len(db['pools'].get(sv, []))})",
                                       callback_data=f"adm:add:{sv}")] for sv in SERVICES]
        rows.append([InlineKeyboardButton("🗑 Remove numbers", callback_data="adm:rmmenu")])
        rows.append([InlineKeyboardButton("🆕 New service", callback_data="adm:newsvc"),
                     InlineKeyboardButton("🗑 Remove service", callback_data="adm:delmenu")])
        await m.reply_text("⚙️ <b>ADMIN PANEL</b>\n\nTap <b>➕ Add numbers</b> for a service, then send a .txt/.csv file.\n"
                           "Or: /addnumbers SERVICE N1 N2…  (or name the file facebook.txt)\n"
                           "/addservice NAME  /delservice NAME  /delnumbers SERVICE N…  /delcountry SERVICE CODE  /setotpgroup  /testgroup  /clearnumbers SERVICE  /assign SERVICE\n"
                           "/ban ID  /unban ID  /addbal ID AMT\n/setrate [SERVICE] AMT  /rates  /broadcast TEXT",
                           parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))

# ==================== OTP WAITING ====================
def fmt_num(num, fmt):
    """fmt 'cc' -> +8801892345612 ; 'nocc' -> 1892345612 (country prefix removed)."""
    if fmt == "nocc":
        p, _ = country_of(num)
        return num[len(p):] if p else num
    return "+" + num

def view_btn(u, num):
    """View OTP: opens the public OTP group when OTP_GROUP_LINK is set, otherwise checks the OTP in a popup."""
    if OTP_GROUP_LINK:
        return InlineKeyboardButton(tr(u, "view_otp"), url=OTP_GROUP_LINK)
    return InlineKeyboardButton(tr(u, "view_otp"), callback_data=f"vo:{num}")

def scanning_text(u, country, sid, mins, nums, fmt):
    """Build waiting message with numbers as <code> so user can tap to copy."""
    lines = [tr(u, "scanning", country=country, sid=sid, mins=mins), ""]
    for num in nums:
        flag = PREFIXES.get(country_of(num)[0], ("🌍", ""))[0]
        lines.append(f"{flag} <code>{esc(fmt_num(num, fmt))}</code>")
    return "\n".join(lines)

def batch_kb(u, sid, prefix, nums, fmt, first_num):
    """Keyboard: format / change / view / cancel (numbers are in the message text as copyable code)."""
    mark = lambda k: ("✅ " if fmt == k else "") + tr(u, k)
    rows = []
    rows.append([InlineKeyboardButton(mark("cc"), callback_data=f"fmt:{first_num}:cc"),
                 InlineKeyboardButton(mark("nocc"), callback_data=f"fmt:{first_num}:nocc")])
    rows.append([InlineKeyboardButton(tr(u, "change"), callback_data=f"chg:{sid}:{prefix}:{first_num}"),
                 view_btn(u, first_num)])
    rows.append([InlineKeyboardButton(tr(u, "cancel"), callback_data=f"cancel:{first_num}")])
    return InlineKeyboardMarkup(rows)

def num_kb(u, sid, prefix, num, fmt):
    """Kept for single-number fallback / compatibility."""
    return batch_kb(u, sid, prefix, [num], fmt, num)

ACTIVE = {}   # number -> {"uid","sid","country","msg","task"}

def persist_held(num, e):
    db["held"][num] = {"uid": e["uid"], "sid": e["sid"], "country": e["country"], "fmt": e["fmt"],
                       "prefix": e["prefix"], "since": e["since"].isoformat()}
    save()

def load_held():
    """After a restart, numbers the users changed away from keep delivering OTPs to them."""
    for num, h in db.get("held", {}).items():
        if num in ACTIVE or h["uid"] not in db["users"]:
            continue
        ACTIVE[num] = {"uid": h["uid"], "sid": h["sid"], "country": h["country"], "fmt": h.get("fmt", "cc"),
                       "prefix": h.get("prefix", ""), "msg": None, "moved": True, "count": 0, "task": None,
                       "since": parse_time(h["since"]) or datetime.now(timezone.utc)}
    if db.get("held"):
        log.info("Loaded %s old numbers that still deliver OTPs", len(db["held"]))

async def allocate(update, ctx, u, sid, prefix, replace=None):
    """Gives NUMBERS_PER_REQUEST numbers together in ONE message with stacked number buttons.
    Change Number releases the whole batch and allocates a fresh set into the same message."""
    q = update.callback_query
    uid = str(update.effective_user.id)
    old_msg = None
    if replace:
        old = ACTIVE.get(replace)
        if old and old["uid"] != uid:
            return
        if old:
            batch = old.get("batch")
            group = [n for n, e in ACTIVE.items()
                     if e["uid"] == uid and not e.get("count") and not e.get("moved")
                     and (n == replace or (batch and e.get("batch") == batch))]
            for n in group:
                e = ACTIVE[n]
                if e.get("msg") and old_msg is None:
                    old_msg = e["msg"]
                e["msg"] = None
                e["moved"] = True
                if e.get("task"):
                    e["task"].cancel()
                if KEEP_OLD_MINUTES > 0:
                    e["task"] = asyncio.create_task(wait_otp(ctx, n, KEEP_OLD_MINUTES * 60))
                else:
                    e["task"] = None
                    persist_held(n, e)
    pool = db["pools"].setdefault(sid, [])
    cands = [n for n in pool if n.startswith(prefix) and n not in ACTIVE]
    picks = random.sample(cands, min(NUMBERS_PER_REQUEST, len(cands)))
    if not picks:
        target = old_msg or q.message
        try:
            await target.edit_text(tr(u, "no_numbers"), parse_mode="HTML")
        except Exception:
            pass
        return
    fmt = u.get("numfmt", "cc")
    batch = str(time.time_ns())
    _, country = country_of(picks[0])
    text = scanning_text(u, country, sid, OTP_VALID_MINUTES, picks, fmt)
    kb = batch_kb(u, sid, prefix, picks, fmt, picks[0])
    msg = None
    if old_msg:
        try:
            await old_msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
            msg = old_msg
        except Exception as ex:
            log.warning("edit failed: %s", ex)
    if msg is None:
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            msg = q.message
        except Exception:
            msg = await q.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    for num in picks:
        pool.remove(num)
        u["nums"] += 1
        u["dn"] += 1
        _, country = country_of(num)
        entry = {"uid": uid, "sid": sid, "country": country, "msg": msg, "prefix": prefix, "fmt": fmt,
                 "batch": batch, "nums": list(picks), "since": datetime.now(timezone.utc) - timedelta(seconds=30)}
        entry["task"] = asyncio.create_task(wait_otp(ctx, num))
        ACTIVE[num] = entry
    save()

def hide_code(otp):
    d = str(otp)
    k = max(0, min(OTP_PUBLIC_VISIBLE_DIGITS, len(d)))
    return d[:k] + "\u2022" * (len(d) - k)

async def complete(ctx, num, otp, cli=None):
    """Forward an OTP to the user who holds `num`. The number stays active until its timer ends,
    so several OTPs on the same number are all forwarded. Used by both group and API modes."""
    e = ACTIVE.get(num)
    if not e:
        return
    first = e.get("count", 0) == 0
    e["count"] = e.get("count", 0) + 1
    e["last"] = otp
    u = db["users"][e["uid"]]
    rate = get_rate(e["sid"]) if (first or PAY_EVERY_OTP) else 0
    if rate or first:
        u["balance"] += rate
        u["otps"] += 1
        u["do"] += 1
    save()
    text = tr(u, "success", country=e["country"], sid=e["sid"], num=fmt_num(num, e["fmt"]),
              otp=esc(otp), rate=rate)
    try:
        # Always send OTP as a new message so the batch allocation message (with all numbers) stays visible
        if e.get("moved") or e.get("msg") is None:
            await ctx.bot.send_message(int(e["uid"]), text, parse_mode="HTML")
        else:
            await e["msg"].reply_text(text, parse_mode="HTML")
    except Exception as ex:
        log.warning("send failed: %s", ex)
    await post_public(ctx, e, num, otp, cli)

def public_text(e, num, otp, cli=None):
    """Public OTP group message: which service, country, masked number; the code is hidden."""
    now = datetime.now(timezone(timedelta(hours=TIMEZONE_HOURS))).strftime("%H:%M:%S")
    lines = ["🔔 <b>OTP RECEIVED</b>",
             f"📱 Service: <b>{esc(e['sid'])}</b>",
             f"🌍 Country: {esc(e['country'])}",
             f"📟 Number: <code>+{num[:-3]}•••</code>"]
    if cli:
        lines.append(f"📨 Sender: {esc(cli)}")
    lines += [f"🔑 Code: <code>{esc(hide_code(otp))}</code>", f"🕒 {now}"]
    return "\n".join(lines)

async def post_public(ctx, e, num, otp, cli=None):
    if not OTP_GROUP_ID:
        return                                # no public group set yet (/setotpgroup)
    if OTP_GROUP_ID == SOURCE_GROUP_ID:      # never post into the source group
        log.warning("OTP_GROUP_ID is the same as SOURCE_GROUP_ID: public post skipped")
        return
    try:
        await ctx.bot.send_message(OTP_GROUP_ID, public_text(e, num, otp, cli), parse_mode="HTML")
    except Exception as ex:
        log.warning("public OTP group post FAILED (%s): %s. Is the bot admin in the group and OTP_GROUP_ID correct?",
                    type(ex).__name__, ex)

async def wait_otp(ctx, num, timeout=None):
    """Waits for the timeout. The OTP itself is delivered by on_source (group mode) or api_poller (api mode)."""
    limit = timeout or POLL_TIMEOUT
    try:
        waited = 0
        while waited < limit:
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        e = ACTIVE.pop(num, None)
        if e and e.get("moved"):
            return                         # old number after Change Number: its message now shows another number
        # Timeout: do NOT message the user. Silently release the number and clear buttons.
        if e and e.get("msg"):
            try:
                await e["msg"].edit_reply_markup(reply_markup=None)
            except Exception:
                pass
    except asyncio.CancelledError:
        pass

async def api_check(app):
    """Fetch the newest SMS once and deliver any OTP for a waiting number. Raises if the API call fails."""
    recs = await fetch_records()
    for rec in recs:
        rid = rec.get("_id")
        if rid in seen_ids:
            continue
        num = re.sub(r"\D", "", str(rec.get("number", "")))
        e = ACTIVE.get(num)
        if not e:
            continue
        t = parse_time(rec.get("createdAt", ""))
        if t and t < e["since"]:
            continue
        text = rec.get("message", "")
        m = OTP_RE.search(text) or OTP_LONG_RE.search(text)
        if m:
            seen_ids.add(rid)
            await complete(app, num, m.group(1), rec.get("cli"))
            e2 = ACTIVE.get(num)
            if e2 and t:
                e2["since"] = t + timedelta(milliseconds=1)
                if e2.get("moved") and num in db["held"]:
                    persist_held(num, e2)

async def api_poller(app):
    """API mode: ONE request every POLL_SECONDS for all waiting numbers."""
    log.info("API mode: checking Teleroutex every %ss", POLL_SECONDS)
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if not ACTIVE:
            continue
        try:
            await api_check(app)
        except Exception as ex:
            log.warning("otp poll failed: %s", type(ex).__name__)   # no URL in the message: it contains the key

async def check_otp_group(app):
    if not OTP_GROUP_ID:
        log.warning("No public OTP group set yet: open your group and send /setotpgroup there (as admin)")
        return
    try:
        chat = await app.bot.get_chat(OTP_GROUP_ID)
        me = await app.bot.get_chat_member(OTP_GROUP_ID, app.bot.id)
        log.info("Public OTP group: %s (bot is %s)", chat.title, me.status)
        if me.status not in ("administrator", "creator", "owner", "member"):
            log.warning("Bot is not a member/admin of the public OTP group: posts will fail")
    except Exception as ex:
        log.warning("Cannot access the public OTP group (%s): %s. Check OTP_GROUP_ID and add the bot as admin.",
                    type(ex).__name__, ex)

async def post_init(app):
    load_held()
    await check_otp_group(app)
    if SMS_SOURCE == "api":
        app.bot_data["poller"] = asyncio.create_task(api_poller(app))

MASK_RE = re.compile(r"\+?(\d{3,})[*xX\u2022\u00b7.]{2,}(\d{2,})")

def match_active(text):
    """Returns (number, text_without_number). Handles full numbers and masked ones like +8801892****12."""
    flat = re.sub(r"[\s\-()]", "", text)
    for num in ACTIVE:                      # 1) full number visible
        if num in flat.replace("+", ""):
            return num, flat.replace("+", "").replace(num, " ")
    for m in MASK_RE.finditer(flat):        # 2) masked number: prefix + stars + last digits
        pre, suf = m.group(1), m.group(2)
        stars = len(m.group(0).lstrip("+")) - len(pre) - len(suf)
        for num in ACTIVE:                  # oldest waiting user first
            if num.startswith(pre) and num.endswith(suf) and len(num) == len(pre) + stars + len(suf):
                return num, text.replace(m.group(0), " ")
    return None, text

async def on_source(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reads SMS forwarded by Teleroutex into the source group/channel."""
    m = update.effective_message
    text = (m.text or m.caption or "") if m else ""
    if not text:
        return
    num, rest = match_active(text)
    if not num:
        return
    mt = OTP_RE.search(rest) or OTP_LONG_RE.search(rest)
    if mt:
        await complete(ctx, num, mt.group(1))

# ==================== CALLBACKS ====================
async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    data = q.data
    u = get_user(update.effective_user)
    # Answer only after handling callbacks that need a custom popup text
    # (copy: and vo:). Everything else gets a silent answer here.
    if not data.startswith(("vo:", "copy:")):
        await q.answer()

    # admin-only callbacks
    if data.startswith(("wda:", "wdr:", "adm:")):
        if not is_admin(uid):
            return
        if data == "adm:stats":
            tot = sum(x["otps"] for x in db["users"].values())
            return await q.message.reply_text(
                f"👥 Users: {len(db['users'])}\n📦 Pools:\n{pool_summary()}\n🔑 OTPs: {tot}\n"
                f"💵 Total balances: {sum(x['balance'] for x in db['users'].values()):.2f} BDT")
        if data == "adm:rates":
            text, kb = rates_text_and_kb()
            try:
                return await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                return await q.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        if data.startswith("adm:rate:"):
            # adm:rate:SERVICE:+  or  adm:rate:default:-
            parts = data.split(":")
            if len(parts) != 4:
                return
            _, _, key, direction = parts
            if key != "default" and key not in SERVICES:
                return
            step = 0.10
            cur = get_rate(key)
            new = max(0.0, round(cur + step, 2) if direction == "+" else round(cur - step, 2))
            db["rates"][key] = new
            save()
            text, kb = rates_text_and_kb()
            try:
                return await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                return
        if data == "adm:ratecustom":
            ctx.user_data["state"] = "setrate"
            return await q.message.reply_text(
                "✏️ Send rate like this:\n"
                "<code>0.80</code> → set default rate\n"
                "<code>WHATSAPP 1.20</code> → set one service\n"
                "Example: <code>FACEBOOK 0.50</code>", parse_mode="HTML")
        if data == "adm:back":
            return await q.edit_message_text("⚙️ Admin panel closed. Open it again from the main menu.")
        if data == "adm:rmmenu":
            kb = [[InlineKeyboardButton(f"🗑 {sv} ({len(db['pools'].get(sv, []))})", callback_data=f"adm:rm:{sv}")]
                  for sv in SERVICES]
            return await q.message.reply_text("Remove numbers from which service?", reply_markup=InlineKeyboardMarkup(kb))
        if data.startswith("adm:rm:"):
            sid = data[7:]
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🧹 Clear all ({len(db['pools'].get(sid, []))})", callback_data=f"adm:rmall:{sid}")],
                [InlineKeyboardButton("🌍 Remove a country", callback_data=f"adm:rmcc:{sid}")],
                [InlineKeyboardButton("✏️ Remove specific numbers", callback_data=f"adm:rmsel:{sid}")]])
            return await q.edit_message_text(f"<b>{esc(sid)}</b>: what do you want to remove?", parse_mode="HTML", reply_markup=kb)
        if data.startswith("adm:rmcc:"):
            sid = data[9:]
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            counts = {}
            for n in db["pools"].get(sid, []):
                p, name = country_of(n)
                counts[p] = (counts.get(p, (name, 0))[0], counts.get(p, (name, 0))[1] + 1)
            if not counts:
                return await q.edit_message_text(f"{sid} has no numbers.")
            btns = [InlineKeyboardButton(f"🗑 {nm} ({c})", callback_data=f"adm:rmccsel:{sid}:{p}")
                    for p, (nm, c) in sorted(counts.items(), key=lambda kv: -kv[1][1])]
            return await q.edit_message_text(f"<b>{esc(sid)}</b>: remove which country?", parse_mode="HTML",
                                             reply_markup=InlineKeyboardMarkup([btns[i:i + 2] for i in range(0, len(btns), 2)]))
        if data.startswith("adm:rmccsel:"):
            _, _, sid, p = data.split(":")
            cnt = sum(1 for n in db["pools"].get(sid, []) if country_of(n)[0] == p)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, remove", callback_data=f"adm:rmccyes:{sid}:{p}"),
                                        InlineKeyboardButton("❌ No", callback_data="adm:delno")]])
            return await q.edit_message_text(
                f"⚠️ Delete {cnt} numbers of this country from <b>{esc(sid)}</b>?", parse_mode="HTML", reply_markup=kb)
        if data.startswith("adm:rmccyes:"):
            _, _, sid, p = data.split(":")
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            gone = [n for n in db["pools"].get(sid, []) if country_of(n)[0] == p]
            n = remove_from_pool(gone, sid)
            return await q.edit_message_text(f"🗑 Removed {n} numbers from {sid}. {sid} pool: {len(db['pools'][sid])}")
        if data.startswith("adm:rmall:"):
            sid = data[10:]
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, clear all", callback_data=f"adm:rmallyes:{sid}"),
                                        InlineKeyboardButton("❌ No", callback_data="adm:delno")]])
            return await q.edit_message_text(
                f"⚠️ Delete all {len(db['pools'].get(sid, []))} numbers of <b>{esc(sid)}</b>?", parse_mode="HTML", reply_markup=kb)
        if data.startswith("adm:rmallyes:"):
            sid = data[13:]
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            n = len(db["pools"].get(sid, []))
            db["pools"][sid] = []
            save()
            return await q.edit_message_text(f"🗑 Deleted {n} numbers from {sid}.")
        if data.startswith("adm:rmsel:"):
            sid = data[10:]
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            ctx.user_data.update(state="delnums", delsvc=sid)
            return await q.edit_message_text(
                f"✏️ Send the numbers to remove from <b>{esc(sid)}</b> as text (one per line or separated by spaces) "
                "or as a .txt/.csv file.", parse_mode="HTML")
        if data == "adm:newsvc":
            ctx.user_data["state"] = "newsvc"
            return await q.message.reply_text(
                "✏️ Send the new service name (example: AGODA, IMO, GOOGLE).\nLetters/numbers, 2-20 characters.")
        if data == "adm:delmenu":
            kb = [[InlineKeyboardButton(f"🗑 {sv} ({len(db['pools'].get(sv, []))})", callback_data=f"adm:del:{sv}")]
                  for sv in SERVICES]
            return await q.message.reply_text("Which service do you want to remove?", reply_markup=InlineKeyboardMarkup(kb))
        if data.startswith("adm:del:"):
            sid = data[8:]
            if sid not in SERVICES:
                return await q.edit_message_text("Service not found.")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, remove", callback_data=f"adm:delyes:{sid}"),
                                        InlineKeyboardButton("❌ No", callback_data="adm:delno")]])
            return await q.edit_message_text(
                f"⚠️ Remove <b>{esc(sid)}</b> and its {len(db['pools'].get(sid, []))} numbers?",
                parse_mode="HTML", reply_markup=kb)
        if data.startswith("adm:delyes:"):
            sid = data[11:]
            if sid in SERVICES:
                del_service(sid)
                return await q.edit_message_text(f"🗑 {sid} removed.")
            return await q.edit_message_text("Service not found.")
        if data == "adm:delno":
            return await q.edit_message_text("Cancelled.")
        if data.startswith("adm:add:"):
            sid = data[8:]
            if sid not in SERVICES:
                return
            ctx.user_data["addsvc"] = sid
            return await q.message.reply_text(
                f"📥 Now send the .txt/.csv file with numbers for <b>{sid}</b>.\n"
                "Every file you send goes to this service until you pick another.", parse_mode="HTML")
        if data == "adm:pend":
            pend = {k: v for k, v in db["withdraws"].items() if v["status"] == "pending"}
            if not pend:
                return await q.message.reply_text("No pending withdrawals.")
            for wid, w in pend.items():
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Paid", callback_data=f"wda:{wid}"),
                                            InlineKeyboardButton("❌ Reject", callback_data=f"wdr:{wid}")]])
                await q.message.reply_text(f"#{wid} {w['method']} {w['number']} — {w['amount']} BDT (user {w['uid']})",
                                           reply_markup=kb)
            return
        wid = data.split(":")[1]
        w = db["withdraws"].get(wid)
        if not w or w["status"] != "pending":
            return await q.edit_message_text("Already handled.")
        target = db["users"][w["uid"]]
        if data.startswith("wda:"):
            w["status"] = "paid"
            note = "wd_paid"
        else:
            w["status"] = "rejected"
            target["balance"] += w["amount"]
            note = "wd_rejected"
        save()
        await q.edit_message_text(f"#{wid} → {w['status']}")
        try:
            await ctx.bot.send_message(int(w["uid"]), tr(target, note, id=wid))
        except Exception:
            pass
        return

    if u["banned"]:
        return
    if data == "chk":
        if await joined(ctx.bot, uid) or is_admin(uid):
            await q.message.delete()
            return await ctx.bot.send_message(uid, tr(u, "welcome"), parse_mode="HTML",
                                              reply_markup=main_menu(u, uid))
        return await q.answer(tr(u, "not_joined"), show_alert=True)

    if not is_admin(uid) and not await joined(ctx.bot, uid):
        return await send_join(update, u)

    if data.startswith("lang:"):
        u["lang"] = data[5:]
        save()
        await q.message.delete()
        await ctx.bot.send_message(uid, tr(u, "lang_set"), reply_markup=main_menu(u, uid))
    elif data.startswith("svc:"):
        sid = data[4:]
        if sid not in SERVICES:
            return await q.edit_message_text(tr(u, "no_numbers"), parse_mode="HTML")
        counts = {}
        for n in db["pools"].get(sid, []):
            p, _ = country_of(n)
            counts[p] = counts.get(p, 0) + 1
        if not counts:
            return await q.edit_message_text(tr(u, "no_numbers"), parse_mode="HTML")
        btns = []
        for p, c in sorted(counts.items(), key=lambda kv: -kv[1]):
            label = f"{PREFIXES[p][0]} {PREFIXES[p][1]} ({c})" if p in PREFIXES else f"🌍 Other ({c})"
            btns.append(InlineKeyboardButton(label, callback_data=f"cty:{sid}:{p}"))
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        await q.edit_message_text(tr(u, "pick_country", sid=sid), parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith(("cty:", "chg:")):
        kind, sid, prefix, *rest = data.split(":")
        await allocate(update, ctx, u, sid, prefix, replace=rest[0] if (kind == "chg" and rest) else None)
    elif data.startswith("fmt:"):
        _, num, fmt = data.split(":")
        u["numfmt"] = fmt
        save()
        e = ACTIVE.get(num)
        if e and e["uid"] == str(uid):
            batch = e.get("batch")
            nums = e.get("nums") or [num]
            for n in nums:
                if n in ACTIVE and ACTIVE[n].get("batch") == batch:
                    ACTIVE[n]["fmt"] = fmt
            text = scanning_text(u, e["country"], e["sid"], OTP_VALID_MINUTES, nums, fmt)
            kb = batch_kb(u, e["sid"], e["prefix"], nums, fmt, nums[0])
            try:
                await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    elif data.startswith("copy:"):
        # Numbers are now shown as <code> in the message — no popup needed
        await q.answer()
    elif data.startswith("vo:"):
        num = data[3:]
        e = ACTIVE.get(num)
        if not e or e["uid"] != str(uid):
            return await q.answer("⌛ This number is no longer active.", show_alert=True)
        if SMS_SOURCE == "api" and time.time() - e.get("vo_at", 0) >= 3:    # at most one fresh check / 3 s
            e["vo_at"] = time.time()
            try:
                await api_check(ctx.application)
            except Exception as ex:
                log.warning("view otp check failed: %s", type(ex).__name__)
        e = ACTIVE.get(num)
        if e and e.get("last"):
            await q.answer(f"🔑 OTP: {e['last']}", show_alert=True)
        else:
            await q.answer("⏳ No OTP yet. Please wait a moment...", show_alert=True)
    elif data.startswith("cancel:"):
        num = data[7:]
        e = ACTIVE.get(num)
        if e and e["uid"] == str(uid):
            batch = e.get("batch")
            group = [n for n, ent in ACTIVE.items()
                     if ent["uid"] == str(uid) and (n == num or (batch and ent.get("batch") == batch))]
            for n in group:
                ent = ACTIVE.pop(n, None)
                if ent and ent.get("task"):
                    ent["task"].cancel()
                db["held"].pop(n, None)
        await q.edit_message_text(tr(u, "cancelled"))
    elif data == "wd":
        if u["balance"] < MIN_WITHDRAW:
            return await q.message.reply_text(tr(u, "wd_min", bal=u["balance"], m=MIN_WITHDRAW), parse_mode="HTML")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌸 bKash", callback_data="wdm:bKash"),
                                    InlineKeyboardButton("🍊 Nagad", callback_data="wdm:Nagad")]])
        await q.message.reply_text(tr(u, "wd_gateway"), reply_markup=kb)
    elif data.startswith("wdm:"):
        ctx.user_data.update(state="wd_amount", wd_method=data[4:])
        await q.message.reply_text(tr(u, "wd_amount", mn=MIN_WITHDRAW, mx=MAX_WITHDRAW))

# ==================== MAIN ====================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addnumbers", addnumbers))
    app.add_handler(CommandHandler(["ban", "unban", "addbal", "broadcast", "setrate", "rates", "clearnumbers", "assign", "addservice", "delservice", "delnumbers", "delcountry", "testgroup", "setotpgroup"], admin_cmds))
    app.add_handler(CallbackQueryHandler(on_cb))
    if SMS_SOURCE == "group":
        app.add_handler(MessageHandler(filters.Chat(SOURCE_GROUP_ID) & (filters.TEXT | filters.CAPTION), on_source), group=-1)
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text))
    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
