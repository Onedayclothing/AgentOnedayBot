import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = "8908882439:AAFjeZ3k-30d4qxHH-AbCvol_cjDypTPXyQ"
GROUP_CHAT_ID = "-1005447296235"  # Group Order របស់អ្នក

async def handle_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text

    # ចាប់យកតែសារណាដែលមានពាក្យ "Oneday Clothing"
    if "Oneday Clothing" in user_text:
        customer = update.message.from_user
        
        # រៀបចំ Username ឬ Direct Link ឆាតទៅកាន់អតិថិជន
        if customer.username:
            customer_username = f"@{customer.username}"
            direct_chat_link = f"https://t.me/{customer.username}"
        else:
            customer_username = "គ្មាន Username"
            direct_chat_link = f"tg://user?id={customer.id}"

        # រៀបចំសារសម្រាប់ Forward ចូល Group
        group_message = (
            f"🔔 **មានការកុម្មង់ទំនិញថ្មី!**\n\n"
            f"{user_text}\n\n"
            f"------------------------\n"
            f"👤 **Telegram អតិថិជន**: {customer_username}\n"
            f"🆔 **User ID**: `{customer.id}`"
        )

        # ប៊ូតុងចុចឆាតទៅកាន់អតិថិជនភ្លាមៗ
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 ឆាតទៅកាន់អតិថិជន", url=direct_chat_link)]
        ])

        try:
            # ផ្ញើសារចូល Group Order
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=group_message,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            # ផ្ញើសារ Confirm ទៅអតិថិជនវិញ
            await update.message.reply_text(
                "✅ **អរគុណសម្រាប់ការកុម្មង់!**\n\n"
                "ខាងហាង Oneday Clothing បានទទួលព័ត៌មានកុម្មង់របស់អ្នករួចរាល់ហើយ។ "
                "ក្រុមការងារនឹងទំនាក់ទំនងទៅអ្នកក្នុងពេលឆាប់ៗនេះ!"
            )
        except Exception as e:
            logging.error(f"Failed to send order message: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    # ចាប់រាល់សារ Text ទាំងអស់ដែលផ្ញើចូល Bot
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order))

    print("Bot Oneday Clothing is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
