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
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- 1. HEALTH CHECK SERVER FOR RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Group Guard & Invoice Bot is Active!")

def run_health_check():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_check, daemon=True).start()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")

# Regex សម្រាប់ចាប់ Link
URL_REGEX = r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/[^\s]*)?)'

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
        print("Khmer Font downloaded successfully!")

setup_khmer_font()

# --- 3. HELPER: TEXT WRAPPER ---
def wrap_text(text, font, max_width, draw):
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
    return lines if lines else [text]

# --- 4. INVOICE PARSER & GENERATOR ---
def parse_order_text(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    shop_name = "Oneday Clothing"
    name = "អតិថិជន"
    phone = ""
    address = "ភ្នំពេញ"
    map_url = ""
    items = []
    delivery_fee = 0.0

    for i, line in enumerate(lines):
        if "— Order" in line or "– Order" in line:
            shop_name = re.sub(r'[\U00010000-\U0010ffff]', '', line.split('—')[0].split('–')[0]).strip()

        if "ឈ្មោះ:" in line:
            name = re.sub(r'^[•\-\*]\s*ឈ្មោះ:\s*', '', line).strip()
        if "លេខទូរស័ព្ទ:" in line:
            phone = re.sub(r'^[•\-\*]\s*លេខទូរស័ព្ទ:\s*', '', line).strip()
        if "ទីតាំង:" in line or "អាសយដ្ឋាន:" in line:
            address = re.sub(r'^[•\-\*]\s*(ទីតាំង|អាសយដ្ឋាន):\s*', '', line).strip()
        if "ទីតាំង Map:" in line or "Map:" in line:
            map_url = re.sub(r'^[•\-\*]\s*(ទីតាំង Map|Map):\s*', '', line).strip()

        if "ដឹកជញ្ជូន" in line:
            match = re.search(r'\$([\d\.]+)', line)
            if match:
                delivery_fee = float(match.group(1))

        item_match = re.match(r'^\d+\.\s+(.+)$', line)
        if item_match and "សរុប" not in line:
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

def render_invoice_image(data, exchange_rate=4045):
    font_large = ImageFont.truetype(FONT_PATH, 30)
    font_medium = ImageFont.truetype(FONT_PATH, 19)
    font_normal = ImageFont.truetype(FONT_PATH, 17)

    width = 850
    temp_img = Image.new("RGB", (width, 100), "white")
    temp_draw = ImageDraw.Draw(temp_img)

    total_items_height = 0
    item_wrapped_lines = []
    for item in data["items"]:
        lines = wrap_text(item["name"], font_normal, 240, temp_draw)
        item_wrapped_lines.append(lines)
        row_h = max(len(lines) * 26, 36) + 16
        total_items_height += row_h

    map_extra_h = 35 if data["mapUrl"] else 0
    height = 580 + total_items_height + map_extra_h

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (width, 14)], fill="#0284c7")

    draw.text((50, 45), data["shopName"].upper(), font=font_large, fill="#000000")
    draw.text((50, 90), "Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ", font=font_normal, fill="#1e293b")

    inv_num = f"#INV-{random.randint(100000, 900000)}"
    now = datetime.now(zoneinfo.ZoneInfo("Asia/Phnom_Penh"))
    date_str = now.strftime("%d/%m/%Y, %I:%M ") + now.strftime("%p").lower().replace("pm", "p.m.").replace("am", "a.m.")

    draw.text((750, 45), inv_num, font=font_medium, fill="#0284c7", anchor="ra")
    draw.text((750, 85), f"Date: {date_str}", font=font_normal, fill="#000000", anchor="ra")

    draw.line([(50, 125), (750, 125)], fill="#cbd5e1", width=1.5)

    y = 145
    draw.text((50, y), f"ឈ្មោះអតិថិជន៖ {data['name']}", font=font_medium, fill="#000000")
    y += 35
    draw.text((50, y), f"លេខទូរស័ព្ទ៖ {data['phone']}", font=font_medium, fill="#000000")
    y += 35
    draw.text((50, y), f"អាសយដ្ឋាន៖ {data['address']}", font=font_medium, fill="#000000")
    y += 35

    if data["mapUrl"]:
        draw.text((50, y), f"ទីតាំង Map៖ {data['mapUrl']}", font=font_medium, fill="#0284c7")
        y += 40
    else:
        y += 10

    draw.rectangle([(50, y), (750, y + 42)], fill="#e2e8f0")
    draw.text((65, y + 10), "No.", font=font_medium, fill="#000000")
    draw.text((120, y + 10), "ទំនិញ / Details", font=font_medium, fill="#000000")
    draw.text((375, y + 10), "ទំហំ", font=font_medium, fill="#000000")
    draw.text((440, y + 10), "ចំនួន", font=font_medium, fill="#000000")
    draw.text((515, y + 10), "តម្លៃ/ឯកតា", font=font_medium, fill="#000000")
    draw.text((720, y + 10), "សរុប", font=font_medium, fill="#000000", anchor="ra")

    y += 52

    for idx, (item, name_lines) in enumerate(zip(data["items"], item_wrapped_lines), start=1):
        row_h = max(len(name_lines) * 26, 36) + 16
        
        draw.text((65, y), str(idx), font=font_normal, fill="#000000")

        line_y = y
        for line in name_lines:
            draw.text((120, line_y), line, font=font_normal, fill="#000000")
            line_y += 26

        draw.text((375, y), item["size"], font=font_normal, fill="#000000")
        draw.text((440, y), str(int(item["qty"])), font=font_normal, fill="#000000")
        draw.text((515, y), f"${item['price']:.2f}", font=font_normal, fill="#000000")
        draw.text((720, y), f"${item['total']:.2f}", font=font_normal, fill="#000000", anchor="ra")

        y += row_h
        draw.line([(50, y), (750, y)], fill="#f1f5f9", width=1)
        y += 10

    y += 10
    draw.line([(50, y), (750, y)], fill="#cbd5e1", width=1.5)
    y += 25

    draw.text((50, y), "ថ្លៃទំនិញសរុប (Subtotal):", font=font_medium, fill="#0f172a")
    draw.text((720, y), f"${data['subtotal']:.2f}", font=font_medium, fill="#000000", anchor="ra")
    y += 30

    draw.text((50, y), "ថ្លៃដឹកជញ្ជូន (Delivery Fee):", font=font_medium, fill="#0f172a")
    draw.text((720, y), f"${data['deliveryFee']:.2f}", font=font_medium, fill="#000000", anchor="ra")
    y += 35

    draw.line([(50, y), (750, y)], fill="#cbd5e1", width=1.5)
    y += 25

    khr_val = f"៛ {int(round(data['grandTotal'] * exchange_rate)):,}"
    draw.text((50, y), "តម្លៃសរុបចុងក្រោយ (Grand Total):", font=font_medium, fill="#000000")
    draw.text((720, y), f"${data['grandTotal']:.2f}", font=font_large, fill="#0284c7", anchor="ra")
    y += 32
    draw.text((720, y), f"({khr_val})", font=font_medium, fill="#000000", anchor="ra")

    draw.text((width / 2, height - 25), "សូមអរគុណសម្រាប់ការបញ្ជាទិញ!", font=font_medium, fill="#64748b", anchor="mm")

    output_path = f"Invoice_{int(datetime.now().timestamp())}.jpg"
    img.save(output_path, "JPEG", quality=95)
    return output_path

# --- 5. BOT HANDLERS ---
async def delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            await update.message.delete()
    except Exception as e:
        print(f"Error deleting system message: {e}")

async def process_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    chat_id = message.chat_id
    user_id = message.from_user.id

    # ក. ចាប់បង្កើត Invoice
    if "Order" in text or "ព័ត៌មានអតិថិជន" in text or "ទំនិញ" in text:
        order_data = parse_order_text(text)
        if order_data and order_data["items"]:
            wait_msg = await message.reply_text("⏳ កំពុងបង្កើតរូបភាពវិក្កយបត្រ...")
            try:
                img_path = render_invoice_image(order_data)

                caption = f"📄 **វិក្កយបត្របញ្ជាទិញ — {order_data['shopName']}**\n\n"
                caption += f"👤 **ឈ្មោះ:** {order_data['name']}\n"
                caption += f"📞 **លេខទូរស័ព្ទ:** {order_data['phone']}\n"
                caption += f"📍 **អាសយដ្ឋាន:** {order_data['address']}\n"

                if order_data["mapUrl"]:
                    clean_coords = order_data["mapUrl"].replace(" ", "")
                    caption += f"🗺️ **ទីតាំង Map:** {order_data['mapUrl']}\n"
                    caption += f"🔗 **Google Maps:** https://www.google.com/maps?q={clean_coords}\n"

                khr = int(round(order_data['grandTotal'] * 4045))
                caption += f"\n💰 **តម្លៃសរុប:** ${order_data['grandTotal']:.2f} (៛ {khr:,})"

                with open(img_path, 'rb') as photo:
                    await message.reply_photo(photo=photo, caption=caption, parse_mode="Markdown")

                await wait_msg.delete()
                if os.path.exists(img_path):
                    os.remove(img_path)
                
                # បញ្ចប់ការធ្វើការត្រឹមនេះ មិនឱ្យបន្តទៅស្កេនលុប Link ទៀតទេ!
                return 

            except Exception as e:
                print(f"Error generating invoice: {e}")
                return

    # ខ. ចាប់លុប Link (សម្រាប់សារធម្មតាដែលមិនមែនជា Order)
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ['administrator', 'creator']:
            if re.search(URL_REGEX, text, re.IGNORECASE):
                await message.delete()
    except Exception as e:
        print(f"Error checking link permissions: {e}")

# --- 6. MAIN FUNCTION ---
def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not set.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_messages))

    print("Bot AgentOneday is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
