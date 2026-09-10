import os
import re
import json
import random
import urllib.request
import asyncio
from datetime import datetime
import pytz
import psycopg2
import requests
from flask import Flask, render_template_string
from threading import Thread
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. SETUP KHMER FONT ---
FONTS_DIR = "fonts"
FONT_PATH = os.path.join(FONTS_DIR, "Battambang-Bold.ttf")

def setup_khmer_font():
    if not os.path.exists(FONTS_DIR):
        os.makedirs(FONTS_DIR, exist_ok=True)
    if not os.path.exists(FONT_PATH):
        print("Downloading Khmer Bold Font from Google Fonts...")
        url = "https://github.com/google/fonts/raw/main/ofl/battambang/Battambang-Bold.ttf"
        urllib.request.urlretrieve(url, FONT_PATH)
        print("Khmer Bold Font downloaded successfully!")

setup_khmer_font()

# --- 2. ENV & DATABASE SETUP ---
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

# --- 3. FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Invoice Bot Telegram Active!"

@app.route('/form')
def form():
    return render_template_string("<!DOCTYPE html><html lang='km'><head><meta charset='UTF-8'><title>Invoice Bot</title></head><body style='font-family:sans-serif; text-align:center; padding-top:50px;'><h2>✅ Bot កំពុងដំណើរការក្នុងទម្រង់ Free!</h2><p>សូមត្រឡប់ទៅកាន់ Telegram Bot វិញ ហើយ Copy & Paste អត្ថបទ Order ចូលទីនេះបានភ្លាមៗ។</p></body></html>")

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

# --- 5. CANVAS / IMAGE GENERATOR ---
def wrap_text(draw, text, font, max_width):
    words = text.split(' ')
    lines = []
    current_line = words[0]
    for word in words[1:]:
        bbox = draw.textbbox((0, 0), current_line + " " + word, font=font)
        if bbox[2] - bbox[0] < max_width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

def render_single_page(data, page_items, start_index, page_num, total_pages, exchange_rate):
    scale = 3
    base_width = 850
    is_first_page = page_num == 1
    is_last_page = page_num == total_pages

    font_bold_30 = ImageFont.truetype(FONT_PATH, 30 * scale)
    font_bold_22 = ImageFont.truetype(FONT_PATH, 22 * scale)
    font_bold_19 = ImageFont.truetype(FONT_PATH, 19 * scale)
    font_bold_18 = ImageFont.truetype(FONT_PATH, 18 * scale)
    font_bold_17 = ImageFont.truetype(FONT_PATH, 17 * scale)
    font_bold_16 = ImageFont.truetype(FONT_PATH, 16 * scale)
    font_bold_15 = ImageFont.truetype(FONT_PATH, 15 * scale)

    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    total_items_height = 0
    for item in page_items:
        wrapped = wrap_text(dummy_draw, item['name'], font_bold_16, 220 * scale)
        total_items_height += max(len(wrapped) * 24, 38) + 16

    has_map = bool(data['mapUrl'])
    customer_extra_height = 30 if has_map else 0

    if is_first_page:
        base_height = (260 + total_items_height + 350 + customer_extra_height) if is_last_page else (200 + total_items_height + 200 + customer_extra_height)
    else:
        base_height = (180 + total_items_height + 350) if is_last_page else (120 + total_items_height + 150)

    img = Image.new("RGB", (base_width * scale, base_height * scale), "#ffffff")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, base_width * scale, 12 * scale], fill="#0284c7")

    header_title = data['shopName'].upper() if data['shopName'] else "INVOICE"
    draw.text((50 * scale, 40 * scale), header_title, font=font_bold_30, fill="#000000")
    draw.text((50 * scale, 80 * scale), "Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ", font=font_bold_15, fill="#1e293b")

    page_str = f" (Page {page_num}/{total_pages})" if total_pages > 1 else ""
    inv_num_str = f"#INV-{data['invoiceNum']}{page_str}"
    draw.text((550 * scale, 40 * scale), inv_num_str, font=font_bold_18, fill="#0284c7")
    draw.text((550 * scale, 75 * scale), f"Date: {data['orderDate']}, {data['timeStr']}", font=font_bold_15, fill="#000000")

    draw.line([(50 * scale, 110 * scale), (750 * scale, 110 * scale)], fill="#94a3b8", width=2 * scale)

    start_y = 125
    if is_first_page:
        draw.text((50 * scale, 130 * scale), f"ឈ្មោះអតិថិជន៖ {data['name']}", font=font_bold_17, fill="#000000")
        draw.text((50 * scale, 160 * scale), f"លេខទូរស័ព្ទ៖ {data['phone']}", font=font_bold_17, fill="#000000")
        draw.text((50 * scale, 190 * scale), f"អាសយដ្ឋាន៖ {data['address']}", font=font_bold_17, fill="#000000")
        if has_map:
            draw.text((50 * scale, 220 * scale), f"ទីតាំង Map៖ {data['mapUrl']}", font=font_bold_17, fill="#0284c7")
            start_y = 265
        else:
            start_y = 235

    draw.rectangle([50 * scale, start_y * scale, 750 * scale, (start_y + 42) * scale], fill="#e2e8f0")
    draw.text((65 * scale, (start_y + 8) * scale), "No.", font=font_bold_16, fill="#000000")
    draw.text((120 * scale, (start_y + 8) * scale), "ទំនិញ / Details", font=font_bold_16, fill="#000000")
    draw.text((370 * scale, (start_y + 8) * scale), "ទំហំ", font=font_bold_16, fill="#000000")
    draw.text((440 * scale, (start_y + 8) * scale), "ចំនួន", font=font_bold_16, fill="#000000")
    draw.text((515 * scale, (start_y + 8) * scale), "តម្លៃ/ឯកតា", font=font_bold_16, fill="#000000")
    draw.text((670 * scale, (start_y + 8) * scale), "សរុប", font=font_bold_16, fill="#000000")

    start_y += 47

    for idx, item in enumerate(page_items):
        wrapped_lines = wrap_text(draw, item['name'], font_bold_16, 230 * scale)
        row_height = max(len(wrapped_lines) * 24, 38) + 16
        text_center_y = start_y + (row_height / 2)

        draw.text((65 * scale, (text_center_y - 10) * scale), str(start_index + idx + 1), font=font_bold_16, fill="#000000")
        
        start_text_y = text_center_y - (((len(wrapped_lines) - 1) * 24) / 2) - 10
        for l_idx, line_txt in enumerate(wrapped_lines):
            draw.text((120 * scale, (start_text_y + (l_idx * 24)) * scale), line_txt, font=font_bold_16, fill="#000000")

        draw.text((370 * scale, (text_center_y - 10) * scale), item['size'], font=font_bold_16, fill="#000000")
        draw.text((440 * scale, (text_center_y - 10) * scale), str(int(item['qty']) if item['qty'].is_integer() else item['qty']), font=font_bold_16, fill="#000000")
        draw.text((515 * scale, (text_center_y - 10) * scale), f"${item['price']:.2f}", font=font_bold_16, fill="#000000")
        draw.text((670 * scale, (text_center_y - 10) * scale), f"${item['total']:.2f}", font=font_bold_16, fill="#000000")

        draw.line([(50 * scale, (start_y + row_height) * scale), (750 * scale, (start_y + row_height) * scale)], fill="#cbd5e1", width=1 * scale)
        start_y += row_height

    if is_last_page:
        start_y += 10
        draw.line([(50 * scale, start_y * scale), (750 * scale, start_y * scale)], fill="#64748b", width=2 * scale)

        start_y += 20
        draw.text((50 * scale, start_y * scale), "ថ្លៃទំនិញសរុប (Subtotal):", font=font_bold_17, fill="#0f172a")
        draw.text((650 * scale, start_y * scale), f"${data['subtotal']:.2f}", font=font_bold_17, fill="#0f172a")

        start_y += 28
        draw.text((50 * scale, start_y * scale), "ថ្លៃដឹកជញ្ជូន (Delivery Fee):", font=font_bold_17, fill="#0f172a")
        draw.text((650 * scale, start_y * scale), f"${data['deliveryFee']:.2f}", font=font_bold_17, fill="#0f172a")

        start_y += 32
        draw.line([(50 * scale, start_y * scale), (750 * scale, start_y * scale)], fill="#64748b", width=2 * scale)

        usd_val = f"${data['grandTotal']:.2f}"
        khr_val = f"៛ {round(data['grandTotal'] * exchange_rate):,}"

        start_y += 20
        draw.text((50 * scale, start_y * scale), "តម្លៃសរុបចុងក្រោយ (Grand Total):", font=font_bold_19, fill="#000000")
        draw.text((650 * scale, start_y * scale), usd_val, font=font_bold_22, fill="#0284c7")

        start_y += 30
        draw.text((650 * scale, start_y * scale), f"({khr_val})", font=font_bold_18, fill="#000000")

    draw.text((320 * scale, (base_height - 30) * scale), "សូមអរគុណសម្រាប់ការបញ្ជាទិញ!", font=font_bold_15, fill="#475569")

    path_out = f"Invoice_{random.randint(1000, 9999)}.jpg"
    img.save(path_out, "JPEG")
    return path_out

def generate_invoice_images(data, exchange_rate):
    items_per_page = 10
    total_pages = (len(data['items']) + items_per_page - 1) // items_per_page
    file_paths = []

    invoice_num = random.randint(100000, 999999)
    tz = pytz.timezone('Asia/Phnom_Penh')
    now = datetime.now(tz)
    order_date = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%I:%M %p').lower()

    full_data = {**data, 'invoiceNum': invoice_num, 'orderDate': order_date, 'timeStr': time_str}

    for i in range(total_pages):
        page_items = data['items'][i * items_per_page:(i + 1) * items_per_page]
        img_path = render_single_page(full_data, page_items, i * items_per_page, i + 1, total_pages, exchange_rate)
        file_paths.append(img_path)

    return file_paths

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

            if len(img_paths) == 1:
                with open(img_paths[0], 'rb') as photo:
                    await update.message.reply_photo(photo=photo, caption=caption_text, parse_mode='Markdown')
            else:
                from telegram import InputMediaPhoto
                media = []
                for idx, p in enumerate(img_paths):
                    with open(p, 'rb') as f:
                        if idx == 0:
                            media.append(InputMediaPhoto(media=f.read(), caption=caption_text, parse_mode='Markdown'))
                        else:
                            media.append(InputMediaPhoto(media=f.read()))
                await update.message.reply_media_group(media=media)

            for p in img_paths:
                if os.path.exists(p):
                    os.remove(p)

        except Exception as e:
            print("Error generating invoice:", e)
            await update.message.reply_text(f"❌ មានបញ្ហាក្នុងការបង្កើតរូបភាព៖ {e}")

# --- 7. BACKGROUND TELEGRAM BOT RUNNER ---
def start_bot():
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN is missing!")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start_command))
    app_bot.add_handler(CommandHandler("setrate", setrate_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Telegram Bot Starting...")
    loop.run_until_complete(app_bot.initialize())
    loop.run_until_complete(app_bot.start())
    loop.run_until_complete(app_bot.updater.start_polling())
    loop.run_forever()

# Init Database
init_db()
fetch_live_exchange_rate()

# Start Bot Thread (Run Only Once)
bot_thread = Thread(target=start_bot, daemon=True)
bot_thread.start()
