import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Logging ማስተካከያ (ስህተት ካለ በግልጽ እንዲታይ)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# /start ትዕዛዝ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Withdraw 💸", callback_data='withdraw_menu')]
    ]
    await update.message.reply_text(
        "እንኳን ወደ ቦቱ በደህና መጡ! 'Withdraw' የሚለውን ይጫኑ፡",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# የአዝራሮች ስራ
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # 1. Withdraw ሲነካ 4ቱን አዝራሮች ማሳየት
    if data == 'withdraw_menu':
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("USDT 🪙", callback_data='pay_usdt')],
            [InlineKeyboardButton("CBE 🏦", callback_data='pay_cbe')],
            [InlineKeyboardButton("Telebirr 📱", callback_data='pay_telebirr')],
            [InlineKeyboardButton("◀️ ተመለስ (Back)", callback_data='pay_back')]
        ]
        await query.edit_message_text(
            text="እባክዎን ገንዘብ ማውጣት የሚፈልጉበትን መንገድ ይምረጡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 2. USDT ሲነካ
    elif data == 'pay_usdt':
        await query.answer(text="USDT ተመርጧል!", show_alert=False)
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ USDT (TRC20) ዋሌት አድራሻዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 3. CBE ሲነካ
    elif data == 'pay_cbe':
        await query.answer(text="CBE ተመርጧል!", show_alert=False)
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ CBE ሂሳብ ቁጥርዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 4. Telebirr ሲነካ
    elif data == 'pay_telebirr':
        await query.answer(text="Telebirr ተመርጧል!", show_alert=False)
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ Telebirr ስልክ ቁጥርዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 5. Back ሲነካ
    elif data == 'pay_back':
        await query.answer()
        keyboard = [[InlineKeyboardButton("Withdraw 💸", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="ወደ ዋናው ገጽ ተመልሰዋል። 'Withdraw' የሚለውን ይጫኑ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def main():
    # ቦት ቶከንዎን እዚህ ያስገቡ
    TOKEN = "YOUR_BOT_TOKEN_HERE"

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))

    print("ቦቱ እየሰራ ነው...")
    app.run_polling()

if __name__ == '__main__':
    main()
