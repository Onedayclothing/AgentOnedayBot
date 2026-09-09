from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = "8908882439:AAFjeZ3k-30d4qxHH-AbCvol_cjDypTPXyQ"
GROUP_CHAT_ID = "-1005447296235"  # Group Order របស់អ្នក

async def handle_order_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # បើសារនោះមានពាក្យ "Oneday Clothing — Order"
    if "Oneday Clothing" in user_text:
        customer = update.message.from_user
        username = f"@{customer.username}" if customer.username else "គ្មាន Username"
        
        group_message = f"{user_text}\n\n------------------------\n"
        group_message += f"👤 **Telegram អតិថិជន**: {username}\n"
        group_message += f"🆔 **User ID**: `{customer.id}`"
        
        # ផ្ញើសារចូល Group
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID, 
            text=group_message, 
            parse_mode="Markdown"
        )
        
        # ផ្ញើសារឆ្លើយតបទៅអតិថិជនវិញ
        await update.message.reply_text(
            "✅ **អរគុណសម្រាប់ការកុម្មង់!**\n\nខាងហាង Oneday Clothing បានទទួលព័ត៌មានកុម្មង់របស់អ្នករួចរាល់ហើយ។"
        )

def main():
    app = Application.builder().token(TOKEN).build()
    
    # ចាប់រាល់សារអក្សរដែលផ្ញើចូល Bot
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order_message))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
