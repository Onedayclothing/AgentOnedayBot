const { Telegraf } = require('telegraf');
const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');
const { createCanvas, registerFont } = require('canvas');
const express = require('express');

// --- 1. AUTO DOWNLOAD & REGISTER KHMER BOLD FONT ---
const fontsDir = path.join(__dirname, 'fonts');
const fontPath = path.join(fontsDir, 'Battambang-Bold.ttf');

async function setupKhmerFont() {
  try {
    if (!fs.existsSync(fontsDir)) {
      fs.mkdirSync(fontsDir, { recursive: true });
    }

    if (!fs.existsSync(fontPath)) {
      console.log("Downloading Khmer Bold Font from Google Fonts...");
      const fontUrl = "https://raw.githubusercontent.com/google/fonts/main/ofl/battambang/Battambang-Bold.ttf";
      const response = await fetch(fontUrl);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const arrayBuffer = await response.arrayBuffer();
      const buffer = Buffer.from(arrayBuffer);
      fs.writeFileSync(fontPath, buffer);
      console.log("Khmer Bold Font downloaded successfully!");
    }

    registerFont(fontPath, { family: 'KhmerFont' });
    console.log("Khmer Bold Font registered successfully!");
  } catch (err) {
    console.error("Error setting up Khmer Font:", err.message);
  }
}

// --- 2. SERVER & DATABASE SETUP ---
const app = express();
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

const PORT = process.env.PORT || 8080;
const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || process.env.BOT_TOKEN;
const ADMIN_CHAT_ID = (process.env.ADMIN_CHAT_ID || "").trim();
let DATABASE_URL = process.env.DATABASE_URL;

if (DATABASE_URL) {
  DATABASE_URL = DATABASE_URL.trim().replace(/[\r\n]+/g, '');
}

if (!BOT_TOKEN) {
  console.error("Error: TELEGRAM_BOT_TOKEN is missing!");
  process.exit(1);
}
const bot = new Telegraf(BOT_TOKEN);

let pool = null;
if (DATABASE_URL) {
  pool = new Pool({
    connectionString: DATABASE_URL,
    ssl: { rejectUnauthorized: false }
  });
}

const dbFile = path.join(__dirname, 'licenses.json');
let memoryDB = { 
  settings: { 
    exchangeRate: 4045, 
    isAutoRate: true,
    defaultDeliveryFee: null 
  },
  allowedUsers: {} 
};

if (fs.existsSync(dbFile)) {
  try {
    memoryDB = JSON.parse(fs.readFileSync(dbFile, 'utf8'));
    if (!memoryDB.settings) {
      memoryDB.settings = { exchangeRate: 4045, isAutoRate: true, defaultDeliveryFee: null };
    }
    if (!memoryDB.allowedUsers) {
      memoryDB.allowedUsers = {};
    }
  } catch (e) {
    console.error("Error reading dbFile:", e);
  }
}

async function initDB() {
  if (pool) {
    try {
      await pool.query(`
        CREATE TABLE IF NOT EXISTS system_store (
          id INT PRIMARY KEY DEFAULT 1,
          data JSONB NOT NULL
        );
      `);
      const res = await pool.query(`SELECT data FROM system_store WHERE id = 1;`);
      if (res.rows.length > 0) {
        memoryDB = res.rows[0].data;
        if (!memoryDB.settings) {
          memoryDB.settings = { exchangeRate: 4045, isAutoRate: true, defaultDeliveryFee: null };
        }
        if (!memoryDB.allowedUsers) {
          memoryDB.allowedUsers = {};
        }
        console.log("Database restored successfully from PostgreSQL!");
      } else {
        await pool.query(`INSERT INTO system_store (id, data) VALUES (1, $1);`, [JSON.stringify(memoryDB)]);
      }
    } catch (err) {
      console.error("PostgreSQL Init Error:", err.message);
    }
  }
}

function getDatabase() {
  return memoryDB;
}

async function saveDatabase(data) {
  memoryDB = data;
  try {
    fs.writeFileSync(dbFile, JSON.stringify(data, null, 2));
  } catch (e) {}

  if (pool) {
    try {
      await pool.query(
        `INSERT INTO system_store (id, data) VALUES (1, $1) 
         ON CONFLICT (id) DO UPDATE SET data = $1;`,
        [JSON.stringify(data)]
      );
    } catch (err) {
      console.error("PostgreSQL Save Error:", err.message);
    }
  }
}

async function fetchLiveExchangeRate() {
  const db = getDatabase();
  if (db.settings && db.settings.isAutoRate === false) return;

  try {
    const res = await fetch('https://open.er-api.com/v6/latest/USD');
    const data = await res.json();
    if (data && data.rates && data.rates.KHR) {
      const liveRate = Math.round(data.rates.KHR);
      db.settings.exchangeRate = liveRate;
      await saveDatabase(db);
    }
  } catch (err) {
    console.error("Error fetching live exchange rate:", err.message);
  }
}

// --- 3. TELEGRAM COMMAND MENU ---
async function setupCommandsMenu() {
  try {
    await bot.telegram.setMyCommands([
      { command: 'start', description: 'ចាប់ផ្តើមប្រើប្រាស់ Bot' },
      { command: 'ratebank', description: 'កំណត់ Rate តាមធនាគារ (Live)' },
      { command: 'rate4050', description: 'កំណត់ Rate ថេរ (ឧទាហរណ៍ 4050)' },
      { command: 'deliveryfree', description: 'កំណត់ថ្លៃដឹក Free ($0)' },
      { command: 'delivery1', description: 'កំណត់ថ្លៃដឹក $1 (ឬលេខផ្សេង)' },
      { command: 'deliveryauto', description: 'គិតថ្លៃដឹកតាម Order ដើម' }
    ]);
  } catch (err) {
    console.error("Error setting commands menu:", err.message);
  }
}

// --- 4. START COMMAND HANDLER ---
bot.start(async (ctx) => {
  return ctx.reply("សូមចុចប៊ូតុង 🛍️ Shop now ដើម្បីទិញផលិតផល!");
});

// --- 5. AUTHORIZATION MIDDLEWARE ---
bot.use(async (ctx, next) => {
  if (!ctx.message || !ctx.message.text) return next();
  const text = ctx.message.text.trim();
  const senderId = ctx.from.id ? ctx.from.id.toString() : "";
  const username = (ctx.from.username || "").toLowerCase();
  const db = getDatabase();

  const isAdmin = ADMIN_CHAT_ID && senderId === ADMIN_CHAT_ID;

  // ១. បន្ថែមសិទ្ធិប្រើប្រាស់៖ /username
  const addMatch = text.match(/^\/([a-zA-Z0-9_]+)$/);
  if (addMatch) {
    const targetUser = addMatch[1].toLowerCase();
    const systemCmds = ['start', 'ratebank', 'deliveryfree', 'deliveryauto'];
    
    if (!systemCmds.includes(targetUser) && !targetUser.startsWith('rate') && !targetUser.startsWith('delivery') && !targetUser.startsWith('un')) {
      if (!isAdmin) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិផ្ដល់សិទ្ធិឲ្យ User ផ្សេងទេ!");
      db.allowedUsers[targetUser] = true;
      await saveDatabase(db);
      return ctx.reply(`✅ បានអនុញ្ញាតឱ្យ @${addMatch[1]} ប្រើប្រាស់ Bot រហូតរៀងទៅ!`);
    }
  }

  // ២. លុបសិទ្ធិប្រើប្រាស់៖ /unusername
  const removeMatch = text.match(/^\/un([a-zA-Z0-9_]+)$/i);
  if (removeMatch) {
    if (!isAdmin) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    const targetUser = removeMatch[1].toLowerCase();
    if (db.allowedUsers[targetUser]) {
      delete db.allowedUsers[targetUser];
      await saveDatabase(db);
      return ctx.reply(`❌ បានលុបសិទ្ធិប្រើប្រាស់របស់ @${removeMatch[1]} រួចរាល់!`);
    } else {
      return ctx.reply(`⚠️ មិនមានឈ្មោះ @${removeMatch[1]} ក្នុងបញ្ជីសិទ្ធិស្រាប់ទេ!`);
    }
  }

  // ៣. /ratebank
  if (text.toLowerCase() === '/ratebank') {
    if (!isAdmin && !db.allowedUsers[username]) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    db.settings.isAutoRate = true;
    await saveDatabase(db);
    await fetchLiveExchangeRate();
    return ctx.reply(`🔄 បានកំណត់ប្រើ Live Rate ធនាគារស្វ័យប្រវត្តិ! Rate: ${db.settings.exchangeRate} KHR`);
  }

  // ៤. /rateXXXX
  const rateMatch = text.match(/^\/rate(\d+)$/i);
  if (rateMatch) {
    if (!isAdmin && !db.allowedUsers[username]) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    const customRate = parseFloat(rateMatch[1]);
    db.settings.isAutoRate = false;
    db.settings.exchangeRate = customRate;
    await saveDatabase(db);
    return ctx.reply(`✅ បានកំណត់ Rate ដោយខ្លួនឯង៖ 1 USD = ${customRate} KHR`);
  }

  // ៥. /deliveryfree ឬ /delivery0
  if (text.toLowerCase() === '/deliveryfree' || text.toLowerCase() === '/delivery0') {
    if (!isAdmin && !db.allowedUsers[username]) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    db.settings.defaultDeliveryFee = 0;
    await saveDatabase(db);
    return ctx.reply(`🚚 បានកំណត់ថ្លៃដឹកជញ្ជូនស្វ័យប្រវត្តិ៖ $0.00 (Free)`);
  }

  // ៦. /deliveryXXX
  const delMatch = text.match(/^\/delivery([\d\.]+)$/i);
  if (delMatch) {
    if (!isAdmin && !db.allowedUsers[username]) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    const customDelivery = parseFloat(delMatch[1]);
    db.settings.defaultDeliveryFee = customDelivery;
    await saveDatabase(db);
    return ctx.reply(`🚚 បានកំណត់ថ្លៃដឹកជញ្ជូនស្វ័យប្រវត្តិ៖ $${customDelivery.toFixed(2)}`);
  }

  // ៧. /deliveryauto
  if (text.toLowerCase() === '/deliveryauto') {
    if (!isAdmin && !db.allowedUsers[username]) return ctx.reply("❌ អ្នកគ្មានសិទ្ធិប្រើប្រាស់ Command នេះទេ!");
    db.settings.defaultDeliveryFee = null;
    await saveDatabase(db);
    return ctx.reply(`🔄 ថ្លៃដឹកជញ្ជូននឹងគិតតាមការវាយបញ្ចូលក្នុង Order អត្ថបទដើមវិញ!`);
  }

  return next();
});

// --- 6. GROUP MODERATION ---
bot.on(['new_chat_members', 'left_chat_member'], async (ctx) => {
  try {
    await ctx.deleteMessage();
  } catch (e) {}
});

bot.on('message', async (ctx, next) => {
  if (!ctx.chat || (ctx.chat.type !== 'group' && ctx.chat.type !== 'supergroup')) {
    return next();
  }

  try {
    const member = await ctx.getChatMember(ctx.from.id);
    const isAdminOrOwner = ['administrator', 'creator'].includes(member.status);

    if (!isAdminOrOwner) {
      const text = ctx.message.text || ctx.message.caption || '';
      const hasEntities = ctx.message.entities || ctx.message.caption_entities || [];
      const isLink = hasEntities.some(e => e.type === 'url' || e.type === 'text_link') || /https?:\/\/[^\s]+/gi.test(text);

      if (isLink) {
        await ctx.deleteMessage();
        return;
      }
    }
  } catch (err) {
    console.error("Group Moderation Error:", err.message);
  }

  return next();
});

// --- 7. ORDER PARSER ---
function parseOrderText(text) {
  try {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l);
    let shopName = "Oneday Clothing";
    let name = "អតិថិជន";
    let phone = "";
    let address = "ភ្នំពេញ";
    let mapUrl = "";
    let items = [];
    let deliveryFee = 0;

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i];

      if (line.includes('— Order') || line.includes('– Order')) {
        shopName = line.split(/[—–]/)[0].replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '').trim();
      }

      if (line.includes('ឈ្មោះ:')) {
        name = line.replace(/^[•\-\*]\s*ឈ្មោះ:\s*/, '').trim();
      }
      if (line.includes('លេខទូរស័ព្ទ:')) {
        phone = line.replace(/^[•\-\*]\s*លេខទូរស័ព្ទ:\s*/, '').trim();
      }
      if (line.includes('ទីតាំង:') || line.includes('អាសយដ្ឋាន:')) {
        address = line.replace(/^[•\-\*]\s*(ទីតាំង|អាសយដ្ឋាន):\s*/, '').trim();
      }
      if (line.includes('ទីតាំង Map:') || line.includes('Map:')) {
        mapUrl = line.replace(/^[•\-\*]\s*(ទីតាំង Map|Map):\s*/, '').trim();
      }

      if (line.includes('ដឹកជញ្ជូន')) {
        let feeMatch = line.match(/\$([\d\.]+)/);
        if (feeMatch) {
          deliveryFee = parseFloat(feeMatch[1]) || 0;
        }
      }

      const itemMatch = line.match(/^\d+\.\s+(.+)$/);
      if (itemMatch && !line.includes('សរុប')) {
        let itemName = itemMatch[1].trim();
        let size = "គ្មាន";
        let qty = 1;
        let price = 0;

        if (i + 1 < lines.length && (lines[i + 1].includes('Size:') || lines[i + 1].includes('×'))) {
          let nextLine = lines[i + 1];
          i++;
          let sizeMatch = nextLine.match(/Size:\s*([^×]+)×\s*([\d\.]+)\s*—\s*\$([\d\.]+)/i);
          if (sizeMatch) {
            size = sizeMatch[1].trim();
            qty = parseFloat(sizeMatch[2]) || 1;
            let totalPriceItem = parseFloat(sizeMatch[3]) || 0;
            price = qty > 0 ? totalPriceItem / qty : totalPriceItem;
          }
        }
        items.push({ name: itemName, size, qty, price, total: qty * price });
      }
    }

    const db = getDatabase();
    if (db.settings && db.settings.defaultDeliveryFee !== null && db.settings.defaultDeliveryFee !== undefined) {
      deliveryFee = db.settings.defaultDeliveryFee;
    }

    let subtotal = items.reduce((sum, item) => sum + item.total, 0);
    let grandTotal = subtotal + deliveryFee;

    return { shopName, name, phone, address, mapUrl, currency: "USD", items, subtotal, deliveryFee, grandTotal };
  } catch (err) {
    console.error("Parse Error:", err);
    return null;
  }
}

function wrapText(ctx, text, maxWidth) {
  const words = text.split(' ');
  let lines = [];
  let currentLine = words[0];

  for (let i = 1; i < words.length; i++) {
    const word = words[i];
    const width = ctx.measureText(currentLine + " " + word).width;
    if (width < maxWidth) {
      currentLine += " " + word;
    } else {
      lines.push(currentLine);
      currentLine = word;
    }
  }
  lines.push(currentLine);
  return lines;
}

// --- 8. CANVAS RENDERER ---
function renderSinglePage(data, pageItems, startIndex, pageNum, totalPages, exchangeRate) {
  return new Promise((resolve) => {
    const scale = 3.5;
    const baseWidth = 850;
    const isFirstPage = pageNum === 1;
    const isLastPage = pageNum === totalPages;
    const font = 'KhmerFont, sans-serif';
    
    const canvasTemp = createCanvas(baseWidth * scale, 100 * scale);
    const ctxTemp = canvasTemp.getContext('2d');
    ctxTemp.font = `bold 16px ${font}`;

    let totalItemsHeight = 0;
    pageItems.forEach(item => {
      const wrapped = wrapText(ctxTemp, item.name, 220);
      totalItemsHeight += Math.max(wrapped.length * 24, 38) + 16;
    });

    const hasMap = !!data.mapUrl;
    const customerInfoExtraHeight = hasMap ? 30 : 0;

    const baseHeight = isFirstPage 
      ? (isLastPage ? 260 + totalItemsHeight + 350 + customerInfoExtraHeight : 200 + totalItemsHeight + 200 + customerInfoExtraHeight)
      : (isLastPage ? 180 + totalItemsHeight + 350 : 120 + totalItemsHeight + 150);

    const canvas = createCanvas(baseWidth * scale, baseHeight * scale);
    const ctx = canvas.getContext('2d');

    ctx.scale(scale, scale);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, baseWidth, baseHeight);

    ctx.fillStyle = '#0284c7';
    ctx.fillRect(0, 0, baseWidth, 12);

    const headerTitle = data.shopName ? data.shopName.toUpperCase() : 'INVOICE';
    ctx.fillStyle = '#000000';
    ctx.font = `bold 30px ${font}`;
    ctx.fillText(headerTitle, 50, 62, 450);

    ctx.fillStyle = '#1e293b';
    ctx.font = `bold 15px ${font}`;
    ctx.fillText('Official Purchase Invoice / វិក្កយបត្របញ្ជាទិញ', 50, 88);

    ctx.fillStyle = '#0284c7';
    ctx.font = `bold 18px ${font}`;
    ctx.textAlign = 'right';
    ctx.fillText('#INV-' + data.invoiceNum + (totalPages > 1 ? ' (Page ' + pageNum + '/' + totalPages + ')' : ''), 750, 60);

    ctx.fillStyle = '#000000';
    ctx.font = `bold 15px ${font}`;
    ctx.fillText('Date: ' + data.orderDate + ', ' + data.timeStr, 750, 85);

    ctx.textAlign = 'left';
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(50, 110);
    ctx.lineTo(750, 110);
    ctx.stroke();

    let startY = 125;
    if (isFirstPage) {
      ctx.fillStyle = '#000000';
      ctx.font = `bold 17px ${font}`;
      ctx.fillText('ឈ្មោះអតិថិជន៖ ' + data.name, 50, 142);
      ctx.fillText('លេខទូរស័ព្ទ៖ ' + data.phone, 50, 172);
      ctx.fillText('អាសយដ្ឋាន៖ ' + data.address, 50, 202);
      
      if (hasMap) {
        ctx.fillStyle = '#0284c7';
        ctx.fillText('ទីតាំង Map៖ ' + data.mapUrl, 50, 232);
        startY = 265;
      } else {
        startY = 235;
      }
    }

    ctx.fillStyle = '#e2e8f0';
    ctx.fillRect(50, startY, 700, 42);

    ctx.fillStyle = '#000000';
    ctx.font = `bold 16px ${font}`;
    ctx.fillText('No.', 65, startY + 27);
    ctx.fillText('ទំនិញ / Details', 120, startY + 27);
    ctx.fillText('ទំហំ', 370, startY + 27);
    ctx.fillText('ចំនួន', 440, startY + 27);
    ctx.fillText('តម្លៃ/ឯកតា', 515, startY + 27);
    ctx.textAlign = 'right';
    ctx.fillText('សរុប', 720, startY + 27);

    startY += 47;
    ctx.font = `bold 16px ${font}`;

    pageItems.forEach((item, index) => {
      const wrappedLines = wrapText(ctx, item.name, 230);
      const rowHeight = Math.max(wrappedLines.length * 24, 38) + 16;
      const textCenterY = startY + (rowHeight / 2) + 5;

      ctx.textAlign = 'left';
      ctx.fillStyle = '#000000';
      
      ctx.fillText((startIndex + index + 1).toString(), 65, textCenterY);

      const startTextY = textCenterY - (((wrappedLines.length - 1) * 24) / 2);
      wrappedLines.forEach((lineText, lineIdx) => {
        ctx.fillText(lineText, 120, startTextY + (lineIdx * 24));
      });

      ctx.fillText(item.size, 370, textCenterY);
      ctx.fillText(item.qty.toString(), 440, textCenterY);

      let itemPriceText = '$' + parseFloat(item.price).toFixed(2);
      let itemTotalText = '$' + parseFloat(item.total).toFixed(2);

      ctx.fillText(itemPriceText, 515, textCenterY);
      ctx.textAlign = 'right';
      ctx.fillText(itemTotalText, 720, textCenterY);

      ctx.strokeStyle = '#cbd5e1';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(50, startY + rowHeight);
      ctx.lineTo(750, startY + rowHeight);
      ctx.stroke();

      startY += rowHeight;
    });

    if (isLastPage) {
      startY += 10;
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(50, startY);
      ctx.lineTo(750, startY);
      ctx.stroke();

      startY += 30;
      ctx.textAlign = 'left';
      ctx.fillStyle = '#0f172a';
      ctx.font = `bold 17px ${font}`;
      ctx.fillText('ថ្លៃទំនិញសរុប (Subtotal):', 50, startY);
      ctx.textAlign = 'right';
      ctx.fillText('$' + data.subtotal.toFixed(2), 720, startY);

      startY += 28;
      ctx.textAlign = 'left';
      ctx.fillText('ថ្លៃដឹកជញ្ជូន (Delivery Fee):', 50, startY);
      ctx.textAlign = 'right';
      ctx.fillText('$' + data.deliveryFee.toFixed(2), 720, startY);

      startY += 32;
      ctx.strokeStyle = '#64748b';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(50, startY);
      ctx.lineTo(750, startY);
      ctx.stroke();

      let usdVal = '$' + data.grandTotal.toFixed(2);
      let khrVal = '៛ ' + Math.round(data.grandTotal * exchangeRate).toLocaleString();

      startY += 32;
      ctx.textAlign = 'left';
      ctx.fillStyle = '#000000';
      ctx.font = `bold 19px ${font}`;
      ctx.fillText('តម្លៃសរុបចុងក្រោយ (Grand Total):', 50, startY);

      ctx.textAlign = 'right';
      ctx.fillStyle = '#0284c7';
      ctx.font = `bold 22px ${font}`;
      ctx.fillText(usdVal, 720, startY);

      startY += 28;
      ctx.textAlign = 'right';
      ctx.fillStyle = '#000000';
      ctx.font = `bold 18px ${font}`;
      ctx.fillText('(' + khrVal + ')', 720, startY);
    }

    ctx.textAlign = 'center';
    ctx.fillStyle = '#475569';
    ctx.font = `bold 15px ${font}`;
    ctx.fillText('សូមអរគុណសម្រាប់ការបញ្ជាទិញ!', baseWidth / 2, baseHeight - 20);

    resolve(canvas.toBuffer('image/jpeg'));
  });
}

// Function បង្កើតរូបភាព (Fix ឈ្មោះ Function ត្រូវគ្នា ១០០%)
async function generateInvoiceImages(data, exchangeRate) {
  const itemsPerPage = 10;
  const totalPages = Math.ceil(data.items.length / itemsPerPage);
  const buffers = [];

  const invoiceNum = Math.floor(100000 + Math.random() * 900000);
  const now = new Date();
  const orderDate = now.toLocaleDateString('en-GB');
  const optionsTime = { timeZone: 'Asia/Phnom_Penh', hour: 'numeric', minute: '2-digit', hour12: true };
  const timeStr = new Intl.DateTimeFormat('en-GB', optionsTime).format(now).toLowerCase().replace('pm', 'p.m.').replace('am', 'a.m.');

  const fullData = { ...data, invoiceNum, orderDate, timeStr };

  for (let i = 0; i < totalPages; i++) {
    const pageItems = data.items.slice(i * itemsPerPage, (i + 1) * itemsPerPage);
    const imgBuffer = await renderSinglePage(fullData, pageItems, i * itemsPerPage, i + 1, totalPages, exchangeRate);
    buffers.push(imgBuffer);
  }
  return buffers;
}

// --- 9. EXPRESS ROUTES & MESSAGE HANDLERS ---
app.get('/form', (req, res) => {
  res.send(`<!DOCTYPE html><html lang="km"><head><meta charset="UTF-8"><title>Invoice Bot</title></head><body style="font-family:sans-serif; text-align:center; padding-top:50px;"><h2>✅ Bot កំពុងដំណើរការក្នុងទម្រង់ Free!</h2><p>សូមត្រឡប់ទៅកាន់ Telegram Bot វិញ ហើយ Copy & Paste អត្ថបទ Order ចូលទីនេះបានភ្លាមៗ។</p></body></html>`);
});
app.get('/', (req, res) => res.send('Invoice Bot Telegram Active!'));
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));

bot.on('text', async (ctx, next) => {
  const text = ctx.message.text.trim();
  if (text.startsWith('/')) {
    return next();
  }

  const senderId = ctx.from.id ? ctx.from.id.toString() : "";
  const username = (ctx.from.username || "").toLowerCase();
  const db = getDatabase();

  const isAdmin = ADMIN_CHAT_ID && senderId === ADMIN_CHAT_ID;
  const isAllowed = isAdmin || (username && db.allowedUsers[username]);

  if (!isAllowed) {
    return ctx.reply("❌ អ្នកមិនទាន់ទទួលបានសិទ្ធិប្រើប្រាស់មុខងារបង្កើត Invoice នេះទេ។");
  }

  if (text.includes('Order') || text.includes('ព័ត៌មានអតិថិជន') || text.includes('ទំនិញ')) {
    const orderData = parseOrderText(text);
    if (!orderData || orderData.items.length === 0) {
      return ctx.reply("❌ មិនអាចអានទម្រង់អត្ថបទបញ្ជាទិញនេះបានទេ!");
    }

    await ctx.reply("⏳ កំពុងបង្កើតរូបភាពវិក្កយបត្រ...");

    try {
      const currentRate = db.settings.exchangeRate || 4045;
      const imageBuffers = await generateInvoiceImages(orderData, currentRate);

      const mediaGroup = imageBuffers.map((buf, index) => {
        const filePath = path.join(__dirname, `Invoice_${Date.now()}_${index}.jpg`);
        fs.writeFileSync(filePath, buf);
        return { type: 'photo', media: { source: filePath }, path: filePath };
      });

      let captionText = `📄 **វិក្កយបត្របញ្ជាទិញ — ${orderData.shopName}**\n\n`;
      captionText += `👤 **ឈ្មោះ:** ${orderData.name}\n`;
      captionText += `📞 **លេខទូរស័ព្ទ:** ${orderData.phone}\n`;
      captionText += `📍 **អាសយដ្ឋាន:** ${orderData.address}\n`;

      if (orderData.mapUrl) {
        const cleanCoords = orderData.mapUrl.replace(/\s+/g, '');
        captionText += `🗺️ **ទីតាំង Map:** ${orderData.mapUrl}\n`;
        captionText += `🔗 **Google Maps:** https://www.google.com/maps?q=${cleanCoords}\n`;
      }

      captionText += `\n💰 **តម្លៃសរុប:** $${orderData.grandTotal.toFixed(2)} (៛ ${Math.round(orderData.grandTotal * currentRate).toLocaleString()})`;

      if (mediaGroup.length === 1) {
        await ctx.replyWithPhoto(mediaGroup[0].media, {
          caption: captionText,
          parse_mode: 'Markdown'
        });
      } else {
        mediaGroup[0].caption = captionText;
        mediaGroup[0].parse_mode = 'Markdown';
        await ctx.replyWithMediaGroup(mediaGroup.map(m => ({
          type: 'photo',
          media: m.media,
          caption: m.caption,
          parse_mode: m.parse_mode
        })));
      }

      mediaGroup.forEach(m => {
        if (fs.existsSync(m.path)) fs.unlinkSync(m.path);
      });

      return;
    } catch (err) {
      console.error(err);
      return ctx.reply("❌ មានបញ្ហាក្នុងការបង្កើតរូបភាព៖ " + err.message);
    }
  }

  return next();
});

// --- 10. START APP ---
async function startApp() {
  await setupKhmerFont();
  await initDB();
  fetchLiveExchangeRate();
  setInterval(fetchLiveExchangeRate, 12 * 60 * 60 * 1000);
  
  await setupCommandsMenu();
  
  bot.launch();
  console.log("Bot, Database, and Khmer Font started successfully!");
}

startApp();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
