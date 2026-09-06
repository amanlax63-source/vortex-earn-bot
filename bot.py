import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from supabase import create_client, Client

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    existing = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", user.id)
        .execute()
    )

    if not existing.data:
        supabase.table("users").insert({
            "telegram_id": user.id,
            "username": user.username or "",
            "balance": 0
        }).execute()

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
        .select("balance")
        .eq("telegram_id", user_id)
        .execute()
    )

    balance_value = result.data[0]["balance"] if result.data else 0

    await update.message.reply_text(
        f"💰 Your Balance\n\n"
        f"Balance: {balance_value} USDT"
    )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    await update.message.reply_text(
        f"🔗 Your Referral Link:\n\n"
        f"{link}\n\n"
        "Invite friends and earn rewards! 🚀"
    )


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👥 Your Referrals\n\n"
        "Total referrals: 0"
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
