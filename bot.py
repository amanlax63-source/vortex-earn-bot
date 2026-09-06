import os
import re
import html
import logging
from datetime import datetime, timezone

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


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

PORT = int(os.getenv("PORT", "10000"))

# Put your Telegram numeric admin ID in Render:
# ADMIN_ID=123456789
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

RATE = 185.0

REFERRAL_REWARD_USDT = 0.015
REFERRAL_REWARD_ETB = REFERRAL_REWARD_USDT * RATE

FIRST_MIN_WITHDRAW_USDT = 0.12
LATER_MIN_WITHDRAW_USDT = 0.50

MANDATORY_CHANNELS = [
    "@Sheger_tech1",
    "@EthioVortex1",
    "@ethiocashflow",
    "@AmanMoneyLab07",
]

SUPPORT_USERNAME = "@AmanM_12"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


if not TOKEN:
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


def back_keyboard(callback_data="main_back"):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data=callback_data,
                )
            ]
        ]
    )


def join_keyboard():
    buttons = []

    for channel in MANDATORY_CHANNELS:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📢 Join {channel}",
                    url=f"https://t.me/{channel.lstrip('@')}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "✅ Verify",
                callback_data="verify_channels",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


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
                    callback_data="wallet_main_back",
                )
            ],
        ]
    )


def wallet_usdt_keyboard():
    return InlineKeyboardMarkup(
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
    )


def wallet_edit_keyboard(method):
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


def withdraw_back_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="withdraw_back",
                )
            ]
        ]
    )


def confirm_withdraw_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm",
                    callback_data="confirm_withdraw",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="cancel_withdraw",
                ),
            ]
        ]
    )


def admin_withdraw_keyboard(request_id):
    return InlineKeyboardMarkup(
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
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_user(telegram_id):
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


def ensure_wallet_json(user):
    value = user.get("wallet")

    if isinstance(value, dict):
        return value

    return {}


def save_user_wallet(telegram_id, wallet_data):
    return (
        supabase
        .table("users")
        .update(
            {
                "wallet": wallet_data,
            }
        )
        .eq("telegram_id", telegram_id)
        .execute()
    )


def create_user(telegram_id, username=None, referred_by=None):
    data = {
        "telegram_id": telegram_id,
        "username": username,
        "balance": 0,
        "referrals": 0,
        "wallet": {},
        "withdrawal_count": 0,
        "total_withdrawn_usdt": 0,
        "total_withdrawn_etb": 0,
        "referred_by": referred_by,
        "referral_count": 0,
        "currency": "USDT",
        "balance_etb": 0,
        "usdt_address": None,
        "telebirr_number": None,
        "bank_name": None,
        "bank_account": None,
        "last_withdrawal_method": None,
        "is_verified": False,
    }

    result = (
        supabase
        .table("users")
        .insert(data)
        .execute()
    )

    if result.data:
        return result.data[0]

    return get_user(telegram_id)


def ensure_user(telegram_id, username=None, referred_by=None):
    user = get_user(telegram_id)

    if user:
        if username != user.get("username"):
            try:
                supabase.table("users").update(
                    {"username": username}
                ).eq(
                    "telegram_id", telegram_id
                ).execute()
            except Exception:
                pass

        return get_user(telegram_id)

    return create_user(
        telegram_id,
        username,
        referred_by,
    )


# ============================================================
# CHANNEL VERIFICATION
# ============================================================

async def check_channel_membership(
    context,
    telegram_id,
    channel,
):
    try:
        member = await context.bot.get_chat_member(
            chat_id=channel,
            user_id=telegram_id,
        )

        return member.status in [
            "member",
            "administrator",
            "creator",
        ]

    except Exception as e:
        logger.warning(
            "Channel check failed for %s: %s",
            channel,
            e,
        )
        return False


async def get_missing_channels(
    context,
    telegram_id,
):
    missing = []

    for channel in MANDATORY_CHANNELS:
        joined = await check_channel_membership(
            context,
            telegram_id,
            channel,
        )

        if not joined:
            missing.append(channel)

    return missing


async def show_join_required(
    update,
    context,
):
    text = (
        "🔒 <b>Verification Required</b>\n\n"
        "To use Vortex Earn Bot, you must join all "
        "required channels below.\n\n"
        "👇 Join all channels, then press <b>Verify</b>."
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


# ============================================================
# REFERRAL
# ============================================================

def extract_referrer(args):
    if not args:
        return None

    value = args[0]

    if value.startswith("ref_"):
        value = value[4:]

    try:
        return int(value)
    except Exception:
        return None


async def reward_referrer(
    context,
    referred_user_id,
):
    user = get_user(referred_user_id)

    if not user:
        return

    referrer_id = user.get("referred_by")

    if not referrer_id:
        return

    if int(referrer_id) == int(referred_user_id):
        return

    referrer = get_user(int(referrer_id))

    if not referrer:
        return

    wallet = ensure_wallet_json(referrer)

    # Prevent duplicate reward.
    if wallet.get("_referral_rewarded_for") is not None:
        rewarded_list = wallet.get("_referral_rewarded_for")

        if not isinstance(rewarded_list, list):
            rewarded_list = []

        if referred_user_id in rewarded_list:
            return

    else:
        rewarded_list = []

    balance = float(referrer.get("balance") or 0)
    balance_etb = float(referrer.get("balance_etb") or 0)
    referral_count = int(
        referrer.get("referral_count") or 0
    )
    referrals = int(
        referrer.get("referrals") or 0
    )

    new_balance = balance + REFERRAL_REWARD_USDT
    new_balance_etb = balance_etb + REFERRAL_REWARD_ETB

    rewarded_list.append(referred_user_id)

    wallet["_referral_rewarded_for"] = rewarded_list

    update_data = {
        "balance": new_balance,
        "balance_etb": new_balance_etb,
        "referral_count": referral_count + 1,
        "referrals": referrals + 1,
        "wallet": wallet,
    }

    try:
        supabase.table("users").update(
            update_data
        ).eq(
            "telegram_id",
            int(referrer_id),
        ).execute()

        try:
            await context.bot.send_message(
                chat_id=int(referrer_id),
                text=(
                    "🎉 <b>Referral Reward!</b>\n\n"
                    f"👤 Your referral completed verification.\n"
                    f"💰 Reward: <b>{REFERRAL_REWARD_USDT:.3f} USDT</b>\n"
                    f"🇪🇹 Value: <b>{REFERRAL_REWARD_ETB:.3f} ETB</b>\n\n"
                    "The reward has been added to your balance."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception(
            "Referral reward error: %s",
            e,
        )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_tg = update.effective_user

    referrer_id = extract_referrer(
        context.args
    )

    if referrer_id == user_tg.id:
        referrer_id = None

    user = get_user(user_tg.id)

    if not user:
        user = create_user(
            user_tg.id,
            user_tg.username,
            referrer_id,
        )

    missing = await get_missing_channels(
        context,
        user_tg.id,
    )

    if missing:
        await show_join_required(
            update,
            context,
        )
        return

    # Mark verified.
    if not user.get("is_verified"):
        try:
            supabase.table("users").update(
                {
                    "is_verified": True,
                }
            ).eq(
                "telegram_id",
                user_tg.id,
            ).execute()

            await reward_referrer(
                context,
                user_tg.id,
            )

        except Exception as e:
            logger.warning(
                "Verification update error: %s",
                e,
            )

    text = (
        "🌪️ <b>Welcome to Vortex Earn Bot!</b>\n\n"
        "💸 Earn rewards by completing available tasks.\n"
        "👥 Invite friends and earn referral rewards.\n"
        "💰 Withdraw your available balance.\n\n"
        "👇 Choose an option below."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# ============================================================
# VERIFY
# ============================================================

async def verify_channels(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    missing = await get_missing_channels(
        context,
        user.id,
    )

    if missing:
        text = (
            "❌ <b>Verification Failed</b>\n\n"
            "You still need to join:\n\n"
            + "\n".join(
                f"• {html.escape(x)}"
                for x in missing
            )
            + "\n\n"
            "Join them and press Verify again."
        )

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )

        return

    db_user = get_user(user.id)

    if not db_user:
        db_user = create_user(
            user.id,
            user.username,
        )

    try:
        supabase.table("users").update(
            {
                "is_verified": True,
            }
        ).eq(
            "telegram_id",
            user.id,
        ).execute()

        await reward_referrer(
            context,
            user.id,
        )

    except Exception as e:
        logger.exception(
            "Verify save error: %s",
            e,
        )

    await query.edit_message_text(
        "✅ <b>Verification Successful!</b>\n\n"
        "You can now use Vortex Earn Bot.",
        parse_mode=ParseMode.HTML,
    )

    await context.bot.send_message(
        chat_id=user.id,
        text="👇 <b>Main Menu</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# ============================================================
# BALANCE
# ============================================================

async def show_balance(
    update,
    context,
):
    user = get_user(
        update.effective_user.id
    )

    if not user:
        await update.message.reply_text(
            "Please use /start first."
        )
        return

    balance = float(
        user.get("balance") or 0
    )

    balance_etb = float(
        user.get("balance_etb") or
        (balance * RATE)
    )

    text = (
        "💰 <b>Balance</b>\n\n"
        f"🪙 USDT = <b>{balance:.6f} USDT</b>\n"
        f"🇪🇹 ETB = <b>{balance_etb:.2f} ETB</b>\n\n"
        f"💱 Rate: <b>1 USDT = {RATE:.0f} ETB</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# ============================================================
# REFERRAL PAGE
# ============================================================

async def show_referral(
    update,
    context,
):
    user = get_user(
        update.effective_user.id
    )

    if not user:
        await update.message.reply_text(
            "Please use /start first."
        )
        return

    me = await context.bot.get_me()

    referral_link = (
        f"https://t.me/{me.username}?start=ref_{user['telegram_id']}"
    )

    count = int(
        user.get("referral_count") or
        user.get("referrals") or
        0
    )

    text = (
        "👥 <b>Referral</b>\n\n"
        "Invite your friends and earn "
        f"<b>{REFERRAL_REWARD_USDT:.3f} USDT</b> "
        "when your direct referral joins all required "
        "channels and becomes verified.\n\n"
        f"💰 Reward: <b>{REFERRAL_REWARD_USDT:.3f} USDT</b>\n"
        f"👥 My Referrals: <b>{count}</b>\n\n"
        "🔗 <b>Your referral link:</b>\n"
        f"<code>{html.escape(referral_link)}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📋 My Referrals",
                    callback_data="my_referrals",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="referral_back",
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
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    result = (
        supabase
        .table("users")
        .select(
            "username,telegram_id,is_verified"
        )
        .eq(
            "referred_by",
            user_id,
        )
        .order(
            "created_at",
            desc=True,
        )
        .execute()
    )

    referrals = result.data or []

    if not referrals:
        text = (
            "👥 <b>My Referrals</b>\n\n"
            "You don't have any referrals yet."
        )

    else:
        lines = []

        for i, person in enumerate(
            referrals,
            start=1,
        ):
            username = person.get("username")

            if username:
                name = f"@{html.escape(username)}"
            else:
                name = str(
                    person.get("telegram_id")
                )

            status = (
                "✅ Verified"
                if person.get("is_verified")
                else "⏳ Pending"
            )

            lines.append(
                f"{i}. {name} — {status}"
            )

        text = (
            "👥 <b>My Referrals</b>\n\n"
            + "\n".join(lines)
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(
            "referral_back"
        ),
    )


# ============================================================
# WALLET
# ============================================================

async def show_wallet(
    update,
    context,
    edit=False,
):
    user = get_user(
        update.effective_user.id
    )

    if not user:
        return

    text = (
        "👛 <b>Wallet</b>\n\n"
        "Choose the payment method you want to manage.\n\n"
        "💵 USDT\n"
        "🏦 CBE\n"
        "📱 Telebirr"
    )

    if edit:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=wallet_keyboard(),
        )


async def show_wallet_usdt(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💵 <b>USDT Wallet</b>\n\n"
        "Choose where you want to save your USDT withdrawal details.",
        parse_mode=ParseMode.HTML,
        reply_markup=wallet_usdt_keyboard(),
    )


async def begin_wallet_bybit(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    context.user_data["wallet_input"] = "bybit"

    await query.edit_message_text(
        "🟢 <b>Bybit UID / Account ID</b>\n\n"
        "Send your Bybit UID / Account ID.\n\n"
        "Example: <code>12345678</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(
            "wallet_back"
        ),
    )


async def begin_wallet_bep20(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    context.user_data["wallet_input"] = "bep20"

    await query.edit_message_text(
        "🟢 <b>BEP20 USDT Address</b>\n\n"
        "Send your BEP20 USDT wallet address.\n\n"
        "Example:\n"
        "<code>0x1234...abcd</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(
            "wallet_back"
        ),
    )


async def show_saved_cbe(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    wallet = ensure_wallet_json(user)

    account = (
        wallet.get("cbe_account")
        or user.get("bank_account")
    )

    name = wallet.get("cbe_name")

    if account and name:
        text = (
            "🏦 <b>CBE Wallet</b>\n\n"
            f"🔢 Account: <code>{html.escape(str(account))}</code>\n"
            f"👤 Name: <b>{html.escape(str(name))}</b>\n\n"
            "Your CBE details are saved."
        )

        keyboard = wallet_edit_keyboard("cbe")

    else:
        context.user_data["wallet_input"] = "cbe_account"

        text = (
            "🏦 <b>CBE Account</b>\n\n"
            "Send your 14-digit CBE account number."
        )

        keyboard = back_keyboard(
            "wallet_back"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def show_saved_telebirr(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    wallet = ensure_wallet_json(user)

    number = (
        wallet.get("telebirr")
        or user.get("telebirr_number")
    )

    name = wallet.get("telebirr_name")

    if number and name:
        text = (
            "📱 <b>Telebirr Wallet</b>\n\n"
            f"📱 Number: <code>{html.escape(str(number))}</code>\n"
            f"👤 Name: <b>{html.escape(str(name))}</b>\n\n"
            "Your Telebirr details are saved."
        )

        keyboard = wallet_edit_keyboard(
            "telebirr"
        )

    else:
        context.user_data["wallet_input"] = "telebirr_number"

        text = (
            "📱 <b>Telebirr</b>\n\n"
            "Send your 10-digit Telebirr phone number.\n\n"
            "It must start with 09 or 07."
        )

        keyboard = back_keyboard(
            "wallet_back"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def wallet_bybit_saved(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    wallet = ensure_wallet_json(user)

    value = wallet.get("bybit_uid")

    if value:
        text = (
            "🟢 <b>Bybit UID</b>\n\n"
            f"UID: <code>{html.escape(str(value))}</code>\n\n"
            "Your Bybit UID is saved."
        )

        keyboard = wallet_edit_keyboard(
            "bybit"
        )

    else:
        context.user_data["wallet_input"] = "bybit"

        text = (
            "🟢 <b>Bybit UID / Account ID</b>\n\n"
            "Send your Bybit UID / Account ID.\n\n"
            "Example: <code>12345678</code>"
        )

        keyboard = back_keyboard(
            "wallet_back"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def wallet_bep20_saved(
    update,
    context,
):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    wallet = ensure_wallet_json(user)

    value = (
        wallet.get("bep20")
        or user.get("usdt_address")
    )

    if value:
        text = (
            "🟢 <b>BEP20 USDT</b>\n\n"
            f"Address:\n<code>{html.escape(str(value))}</code>\n\n"
            "Your BEP20 address is saved."
        )

        keyboard = wallet_edit_keyboard(
            "bep20"
        )

    else:
        context.user_data["wallet_input"] = "bep20"

        text = (
            "🟢 <b>BEP20 USDT Address</b>\n\n"
            "Send your BEP20 USDT address."
        )

        keyboard = back_keyboard(
            "wallet_back"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def wallet_edit(
    update,
    context,
    method,
):
    query = update.callback_query
    await query.answer()

    if method == "bybit":
        context.user_data["wallet_input"] = "bybit"

        text = (
            "✏️ <b>Edit Bybit UID</b>\n\n"
            "Send your new Bybit UID / Account ID."
        )

    elif method == "bep20":
        context.user_data["wallet_input"] = "bep20"

        text = (
            "✏️ <b>Edit BEP20 Address</b>\n\n"
            "Send your new BEP20 USDT address."
        )

    elif method == "cbe":
        context.user_data["wallet_input"] = "cbe_account"

        text = (
            "✏️ <b>Edit CBE</b>\n\n"
            "Send your new 14-digit CBE account number."
        )

    elif method == "telebirr":
        context.user_data["wallet_input"] = "telebirr_number"

        text = (
            "✏️ <b>Edit Telebirr</b>\n\n"
            "Send your new 10-digit Telebirr number."
        )

    else:
        return

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(
            "wallet_back"
        ),
    )


# ============================================================
# WALLET INPUT HANDLING
# ============================================================

def valid_name(value):
    value = value.strip()

    if len(value) < 2 or len(value) > 100:
        return False

    return bool(
        re.fullmatch(
            r"[A-Za-z\u1200-\u137F\u1380-\u139F\s'\-]+",
            value,
        )
    )


async def process_wallet_input(
    update,
    context,
):
    mode = context.user_data.get(
        "wallet_input"
    )

    if not mode:
        return False

    message = update.message
    value = message.text.strip()

    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        return True

    wallet = ensure_wallet_json(user)

    # ---------------- BYBIT ----------------

    if mode == "bybit":
        if not re.fullmatch(r"\d{5,20}", value):
            await message.reply_text(
                "❌ Invalid Bybit UID.\n\n"
                "It must contain 5–20 digits.",
                reply_markup=MAIN_MENU,
            )
            return True

        wallet["bybit_uid"] = value

        save_user_wallet(
            user_id,
            wallet,
        )

        await message.reply_text(
            "✅ Bybit UID saved successfully.",
            reply_markup=MAIN_MENU,
        )

        context.user_data.pop(
            "wallet_input",
            None,
        )

        return True

    # ---------------- BEP20 ----------------

    if mode == "bep20":
        if not re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            value,
        ):
            await message.reply_text(
                "❌ Invalid BEP20 address.\n\n"
                "It must start with 0x and contain "
                "40 hexadecimal characters.",
                reply_markup=MAIN_MENU,
            )
            return True

        wallet["bep20"] = value

        save_user_wallet(
            user_id,
            wallet,
        )

        supabase.table("users").update(
            {
                "usdt_address": value,
            }
        ).eq(
            "telegram_id",
            user_id,
        ).execute()

        await message.reply_text(
            "✅ BEP20 USDT address saved successfully.",
            reply_markup=MAIN_MENU,
        )

        context.user_data.pop(
            "wallet_input",
            None,
        )

        return True

    # ---------------- CBE ACCOUNT ----------------

    if mode == "cbe_account":
        if not re.fullmatch(
            r"\d{14}",
            value,
        ):
            await message.reply_text(
                "❌ Invalid CBE account number.\n\n"
                "It must contain exactly 14 digits.",
                reply_markup=MAIN_MENU,
            )
            return True

        context.user_data[
            "pending_cbe_account"
        ] = value

        context.user_data[
            "wallet_input"
        ] = "cbe_name"

        await message.reply_text(
            "👤 Now send your <b>full name + father's name</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        return True

    # ---------------- CBE NAME ----------------

    if mode == "cbe_name":
        if not valid_name(value):
            await message.reply_text(
                "❌ Invalid name.\n\n"
                "Please enter your full name and father's name.",
                reply_markup=MAIN_MENU,
            )
            return True

        account = context.user_data.get(
            "pending_cbe_account"
        )

        wallet["cbe_account"] = account
        wallet["cbe_name"] = value

        save_user_wallet(
            user_id,
            wallet,
        )

        supabase.table("users").update(
            {
                "bank_account": account,
                "bank_name": value,
            }
        ).eq(
            "telegram_id",
            user_id,
        ).execute()

        context.user_data.pop(
            "pending_cbe_account",
            None,
        )
        context.user_data.pop(
            "wallet_input",
            None,
        )

        await message.reply_text(
            "✅ CBE details saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    # ---------------- TELEBIRR NUMBER ----------------

    if mode == "telebirr_number":
        if not re.fullmatch(
            r"(09|07)\d{8}",
            value,
        ):
            await message.reply_text(
                "❌ Invalid Telebirr number.\n\n"
                "It must be exactly 10 digits "
                "and start with 09 or 07.",
                reply_markup=MAIN_MENU,
            )
            return True

        context.user_data[
            "pending_telebirr"
        ] = value

        context.user_data[
            "wallet_input"
        ] = "telebirr_name"

        await message.reply_text(
            "👤 Now send your <b>full name + father's name</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )

        return True

    # ---------------- TELEBIRR NAME ----------------

    if mode == "telebirr_name":
        if not valid_name(value):
            await message.reply_text(
                "❌ Invalid name.\n\n"
                "Please enter your full name and father's name.",
                reply_markup=MAIN_MENU,
            )
            return True

        number = context.user_data.get(
            "pending_telebirr"
        )

        wallet["telebirr"] = number
        wallet["telebirr_name"] = value

        save_user_wallet(
            user_id,
            wallet,
        )

        supabase.table("users").update(
            {
                "telebirr_number": number,
            }
        ).eq(
            "telegram_id",
            user_id,
        ).execute()

        context.user_data.pop(
            "pending_telebirr",
            None,
        )
        context.user_data.pop(
            "wallet_input",
            None,
        )

        await message.reply_text(
            "✅ Telebirr details saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    return False


# ============================================================
# WITHDRAW
# ============================================================

async def show_withdraw(
    update,
    context,
):
    user = get_user(
        update.effective_user.id
    )

    if not user:
        await update.message.reply_text(
            "Please use /start first."
        )
        return

    balance = float(
        user.get("balance") or 0
    )

    text = (
        "💸 <b>Withdraw</b>\n\n"
        f"💰 Available: <b>{balance:.6f} USDT</b>\n\n"
        "Choose your withdrawal method:"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=withdraw_keyboard(),
    )


def get_min_withdraw(user):
    count = int(
        user.get("withdrawal_count") or 0
    )

    if count < 2:
        return FIRST_MIN_WITHDRAW_USDT

    return LATER_MIN_WITHDRAW_USDT


async def select_withdraw_method(
    update,
    context,
    method,
):
    query = update.callback_query

    await query.answer()

    user = get_user(query.from_user.id)

    if not user:
        await query.edit_message_text(
            "Please use /start first."
        )
        return

    method = method.lower()

    wallet = ensure_wallet_json(user)

    if method == "usdt":
        bybit = wallet.get("bybit_uid")
        bep20 = (
            wallet.get("bep20")
            or user.get("usdt_address")
        )

        if not bybit and not bep20:
            await query.edit_message_text(
                "❌ <b>No USDT wallet saved.</b>\n\n"
                "Please save your Bybit UID or BEP20 address "
                "from 👛 Wallet first.",
                parse_mode=ParseMode.HTML,
                reply_markup=withdraw_back_keyboard(),
            )
            return

        if bybit and bep20:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Bybit UID",
                            callback_data="withdraw_bybit",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🟢 BEP20",
                            callback_data="withdraw_bep20",
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

            await query.edit_message_text(
                "💵 <b>USDT Withdrawal</b>\n\n"
                "You have two saved USDT methods.\n"
                "Choose which one to use:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return

        if bybit:
            await withdraw_use_bybit(
                update,
                context,
                edit=True,
            )
            return

        await withdraw_use_bep20(
            update,
            context,
            edit=True,
        )
        return

    if method == "cbe":
        account = (
            wallet.get("cbe_account")
            or user.get("bank_account")
        )
        name = wallet.get("cbe_name")

        if not account or not name:
            await query.edit_message_text(
                "❌ <b>CBE wallet not saved.</b>\n\n"
                "Please save your CBE account and name "
                "from 👛 Wallet first.",
                parse_mode=ParseMode.HTML,
                reply_markup=withdraw_back_keyboard(),
            )
            return

        context.user_data[
            "withdraw_method"
        ] = "cbe"

        context.user_data[
            "withdraw_payment_details"
        ] = f"CBE Account: {account}\nName: {name}"

        await ask_withdraw_amount(
            update,
            context,
            edit=True,
        )
        return

    if method == "telebirr":
        number = (
            wallet.get("telebirr")
            or user.get("telebirr_number")
        )
        name = wallet.get("telebirr_name")

        if not number or not name:
            await query.edit_message_text(
                "❌ <b>Telebirr wallet not saved.</b>\n\n"
                "Please save your Telebirr number and name "
                "from 👛 Wallet first.",
                parse_mode=ParseMode.HTML,
                reply_markup=withdraw_back_keyboard(),
            )
            return

        context.user_data[
            "withdraw_method"
        ] = "telebirr"

        context.user_data[
            "withdraw_payment_details"
        ] = f"Telebirr: {number}\nName: {name}"

        await ask_withdraw_amount(
            update,
            context,
            edit=True,
        )
        return


async def withdraw_use_bybit(
    update,
    context,
    edit=False,
):
    user = get_user(
        update.effective_user.id
    )

    wallet = ensure_wallet_json(user)

    value = wallet.get("bybit_uid")

    if not value:
        return

    context.user_data[
        "withdraw_method"
    ] = "bybit"

    context.user_data[
        "withdraw_payment_details"
    ] = f"Bybit UID: {value}"

    await ask_withdraw_amount(
        update,
        context,
        edit=edit,
    )


async def withdraw_use_bep20(
    update,
    context,
    edit=False,
):
    user = get_user(
        update.effective_user.id
    )

    wallet = ensure_wallet_json(user)

    value = (
        wallet.get("bep20")
        or user.get("usdt_address")
    )

    if not value:
        return

    context.user_data[
        "withdraw_method"
    ] = "bep20"

    context.user_data[
        "withdraw_payment_details"
    ] = f"BEP20: {value}"

    await ask_withdraw_amount(
        update,
        context,
        edit=edit,
    )


async def ask_withdraw_amount(
    update,
    context,
    edit=False,
):
    user = get_user(
        update.effective_user.id
    )

    minimum = get_min_withdraw(user)

    text = (
        "💸 <b>Enter Withdrawal Amount</b>\n\n"
        f"Minimum: <b>{minimum:.2f} USDT</b>\n"
        f"Rate: <b>1 USDT = {RATE:.0f} ETB</b>\n\n"
        "Send the amount in USDT.\n\n"
        "Example: <code>0.12</code>"
    )

    context.user_data[
        "withdraw_amount_input"
    ] = True

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=withdraw_back_keyboard(),
        )

    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=withdraw_back_keyboard(),
        )


# ============================================================
# WITHDRAW AMOUNT INPUT
# ============================================================

async def process_withdraw_amount(
    update,
    context,
):
    if not context.user_data.get(
        "withdraw_amount_input"
    ):
        return False

    value = update.message.text.strip()

    try:
        amount = float(value)
    except ValueError:
        await update.message.reply_text(
            "❌ Please send a valid number.\n\n"
            "Example: 0.12"
        )
        return True

    if amount <= 0:
        await update.message.reply_text(
            "❌ Amount must be greater than 0."
        )
        return True

    user = get_user(
        update.effective_user.id
    )

    if not user:
        return True

    minimum = get_min_withdraw(user)
    balance = float(
        user.get("balance") or 0
    )

    if amount < minimum:
        await update.message.reply_text(
            f"❌ Minimum withdrawal is "
            f"<b>{minimum:.2f} USDT</b>.",
            parse_mode=ParseMode.HTML,
        )
        return True

    if amount > balance:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n\n"
            f"Available: <b>{balance:.6f} USDT</b>",
            parse_mode=ParseMode.HTML,
        )
        return True

    # Duplicate pending withdrawal protection.
    pending = (
        supabase
        .table("withdrawal_requests")
        .select("id")
        .eq(
            "user_id",
            update.effective_user.id,
        )
        .eq(
            "status",
            "pending",
        )
        .limit(1)
        .execute()
    )

    if pending.data:
        await update.message.reply_text(
            "⏳ You already have a pending withdrawal.\n\n"
            "Please wait until it is processed."
        )

        context.user_data.clear()
        return True

    method = context.user_data.get(
        "withdraw_method"
    )

    details = context.user_data.get(
        "withdraw_payment_details"
    )

    if not method or not details:
        await update.message.reply_text(
            "❌ Withdrawal session expired.\n\n"
            "Please start again."
        )

        context.user_data.clear()
        return True

    amount_etb = amount * RATE

    context.user_data[
        "withdraw_amount"
    ] = amount

    context.user_data[
        "withdraw_amount_etb"
    ] = amount_etb

    context.user_data[
        "withdraw_amount_input"
    ] = False

    text = (
        "🔎 <b>Confirm Withdrawal</b>\n\n"
        f"💰 Amount: <b>{amount:.6f} USDT</b>\n"
        f"🇪🇹 Value: <b>{amount_etb:.2f} ETB</b>\n"
        f"💳 Method: <b>{html.escape(method.upper())}</b>\n\n"
        f"📌 Payment details:\n"
        f"<code>{html.escape(details)}</code>\n\n"
        "⚠️ Make sure the payment details are correct."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_withdraw_keyboard(),
    )

    return True


# ============================================================
# CONFIRM WITHDRAW
# ============================================================

async def confirm_withdraw(
    update,
    context,
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:
        return

    amount = context.user_data.get(
        "withdraw_amount"
    )

    amount_etb = context.user_data.get(
        "withdraw_amount_etb"
    )

    method = context.user_data.get(
        "withdraw_method"
    )

    details = context.user_data.get(
        "withdraw_payment_details"
    )

    if not amount or not method or not details:
        await query.edit_message_text(
            "❌ Withdrawal session expired.\n\n"
            "Please start again.",
        )
        return

    balance = float(
        user.get("balance") or 0
    )

    if amount > balance:
        await query.edit_message_text(
            "❌ Your balance is no longer sufficient."
        )

        context.user_data.clear()
        return

    pending = (
        supabase
        .table("withdrawal_requests")
        .select("id")
        .eq(
            "user_id",
            query.from_user.id,
        )
        .eq(
            "status",
            "pending",
        )
        .limit(1)
        .execute()
    )

    if pending.data:
        await query.edit_message_text(
            "⏳ You already have a pending withdrawal."
        )

        context.user_data.clear()
        return

    try:
        result = (
            supabase
            .table("withdrawal_requests")
            .insert(
                {
                    "user_id": query.from_user.id,
                    "amount_usdt": amount,
                    "amount_etb": amount_etb,
                    "method": method,
                    "payment_details": details,
                    "status": "pending",
                }
            )
            .execute()
        )

        request_id = None

        if result.data:
            request_id = result.data[0].get(
                "id"
            )

        await query.edit_message_text(
            "✅ <b>Withdrawal Request Submitted</b>\n\n"
            f"💰 Amount: <b>{amount:.6f} USDT</b>\n"
            f"🇪🇹 Value: <b>{amount_etb:.2f} ETB</b>\n"
            f"💳 Method: <b>{html.escape(method.upper())}</b>\n\n"
            "⏳ Status: <b>Pending</b>\n\n"
            "💡 Payment is processed manually by the admin.",
            parse_mode=ParseMode.HTML,
        )

        # Notify admin.
        if ADMIN_ID and request_id:
            username = (
                f"@{query.from_user.username}"
                if query.from_user.username
                else "No username"
            )

            admin_text = (
                "💸 <b>NEW WITHDRAWAL REQUEST</b>\n\n"
                f"🆔 Request ID: <code>{request_id}</code>\n"
                f"👤 User: {html.escape(username)}\n"
                f"🆔 Telegram ID: <code>{query.from_user.id}</code>\n\n"
                f"💰 Amount: <b>{amount:.6f} USDT</b>\n"
                f"🇪🇹 ETB: <b>{amount_etb:.2f}</b>\n"
                f"💳 Method: <b>{html.escape(method.upper())}</b>\n\n"
                f"📌 Payment details:\n"
                f"<code>{html.escape(details)}</code>"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode=ParseMode.HTML,
                reply_markup=admin_withdraw_keyboard(
                    request_id
                ),
            )

    except Exception as e:
        logger.exception(
            "Withdrawal insert error: %s",
            e,
        )

        await query.edit_message_text(
            "❌ Something went wrong while creating "
            "your withdrawal request.\n\n"
            "Please try again later."
        )

    context.user_data.clear()


# ============================================================
# ADMIN APPROVE / REJECT
# ============================================================

async def admin_approve(
    update,
    context,
    request_id,
):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "❌ Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    result = (
        supabase
        .table("withdrawal_requests")
        .select("*")
        .eq(
            "id",
            request_id,
        )
        .limit(1)
        .execute()
    )

    if not result.data:
        await query.edit_message_text(
            "❌ Withdrawal request not found."
        )
        return

    request = result.data[0]

    if request.get("status") != "pending":
        await query.edit_message_text(
            "⚠️ This withdrawal has already been processed."
        )
        return

    user_id = int(
        request["user_id"]
    )

    amount = float(
        request["amount_usdt"] or 0
    )

    amount_etb = float(
        request["amount_etb"] or 0
    )

    user = get_user(user_id)

    if not user:
        await query.edit_message_text(
            "❌ User not found."
        )
        return

    balance = float(
        user.get("balance") or 0
    )

    if balance < amount:
        await query.edit_message_text(
            "❌ User balance is insufficient."
        )
        return

    # Mark as processing first to prevent double-click.
    processing = (
        supabase
        .table("withdrawal_requests")
        .update(
            {
                "status": "processing",
            }
        )
        .eq(
            "id",
            request_id,
        )
        .eq(
            "status",
            "pending",
        )
        .execute()
    )

    if not processing.data:
        await query.edit_message_text(
            "⚠️ This request is already being processed."
        )
        return

    try:
        new_balance = balance - amount

        new_balance_etb = float(
            user.get("balance_etb") or 0
        ) - amount_etb

        if new_balance_etb < 0:
            new_balance_etb = 0

        withdrawal_count = int(
            user.get("withdrawal_count") or 0
        ) + 1

        total_usdt = float(
            user.get("total_withdrawn_usdt") or 0
        ) + amount

        total_etb = float(
            user.get("total_withdrawn_etb") or 0
        ) + amount_etb

        updated = (
            supabase
            .table("users")
            .update(
                {
                    "balance": new_balance,
                    "balance_etb": new_balance_etb,
                    "withdrawal_count": withdrawal_count,
                    "total_withdrawn_usdt": total_usdt,
                    "total_withdrawn_etb": total_etb,
                    "last_withdrawal_method": request.get(
                        "method"
                    ),
                }
            )
            .eq(
                "telegram_id",
                user_id,
            )
            .execute()
        )

        if not updated.data:
            raise RuntimeError(
                "User balance update failed"
            )

        processed_at = datetime.now(
            timezone.utc
        ).isoformat()

        approved = (
            supabase
            .table("withdrawal_requests")
            .update(
                {
                    "status": "approved",
                    "processed_at": processed_at,
                }
            )
            .eq(
                "id",
                request_id,
            )
            .eq(
                "status",
                "processing",
            )
            .execute()
        )

        if not approved.data:
            raise RuntimeError(
                "Withdrawal approval update failed"
            )

        await query.edit_message_text(
            "✅ <b>Withdrawal Approved</b>\n\n"
            f"🆔 Request: <code>{request_id}</code>\n"
            f"💰 Amount: <b>{amount:.6f} USDT</b>\n"
            f"🇪🇹 ETB: <b>{amount_etb:.2f}</b>\n\n"
            "The balance has been deducted.",
            parse_mode=ParseMode.HTML,
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ <b>Withdrawal Approved</b>\n\n"
                    f"💰 Amount: <b>{amount:.6f} USDT</b>\n"
                    f"🇪🇹 Value: <b>{amount_etb:.2f} ETB</b>\n\n"
                    "Your withdrawal has been approved by the admin."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=MAIN_MENU,
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception(
            "Admin approve error: %s",
            e,
        )

        # Return request to pending if something failed.
        try:
            supabase.table(
                "withdrawal_requests"
            ).update(
                {
                    "status": "pending",
                }
            ).eq(
                "id",
                request_id,
            ).eq(
                "status",
                "processing",
            ).execute()
        except Exception:
            pass

        await query.edit_message_text(
            "❌ Approval failed.\n\n"
            "The request was returned to pending."
        )


async def admin_reject(
    update,
    context,
    request_id,
):
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer(
            "❌ Admin only.",
            show_alert=True,
        )
        return

    await query.answer()

    result = (
        supabase
        .table("withdrawal_requests")
        .select("*")
        .eq(
            "id",
            request_id,
        )
        .limit(1)
        .execute()
    )

    if not result.data:
        await query.edit_message_text(
            "❌ Withdrawal request not found."
        )
        return

    request = result.data[0]

    if request.get("status") != "pending":
        await query.edit_message_text(
            "⚠️ This withdrawal has already been processed."
        )
        return

    processed_at = datetime.now(
        timezone.utc
    ).isoformat()

    (
        supabase
        .table("withdrawal_requests")
        .update(
            {
                "status": "rejected",
                "processed_at": processed_at,
            }
        )
        .eq(
            "id",
            request_id,
        )
        .eq(
            "status",
            "pending",
        )
        .execute()
    )

    amount = float(
        request.get("amount_usdt") or 0
    )

    await query.edit_message_text(
        "❌ <b>Withdrawal Rejected</b>\n\n"
        f"🆔 Request: <code>{request_id}</code>\n"
        f"💰 Amount: <b>{amount:.6f} USDT</b>\n\n"
        "User balance was not deducted.",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            chat_id=int(request["user_id"]),
            text=(
                "❌ <b>Withdrawal Rejected</b>\n\n"
                f"💰 Amount: <b>{amount:.6f} USDT</b>\n\n"
                "Your balance has not been deducted."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
    except Exception:
        pass


# ============================================================
# HISTORY
# ============================================================

async def show_history(
    update,
    context,
):
    user_id = update.effective_user.id

    result = (
        supabase
        .table("withdrawal_requests")
        .select(
            "id,amount_usdt,amount_etb,method,status,created_at"
        )
        .eq(
            "user_id",
            user_id,
        )
        .order(
            "created_at",
            desc=True,
        )
        .limit(10)
        .execute()
    )

    rows = result.data or []

    if not rows:
        text = (
            "📜 <b>Withdrawal History</b>\n\n"
            "No withdrawal requests yet."
        )

    else:
        lines = [
            "📜 <b>Withdrawal History</b>\n"
        ]

        for row in rows:
            amount = float(
                row.get("amount_usdt") or 0
            )

            status = row.get("status", "unknown")

            if status == "approved":
                emoji = "✅"
            elif status == "rejected":
                emoji = "❌"
            elif status == "processing":
                emoji = "⚙️"
            else:
                emoji = "⏳"

            lines.append(
                f"{emoji} #{row.get('id')} — "
                f"{amount:.6f} USDT — "
                f"{html.escape(str(row.get('method')))} — "
                f"{html.escape(status)}"
            )

        text = "\n".join(lines)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


# ============================================================
# TASKS
# ============================================================

async def show_tasks(
    update,
    context,
):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Promotion Service",
                    url="https://t.me/AmanM_12",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="tasks_back",
                )
            ],
        ]
    )

    await update.message.reply_text(
        "🎯 <b>Tasks</b>\n\n"
        "Complete available earning tasks here.\n\n"
        "📢 Promotion Service\n"
        "Contact support for available promotion tasks.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ============================================================
# SUPPORT
# ============================================================

async def show_support(
    update,
    context,
):
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🆘 Contact Support",
                    url="https://t.me/AmanM_12",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="support_back",
                )
            ],
        ]
    )

    await update.message.reply_text(
        "🆘 <b>Support</b>\n\n"
        "If you need help, contact our support admin.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ============================================================
# TEXT ROUTER
# ============================================================

async def text_router(
    update,
    context,
):
    # Wallet input first.
    if context.user_data.get(
        "wallet_input"
    ):
        handled = await process_wallet_input(
            update,
            context,
        )

        if handled:
            return

    # Withdrawal amount.
    if context.user_data.get(
        "withdraw_amount_input"
    ):
        handled = await process_withdraw_amount(
            update,
            context,
        )

        if handled:
            return

    text = update.message.text

    if text == "💰 Balance":
        await show_balance(
            update,
            context,
        )

    elif text == "🎯 Tasks":
        await show_tasks(
            update,
            context,
        )

    elif text == "👥 Referral":
        await show_referral(
            update,
            context,
        )

    elif text == "👛 Wallet":
        await show_wallet(
            update,
            context,
            edit=False,
        )

    elif text == "💸 Withdraw":
        await show_withdraw(
            update,
            context,
        )

    elif text == "🆘 Support":
        await show_support(
            update,
            context,
        )

    else:
        await update.message.reply_text(
            "👇 Please choose an option from the menu.",
            reply_markup=MAIN_MENU,
        )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update,
    context,
):
    query = update.callback_query
    data = query.data

    # ---------------- CHANNELS ----------------

    if data == "verify_channels":
        await verify_channels(
            update,
            context,
        )
        return

    # ---------------- MAIN BACK ----------------

    if data == "main_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------- WALLET ----------------

    if data == "wallet_main_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    if data == "wallet_back":
        await show_wallet(
            update,
            context,
            edit=True,
        )
        return

    if data == "wallet_usdt":
        await show_wallet_usdt(
            update,
            context,
        )
        return

    if data == "wallet_bybit":
        await wallet_bybit_saved(
            update,
            context,
        )
        return

    if data == "wallet_bep20":
        await wallet_bep20_saved(
            update,
            context,
        )
        return

    if data == "wallet_cbe":
        await show_saved_cbe(
            update,
            context,
        )
        return

    if data == "wallet_telebirr":
        await show_saved_telebirr(
            update,
            context,
        )
        return

    if data == "wallet_edit_bybit":
        await wallet_edit(
            update,
            context,
            "bybit",
        )
        return

    if data == "wallet_edit_bep20":
        await wallet_edit(
            update,
            context,
            "bep20",
        )
        return

    if data == "wallet_edit_cbe":
        await wallet_edit(
            update,
            context,
            "cbe",
        )
        return

    if data == "wallet_edit_telebirr":
        await wallet_edit(
            update,
            context,
            "telebirr",
        )
        return

    # ---------------- WITHDRAW ----------------
    #
    # IMPORTANT:
    # Lowercase values are intentionally passed here.
    #

    if data == "withdraw_usdt":
        await select_withdraw_method(
            update,
            context,
            "usdt",
        )
        return

    if data == "withdraw_cbe":
        await select_withdraw_method(
            update,
            context,
            "cbe",
        )
        return

    if data == "withdraw_telebirr":
        await select_withdraw_method(
            update,
            context,
            "telebirr",
        )
        return

    if data == "withdraw_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    if data == "withdraw_bybit":
        await query.answer()

        await withdraw_use_bybit(
            update,
            context,
            edit=True,
        )
        return

    if data == "withdraw_bep20":
        await query.answer()

        await withdraw_use_bep20(
            update,
            context,
            edit=True,
        )
        return

    if data == "confirm_withdraw":
        await confirm_withdraw(
            update,
            context,
        )
        return

    if data == "cancel_withdraw":
        await query.answer()

        context.user_data.clear()

        await query.edit_message_text(
            "❌ Withdrawal cancelled."
        )

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------- REFERRAL ----------------

    if data == "my_referrals":
        await my_referrals(
            update,
            context,
        )
        return

    if data == "referral_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------- TASKS ----------------

    if data == "tasks_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------- SUPPORT ----------------

    if data == "support_back":
        await query.answer()

        await query.message.delete()

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="👇 <b>Main Menu</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=MAIN_MENU,
        )
        return

    # ---------------- ADMIN ----------------

    if data.startswith("admin_approve_"):
        request_id = data.replace(
            "admin_approve_",
            "",
            1,
        )

        try:
            request_id = int(request_id)
        except ValueError:
            await query.answer(
                "Invalid request ID.",
                show_alert=True,
            )
            return

        await admin_approve(
            update,
            context,
            request_id,
        )
        return

    if data.startswith("admin_reject_"):
        request_id = data.replace(
            "admin_reject_",
            "",
            1,
        )

        try:
            request_id = int(request_id)
        except ValueError:
            await query.answer(
                "Invalid request ID.",
                show_alert=True,
            )
            return

        await admin_reject(
            update,
            context,
            request_id,
        )
        return

    await query.answer()


# ============================================================
# ADMIN COMMAND
# ============================================================

async def admin_command(
    update,
    context,
):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ Admin only."
        )
        return

    await update.message.reply_text(
        "👑 <b>Admin Panel</b>\n\n"
        "Withdrawal requests are sent here automatically.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


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


# ============================================================
# MAIN
# ============================================================

def main():
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
            "balance",
            show_balance,
        )
    )

    application.add_handler(
        CommandHandler(
            "referral",
            show_referral,
        )
    )

    application.add_handler(
        CommandHandler(
            "history",
            show_history,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    # Callback buttons
    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Text input / menu
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    application.add_error_handler(
        error_handler
    )

    webhook_url = (
        f"https://vortex-earn-bot.onrender.com/{TOKEN}"
    )

    logger.info(
        "Starting Vortex Earn Bot..."
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=webhook_url,
    )


if __name__ == "__main__":
    main()
