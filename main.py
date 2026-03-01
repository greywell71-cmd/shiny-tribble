import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# Настройки
TOKEN = "8758242353:AAG5DoNU8Im5TXaXFeeWgHSj1_nSB4OwblI"
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
    "debug_log": {}
}

# Топ-пары
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

# Картинка — только график (бары + круговая диаграмма)
def generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, rsi, atr, tf, rr):
    WIDTH, HEIGHT = 1024, 1024
    
    BG_START = (5, 5, 25)
    BG_END   = (30, 15, 70)
    GOLD     = (255, 215, 0)
    ACCENT   = (255, 180, 0) if signal == "BUY" else (255, 80, 120)
    TEXT     = (255, 255, 255)

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img, "RGBA")

    for y in range(HEIGHT):
        r = int(BG_START[0] + (BG_END[0] - BG_START[0]) * y / HEIGHT)
        g = int(BG_START[1] + (BG_END[1] - BG_START[1]) * y / HEIGHT)
        b = int(BG_START[2] + (BG_END[2] - BG_START[2]) * y / HEIGHT)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    font_large  = ImageFont.load_default()
    font_medium = ImageFont.load_default()

    title = f"PREMIUM {signal} {symbol}"
    draw.text((80, 40), title, fill=GOLD, font=font_large)

    bar_y = 200
    bar_heights = [500, 650, 800, 950, 1100]
    bar_x = 80
    draw.text((80, bar_y - 80), "Revenue Growth", fill=GOLD, font=font_medium)
    for i, h in enumerate(bar_heights):
        color = ACCENT if i % 2 == 0 else (200, 150, 50)
        draw.rectangle([bar_x + i*140, bar_y - h, bar_x + i*140 + 100, bar_y], fill=color, outline=GOLD, width=8)

    circle_x, circle_y = WIDTH - 450, 250
    draw.ellipse([circle_x, circle_y, circle_x+350, circle_y+350], outline=GOLD, width=10)
    draw.pieslice([circle_x, circle_y, circle_x+350, circle_y+350], 0, 170, fill=ACCENT)
    draw.pieslice([circle_x, circle_y, circle_x+350, circle_y+350], 170, 300, fill=(180, 120, 60))
    draw.pieslice([circle_x, circle_y, circle_x+350, circle_y+350], 300, 360, fill=(80,80,140))

    output = BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output

# Отправка сигнала — картинка + цветной текст с эмодзи и ссылками
def send_signal(symbol, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        if now - state["sent_signals"].get(key, 0) < 3600:
            logger.info(f"Антиспам: {symbol} {signal} недавно отправлен")
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

    # Цветной выделенный текст с эмодзи
    bg_color = "#006400" if signal == "BUY" else "#8B0000"
    emoji = "🚀" if signal == "BUY" else "📉"
    params_text = (
        f"<b>🔔 PREMIUM {signal} {symbol} {emoji}</b>\n\n"
        f"<div style='background-color:{bg_color}; color:white; padding:16px; border-radius:12px; font-size:16px; line-height:1.6;'>"
        f"<b>Entry:</b> {entry:.4f}\n"
        f"<b>TP1 ↑:</b> {tp1:.4f}\n"
        f"<b>TP2 ↑:</b> {tp2:.4f}\n"
        f"<b>TP3 ↑:</b> {tp3:.4f}\n"
        f"<b>SL ↓:</b> {sl:.4f}\n"
        f"<b>💹 RSI:</b> {round(rsi, 2)}\n"
        f"<b>💹 ATR:</b> {round(atr, 4)}\n"
        f"<b>⏱️ TF:</b> 1h\n"
        f"<b>⚖️ R/R:</b> 1:2+"
        f"</div>\n\n"
        f"🔗 Перейти к торговле:\n"
        f"• Spot BUY → https://www.binance.com/en/trade/{symbol_bin}?type=spot\n"
        f"• Spot SELL → https://www.binance.com/en/trade/{symbol_bin}?type=spot\n"
        f"• Futures LONG → https://www.binance.com/en/futures/{symbol_bin}\n"
        f"• Futures SHORT → https://www.binance.com/en/futures/{symbol_bin}"
    )

    try:
        img = generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, round(rsi,1), round(atr,4), "1h", "1:2+")
        bot.send_photo(CHAT_ID, photo=img)
        bot.send_message(CHAT_ID, params_text, parse_mode="HTML")
        state["history"][symbol].append({"signal": signal, "entry": entry, "time": now})
        logger.info(f"Сигнал отправлен: {symbol} {signal}")
    except Exception as e:
        logger.error(f"Ошибка отправки {symbol}: {e}")

# Безопасный fetch
def safe_fetch_ohlcv(symbol):
    try:
        return exchange.fetch_ohlcv(symbol, "1h", limit=200)
    except ccxt.RateLimitExceeded:
        logger.warning(f"Rate limit {symbol}, ждём 20 сек")
        time.sleep(20)
        return safe_fetch_ohlcv(symbol)
    except Exception as e:
        logger.error(f"{symbol} fetch error: {e}")
        return None

# Анализ рынка
def analyze_market():
    tf = "1h"
    logger.info("Начало цикла анализа...")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            bars = safe_fetch_ohlcv(symbol)
            if not bars:
                continue

            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)

            price = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema) or pd.isna(atr):
                continue

            log_msg = f"{symbol} | RSI={rsi:.1f} | Price={price:.4f} | EMA={ema:.4f} | ATR={atr:.4f}"
            logger.info(log_msg)

            with lock:
                if symbol not in state["debug_log"]:
                    state["debug_log"][symbol] = []
                state["debug_log"][symbol].append(log_msg)
                if len(state["debug_log"][symbol]) > 10:
                    state["debug_log"][symbol].pop(0)

            if rsi < 55 and price > ema:
                send_signal(symbol, "BUY", price, atr, rsi)
            if rsi > 45 and price < ema:
                send_signal(symbol, "SELL", price, atr, rsi)

            time.sleep(0.4)
        except Exception as e:
            logger.error(f"Анализ {symbol} ошибка: {e}")
    logger.info("Цикл анализа завершён")

def loop_analyze():
    while True:
        analyze_market()
        time.sleep(300)

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
            bot.reply_to(m, "Нет сигналов пока.")
        else:
            text = "Последние сигналы:\n"
            for sym, hist in state["history"].items():
                last = hist[-1]
                text += f"{sym} → {last['signal']} @ {last['entry']}\n"
            bot.reply_to(m, text)

@bot.message_handler(commands=["debug"])
def cmd_debug(m):
    text = "Последние проверки:\n\n"
    with lock:
        for sym, logs in list(state["debug_log"].items())[:8]:
            text += f"🟡 {sym}\n" + "\n".join(logs[-3:]) + "\n\n"
    bot.reply_to(m, text or "Нет данных.")

if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    Thread(target=lambda: bot.polling(non_stop=True, interval=3, timeout=30), daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
