import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Logging ማስተካከያ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# /start ትዕዛዝ ሲላክ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Withdraw 💸", callback_data='withdraw_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "እንኳን ወደ ቦቱ በደህና መጡ! ገንዘብ ለማውጣት 'Withdraw' የሚለውን ይጫኑ፡",
        reply_markup=reply_markup
    )

# የአዝራሮች (Callback Queries) አስተናጋጅ
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # የቴሌግራም አዝራር ጭነትን ማረጋገጫ (Loading እንዲቆም)

    data = query.data

    # Withdraw ሲነካ አራቱን አዝራሮች ማሳያ
    if data == 'withdraw_menu':
        keyboard = [
            [InlineKeyboardButton("USDT 🪙", callback_data='pay_usdt')],
            [InlineKeyboardButton("CBE 🏦", callback_data='pay_cbe')],
            [InlineKeyboardButton("Telebirr 📱", callback_data='pay_telebirr')],
            [InlineKeyboardButton("◀️ ተመለስ (Back)", callback_data='pay_back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="እባክዎን ገንዘብ ማውጣት የሚፈልጉበትን መንገድ ይምረጡ፡",
            reply_markup=reply_markup
        )

    # USDT ሲመረጥ
    elif data == 'pay_usdt':
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ USDT (TRC20) ዋሌት አድራሻዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # CBE (የኢትዮጵያ ንግድ ባንክ) ሲመረጥ
    elif data == 'pay_cbe':
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ CBE ሂሳብ ቁጥርዎን እና የባንክ አካውንት ስምዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Telebirr ሲመረጥ
    elif data == 'pay_telebirr':
        keyboard = [[InlineKeyboardButton("◀️ ተመለስ", callback_data='withdraw_menu')]]
        await query.edit_message_text(
            text="እባክዎን የ Telebirr ስልክ ቁጥርዎን ያስገቡ፡",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Back (ወደ ዋናው ገጽ መመለሻ) ሲመረጥ
    elif data == 'pay_back':
        keyboard = [
            [InlineKeyboardButton("Withdraw 💸", callback_data='withdraw_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="ወደ ዋናው ማውጫ ተመልሰዋል። 'Withdraw' የሚለውን ይጫኑ፡",
            reply_markup=reply_markup
        )

# ዋናው የቦት ማቀናበሪያ
def main():
    # BOT_TOKEN ቦታ ላይ የእርስዎን ቦት 토ከን ያስገቡ
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers ማገናኘት
    app.add_handler(CommandHandler("start", start))
    
    # የሁሉንም አዝራሮች ስራ የሚያስተናግደው CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button_click))

    print("ቦቱ መስራት ጀምሯል...")
    app.run_polling()

if __name__ == '__main__':
    main()
