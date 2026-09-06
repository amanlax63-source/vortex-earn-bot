import os

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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


# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

# Referral
REF_USDT = 0.015
CONVERT_RATE = 185
REF_ETB = REF_USDT * CONVERT_RATE

# Withdrawal minimums
MIN_WITHDRAW_USDT = 0.12
MIN_WITHDRAW_ETB = MIN_WITHDRAW_USDT * CONVERT_RATE

# Mandatory channels
CHANNELS = [
    ("@Sheger_tech1", "Sheger Tech"),
    ("@EthioVortex1", "Ethio Vortex"),
    ("@ethiocashflow", "Ethio Cash Flow"),
    ("@AmanMoneyLab07", "Aman Money Lab"),
]

SUPPORT_USERNAME = "@AmanM_12"


# =========================
# MENU
# =========================

def main_menu():
    keyboard = [
        ["💰 Balance", "🎯 Tasks"],
        ["👥 Referral", "👛 Wallet"],
        ["💸 Withdraw", "🆘 Support"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================
# CHANNEL CHECK
# =========================

async def check_membership(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE
):
    not_joined = []

    for channel, name in CHANNELS:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in ["left", "kicked"]:
                not_joined.append((channel, name))

        except Exception:
            not_joined.append((channel, name))

    return not_joined


def channel_keyboard():
    buttons = []

    for channel, name in CHANNELS:
        buttons.append([
            InlineKeyboardButton(
                f"📢 Join {name}",
                url=f"https://t.me/{channel.replace('@', '')}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "✅ Verify",
            callback_data="verify_channels"
        )
    ])

    return InlineKeyboardMarkup(buttons)


async def require_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    not_joined = await check_membership(
        user_id,
        context
    )

    if not_joined:
        text = (
            "🔒 Vortex Earn Bot\n\n"
            "Before you start using the bot, "
            "you must join ALL 4 channels below.\n\n"
            "After joining all channels, press "
            "✅ Verify."
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=channel_keyboard()
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=channel_keyboard()
            )

        return False

    return True


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    existing = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", user.id)
        .execute()
    )

    if not existing.data:

        referred_by = None

        # Referral link
        if context.args:
            ref_text = context.args[0]

            if ref_text.startswith("ref_"):
                try:
                    referrer_id = int(
                        ref_text.replace("ref_", "")
                    )

                    if referrer_id != user.id:

                        referrer = (
                            supabase.table("users")
                            .select("telegram_id")
                            .eq(
                                "telegram_id",
                                referrer_id
                            )
                            .execute()
                        )

                        if referrer.data:
                            referred_by = referrer_id

                except ValueError:
                    pass

        # Create new user
        supabase.table("users").insert({
            "telegram_id": user.id,
            "username": user.username or "",
            "balance": 0,
            "balance_etb": 0,
            "referred_by": referred_by,
            "referral_count": 0,
            "currency": "USDT",
        }).execute()

        # Give referral reward
        # BOTH USDT AND ETB are stored.
        if referred_by:

            referrer_data = (
                supabase.table("users")
                .select(
                    "balance, balance_etb, referral_count"
                )
                .eq(
                    "telegram_id",
                    referred_by
                )
                .execute()
            )

            if referrer_data.data:

                ref = referrer_data.data[0]

                old_usdt = float(
                    ref.get("balance") or 0
                )

                old_etb = float(
                    ref.get("balance_etb") or 0
                )

                old_count = int(
                    ref.get("referral_count") or 0
                )

                new_usdt = old_usdt + REF_USDT
                new_etb = old_etb + REF_ETB
                new_count = old_count + 1

                supabase.table("users").update({
                    "balance": new_usdt,
                    "balance_etb": new_etb,
                    "referral_count": new_count,
                }).eq(
                    "telegram_id",
                    referred_by
                ).execute()

                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=(
                            "🎉 Referral Reward!\n\n"
                            "👤 New referral joined!\n\n"
                            f"🪙 +{REF_USDT:.3f} USDT\n"
                            f"🇪🇹 +{REF_ETB:.3f} ETB\n\n"
                            f"👥 Your referral count: "
                            f"{new_count}"
                        )
                    )
                except Exception:
                    pass

    # Mandatory channel check
    if not await require_channels(
        update,
        context
    ):
        return

    await update.message.reply_text(
        "🎉 Welcome to Vortex Earn Bot! 🌪️💸\n\n"
        "Complete tasks and earn rewards.\n"
        "Invite friends and earn more! 🚀\n\n"
        "Choose an option below:",
        reply_markup=main_menu()
    )


# =========================
# VERIFY
# =========================

async def verify_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    not_joined = await check_membership(
        user_id,
        context
    )

    if not_joined:

        names = "\n".join(
            f"❌ {name}"
            for _, name in not_joined
        )

        await query.edit_message_text(
            "⚠️ You have not joined all required "
            "channels yet.\n\n"
            f"{names}\n\n"
            "Please join the remaining channels "
            "and press ✅ Verify again.",
            reply_markup=channel_keyboard()
        )

        return

    await query.edit_message_text(
        "✅ Verification successful!\n\n"
        "You joined all required channels.\n"
        "Vortex Earn Bot is now ready! 🚀"
    )

    await context.bot.send_message(
        chat_id=user_id,
        text="Choose an option below:",
        reply_markup=main_menu()
    )


# =========================
# BALANCE
# =========================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    user_id = update.effective_user.id

    result = (
        supabase.table("users")
        .select("balance, balance_etb")
        .eq(
            "telegram_id",
            user_id
        )
        .execute()
    )

    if not result.data:
        await update.message.reply_text(
            "Please use /start first."
        )
        return

    data = result.data[0]

    usdt = float(
        data.get("balance") or 0
    )

    etb = float(
        data.get("balance_etb") or 0
    )

    await update.message.reply_text(
        "💰 Balance\n\n"
        f"🪙 USDT = {usdt:.6f} USDT\n"
        f"🇪🇹 ETB = {etb:.2f} ETB\n\n"
        f"💱 Rate: 1 USDT = {CONVERT_RATE} ETB"
    )


# =========================
# REFERRAL
# =========================

async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    user_id = update.effective_user.id

    bot_username = (
        await context.bot.get_me()
    ).username

    link = (
        f"https://t.me/{bot_username}"
        f"?start=ref_{user_id}"
    )

    await update.message.reply_text(
        "🔗 Your Referral Link\n\n"
        f"{link}\n\n"
        "👥 Invite friends and earn commission!\n\n"
        f"🪙 USDT: {REF_USDT:.3f} per referral\n"
        f"🇪🇹 ETB: {REF_ETB:.3f} per referral\n\n"
        "💱 1 USDT = 185 ETB\n\n"
        "⚠️ Only the person who invited "
        "the new user receives the commission."
    )


# =========================
# REFERRALS
# =========================

async def referrals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    user_id = update.effective_user.id

    result = (
        supabase.table("users")
        .select("referral_count")
        .eq(
            "telegram_id",
            user_id
        )
        .execute()
    )

    count = (
        result.data[0]["referral_count"]
        if result.data
        else 0
    )

    await update.message.reply_text(
        "👥 Your Referrals\n\n"
        f"Total referrals: {count}"
    )


# =========================
# TASKS
# =========================

async def tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    await update.message.reply_text(
        "🎯 Tasks\n\n"
        "No tasks available yet.\n\n"
        "More earning tasks will be added soon. 🚀"
    )


# =========================
# WALLET
# =========================

async def wallet(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "💵 USDT",
                callback_data="wallet_usdt"
            )
        ],
        [
            InlineKeyboardButton(
                "🏦 CBE",
                callback_data="wallet_cbe"
            )
        ],
        [
            InlineKeyboardButton(
                "📱 Telebirr",
                callback_data="wallet_telebirr"
            )
        ],
    ]

    await update.message.reply_text(
        "👛 Wallet\n\n"
        "Choose your payment method:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def wallet_usdt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "🟢 Bybit UID / Account ID",
                callback_data="wallet_bybit"
            )
        ],
        [
            InlineKeyboardButton(
                "🟢 BEP20 USDT Address",
                callback_data="wallet_bep20"
            )
        ],
    ]

    await query.edit_message_text(
        "💵 USDT Wallet\n\n"
        "Choose your USDT payout method:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# WITHDRAW
# =========================

async def withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_channels(update, context):
        return

    await update.message.reply_text(
        "💸 Withdraw\n\n"
        "Choose withdrawal method:\n\n"
        "💵 USDT\n"
        "📱 Telebirr\n"
        "🏦 CBE\n\n"
        f"Minimum withdrawal:\n"
        f"💵 {MIN_WITHDRAW_USDT:.2f} USDT\n"
        f"🇪🇹 {MIN_WITHDRAW_ETB:.2f} ETB"
    )


# =========================
# SUPPORT
# =========================

async def support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "🆘 Support\n\n"
        f"Contact support: {SUPPORT_USERNAME}"
    )


# =========================
# BUTTON HANDLER
# =========================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:
        raise ValueError(
            "BOT_TOKEN environment variable is not set."
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Supabase environment variables are not set."
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("balance", balance)
    )

    app.add_handler(
        CommandHandler("referral", referral)
    )

    app.add_handler(
        CommandHandler("referrals", referrals)
    )

    app.add_handler(
        CommandHandler("wallet", wallet)
    )

    app.add_handler(
        CommandHandler("withdraw", withdraw)
    )

    app.add_handler(
        CommandHandler("support", support)
    )

    app.add_handler(
        CallbackQueryHandler(
            verify_channels,
            pattern="^verify_channels$"
        )
    )
    
app.add_handler(
    CallbackQueryHandler(
        wallet_usdt,
        pattern="^wallet_usdt$"
    )
)

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            button_handler
        )
    )

    print("Vortex Earn Bot is running...")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=(
            f"https://vortex-earn-bot.onrender.com/"
            f"{TOKEN}"
        ),
    )

if __name__ == "__main__":
    main()
