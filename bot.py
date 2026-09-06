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
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from supabase import create_client, Client


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

SUPPORT_USERNAME = "AmanM_12"

RATE = Decimal("185")
REFERRAL_REWARD = Decimal("0.015")
REFERRAL_ETB = REFERRAL_REWARD * RATE

MIN_FIRST_WITHDRAWAL = Decimal("0.12")
MIN_LATER_WITHDRAWAL = Decimal("0.50")

CHANNELS = [
    ("@Sheger_tech1", "https://t.me/Sheger_tech1"),
    ("@EthioVortex1", "https://t.me/EthioVortex1"),
    ("@ethiocashflow", "https://t.me/ethiocashflow"),
    ("@AmanMoneyLab07", "https://t.me/AmanMoneyLab07"),
]

ADMIN_IDS = set()

if os.getenv("ADMIN_IDS"):
    for value in os.getenv("ADMIN_IDS", "").split(","):
        value = value.strip()
        if value.isdigit():
            ADMIN_IDS.add(int(value))


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("vortex_earn_bot")


# ============================================================
# SUPABASE
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# ============================================================
# USER STATES
# ============================================================

user_states = {}


def state_for(user_id):
    return user_states.setdefault(
        user_id,
        {
            "action": None,
            "method": None,
            "wallet_type": None,
            "temp": {},
        },
    )


def clear_state(user_id):
    user_states[user_id] = {
        "action": None,
        "method": None,
        "wallet_type": None,
        "temp": {},
    }


# ============================================================
# KEYBOARDS
# ============================================================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Balance", "🎯 Tasks"],
        ["👥 Referral", "👛 Wallet"],
        ["💸 Withdraw", "🆘 Support"],
    ],
    resize_keyboard=True,
)


def back_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 Back", callback_data="wallet_back")]
        ]
    )


def wallet_menu():
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
        ]
    )


def referral_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 My Referrals",
                    callback_data="my_referrals",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="main_back",
                )
            ],
        ]
    )


def withdraw_menu():
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


def confirmation_keyboard():
    return InlineKeyboardMarkup(
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
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

def db_get_user_sync(telegram_id):
    result = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


async def db_get_user(telegram_id):
    return await asyncio.to_thread(
        db_get_user_sync,
        telegram_id,
    )


def db_create_user_sync(telegram_id, username, referred_by=None):
    data = {
        "telegram_id": telegram_id,
        "username": username or "",
        "balance": 0,
        "balance_etb": 0,
        "referrals": 0,
        "referral_count": 0,
        "withdrawal_count": 0,
        "total_withdrawn_usdt": 0,
        "total_withdrawn_etb": 0,
        "wallet": "",
        "usdt_address": "",
        "telebirr_number": "",
        "bank_name": "",
        "bank_account": "",
        "last_withdrawal_method": "",
        "is_verified": False,
        "referred_by": referred_by,
        "currency": "USDT",
    }

    result = (
        supabase.table("users")
        .insert(data)
        .execute()
    )

    if result.data:
        return result.data[0]

    return db_get_user_sync(telegram_id)


async def db_create_user(telegram_id, username, referred_by=None):
    return await asyncio.to_thread(
        db_create_user_sync,
        telegram_id,
        username,
        referred_by,
    )


def db_update_user_sync(telegram_id, data):
    result = (
        supabase.table("users")
        .update(data)
        .eq("telegram_id", telegram_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


async def db_update_user(telegram_id, data):
    return await asyncio.to_thread(
        db_update_user_sync,
        telegram_id,
        data,
    )


def db_get_referrals_sync(telegram_id):
    result = (
        supabase.table("users")
        .select(
            "telegram_id,username,is_verified,created_at"
        )
        .eq("referred_by", telegram_id)
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


async def db_get_referrals(telegram_id):
    return await asyncio.to_thread(
        db_get_referrals_sync,
        telegram_id,
    )


def db_create_withdrawal_sync(data):
    result = (
        supabase.table("withdrawal_requests")
        .insert(data)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


async def db_create_withdrawal(data):
    return await asyncio.to_thread(
        db_create_withdrawal_sync,
        data,
    )


def db_get_pending_withdrawals_sync():
    result = (
        supabase.table("withdrawal_requests")
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )

    return result.data or []


async def db_get_pending_withdrawals():
    return await asyncio.to_thread(
        db_get_pending_withdrawals_sync
    )


def db_get_user_withdrawals_sync(telegram_id):
    result = (
        supabase.table("withdrawal_requests")
        .select("*")
        .eq("user_id", telegram_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    return result.data or []


async def db_get_user_withdrawals(telegram_id):
    return await asyncio.to_thread(
        db_get_user_withdrawals_sync,
        telegram_id,
    )


def db_update_withdrawal_sync(request_id, data):
    result = (
        supabase.table("withdrawal_requests")
        .update(data)
        .eq("id", request_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


async def db_update_withdrawal(request_id, data):
    return await asyncio.to_thread(
        db_update_withdrawal_sync,
        request_id,
        data,
    )


# ============================================================
# WALLET JSON
# ============================================================

def get_wallet_data(user):
    raw = user.get("wallet")

    if not raw:
        return {}

    if isinstance(raw, dict):
        return raw

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


async def save_wallet_data(user, data):
    return await db_update_user(
        user["telegram_id"],
        {
            "wallet": json.dumps(
                data,
                ensure_ascii=False,
            )
        },
    )


# ============================================================
# VALIDATION
# ============================================================

def valid_telebirr(value):
    return bool(
        re.fullmatch(
            r"(09|07)\d{8}",
            value.strip(),
        )
    )


def valid_cbe_account(value):
    return bool(
        re.fullmatch(
            r"\d{14}",
            value.strip(),
        )
    )


def valid_bybit_uid(value):
    return bool(
        re.fullmatch(
            r"\d{5,20}",
            value.strip(),
        )
    )


def valid_bep20(value):
    return bool(
        re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            value.strip(),
        )
    )


def valid_person_name(value):
    value = value.strip()

    if not value:
        return False

    if len(value) > 80:
        return False

    return bool(
        re.fullmatch(
            r"[A-Za-zÀ-ÿ\u1200-\u137F' -]+",
            value,
        )
    )


def money(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt_usdt(value):
    return f"{money(value):.6f}".rstrip("0").rstrip(".")


def fmt_etb(value):
    return f"{money(value):.2f}"


# ============================================================
# MEMBERSHIP
# ============================================================

async def check_membership(bot, user_id):
    missing = []

    for username, _url in CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=username,
                user_id=user_id,
            )

            if member.status in (
                "left",
                "kicked",
            ):
                missing.append(username)

        except Exception as exc:
            logger.warning(
                "Membership check failed for %s: %s",
                username,
                exc,
            )
            missing.append(username)

    return missing


def join_keyboard():
    rows = []

    for username, url in CHANNELS:
        rows.append(
            [
                InlineKeyboardButton(
                    f"➕ Join {username}",
                    url=url,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "✅ Verify",
                callback_data="verify_membership",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# ============================================================
# START / ONBOARDING
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user:
        return

    existing = await db_get_user(user.id)

    referred_by = None

    if not existing and context.args:
        argument = context.args[0].strip()

        if argument.startswith("ref_"):
            raw_id = argument[4:]

            if raw_id.isdigit():
                candidate = int(raw_id)

                if candidate != user.id:
                    referred_by = candidate

    if not existing:
        try:
            existing = await db_create_user(
                user.id,
                user.username or "",
                referred_by,
            )
        except Exception as exc:
            logger.exception(
                "User creation error: %s",
                exc,
            )

            await update.message.reply_text(
                "⚠️ Something went wrong.\n"
                "Please try again.",
            )
            return

    else:
        if (
            existing.get("username", "") !=
            (user.username or "")
        ):
            await db_update_user(
                user.id,
                {
                    "username": user.username or ""
                },
            )

    missing = await check_membership(
        context.bot,
        user.id,
    )

    if missing:
        await update.message.reply_text(
            "🌪️ *Welcome to Vortex Earn Bot!*\n\n"
            "💰 Earn rewards\n"
            "👥 Invite friends\n"
            "💸 Withdraw your earnings\n\n"
            "Before using the bot, please join all "
            "required channels below and then press "
            "*Verify*.",
            parse_mode="Markdown",
            reply_markup=join_keyboard(),
        )
        return

    await complete_verified_start(
        update,
        context,
        existing,
    )


async def complete_verified_start(
    update,
    context,
    user,
):
    await process_referral_reward(
        context,
        user,
    )

    await update.message.reply_text(
        "✅ *Verification successful!*\n\n"
        "🌪️ Welcome to Vortex Earn Bot.\n"
        "Choose an option below 👇",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
    )


# ============================================================
# REFERRAL REWARD
# ============================================================

async def process_referral_reward(context, user):
    try:
        referred_by = user.get("referred_by")

        if not referred_by:
            return

        if int(referred_by) == int(user["telegram_id"]):
            return

        wallet = get_wallet_data(user)

        if wallet.get("_referral_rewarded"):
            return

        referrer = await db_get_user(
            int(referred_by)
        )

        if not referrer:
            return

        ref_balance = money(
            referrer.get("balance")
        )

        ref_balance_etb = money(
            referrer.get("balance_etb")
        )

        await db_update_user(
            referrer["telegram_id"],
            {
                "balance": str(
                    ref_balance + REFERRAL_REWARD
                ),
                "balance_etb": str(
                    ref_balance_etb + REFERRAL_ETB
                ),
                "referral_count":
                    int(referrer.get("referral_count") or 0)
                    + 1,
                "referrals":
                    int(referrer.get("referrals") or 0)
                    + 1,
            },
        )

        wallet["_referral_rewarded"] = True

        await save_wallet_data(
            user,
            wallet,
        )

        try:
            await context.bot.send_message(
                chat_id=referrer["telegram_id"],
                text=(
                    "🎉 *New Referral Reward!*\n\n"
                    f"👤 A new user joined through your link.\n\n"
                    f"💰 Reward: "
                    f"+{fmt_usdt(REFERRAL_REWARD)} USDT\n"
                    f"🇪🇹 Value: "
                    f"+{fmt_etb(REFERRAL_ETB)} ETB\n\n"
                    f"💱 Rate: 1 USDT = {RATE} ETB"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    except Exception as exc:
        logger.exception(
            "Referral reward error: %s",
            exc,
        )


# ============================================================
# VERIFY CALLBACK
# ============================================================

async def verify_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    missing = await check_membership(
        context.bot,
        user.id,
    )

    if missing:
        text = (
            "❌ *Verification incomplete*\n\n"
            "Please join these channel(s):\n\n"
        )

        for channel in missing:
            text += f"• {channel}\n"

        text += (
            "\nAfter joining, press *Verify* again."
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=join_keyboard(),
        )
        return

    db_user = await db_get_user(user.id)

    if db_user:
        await db_update_user(
            user.id,
            {
                "is_verified": True,
                "username": user.username or "",
            },
        )

        db_user["is_verified"] = True

        await process_referral_reward(
            context,
            db_user,
        )

    await query.edit_message_text(
        "✅ *Verification successful!*\n\n"
        "You can now use all bot features.",
        parse_mode="Markdown",
    )

    await context.bot.send_message(
        chat_id=user.id,
        text="🌪️ Choose an option below 👇",
        reply_markup=MAIN_MENU,
    )


# ============================================================
# BALANCE
# ============================================================

async def show_balance(update, context):
    user = update.effective_user

    db_user = await db_get_user(user.id)

    if not db_user:
        await update.message.reply_text(
            "Please send /start first."
        )
        return

    usdt = money(db_user.get("balance"))
    etb = money(db_user.get("balance_etb"))

    await update.message.reply_text(
        "💰 *Balance*\n\n"
        f"🪙 USDT = {fmt_usdt(usdt)} USDT\n"
        f"🇪🇹 ETB = {fmt_etb(etb)} ETB\n\n"
        f"💱 Rate: 1 USDT = {RATE} ETB",
        parse_mode="Markdown",
    )


# ============================================================
# REFERRAL
# ============================================================

async def show_referral(update, context):
    user = update.effective_user

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{user.id}"
    )

    db_user = await db_get_user(user.id)

    count = 0

    if db_user:
        count = int(
            db_user.get("referral_count") or
            db_user.get("referrals") or
            0
        )

    await update.message.reply_text(
        "👥 *Referral Program*\n\n"
        f"🔗 Your referral link:\n{link}\n\n"
        f"👤 Successful referrals: {count}\n"
        f"💰 Reward: {fmt_usdt(REFERRAL_REWARD)} USDT\n"
        f"🇪🇹 Equivalent: {fmt_etb(REFERRAL_ETB)} ETB\n"
        f"💱 Rate: 1 USDT = {RATE} ETB\n\n"
        "Invite friends and earn when they "
        "successfully join and verify.",
        parse_mode="Markdown",
        reply_markup=referral_keyboard(),
    )


async def my_referrals(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    referrals = await db_get_referrals(
        user.id
    )

    if not referrals:
        text = (
            "👥 *My Referrals*\n\n"
            "You don't have any referrals yet.\n\n"
            "Share your referral link to invite people."
        )

    else:
        lines = [
            "👥 *My Referrals*\n"
        ]

        for index, item in enumerate(
            referrals,
            start=1,
        ):
            username = item.get("username")

            if username:
                name = f"@{username}"
            else:
                name = (
                    f"User {item.get('telegram_id')}"
                )

            verified = (
                "✅ Verified"
                if item.get("is_verified")
                else "⏳ Pending"
            )

            lines.append(
                f"{index}. {name} — {verified}"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
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


# ============================================================
# TASKS
# ============================================================

async def show_tasks(update, context):
    await update.message.reply_text(
        "🎯 *Tasks*\n\n"
        "Automated earning tasks are currently "
        "being prepared.\n\n"
        "📢 *Promotion Service*\n"
        "If you want to promote your Telegram "
        "channel, bot, product or service, contact "
        "our support team for promotion options.\n\n"
        "🆘 Support: @AmanM_12",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📢 Promotion Service",
                        url="https://t.me/AmanM_12",
                    )
                ]
            ]
        ),
    )


# ============================================================
# WALLET MAIN
# ============================================================

async def show_wallet(update, context):
    user = update.effective_user

    db_user = await db_get_user(user.id)

    if not db_user:
        await update.message.reply_text(
            "Please send /start first."
        )
        return

    await update.message.reply_text(
        "👛 *Wallet*\n\n"
        "Choose the payment method you want to "
        "set up or manage:",
        parse_mode="Markdown",
        reply_markup=wallet_menu(),
    )


# ============================================================
# WALLET STATUS
# ============================================================

def wallet_status_text(data):
    lines = []

    bybit = data.get("bybit_uid")
    bep20 = data.get("bep20")
    cbe_account = data.get("cbe_account")
    cbe_name = data.get("cbe_name")
    telebirr = data.get("telebirr")
    telebirr_name = data.get("telebirr_name")

    lines.append(
        "🟢 Bybit UID saved"
        if bybit
        else "⚪ Bybit UID not set"
    )

    lines.append(
        "🟢 BEP20 address saved"
        if bep20
        else "⚪ BEP20 address not set"
    )

    return "\n".join(lines)


# ============================================================
# USDT WALLET PAGE
# ============================================================

async def wallet_usdt(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = await db_get_user(
        query.from_user.id
    )

    if not user:
        return

    data = get_wallet_data(user)

    text = (
        "💵 *USDT Wallet*\n\n"
        "You can save either a Bybit UID / Account ID "
        "or a BEP20 USDT address.\n\n"
    )

    if data.get("bybit_uid"):
        text += (
            f"🟢 *Bybit UID:* "
            f"`{html.escape(str(data['bybit_uid']))}`\n"
        )
    else:
        text += "⚪ Bybit UID: Not saved\n"

    if data.get("bep20"):
        text += (
            f"🟢 *BEP20:* "
            f"`{html.escape(str(data['bep20']))}`\n"
        )
    else:
        text += "⚪ BEP20: Not saved\n"

    text += (
        "\nChoose what you want to add or edit:"
    )

    buttons = []

    if data.get("bybit_uid"):
        buttons.append(
            [
                InlineKeyboardButton(
                    "✏️ Edit Bybit UID",
                    callback_data="wallet_edit_bybit",
                )
            ]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    "➕ Add Bybit UID",
                    callback_data="wallet_add_bybit",
                )
            ]
        )

    if data.get("bep20"):
        buttons.append(
            [
                InlineKeyboardButton(
                    "✏️ Edit BEP20",
                    callback_data="wallet_edit_bep20",
                )
            ]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    "➕ Add BEP20",
                    callback_data="wallet_add_bep20",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="wallet_back",
            )
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# BYBIT INPUT
# ============================================================

async def begin_wallet_bybit(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = state_for(user_id)

    state["action"] = "wallet_bybit"

    await query.edit_message_text(
        "🟢 *Bybit UID / Account ID*\n\n"
        "Please send your Bybit UID / Account ID.\n\n"
        "Example: `12345678`",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# BEP20 INPUT
# ============================================================

async def begin_wallet_bep20(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = state_for(user_id)

    state["action"] = "wallet_bep20"

    await query.edit_message_text(
        "🟢 *BEP20 USDT Address*\n\n"
        "Send your BEP20 address.\n\n"
        "Example:\n"
        "`0x1234567890abcdef1234567890abcdef12345678`",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# CBE PAGE
# ============================================================

async def wallet_cbe(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = await db_get_user(
        query.from_user.id
    )

    if not user:
        return

    data = get_wallet_data(user)

    account = data.get("cbe_account")
    name = data.get("cbe_name")

    if account and name:
        text = (
            "🏦 *CBE Wallet*\n\n"
            f"🟢 Account Number: `{account}`\n"
            f"🟢 Name: {html.escape(name)}\n\n"
            "Your CBE details are saved."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✏️ Edit",
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

    else:
        text = (
            "🏦 *CBE Wallet*\n\n"
            "You have not saved your CBE details yet.\n\n"
            "You will need:\n"
            "• 14-digit CBE account number\n"
            "• Your full name\n"
            "• Your father's name"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ Add CBE",
                        callback_data="wallet_add_cbe",
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
        parse_mode="HTML",
        reply_markup=keyboard,
    )


# ============================================================
# CBE INPUT
# ============================================================

async def begin_wallet_cbe(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = state_for(user_id)

    state["action"] = "wallet_cbe_account"

    await query.edit_message_text(
        "🏦 *CBE Account Number*\n\n"
        "Send your 14-digit CBE account number.\n\n"
        "Example: `12345678901234`",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# TELEBIRR PAGE
# ============================================================

async def wallet_telebirr(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = await db_get_user(
        query.from_user.id
    )

    if not user:
        return

    data = get_wallet_data(user)

    number = data.get("telebirr")
    name = data.get("telebirr_name")

    if number and name:
        text = (
            "📱 *Telebirr Wallet*\n\n"
            f"🟢 Phone: `{number}`\n"
            f"🟢 Name: {html.escape(name)}\n\n"
            "Your Telebirr details are saved."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✏️ Edit",
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

    else:
        text = (
            "📱 *Telebirr Wallet*\n\n"
            "You have not saved your Telebirr details yet.\n\n"
            "You will need:\n"
            "• 10-digit Telebirr number starting with 09 or 07\n"
            "• Your full name\n"
            "• Your father's name"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "➕ Add Telebirr",
                        callback_data="wallet_add_telebirr",
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
        parse_mode="HTML",
        reply_markup=keyboard,
    )


# ============================================================
# TELEBIRR INPUT
# ============================================================

async def begin_wallet_telebirr(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = state_for(user_id)

    state["action"] = "wallet_telebirr_phone"

    await query.edit_message_text(
        "📱 *Telebirr Number*\n\n"
        "Send your 10-digit Telebirr number.\n\n"
        "It must start with *09* or *07*.\n\n"
        "Example: `0912345678`",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# NAME INPUT
# ============================================================

async def ask_full_name(
    update,
    context,
    method,
):
    user_id = update.effective_user.id

    state = state_for(user_id)

    state["method"] = method

    if method == "cbe":
        state["action"] = "wallet_cbe_name"

    elif method == "telebirr":
        state["action"] = "wallet_telebirr_name"

    await update.message.reply_text(
        "👤 *Your Full Name*\n\n"
        "Please send your full name.\n\n"
        "Example: Abebe Kebede",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["🔙 Cancel"]],
            resize_keyboard=True,
        ),
    )


async def ask_father_name(
    update,
    context,
    method,
):
    user_id = update.effective_user.id

    state = state_for(user_id)

    state["method"] = method

    if method == "cbe":
        state["action"] = "wallet_cbe_father"

    elif method == "telebirr":
        state["action"] = "wallet_telebirr_father"

    await update.message.reply_text(
        "👨 *Father's Name*\n\n"
        "Please send your father's name.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["🔙 Cancel"]],
            resize_keyboard=True,
        ),
    )


# ============================================================
# WALLET MESSAGE HANDLER
# ============================================================

async def handle_wallet_input(
    update,
    context,
):
    user = update.effective_user

    if not user or not update.message:
        return

    text = update.message.text.strip()

    if text == "🔙 Cancel":
        clear_state(user.id)

        await update.message.reply_text(
            "↩️ Cancelled.",
            reply_markup=MAIN_MENU,
        )
        return

    state = state_for(user.id)
    action = state.get("action")

    if not action:
        return

    db_user = await db_get_user(user.id)

    if not db_user:
        clear_state(user.id)
        return

    data = get_wallet_data(db_user)

    # --------------------------------------------------------
    # BYBIT
    # --------------------------------------------------------

    if action == "wallet_bybit":
        if not valid_bybit_uid(text):
            await update.message.reply_text(
                "❌ Invalid Bybit UID.\n\n"
                "Please enter a valid numeric UID "
                "between 5 and 20 digits.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        data["bybit_uid"] = text

        await save_wallet_data(
            db_user,
            data,
        )

        clear_state(user.id)

        await update.message.reply_text(
            "✅ *Bybit UID saved successfully.*\n\n"
            f"🟢 UID: `{text}`",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )

        return

    # --------------------------------------------------------
    # BEP20
    # --------------------------------------------------------

    if action == "wallet_bep20":
        if not valid_bep20(text):
            await update.message.reply_text(
                "❌ Invalid BEP20 address.\n\n"
                "It must start with `0x` and contain "
                "40 hexadecimal characters after it.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        data["bep20"] = text
        data["usdt_address"] = text

        await save_wallet_data(
            db_user,
            data,
        )

        clear_state(user.id)

        await update.message.reply_text(
            "✅ *BEP20 address saved successfully.*\n\n"
            f"🟢 Address: `{text}`",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )

        return

    # --------------------------------------------------------
    # CBE ACCOUNT
    # --------------------------------------------------------

    if action == "wallet_cbe_account":
        if not valid_cbe_account(text):
            await update.message.reply_text(
                "❌ Invalid CBE account number.\n\n"
                "It must contain exactly 14 digits.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        state["temp"]["cbe_account"] = text
        state["action"] = "wallet_cbe_name"

        await update.message.reply_text(
            "👤 *Your Full Name*\n\n"
            "Send your full name.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )

        return

    # --------------------------------------------------------
    # CBE NAME
    # --------------------------------------------------------

    if action == "wallet_cbe_name":
        if not valid_person_name(text):
            await update.message.reply_text(
                "❌ Please enter a valid name.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        state["temp"]["cbe_name"] = text
        state["action"] = "wallet_cbe_father"

        await update.message.reply_text(
            "👨 *Father's Name*\n\n"
            "Send your father's name.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )

        return

    # --------------------------------------------------------
    # CBE FATHER
    # --------------------------------------------------------

    if action == "wallet_cbe_father":
        if not valid_person_name(text):
            await update.message.reply_text(
                "❌ Please enter a valid father's name.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        data["cbe_account"] = (
            state["temp"].get("cbe_account", "")
        )

        data["cbe_name"] = (
            state["temp"].get("cbe_name", "")
            + " "
            + text
        ).strip()

        await save_wallet_data(
            db_user,
            data,
        )

        await db_update_user(
            user.id,
            {
                "bank_account":
                    data["cbe_account"],
                "bank_name":
                    data["cbe_name"],
            },
        )

        clear_state(user.id)

        await update.message.reply_text(
            "✅ *CBE details saved successfully.*\n\n"
            f"🏦 Account: `{data['cbe_account']}`\n"
            f"👤 Name: {data['cbe_name']}",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )

        return

    # --------------------------------------------------------
    # TELEBIRR PHONE
    # --------------------------------------------------------

    if action == "wallet_telebirr_phone":
        if not valid_telebirr(text):
            await update.message.reply_text(
                "❌ Invalid Telebirr number.\n\n"
                "It must contain exactly 10 digits "
                "and start with 09 or 07.\n\n"
                "Example: 0912345678",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        state["temp"]["telebirr"] = text
        state["action"] = "wallet_telebirr_name"

        await update.message.reply_text(
            "👤 *Your Full Name*\n\n"
            "Send your full name.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )

        return

    # --------------------------------------------------------
    # TELEBIRR NAME
    # --------------------------------------------------------

    if action == "wallet_telebirr_name":
        if not valid_person_name(text):
            await update.message.reply_text(
                "❌ Please enter a valid name.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        state["temp"]["telebirr_name"] = text
        state["action"] = "wallet_telebirr_father"

        await update.message.reply_text(
            "👨 *Father's Name*\n\n"
            "Send your father's name.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )

        return

    # --------------------------------------------------------
    # TELEBIRR FATHER
    # --------------------------------------------------------

    if action == "wallet_telebirr_father":
        if not valid_person_name(text):
            await update.message.reply_text(
                "❌ Please enter a valid father's name.",
                reply_markup=ReplyKeyboardMarkup(
                    [["🔙 Cancel"]],
                    resize_keyboard=True,
                ),
            )
            return

        data["telebirr"] = (
            state["temp"].get("telebirr", "")
        )

        data["telebirr_name"] = (
            state["temp"].get("telebirr_name", "")
            + " "
            + text
        ).strip()

        await save_wallet_data(
            db_user,
            data,
        )

        await db_update_user(
            user.id,
            {
                "telebirr_number":
                    data["telebirr"],
            },
        )

        clear_state(user.id)

        await update.message.reply_text(
            "✅ *Telebirr details saved successfully.*\n\n"
            f"📱 Phone: `{data['telebirr']}`\n"
            f"👤 Name: {data['telebirr_name']}",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU,
        )

        return


# ============================================================
# WALLET EDIT CALLBACKS
# ============================================================

async def wallet_edit_bybit(
    update,
    context,
):
    await begin_wallet_bybit(
        update,
        context,
    )


async def wallet_edit_bep20(
    update,
    context,
):
    await begin_wallet_bep20(
        update,
        context,
    )


async def wallet_edit_cbe(
    update,
    context,
):
    await begin_wallet_cbe(
        update,
        context,
    )


async def wallet_edit_telebirr(
    update,
    context,
):
    await begin_wallet_telebirr(
        update,
        context,
    )


# ============================================================
# WITHDRAWAL
# ============================================================

def withdrawal_minimum(db_user):
    count = int(
        db_user.get("withdrawal_count") or 0
    )

    if count < 2:
        return MIN_FIRST_WITHDRAWAL

    return MIN_LATER_WITHDRAWAL


async def show_withdraw(update, context):
    user = update.effective_user

    db_user = await db_get_user(user.id)

    if not db_user:
        await update.message.reply_text(
            "Please send /start first."
        )
        return

    minimum = withdrawal_minimum(db_user)

    await update.message.reply_text(
        "💸 *Withdraw*\n\n"
        f"Minimum withdrawal: "
        f"{fmt_usdt(minimum)} USDT\n\n"
        "Choose your payment method:",
        parse_mode="Markdown",
        reply_markup=withdraw_menu(),
    )


# ============================================================
# WITHDRAW METHOD
# ============================================================

async def select_withdraw_method(
    update,
    context,
    method,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    db_user = await db_get_user(user_id)

    if not db_user:
        return

    data = get_wallet_data(db_user)

    state = state_for(user_id)

    state["method"] = method

    if method == "usdt":
        bybit = data.get("bybit_uid")
        bep20 = data.get("bep20")

        if bybit and bep20:
            state["action"] = "withdraw_usdt_choice"

            await query.edit_message_text(
                "💵 *USDT Withdrawal*\n\n"
                "You have two saved USDT methods.\n"
                "Choose which one you want to use:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🟢 Bybit UID",
                                callback_data="withdraw_use_bybit",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🟢 BEP20",
                                callback_data="withdraw_use_bep20",
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

        if bybit:
            state["temp"]["payment_type"] = "Bybit"
            state["temp"]["payment_details"] = bybit

        elif bep20:
            state["temp"]["payment_type"] = "BEP20"
            state["temp"]["payment_details"] = bep20

        else:
            await query.edit_message_text(
                "❌ *USDT Wallet Not Set*\n\n"
                "Please save a Bybit UID or BEP20 "
                "address in Wallet first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "👛 Open Wallet",
                                callback_data="wallet_back",
                            )
                        ]
                    ]
                ),
            )
            return

    elif method == "cbe":
        account = data.get("cbe_account")
        name = data.get("cbe_name")

        if not account:
            account = db_user.get("bank_account")

        if not name:
            name = db_user.get("bank_name")

        if not account or not name:
            await query.edit_message_text(
                "❌ *CBE Wallet Not Set*\n\n"
                "Please save your CBE details in "
                "Wallet first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "👛 Open Wallet",
                                callback_data="wallet_back",
                            )
                        ]
                    ]
                ),
            )
            return

        state["temp"]["payment_type"] = "CBE"
        state["temp"]["payment_details"] = (
            f"Account: {account}\n"
            f"Name: {name}"
        )

    elif method == "telebirr":
        number = data.get("telebirr")

        if not number:
            number = db_user.get(
                "telebirr_number"
            )

        name = data.get("telebirr_name")

        if not number or not name:
            await query.edit_message_text(
                "❌ *Telebirr Wallet Not Set*\n\n"
                "Please save your Telebirr details "
                "in Wallet first.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "👛 Open Wallet",
                                callback_data="wallet_back",
                            )
                        ]
                    ]
                ),
            )
            return

        state["temp"]["payment_type"] = "Telebirr"
        state["temp"]["payment_details"] = (
            f"Phone: {number}\n"
            f"Name: {name}"
        )

    state["action"] = "withdraw_amount"

    minimum = withdrawal_minimum(db_user)

    await query.edit_message_text(
        "💸 *Withdrawal Amount*\n\n"
        f"Minimum: {fmt_usdt(minimum)} USDT\n"
        f"Rate: 1 USDT = {RATE} ETB\n\n"
        "Send the amount you want to withdraw.\n\n"
        "Example: `0.12`",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# USDT CHOICE
# ============================================================

async def withdraw_use_bybit(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    db_user = await db_get_user(user_id)

    if not db_user:
        return

    data = get_wallet_data(db_user)

    if not data.get("bybit_uid"):
        await query.answer(
            "Bybit UID is not saved.",
            show_alert=True,
        )
        return

    state = state_for(user_id)

    state["method"] = "usdt"
    state["action"] = "withdraw_amount"
    state["temp"]["payment_type"] = "Bybit"
    state["temp"]["payment_details"] = (
        data["bybit_uid"]
    )

    minimum = withdrawal_minimum(db_user)

    await query.edit_message_text(
        "💸 *USDT Withdrawal — Bybit*\n\n"
        f"Minimum: {fmt_usdt(minimum)} USDT\n"
        f"Rate: 1 USDT = {RATE} ETB\n\n"
        "Send the amount you want to withdraw.",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


async def withdraw_use_bep20(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    db_user = await db_get_user(user_id)

    if not db_user:
        return

    data = get_wallet_data(db_user)

    if not data.get("bep20"):
        await query.answer(
            "BEP20 address is not saved.",
            show_alert=True,
        )
        return

    state = state_for(user_id)

    state["method"] = "usdt"
    state["action"] = "withdraw_amount"
    state["temp"]["payment_type"] = "BEP20"
    state["temp"]["payment_details"] = (
        data["bep20"]
    )

    minimum = withdrawal_minimum(db_user)

    await query.edit_message_text(
        "💸 *USDT Withdrawal — BEP20*\n\n"
        f"Minimum: {fmt_usdt(minimum)} USDT\n"
        f"Rate: 1 USDT = {RATE} ETB\n\n"
        "Send the amount you want to withdraw.",
        parse_mode="Markdown",
        reply_markup=back_keyboard(),
    )


# ============================================================
# WITHDRAW AMOUNT INPUT
# ============================================================

async def handle_withdraw_amount(
    update,
    context,
):
    user = update.effective_user

    if not user or not update.message:
        return

    text = update.message.text.strip()

    state = state_for(user.id)

    if state.get("action") != "withdraw_amount":
        return

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text(
            "❌ Invalid amount.\n\n"
            "Example: 0.12",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ Amount must be greater than 0.",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )
        return

    db_user = await db_get_user(user.id)

    if not db_user:
        clear_state(user.id)
        return

    minimum = withdrawal_minimum(db_user)
    balance = money(db_user.get("balance"))

    if amount < minimum:
        await update.message.reply_text(
            "❌ Amount is below the minimum.\n\n"
            f"Minimum withdrawal: "
            f"{fmt_usdt(minimum)} USDT",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )
        return

    if amount > balance:
        await update.message.reply_text(
            "❌ Insufficient balance.\n\n"
            f"Available: {fmt_usdt(balance)} USDT",
            reply_markup=ReplyKeyboardMarkup(
                [["🔙 Cancel"]],
                resize_keyboard=True,
            ),
        )
        return

    # Check existing pending withdrawals
    pending = await asyncio.to_thread(
        lambda: (
            supabase.table(
                "withdrawal_requests"
            )
            .select("id")
            .eq("user_id", user.id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        ).data or []
    )

    if pending:
        clear_state(user.id)

        await update.message.reply_text(
            "⏳ You already have a pending withdrawal.\n\n"
            "Please wait until it is processed.",
            reply_markup=MAIN_MENU,
        )
        return

    etb = amount * RATE

    state["temp"]["amount"] = str(amount)
    state["temp"]["amount_etb"] = str(etb)
    state["action"] = "withdraw_confirm"

    payment_type = state["temp"].get(
        "payment_type",
        "",
    )

    await update.message.reply_text(
        "🧾 *Confirm Withdrawal*\n\n"
        f"💰 Amount: {fmt_usdt(amount)} USDT\n"
        f"🇪🇹 Value: {fmt_etb(etb)} ETB\n"
        f"💳 Method: {payment_type}\n\n"
        "Do you want to submit this withdrawal?",
        parse_mode="Markdown",
        reply_markup=confirmation_keyboard(),
    )


# ============================================================
# WITHDRAW CONFIRM
# ============================================================

async def confirm_withdraw(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    state = state_for(user_id)

    if state.get("action") != "withdraw_confirm":
        await query.edit_message_text(
            "⚠️ This withdrawal session has expired."
        )
        return

    amount = money(
        state["temp"].get("amount")
    )

    amount_etb = money(
        state["temp"].get("amount_etb")
    )

    method = state.get("method", "")
    payment_type = state["temp"].get(
        "payment_type",
        "",
    )
    payment_details = state["temp"].get(
        "payment_details",
        "",
    )

    db_user = await db_get_user(user_id)

    if not db_user:
        clear_state(user_id)

        await query.edit_message_text(
            "❌ User account not found."
        )
        return

    balance = money(
        db_user.get("balance")
    )

    minimum = withdrawal_minimum(db_user)

    if amount < minimum:
        clear_state(user_id)

        await query.edit_message_text(
            "❌ The minimum withdrawal has changed.\n\n"
            f"Minimum: {fmt_usdt(minimum)} USDT"
        )
        return

    if amount > balance:
        clear_state(user_id)

        await query.edit_message_text(
            "❌ Insufficient balance."
        )
        return

    # Re-check pending request
    pending = await asyncio.to_thread(
        lambda: (
            supabase.table(
                "withdrawal_requests"
            )
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        ).data or []
    )

    if pending:
        clear_state(user_id)

        await query.edit_message_text(
            "⏳ You already have a pending withdrawal."
        )
        return

    request_data = {
        "user_id": user_id,
        "amount_usdt": str(amount),
        "amount_etb": str(amount_etb),
        "method": method,
        "payment_details": (
            f"{payment_type}: {payment_details}"
        ),
        "status": "pending",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    try:
        request = await db_create_withdrawal(
            request_data
        )

    except Exception as exc:
        logger.exception(
            "Withdrawal creation failed: %s",
            exc,
        )

        await query.edit_message_text(
            "❌ Could not submit your withdrawal.\n\n"
            "Please try again later."
        )
        clear_state(user_id)
        return

    clear_state(user_id)

    request_id = (
        request.get("id")
        if request
        else "N/A"
    )

    await query.edit_message_text(
        "✅ *Withdrawal Submitted*\n\n"
        f"🆔 Request: #{request_id}\n"
        f"💰 Amount: {fmt_usdt(amount)} USDT\n"
        f"🇪🇹 Value: {fmt_etb(amount_etb)} ETB\n"
        f"💳 Method: {payment_type}\n\n"
        "⏳ Status: Pending\n\n"
        "Your withdrawal will be reviewed manually.",
        parse_mode="Markdown",
    )

    # Admin notification
    if ADMIN_IDS:
        username = (
            f"@{user.username}"
            if user.username
            else "No username"
        )

        admin_text = (
            "🚨 *New Withdrawal Request*\n\n"
            f"🆔 Request: #{request_id}\n"
            f"👤 User: {html.escape(username)}\n"
            f"📱 Telegram ID: `{user_id}`\n\n"
            f"💰 Amount: {fmt_usdt(amount)} USDT\n"
            f"🇪🇹 Value: {fmt_etb(amount_etb)} ETB\n"
            f"💳 Method: {html.escape(payment_type)}\n\n"
            f"📌 Payment details:\n"
            f"{html.escape(payment_details)}"
        )

        admin_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve",
                        callback_data=(
                            f"admin_approve_{request_id}"
                        ),
                    ),
                    InlineKeyboardButton(
                        "❌ Reject",
                        callback_data=(
                            f"admin_reject_{request_id}"
                        ),
                    ),
                ]
            ]
        )

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    parse_mode="HTML",
                    reply_markup=admin_keyboard,
                )
            except Exception as exc:
                logger.warning(
                    "Admin notification failed: %s",
                    exc,
                )


# ============================================================
# CANCEL WITHDRAW
# ============================================================

async def cancel_withdraw(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    clear_state(
        query.from_user.id
    )

    await query.edit_message_text(
        "❌ Withdrawal cancelled."
    )

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="Choose an option below 👇",
        reply_markup=MAIN_MENU,
    )


# ============================================================
# HISTORY
# ============================================================

async def show_history(update, context):
    user = update.effective_user

    rows = await db_get_user_withdrawals(
        user.id
    )

    if not rows:
        await update.message.reply_text(
            "📜 *Withdrawal History*\n\n"
            "No withdrawal requests yet.",
            parse_mode="Markdown",
        )
        return

    lines = [
        "📜 *Withdrawal History*\n"
    ]

    for row in rows:
        request_id = row.get("id", "-")
        amount = fmt_usdt(
            row.get("amount_usdt")
        )
        status = row.get(
            "status",
            "unknown",
        ).capitalize()

        created = row.get(
            "created_at",
            "",
        )

        lines.append(
            f"🆔 #{request_id}\n"
            f"💰 {amount} USDT\n"
            f"📌 {status}\n"
            f"🕒 {created}\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def admin_command(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ Admin only."
        )
        return

    pending = await db_get_pending_withdrawals()

    if not pending:
        await update.message.reply_text(
            "🛠️ *Admin Dashboard*\n\n"
            "No pending withdrawals.",
            parse_mode="Markdown",
        )
        return

    lines = [
        "🛠️ *Admin Dashboard*\n",
        f"⏳ Pending: {len(pending)}\n",
    ]

    for row in pending[:10]:
        lines.append(
            f"\n🆔 #{row.get('id')}\n"
            f"👤 User: {row.get('user_id')}\n"
            f"💰 {fmt_usdt(row.get('amount_usdt'))} USDT\n"
            f"💳 {row.get('method')}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


# ============================================================
# ADMIN APPROVE
# ============================================================

async def admin_approve(
    update,
    context,
):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    request_id = int(
        query.data.split("_")[-1]
    )

    # Get request
    result = await asyncio.to_thread(
        lambda: (
            supabase.table(
                "withdrawal_requests"
            )
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
        ).data or []
    )

    if not result:
        await query.edit_message_text(
            "❌ Withdrawal request not found."
        )
        return

    request = result[0]

    if request.get("status") != "pending":
        await query.edit_message_text(
            "⚠️ This request has already been processed."
        )
        return

    user_id = int(
        request["user_id"]
    )

    amount = money(
        request.get("amount_usdt")
    )

    amount_etb = money(
        request.get("amount_etb")
    )

    user = await db_get_user(user_id)

    if not user:
        await query.edit_message_text(
            "❌ User account not found."
        )
        return

    balance = money(
        user.get("balance")
    )

    if balance < amount:
        await query.edit_message_text(
            "❌ User no longer has enough balance."
        )
        return

    new_balance = balance - amount

    old_etb = money(
        user.get("balance_etb")
    )

    new_etb = old_etb - amount_etb

    if new_etb < 0:
        new_etb = Decimal("0")

    count = int(
        user.get("withdrawal_count") or 0
    )

    total_usdt = money(
        user.get("total_withdrawn_usdt")
    )

    total_etb = money(
        user.get("total_withdrawn_etb")
    )

    updated = await db_update_user(
        user_id,
        {
            "balance": str(new_balance),
            "balance_etb": str(new_etb),
            "withdrawal_count": count + 1,
            "total_withdrawn_usdt":
                str(total_usdt + amount),
            "total_withdrawn_etb":
                str(total_etb + amount_etb),
            "last_withdrawal_method":
                request.get("method", ""),
        },
    )

    if not updated:
        await query.edit_message_text(
            "❌ Could not update user balance."
        )
        return

    await db_update_withdrawal(
        request_id,
        {
            "status": "approved",
            "processed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        },
    )

    await query.edit_message_text(
        f"✅ *Withdrawal #{request_id} approved.*\n\n"
        f"💰 {fmt_usdt(amount)} USDT",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 *Withdrawal Approved!*\n\n"
                f"💰 Amount: {fmt_usdt(amount)} USDT\n"
                f"🇪🇹 Value: {fmt_etb(amount_etb)} ETB\n\n"
                "✅ Your withdrawal has been approved."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


# ============================================================
# ADMIN REJECT
# ============================================================

async def admin_reject(
    update,
    context,
):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    request_id = int(
        query.data.split("_")[-1]
    )

    result = await asyncio.to_thread(
        lambda: (
            supabase.table(
                "withdrawal_requests"
            )
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
        ).data or []
    )

    if not result:
        await query.edit_message_text(
            "❌ Request not found."
        )
        return

    request = result[0]

    if request.get("status") != "pending":
        await query.edit_message_text(
            "⚠️ This request has already been processed."
        )
        return

    await db_update_withdrawal(
        request_id,
        {
            "status": "rejected",
            "processed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        },
    )

    await query.edit_message_text(
        f"❌ *Withdrawal #{request_id} rejected.*",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            chat_id=int(request["user_id"]),
            text=(
                "❌ *Withdrawal Rejected*\n\n"
                f"🆔 Request: #{request_id}\n\n"
                "Your balance was not deducted."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


# ============================================================
# SUPPORT
# ============================================================

async def show_support(update, context):
    await update.message.reply_text(
        "🆘 *Support*\n\n"
        "If you need help, contact our support team.\n\n"
        "👤 @AmanM_12",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💬 Contact Support",
                        url="https://t.me/AmanM_12",
                    )
                ]
            ]
        ),
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update,
    context,
):
    query = update.callback_query

    data = query.data or ""

    # ---------------------------
    # Wallet
    # ---------------------------

    if data == "wallet_usdt":
        await wallet_usdt(update, context)
        return

    if data == "wallet_cbe":
        await wallet_cbe(update, context)
        return

    if data == "wallet_telebirr":
        await wallet_telebirr(update, context)
        return

    if data in (
        "wallet_add_bybit",
        "wallet_edit_bybit",
    ):
        await begin_wallet_bybit(
            update,
            context,
        )
        return

    if data in (
        "wallet_add_bep20",
        "wallet_edit_bep20",
    ):
        await begin_wallet_bep20(
            update,
            context,
        )
        return

    if data in (
        "wallet_add_cbe",
        "wallet_edit_cbe",
    ):
        await begin_wallet_cbe(
            update,
            context,
        )
        return

    if data in (
        "wallet_add_telebirr",
        "wallet_edit_telebirr",
    ):
        await begin_wallet_telebirr(
            update,
            context,
        )
        return

    if data == "wallet_back":
        await query.answer()

        clear_state(
            query.from_user.id
        )

        await query.edit_message_text(
            "👛 *Wallet*\n\n"
            "Choose the payment method you want "
            "to manage:",
            parse_mode="Markdown",
            reply_markup=wallet_menu(),
        )
        return

    # ---------------------------
    # Referral
    # ---------------------------

    if data == "my_referrals":
        await my_referrals(
            update,
            context,
        )
        return

    if data == "referral_back":
        await query.answer()

        await query.edit_message_text(
            "👥 *Referral Program*\n\n"
            "Use the buttons below:",
            parse_mode="Markdown",
            reply_markup=referral_keyboard(),
        )
        return

    # ---------------------------
    # Main back
    # ---------------------------

    if data == "main_back":
        await query.answer()

        await query.edit_message_text(
            "🌪️ Choose an option from the menu below."
        )

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="Main Menu 👇",
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------------------
    # Verify
    # ---------------------------

    if data == "verify_membership":
        await verify_membership(
            update,
            context,
        )
        return

    # ---------------------------
    # Withdraw
    # ---------------------------

    if data == "withdraw_usdt":
        await select_withdraw_method(
            update,
            context,
            "USDT",
        )
        return

    if data == "withdraw_cbe":
        await select_withdraw_method(
            update,
            context,
            "CBE",
        )
        return

    if data == "withdraw_telebirr":
        await select_withdraw_method(
            update,
            context,
            "Telebirr",
        )
        return

    if data == "withdraw_use_bybit":
        await withdraw_use_bybit(
            update,
            context,
        )
        return

    if data == "withdraw_use_bep20":
        await withdraw_use_bep20(
            update,
            context,
        )
        return

    if data == "withdraw_confirm":
        await confirm_withdraw(
            update,
            context,
        )
        return

    if data == "withdraw_cancel":
        await cancel_withdraw(
            update,
            context,
        )
        return

    if data == "withdraw_back":
        await query.answer()

        clear_state(
            query.from_user.id
        )

        await query.edit_message_text(
            "💸 *Withdraw*\n\n"
            "Choose your payment method:",
            parse_mode="Markdown",
            reply_markup=withdraw_menu(),
        )
        return

    # ---------------------------
    # Admin
    # ---------------------------

    if data.startswith("admin_approve_"):
        await admin_approve(
            update,
            context,
        )
        return

    if data.startswith("admin_reject_"):
        await admin_reject(
            update,
            context,
        )
        return

    await query.answer(
        "⚠️ Unknown action.",
        show_alert=True,
    )


# ============================================================
# TEXT ROUTER
# ============================================================

async def text_router(
    update,
    context,
):
    user = update.effective_user

    if not user or not update.message:
        return

    text = update.message.text.strip()

    # Active input state gets priority
    state = state_for(user.id)

    if state.get("action"):
        if state["action"].startswith("wallet_"):
            await handle_wallet_input(
                update,
                context,
            )
            return

        if state["action"] in (
            "withdraw_amount",
        ):
            await handle_withdraw_amount(
                update,
                context,
            )
            return

    # Main menu
    if text == "💰 Balance":
        await show_balance(
            update,
            context,
        )
        return

    if text == "🎯 Tasks":
        await show_tasks(
            update,
            context,
        )
        return

    if text == "👥 Referral":
        await show_referral(
            update,
            context,
        )
        return

    if text == "👛 Wallet":
        await show_wallet(
            update,
            context,
        )
        return

    if text == "💸 Withdraw":
        await show_withdraw(
            update,
            context,
        )
        return

    if text == "🆘 Support":
        await show_support(
            update,
            context,
        )
        return


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error,
    )

    try:
        if isinstance(update, Update):
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=(
                        "⚠️ A small technical issue occurred.\n"
                        "Please try again."
                    ),
                )
    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info(
        "Vortex Earn Bot is starting..."
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
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
            "balance",
            show_balance,
        )
    )

    application.add_handler(
        CommandHandler(
            "referral",
            show_referral
