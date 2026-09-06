import os
import json
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from html import escape

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from supabase import create_client, Client


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "AmanM_12").strip().lstrip("@")

PORT = int(os.getenv("PORT", "10000"))

RATE = Decimal("185")
REFERRAL_REWARD = Decimal("0.015")
REFERRAL_REWARD_ETB = REFERRAL_REWARD * RATE

FIRST_WITHDRAWAL_MIN = Decimal("0.12")
NORMAL_WITHDRAWAL_MIN = Decimal("0.50")

SUPPORT_USERNAME = "AmanM_12"

MANDATORY_CHANNELS = [
    ("Sheger Tech", "@Sheger_tech1"),
    ("Ethio Vortex", "@EthioVortex1"),
    ("Ethio Cash Flow", "@ethiocashflow"),
    ("Aman Money Lab", "@AmanMoneyLab07"),
]


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# SUPABASE
# =========================================================

supabase: Client | None = None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# =========================================================
# TEMPORARY USER STATES
# =========================================================

user_states = {}


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


BACK_KEYBOARD = ReplyKeyboardMarkup(
    [["🔙 Back"]],
    resize_keyboard=True,
)


# =========================================================
# BASIC HELPERS
# =========================================================

def now_utc():
    return datetime.now(timezone.utc).isoformat()


def dec(value):
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def fmt(value, places=8):
    number = dec(value)

    text = f"{number:.{places}f}".rstrip("0").rstrip(".")

    if "." not in text:
        return text

    return text


def user_name(user):
    if user.username:
        return f"@{user.username}"

    return user.first_name or "User"


def is_admin(update: Update):
    if not update.effective_user:
        return False

    user = update.effective_user

    if ADMIN_ID and user.id == ADMIN_ID:
        return True

    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        return True

    return False


def clear_state(user_id):
    user_states.pop(user_id, None)


# =========================================================
# DATABASE HELPERS
# =========================================================

def db_required():
    if supabase is None:
        raise RuntimeError("Supabase is not configured.")


def get_user(telegram_id):
    db_required()

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


def create_user(telegram_user, referred_by=None):
    db_required()

    data = {
        "telegram_id": telegram_user.id,
        "username": telegram_user.username or "",
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

    result = supabase.table("users").insert(data).execute()

    if result.data:
        return result.data[0]

    return get_user(telegram_user.id)


def ensure_user(telegram_user, referred_by=None):
    existing = get_user(telegram_user.id)

    if existing:
        # Keep username updated
        current_username = existing.get("username") or ""
        new_username = telegram_user.username or ""

        if current_username != new_username:
            supabase.table("users").update(
                {"username": new_username}
            ).eq(
                "telegram_id", telegram_user.id
            ).execute()

            existing["username"] = new_username

        return existing, False

    return create_user(telegram_user, referred_by), True


def update_user(telegram_id, data):
    db_required()

    return (
        supabase
        .table("users")
        .update(data)
        .eq("telegram_id", telegram_id)
        .execute()
    )


# =========================================================
# WALLET JSON
# =========================================================

def get_wallet_data(user):
    raw = user.get("wallet") or ""

    if not raw:
        return {}

    try:
        data = json.loads(raw)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_wallet_data(user_id, data):
    return update_user(
        user_id,
        {
            "wallet": json.dumps(data, ensure_ascii=False)
        },
    )


def wallet_has_bybit(user):
    wallet = get_wallet_data(user)

    return bool(
        wallet.get("bybit_uid")
    )


def wallet_has_bep20(user):
    wallet = get_wallet_data(user)

    return bool(
        wallet.get("bep20")
        or user.get("usdt_address")
    )


def wallet_has_cbe(user):
    return bool(
        user.get("bank_account")
        and user.get("bank_name")
    )


def wallet_has_telebirr(user):
    wallet = get_wallet_data(user)

    return bool(
        user.get("telebirr_number")
        and wallet.get("telebirr_name")
    )


# =========================================================
# CHANNEL CHECK
# =========================================================

async def is_member(bot, user_id, channel_username):
    try:
        member = await bot.get_chat_member(
            chat_id=channel_username,
            user_id=user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        logger.warning(
            "Membership check failed for %s: %s",
            channel_username,
            e,
        )
        return False


async def get_missing_channels(bot, user_id):
    missing = []

    for name, username in MANDATORY_CHANNELS:
        if not await is_member(bot, user_id, username):
            missing.append((name, username))

    return missing


def join_keyboard(missing=None):
    if missing is None:
        missing = MANDATORY_CHANNELS

    buttons = []

    for name, username in missing:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📢 Join {name}",
                    url=f"https://t.me/{username.lstrip('@')}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "✅ Verify Membership",
                callback_data="verify",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


# =========================================================
# WELCOME / ACCESS
# =========================================================

async def send_join_screen(update, context, missing=None):
    text = (
        "🌪️ <b>Welcome to Vortex Earn Bot!</b>\n\n"
        "💸 Earn rewards through referrals and available activities.\n\n"
        "🔐 Before using the bot, please join all required channels "
        "below, then press <b>Verify Membership</b>.\n\n"
        "👇 Join all channels:"
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(missing),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(missing),
        )


async def check_access(update, context):
    user = update.effective_user

    missing = await get_missing_channels(
        context.bot,
        user.id,
    )

    if missing:
        await send_join_screen(
            update,
            context,
            missing,
        )
        return False

    return True


# =========================================================
# REFERRAL SYSTEM
# =========================================================

async def process_referral_reward(user_id):
    """
    Gives the referral reward once, after successful verification.
    The referred_by field is cleared after rewarding.
    """

    user = get_user(user_id)

    if not user:
        return False

    referred_by = user.get("referred_by")

    if not referred_by:
        return False

    if int(referred_by) == int(user_id):
        update_user(
            user_id,
            {"referred_by": None},
        )
        return False

    referrer = get_user(int(referred_by))

    if not referrer:
        update_user(
            user_id,
            {"referred_by": None},
        )
        return False

    # Reward referrer
    old_balance = dec(referrer.get("balance"))
    old_etb = dec(referrer.get("balance_etb"))

    new_balance = old_balance + REFERRAL_REWARD
    new_etb = old_etb + REFERRAL_REWARD_ETB

    old_referrals = int(referrer.get("referrals") or 0)
    old_referral_count = int(
        referrer.get("referral_count") or 0
    )

    update_user(
        int(referred_by),
        {
            "balance": float(new_balance),
            "balance_etb": float(new_etb),
            "referrals": old_referrals + 1,
            "referral_count": old_referral_count + 1,
        },
    )

    # Clear referral source so it cannot be rewarded again
    update_user(
        user_id,
        {"referred_by": None},
    )

    try:
        await context_bot_send(
            referrer_id=int(referred_by),
            text=(
                "🎉 <b>New Referral!</b>\n\n"
                "👤 Someone joined using your referral link.\n\n"
                f"💰 Reward: <b>{fmt(REFERRAL_REWARD)} USDT</b>\n"
                f"🇪🇹 Value: <b>{fmt(REFERRAL_REWARD_ETB, 3)} ETB</b>\n\n"
                f"💵 Your new balance: <b>{fmt(new_balance)} USDT</b>"
            ),
        )
    except Exception as e:
        logger.warning(
            "Could not notify referrer: %s",
            e,
        )

    return True


# Global application reference for referral notifications
application_instance = None


async def context_bot_send(referrer_id, text):
    if application_instance is None:
        return

    await application_instance.bot.send_message(
        chat_id=referrer_id,
        text=text,
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = update.effective_user

    referred_by = None

    if context.args:
        ref_code = context.args[0].strip()

        if ref_code.startswith("ref_"):
            ref_code = ref_code[4:]

        try:
            referred_by = int(ref_code)
        except ValueError:
            referred_by = None

    if referred_by == telegram_user.id:
        referred_by = None

    try:
        user, is_new = ensure_user(
            telegram_user,
            referred_by=ref_by if False else referred_by,
        )

    except Exception as e:
        logger.exception("User creation error: %s", e)

        await update.message.reply_text(
            "⚠️ Temporary database error.\n"
            "Please try again in a moment."
        )
        return

    # Save referral source only for new users
    if (
        not is_new
        and referred_by
        and not user.get("referred_by")
        and user.get("telegram_id") != referred_by
    ):
        # Do not overwrite existing referral relationship
        pass

    missing = await get_missing_channels(
        context.bot,
        telegram_user.id,
    )

    if missing:
        await update.message.reply_text(
            "🌪️ <b>Welcome to Vortex Earn Bot!</b>\n\n"
            "🔐 Please join all required channels first.\n"
            "Then press <b>Verify Membership</b>.\n\n"
            "💰 After verification, your dashboard will unlock.",
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(missing),
        )
        return

    # User is verified
    if not user.get("is_verified"):
        update_user(
            telegram_user.id,
            {"is_verified": True},
        )

        await process_referral_reward(
            telegram_user.id
        )

    clear_state(telegram_user.id)

    await update.message.reply_text(
        "✅ <b>Verified successfully!</b>\n\n"
        "🌪️ Welcome to <b>Vortex Earn Bot</b>.\n"
        "Choose an option below:",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# VERIFY CALLBACK
# =========================================================

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user

    missing = await get_missing_channels(
        context.bot,
        user.id,
    )

    if missing:
        names = "\n".join(
            f"❌ {escape(name)}"
            for name, _ in missing
        )

        await query.message.reply_text(
            "⚠️ <b>Verification failed.</b>\n\n"
            "You still need to join:\n\n"
            f"{names}\n\n"
            "Join them and press Verify again.",
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(missing),
        )
        return

    update_user(
        user.id,
        {"is_verified": True},
    )

    rewarded = await process_referral_reward(
        user.id
    )

    clear_state(user.id)

    if rewarded:
        extra = (
            "\n🎁 Your referrer received their referral reward."
        )
    else:
        extra = ""

    await query.message.reply_text(
        "✅ <b>Verification successful!</b>\n\n"
        "🌪️ Your Vortex Earn dashboard is now unlocked."
        f"{extra}",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    user = get_user(update.effective_user.id)

    if not user:
        await update.message.reply_text(
            "⚠️ User not found. Please use /start."
        )
        return

    usdt = dec(user.get("balance"))
    etb = dec(user.get("balance_etb"))

    await update.message.reply_text(
        "💰 <b>Balance</b>\n\n"
        f"🪙 USDT = <b>{fmt(usdt)} USDT</b>\n"
        f"🇪🇹 ETB = <b>{fmt(etb, 2)} ETB</b>\n\n"
        f"💱 Rate: <b>1 USDT = {fmt(RATE, 0)} ETB</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    user = get_user(update.effective_user.id)

    if not user:
        return

    bot_username = context.bot.username

    referral_link = (
        f"https://t.me/{bot_username}?start={user['telegram_id']}"
    )

    count = int(user.get("referral_count") or 0)

    await update.message.reply_text(
        "👥 <b>Referral Program</b>\n\n"
        f"👤 Your referrals: <b>{count}</b>\n\n"
        f"🎁 Reward per referral: <b>{fmt(REFERRAL_REWARD)} USDT</b>\n"
        f"🇪🇹 Equivalent: <b>{fmt(REFERRAL_REWARD_ETB, 3)} ETB</b>\n"
        f"💱 Rate: <b>1 USDT = {fmt(RATE, 0)} ETB</b>\n\n"
        "🔗 <b>Your referral link:</b>\n"
        f"<code>{escape(referral_link)}</code>\n\n"
        "📌 Share the link and earn when a new user joins "
        "and successfully verifies membership.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# TASKS
# =========================================================

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Promotion Service",
                    url=f"https://t.me/{SUPPORT_USERNAME}",
                )
            ]
        ]
    )

    await update.message.reply_text(
        "🎯 <b>Tasks</b>\n\n"
        "🚧 Automated earning tasks are currently being prepared.\n\n"
        "📢 <b>Promotion Service</b>\n"
        "If you want to promote a Telegram channel, bot, "
        "product or service, contact the admin for available "
        "promotion options and commission details.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================================================
# WALLET MAIN
# =========================================================

def wallet_main_keyboard():
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


async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    clear_state(update.effective_user.id)

    await update.message.reply_text(
        "👛 <b>Wallet</b>\n\n"
        "Choose the payment method you want to save.\n\n"
        "💵 USDT — Bybit UID / Account ID or BEP20 address\n"
        "🏦 CBE — Account number + account name\n"
        "📱 Telebirr — Phone number + name",
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_main_keyboard(),
    )


# =========================================================
# WALLET CALLBACKS
# =========================================================

async def wallet_usdt(update, context):
    query = update.callback_query
    await query.answer()

    clear_state(update.effective_user.id)

    await query.message.reply_text(
        "💵 <b>USDT Wallet</b>\n\n"
        "Choose what you want to save:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🟢 Bybit UID / Account ID",
                        callback_data="wallet_bybit",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🟢 BEP20 USDT Address",
                        callback_data="wallet_bep20",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="wallet_back",
                    )
                ],
            ]
        ),
    )


async def wallet_bybit(update, context):
    query = update.callback_query
    await query.answer()

    user_states[update.effective_user.id] = {
        "state": "wallet_bybit"
    }

    await query.message.reply_text(
        "🟢 <b>Bybit UID / Account ID</b>\n\n"
        "Send your Bybit UID or Account ID below.\n\n"
        "🔙 Press Back to cancel.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def wallet_bep20(update, context):
    query = update.callback_query
    await query.answer()

    user_states[update.effective_user.id] = {
        "state": "wallet_bep20"
    }

    await query.message.reply_text(
        "🟢 <b>BEP20 USDT Address</b>\n\n"
        "Send your BEP20 USDT wallet address below.\n\n"
        "⚠️ Make sure the address is correct before saving.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def wallet_cbe(update, context):
    query = update.callback_query
    await query.answer()

    user_states[update.effective_user.id] = {
        "state": "wallet_cbe_account"
    }

    await query.message.reply_text(
        "🏦 <b>CBE Wallet</b>\n\n"
        "Step 1/2\n\n"
        "Send your CBE account number.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def wallet_telebirr(update, context):
    query = update.callback_query
    await query.answer()

    user_states[update.effective_user.id] = {
        "state": "wallet_telebirr_phone"
    }

    await query.message.reply_text(
        "📱 <b>Telebirr Wallet</b>\n\n"
        "Step 1/2\n\n"
        "Send your Telebirr phone number.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def wallet_back(update, context):
    query = update.callback_query
    await query.answer()

    clear_state(update.effective_user.id)

    await query.message.reply_text(
        "👛 <b>Wallet</b>\n\n"
        "Choose a payment method:",
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_main_keyboard(),
    )


# =========================================================
# WITHDRAWAL
# =========================================================

def withdrawal_minimum(user):
    count = int(user.get("withdrawal_count") or 0)

    if count < 2:
        return FIRST_WITHDRAWAL_MIN

    return NORMAL_WITHDRAWAL_MIN


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


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    clear_state(update.effective_user.id)

    user = get_user(update.effective_user.id)

    minimum = withdrawal_minimum(user)

    await update.message.reply_text(
        "💸 <b>Withdraw</b>\n\n"
        f"💰 Available: <b>{fmt(user.get('balance'))} USDT</b>\n"
        f"🇪🇹 Value: <b>{fmt(user.get('balance_etb'), 2)} ETB</b>\n\n"
        f"📌 Minimum withdrawal: <b>{fmt(minimum)} USDT</b>\n"
        f"💱 Rate: <b>1 USDT = {fmt(RATE, 0)} ETB</b>\n\n"
        "Choose your payment method:",
        parse_mode=ParseMode.HTML,
        reply_markup=withdraw_keyboard(),
    )


# =========================================================
# WITHDRAWAL METHOD CALLBACKS
# =========================================================

async def withdraw_usdt(update, context):
    query = update.callback_query
    await query.answer()

    user = get_user(update.effective_user.id)

    if not wallet_has_bybit(user) and not wallet_has_bep20(user):
        await query.message.reply_text(
            "⚠️ <b>USDT wallet not found.</b>\n\n"
            "Please save either your Bybit UID / Account ID "
            "or BEP20 USDT address in Wallet first.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👛 Open Wallet",
                            callback_data="wallet_from_withdraw",
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

    await start_withdraw_amount(
        query,
        "USDT",
    )


async def withdraw_cbe(update, context):
    query = update.callback_query
    await query.answer()

    user = get_user(update.effective_user.id)

    if not wallet_has_cbe(user):
        await query.message.reply_text(
            "⚠️ <b>CBE wallet not found.</b>\n\n"
            "Please save your CBE account number and account name "
            "in Wallet first.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👛 Open Wallet",
                            callback_data="wallet_from_withdraw",
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

    await start_withdraw_amount(
        query,
        "CBE",
    )


async def withdraw_telebirr(update, context):
    query = update.callback_query
    await query.answer()

    user = get_user(update.effective_user.id)

    if not wallet_has_telebirr(user):
        await query.message.reply_text(
            "⚠️ <b>Telebirr wallet not found.</b>\n\n"
            "Please save your Telebirr phone number and name "
            "in Wallet first.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👛 Open Wallet",
                            callback_data="wallet_from_withdraw",
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

    await start_withdraw_amount(
        query,
        "Telebirr",
    )


async def withdraw_back(update, context):
    query = update.callback_query
    await query.answer()

    clear_state(update.effective_user.id)

    await query.message.reply_text(
        "💸 <b>Withdraw</b>\n\n"
        "Choose a payment method:",
        parse_mode=ParseMode.HTML,
        reply_markup=withdraw_keyboard(),
    )


async def wallet_from_withdraw(update, context):
    query = update.callback_query
    await query.answer()

    clear_state(update.effective_user.id)

    await query.message.reply_text(
        "👛 <b>Wallet</b>\n\n"
        "Choose the wallet method you want to save:",
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_main_keyboard(),
    )


async def start_withdraw_amount(query, method):
    user_id = query.from_user.id

    user_states[user_id] = {
        "state": "withdraw_amount",
        "method": method,
    }

    user = get_user(user_id)

    minimum = withdrawal_minimum(user)

    await query.message.reply_text(
        f"💸 <b>{escape(method)} Withdrawal</b>\n\n"
        f"💰 Available: <b>{fmt(user.get('balance'))} USDT</b>\n"
        f"📌 Minimum: <b>{fmt(minimum)} USDT</b>\n\n"
        "✍️ Enter the amount you want to withdraw.\n\n"
        "Example: <code>0.12</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


# =========================================================
# MESSAGE INPUT HANDLER
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    if text == "🔙 Back":
        clear_state(user.id)

        await update.message.reply_text(
            "↩️ Cancelled.",
            reply_markup=MAIN_MENU,
        )
        return

    state_data = user_states.get(user.id)

    if state_data:
        state = state_data.get("state")

        if state == "wallet_bybit":
            await save_bybit(update, text)
            return

        if state == "wallet_bep20":
            await save_bep20(update, text)
            return

        if state == "wallet_cbe_account":
            await save_cbe_account(update, text)
            return

        if state == "wallet_cbe_name":
            await save_cbe_name(update, text)
            return

        if state == "wallet_telebirr_phone":
            await save_telebirr_phone(update, text)
            return

        if state == "wallet_telebirr_name":
            await save_telebirr_name(update, text)
            return

        if state == "withdraw_amount":
            await handle_withdraw_amount(update, text)
            return

    # Main menu text
    if text == "💰 Balance":
        await balance(update, context)

    elif text == "🎯 Tasks":
        await tasks(update, context)

    elif text == "👥 Referral":
        await referral(update, context)

    elif text == "👛 Wallet":
        await wallet(update, context)

    elif text == "💸 Withdraw":
        await withdraw(update, context)

    elif text == "🆘 Support":
        await update.message.reply_text(
            "🆘 <b>Support</b>\n\n"
            "Need help? Contact the admin:\n"
            f"👉 @{SUPPORT_USERNAME}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💬 Contact Support",
                            url=f"https://t.me/{SUPPORT_USERNAME}",
                        )
                    ]
                ]
            ),
        )


# =========================================================
# WALLET SAVE FUNCTIONS
# =========================================================

async def save_bybit(update, text):
    if len(text) < 3:
        await update.message.reply_text(
            "⚠️ Please enter a valid Bybit UID / Account ID."
        )
        return

    user = get_user(update.effective_user.id)

    data = get_wallet_data(user)

    data["bybit_uid"] = text

    save_wallet_data(
        update.effective_user.id,
        data,
    )

    update_user(
        update.effective_user.id,
        {
            "last_withdrawal_method": "USDT",
        },
    )

    clear_state(update.effective_user.id)

    await update.message.reply_text(
        "✅ <b>Bybit UID / Account ID saved.</b>\n\n"
        "Your USDT withdrawal wallet has been updated.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


async def save_bep20(update, text):
    if len(text) < 20:
        await update.message.reply_text(
            "⚠️ That address looks too short.\n"
            "Please send your BEP20 USDT address."
        )
        return

    user = get_user(update.effective_user.id)

    data = get_wallet_data(user)

    data["bep20"] = text

    save_wallet_data(
        update.effective_user.id,
        data,
    )

    update_user(
        update.effective_user.id,
        {
            "usdt_address": text,
            "last_withdrawal_method": "USDT",
        },
    )

    clear_state(update.effective_user.id)

    await update.message.reply_text(
        "✅ <b>BEP20 USDT address saved.</b>\n\n"
        "Your USDT withdrawal wallet has been updated.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


async def save_cbe_account(update, text):
    if len(text) < 4:
        await update.message.reply_text(
            "⚠️ Please enter a valid CBE account number."
        )
        return

    user_states[update.effective_user.id] = {
        "state": "wallet_cbe_name",
        "account": text,
    }

    await update.message.reply_text(
        "🏦 <b>CBE Wallet</b>\n\n"
        "Step 2/2\n\n"
        "Send the account holder's name.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def save_cbe_name(update, text):
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Please enter the account holder's name."
        )
        return

    state_data = user_states.get(
        update.effective_user.id,
        {},
    )

    account = state_data.get("account")

    update_user(
        update.effective_user.id,
        {
            "bank_account": account,
            "bank_name": text,
            "last_withdrawal_method": "CBE",
        },
    )

    clear_state(update.effective_user.id)

    await update.message.reply_text(
        "✅ <b>CBE wallet saved.</b>\n\n"
        "Account number and account name have been saved.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


async def save_telebirr_phone(update, text):
    digits = "".join(
        character for character in text
        if character.isdigit()
    )

    if len(digits) < 9:
        await update.message.reply_text(
            "⚠️ Please enter a valid Telebirr phone number."
        )
        return

    user_states[update.effective_user.id] = {
        "state": "wallet_telebirr_name",
        "phone": text,
    }

    await update.message.reply_text(
        "📱 <b>Telebirr Wallet</b>\n\n"
        "Step 2/2\n\n"
        "Send the account holder's name.",
        parse_mode=ParseMode.HTML,
        reply_markup=BACK_KEYBOARD,
    )


async def save_telebirr_name(update, text):
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Please enter the account holder's name."
        )
        return

    state_data = user_states.get(
        update.effective_user.id,
        {},
    )

    phone = state_data.get("phone")

    user = get_user(update.effective_user.id)

    data = get_wallet_data(user)

    data["telebirr_name"] = text

    save_wallet_data(
        update.effective_user.id,
        data,
    )

    update_user(
        update.effective_user.id,
        {
            "telebirr_number": phone,
            "last_withdrawal_method": "Telebirr",
        },
    )

    clear_state(update.effective_user.id)

    await update.message.reply_text(
        "✅ <b>Telebirr wallet saved.</b>\n\n"
        "Phone number and name have been saved.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# WITHDRAW AMOUNT
# =========================================================

async def handle_withdraw_amount(update, text):
    user_id = update.effective_user.id

    state_data = user_states.get(user_id, {})

    method = state_data.get("method")

    try:
        amount = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text(
            "⚠️ Please enter a valid number.\n\n"
            "Example: 0.12"
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "⚠️ Amount must be greater than 0."
        )
        return

    user = get_user(user_id)

    balance_usdt = dec(user.get("balance"))

    minimum = withdrawal_minimum(user)

    if amount < minimum:
        await update.message.reply_text(
            f"⚠️ Minimum withdrawal is "
            f"<b>{fmt(minimum)} USDT</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if amount > balance_usdt:
        await update.message.reply_text(
            "⚠️ <b>Insufficient balance.</b>\n\n"
            f"Available: <b>{fmt(balance_usdt)} USDT</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Prevent multiple pending requests
    try:
        pending = (
            supabase
            .table("withdrawal_requests")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )

        if pending.data:
            await update.message.reply_text(
                "⚠️ You already have a pending withdrawal.\n\n"
                "Please wait until it is processed before creating "
                "another request.",
                reply_markup=MAIN_MENU,
            )
            clear_state(user_id)
            return

    except Exception as e:
        logger.warning(
            "Pending withdrawal check failed: %s",
            e,
        )

    amount_etb = amount * RATE

    user_states[user_id] = {
        "state": "withdraw_confirm",
        "method": method,
        "amount": str(amount),
        "amount_etb": str(amount_etb),
    }

    await update.message.reply_text(
        "🔎 <b>Confirm Withdrawal</b>\n\n"
        f"💳 Method: <b>{escape(method)}</b>\n"
        f"💰 Amount: <b>{fmt(amount)} USDT</b>\n"
        f"🇪🇹 Value: <b>{fmt(amount_etb, 2)} ETB</b>\n"
        f"💱 Rate: <b>1 USDT = {fmt(RATE, 0)} ETB</b>\n\n"
        "⚠️ The request will be sent for manual processing.",
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


# =========================================================
# WITHDRAW CONFIRM / CANCEL
# =========================================================

def get_payment_details(user, method):
    wallet = get_wallet_data(user)

    if method == "USDT":
        bybit = wallet.get("bybit_uid")

        if bybit:
            return f"Bybit UID / Account ID: {bybit}"

        bep20 = wallet.get("bep20") or user.get("usdt_address")

        if bep20:
            return f"BEP20 USDT Address: {bep20}"

    if method == "CBE":
        return (
            f"Account: {user.get('bank_account')}\n"
            f"Name: {user.get('bank_name')}"
        )

    if method == "Telebirr":
        return (
            f"Phone: {user.get('telebirr_number')}\n"
            f"Name: {wallet.get('telebirr_name')}"
        )

    return ""


async def withdraw_confirm(update, context):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    state_data = user_states.get(user_id)

    if not state_data:
        await query.message.reply_text(
            "⚠️ Withdrawal session expired. Please try again.",
            reply_markup=MAIN_MENU,
        )
        return

    method = state_data.get("method")
    amount = dec(state_data.get("amount"))
    amount_etb = dec(state_data.get("amount_etb"))

    user = get_user(user_id)

    if not user:
        clear_state(user_id)

        await query.message.reply_text(
            "⚠️ User not found.",
            reply_markup=MAIN_MENU,
        )
        return

    # Re-check balance before creating request
    balance_usdt = dec(user.get("balance"))

    if amount > balance_usdt:
        clear_state(user_id)

        await query.message.reply_text(
            "⚠️ Your balance has changed.\n"
            "Please try again.",
            reply_markup=MAIN_MENU,
        )
        return

    payment_details = get_payment_details(
        user,
        method,
    )

    if not payment_details:
        clear_state(user_id)

        await query.message.reply_text(
            "⚠️ Payment details are missing.\n"
            "Please update your Wallet first.",
            reply_markup=MAIN_MENU,
        )
        return

    try:
        pending = (
            supabase
            .table("withdrawal_requests")
            .select("id")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )

        if pending.data:
            clear_state(user_id)

            await query.message.reply_text(
                "⚠️ You already have a pending withdrawal.",
                reply_markup=MAIN_MENU,
            )
            return

    except Exception as e:
        logger.warning(
            "Pending request re-check failed: %s",
            e,
        )

    try:
        result = (
            supabase
            .table("withdrawal_requests")
            .insert(
                {
                    "user_id": user_id,
                    "amount_usdt": float(amount),
                    "amount_etb": float(amount_etb),
                    "method": method,
                    "payment_details": payment_details,
                    "status": "pending",
                }
            )
            .execute()
        )

        request_id = (
            result.data[0]["id"]
            if result.data
            else "Unknown"
        )

    except Exception as e:
        logger.exception(
            "Withdrawal creation error: %s",
            e,
        )

        await query.message.reply_text(
            "❌ Could not create the withdrawal request.\n"
            "Please try again later.",
            reply_markup=MAIN_MENU,
        )
        return

    clear_state(user_id)

    await query.message.reply_text(
        "✅ <b>Withdrawal request submitted!</b>\n\n"
        f"🆔 Request ID: <code>{request_id}</code>\n"
        f"💳 Method: <b>{escape(method)}</b>\n"
        f"💰 Amount: <b>{fmt(amount)} USDT</b>\n"
        f"🇪🇹 Value: <b>{fmt(amount_etb, 2)} ETB</b>\n\n"
        "⏳ Status: <b>Pending</b>\n"
        "💡 Payment is processed manually after review.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )

    # Notify admin
    try:
        if ADMIN_ID:
            username_text = (
                f"@{user['username']}"
                if user.get("username")
                else "No username"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "💸 <b>New Withdrawal Request</b>\n\n"
                    f"🆔 Request ID: <code>{request_id}</code>\n"
                    f"👤 User: {escape(username_text)}\n"
                    f"🆔 Telegram ID: <code>{user_id}</code>\n"
                    f"💳 Method: <b>{escape(method)}</b>\n"
                    f"💰 Amount: <b>{fmt(amount)} USDT</b>\n"
                    f"🇪🇹 Value: <b>{fmt(amount_etb, 2)} ETB</b>\n\n"
                    f"📌 Payment details:\n"
                    f"<code>{escape(payment_details)}</code>"
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

    except Exception as e:
        logger.warning(
            "Admin notification failed: %s",
            e,
        )


async def withdraw_cancel(update, context):
    query = update.callback_query
    await query.answer()

    clear_state(update.effective_user.id)

    await query.message.reply_text(
        "❌ Withdrawal cancelled.",
        reply_markup=MAIN_MENU,
    )


# =========================================================
# ADMIN WITHDRAWAL ACTIONS
# =========================================================

async def admin_approve(update, context):
    query = update.callback_query

    if not is_admin(update):
        await query.answer(
            "⛔ Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    try:
        request_id = int(
            query.data.replace(
                "admin_approve_",
                "",
            )
        )
    except ValueError:
        await query.message.reply_text(
            "⚠️ Invalid request ID."
        )
        return

    try:
        result = (
            supabase
            .table("withdrawal_requests")
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            await query.message.reply_text(
                "⚠️ Withdrawal request not found."
            )
            return

        request = result.data[0]

        if request.get("status") != "pending":
            await query.message.reply_text(
                "⚠️ This request has already been processed."
            )
            return

        user_id = int(request["user_id"])

        user = get_user(user_id)

        if not user:
            await query.message.reply_text(
                "⚠️ User not found."
            )
            return

        amount = dec(request.get("amount_usdt"))
        amount_etb = dec(request.get("amount_etb"))

        balance = dec(user.get("balance"))

        if amount > balance:
            await query.message.reply_text(
                "❌ User balance is insufficient for this request."
            )
            return

        new_balance = balance - amount

        current_etb = dec(user.get("balance_etb"))

        new_etb = current_etb - amount_etb

        if new_etb < 0:
            new_etb = Decimal("0")

        withdrawal_count = int(
            user.get("withdrawal_count") or 0
        )

        total_usdt = (
            dec(user.get("total_withdrawn_usdt"))
            + amount
        )

        total_etb = (
            dec(user.get("total_withdrawn_etb"))
            + amount_etb
        )

        update_user(
            user_id,
            {
                "balance": float(new_balance),
                "balance_etb": float(new_etb),
                "withdrawal_count": withdrawal_count + 1,
                "total_withdrawn_usdt": float(total_usdt),
                "total_withdrawn_etb": float(total_etb),
            },
        )

        supabase.table(
            "withdrawal_requests"
        ).update(
            {
                "status": "approved",
                "processed_at": now_utc(),
            }
        ).eq(
            "id",
            request_id,
        ).execute()

        await query.message.reply_text(
            "✅ <b>Withdrawal approved.</b>\n\n"
            f"🆔 Request: <code>{request_id}</code>\n"
            f"💰 Amount: <b>{fmt(amount)} USDT</b>",
            parse_mode=ParseMode.HTML,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ <b>Withdrawal Approved</b>\n\n"
                    f"💰 Amount: <b>{fmt(amount)} USDT</b>\n"
                    f"🇪🇹 Value: <b>{fmt(amount_etb, 2)} ETB</b>\n\n"
                    "Your withdrawal has been approved and processed manually."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(
                "Could not notify user about approval: %s",
                e,
            )

    except Exception as e:
        logger.exception(
            "Admin approve error: %s",
            e,
        )

        await query.message.reply_text(
            "❌ Error while approving the request."
        )


async def admin_reject(update, context):
    query = update.callback_query

    if not is_admin(update):
        await query.answer(
            "⛔ Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    try:
        request_id = int(
            query.data.replace(
                "admin_reject_",
                "",
            )
        )
    except ValueError:
        await query.message.reply_text(
            "⚠️ Invalid request ID."
        )
        return

    try:
        result = (
            supabase
            .table("withdrawal_requests")
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            await query.message.reply_text(
                "⚠️ Request not found."
            )
            return

        request = result.data[0]

        if request.get("status") != "pending":
            await query.message.reply_text(
                "⚠️ This request has already been processed."
            )
            return

        user_id = int(request["user_id"])

        supabase.table(
            "withdrawal_requests"
        ).update(
            {
                "status": "rejected",
                "processed_at": now_utc(),
            }
        ).eq(
            "id",
            request_id,
        ).execute()

        await query.message.reply_text(
            "❌ <b>Withdrawal rejected.</b>\n\n"
            f"🆔 Request: <code>{request_id}</code>\n"
            "💰 User balance was not deducted.",
            parse_mode=ParseMode.HTML,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ <b>Withdrawal Rejected</b>\n\n"
                    f"💰 Amount: <b>{fmt(request.get('amount_usdt'))} USDT</b>\n\n"
                    "Your balance was not deducted."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(
                "Could not notify user about rejection: %s",
                e,
            )

    except Exception as e:
        logger.exception(
            "Admin reject error: %s",
            e,
        )

        await query.message.reply_text(
            "❌ Error while rejecting the request."
        )


# =========================================================
# WITHDRAWAL HISTORY
# =========================================================

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    user_id = update.effective_user.id

    try:
        result = (
            supabase
            .table("withdrawal_requests")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )

    except Exception as e:
        logger.exception(
            "History error: %s",
            e,
        )

        await update.message.reply_text(
            "⚠️ Could not load withdrawal history."
        )
        return

    if not result.data:
        await update.message.reply_text(
            "📋 <b>Withdrawal History</b>\n\n"
            "No withdrawal requests yet.",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    lines = [
        "📋 <b>Withdrawal History</b>\n"
    ]

    for item in result.data:
        request_id = item.get("id")
        amount = fmt(item.get("amount_usdt"))
        method = escape(
            str(item.get("method") or "")
        )
        status = escape(
            str(item.get("status") or "").title()
        )

        lines.append(
            f"🆔 <code>{request_id}</code> | "
            f"{method} | <b>{amount} USDT</b>\n"
            f"Status: <b>{status}</b>\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

async def admin_dashboard(update, context):
    if not is_admin(update):
        await update.message.reply_text(
            "⛔ Admin only."
        )
        return

    try:
        users_result = (
            supabase
            .table("users")
            .select("telegram_id", count="exact")
            .execute()
        )

        pending_result = (
            supabase
            .table("withdrawal_requests")
            .select("id", count="exact")
            .eq("status", "pending")
            .execute()
        )

        approved_result = (
            supabase
            .table("withdrawal_requests")
            .select("id", count="exact")
            .eq("status", "approved")
            .execute()
        )

        rejected_result = (
            supabase
            .table("withdrawal_requests")
            .select("id", count="exact")
            .eq("status", "rejected")
            .execute()
        )

        users_count = users_result.count or 0
        pending_count = pending_result.count or 0
        approved_count = approved_result.count or 0
        rejected_count = rejected_result.count or 0

    except Exception as e:
        logger.exception(
            "Admin dashboard error: %s",
            e,
        )

        await update.message.reply_text(
            "❌ Could not load admin dashboard."
        )
        return

    await update.message.reply_text(
        "🛠️ <b>Vortex Earn Admin</b>\n\n"
        f"👥 Users: <b>{users_count}</b>\n"
        f"⏳ Pending withdrawals: <b>{pending_count}</b>\n"
        f"✅ Approved: <b>{approved_count}</b>\n"
        f"❌ Rejected: <b>{rejected_count}</b>\n\n"
        "Use the buttons in withdrawal notifications to "
        "approve or reject requests.",
        parse_mode=ParseMode.HTML,
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    global application_instance

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL or SUPABASE_KEY is missing."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application_instance = application

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("balance", balance)
    )

    application.add_handler(
        CommandHandler("referral", referral)
    )

    application.add_handler(
        CommandHandler("history", history)
    )

    application.add_handler(
        CommandHandler("admin", admin_dashboard)
    )

    # Callback buttons
    application.add_handler(
        CallbackQueryHandler(
            verify_callback,
            pattern=r"^verify$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_usdt,
            pattern=r"^wallet_usdt$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_bybit,
            pattern=r"^wallet_bybit$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_bep20,
            pattern=r"^wallet_bep20$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_cbe,
            pattern=r"^wallet_cbe$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_telebirr,
            pattern=r"^wallet_telebirr$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_back,
            pattern=r"^wallet_back$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            wallet_from_withdraw,
            pattern=r"^wallet_from_withdraw$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_usdt,
            pattern=r"^withdraw_usdt$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_cbe,
            pattern=r"^withdraw_cbe$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_telebirr,
            pattern=r"^withdraw_telebirr$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_back,
            pattern=r"^withdraw_back$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_confirm,
            pattern=r"^withdraw_confirm$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            withdraw_cancel,
            pattern=r"^withdraw_cancel$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_approve,
            pattern=r"^admin_approve_\d+$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_reject,
            pattern=r"^admin_reject_\d+$",
        )
    )

    # Text messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Vortex Earn Bot is starting..."
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=(
            f"https://vortex-earn-bot.onrender.com/{TOKEN}"
        ),
    )


if __name__ == "__main__":
    main()
