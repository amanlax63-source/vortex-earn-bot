import os
from decimal import Decimal

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from supabase import create_client


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

PORT = int(os.getenv("PORT", "10000"))

# Admin numeric Telegram ID.
# Add this to Render Environment Variables as ADMIN_ID.
ADMIN_ID = os.getenv("ADMIN_ID")

SUPPORT_USERNAME = "@AmanM_12"

# Fixed exchange rate
USDT_TO_ETB = Decimal("185")

# Referral reward
REFERRAL_REWARD_USDT = Decimal("0.015")
REFERRAL_REWARD_ETB = REFERRAL_REWARD_USDT * USDT_TO_ETB

# Withdrawal minimums
FIRST_MIN_WITHDRAW_USDT = Decimal("0.12")
LATER_MIN_WITHDRAW_USDT = Decimal("0.50")

# Mandatory channels
REQUIRED_CHANNELS = [
    "@Sheger_tech1",
    "@EthioVortex1",
    "@ethiocashflow",
    "@AmanMoneyLab07",
]


# =========================================================
# SUPABASE
# =========================================================

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set.")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase environment variables are not set.")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


# =========================================================
# MAIN MENU
# =========================================================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Balance", "🎯 Tasks"],
        ["👥 Referral", "👛 Wallet"],
        ["💸 Withdraw", "🆘 Support"],
    ],
    resize_keyboard=True,
)


# =========================================================
# DATABASE HELPERS
# =========================================================

def get_user(telegram_id: int):
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


def create_user(
    telegram_id: int,
    username: str,
    referred_by=None,
):
    data = {
        "telegram_id": telegram_id,
        "username": username or "",
        "balance": 0,
        "balance_etb": 0,
        "referrals": 0,
        "referral_count": 0,
        "wallet": "",
        "withdrawal_count": 0,
        "total_withdrawn_usdt": 0,
        "total_withdrawn_etb": 0,
        "currency": "USDT",
        "usdt_address": "",
        "telebirr_number": "",
        "bank_name": "",
        "bank_account": "",
        "last_withdrawal_method": "",
        "is_verified": False,
    }

    if referred_by:
        data["referred_by"] = referred_by
    else:
        data["referred_by"] = None

    result = (
        supabase
        .table("users")
        .insert(data)
        .execute()
    )

    if result.data:
        return result.data[0]

    return None


def update_user(telegram_id: int, data: dict):
    return (
        supabase
        .table("users")
        .update(data)
        .eq("telegram_id", telegram_id)
        .execute()
    )


def ensure_user(update: Update):
    user = update.effective_user

    if not user:
        return None

    db_user = get_user(user.id)

    if db_user:
        # Keep username updated
        if db_user.get("username") != (user.username or ""):
            update_user(
                user.id,
                {"username": user.username or ""},
            )

        return db_user

    return create_user(
        telegram_id=user.id,
        username=user.username or "",
    )


# =========================================================
# CHANNEL CHECK
# =========================================================

async def is_member(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    channel: str,
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

    except Exception:
        return False


async def missing_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    telegram_id = update.effective_user.id

    missing = []

    for channel in REQUIRED_CHANNELS:
        if not await is_member(
            context,
            telegram_id,
            channel,
        ):
            missing.append(channel)

    return missing


def channel_keyboard():
    keyboard = []

    for channel in REQUIRED_CHANNELS:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"➕ Join {channel}",
                    url=f"https://t.me/{channel.lstrip('@')}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "✅ Verify",
                callback_data="verify_channels",
            )
        ]
    )

    return InlineKeyboardMarkup(keyboard)


async def require_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    missing = await missing_channels(
        update,
        context,
    )

    if not missing:
        return True

    text = (
        "🔒 Access Locked\n\n"
        "Please join all required channels first.\n\n"
        "After joining all 4 channels, press "
        "✅ Verify."
    )

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=channel_keyboard(),
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                reply_markup=channel_keyboard(),
            )
    else:
        await update.message.reply_text(
            text,
            reply_markup=channel_keyboard(),
        )

    return False


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    telegram_user = update.effective_user

    if not telegram_user:
        return

    existing = get_user(telegram_user.id)

    # -----------------------------------------------------
    # New user
    # -----------------------------------------------------
    if not existing:

        referred_by = None

        if context.args:
            ref_value = context.args[0]

            if ref_value.startswith("ref_"):
                try:
                    referred_by = int(
                        ref_value.replace("ref_", "")
                    )
                except ValueError:
                    referred_by = None

        # Prevent self referral
        if referred_by == telegram_user.id:
            referred_by = None

        # Make sure referrer exists
        if referred_by:
            referrer = get_user(referred_by)

            if not referrer:
                referred_by = None

        existing = create_user(
            telegram_id=telegram_user.id,
            username=telegram_user.username or "",
            referred_by=referred_by,
        )

        # -------------------------------------------------
        # Give referral reward immediately
        # -------------------------------------------------
        if existing and referred_by:

            referrer = get_user(referred_by)

            if referrer:

                old_balance = Decimal(
                    str(referrer.get("balance") or 0)
                )

                old_balance_etb = Decimal(
                    str(referrer.get("balance_etb") or 0)
                )

                old_referral_count = int(
                    referrer.get("referral_count") or 0
                )

                new_balance = (
                    old_balance +
                    REFERRAL_REWARD_USDT
                )

                new_balance_etb = (
                    old_balance_etb +
                    REFERRAL_REWARD_ETB
                )

                update_user(
                    referred_by,
                    {
                        "balance": float(new_balance),
                        "balance_etb": float(new_balance_etb),
                        "referral_count": old_referral_count + 1,
                        "referrals": old_referral_count + 1,
                    },
                )

                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=(
                            "🎉 New Referral!\n\n"
                            "You received:\n"
                            f"💵 {REFERRAL_REWARD_USDT:.3f} USDT\n"
                            f"🇪🇹 {REFERRAL_REWARD_ETB:.3f} ETB\n\n"
                            "💱 Rate: 1 USDT = 185 ETB"
                        ),
                    )
                except Exception:
                    pass

    # -----------------------------------------------------
    # Check channels
    # -----------------------------------------------------

    if await require_channels(
        update,
        context,
    ):
        await update.message.reply_text(
            "🎉 Welcome to Vortex Earn Bot!\n\n"
            "Your account is ready.\n"
            "Choose an option below.",
            reply_markup=MAIN_MENU,
        )


# =========================================================
# VERIFY CHANNELS
# =========================================================

async def verify_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    missing = await missing_channels(
        update,
        context,
    )

    if missing:
        missing_text = "\n".join(
            f"❌ {channel}"
            for channel in missing
        )

        await query.edit_message_text(
            "❌ Verification failed.\n\n"
            "You still need to join:\n\n"
            f"{missing_text}\n\n"
            "Join them and press Verify again.",
            reply_markup=channel_keyboard(),
        )

        return

    # Mark user verified
    update_user(
        update.effective_user.id,
        {"is_verified": True},
    )

    await query.edit_message_text(
        "✅ Verification successful!\n\n"
        "🎉 All required channels are joined.\n"
        "Your Vortex Earn account is unlocked.",
    )

    await query.message.reply_text(
        "Choose an option below:",
        reply_markup=MAIN_MENU,
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_channels(
        update,
        context,
    ):
        return

    user = ensure_user(update)

    if not user:
        return

    usdt = Decimal(
        str(user.get("balance") or 0)
    )

    etb = Decimal(
        str(user.get("balance_etb") or 0)
    )

    # Keep ETB synchronized with USDT
    expected_etb = usdt * USDT_TO_ETB

    if abs(etb - expected_etb) > Decimal("0.01"):
        etb = expected_etb

        update_user(
            update.effective_user.id,
            {
                "balance_etb": float(etb),
            },
        )

    await update.message.reply_text(
        "💰 Balance\n\n"
        f"🪙 USDT = {usdt:.6f} USDT\n"
        f"🇪🇹 ETB = {etb:.2f} ETB\n\n"
        "💱 Rate: 1 USDT = 185 ETB"
    )


# =========================================================
# REFERRAL
# =========================================================

async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_channels(
        update,
        context,
    ):
        return

    user = ensure_user(update)

    if not user:
        return

    bot_info = await context.bot.get_me()

    referral_link = (
        f"https://t.me/{bot_info.username}"
        f"?start=ref_{update.effective_user.id}"
    )

    count = int(
        user.get("referral_count") or
        user.get("referrals") or
        0
    )

    await update.message.reply_text(
        "👥 Referral Program\n\n"
        f"🔗 Your referral link:\n"
        f"{referral_link}\n\n"
        f"💵 Reward per direct referral: "
        f"{REFERRAL_REWARD_USDT:.3f} USDT\n"
        f"🇪🇹 Equivalent: "
        f"{REFERRAL_REWARD_ETB:.3f} ETB\n\n"
        f"👤 Direct referrals: {count}\n\n"
        "💱 Rate: 1 USDT = 185 ETB\n\n"
        "ℹ️ One-level referral system."
    )


async def referrals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await referral(update, context)


# =========================================================
# TASKS
# =========================================================

async def tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_channels(
        update,
        context,
    ):
        return

    await update.message.reply_text(
        "🎯 Tasks\n\n"
        "No tasks are available right now.\n\n"
        "New earning tasks will appear here."
    )


# =========================================================
# WALLET MAIN
# =========================================================

async def wallet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_channels(
        update,
        context,
    ):
        return

    keyboard = [
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

    await update.message.reply_text(
        "👛 Wallet\n\n"
        "Choose your payment method:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# WALLET - USDT
# =========================================================

async def wallet_usdt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    keyboard = [
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

    await query.edit_message_text(
        "💵 USDT Wallet\n\n"
        "Choose your USDT payout method:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# WALLET - CBE
# =========================================================

async def wallet_cbe(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    context.user_data["wallet_state"] = "cbe_account"

    await query.edit_message_text(
        "🏦 CBE Wallet\n\n"
        "Send your CBE account number.\n\n"
        "Example:\n"
        "1000123456789"
    )


# =========================================================
# WALLET - TELEBIRR
# =========================================================

async def wallet_telebirr(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    context.user_data["wallet_state"] = "telebirr_number"

    await query.edit_message_text(
        "📱 Telebirr Wallet\n\n"
        "Send your Telebirr phone number.\n\n"
        "Example:\n"
        "09XXXXXXXX"
    )


# =========================================================
# WALLET - BYBIT
# =========================================================

async def wallet_bybit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    context.user_data["wallet_state"] = "bybit"

    await query.edit_message_text(
        "🟢 Bybit UID / Account ID\n\n"
        "Send your Bybit UID or Account ID."
    )


# =========================================================
# WALLET - BEP20
# =========================================================

async def wallet_bep20(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    context.user_data["wallet_state"] = "bep20"

    await query.edit_message_text(
        "🟢 BEP20 USDT Address\n\n"
        "Send your BEP20 USDT wallet address."
    )


# =========================================================
# WALLET TEXT INPUT
# =========================================================

async def wallet_text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    state = context.user_data.get("wallet_state")

    if not state:
        return False

    text = update.message.text.strip()

    if not text:
        return True

    telegram_id = update.effective_user.id

    # -----------------------------------------------------
    # Bybit
    # -----------------------------------------------------

    if state == "bybit":

        update_user(
            telegram_id,
            {
                "usdt_address": text,
                "last_withdrawal_method": "Bybit UID / Account ID",
            },
        )

        context.user_data.pop("wallet_state", None)

        await update.message.reply_text(
            "✅ Bybit UID / Account ID saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    # -----------------------------------------------------
    # BEP20
    # -----------------------------------------------------

    if state == "bep20":

        update_user(
            telegram_id,
            {
                "usdt_address": text,
                "last_withdrawal_method": "BEP20",
            },
        )

        context.user_data.pop("wallet_state", None)

        await update.message.reply_text(
            "✅ BEP20 USDT address saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    # -----------------------------------------------------
    # CBE account
    # -----------------------------------------------------

    if state == "cbe_account":

        context.user_data["temp_cbe_account"] = text
        context.user_data["wallet_state"] = "cbe_name"

        await update.message.reply_text(
            "🏦 CBE Account Number saved.\n\n"
            "Now send the account holder name."
        )

        return True

    # -----------------------------------------------------
    # CBE name
    # -----------------------------------------------------

    if state == "cbe_name":

        account = context.user_data.get(
            "temp_cbe_account"
        )

        update_user(
            telegram_id,
            {
                "bank_name": text,
                "bank_account": account or "",
                "last_withdrawal_method": "CBE",
            },
        )

        context.user_data.pop("temp_cbe_account", None)
        context.user_data.pop("wallet_state", None)

        await update.message.reply_text(
            "✅ CBE wallet saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    # -----------------------------------------------------
    # Telebirr number
    # -----------------------------------------------------

    if state == "telebirr_number":

        context.user_data["temp_telebirr_number"] = text
        context.user_data["wallet_state"] = "telebirr_name"

        await update.message.reply_text(
            "📱 Telebirr number saved.\n\n"
            "Now send the account holder name."
        )

        return True

    # -----------------------------------------------------
    # Telebirr name
    # -----------------------------------------------------

    if state == "telebirr_name":

        number = context.user_data.get(
            "temp_telebirr_number"
        )

        update_user(
            telegram_id,
            {
                "telebirr_number": number or "",
                "bank_name": text,
                "last_withdrawal_method": "Telebirr",
            },
        )

        context.user_data.pop(
            "temp_telebirr_number",
            None,
        )

        context.user_data.pop(
            "wallet_state",
            None,
        )

        await update.message.reply_text(
            "✅ Telebirr wallet saved successfully.",
            reply_markup=MAIN_MENU,
        )

        return True

    return False


# =========================================================
# WITHDRAW MAIN
# =========================================================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await require_channels(
        update,
        context,
    ):
        return

    user = ensure_user(update)

    if not user:
        return

    withdrawal_count = int(
        user.get("withdrawal_count") or 0
    )

    if withdrawal_count < 2:
        minimum = FIRST_MIN_WITHDRAW_USDT
    else:
        minimum = LATER_MIN_WITHDRAW_USDT

    minimum_etb = minimum * USDT_TO_ETB

    keyboard = [
        [
            InlineKeyboardButton(
                "💵 USDT",
                callback_data="withdraw_usdt",
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
                "🏦 CBE",
                callback_data="withdraw_cbe",
            )
        ],
    ]

    await update.message.reply_text(
        "💸 Withdraw\n\n"
        "Choose withdrawal method:\n\n"
        f"Minimum withdrawal:\n"
        f"💵 {minimum:.2f} USDT\n"
        f"🇪🇹 {minimum_etb:.2f} ETB\n\n"
        "💱 Rate: 1 USDT = 185 ETB",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# WITHDRAW - GET MINIMUM
# =========================================================

def get_minimum_withdrawal(user):
    count = int(
        user.get("withdrawal_count") or 0
    )

    if count < 2:
        return FIRST_MIN_WITHDRAW_USDT

    return LATER_MIN_WITHDRAW_USDT


# =========================================================
# WITHDRAW METHOD CALLBACKS
# =========================================================

async def withdraw_usdt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        update.effective_user.id
    )

    if not user:
        return

    saved = user.get("usdt_address") or ""

    if not saved:
        await query.edit_message_text(
            "❌ USDT wallet is not set.\n\n"
            "Please open 👛 Wallet and add either:\n"
            "🟢 Bybit UID / Account ID\n"
            "or\n"
            "🟢 BEP20 USDT Address"
        )
        return

    context.user_data["withdraw_method"] = "USDT"
    context.user_data["withdraw_state"] = "amount"

    await query.edit_message_text(
        "💵 USDT Withdrawal\n\n"
        "Send the amount you want to withdraw in USDT.\n\n"
        "Example:\n"
        "0.20"
    )


async def withdraw_telebirr(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        update.effective_user.id
    )

    if not user:
        return

    number = user.get("telebirr_number") or ""
    name = user.get("bank_name") or ""

    if not number or not name:
        await query.edit_message_text(
            "❌ Telebirr wallet is not complete.\n\n"
            "Please open 👛 Wallet → 📱 Telebirr "
            "and save your number and name first."
        )
        return

    context.user_data["withdraw_method"] = "Telebirr"
    context.user_data["withdraw_state"] = "amount"

    await query.edit_message_text(
        "📱 Telebirr Withdrawal\n\n"
        "Send the amount you want to withdraw in USDT.\n\n"
        "The ETB equivalent will be calculated "
        "at 1 USDT = 185 ETB."
    )


async def withdraw_cbe(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        update.effective_user.id
    )

    if not user:
        return

    account = user.get("bank_account") or ""
    name = user.get("bank_name") or ""

    if not account or not name:
        await query.edit_message_text(
            "❌ CBE wallet is not complete.\n\n"
            "Please open 👛 Wallet → 🏦 CBE "
            "and save your account number and name first."
        )
        return

    context.user_data["withdraw_method"] = "CBE"
    context.user_data["withdraw_state"] = "amount"

    await query.edit_message_text(
        "🏦 CBE Withdrawal\n\n"
        "Send the amount you want to withdraw in USDT.\n\n"
        "The ETB equivalent will be calculated "
        "at 1 USDT = 185 ETB."
    )


# =========================================================
# WITHDRAW AMOUNT INPUT
# =========================================================

async def process_withdraw_amount(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    state = context.user_data.get(
        "withdraw_state"
    )

    if state != "amount":
        return False

    text = update.message.text.strip()

    try:
        amount = Decimal(text)
    except Exception:
        await update.message.reply_text(
            "❌ Invalid amount.\n\n"
            "Please enter a number.\n"
            "Example: 0.20"
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
        await update.message.reply_text(
            "❌ User account not found."
        )
        return True

    balance_usdt = Decimal(
        str(user.get("balance") or 0)
    )

    minimum = get_minimum_withdrawal(user)

    if amount < minimum:
        await update.message.reply_text(
            "❌ Amount is below the minimum.\n\n"
            f"Minimum: {minimum:.2f} USDT\n"
            f"🇪🇹 {minimum * USDT_TO_ETB:.2f} ETB"
        )
        return True

    if amount > balance_usdt:
        await update.message.reply_text(
            "❌ Insufficient balance.\n\n"
            f"Your balance: {balance_usdt:.6f} USDT"
        )
        return True

    method = context.user_data.get(
        "withdraw_method"
    )

    amount_etb = amount * USDT_TO_ETB

    context.user_data["withdraw_amount"] = str(
        amount
    )

    context.user_data["withdraw_state"] = "confirm"

    keyboard = [
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

    await update.message.reply_text(
        "🔎 Confirm Withdrawal\n\n"
        f"💵 Amount: {amount:.6f} USDT\n"
        f"🇪🇹 Value: {amount_etb:.2f} ETB\n"
        f"💳 Method: {method}\n\n"
        "Do you want to submit this withdrawal request?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    return True


# =========================================================
# GET PAYMENT DETAILS
# =========================================================

def get_payment_details(
    user,
    method,
):
    if method == "USDT":
        address = user.get("usdt_address") or ""

        return f"USDT UID / Address: {address}"

    if method == "CBE":
        account = user.get("bank_account") or ""
        name = user.get("bank_name") or ""

        return (
            f"CBE Account: {account}\n"
            f"Account Name: {name}"
        )

    if method == "Telebirr":
        number = user.get("telebirr_number") or ""
        name = user.get("bank_name") or ""

        return (
            f"Telebirr Number: {number}\n"
            f"Account Name: {name}"
        )

    return ""


# =========================================================
# CONFIRM WITHDRAWAL
# =========================================================

async def withdraw_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:
        await query.edit_message_text(
            "❌ User account not found."
        )
        return

    amount_text = context.user_data.get(
        "withdraw_amount"
    )

    method = context.user_data.get(
        "withdraw_method"
    )

    if not amount_text or not method:
        await query.edit_message_text(
            "❌ Withdrawal session expired.\n\n"
            "Please start again."
        )
        return

    amount = Decimal(amount_text)

    current_balance = Decimal(
        str(user.get("balance") or 0)
    )

    if amount > current_balance:
        await query.edit_message_text(
            "❌ Your balance has changed.\n\n"
            "Insufficient balance."
        )
        return

    payment_details = get_payment_details(
        user,
        method,
    )

    amount_etb = amount * USDT_TO_ETB

    request_data = {
        "user_id": telegram_id,
        "amount_usdt": float(amount),
        "amount_etb": float(amount_etb),
        "method": method,
        "payment_details": payment_details,
        "status": "pending",
    }

    result = (
        supabase
        .table("withdrawal_requests")
        .insert(request_data)
        .execute()
    )

    if not result.data:
        await query.edit_message_text(
            "❌ Failed to create withdrawal request.\n\n"
            "Please try again later."
        )
        return

    request_id = result.data[0]["id"]

    # Clear withdrawal state
    context.user_data.pop(
        "withdraw_amount",
        None,
    )

    context.user_data.pop(
        "withdraw_method",
        None,
    )

    context.user_data.pop(
        "withdraw_state",
        None,
    )

    await query.edit_message_text(
        "✅ Withdrawal request submitted!\n\n"
        f"🆔 Request ID: #{request_id}\n"
        f"💵 Amount: {amount:.6f} USDT\n"
        f"🇪🇹 Value: {amount_etb:.2f} ETB\n"
        f"💳 Method: {method}\n\n"
        "⏳ Status: Pending\n\n"
        "Your request will be reviewed manually."
    )

    # -----------------------------------------------------
    # Notify admin
    # -----------------------------------------------------

    if ADMIN_ID:

        admin_text = (
            "🔔 NEW WITHDRAWAL REQUEST\n\n"
            f"🆔 Request: #{request_id}\n"
            f"👤 User ID: {telegram_id}\n"
            f"👤 Username: "
            f"@{user.username}"
            if user.username
            else
            f"🔔 NEW WITHDRAWAL REQUEST\n\n"
            f"🆔 Request: #{request_id}\n"
            f"👤 User ID: {telegram_id}\n"
        )

        admin_text += (
            f"\n💵 Amount: {amount:.6f} USDT"
            f"\n🇪🇹 Value: {amount_etb:.2f} ETB"
            f"\n💳 Method: {method}"
            f"\n\n📌 Payment details:"
            f"\n{payment_details}"
        )

        keyboard = [
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

        try:
            await context.bot.send_message(
                chat_id=int(ADMIN_ID),
                text=admin_text,
                reply_markup=InlineKeyboardMarkup(
                    keyboard
                ),
            )
        except Exception as e:
            print(
                "Admin notification failed:",
                e,
            )


# =========================================================
# CANCEL WITHDRAWAL
# =========================================================

async def withdraw_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    context.user_data.pop(
        "withdraw_amount",
        None,
    )

    context.user_data.pop(
        "withdraw_method",
        None,
    )

    context.user_data.pop(
        "withdraw_state",
        None,
    )

    await query.edit_message_text(
        "❌ Withdrawal cancelled."
    )


# =========================================================
# ADMIN APPROVE
# =========================================================

async def admin_approve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    if not ADMIN_ID:
        return

    if update.effective_user.id != int(ADMIN_ID):
        await query.answer(
            "⛔ Not authorized.",
            show_alert=True,
        )
        return

    request_id = int(
        query.data.replace(
            "admin_approve_",
            "",
        )
    )

    result = (
        supabase
        .table("withdrawal_requests")
        .select("*")
        .eq("id", request_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        await query.edit_message_text(
            "❌ Withdrawal request not found."
        )
        return

    request = result.data[0]

    if request["status"] != "pending":
        await query.edit_message_text(
            "⚠️ This request has already been processed."
        )
        return

    telegram_id = int(
        request["user_id"]
    )

    user = get_user(telegram_id)

    if not user:
        await query.edit_message_text(
            "❌ User account not found."
        )
        return

    amount = Decimal(
        str(request["amount_usdt"])
    )

    amount_etb = Decimal(
        str(request["amount_etb"])
    )

    current_balance = Decimal(
        str(user.get("balance") or 0)
    )

    if current_balance < amount:
        await query.edit_message_text(
            "❌ Cannot approve.\n\n"
            "User has insufficient balance."
        )
        return

    new_balance = current_balance - amount

    new_balance_etb = (
        new_balance * USDT_TO_ETB
    )

    old_count = int(
        user.get("withdrawal_count") or 0
    )

    old_total_usdt = Decimal(
        str(
            user.get(
                "total_withdrawn_usdt"
            ) or 0
        )
    )

    old_total_etb = Decimal(
        str(
            user.get(
                "total_withdrawn_etb"
            ) or 0
        )
    )

    update_user(
        telegram_id,
        {
            "balance": float(new_balance),
            "balance_etb": float(new_balance_etb),
            "withdrawal_count": old_count + 1,
            "total_withdrawn_usdt": float(
                old_total_usdt + amount
            ),
            "total_withdrawn_etb": float(
                old_total_etb + amount_etb
            ),
            "last_withdrawal_method": request["method"],
        },
    )

    (
        supabase
        .table("withdrawal_requests")
        .update(
            {
                "status": "approved",
                "processed_at": "now()",
            }
        )
        .eq("id", request_id)
        .execute()
    )

    await query.edit_message_text(
        f"✅ Withdrawal #{request_id} approved.\n\n"
        f"💵 {amount:.6f} USDT\n"
        f"🇪🇹 {amount_etb:.2f} ETB"
    )

    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "✅ Withdrawal Approved\n\n"
                f"🆔 Request: #{request_id}\n"
                f"💵 Amount: {amount:.6f} USDT\n"
                f"🇪🇹 Value: {amount_etb:.2f} ETB\n\n"
                "Your withdrawal has been approved."
            ),
        )
    except Exception:
        pass


# =========================================================
# ADMIN REJECT
# =========================================================

async def admin_reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    await query.answer()

    if not ADMIN_ID:
        return

    if update.effective_user.id != int(ADMIN_ID):
        await query.answer(
            "⛔ Not authorized.",
            show_alert=True,
        )
        return

    request_id = int(
        query.data.replace(
            "admin_reject_",
            "",
        )
    )

    result = (
        supabase
        .table("withdrawal_requests")
        .select("*")
        .eq("id", request_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        await query.edit_message_text(
            "❌ Withdrawal request not found."
        )
        return

    request = result.data[0]

    if request["status"] != "pending":
        await query.edit_message_text(
            "⚠️ This request has already been processed."
        )
        return

    (
        supabase
        .table("withdrawal_requests")
        .update(
            {
                "status": "rejected",
                "processed_at": "now()",
            }
        )
        .eq("id", request_id)
        .execute()
    )

    await query.edit_message_text(
        f"❌ Withdrawal #{request_id} rejected.\n\n"
        "User balance was not deducted."
    )

    try:
        await context.bot.send_message(
            chat_id=int(request["user_id"]),
            text=(
                "❌ Withdrawal Rejected\n\n"
                f"🆔 Request: #{request_id}\n\n"
                "Your balance was not deducted."
            ),
        )
    except Exception:
        pass


# =========================================================
# SUPPORT
# =========================================================

async def support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🆘 Support\n\n"
        f"Contact support: {SUPPORT_USERNAME}"
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    # Wallet input first
    if await wallet_text_handler(
        update,
        context,
    ):
        return

    # Withdrawal input
    if await process_withdraw_amount(
        update,
        context,
    ):
        return

    text = update.message.text

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
        await support(update, context)


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "balance",
            balance,
        )
    )

    app.add_handler(
        CommandHandler(
            "referral",
            referral,
        )
    )

    app.add_handler(
        CommandHandler(
            "referrals",
            referrals,
        )
    )

    app.add_handler(
        CommandHandler(
            "wallet",
            wallet,
        )
    )

    app.add_handler(
        CommandHandler(
            "withdraw",
            withdraw,
        )
    )

    app.add_handler(
        CommandHandler(
            "support",
            support,
        )
    )

    # -----------------------------------------------------
    # Channel verification
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            verify_channels,
            pattern="^verify_channels$",
        )
    )

    # -----------------------------------------------------
    # Wallet callbacks
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            wallet_usdt,
            pattern="^wallet_usdt$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            wallet_cbe,
            pattern="^wallet_cbe$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            wallet_telebirr,
            pattern="^wallet_telebirr$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            wallet_bybit,
            pattern="^wallet_bybit$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            wallet_bep20,
            pattern="^wallet_bep20$",
        )
    )

    # -----------------------------------------------------
    # Wallet back
    # -----------------------------------------------------

    async def wallet_back(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        query = update.callback_query

        await query.answer()

        keyboard = [
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

        await query.edit_message_text(
            "👛 Wallet\n\n"
            "Choose your payment method:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

    app.add_handler(
        CallbackQueryHandler(
            wallet_back,
            pattern="^wallet_back$",
        )
    )

    # -----------------------------------------------------
    # Withdrawal callbacks
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            withdraw_usdt,
            pattern="^withdraw_usdt$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            withdraw_telebirr,
            pattern="^withdraw_telebirr$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            withdraw_cbe,
            pattern="^withdraw_cbe$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            withdraw_confirm,
            pattern="^withdraw_confirm$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            withdraw_cancel,
            pattern="^withdraw_cancel$",
        )
    )

    # -----------------------------------------------------
    # Admin callbacks
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            admin_approve,
            pattern=r"^admin_approve_\d+$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_reject,
            pattern=r"^admin_reject_\d+$",
        )
    )

    # -----------------------------------------------------
    # Text handler
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            button_handler,
        )
    )

    print(
        "Vortex Earn Bot is running..."
    )

    # -----------------------------------------------------
    # Render Webhook
    # -----------------------------------------------------

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=(
            "https://vortex-earn-bot.onrender.com/"
            f"{TOKEN}"
        ),
    )


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":
    main()
