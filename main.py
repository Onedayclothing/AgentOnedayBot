import os
import re
import json
import random
import urllib.request
from datetime import datetime
import pytz
import psycopg2
import requests
from flask import Flask, render_template_string
from threading import Thread
import cairosvg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. SETUP KHMER FONT ---
FONTS_DIR = "fonts"
FONT_PATH = os.path.join(FONTS_DIR, "Battambang-Bold.ttf")

def setup_khmer_font():
    if not os.path.exists(FONTS_DIR):
        os.makedirs(FONTS_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        print("Downloading Khmer Font...")
        url = "https://raw.githubusercontent.com/google/fonts/main/ofl/battambang/Battambang-Bold.ttf"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(FONT_PATH, 'wb') as out_file:
            out_file.write(response.read())
        print("Khmer Font downloaded successfully!")

setup_khmer_font()

# --- 2. ENV & DATABASE SETUP ---
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

# --- 3. FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Invoice Bot Telegram Active!"

def run_flask():
    app.run(host='0.0.0.0', port=PORT, use_reloader=False)

# --- 4. ORDER PARSER ---
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

# --- 5. SVG INVOICE GENERATOR (PERFECT KHMER FONT) ---
def generate_invoice_images(data, exchange_rate):
    invoice_num = random.randint(100000, 999999)
    tz = pytz.timezone('Asia/Phnom_Penh')
    now = datetime.now(tz)
    order_date = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%I:%M %p').lower()

    khr_val = f"៛ {int(round(data['grandTotal'] * exchange_rate)):,}"

    # Build SVG table rows
    y = 310
    items_svg = ""
    for idx, item in enumerate(data['items']):
        qty_str = str(int(item['qty'])) if item['qty'].is_integer() else str(item['qty'])
        items_svg += f"""
        <text x="70" y="{y}" font-size="16" fill="#000">{idx + 1}</text>
        <text x="120" y="{y}" font-size="16" fill="#000">{item['name']}</text>
        <text x="380" y="{y}" font-size="16" fill="#000" text-anchor="middle">{item['size']}</text>
        <text x="450" y="{y}" font-size="16" fill="#000" text-anchor="middle">{qty_str}</text>
        <text x="580" y="{y}" font-size="16" fill="#000" text-anchor="end">${item['price']:.2f}</text>
        <text x="730" y="{y}" font-size="16" fill="#000" text-anchor="end">${item['total']:.2f}</text>
        <line x1="50" y1="{y + 12}" x2="750" y2="{y + 12}" stroke="#cbd5e1" stroke-width="1"/>
        """
        y += 45

    map_svg = f'<text x="50" y="225" font-size="17" fill="#0284c7">ទីតាំង Map៖ {data["mapUrl"]}</text>' if data['mapUrl'] else ''

    total_height = max(y + 220, 650)

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="{total_height}" viewBox="0 0 800 {total_height}">
        <style>
            @font-face {{
                font-family: 'KhmerFont';
                src: url('{os.path.abspath(FONT_PATH)}');
            }}
            text {{
                font-family: 'KhmerFont', sans-serif;
                font-weight: bold;
            }}
        </style>
        <rect width="100%" height="100%" fill="#ffffff"/>
        <rect x="0" y="0" width="800" height="12" fill="#0284c7"/>
        
        <text x="50" y="55" font-size="28" fill="#000">{data['shopName'].upper()}</text>
        <text x="50" y="85" font-size="15" fill="#1e293b">Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ</text>

        <text x="750" y="55" font-size="20" fill="#0284c7" text-anchor="end">#INV-{invoice_num}</text>
        <text x="750" y="85" font-size="15" fill="#000" text-anchor="end">Date: {order_date}, {time_str}</text>

        <line x1="50" y1="110" x2="750" y2="110" stroke="#94a3b8" stroke-width="2"/>

        <text x="50" y="140" font-size="17" fill="#000">ឈ្មោះអតិថិជន៖ {data['name']}</text>
        <text x="50" y="168" font-size="17" fill="#000">លេខទូរស័ព្ទ៖ {data['phone']}</text>
        <text x="50" y="196" font-size="17" fill="#000">អាសយដ្ឋាន៖ {data['address']}</text>
        {map_svg}

        <rect x="50" y="250" width="700" height="40" fill="#e2e8f0"/>
        <text x="65" y="275" font-size="16" fill="#000">No.</text>
        <text x="120" y="275" font-size="16" fill="#000">ទំនិញ / Details</text>
        <text x="380" y="275" font-size="16" fill="#000" text-anchor="middle">ទំហំ</text>
        <text x="450" y="275" font-size="16" fill="#000" text-anchor="middle">ចំនួន</text>
        <text x="580" y="275" font-size="16" fill="#000" text-anchor="end">តម្លៃ/ឯកតា</text>
        <text x="730" y="275" font-size="16" fill="#000" text-anchor="end">សរុប</text>

        {items_svg}

        <line x1="50" y1="{y + 10}" x2="750" y2="{y + 10}" stroke="#64748b" stroke-width="2"/>

        <text x="50" y="{y + 40}" font-size="17" fill="#0f172a">ថ្លៃទំនិញសរុប (Subtotal):</text>
        <text x="730" y="{y + 40}" font-size="17" fill="#0f172a" text-anchor="end">${data['subtotal']:.2f}</text>

        <text x="50" y="{y + 70}" font-size="17" fill="#0f172a">ថ្លៃដឹកជញ្ជូន (Delivery Fee):</text>
        <text x="730" y="{y + 70}" font-size="17" fill="#0f172a" text-anchor="end">${data['deliveryFee']:.2f}</text>

        <line x1="50" y1="{y + 90}" x2="750" y2="{y + 90}" stroke="#64748b" stroke-width="2"/>

        <text x="50" y="{y + 120}" font-size="19" fill="#000">តម្លៃសរុបចុងក្រោយ (Grand Total):</text>
        <text x="730" y="{y + 120}" font-size="22" fill="#0284c7" text-anchor="end">${data['grandTotal']:.2f}</text>
        <text x="730" y="{y + 150}" font-size="18" fill="#000" text-anchor="end">({khr_val})</text>

        <text x="400" y="{total_height - 30}" font-size="15" fill="#475569" text-anchor="middle">សូមអរគុណសម្រាប់ការបញ្ជាទិញ!</text>
    </svg>"""

    file_path = f"Invoice_{random.randint(1000, 9999)}.jpg"
    cairosvg.svg2jpeg(bytestring=svg_content.encode('utf-8'), write_to=file_path)
    return [file_path]

# --- 6. TELEGRAM BOT HANDLERS ---
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

# --- 7. MAIN RUNNER ---
if __name__ == '__main__':
    init_db()
    fetch_live_exchange_rate()

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
