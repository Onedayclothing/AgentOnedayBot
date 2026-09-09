import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

WEB_APP_URL = "https://onedayclothing.github.io"

# Health Check Server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Group Guard Bot is Active!")

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
URL_REGEX = r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/[^\s]*)?)'

# ០. មុខងារ /start បង្ហាញប៊ូតុងបើក Mini App
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛍️ បើកហាងទំនិញ / Shop Now", web_app=WebAppInfo(url=WEB_APP_URL))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "សូមស្វាគមន៍មកកាន់ Oneday Clothing! 🛍️\nចុចប៊ូតុងខាងក្រោមដើម្បីចូលមើល និងកុម្មង់ទំនិញ៖",
        reply_markup=reply_markup
    )

# ថែមមុខងារទទួល Order ស្វ័យប្រវត្តិពី Mini App
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message and update.effective_message.web_app_data:
        order_text = update.effective_message.web_app_data.data
        
        # ផ្ញើសារ Confirmation ទៅកាន់ Customer ភ្លាមៗ
        await update.message.reply_text(
            f"✅ **ការកុម្មង់ត្រូវបានបញ្ជូនជោគជ័យ!**\n\n{order_text}\n\nក្រុមការងារនឹងទាក់ទងទៅអ្នកក្នុងពេលឆាប់ៗនេះ។ សូមអរគុណ! 🙏",
            parse_mode="Markdown"
        )

# ១. លុបសារ System (ពេល Join/Leave Group)
async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            if update.message.new_chat_members or update.message.left_chat_member:
                await update.message.delete()
    except Exception as e:
        print(f"Error deleting system message: {e}")

# ២. លុប Link របស់ Member ធម្មតា
async def filter_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat_id = message.chat_id
    user_id = message.from_user.id

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            return

        if re.search(URL_REGEX, message.text, re.IGNORECASE):
            await message.delete()

    except Exception as e:
        print(f"Error checking link/permissions: {e}")

def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not set.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # ថែម Handler សម្រាប់ /start
    app.add_handler(CommandHandler("start", start_command))
    
    # ថែម Handler សម្រាប់ទទួល Order ពី Mini App (tg.sendData)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # លុបសារ System
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_system_message))
    
    # លុប Link
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
