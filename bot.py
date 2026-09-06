import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from supabase import create_client, Client

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

REF_USDT = 0.012
REF_ETB = 2


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    existing = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", user.id)
        .execute()
    )

    # New user
    if not existing.data:
        referred_by = None

        # Check referral link
        if context.args:
            ref_text = context.args[0]

            if ref_text.startswith("ref_"):
                try:
                    referrer_id = int(ref_text.replace("ref_", ""))

                    # Prevent self-referral
                    if referrer_id != user.id:
                        referrer = (
                            supabase.table("users")
                            .select("telegram_id")
                            .eq("telegram_id", referrer_id)
                            .execute()
                        )

                        if referrer.data:
                            referred_by = referrer_id

                except ValueError:
                    pass

        # Create user
        supabase.table("users").insert({
            "telegram_id": user.id,
            "username": user.username or "",
            "balance": 0,
            "balance_etb": 0,
            "referred_by": referred_by,
            "referral_count": 0,
            "currency": "USDT"
        }).execute()

        # Give commission to referrer ONLY
        if referred_by:
            referrer_data = (
                supabase.table("users")
                .select("currency, balance, balance_etb, referral_count")
                .eq("telegram_id", referred_by)
                .execute()
            )

            if referrer_data.data:
                ref = referrer_data.data[0]
                currency = ref.get("currency") or "USDT"

                if currency == "ETB":
                    new_balance = float(ref.get("balance_etb") or 0) + REF_ETB

                    supabase.table("users").update({
                        "balance_etb": new_balance,
                        "referral_count": (ref.get("referral_count") or 0) + 1
                    }).eq("telegram_id", referred_by).execute()

                    try:
                        await context.bot.send_message(
                            chat_id=referred_by,
                            text=(
                                "🎉 Referral Reward!\n\n"
                                f"👤 New referral joined!\n"
                                f"💰 +{REF_ETB} ETB\n\n"
                                f"Your referral count: "
                                f"{(ref.get('referral_count') or 0) + 1}"
                            )
                        )
                    except Exception:
                        pass

                else:
                    new_balance = float(ref.get("balance") or 0) + REF_USDT

                    supabase.table("users").update({
                        "balance": new_balance,
                        "referral_count": (ref.get("referral_count") or 0) + 1
                    }).eq("telegram_id", referred_by).execute()

                    try:
                        await context.bot.send_message(
                            chat_id=referred_by,
                            text=(
                                "🎉 Referral Reward!\n\n"
                                f"👤 New referral joined!\n"
                                f"💰 +{REF_USDT} USDT\n\n"
                                f"Your referral count: "
                                f"{(ref.get('referral_count') or 0) + 1}"
                            )
                        )
                    except Exception:
                        pass

    await update.message.reply_text(
        "Welcome to Vortex Earn Bot! 🌪️💸\n\n"
        "Complete tasks and earn rewards.\n"
        "Invite friends and earn more! 🚀\n\n"
        "/balance - Check your balance\n"
        "/referral - Get your referral link\n"
        "/referrals - Check your referrals\n"
        "/wallet - Wallet information\n"
        "/withdraw - Withdraw your earnings\n"
        "/support - Contact support"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    result = (
        supabase.table("users")
        .select("balance, balance_etb, currency")
        .eq("telegram_id", user_id)
        .execute()
    )

    if not result.data:
        await update.message.reply_text(
            "Please use /start first."
        )
        return

    data = result.data[0]

    usdt = float(data.get("balance") or 0)
    etb = float(data.get("balance_etb") or 0)

    await update.message.reply_text(
        "💰 Your Balance\n\n"
        f"🪙 USDT: {usdt:.6f}\n"
        f"🇪🇹 ETB: {etb:.2f}"
    )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    await update.message.reply_text(
        "🔗 Your Referral Link\n\n"
        f"{link}\n\n"
        "👥 Invite friends and earn commission!\n\n"
        "🪙 USDT: 0.012 per referral\n"
        "🇪🇹 ETB: 2 ETB per referral\n\n"
        "⚠️ Only the person who invited the new user receives the commission."
    )


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    result = (
        supabase.table("users")
        .select("referral_count")
        .eq("telegram_id", user_id)
        .execute()
    )

    count = result.data[0]["referral_count"] if result.data else 0

    await update.message.reply_text(
        "👥 Your Referrals\n\n"
        f"Total referrals: {count}"
    )


async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👛 Wallet\n\n"
        "No wallet connected yet."
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 Withdraw\n\n"
        "Choose your withdrawal method:\n\n"
        "💵 USDT\n"
        "📱 Telebirr (ETB)\n"
        "🏦 CBE (ETB)"
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Support\n\n"
        "Please contact Vortex Earn Support."
    )


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Supabase environment variables are not set.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("referrals", referrals))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("support", support))

    print("Vortex Earn Bot is running...")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://vortex-earn-bot.onrender.com/{TOKEN}",
    )


if __name__ == "__main__":
    main()
