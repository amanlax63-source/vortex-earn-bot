import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("Withdraw 💸", callback_data="withdraw_menu")]
    ]

    await update.message.reply_text(
        "እንኳን ወደ ቦቱ በደህና መጡ! 👋\n\n"
        "ገንዘብ ለማውጣት Withdraw 💸 የሚለውን ይጫኑ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# Buttons
# =========================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # -------------------------
    # Withdraw menu
    # -------------------------
    if data == "withdraw_menu":

        keyboard = [
            [InlineKeyboardButton("USDT 🪙", callback_data="pay_usdt")],
            [InlineKeyboardButton("CBE 🏦", callback_data="pay_cbe")],
            [InlineKeyboardButton("Telebirr 📱", callback_data="pay_telebirr")],
            [InlineKeyboardButton("◀️ Back", callback_data="pay_back")],
        ]

        await query.edit_message_text(
            "💸 Withdraw\n\n"
            "የሚከፈልበትን method ይምረጡ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # USDT
    # -------------------------
    elif data == "pay_usdt":

        context.user_data["withdraw_method"] = "USDT"

        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            "🪙 USDT Withdrawal\n\n"
            "እባክዎን የUSDT TRC20 wallet address ያስገቡ።\n\n"
            "⚠️ TRC20 address ብቻ ይጠቀሙ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # CBE
    # -------------------------
    elif data == "pay_cbe":

        context.user_data["withdraw_method"] = "CBE"

        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            "🏦 CBE Withdrawal\n\n"
            "እባክዎን የCBE የሂሳብ ቁጥርዎን ያስገቡ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # Telebirr
    # -------------------------
    elif data == "pay_telebirr":

        context.user_data["withdraw_method"] = "Telebirr"

        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            "📱 Telebirr Withdrawal\n\n"
            "እባክዎን የTelebirr ስልክ ቁጥርዎን ያስገቡ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # -------------------------
    # Back
    # -------------------------
    elif data == "pay_back":

        keyboard = [
            [InlineKeyboardButton("Withdraw 💸", callback_data="withdraw_menu")]
        ]

        await query.edit_message_text(
            "🏠 ወደ ዋናው ገጽ ተመልሰዋል።",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# =========================
# User sends withdrawal info
# =========================
async def receive_withdraw_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    method = context.user_data.get("withdraw_method")

    # No withdrawal process active
    if not method:
        return

    value = update.message.text.strip()

    if not value:
        await update.message.reply_text(
            "❌ እባክዎን ትክክለኛ መረጃ ያስገቡ።"
        )
        return

    # Save user's information
    context.user_data["withdraw_info"] = value

    # Confirmation buttons
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Confirm",
                callback_data="confirm_withdraw"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="withdraw_menu"
            )
        ],
    ]

    await update.message.reply_text(
        f"📋 Withdrawal Details\n\n"
        f"💳 Method: {method}\n"
        f"📝 Information: {value}\n\n"
        f"እባክዎን መረጃው ትክክል መሆኑን ያረጋግጡ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================
# Confirm withdrawal
# =========================
async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    method = context.user_data.get("withdraw_method")
    info = context.user_data.get("withdraw_info")

    if not method or not info:
        await query.edit_message_text(
            "❌ Withdrawal session አልተገኘም። እባክዎን እንደገና Withdraw ይጀምሩ።"
        )
        return

    await query.edit_message_text(
        "✅ የWithdrawal መረጃዎ ተቀብሏል።\n\n"
        f"💳 Method: {method}\n"
        f"📝 Information: {info}\n\n"
        "⏳ Admin እንዲያረጋግጥ ተልኳል።"
    )

    # Clear withdrawal session
    context.user_data.pop("withdraw_method", None)
    context.user_data.pop("withdraw_info", None)


# =========================
# Main
# =========================
def main():

    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError(
            "BOT_TOKEN environment variable አልተገኘም።"
        )

    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))

    # Inline buttons
    app.add_handler(
        CallbackQueryHandler(
            confirm_withdraw,
            pattern="^confirm_withdraw$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_click,
            pattern="^(withdraw_menu|pay_usdt|pay_cbe|pay_telebirr|pay_back)$"
        )
    )

    # User text
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_withdraw_info
        )
    )

    print("🤖 Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
