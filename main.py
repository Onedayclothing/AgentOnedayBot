import os
import re
import json
import random
import subprocess
from datetime import datetime
import pytz
import psycopg2
import requests
from flask import Flask, render_template_string
from threading import Thread
from playwright.sync_api import sync_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Install Playwright Chromium Browser
try:
    subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception as e:
    print("Playwright install log:", e)

# --- 1. ENV & DATABASE SETUP ---
PORT = int(os.environ.get("PORT", 8080))
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.strip().replace('\r', '').replace('\n', '')

DB_FILE = "licenses.json"
memory_db = {"settings": {"exchangeRate": 4045, "isAutoRate": True}}

if os.path.exists(DB_FILE):
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            memory_db = json.load(f)
            if "settings" not in memory_db:
                memory_db["settings"] = {"exchangeRate": 4045, "isAutoRate": True}
    except Exception as e:
        print("Error reading DB file:", e)

def get_db_connection():
    if DATABASE_URL:
        try:
            return psycopg2.connect(DATABASE_URL, sslmode='require')
        except Exception as e:
            print("PostgreSQL connection error:", e)
    return None

def init_db():
    global memory_db
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS system_store (
                    id INT PRIMARY KEY DEFAULT 1,
                    data JSONB NOT NULL
                );
            """)
            cur.execute("SELECT data FROM system_store WHERE id = 1;")
            row = cur.fetchone()
            if row:
                memory_db = row[0]
                if "settings" not in memory_db:
                    memory_db["settings"] = {"exchangeRate": 4045, "isAutoRate": True}
                print("Database restored successfully from PostgreSQL!")
            else:
                cur.execute("INSERT INTO system_store (id, data) VALUES (1, %s);", (json.dumps(memory_db),))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print("PostgreSQL Init Error:", e)

def save_database(data):
    global memory_db
    memory_db = data
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("File save error:", e)

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_store (id, data) VALUES (1, %s)
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data;
            """, (json.dumps(data),))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print("PostgreSQL Save Error:", e)

def fetch_live_exchange_rate():
    db = memory_db
    if db.get("settings", {}).get("isAutoRate") is False:
        return
    try:
        res = requests.get('https://open.er-api.com/v6/latest/USD').json()
        if res and "rates" in res and "KHR" in res["rates"]:
            live_rate = round(res["rates"]["KHR"])
            db["settings"]["exchangeRate"] = live_rate
            save_database(db)
    except Exception as e:
        print("Error fetching exchange rate:", e)

# --- 2. FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Invoice Bot Telegram Active!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

# --- 3. ORDER PARSER ---
def parse_order_text(text):
    try:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        shop_name = "Oneday Clothing"
        name = "អតិថិជន"
        phone = ""
        address = "ភ្នំពេញ"
        map_url = ""
        items = []
        delivery_fee = 0.0

        i = 0
        while i < len(lines):
            line = lines[i]

            if '— Order' in line or '– Order' in line:
                raw_shop = re.split(r'[—–]', line)[0]
                shop_name = re.sub(r'[^\w\s]', '', raw_shop).strip() or shop_name

            if 'ឈ្មោះ:' in line:
                name = re.sub(r'^[•\-\*]\s*ឈ្មោះ:\s*', '', line).strip()
            if 'លេខទូរស័ព្ទ:' in line:
                phone = re.sub(r'^[•\-\*]\s*លេខទូរស័ព្ទ:\s*', '', line).strip()
            if 'ទីតាំង:' in line or 'អាសយដ្ឋាន:' in line:
                address = re.sub(r'^[•\-\*]\s*(ទីតាំង|អាសយដ្ឋាន):\s*', '', line).strip()
            if 'ទីតាំង Map:' in line or 'Map:' in line:
                map_url = re.sub(r'^[•\-\*]\s*(ទីតាំង Map|Map):\s*', '', line).strip()

            if 'ដឹកជញ្ជូន' in line:
                fee_match = re.search(r'\$([\d\.]+)', line)
                if fee_match:
                    delivery_fee = float(fee_match.group(1))

            item_match = re.match(r'^\d+\.\s+(.+)$', line)
            if item_match and 'សរុប' not in line:
                item_name = item_match.group(1).strip()
                size = "គ្មាន"
                qty = 1.0
                price = 0.0

                if i + 1 < len(lines) and ('Size:' in lines[i + 1] or '×' in lines[i + 1]):
                    next_line = lines[i + 1]
                    i += 1
                    size_match = re.search(r'Size:\s*([^×]+)×\s*([\d\.]+)\s*—\s*\$([\d\.]+)', next_line, re.IGNORECASE)
                    if size_match:
                        size = size_match.group(1).strip()
                        qty = float(size_match.group(2))
                        total_price_item = float(size_match.group(3))
                        price = total_price_item / qty if qty > 0 else total_price_item

                items.append({'name': item_name, 'size': size, 'qty': qty, 'price': price, 'total': qty * price})
            i += 1

        subtotal = sum(item['total'] for item in items)
        grand_total = subtotal + delivery_fee

        return {
            'shopName': shop_name, 'name': name, 'phone': phone,
            'address': address, 'mapUrl': map_url, 'items': items,
            'subtotal': subtotal, 'deliveryFee': delivery_fee, 'grandTotal': grand_total
        }
    except Exception as e:
        print("Parse Error:", e)
        return None

# --- 4. HTML INVOICE TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="km">
<head>
    <meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=Battambang:wght@400;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Battambang', sans-serif;
            width: 750px;
            margin: 0 auto;
            padding: 30px;
            background: #ffffff;
            color: #0f172a;
            box-sizing: border-box;
        }
        .header-bar {
            height: 10px;
            background-color: #0284c7;
            margin: -30px -30px 20px -30px;
        }
        .top-table {
            width: 100%;
            margin-bottom: 10px;
        }
        .shop-name {
            font-size: 26px;
            font-weight: bold;
            color: #000;
            text-transform: uppercase;
        }
        .sub-title {
            font-size: 14px;
            font-weight: bold;
            color: #1e293b;
        }
        .inv-num {
            font-size: 18px;
            font-weight: bold;
            color: #0284c7;
            text-align: right;
        }
        .inv-date {
            font-size: 13px;
            font-weight: bold;
            text-align: right;
        }
        hr {
            border: 0;
            border-top: 2px solid #94a3b8;
            margin: 10px 0 15px 0;
        }
        .customer-info {
            font-size: 15px;
            font-weight: bold;
            line-height: 1.8;
            margin-bottom: 15px;
        }
        .map-url { color: #0284c7; }
        .items-table {
            width: 100%;
            border-collapse: collapse;
        }
        .items-table th {
            background-color: #e2e8f0;
            color: #000;
            font-size: 14px;
            font-weight: bold;
            padding: 8px;
            text-align: left;
        }
        .items-table td {
            padding: 10px 8px;
            border-bottom: 1px solid #cbd5e1;
            font-size: 14px;
            font-weight: bold;
        }
        .text-center { text-align: center; }
        .text-right { text-align: right; }
        .summary-table {
            width: 320px;
            float: right;
            margin-top: 15px;
            font-size: 15px;
            font-weight: bold;
            line-height: 1.8;
        }
        .grand-total {
            border-top: 2px solid #64748b;
            font-size: 18px;
            color: #0284c7;
        }
        .khr-val {
            font-size: 16px;
            color: #000;
            text-align: right;
        }
        .footer {
            clear: both;
            text-align: center;
            padding-top: 40px;
            font-size: 14px;
            font-weight: bold;
            color: #475569;
        }
    </style>
</head>
<body>
    <div class="header-bar"></div>
    <table class="top-table">
        <tr>
            <td>
                <div class="shop-name">{{ data['shopName'] }}</div>
                <div class="sub-title">Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ</div>
            </td>
            <td style="vertical-align: top;">
                <div class="inv-num">#INV-{{ data['invoiceNum'] }}</div>
                <div class="inv-date">Date: {{ data['orderDate'] }}, {{ data['timeStr'] }}</div>
            </td>
        </tr>
    </table>
    <hr>
    <div class="customer-info">
        <div>ឈ្មោះអតិថិជន៖ {{ data['name'] }}</div>
        <div>លេខទូរស័ព្ទ៖ {{ data['phone'] }}</div>
        <div>អាសយដ្ឋាន៖ {{ data['address'] }}</div>
        {% if data['mapUrl'] %}
        <div class="map-url">ទីតាំង Map៖ {{ data['mapUrl'] }}</div>
        {% endif %}
    </div>

    <table class="items-table">
        <thead>
            <tr>
                <th style="width: 6%;">No.</th>
                <th style="width: 44%;">ទំនិញ / Details</th>
                <th style="width: 12%;" class="text-center">ទំហំ</th>
                <th style="width: 10%;" class="text-center">ចំនួន</th>
                <th style="width: 14%;" class="text-right">តម្លៃ/ឯកតា</th>
                <th style="width: 14%;" class="text-right">សរុប</th>
            </tr>
        </thead>
        <tbody>
            {% for item in data['items'] %}
            <tr>
                <td>{{ loop.index }}</td>
                <td>{{ item['name'] }}</td>
                <td class="text-center">{{ item['size'] }}</td>
                <td class="text-center">{{ item['qty'] }}</td>
                <td class="text-right">${{ "%.2f"|format(item['price']) }}</td>
                <td class="text-right">${{ "%.2f"|format(item['total']) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <table class="summary-table">
        <tr>
            <td>ថ្លៃទំនិញសរុប (Subtotal):</td>
            <td class="text-right">${{ "%.2f"|format(data['subtotal']) }}</td>
        </tr>
        <tr>
            <td>ថ្លៃដឹកជញ្ជូន (Delivery Fee):</td>
            <td class="text-right">${{ "%.2f"|format(data['deliveryFee']) }}</td>
        </tr>
        <tr class="grand-total">
            <td>តម្លៃសរុបចុងក្រោយ:</td>
            <td class="text-right">${{ "%.2f"|format(data['grandTotal']) }}</td>
        </tr>
        <tr>
            <td colspan="2" class="khr-val">({{ khr_text }})</td>
        </tr>
    </table>

    <div class="footer">
        សូមអរគុណសម្រាប់ការបញ្ជាទិញ!
    </div>
</body>
</html>
"""

def generate_invoice_images(data, exchange_rate):
    invoice_num = random.randint(100000, 999999)
    tz = pytz.timezone('Asia/Phnom_Penh')
    now = datetime.now(tz)
    order_date = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%I:%M %p').lower()

    full_data = {**data, 'invoiceNum': invoice_num, 'orderDate': order_date, 'timeStr': time_str}

    khr_val = int(round(data['grandTotal'] * exchange_rate))
    khr_text = f"៛ {khr_val:,}"

    with app.app_context():
        rendered_html = render_template_string(HTML_TEMPLATE, data=full_data, khr_text=khr_text)
    
    file_path = f"Invoice_{random.randint(1000, 9999)}.jpg"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page(viewport={"width": 800, "height": 950})
        page.set_content(rendered_html)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=file_path, type="jpeg", full_page=True)
        browser.close()

    return [file_path]

# --- 5. TELEGRAM BOT HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot ដំណើរការជោគជ័យ (Free ឥតគិតថ្លៃ)!\n\nគ្រាន់តែ Copy & Paste អត្ថបទ Order ចូលទីនេះ វានឹងចេញជារូបភាពវិក្កយបត្រស្អាតល្អជូនភ្លាមៗ!")

async def setrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = str(update.message.from_user.id)
    if ADMIN_CHAT_ID and sender_id != str(ADMIN_CHAT_ID):
        await update.message.reply_text("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!")
        return

    args = context.args
    db = memory_db
    if not args:
        rate = db.get("settings", {}).get("exchangeRate", 4045)
        await update.message.reply_text(f"📊 Rate បច្ចុប្បន្ន៖ 1 USD = {rate} KHR")
        return

    val = args[0].lower().strip()
    if val == "auto":
        db["settings"]["isAutoRate"] = True
        save_database(db)
        fetch_live_exchange_rate()
        rate = db["settings"]["exchangeRate"]
        await update.message.reply_text(f"🔄 បើក Auto Exchange Rate រួចរាល់! Rate: {rate}")
    else:
        try:
            rate_num = float(val)
            db["settings"]["isAutoRate"] = False
            db["settings"]["exchangeRate"] = rate_num
            save_database(db)
            await update.message.reply_text(f"✅ កំណត់ Rate ជោគជ័យ៖ 1 USD = {rate_num} KHR")
        except ValueError:
            await update.message.reply_text("❌ លេខមិនត្រឹមត្រូវ!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith('/'):
        return

    if 'Order' in text or 'ព័ត៌មានអតិថិជន' in text or 'ទំនិញ' in text:
        order_data = parse_order_text(text)
        if not order_data or not order_data['items']:
            await update.message.reply_text("❌ មិនអាចអានទម្រង់អត្ថបទបញ្ជាទិញនេះបានទេ!")
            return

        await update.message.reply_text("⏳ កំពុងបង្កើតរូបភាពវិក្កយបត្រ...")

        try:
            db = memory_db
            current_rate = db.get("settings", {}).get("exchangeRate", 4045)
            img_paths = generate_invoice_images(order_data, current_rate)

            caption_text = f"📄 **វិក្កយបត្របញ្ជាទិញ — {order_data['shopName']}**\n\n"
            caption_text += f"👤 **ឈ្មោះ:** {order_data['name']}\n"
            caption_text += f"📞 **លេខទូរស័ព្ទ:** {order_data['phone']}\n"
            caption_text += f"📍 **អាសយដ្ឋាន:** {order_data['address']}\n"

            if order_data['mapUrl']:
                clean_coords = re.sub(r'\s+', '', order_data['mapUrl'])
                caption_text += f"🗺️ **ទីតាំង Map:** {order_data['mapUrl']}\n"
                caption_text += f"🔗 **Google Maps:** https://www.google.com/maps?q={clean_coords}\n"

            khr_total = round(order_data['grandTotal'] * current_rate)
            caption_text += f"\n💰 **តម្លៃសរុប:** ${order_data['grandTotal']:.2f} (៛ {khr_total:,})"

            with open(img_paths[0], 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption_text, parse_mode='Markdown')

            for p in img_paths:
                if os.path.exists(p):
                    os.remove(p)

        except Exception as e:
            print("Error generating invoice:", e)
            await update.message.reply_text(f"❌ មានបញ្ហាក្នុងការបង្កើតរូបភាព៖ {e}")

# --- 6. MAIN RUNNER ---
if __name__ == '__main__':
    init_db()
    fetch_live_exchange_rate()

    # Start Flask Web Server
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is missing!")
    else:
        print("Starting Telegram Bot...")
        app_bot = Application.builder().token(BOT_TOKEN).build()
        app_bot.add_handler(CommandHandler("start", start_command))
        app_bot.add_handler(CommandHandler("setrate", setrate_command))
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        app_bot.run_polling()
