import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

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

# Regex សម្រាប់ចាប់ Link គ្រប់ប្រភេទ
URL_REGEX = r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/[^\s]*)?)'

# ១. លុបសារ System (ពេល Join ឬ Leave Group)
async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
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
        
        # បើជា Administrator ឬ Creator (Owner) មិនបាច់លុបទេ
        if member.status in ['administrator', 'creator']:
            return

        # បើជា Member ធម្មតា ហើយមាន Link គឺលុបចោល
        if re.search(URL_REGEX, message.text, re.IGNORECASE):
            await message.delete()

    except Exception as e:
        print(f"Error checking link/permissions: {e}")

def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not set.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # ប្រើ filters.StatusUpdate.ALL ដើម្បីចាប់រាល់សារ System (Join/Leave/Group Photo Change...)
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))

    # ចាប់លុប Link
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links))

    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
