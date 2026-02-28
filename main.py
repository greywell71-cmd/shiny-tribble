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
ICON_FOLDER = './icons/'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

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
state = {'sent_signals': {}, 'last_direction': {}, 'history': {}}

# --- Функция генерации VIP PNG ---
def generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, rsi, atr, tf, rr):
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

    # Заголовок
    draw.text((50,40), f"VIP SIGNAL {signal} {symbol}", fill=HIGHLIGHT_COLOR, font=font_large)

    # Основные данные
    y = 160
    data = {"Entry": entry, "TP1": tp1, "TP2": tp2, "TP3": tp3, "SL": sl, "RSI": rsi, "ATR": atr, "TF": tf, "R/R": rr}
    for k,v in data.items():
        draw.text((50,y), f"{k}: {v}", fill=TEXT_COLOR, font=font_medium)
        y += 55

    # Кнопки
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

# --- Отправка сигнала ---
def send_signal(symbol, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        last_time = state['sent_signals'].get(key,0)
        if now - last_time < 7200:
            return
        state['sent_signals'][key] = now
        if symbol not in state['history']:
            state['history'][symbol] = []
    
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

    image = generate_vip_png(symbol, signal, entry_price, tp1, tp2, tp3, sl_price, round(rsi,2), round(atr,4), tf, rr_ratio)
    bot.send_photo(CHAT_ID, photo=image, caption=f"🔔 VIP сигнал {signal} {symbol}", reply_markup=markup)

    # Логируем историю
    state['history'][symbol].append({'signal':signal,'entry':entry_price,'tp1':tp1,'tp2':tp2,'tp3':tp3,'sl':sl_price,'time':now})

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
            df['macd'] = ta.macd(df['c'])['MACD_12_26_9']
            df['vol_avg'] = df['v'].rolling(20).mean()

            price = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]
            vol = df['v'].iloc[-1]
            vol_avg = df['vol_avg'].iloc[-1]
            macd = df['macd'].iloc[-1]

            if any(pd.isna(x) for x in [rsi, ema, atr, vol_avg, macd]):
                continue

            candle_body = abs(df['c'].iloc[-1]-df['o'].iloc[-1])
            if candle_body < 0.5*atr or vol <= vol_avg:
                continue

            if rsi<30 and price>ema and macd>0:
                send_signal(symbol, "BUY", price, atr, rsi)
            if rsi>70 and price<ema and macd<0:
                send_signal(symbol, "SELL", price, atr, rsi)

            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

def loop_analyze():
    while True:
        analyze_market()
        time.sleep(300)

# --- Flask ---
app = Flask(__name__)
@app.route('/')
def home():
    return "VIP Бот работает"

# --- Команды ---
@bot.message_handler(commands=['status'])
def cmd_status(m):
    bot.reply_to(m, "🤖 VIP Бот онлайн, сканирует все пары USDT!")

@bot.message_handler(commands=['report'])
def cmd_report(m):
    text = "📊 *ТЕКУЩИЙ ОТЧЕТ*\n\n"
    with lock:
        for s,h in state['history'].items():
            last = h[-1]
            text += f"🔹 `{s}` — Последний сигнал: {last['signal']} (Entry: {last['entry']})\n"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def cmd_history(m):
    msg = "📜 История сигналов:\n\n"
    with lock:
        for s,h in state['history'].items():
            msg += f"{s}:\n"
            for sig in h[-5:]:
                msg += f"  - {sig['signal']} Entry:{sig['entry']} TP1:{sig['tp1']} SL:{sig['sl']}\n"
    bot.send_message(m.chat.id, msg)

# --- Запуск ---
if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    while True:
        try:
            bot.polling(non_stop=True, interval=3, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)
