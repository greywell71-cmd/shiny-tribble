import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock
from io import BytesIO
import mplfinance as mpf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- НАСТРОЙКИ ---
TOKEN = os.environ.get("8758242353:AAFi-6vGtHgQoOUsWcN3XaLBAtjh6SHaxac")
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if not TOKEN or ":" not in TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram не задан!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# Настройка Binance с защитой от спама
exchange = ccxt.binance({
    "enableRateLimit": True, 
    "timeout": 30000,
    "options": {"defaultType": "spot"}
})

lock = Lock()
state = {"sent_signals": {}}
SYMBOLS_TO_SCAN = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT']

def generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    try:
        plot_df = df.tail(40).copy()
        plot_df.index = pd.to_datetime(plot_df.index)
        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=colors, facecolor='#050519', figcolor='#050519')
        levels = [entry, tp1, tp2, tp3, sl]
        level_colors = ['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000']
        
        buf = BytesIO()
        fig, _ = mpf.plot(
            plot_df, type='candle', style=s,
            title=f"\nPREMIUM {signal} {symbol}",
            hlines=dict(hlines=levels, colors=level_colors, linestyle='-.', linewidths=1.5),
            figsize=(12, 8), savefig=buf, returnfig=True
        )
        buf.seek(0)
        plt.close(fig) 
        return buf
    except Exception as e:
        logger.error(f"Ошибка отрисовки {symbol}: {e}")
        plt.close('all')
        return None

def send_signal(symbol, df, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        if now - state["sent_signals"].get(key, 0) < 7200: return
        state["sent_signals"][key] = now

    entry, mul = round(price, 4), (1 if signal == "BUY" else -1)
    tp1, tp2, tp3 = round(price + atr*mul, 4), round(price + (atr*1.5)*mul, 4), round(price + (atr*2.5)*mul, 4)
    sl = round(price - (atr*1.2)*mul, 4)

    m_emoji, t_emoji, dot = ("🚀", "📈", "🟢") if signal == "BUY" else ("📉", "📉", "🔴")
    
    params_text = (
        f"{m_emoji} <b>PREMIUM SIGNAL: {symbol}</b> {m_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Тип:</b> {signal} {t_emoji}\n"
        f"<b>Вход:</b> <code>{entry:.4f}</code>\n\n"
        f"🎯 <b>ЦЕЛИ:</b>\n"
        f"├ TP1: <code>{tp1:.4f}</code> ✅\n"
        f"├ TP2: <code>{tp2:.4f}</code> 🔥\n"
        f"└ TP3: <code>{tp3:.4f}</code> 🚀\n\n"
        f"🛑 <b>STOP LOSS:</b> <code>{sl:.4f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>АНАЛИЗ:</b>\n"
        f"{dot} RSI: <code>{round(rsi, 2)}</code>\n"
        f"💎 <i>Status: Active</i>"
    )

    try:
        img_buf = generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl)
        if img_buf:
            bot.send_photo(CHAT_ID, photo=img_buf, caption=params_text, parse_mode="HTML")
        else:
            bot.send_message(CHAT_ID, params_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Telegram error {symbol}: {e}")

def analyze_market():
    logger.info(">>> Цикл сканирования запущен...")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            time.sleep(12) # Защита от бана 418
            bars = exchange.fetch_ohlcv(symbol, "1h", limit=250)
            if not bars: continue

            df = pd.DataFrame(bars, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            rsi = ta.rsi(df['Close'], length=14).iloc[-1]
            ema = ta.ema(df['Close'], length=200).iloc[-1]
            atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
            price = df['Close'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema): continue

            if rsi < 35 and price > ema:
                send_signal(symbol, df.set_index(pd.to_datetime(df['Date'], unit='ms')), "BUY", price, atr, rsi)
            elif rsi > 65 and price < ema:
                send_signal(symbol, df.set_index(pd.to_datetime(df['Date'], unit='ms')), "SELL", price, atr, rsi)

        except ccxt.DDoSProtection:
            logger.error("БАН 418! Спим 15 минут...")
            time.sleep(900)
            return 
        except Exception as e:
            logger.error(f"Ошибка {symbol}: {e}")

def loop_analyze():
    while True:
        try:
            analyze_market()
            time.sleep(600) 
        except Exception as e:
            logger.error(f"Ошибка цикла: {e}")
            time.sleep(60)

# --- WEB SERVER & BOT START ---
app = Flask(__name__)
@app.route("/")
def home(): return "Бот работает"

if __name__ == "__main__":
    # Фоновые задачи
    Thread(target=loop_analyze, daemon=True).start()
    
    def start_bot():
        while True:
            try:
                logger.info("Запуск Telegram Polling...")
                bot.infinity_polling(timeout=20, long_polling_timeout=10)
            except Exception as e:
                logger.error(f"Конфликт или ошибка бота: {e}")
                time.sleep(20) # Пауза перед перезапуском при ошибке 409

    Thread(target=start_bot, daemon=True).start()
    
    # Основной поток для Render (решает ошибку порта)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
            
