import os
import re
import math
import random
import threading
from datetime import datetime
import zoneinfo
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. HEALTH CHECK SERVER FOR RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Service Active!")

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
URL_REGEX = r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/[^\s]*)?)'

# --- GLOBAL EXCHANGE RATE CONFIG ---
CURRENT_EXCHANGE_RATE = 4045
IS_AUTO_RATE = True

def fetch_live_bank_rate():
    global CURRENT_EXCHANGE_RATE
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        data = res.json()
        if data and "rates" in data and "KHR" in data["rates"]:
            live_rate = round(data["rates"]["KHR"])
            CURRENT_EXCHANGE_RATE = live_rate
            return live_rate
    except Exception as e:
        print(f"Error fetching live exchange rate: {e}")
    return CURRENT_EXCHANGE_RATE

# ទាញយក Live Rate ភ្លាមៗពេល Bot ដើរដំបូង
fetch_live_bank_rate()

# --- 2. KHMER FONT SETUP ---
FONT_DIR = "fonts"
FONT_PATH = os.path.join(FONT_DIR, "Battambang-Bold.ttf")

def setup_khmer_font():
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR)
    if not os.path.exists(FONT_PATH):
        print("Downloading Khmer Bold Font...")
        url = "https://github.com/google/fonts/raw/main/ofl/battambang/Battambang-Bold.ttf"
        res = requests.get(url)
        with open(FONT_PATH, "wb") as f:
            f.write(res.content)
        print("Khmer Font downloaded!")

setup_khmer_font()

# --- 3. HELPER: TEXT WRAPPER ---
def wrap_text_max2(text, font, max_width, draw):
    words = text.split(' ')
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(' '.join(current_line))
        
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1][:18] + "..." if len(lines[1]) > 18 else lines[1] + "..."
        
    return lines if lines else [text]

# --- 4. PARSER & MULTI-PAGE GENERATOR ---
def parse_order_text(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    shop_name = "ONEDAY CLOTHING"
    name = "អតិថិជន"
    phone = ""
    address = "ភ្នំពេញ"
    map_url = ""
    items = []
    delivery_fee = 0.0

    for i, line in enumerate(lines):
        if "Order" in line:
            clean_shop = line.replace('🛍️', '').replace('Order', '').replace('—', '').replace('–', '').strip()
            if clean_shop:
                shop_name = clean_shop

        if "ឈ្មោះ:" in line:
            name = re.sub(r'^[🛍️👤📦💰•\-\*]*\s*ឈ្មោះ:\s*', '', line).strip()
        if "លេខទូរស័ព្ទ:" in line:
            phone = re.sub(r'^[🛍️👤📦💰•\-\*]*\s*លេខទូរស័ព្ទ:\s*', '', line).strip()
        if "ទីតាំង:" in line or "អាសយដ្ឋាន:" in line:
            address = re.sub(r'^[🛍️👤📦💰•\-\*]*\s*(ទីតាំង|អាសយដ្ឋាន):\s*', '', line).strip()
        if "ទីតាំង Map:" in line or "Map:" in line:
            if "Link Google Maps:" not in line:
                map_url = re.sub(r'^[🛍️👤📦💰•\-\*]*\s*(ទីតាំង Map|Map):\s*', '', line).strip()

        if "ថ្លៃដឹកជញ្ជូន" in line or "ដឹកជញ្ជូន" in line:
            match = re.search(r'\$([\d\.]+)', line)
            if match:
                delivery_fee = float(match.group(1))

        item_match = re.match(r'^\d+\.\s+(.+)$', line)
        if item_match and "សរុប" not in line and "តម្លៃ" not in line:
            item_name = item_match.group(1).strip()
            size = "គ្មាន"
            qty = 1.0
            price = 0.0

            if i + 1 < len(lines) and ("Size:" in lines[i + 1] or "×" in lines[i + 1]):
                next_line = lines[i + 1]
                size_match = re.search(r'Size:\s*([^×]+)×\s*([\d\.]+)\s*—\s*\$([\d\.]+)', next_line, re.IGNORECASE)
                if size_match:
                    size = size_match.group(1).strip()
                    qty = float(size_match.group(2))
                    total_price_item = float(size_match.group(3))
                    price = total_price_item / qty if qty > 0 else total_price_item

            items.append({
                "name": item_name,
                "size": size,
                "qty": qty,
                "price": price,
                "total": qty * price
            })

    subtotal = sum(item["total"] for item in items)
    grand_total = subtotal + delivery_fee

    return {
        "shopName": shop_name,
        "name": name,
        "phone": phone,
        "address": address,
        "mapUrl": map_url,
        "items": items,
        "subtotal": subtotal,
        "deliveryFee": delivery_fee,
        "grandTotal": grand_total
    }

def render_single_page(data, page_items, start_idx, page_num, total_pages, exchange_rate=None):
    if exchange_rate is None:
        exchange_rate = CURRENT_EXCHANGE_RATE

    S = 3.0
    font_large = ImageFont.truetype(FONT_PATH, int(30 * S))
    font_medium = ImageFont.truetype(FONT_PATH, int(20 * S))
    font_normal = ImageFont.truetype(FONT_PATH, int(18 * S))

    base_width = 850
    width = int(base_width * S)
    
    temp_img = Image.new("RGB", (width, int(100 * S)), "white")
    temp_draw = ImageDraw.Draw(temp_img)

    total_items_height = 0
    item_wrapped_lines = []
    for item in page_items:
        lines = wrap_text_max2(item["name"], font_normal, int(280 * S), temp_draw)
        item_wrapped_lines.append(lines)
        row_h = max(len(lines) * int(30 * S), int(42 * S)) + int(20 * S)
        total_items_height += row_h

    is_first_page = (page_num == 1)
    is_last_page = (page_num == total_pages)

    map_extra_h = int(40 * S) if (is_first_page and data["mapUrl"]) else 0
    cust_info_h = int(140 * S) if is_first_page else 0
    totals_h = int(320 * S) if is_last_page else int(80 * S)

    height = int((240 * S) + cust_info_h + map_extra_h + total_items_height + totals_h)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # Top Accent Line
    draw.rectangle([(0, 0), (width, int(16 * S))], fill="#0284c7")

    # Header
    draw.text((int(40 * S), int(45 * S)), data["shopName"].upper(), font=font_large, fill="#000000")
    draw.text((int(40 * S), int(95 * S)), "Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ", font=font_normal, fill="#0f172a")

    page_str = f" (Page {page_num}/{total_pages})" if total_pages > 1 else ""
    inv_num = f"#INV-{data['inv_num']}{page_str}"
    
    draw.text((int(810 * S), int(45 * S)), inv_num, font=font_medium, fill="#0284c7", anchor="ra")
    draw.text((int(810 * S), int(90 * S)), f"Date: {data['date_str']}", font=font_normal, fill="#000000", anchor="ra")

    draw.line([(int(40 * S), int(135 * S)), (int(810 * S), int(135 * S))], fill="#64748b", width=int(2 * S))

    y = int(155 * S)
    if is_first_page:
        draw.text((int(40 * S), y), f"ឈ្មោះអតិថិជន៖ {data['name']}", font=font_medium, fill="#000000")
        y += int(38 * S)
        draw.text((int(40 * S), y), f"លេខទូរស័ព្ទ៖ {data['phone']}", font=font_medium, fill="#000000")
        y += int(38 * S)
        draw.text((int(40 * S), y), f"អាសយដ្ឋាន៖ {data['address']}", font=font_medium, fill="#000000")
        y += int(38 * S)

        if data["mapUrl"]:
            draw.text((int(40 * S), y), f"ទីតាំង Map៖ {data['mapUrl']}", font=font_medium, fill="#0284c7")
            y += int(45 * S)
        else:
            y += int(10 * S)

    # Table Header Frame
    draw.rectangle([(int(40 * S), y), (int(810 * S), y + int(46 * S))], fill="#e2e8f0")
    draw.text((int(55 * S), y + int(10 * S)), "No.", font=font_medium, fill="#000000")
    draw.text((int(115 * S), y + int(10 * S)), "ទំនិញ / Details", font=font_medium, fill="#000000")
    draw.text((int(420 * S), y + int(10 * S)), "ទំហំ", font=font_medium, fill="#000000")
    draw.text((int(490 * S), y + int(10 * S)), "ចំនួន", font=font_medium, fill="#000000")
    draw.text((int(570 * S), y + int(10 * S)), "តម្លៃ/ឯកតា", font=font_medium, fill="#000000")
    draw.text((int(795 * S), y + int(10 * S)), "សរុប", font=font_medium, fill="#000000", anchor="ra")

    y += int(58 * S)

    # Table Items
    for idx, (item, name_lines) in enumerate(zip(page_items, item_wrapped_lines), start=start_idx):
        row_h = max(len(name_lines) * int(30 * S), int(42 * S)) + int(20 * S)
        
        draw.text((int(55 * S), y), str(idx), font=font_normal, fill="#000000")

        line_y = y
        for line in name_lines:
            draw.text((int(115 * S), line_y), line, font=font_normal, fill="#000000")
            line_y += int(30 * S)

        draw.text((int(420 * S), y), item["size"], font=font_normal, fill="#000000")
        draw.text((int(490 * S), y), str(int(item["qty"])), font=font_normal, fill="#000000")
        draw.text((int(570 * S), y), f"${item['price']:.2f}", font=font_normal, fill="#000000")
        draw.text((int(795 * S), y), f"${item['total']:.2f}", font=font_normal, fill="#000000", anchor="ra")

        y += row_h
        draw.line([(int(40 * S), y), (int(810 * S), y)], fill="#e2e8f0", width=int(1.5 * S))
        y += int(12 * S)

    # Summary Totals
    if is_last_page:
        y += int(15 * S)
        draw.line([(int(40 * S), y), (int(810 * S), y)], fill="#64748b", width=int(2 * S))
        y += int(30 * S)

        draw.text((int(40 * S), y), "ថ្លៃទំនិញសរុប (Subtotal):", font=font_medium, fill="#000000")
        draw.text((int(795 * S), y), f"${data['subtotal']:.2f}", font=font_medium, fill="#000000", anchor="ra")
        y += int(35 * S)

        draw.text((int(40 * S), y), "ថ្លៃដឹកជញ្ជូន (Delivery Fee):", font=font_medium, fill="#000000")
        draw.text((int(795 * S), y), f"${data['deliveryFee']:.2f}", font=font_medium, fill="#000000", anchor="ra")
        y += int(40 * S)

        draw.line([(int(40 * S), y), (int(810 * S), y)], fill="#64748b", width=int(2 * S))
        y += int(35 * S)

        khr_val = f"៛ {int(round(data['grandTotal'] * exchange_rate)):,}"
        draw.text((int(40 * S), y), "តម្លៃសរុបចុងក្រោយ (Grand Total):", font=font_medium, fill="#000000")
        draw.text((int(795 * S), y), f"${data['grandTotal']:.2f}", font=font_large, fill="#0284c7", anchor="ra")
        y += int(40 * S)
        draw.text((int(795 * S), y), f"({khr_val})", font=font_medium, fill="#000000", anchor="ra")
        y += int(30 * S)

    # Footer
    draw.text((int(width / 2), int(height - (30 * S))), "", font=font_medium, fill="#475569", anchor="mm")

    output_path = f"Invoice_{page_num}_{int(datetime.now().timestamp())}.jpg"
    img.save(output_path, "JPEG", quality=100, dpi=(300, 300))
    return output_path

def generate_invoice_images(data):
    items_per_page = 10
    total_pages = math.ceil(len(data["items"]) / items_per_page) if data["items"] else 1
    
    now = datetime.now(zoneinfo.ZoneInfo("Asia/Phnom_Penh"))
    data["inv_num"] = random.randint(100000, 900000)
    data["date_str"] = now.strftime("%d/%m/%Y, %I:%M ") + now.strftime("%p").lower().replace("pm", "p.m.").replace("am", "a.m.")

    paths = []
    for i in range(total_pages):
        page_items = data["items"][i * items_per_page : (i + 1) * items_per_page]
        img_p = render_single_page(data, page_items, (i * items_per_page) + 1, i + 1, total_pages)
        paths.append(img_p)
    return paths

# --- 5. EXCHANGE RATE COMMAND HANDLERS ---
async def set_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_EXCHANGE_RATE, IS_AUTO_RATE
    cmd_text = update.message.text.strip()
    
    # បើវាយ /RateBank
    if cmd_text.lower() == "/ratebank":
        IS_AUTO_RATE = True
        new_rate = fetch_live_bank_rate()
        await update.message.reply_text(f"🔄 បានបើក Auto Live Exchange Rate ពីធនាគារជោគជ័យ!\n📊 Rate បច្ចុប្បន្ន៖ 1 USD = {new_rate:,} KHR")
        return

    # បើវាយ /Rate ឬ /rate
    if cmd_text.lower() == "/rate":
        mode_str = "Auto ពីធនាគារ" if IS_AUTO_RATE else "Manual (កំណត់ដោយខ្លួនឯង)"
        await update.message.reply_text(f"📊 Exchange Rate បច្ចុប្បន្ន៖ 1 USD = {CURRENT_EXCHANGE_RATE:,} KHR\n⚙️ ទម្រង់៖ {mode_str}")
        return

    # បើវាយ /Rate4100, /Rate4050 ...
    match = re.match(r'^/Rate(\d+)$', cmd_text, re.IGNORECASE)
    if match:
        new_rate = int(match.group(1))
        CURRENT_EXCHANGE_RATE = new_rate
        IS_AUTO_RATE = False
        await update.message.reply_text(f"✅ បានកំណត់ Exchange Rate ជោគជ័យ!\n📊 1 USD = {new_rate:,} KHR")

# --- 6. SEPARATED BOT HANDLERS ---
async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            await update.message.delete()
    except Exception as e:
        print(f"Error deleting system message: {e}")

async def generate_invoice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    
    # រំលងប្រសិនបើជា Command
    if text.startswith("/"):
        return

    order_data = parse_order_text(text)

    if order_data and order_data["items"]:
        wait_msg = await message.reply_text("⏳ កំពុងបង្កើតរូបភាពវិក្កយបត្រ...")
        try:
            img_paths = generate_invoice_images(order_data)

            caption = f"📄 **វិក្កយបត្របញ្ជាទិញ — {order_data['shopName']}**\n\n"
            caption += f"👤 **ឈ្មោះ:** {order_data['name']}\n"
            caption += f"📞 **លេខទូរស័ព្ទ:** {order_data['phone']}\n"
            caption += f"📍 **អាសយដ្ឋាន:** {order_data['address']}\n"

            if order_data["mapUrl"]:
                clean_coords = order_data["mapUrl"].replace(" ", "")
                caption += f"🗺️ **ទីតាំង Map:** {order_data['mapUrl']}\n"
                caption += f"🔗 **Google Maps:** https://www.google.com/maps?q={clean_coords}\n"

            khr = int(round(order_data['grandTotal'] * CURRENT_EXCHANGE_RATE))
            caption += f"\n💰 **តម្លៃសរុប:** ${order_data['grandTotal']:.2f} (៛ {khr:,})"

            if len(img_paths) == 1:
                with open(img_paths[0], 'rb') as photo:
                    await message.reply_photo(photo=photo, caption=caption, parse_mode="Markdown")
            else:
                from telegram import InputMediaPhoto
                media = []
                for idx, p in enumerate(img_paths):
                    with open(p, 'rb') as photo_file:
                        if idx == 0:
                            media.append(InputMediaPhoto(media=photo_file.read(), caption=caption, parse_mode="Markdown"))
                        else:
                            media.append(InputMediaPhoto(media=photo_file.read()))
                await message.reply_media_group(media=media)

            await wait_msg.delete()
            for p in img_paths:
                if os.path.exists(p):
                    os.remove(p)
        except Exception as e:
            print(f"Error: {e}")
            await wait_msg.edit_text(f"❌ មានបញ្ហាក្នុងការបង្កើតរូបភាព៖ {e}")

async def filter_links_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    if text.startswith("/") or any(k in text for k in ["Order", "ព័ត៌មានអតិថិជន", "ទំនិញ", "ឈ្មោះ:"]):
        return

    try:
        chat_id = message.chat_id
        user_id = message.from_user.id
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            if re.search(URL_REGEX, text, re.IGNORECASE):
                await message.delete()
    except Exception as e:
        print(f"Error checking link permissions: {e}")

# --- 7. MAIN FUNCTION ---
def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not set.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # System Status Update Handler
    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))

    # Rate Command Handlers
    app.add_handler(MessageHandler(filters.Regex(r'^(?i)/rate.*$'), set_rate_command), group=0)

    # Invoice Generator Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_invoice_handler), group=1)

    # Link Filter Handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_links_handler), group=2)

    print("Bot AgentOneday is running with Exchange Rate Tool...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
