import os
import re
import json
import html
import logging
import asyncio
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from supabase import create_client, Client


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "AmanM_12").strip().lstrip("@")

PORT = int(os.getenv("PORT", "10000"))

BOT_USERNAME = "VortexEarnBot"

RATE = Decimal("185")
REFERRAL_REWARD = Decimal("0.015")
REFERRAL_REWARD_ETB = REFERRAL_REWARD * RATE

MIN_WITHDRAW_FIRST = Decimal("0.12")
MIN_WITHDRAW_LATER = Decimal("0.50")

SUPPORT_USERNAME = "AmanM_12"

CHANNELS = [
    ("Sheger Tech", "@Sheger_tech1", "https://t.me/Sheger_tech1"),
    ("Ethio Vortex", "@EthioVortex1", "https://t.me/EthioVortex1"),
    ("Ethio Cash Flow", "@ethiocashflow", "https://t.me/ethiocashflow"),
    ("Aman Money Lab", "@AmanMoneyLab07", "https://t.me/AmanMoneyLab07"),
]

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("vortex-earn-bot")


# =========================================================
# SUPABASE
# =========================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# =========================================================
# IN-MEMORY USER STATES
# =========================================================

USER_STATES = {}


def get_state(user_id: int):
    return USER_STATES.setdefault(
        user_id,
        {
            "flow": None,
            "data": {},
        },
    )


def clear_state(user_id: int):
    USER_STATES.pop(user_id, None)


def set_flow(user_id: int, flow: str, data=None):
    USER_STATES[user_id] = {
        "flow": flow,
        "data": data or {},
    }


# =========================================================
# HELPERS
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def money(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt_usdt(value) -> str:
    return f"{money(value):.8f}".rstrip("0").rstrip(".")


def fmt_etb(value) -> str:
    return f"{money(value):.2f}"


def safe_text(value) -> str:
    return html.escape(str(value or ""))


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


def valid_name(value: str) -> bool:
    value = normalize_name(value)

    if len(value) < 2:
        return False

    if len(value) > 80:
        return False

    parts = value.split()

    if len(parts) < 2:
        return False

    for char in value:
        if char.isalpha() or char in " -'":
            continue
        return False

    return True


def valid_telebirr(value: str) -> bool:
    value = value.strip()

    return bool(
        re.fullmatch(r"(09|07)\d{8}", value)
    )


def valid_cbe_account(value: str) -> bool:
    value = value.strip()

    return bool(
        re.fullmatch(r"\d{14}", value)
    )


def valid_bybit_uid(value: str) -> bool:
    value = value.strip()

    return bool(
        re.fullmatch(r"\d{5,20}", value)
    )


def valid_bep20(value: str) -> bool:
    value = value.strip()

    return bool(
        re.fullmatch(r"0x[a-fA-F0-9]{40}", value)
    )


def user_display(user: dict) -> str:
    username = user.get("username")

    if username:
        return f"@{safe_text(username)}"

    return safe_text(user.get("telegram_id", ""))


def referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


# =========================================================
# DATABASE HELPERS
# =========================================================

def db_get_user(telegram_id: int):
    result = (
        supabase
        .table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def db_create_user(telegram_user, referred_by=None):
    username = telegram_user.username or ""

    payload = {
        "telegram_id": telegram_user.id,
        "username": username,
        "balance": 0,
        "balance_etb": 0,
        "referrals": 0,
        "referral_count": 0,
        "wallet": "",
        "withdrawal_count": 0,
        "total_withdrawn_usdt": 0,
        "total_withdrawn_etb": 0,
        "referred_by": referred_by,
        "currency": "USDT",
        "usdt_address": "",
        "telebirr_number": "",
        "bank_name": "",
        "bank_account": "",
        "last_withdrawal_method": "",
        "is_verified": False,
    }

    result = (
        supabase
        .table("users")
        .insert(payload)
        .execute()
    )

    return result.data[0] if result.data else None


def ensure_user(telegram_user, referred_by=None):
    existing = db_get_user(telegram_user.id)

    if existing:
        # Keep username updated.
        if existing.get("username") != (telegram_user.username or ""):
            try:
                supabase.table("users").update(
                    {
                        "username": telegram_user.username or ""
                    }
                ).eq(
                    "telegram_id", telegram_user.id
                ).execute()
            except Exception:
                pass

        return db_get_user(telegram_user.id), False

    return db_create_user(
        telegram_user,
        referred_by=referred_by,
    ), True


def wallet_data(user: dict) -> dict:
    raw = user.get("wallet")

    if not raw:
        return {}

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_wallet_json(user_id: int, data: dict):
    return (
        supabase
        .table("users")
        .update(
            {
                "wallet": json.dumps(
                    data,
                    ensure_ascii=False,
                )
            }
        )
        .eq("telegram_id", user_id)
        .execute()
    )


# =========================================================
# ASYNC DB WRAPPERS
# =========================================================

async def adb_get_user(user_id):
    return await asyncio.to_thread(
        db_get_user,
        user_id,
    )


async def adb_ensure_user(telegram_user, referred_by=None):
    return await asyncio.to_thread(
        ensure_user,
        telegram_user,
        referred_by,
    )


async def adb_update(table, values, column, value):
    def operation():
        return (
            supabase
            .table(table)
            .update(values)
            .eq(column, value)
            .execute()
        )

    return await asyncio.to_thread(operation)


async def adb_insert(table, values):
    def operation():
        return (
            supabase
            .table(table)
            .insert(values)
            .execute()
        )

    return await asyncio.to_thread(operation)


async def adb_select(table, columns="*", filters_data=None, limit=None):
    def operation():
        query = supabase.table(table).select(columns)

        for column, value in (filters_data or []):
            query = query.eq(column, value)

        if limit:
            query = query.limit(limit)

        return query.execute()

    return await asyncio.to_thread(operation)


# =========================================================
# KEYBOARDS
# =========================================================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Balance", "🎯 Tasks"],
        ["👥 Referral", "👛 Wallet"],
        ["💸 Withdraw", "🆘 Support"],
    ],
    resize_keyboard=True,
)


def back_keyboard():
    return ReplyKeyboardMarkup(
        [["🔙 Back"]],
        resize_keyboard=True,
    )


def join_keyboard():
    rows = []

    for name, username, url in CHANNELS:
        rows.append(
            [
                InlineKeyboardButton(
                    f"📢 {name}",
                    url=url,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "✅ Verify Membership",
                callback_data="verify_membership",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


def wallet_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💵 USDT",
                    callback_data="wallet_usdt",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏦 CBE",
                    callback_data="wallet_cbe",
                )
            ],
            [
                InlineKeyboardButton(
                    "📱 Telebirr",
                    callback_data="wallet_telebirr",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="wallet_back",
                )
            ],
        ]
    )


def wallet_usdt_keyboard(data: dict):
    bybit = data.get("bybit_uid")
    bep20 = data.get("bep20")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🟢 Bybit UID / Account ID"
                    + (" ✅" if bybit else ""),
                    callback_data="wallet_add_bybit",
                )
            ],
            [
                InlineKeyboardButton(
                    "🟢 BEP20 USDT Address"
                    + (" ✅" if bep20 else ""),
                    callback_data="wallet_add_bep20",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="wallet_back",
                )
            ],
        ]
    )


def saved_wallet_keyboard(method):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Edit",
                    callback_data=f"wallet_edit_{method}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="wallet_back",
                )
            ],
        ]
    )


def withdraw_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💵 USDT",
                    callback_data="withdraw_usdt",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏦 CBE",
                    callback_data="withdraw_cbe",
                )
            ],
            [
                InlineKeyboardButton(
                    "📱 Telebirr",
                    callback_data="withdraw_telebirr",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="withdraw_back",
                )
            ],
        ]
    )


# =========================================================
# MEMBERSHIP
# =========================================================

async def check_membership(bot, user_id: int):
    missing = []

    for name, username, url in CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=username,
                user_id=user_id,
            )

            if member.status in (
                "left",
                "kicked",
            ):
                missing.append(
                    (name, username, url)
                )

        except Exception as exc:
            logger.warning(
                "Membership check failed for %s: %s",
                username,
                exc,
            )

            missing.append(
                (name, username, url)
            )

    return missing


# =========================================================
# WELCOME
# =========================================================

async def show_join_screen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = (
        "🌪️ <b>Vortex Earn</b>\n\n"
        "🇪🇹 እንኳን ወደ Vortex Earn በደህና መጡ!\n\n"
        "💸 ስራዎችን ይስሩ፣ referrals ያግኙ፣ "
        "እና ያገኙትን ገንዘብ ያውጡ።\n\n"
        "👇 ለመጀመር ከታች ያሉትን channels ሁሉ Join ያድርጉ፣ "
        "ከዚያ Verify ይጫኑ።"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )


# =========================================================
# REFERRAL
# =========================================================

async def process_referral_reward(
    user: dict,
    context: ContextTypes.DEFAULT_TYPE,
):
    referred_by = user.get("referred_by")

    if not referred_by:
        return False

    try:
        referred_by = int(referred_by)
    except Exception:
        return False

    if referred_by == int(user["telegram_id"]):
        return False

    data = wallet_data(user)

    if data.get("_referral_rewarded") is True:
        return False

    referrer = await adb_get_user(referred_by)

    if not referrer:
        return False

    current_balance = money(referrer.get("balance"))
    current_etb = money(referrer.get("balance_etb"))
    referrals = int(referrer.get("referral_count") or 0)
    referrals_compat = int(referrer.get("referrals") or 0)

    new_balance = current_balance + REFERRAL_REWARD
    new_etb = current_etb + REFERRAL_REWARD_ETB

    await adb_update(
        "users",
        {
            "balance": str(new_balance),
            "balance_etb": str(new_etb),
            "referral_count": referrals + 1,
            "referrals": referrals_compat + 1,
        },
        "telegram_id",
        referred_by,
    )

    data["_referral_rewarded"] = True

    await save_wallet_json(
        int(user["telegram_id"]),
        data,
    )

    await context.bot.send_message(
        chat_id=referred_by,
        text=(
            "🎉 <b>New Referral!</b>\n\n"
            "👤 አንድ ሰው በእርስዎ referral link ተመዝግቧል።\n\n"
            f"💰 Reward: <b>{fmt_usdt(REFERRAL_REWARD)} USDT</b>\n"
            f"🇪🇹 Value: <b>{fmt_etb(REFERRAL_REWARD_ETB)} ETB</b>\n"
            f"💱 Rate: 1 USDT = {RATE} ETB"
        ),
        parse_mode=ParseMode.HTML,
    )

    return True


async def referral_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = await adb_get_user(
        update.effective_user.id
    )

    if not user:
        return

    count = int(
        user.get("referral_count")
        or user.get("referrals")
        or 0
    )

    link = referral_link(
        update.effective_user.id
    )

    text = (
        "👥 <b>Referral Center</b>\n\n"
        "👤 የጋበዛቸው ሰዎች: "
        f"<b>{count}</b>\n\n"
        f"🎁 ለአንድ successful referral: "
        f"<b>{fmt_usdt(REFERRAL_REWARD)} USDT</b>\n"
        f"🇪🇹 የዚህ ዋጋ: "
        f"<b>{fmt_etb(REFERRAL_REWARD_ETB)} ETB</b>\n\n"
        f"💱 Rate: <b>1 USDT = {RATE} ETB</b>\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>{safe_text(link)}</code>\n\n"
        "📌 ይህን link ለጓደኞችዎ ያጋሩ።"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👀 My Referrals",
                    callback_data="my_referrals",
                )
            ],
            [
                InlineKeyboardButton(
                    "📤 Share Referral",
                    url=(
                        "https://t.me/share/url?"
                        f"url={link}"
                    ),
                )
            ],
        ]
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def my_referrals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    result = await adb_select(
        "users",
        "*",
        [("referred_by", user_id)],
        limit=100,
    )

    users = result.data or []

    if not users:
        await query.edit_message_text(
            "👥 <b>My Referrals</b>\n\n"
            "እስካሁን የጋበዙት ሰው የለም።\n\n"
            "🔗 Referral link ይጋሩ እና የጋበዙትን "
            "ሰዎች እዚህ ያያሉ።",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [
        "👥 <b>My Referrals</b>",
        "",
    ]

    for index, item in enumerate(users, start=1):
        username = item.get("username")

        if username:
            name = f"@{safe_text(username)}"
        else:
            name = f"User {item.get('telegram_id')}"

        status = (
            "✅ Verified"
            if item.get("is_verified")
            else "⏳ Pending"
        )

        lines.append(
            f"{index}. {name} — {status}"
        )

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="referral_back",
                    )
                ]
            ]
        ),
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    clear_state(
        update.effective_user.id
    )

    referred_by = None

    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referred_by = int(
                    arg.replace("ref_", "", 1)
                )

                if referred_by == update.effective_user.id:
                    referred_by = None

            except ValueError:
                referred_by = None

    try:
        user, is_new = await adb_ensure_user(
            update.effective_user,
            referred_by=referred_by,
        )
    except Exception:
        logger.exception("User creation failed")

        await update.message.reply_text(
            "⚠️ የserver ችግር ተፈጥሯል።\n"
            "እባክዎ ትንሽ ቆይተው /start እንደገና ይሞክሩ።"
        )
        return

    missing = await check_membership(
        context.bot,
        update.effective_user.id,
    )

    if missing:
        await show_join_screen(
            update,
            context,
        )
        return

    # Successful verification.
    if not user.get("is_verified"):
        try:
            await adb_update(
                "users",
                {
                    "is_verified": True
                },
                "telegram_id",
                update.effective_user.id,
            )

            user["is_verified"] = True

        except Exception:
            logger.exception(
                "Could not mark user verified"
            )

    # Referral reward only after successful membership verification.
    if user.get("referred_by"):
        try:
            await process_referral_reward(
                user,
                context,
            )
        except Exception:
            logger.exception(
                "Referral reward failed"
            )

    await update.message.reply_text(
        "🎉 <b>Welcome to Vortex Earn!</b>\n\n"
        "✅ Account verified successfully.\n\n"
        "💸 አሁን ከታች ካሉት options የፈለጉትን ይምረጡ።",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# VERIFY
# =========================================================

async def verify_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer("Checking membership...")

    missing = await check_membership(
        context.bot,
        update.effective_user.id,
    )

    if missing:
        rows = []

        for name, username, url in missing:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"📢 Join {name}",
                        url=url,
                    )
                ]
            )

        rows.append(
            [
                InlineKeyboardButton(
                    "🔄 Verify Again",
                    callback_data="verify_membership",
                )
            ]
        )

        await query.edit_message_text(
            "❌ <b>Verification failed</b>\n\n"
            "እባክዎ ከታች ያሉትን channel(s) ሁሉ Join ያድርጉ።\n\n"
            "ከዚያ Verify Again ይጫኑ።",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )

        return

    user = await adb_get_user(
        update.effective_user.id
    )

    if user:
        try:
            await adb_update(
                "users",
                {
                    "is_verified": True
                },
                "telegram_id",
                update.effective_user.id,
            )

            user["is_verified"] = True

        except Exception:
            pass

        try:
            await process_referral_reward(
                user,
                context,
            )
        except Exception:
            logger.exception(
                "Referral reward failed"
            )

    await query.delete_message()

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=(
            "🎉 <b>Verification Successful!</b>\n\n"
            "✅ ሁሉንም channels ተቀላቅለዋል።\n"
            "🚀 አሁን መጠቀም ጀምረዋል!"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# BALANCE
# =========================================================

async def balance_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = await adb_get_user(
        update.effective_user.id
    )

    if not user:
        await update.message.reply_text(
            "⚠️ Account not found. /start ይጫኑ።"
        )
        return

    usdt = money(user.get("balance"))
    etb = money(user.get("balance_etb"))

    await update.message.reply_text(
        "💰 <b>Your Balance</b>\n\n"
        f"🪙 USDT: <b>{fmt_usdt(usdt)} USDT</b>\n"
        f"🇪🇹 ETB: <b>{fmt_etb(etb)} ETB</b>\n\n"
        f"💱 Rate: <b>1 USDT = {RATE} ETB</b>",
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# TASKS
# =========================================================

async def tasks_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📣 Promotion Service",
                    url=f"https://t.me/{SUPPORT_USERNAME}",
                )
            ]
        ]
    )

    await update.message.reply_text(
        "🎯 <b>Tasks & Promotion</b>\n\n"
        "📌 አሁን ላይ automated earning tasks እየተዘጋጁ ነው።\n\n"
        "📣 የTelegram channel, bot, product ወይም service "
        "promotion ማስራት ከፈለጉ ከAdmin ጋር ይገናኙ።\n\n"
        "💼 Commission-based promotion ይገኛል።",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================================================
# WALLET
# =========================================================

async def wallet_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "👛 <b>Wallet Center</b>\n\n"
        "ከታች ያለውን payment method ይምረጡ።\n"
        "✅ አንድ method ከተሞላ በኋላ ዳግም አዲስ አይጠይቅም።\n"
        "✏️ Edit በመጫን መረጃውን ማስተካከል ይችላሉ።",
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_keyboard(),
    )


async def wallet_usdt_page(
    query,
    user_id: int,
):
    user = await adb_get_user(user_id)

    data = wallet_data(user or {})

    bybit = data.get("bybit_uid")
    bep20 = data.get("bep20")

    text = "💵 <b>USDT Wallet</b>\n\n"

    if bybit:
        text += (
            f"🟢 Bybit UID: "
            f"<code>{safe_text(bybit)}</code>\n"
        )

    if bep20:
        text += (
            f"🟢 BEP20: "
            f"<code>{safe_text(bep20)}</code>\n"
        )

    if not bybit and not bep20:
        text += (
            "⚠️ እስካሁን USDT wallet አልተሞላም።\n\n"
            "ከታች አንዱን ይምረጡ።"
        )
    else:
        text += (
            "\n✏️ ያለውን መረጃ Edit ማድረግ "
            "ወይም ሌላ USDT method መጨመር ይችላሉ።"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_usdt_keyboard(data),
    )


async def wallet_cbe_page(
    query,
    user_id: int,
):
    user = await adb_get_user(user_id)

    data = wallet_data(user or {})

    account = data.get(
        "cbe_account"
    ) or user.get("bank_account")

    name = data.get(
        "cbe_name"
    ) or user.get("bank_name")

    if account and name:
        text = (
            "🏦 <b>CBE Wallet</b>\n\n"
            f"🔢 Account: <code>{safe_text(account)}</code>\n"
            f"👤 Name: <b>{safe_text(name)}</b>\n\n"
            "✅ Wallet saved."
        )

        keyboard = saved_wallet_keyboard(
            "cbe"
        )

    else:
        text = (
            "🏦 <b>CBE Wallet</b>\n\n"
            "⚠️ CBE account እስካሁን አልተሞላም።\n\n"
            "🔢 Account Number: 14 digits ብቻ\n"
            "👤 Full Name + Father Name"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ Add CBE Account",
                        callback_data="wallet_edit_cbe",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="wallet_back",
                    )
                ],
            ]
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def wallet_telebirr_page(
    query,
    user_id: int,
):
    user = await adb_get_user(user_id)

    data = wallet_data(user or {})

    phone = (
        data.get("telebirr_number")
        or user.get("telebirr_number")
    )

    name = data.get(
        "telebirr_name"
    )

    if phone and name:
        text = (
            "📱 <b>Telebirr Wallet</b>\n\n"
            f"📞 Number: <code>{safe_text(phone)}</code>\n"
            f"👤 Name: <b>{safe_text(name)}</b>\n\n"
            "✅ Wallet saved."
        )

        keyboard = saved_wallet_keyboard(
            "telebirr"
        )

    else:
        text = (
            "📱 <b>Telebirr Wallet</b>\n\n"
            "⚠️ Telebirr wallet እስካሁን አልተሞላም።\n\n"
            "📞 Phone: 10 digits ብቻ፣ 09 ወይም 07 የሚጀምር\n"
            "👤 Full Name + Father Name"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ Add Telebirr",
                        callback_data="wallet_edit_telebirr",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="wallet_back",
                    )
                ],
            ]
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================================================
# WALLET INPUT FLOWS
# =========================================================

async def begin_wallet_bybit(
    query,
):
    set_flow(
        query.from_user.id,
        "wallet_bybit",
    )

    await query.edit_message_text(
        "💵 <b>Bybit UID / Account ID</b>\n\n"
        "🔢 Bybit UID ያስገቡ።\n\n"
        "ምሳሌ: <code>12345678</code>\n\n"
        "🔙 Back ለመመለስ በታች ያለውን Back ይጫኑ።",
        parse_mode=ParseMode.HTML,
    )


async def begin_wallet_bep20(
    query,
):
    set_flow(
        query.from_user.id,
        "wallet_bep20",
    )

    await query.edit_message_text(
        "💵 <b>BEP20 USDT Address</b>\n\n"
        "የBEP20 USDT address ያስገቡ።\n\n"
        "ምሳሌ:\n"
        "<code>0x1234...abcd</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def begin_wallet_cbe(
    query,
):
    set_flow(
        query.from_user.id,
        "wallet_cbe_account",
    )

    await query.edit_message_text(
        "🏦 <b>CBE Account</b>\n\n"
        "🔢 14-digit CBE account number ያስገቡ።\n\n"
        "⚠️ ቁጥር ብቻ መሆን አለበት።",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


async def begin_wallet_telebirr(
    query,
):
    set_flow(
        query.from_user.id,
        "wallet_telebirr_phone",
    )

    await query.edit_message_text(
        "📱 <b>Telebirr</b>\n\n"
        "📞 10-digit Telebirr phone number ያስገቡ።\n\n"
        "ለምሳሌ: <code>0912345678</code>\n\n"
        "09 ወይም 07 መጀመር አለበት።",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


# =========================================================
# WITHDRAW
# =========================================================

async def get_withdraw_minimum(user):
    count = int(
        user.get("withdrawal_count") or 0
    )

    if count < 2:
        return MIN_WITHDRAW_FIRST

    return MIN_WITHDRAW_LATER


async def withdraw_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "💸 <b>Withdraw</b>\n\n"
        "የሚከፈልበትን method ይምረጡ።\n\n"
        "⚡ Manual payout — Admin በእጅ ይከፍላል።",
        parse_mode=ParseMode.HTML,
        reply_markup=withdraw_keyboard(),
    )


async def has_pending_withdrawal(user_id):
    result = await adb_select(
        "withdrawal_requests",
        "*",
        [
            ("user_id", user_id),
            ("status", "pending"),
        ],
        limit=1,
    )

    return bool(result.data)


async def get_payment_details(
    user: dict,
    method: str,
):
    data = wallet_data(user)

    if method == "usdt":
        # Do not silently choose one when both exist.
        bybit = data.get("bybit_uid")
        bep20 = data.get("bep20")

        if bybit and bep20:
            return {
                "multiple": True,
                "bybit": bybit,
                "bep20": bep20,
            }

        if bybit:
            return {
                "multiple": False,
                "type": "Bybit UID",
                "value": bybit,
            }

        if bep20:
            return {
                "multiple": False,
                "type": "BEP20",
                "value": bep20,
            }

        return None

    if method == "cbe":
        account = (
            data.get("cbe_account")
            or user.get("bank_account")
        )

        name = (
            data.get("cbe_name")
            or user.get("bank_name")
        )

        if account and name:
            return {
                "multiple": False,
                "type": "CBE",
                "value": (
                    f"Account: {account}\n"
                    f"Name: {name}"
                ),
            }

        return None

    if method == "telebirr":
        phone = (
            data.get("telebirr_number")
            or user.get("telebirr_number")
        )

        name = data.get("telebirr_name")

        if phone and name:
            return {
                "multiple": False,
                "type": "Telebirr",
                "value": (
                    f"Phone: {phone}\n"
                    f"Name: {name}"
                ),
            }

        return None

    return None


async def start_withdraw_method(
    query,
    method,
):
    user_id = query.from_user.id

    user = await adb_get_user(user_id)

    if not user:
        await query.answer(
            "Account not found.",
            show_alert=True,
        )
        return

    payment = await get_payment_details(
        user,
        method,
    )

    if not payment:
        await query.answer(
            "እባክዎ Wallet መጀመሪያ ይሙሉ።",
            show_alert=True,
        )
        return

    if payment.get("multiple"):
        set_flow(
            user_id,
            "withdraw_usdt_method",
        )

        await query.edit_message_text(
            "💵 <b>Choose USDT payout method</b>\n\n"
            "ሁለቱም wallet methods ተቀምጠዋል። "
            "የሚጠቀሙበትን ይምረጡ።",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Bybit UID",
                            callback_data="withdraw_usdt_bybit",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🟢 BEP20",
                            callback_data="withdraw_usdt_bep20",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Back",
                            callback_data="withdraw_back",
                        )
                    ],
                ]
            ),
        )

        return

    minimum = await get_withdraw_minimum(
        user
    )

    balance = money(user.get("balance"))

    if balance < minimum:
        await query.answer(
            f"Minimum withdrawal is {fmt_usdt(minimum)} USDT.",
            show_alert=True,
        )
        return

    set_flow(
        user_id,
        "withdraw_amount",
        {
            "method": method,
            "payment_type": payment["type"],
            "payment_value": payment["value"],
            "minimum": str(minimum),
        },
    )

    await query.edit_message_text(
        "💸 <b>Enter Withdrawal Amount</b>\n\n"
        f"💰 Available: <b>{fmt_usdt(balance)} USDT</b>\n"
        f"🔻 Minimum: <b>{fmt_usdt(minimum)} USDT</b>\n\n"
        "የሚያወጡትን USDT amount ያስገቡ።",
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# WITHDRAW CONFIRMATION
# =========================================================

async def show_withdraw_confirmation(
    update,
    context,
    amount: Decimal,
):
    state = get_state(
        update.effective_user.id
    )

    data = state.get("data", {})

    etb = amount * RATE

    text = (
        "🔎 <b>Confirm Withdrawal</b>\n\n"
        f"💵 Amount: <b>{fmt_usdt(amount)} USDT</b>\n"
        f"🇪🇹 Value: <b>{fmt_etb(etb)} ETB</b>\n"
        f"💱 Rate: <b>1 USDT = {RATE} ETB</b>\n\n"
        f"💳 Method: <b>{safe_text(data.get('payment_type'))}</b>\n"
        f"<pre>{safe_text(data.get('payment_value'))}</pre>\n\n"
        "እርግጠኛ ከሆኑ Confirm ይጫኑ።"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Confirm",
                        callback_data="withdraw_confirm",
                    ),
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="withdraw_cancel",
                    ),
                ]
            ]
        ),
    )


async def create_withdrawal(
    query,
    context,
):
    user_id = query.from_user.id

    state = get_state(user_id)
    data = state.get("data", {})

    try:
        amount = Decimal(
            data.get("amount", "0")
        )
    except Exception:
        await query.answer(
            "Invalid amount.",
            show_alert=True,
        )
        return

    user = await adb_get_user(user_id)

    if not user:
        return

    balance = money(user.get("balance"))

    if amount <= 0 or amount > balance:
        await query.answer(
            "Insufficient balance.",
            show_alert=True,
        )
        return

    minimum = money(
        data.get("minimum")
    )

    if amount < minimum:
        await query.answer(
            f"Minimum is {fmt_usdt(minimum)} USDT.",
            show_alert=True,
        )
        return

    if await has_pending_withdrawal(user_id):
        await query.answer(
            "You already have a pending withdrawal.",
            show_alert=True,
        )
        clear_state(user_id)
        return

    method = data.get("method")

    payment_details = (
        f"{data.get('payment_type')}: "
        f"{data.get('payment_value')}"
    )

    request = {
        "user_id": user_id,
        "amount_usdt": str(amount),
        "amount_etb": str(amount * RATE),
        "method": method,
        "payment_details": payment_details,
        "status": "pending",
        "created_at": now_iso(),
    }

    try:
        result = await adb_insert(
            "withdrawal_requests",
            request,
        )
    except Exception:
        logger.exception(
            "Withdrawal insert failed"
        )

        await query.answer(
            "Server error. Please try again.",
            show_alert=True,
        )
        return

    clear_state(user_id)

    await query.edit_message_text(
        "✅ <b>Withdrawal Request Submitted</b>\n\n"
        f"💵 Amount: <b>{fmt_usdt(amount)} USDT</b>\n"
        f"🇪🇹 Value: <b>{fmt_etb(amount * RATE)} ETB</b>\n"
        f"💳 Method: <b>{safe_text(method.upper())}</b>\n\n"
        "⏳ Status: <b>Pending</b>\n\n"
        "👨‍💼 Admin በእጅ ከፍሎ ከጨረሰ በኋላ "
        "balance ይቀነሳል።",
        parse_mode=ParseMode.HTML,
    )

    # Notify admin.
    if ADMIN_ID:
        username_text = (
            f"@{user['username']}"
            if user.get("username")
            else "No username"
        )

        request_id = (
            result.data[0].get("id")
            if result.data
            else "N/A"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🔔 <b>NEW WITHDRAWAL</b>\n\n"
                f"🆔 Request: <code>{request_id}</code>\n"
                f"👤 User: {safe_text(username_text)}\n"
                f"🆔 Telegram ID: <code>{user_id}</code>\n\n"
                f"💵 Amount: <b>{fmt_usdt(amount)} USDT</b>\n"
                f"🇪🇹 ETB: <b>{fmt_etb(amount * RATE)} ETB</b>\n"
                f"💳 Method: <b>{safe_text(method.upper())}</b>\n\n"
                f"<pre>{safe_text(payment_details)}</pre>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Approve",
                            callback_data=f"admin_approve_{request_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ Reject",
                            callback_data=f"admin_reject_{request_id}",
                        ),
                    ]
                ]
            ),
        )


# =========================================================
# WITHDRAW HISTORY
# =========================================================

async def history_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    result = await adb_select(
        "withdrawal_requests",
        "*",
        [
            (
                "user_id",
                update.effective_user.id,
            )
        ],
        limit=20,
    )

    rows = result.data or []

    if not rows:
        await update.message.reply_text(
            "📜 <b>Withdrawal History</b>\n\n"
            "እስካሁን withdrawal የለም።",
            parse_mode=ParseMode.HTML,
        )
        return

    # Sort newest first locally.
    rows.sort(
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )

    lines = [
        "📜 <b>Withdrawal History</b>",
        "",
    ]

    for item in rows[:15]:
        status = item.get("status", "unknown")

        icon = {
            "pending": "⏳",
            "approved": "✅",
            "rejected": "❌",
        }.get(status, "ℹ️")

        amount = fmt_usdt(
            item.get("amount_usdt")
        )

        method = str(
            item.get("method", "")
        ).upper()

        lines.append(
            f"{icon} <b>{amount} USDT</b> — "
            f"{safe_text(method)} — "
            f"{safe_text(status.title())}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "⛔ Access denied."
        )
        return

    result = await adb_select(
        "withdrawal_requests",
        "*",
        [
            ("status", "pending")
        ],
        limit=50,
    )

    requests = result.data or []

    lines = [
        "👨‍💼 <b>Admin Dashboard</b>",
        "",
        f"⏳ Pending withdrawals: <b>{len(requests)}</b>",
        "",
    ]

    if not requests:
        lines.append(
            "✅ No pending withdrawals."
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def admin_approve(
    query,
    context,
    request_id: int,
):
    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "Access denied.",
            show_alert=True,
        )
        return

    result = await adb_select(
        "withdrawal_requests",
        "*",
        [("id", request_id)],
        limit=1,
    )

    if not result.data:
        await query.answer(
            "Request not found.",
            show_alert=True,
        )
        return

    request = result.data[0]

    if request.get("status") != "pending":
        await query.answer(
            "This request was already processed.",
            show_alert=True,
        )
        return

    user_id = int(
        request["user_id"]
    )

    user = await adb_get_user(user_id)

    if not user:
        await query.answer(
            "User not found.",
            show_alert=True,
        )
        return

    amount = money(
        request.get("amount_usdt")
    )

    balance = money(
        user.get("balance")
    )

    if amount > balance:
        await query.answer(
            "User balance is insufficient.",
            show_alert=True,
        )
        return

    etb = money(
        request.get("amount_etb")
    )

    new_balance = balance - amount
    current_etb = money(
        user.get("balance_etb")
    )
    new_etb = max(
        Decimal("0"),
        current_etb - etb,
    )

    withdrawal_count = int(
        user.get("withdrawal_count") or 0
    )

    total_usdt = money(
        user.get("total_withdrawn_usdt")
    )

    total_etb = money(
        user.get("total_withdrawn_etb")
    )

    try:
        await adb_update(
            "users",
            {
                "balance": str(new_balance),
                "balance_etb": str(new_etb),
                "withdrawal_count": withdrawal_count + 1,
                "total_withdrawn_usdt": str(
                    total_usdt + amount
                ),
                "total_withdrawn_etb": str(
                    total_etb + etb
                ),
                "last_withdrawal_method": request.get(
                    "method"
                ),
            },
            "telegram_id",
            user_id,
        )

        await adb_update(
            "withdrawal_requests",
            {
                "status": "approved",
                "processed_at": now_iso(),
            },
            "id",
            request_id,
        )

    except Exception:
        logger.exception(
            "Approval failed"
        )

        await query.answer(
            "Database error.",
            show_alert=True,
        )
        return

    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await query.answer(
        "Approved successfully.",
        show_alert=False,
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "✅ <b>Withdrawal Approved</b>\n\n"
            f"💵 Amount: <b>{fmt_usdt(amount)} USDT</b>\n"
            f"🇪🇹 Value: <b>{fmt_etb(etb)} ETB</b>\n\n"
            "🎉 Payment has been approved."
        ),
        parse_mode=ParseMode.HTML,
    )


async def admin_reject(
    query,
    context,
    request_id: int,
):
    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "Access denied.",
            show_alert=True,
        )
        return

    result = await adb_select(
        "withdrawal_requests",
        "*",
        [("id", request_id)],
        limit=1,
    )

    if not result.data:
        await query.answer(
            "Request not found.",
            show_alert=True,
        )
        return

    request = result.data[0]

    if request.get("status") != "pending":
        await query.answer(
            "Already processed.",
            show_alert=True,
        )
        return

    try:
        await adb_update(
            "withdrawal_requests",
            {
                "status": "rejected",
                "processed_at": now_iso(),
            },
            "id",
            request_id,
        )

    except Exception:
        logger.exception(
            "Reject failed"
        )

        await query.answer(
            "Database error.",
            show_alert=True,
        )
        return

    await query.edit_message_reply_markup(
        reply_markup=None
    )

    await query.answer(
        "Rejected.",
        show_alert=False,
    )

    await context.bot.send_message(
        chat_id=int(request["user_id"]),
        text=(
            "❌ <b>Withdrawal Rejected</b>\n\n"
            f"💵 Amount: <b>"
            f"{fmt_usdt(request.get('amount_usdt'))} USDT"
            f"</b>\n\n"
            "ℹ️ Your balance was not deducted."
        ),
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# SUPPORT
# =========================================================

async def support_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🆘 <b>Support</b>\n\n"
        "ማንኛውም ጥያቄ ወይም ችግር ካለዎት "
        "ከAdmin ጋር ይገናኙ።\n\n"
        "👨‍💻 Admin: @"
        + safe_text(SUPPORT_USERNAME),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💬 Contact Admin",
                        url=f"https://t.me/{SUPPORT_USERNAME}",
                    )
                ]
            ]
        ),
    )


# =========================================================
# BACK
# =========================================================

async def back_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    clear_state(
        update.effective_user.id
    )

    await update.message.reply_text(
        "↩️ ወደ Main Menu ተመልሰዋል።",
        reply_markup=MAIN_MENU,
    )


# =========================================================
# TEXT INPUT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Main menu.
    if text == "💰 Balance":
        await balance_page(update, context)
        return

    if text == "🎯 Tasks":
        await tasks_page(update, context)
        return

    if text == "👥 Referral":
        await referral_page(update, context)
        return

    if text == "👛 Wallet":
        await wallet_page(update, context)
        return

    if text == "💸 Withdraw":
        await withdraw_page(update, context)
        return

    if text == "🆘 Support":
        await support_page(update, context)
        return

    if text == "🔙 Back":
        await back_handler(update, context)
        return

    state = get_state(user_id)

    flow = state.get("flow")
    data = state.get("data", {})

    # -----------------------------------------------------
    # BYBIT UID
    # -----------------------------------------------------

    if flow == "wallet_bybit":
        if not valid_bybit_uid(text):
            await update.message.reply_text(
                "❌ <b>Invalid Bybit UID</b>\n\n"
                "እባክዎ ትክክለኛ numeric Bybit UID "
                "ያስገቡ።",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        user = await adb_get_user(user_id)
        wallet = wallet_data(user or {})

        wallet["bybit_uid"] = text

        await save_wallet_json(
            user_id,
            wallet,
        )

        await update.message.reply_text(
            "✅ <b>Bybit UID Saved</b>\n\n"
            f"🟢 UID: <code>{safe_text(text)}</code>\n\n"
            "👛 Wallet → USDT ብለው ሲገቡ "
            "ይህን መረጃ ያያሉ።",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        clear_state(user_id)
        return

    # -----------------------------------------------------
    # BEP20
    # -----------------------------------------------------

    if flow == "wallet_bep20":
        if not valid_bep20(text):
            await update.message.reply_text(
                "❌ <b>Invalid BEP20 Address</b>\n\n"
                "የBEP20 USDT address ትክክለኛ format "
                "ይኖረው ዘንድ ያስገቡ።\n\n"
                "ምሳሌ: 0x + 40 hexadecimal characters",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        user = await adb_get_user(user_id)
        wallet = wallet_data(user or {})

        wallet["bep20"] = text

        await save_wallet_json(
            user_id,
            wallet,
        )

        await adb_update(
            "users",
            {
                "usdt_address": text
            },
            "telegram_id",
            user_id,
        )

        await update.message.reply_text(
            "✅ <b>BEP20 Wallet Saved</b>\n\n"
            f"🟢 Address:\n<code>{safe_text(text)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        clear_state(user_id)
        return

    # -----------------------------------------------------
    # CBE ACCOUNT
    # -----------------------------------------------------

    if flow == "wallet_cbe_account":
        if not valid_cbe_account(text):
            await update.message.reply_text(
                "❌ <b>Invalid CBE Account</b>\n\n"
                "CBE account number <b>14 digits</b> ብቻ "
                "መሆን አለበት።\n\n"
                "ምንም spaces ወይም letters አይኖሩትም።",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        set_flow(
            user_id,
            "wallet_cbe_name",
            {
                "account": text
            },
        )

        await update.message.reply_text(
            "👤 <b>CBE Account Name</b>\n\n"
            "የራስዎን <b>ሙሉ ስም</b> እና "
            "<b>የአባት ስም</b> ያስገቡ።\n\n"
            "ምሳሌ: <code>Aman Getachew</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    # -----------------------------------------------------
    # CBE NAME
    # -----------------------------------------------------

    if flow == "wallet_cbe_name":
        if not valid_name(text):
            await update.message.reply_text(
                "❌ <b>Invalid Name</b>\n\n"
                "ሙሉ ስም + የአባት ስም በትክክል ያስገቡ።\n"
                "Letters እና spaces ብቻ ይጠቀሙ።",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        account = data.get("account")

        user = await adb_get_user(user_id)
        wallet = wallet_data(user or {})

        wallet["cbe_account"] = account
        wallet["cbe_name"] = normalize_name(text)

        await save_wallet_json(
            user_id,
            wallet,
        )

        await adb_update(
            "users",
            {
                "bank_account": account,
                "bank_name": normalize_name(text),
            },
            "telegram_id",
            user_id,
        )

        await update.message.reply_text(
            "✅ <b>CBE Wallet Saved</b>\n\n"
            f"🔢 Account: <code>{safe_text(account)}</code>\n"
            f"👤 Name: <b>{safe_text(normalize_name(text))}</b>\n\n"
            "✏️ ከዚህ በኋላ Wallet ሲገቡ "
            "እንደገና ሙላ አይሉዎትም፤ Edit ብቻ ይጠቀሙ።",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        clear_state(user_id)
        return

    # -----------------------------------------------------
    # TELEBIRR PHONE
    # -----------------------------------------------------

    if flow == "wallet_telebirr_phone":
        if not valid_telebirr(text):
            await update.message.reply_text(
                "❌ <b>Invalid Telebirr Number</b>\n\n"
                "ቁጥሩ <b>10 digits</b> ብቻ መሆን አለበት።\n"
                "እና <b>09</b> ወይም <b>07</b> መጀመር አለበት።\n\n"
                "ምሳሌ: <code>0912345678</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        set_flow(
            user_id,
            "wallet_telebirr_name",
            {
                "phone": text
            },
        )

        await update.message.reply_text(
            "👤 <b>Telebirr Account Name</b>\n\n"
            "የራስዎን <b>ሙሉ ስም</b> እና "
            "<b>የአባት ስም</b> ያስገቡ።\n\n"
            "ምሳሌ: <code>Aman Getachew</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(),
        )
        return

    # -----------------------------------------------------
    # TELEBIRR NAME
    # -----------------------------------------------------

    if flow == "wallet_telebirr_name":
        if not valid_name(text):
            await update.message.reply_text(
                "❌ <b>Invalid Name</b>\n\n"
                "ሙሉ ስም + የአባት ስም ያስገቡ።",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        phone = data.get("phone")

        user = await adb_get_user(user_id)
        wallet = wallet_data(user or {})

        wallet["telebirr_number"] = phone
        wallet["telebirr_name"] = normalize_name(text)

        await save_wallet_json(
            user_id,
            wallet,
        )

        await adb_update(
            "users",
            {
                "telebirr_number": phone,
            },
            "telegram_id",
            user_id,
        )

        await update.message.reply_text(
            "✅ <b>Telebirr Wallet Saved</b>\n\n"
            f"📞 Number: <code>{safe_text(phone)}</code>\n"
            f"👤 Name: <b>{safe_text(normalize_name(text))}</b>\n\n"
            "✏️ ከዚህ በኋላ Edit ብቻ በማድረግ "
            "መረጃውን ይቀይሩ።",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        clear_state(user_id)
        return

    # -----------------------------------------------------
    # WITHDRAW AMOUNT
    # -----------------------------------------------------

    if flow == "withdraw_amount":
        try:
            amount = Decimal(text)
        except InvalidOperation:
            await update.message.reply_text(
                "❌ ትክክለኛ USDT amount ያስገቡ።",
                reply_markup=back_keyboard(),
            )
            return

        if amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0.",
                reply_markup=back_keyboard(),
            )
            return

        minimum = money(
            data.get("minimum")
        )

        if amount < minimum:
            await update.message.reply_text(
                f"❌ Minimum withdrawal: "
                f"<b>{fmt_usdt(minimum)} USDT</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        user = await adb_get_user(user_id)

        if not user:
            return

        balance = money(
            user.get("balance")
        )

        if amount > balance:
            await update.message.reply_text(
                f"❌ Insufficient balance.\n\n"
                f"Available: <b>{fmt_usdt(balance)} USDT</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(),
            )
            return

        data["amount"] = str(amount)

        set_flow(
            user_id,
            "withdraw_confirm",
            data,
        )

        await show_withdraw_confirmation(
            update,
            context,
            amount,
        )

        return

    # -----------------------------------------------------
    # WITHDRAW USDT METHOD
    # -----------------------------------------------------

    if flow == "withdraw_usdt_method":
        await update.message.reply_text(
            "💵 ከላይ ያለውን Bybit ወይም BEP20 option ይምረጡ።",
            reply_markup=back_keyboard(),
        )
        return

    # Unknown input.
    await update.message.reply_text(
        "ℹ️ እባክዎ ከMenu ያለውን option ይምረጡ።",
        reply_markup=MAIN_MENU,
    )


# =========================================================
# CALLBACKS
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # -----------------------------
    # WALLET
    # -----------------------------

    if data == "wallet_back":
        clear_state(user_id)

        await query.edit_message_text(
            "👛 <b>Wallet Center</b>\n\n"
            "Payment method ይምረጡ።",
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_keyboard(),
        )
        return

    if data == "wallet_usdt":
        clear_state(user_id)

        await wallet_usdt_page(
            query,
            user_id,
        )
        return

    if data == "wallet_cbe":
        clear_state(user_id)

        await wallet_cbe_page(
            query,
            user_id,
        )
        return

    if data == "wallet_telebirr":
        clear_state(user_id)

        await wallet_telebirr_page(
            query,
            user_id,
        )
        return

    if data == "wallet_add_bybit":
        await begin_wallet_bybit(query)
        return

    if data == "wallet_add_bep20":
        await begin_wallet_bep20(query)
        return

    if data == "wallet_edit_cbe":
        await begin_wallet_cbe(query)
        return

    if data == "wallet_edit_telebirr":
        await begin_wallet_telebirr(query)
        return

    if data == "wallet_edit_bybit":
        await begin_wallet_bybit(query)
        return

    if data == "wallet_edit_bep20":
        await begin_wallet_bep20(query)
        return

    # -----------------------------
    # REFERRAL
    # -----------------------------

    if data == "my_referrals":
        await my_referrals(
            update,
            context,
        )
        return

    if data == "referral_back":
        await query.delete_message()

        await context.bot.send_message(
            chat_id=user_id,
            text="👥 Referral Center",
            reply_markup=MAIN_MENU,
        )
        return

    # -----------------------------
    # WITHDRAW
    # -----------------------------

    if data == "withdraw_back":
        clear_state(user_id)

        await query.edit_message_text(
            "💸 <b>Withdraw</b>\n\n"
            "Payment method ይምረጡ።",
            parse_mode=ParseMode.HTML,
            reply_markup=withdraw_keyboard(),
        )
        return

    if data == "withdraw_usdt":
        await start_withdraw_method(
            query,
            "usdt",
        )
        return

    if data == "withdraw_cbe":
        await start_withdraw_method(
            query,
            "cbe",
        )
        return

    if data == "withdraw_telebirr":
        await start_withdraw_method(
            query,
            "telebirr",
        )
        return

    if data in (
        "withdraw_usdt_bybit",
        "withdraw_usdt_bep20",
    ):
        user = await adb_get_user(user_id)

        wallet = wallet_data(user or {})

        if data == "withdraw_usdt_bybit":
            payment_type = "Bybit UID"
            payment_value = wallet.get(
                "bybit_uid"
            )
        else:
            payment_type = "BEP20"
            payment_value = wallet.get(
                "bep20"
            )

        if not payment_value:
            await query.answer(
                "Wallet not found.",
                show_alert=True,
            )
            return

        minimum = await get_withdraw_minimum(
            user
        )

        set_flow(
            user_id,
            "withdraw_amount",
            {
                "method": "usdt",
                "payment_type": payment_type,
                "payment_value": payment_value,
                "minimum": str(minimum),
            },
        )

        await query.edit_message_text(
            "💸 <b>Enter Withdrawal Amount</b>\n\n"
            f"💰 Available: <b>{fmt_usdt(user.get('balance'))} USDT</b>\n"
            f"🔻 Minimum: <b>{fmt_usdt(minimum)} USDT</b>\n\n"
            f"💳 Method: <b>{payment_type}</b>\n\n"
            "USDT amount ያስገቡ።",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "withdraw_cancel":
        clear_state(user_id)

        await query.edit_message_text(
            "❌ Withdrawal cancelled."
        )
        return

    if data == "withdraw_confirm":
        await create_withdrawal(
            query,
            context,
        )
        return

    # -----------------------------
    # ADMIN
    # -----------------------------

    if data.startswith("admin_approve_"):
        request_id = int(
            data.replace(
                "admin_approve_",
                "",
                1,
            )
        )

        await admin_approve(
            query,
            context,
            request_id,
        )
        return

    if data.startswith("admin_reject_"):
        request_id = int(
            data.replace(
                "admin_reject_",
                "",
                1,
            )
        )

        await admin_reject(
            query,
            context,
            request_id,
        )
        return

    # -----------------------------
    # VERIFY
    # -----------------------------

    if data == "verify_membership":
        await verify_membership(
            update,
            context,
        )
        return


# =========================================================
# COMMANDS
# =========================================================

async def history_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await history_page(
        update,
        context,
    )


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await admin_dashboard(
        update,
        context,
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Unhandled exception",
        exc_info=context.error,
    )

    try:
        if isinstance(update, Update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ ትንሽ technical problem ተፈጥሯል።\n"
                    "እባክዎ እንደገና ይሞክሩ።"
                )
    except Exception:
        pass


# =========================================================
# MAIN
# =========================================================

def main():
    logger.info(
        "Vortex Earn Bot is starting..."
    )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "referral",
            referral_page,
        )
    )

    application.add_handler(
        CommandHandler(
            "history",
            history_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    # Callbacks
    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # Main menu / text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=(
            f"https://vortex-earn-bot.onrender.com/{TOKEN}"
        ),
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
