import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock
from telebot import types
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import requests

# --- Настройки ---
TOKEN = '8758242353:AAGiH1xfNuyGduYiupjpa4gYlodNDMM7LMk'
CHAT_ID = '737143225'
ICON_FOLDER = './icons/'  # Папка с иконками монет: BTC.png, ETH.png и т.д.

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Сброс webhook ---
def force_reset():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        logger.info("Сессия Telegram очищена.")
    except Exception as e:
        logger.error(f"Ошибка сброса webhook: {e}")

force_reset()

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
lock = Lock()
state = {'sent_signals': {}, 'last_direction': {}}

# --- Генерация топового VIP PNG ---
def generate_top_vip_signal(symbol, signal, entry, tp1, tp2, tp3, sl, rsi, atr, tf, rr):
    WIDTH, HEIGHT = 1024, 1024
    BG_COLOR = (18, 18, 18)
    TEXT_COLOR = (255, 255, 255)
    HIGHLIGHT_COLOR = (0, 220, 0) if signal=="BUY" else (255, 60, 60)
    BUTTON_BG = (40, 40, 40)
    BUTTON_HIGHLIGHT = HIGHLIGHT_COLOR

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("arial.ttf", 48)
        font_medium = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 28)
    except:
        font_large = font_medium = font_small = ImageFont.load_default()

    # --- Иконка монеты ---
    coin_name = symbol.split('/')[0]
    icon_path = os.path.join(ICON_FOLDER, f"{coin_name}.png")
    if os.path.exists(icon_path):
        icon = Image.open(icon_path).resize((100,100))
        img.paste(icon, (50,40), icon if icon.mode=='RGBA' else None)

    # Заголовок
    draw.text((170,40), f"VIP SIGNAL {signal} {symbol}", fill=HIGHLIGHT_COLOR, font=font_large)

    # Основные данные
    y = 160
    data = {"Entry": entry, "TP1": tp1, "TP2": tp2, "TP3": tp3, "SL": sl, "RSI": rsi, "ATR": atr, "TF": tf, "R/R": rr}
    for k,v in data.items():
        draw.text((50,y), f"{k}: {v}", fill=TEXT_COLOR, font=font_medium)
        y += 55

    # --- R/R графическая полоска ---
    rr_y = y + 20
    rr_height = 30
    rr_width = WIDTH - 100
    draw.rectangle([50, rr_y, 50+rr_width, rr_y+rr_height], fill=(60,60,60))
    tp_pos = int((tp1 - sl)/(tp3 - sl) * rr_width) if tp3 != sl else rr_width
    draw.rectangle([50, rr_y, 50+tp_pos, rr_y+rr_height], fill=(0,220,0) if signal=='BUY' else (255,60,60))
    draw.text((50, rr_y+rr_height+5), "Risk/Reward", fill=TEXT_COLOR, font=font_small)

    # --- Мини-график RSI ---
    rsi_height = 100
    rsi_width = WIDTH - 100
    rsi_y = rr_y + rr_height + 50
    draw.rectangle([50, rsi_y, 50+rsi_width, rsi_y+rsi_height], fill=(30,30,30))
    val = int(rsi_height * (1 - rsi/100))
    draw.line([50, rsi_y+val, 50+rsi_width, rsi_y+val], fill=(0,200,255))

    # --- Кнопки ---
    buttons = ["🟢 Spot BUY", "🔴 Spot SELL", "📈 Futures LONG", "📉 Futures SHORT", "📊 Open Chart"]
    y_button = HEIGHT-150
    button_width, button_height = 180, 60
    gap = 20
    for i, btn in enumerate(buttons):
        x = 50 + i*(button_width+gap)
        color = BUTTON_HIGHLIGHT if ('BUY' in btn and signal=='BUY') or ('SELL' in btn and signal=='SELL') else BUTTON_BG
        draw.rectangle([x, y_button, x+button_width, y_button+button_height], fill=color)
        w,h = draw.textsize(btn, font=font_small)
        draw.text((x + (button_width-w)/2, y_button + (button_height-h)/2), btn, fill=(255,255,255), font=font_small)

    output = BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output

# --- Анализ рынка ---
def analyze_market():
    logger.info(">>> Сканирование всех USDT-пар...")
    try:
        markets = exchange.load_markets()
        symbols_to_scan = [s for s in markets if '/USDT' in s]
    except Exception as e:
        logger.error(f"Ошибка загрузки рынка: {e}")
        return

    for symbol in symbols_to_scan:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=210)
            df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)
            df['vol_avg'] = df['v'].rolling(20).mean()

            price = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]
            vol = df['v'].iloc[-1]
            vol_avg = df['vol_avg'].iloc[-1]

            if any(pd.isna(x) for x in [rsi, ema, atr, vol_avg]):
                continue

            # --- LONG сигнал ---
            if rsi < 30 and price > ema and atr > price*0.003 and vol > vol_avg:
                send_signal(symbol, "BUY", price, atr, rsi)

            # --- SHORT сигнал ---
            if rsi > 70 and price < ema and atr > price*0.003 and vol > vol_avg:
                send_signal(symbol, "SELL", price, atr, rsi)

            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

# --- Функция отправки сигнала ---
def send_signal(symbol, signal, price, atr, rsi):
    now = time.time()
    with lock:
        last_time = state['sent_signals'].get(f"{symbol}_{signal}",0)
        if now - last_time < 7200:
            return
        state['sent_signals'][f"{symbol}_{signal}"] = now

    entry_price = round(price,4)
    tp1 = round(price + atr if signal=='BUY' else price - atr,4)
    tp2 = round(price + atr*1.5 if signal=='BUY' else price - atr*1.5,4)
    tp3 = round(price + atr*2 if signal=='BUY' else price - atr*2,4)
    sl_price = round(price - atr if signal=='BUY' else price + atr,4)
    rr_ratio = "1:2"
    tf = "1H"

    symbol_binance = symbol.replace('/','_')
    urls = {
        "spot_buy": f"https://www.binance.com/en/trade/{symbol_binance}?type=MARKET",
        "spot_sell": f"https://www.binance.com/en/trade/{symbol_binance}?type=MARKET",
        "futures_buy": f"https://www.binance.com/en/futures/{symbol_binance}?type=MARKET",
        "futures_sell": f"https://www.binance.com/en/futures/{symbol_binance}?type=MARKET",
        "chart": f"https://www.tradingview.com/symbols/{symbol_binance}/"
    }

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Spot BUY", url=urls["spot_buy"]),
        types.InlineKeyboardButton("🔴 Spot SELL", url=urls["spot_sell"]),
        types.InlineKeyboardButton("📈 Futures LONG", url=urls["futures_buy"]),
        types.InlineKeyboardButton("📉 Futures SHORT", url=urls["futures_sell"]),
        types.InlineKeyboardButton("📊 Open Chart", url=urls["chart"])
    )

    image = generate_top_vip_signal(symbol, signal, entry_price, tp1, tp2, tp3, sl_price, round(rsi,2), round(atr,4), tf, rr_ratio)
    bot.send_photo(CHAT_ID, photo=image, caption=f"🔔 VIP сигнал {signal} {symbol}", reply_markup=markup)
    logger.info(f"Отправлен топовый VIP сигнал {signal} для {symbol}")

# --- Flask ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Топовый VIP Бот работает"

# --- Команды Telegram ---
@bot.message_handler(commands=['status'])
def cmd_status(m):
    bot.reply_to(m, "🤖 VIP Шкура разьебывае, сканирует все пары USDT!")

@bot.message_handler(commands=['report'])
def cmd_report(m):
    text = "📊 *ТЕКУЩИЙ ОТЧЕТ*\n\n"
    with lock:
        for s,r in state['last_direction'].items():
            text += f"🔹 `{s}` — Последний сигнал: {r}\n"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

# --- Запуск ---
if __name__ == "__main__":
    Thread(target=lambda:(time.sleep(5), analyze_market()), daemon=True).start()
    Thread(target=lambda: [time.sleep(300), analyze_market()], daemon=True).start()
    port = int(os.environ.get("PORT",8080))
    Thread(target=lambda: app.run(host='0.0.0.0',port=port,use_reloader=False), daemon=True).start()
    while True:
        try:
            bot.polling(non_stop=True, interval=3, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)
