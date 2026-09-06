import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Welcome to Vortex Earn Bot!\n\n"
        "💰 Complete tasks and earn rewards.\n"
        "🔗 Invite friends and earn more!\n\n"
        "Use the commands below to get started."
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Your balance: 0.00 USDT")


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    await update.message.reply_text(
        f"🔗 Your Referral Link:\n\n{link}\n\n"
        "👥 Invite friends and earn rewards!"
    )


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👥 Your referrals: 0")


async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Wallet\n\nNo wallet connected yet."
    )


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 Withdraw\n\n"
        "Your balance is not enough to make a withdrawal."
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Support\n\n"
        "Please contact Vortex Earn Support."
    )


def main():
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
