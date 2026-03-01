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

# Настройки
TOKEN = "8758242353:AAG5DoNU8Im5TXaXFeeWgHSj1_nSB4OwblI"
CHAT_ID = os.getenv('737143225')


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})
lock = Lock()
state = {
    "sent_signals": {},
    "history": {},
    "debug_log": {}  # для команды /debug — последние проверки
}

# Топ-пары (48 штук — оптимально для Render + Binance лимитов)
SYMBOLS_TO_SCAN = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'LINK/USDT',
    'TON/USDT', 'DOT/USDT', 'SUI/USDT', 'NEAR/USDT', 'TRX/USDT',
    'PEPE/USDT', 'LTC/USDT', 'UNI/USDT', 'APT/USDT', 'ICP/USDT',
    'HBAR/USDT', 'KAS/USDT', 'ETC/USDT', 'FET/USDT', 'VET/USDT',
    'OP/USDT', 'FIL/USDT', 'INJ/USDT', 'ARB/USDT', 'MNT/USDT',
    'IMX/USDT', 'WIF/USDT', 'JUP/USDT', 'ONDO/USDT', 'AR/USDT',
    'FLOKI/USDT', 'GRT/USDT', 'RUNE/USDT', 'SEI/USDT', 'TIA/USDT',
    'ALGO/USDT', 'AAVE/USDT', 'QNT/USDT', 'MKR/USDT', 'FLOW/USDT',
    'BCH/USDT', 'THETA/USDT', 'FTM/USDT', 'STX/USDT', 'ATOM/USDT',
]

# Генерация картинки (упрощённая, без шрифтов)
def generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, rsi, atr, tf, rr):
    WIDTH, HEIGHT = 800, 800
    BG_COLOR = (20, 20, 20)
    TEXT_COLOR = (240, 240, 240)
    HIGHLIGHT = (0, 200, 0) if signal == "BUY" else (220, 50, 50)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.text((40, 40), f"{signal} {symbol}", fill=HIGHLIGHT, font=font)
    y = 120
    for k, v in {"Entry": entry, "TP1": tp1, "TP2": tp2, "TP3": tp3, "SL": sl,
                 "RSI": rsi, "ATR": atr, "TF": tf, "R/R": rr}.items():
        draw.text((40, y), f"{k}: {v}", fill=TEXT_COLOR, font=font)
        y += 50

    output = BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output

# Отправка сигнала
def send_signal(symbol, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        if now - state["sent_signals"].get(key, 0) < 3600:  # 1 час антиспам
            return
        state["sent_signals"][key] = now
        if symbol not in state["history"]:
            state["history"][symbol] = []

    entry = round(price, 4)
    tp1 = round(price + atr if signal == "BUY" else price - atr, 4)
    tp2 = round(price + atr * 1.5 if signal == "BUY" else price - atr * 1.5, 4)
    tp3 = round(price + atr * 2.5 if signal == "BUY" else price - atr * 2.5, 4)
    sl = round(price - atr * 1.2 if signal == "BUY" else price + atr * 1.2, 4)

    symbol_bin = symbol.replace("/", "")
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Spot BUY", url=f"https://www.binance.com/en/trade/{symbol_bin}"),
        types.InlineKeyboardButton("Spot SELL", url=f"https://www.binance.com/en/trade/{symbol_bin}"),
        types.InlineKeyboardButton("Futures LONG", url=f"https://www.binance.com/en/futures/{symbol_bin}"),
        types.InlineKeyboardButton("Futures SHORT", url=f"https://www.binance.com/en/futures/{symbol_bin}"),
    )

    try:
        img = generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, round(rsi,1), round(atr,4), "1h", "1:2+")
        bot.send_photo(CHAT_ID, photo=img, caption=f"🔔 {signal} {symbol}\nEntry: {entry}", reply_markup=markup)
        state["history"][symbol].append({"signal": signal, "entry": entry, "time": now})
        logger.info(f"СИГНАЛ ОТПРАВЛЕН → {symbol} {signal}")
    except Exception as e:
        logger.error(f"Ошибка отправки {symbol}: {e}")

# Безопасный fetch
def safe_fetch_ohlcv(symbol):
    try:
        return exchange.fetch_ohlcv(symbol, "1h", limit=200)
    except ccxt.RateLimitExceeded:
        time.sleep(20)
        return safe_fetch_ohlcv(symbol)
    except Exception as e:
        logger.error(f"{symbol} fetch error: {e}")
        return None

# Анализ
def analyze_market():
    for symbol in SYMBOLS_TO_SCAN:
        try:
            bars = safe_fetch_ohlcv(symbol)
            if not bars:
                continue

            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema'] = ta.ema(df['close'], length=200)
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

            price = df['close'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema) or pd.isna(atr):
                continue

            # Логируем каждую проверку (для отладки)
            log_msg = f"{symbol} | RSI={rsi:.1f} | Price={price:.4f} | EMA={ema:.4f} | ATR={atr:.4f}"
            logger.info(log_msg)

            with lock:
                if symbol not in state["debug_log"]:
                    state["debug_log"][symbol] = []
                state["debug_log"][symbol].append(log_msg)
                if len(state["debug_log"][symbol]) > 10:
                    state["debug_log"][symbol].pop(0)

            # Очень простые условия для теста
            if rsi < 50 and price > ema:
                send_signal(symbol, "BUY", price, atr, rsi)
            if rsi > 50 and price < ema:
                send_signal(symbol, "SELL", price, atr, rsi)

            time.sleep(0.4)  # пауза между парами

        except Exception as e:
            logger.error(f"Анализ {symbol} ошибка: {e}")

def loop_analyze():
    while True:
        logger.info("Начало цикла анализа...")
        analyze_market()
        logger.info("Цикл анализа завершён")
        time.sleep(300)

# Flask + команды
app = Flask(__name__)

@app.route("/")
def home():
    return "Бот работает"

@bot.message_handler(commands=["status"])
def cmd_status(m):
    bot.reply_to(m, "🤖 Бот онлайн, сканирует топ-пары")

@bot.message_handler(commands=["report", "history"])
def cmd_report(m):
    with lock:
        if not state["history"]:
            bot.reply_to(m, "Пока нет сигналов в истории.")
        else:
            text = "Последние сигналы:\n"
            for sym, hist in state["history"].items():
                last = hist[-1]
                text += f"{sym} → {last['signal']} @ {last['entry']}\n"
            bot.reply_to(m, text)

@bot.message_handler(commands=["debug"])
def cmd_debug(m):
    text = "Последние проверки (до 10):\n\n"
    with lock:
        for sym, logs in list(state["debug_log"].items())[:8]:
            text += f"🟡 {sym}\n" + "\n".join(logs[-3:]) + "\n\n"
    bot.reply_to(m, text or "Нет данных отладки пока")

# Запуск
if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    Thread(target=lambda: bot.polling(non_stop=True, interval=3, timeout=20), daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
