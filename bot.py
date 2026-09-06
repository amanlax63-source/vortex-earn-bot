import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================
# START
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Withdraw 💸", callback_data="withdraw_menu")]
    ]

    await update.message.reply_text(
        "እንኳን ወደ ቦቱ በደህና መጡ! 👋\n\n"
        "ከታች ያለውን Withdraw የሚለውን ይጫኑ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# WITHDRAW MENU
# =========================
async def show_withdraw_menu(query):
    keyboard = [
        [InlineKeyboardButton("USDT 🪙", callback_data="pay_usdt")],
        [InlineKeyboardButton("CBE 🏦", callback_data="pay_cbe")],
        [InlineKeyboardButton("Telebirr 📱", callback_data="pay_telebirr")],
        [InlineKeyboardButton("◀️ Back", callback_data="pay_back")],
    ]

    await query.edit_message_text(
        text="💸 Withdraw\n\n"
        "እባክዎን ገንዘብ ማውጣት የሚፈልጉበትን "
        "መንገድ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# BUTTON HANDLER
# =========================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # Always answer callback first
    await query.answer()

    # -------------------------
    # Withdraw
    # -------------------------
    if data == "withdraw_menu":
        await show_withdraw_menu(query)

    # -------------------------
    # USDT
    # -------------------------
    elif data == "pay_usdt":
        keyboard = [
            [InlineKeyboardButton("◀️ Back", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            text="🪙 USDT Withdraw\n\n"
            "እባክዎን የ USDT (TRC20) wallet addressዎን ያስገቡ።\n\n"
            "ምሳሌ፦\n"
            "`Txxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # CBE
    # -------------------------
    elif data == "pay_cbe":
        keyboard = [
            [InlineKeyboardButton("◀️ Back", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            text="🏦 CBE Withdraw\n\n"
            "እባክዎን የ CBE የሂሳብ ቁጥርዎን ያስገቡ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # Telebirr
    # -------------------------
    elif data == "pay_telebirr":
        keyboard = [
            [InlineKeyboardButton("◀️ Back", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            text="📱 Telebirr Withdraw\n\n"
            "እባክዎን የ Telebirr ስልክ ቁጥርዎን ያስገቡ።\n\n"
            "ምሳሌ፦ 09xxxxxxxx",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # Back to main page
    # -------------------------
    elif data == "pay_back":
        keyboard = [
            [InlineKeyboardButton("Withdraw 💸", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            text="🏠 ዋናው ገጽ\n\n"
            "ከታች ያለውን Withdraw የሚለውን ይጫኑ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# =========================
# MAIN
# =========================
def main():
    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError(
            "BOT_TOKEN environment variable አልተገኘም። "
            "በRender/GitHub Secrets ውስጥ BOT_TOKEN ያስገቡ።"
        )

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))

    print("Bot is running...")

    app.run_polling()


# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()
