const express = require('express');
const TelegramBot = require('node-telegram-bot-api');
const { createCanvas, registerFont } = require('canvas');
const fs = require('fs');
const path = require('path');
const https = require('https');
const { Pool } = require('pg');

const app = express();
const PORT = process.env.PORT || 8080;
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || process.env.BOT_TOKEN;
const DATABASE_URL = process.env.DATABASE_URL;

// --- 1. DOWNLOAD & REGISTER KHMER FONT ---
const fontsDir = path.join(__dirname, 'fonts');
const fontPath = path.join(fontsDir, 'NotoSansKhmer.ttf');

if (!fs.existsSync(fontsDir)) fs.mkdirSync(fontsDir, { recursive: true });

function setupFont() {
  return new Promise((resolve) => {
    if (fs.existsSync(fontPath)) {
      registerFont(fontPath, { family: 'KhmerFont' });
      console.log('Font loaded from cache!');
      return resolve();
    }
    console.log('Downloading Noto Sans Khmer Font...');
    const file = fs.createWriteStream(fontPath);
    https.get('https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskhmer/NotoSansKhmer%5Bwdth%2Cwght%5D.ttf', (res) => {
      res.pipe(file);
      file.on('finish', () => {
        file.close();
        registerFont(fontPath, { family: 'KhmerFont' });
        console.log('Font downloaded and registered successfully!');
        resolve();
      });
    }).on('error', (err) => {
      console.error('Font download error:', err);
      resolve();
    });
  });
}

// --- 2. DATABASE SETUP ---
let pool = DATABASE_URL ? new Pool({ connectionString: DATABASE_URL, ssl: { rejectUnauthorized: false } }) : null;
let exchangeRate = 4045;

async function initDb() {
  if (!pool) return;
  try {
    await pool.query(`CREATE TABLE IF NOT EXISTS system_store (id INT PRIMARY KEY DEFAULT 1, data JSONB NOT NULL);`);
    const res = await pool.query('SELECT data FROM system_store WHERE id = 1;');
    if (res.rows.length > 0 && res.rows[0].data?.settings?.exchangeRate) {
      exchangeRate = res.rows[0].data.settings.exchangeRate;
    }
  } catch (err) {
    console.error('DB Init Error:', err);
  }
}

// --- 3. PARSE ORDER TEXT ---
function parseOrderText(text) {
  try {
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    let shopName = "Oneday Clothing", name = "អតិថិជន", phone = "", address = "ភ្នំពេញ", mapUrl = "";
    let items = [], deliveryFee = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('— Order') || line.includes('– Order')) shopName = line.split(/[—–]/)[0].replace(/[^\w\s]/g, '').trim() || shopName;
      if (line.includes('ឈ្មោះ:')) name = line.replace(/^[•\-\*]\s*ឈ្មោះ:\s*/, '').trim();
      if (line.includes('លេខទូរស័ព្ទ:')) phone = line.replace(/^[•\-\*]\s*លេខទូរស័ព្ទ:\s*/, '').trim();
      if (line.includes('ទីតាំង:') || line.includes('អាសយដ្ឋាន:')) address = line.replace(/^[•\-\*]\s*(ទីតាំង|អាសយដ្ឋាន):\s*/, '').trim();
      if (line.includes('ទីតាំង Map:') || line.includes('Map:')) mapUrl = line.replace(/^[•\-\*]\s*(ទីតាំង Map|Map):\s*/, '').trim();
      if (line.includes('ដឹកជញ្ជូន')) {
        const match = line.match(/\$([\d\.]+)/);
        if (match) deliveryFee = parseFloat(match[1]);
      }

      if (/^\d+\.\s+/.test(line) && !line.includes('សរុប')) {
        let itemName = line.replace(/^\d+\.\s+/, '').trim();
        let size = "គ្មាន", qty = 1, price = 0;

        if (i + 1 < lines.length && (lines[i + 1].includes('Size:') || lines[i + 1].includes('×'))) {
          const sizeMatch = lines[i + 1].match(/Size:\s*([^×]+)×\s*([\d\.]+)\s*—\s*\$([\d\.]+)/i);
          if (sizeMatch) {
            size = sizeMatch[1].trim();
            qty = parseFloat(sizeMatch[2]);
            let total = parseFloat(sizeMatch[3]);
            price = total / qty;
            i++;
          }
        }
        items.push({ name: itemName, size, qty, price, total: qty * price });
      }
    }

    const subtotal = items.reduce((sum, item) => sum + item.total, 0);
    return { shopName, name, phone, address, mapUrl, items, subtotal, deliveryFee, grandTotal: subtotal + deliveryFee };
  } catch (e) {
    return null;
  }
}

// --- 4. RENDER INVOICE CANVAS ---
function renderInvoice(data) {
  const width = 850;
  const itemsHeight = data.items.length * 45;
  const height = 480 + itemsHeight;

  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');

  // Background
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);

  // Top Line
  ctx.fillStyle = '#0284c7';
  ctx.fillRect(0, 0, width, 12);

  // Header
  ctx.fillStyle = '#000000';
  ctx.font = 'bold 28px KhmerFont, sans-serif';
  ctx.fillText(data.shopName.toUpperCase(), 50, 55);

  ctx.font = '15px KhmerFont, sans-serif';
  ctx.fillStyle = '#1e293b';
  ctx.fillText('Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ', 50, 85);

  const invNum = Math.floor(100000 + Math.random() * 900000);
  ctx.fillStyle = '#0284c7';
  ctx.font = 'bold 20px KhmerFont, sans-serif';
  ctx.fillText(`#INV-${invNum}`, 650, 55);

  ctx.fillStyle = '#000000';
  ctx.font = '15px KhmerFont, sans-serif';
  const now = new Date().toLocaleDateString('en-GB');
  ctx.fillText(`Date: ${now}`, 650, 85);

  ctx.strokeStyle = '#94a3b8';
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(50, 110); ctx.lineTo(750, 110); ctx.stroke();

  // Customer Info
  ctx.font = '16px KhmerFont, sans-serif';
  ctx.fillText(`ឈ្មោះអតិថិជន៖ ${data.name}`, 50, 140);
  ctx.fillText(`លេខទូរស័ព្ទ៖ ${data.phone}`, 50, 168);
  ctx.fillText(`អាសយដ្ឋាន៖ ${data.address}`, 50, 196);
  if (data.mapUrl) {
    ctx.fillStyle = '#0284c7';
    ctx.fillText(`ទីតាំង Map៖ ${data.mapUrl}`, 50, 224);
  }

  // Table Header
  let startY = data.mapUrl ? 250 : 220;
  ctx.fillStyle = '#e2e8f0';
  ctx.fillRect(50, startY, 700, 40);

  ctx.fillStyle = '#000000';
  ctx.font = 'bold 16px KhmerFont, sans-serif';
  ctx.fillText('No.', 65, startY + 26);
  ctx.fillText('ទំនិញ / Details', 120, startY + 26);
  ctx.fillText('ទំហំ', 380, startY + 26);
  ctx.fillText('ចំនួន', 450, startY + 26);
  ctx.fillText('តម្លៃ/ឯកតា', 540, startY + 26);
  ctx.fillText('សរុប', 680, startY + 26);

  // Items
  startY += 60;
  data.items.forEach((item, idx) => {
    ctx.font = '16px KhmerFont, sans-serif';
    ctx.fillText(`${idx + 1}`, 65, startY);
    ctx.fillText(item.name, 120, startY);
    ctx.fillText(item.size, 380, startY);
    ctx.fillText(`${item.qty}`, 450, startY);
    ctx.fillText(`$${item.price.toFixed(2)}`, 540, startY);
    ctx.fillText(`$${item.total.toFixed(2)}`, 680, startY);

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(50, startY + 12); ctx.lineTo(750, startY + 12); ctx.stroke();
    startY += 45;
  });

  // Summary
  startY += 10;
  ctx.font = '16px KhmerFont, sans-serif';
  ctx.fillText('ថ្លៃទំនិញសរុប (Subtotal):', 50, startY);
  ctx.fillText(`$${data.subtotal.toFixed(2)}`, 680, startY);

  startY += 30;
  ctx.fillText('ថ្លៃដឹកជញ្ជូន (Delivery Fee):', 50, startY);
  ctx.fillText(`$${data.deliveryFee.toFixed(2)}`, 680, startY);

  startY += 20;
  ctx.strokeStyle = '#64748b';
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(50, startY); ctx.lineTo(750, startY); ctx.stroke();

  startY += 30;
  ctx.font = 'bold 18px KhmerFont, sans-serif';
  ctx.fillText('តម្លៃសរុបចុងក្រោយ (Grand Total):', 50, startY);
  ctx.fillStyle = '#0284c7';
  ctx.font = 'bold 22px KhmerFont, sans-serif';
  ctx.fillText(`$${data.grandTotal.toFixed(2)}`, 680, startY);

  const khrTotal = Math.round(data.grandTotal * exchangeRate).toLocaleString();
  ctx.fillStyle = '#000000';
  ctx.font = '16px KhmerFont, sans-serif';
  ctx.fillText(`(៛ ${khrTotal})`, 680, startY + 25);

  return canvas.toBuffer('image/jpeg');
}

// --- 5. SERVER & BOT START ---
app.get('/', (req, res) => res.send('Invoice Bot Active!'));
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));

setupFont().then(() => {
  initDb();
  if (BOT_TOKEN) {
    const bot = new TelegramBot(BOT_TOKEN, { polling: true });

    bot.onText(/\/start/, (msg) => bot.sendMessage(msg.chat.id, '🤖 Bot ដំណើរការជោគជ័យ! Copy-paste អត្ថបទ Order ដើម្បីបង្កើតវិក្កយបត្រ។'));

    bot.on('message', async (msg) => {
      const text = msg.text || '';
      if (text.startsWith('/')) return;

      if (text.includes('Order') || text.includes('ទំនិញ')) {
        const orderData = parseOrderText(text);
        if (!orderData || !orderData.items.length) return bot.sendMessage(msg.chat.id, '❌ មិនអាចអានទម្រង់អត្ថបទបញ្ជាទិញបានទេ!');

        bot.sendMessage(msg.chat.id, '⏳ កំពុងបង្កើតរូបភាពវិក្កយបត្រ...');
        try {
          const imgBuffer = renderInvoice(orderData);
          bot.sendPhoto(msg.chat.id, imgBuffer, { caption: `📄 **វិក្កយបត្រ — ${orderData.shopName}**` });
        } catch (err) {
          console.error('Render Error:', err);
          bot.sendMessage(msg.chat.id, '❌ មានបញ្ហាក្នុងការបង្កើតរូបភាព!');
        }
      }
    });
  }
});
