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

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8758242353:AAEVzrxHf5L5uJE-6dhzguJqbMFbqx8wbD0" # Твой токен
CHAT_ID = "737143225" 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
lock = Lock()
state = {"sent_signals": {}, "last_prices": {}}
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

# --- ОБРАБОТКА КОМАНД ---
@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    try:
        status_text = "✅ <b>Бот активен и сканирует рынок!</b>\n\n"
        status_text += "Последние цены:\n"
        for symbol, price in state["last_prices"].items():
            status_text += f"• {symbol}: <code>{price}</code>\n"
        
        if not state["last_prices"]:
            status_text += "<i>Данные от биржи еще подгружаются...</i>"
            
        bot.reply_to(message, status_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")

# --- ФУНКЦИИ АНАЛИЗА ---
def send_signal(symbol, df, signal, price, atr, rsi):
    with lock:
        key = f"{symbol}_{signal}"
        if time.time() - state["sent_signals"].get(key, 0) < 7200: return
        state["sent_signals"][key] = time.time()

    entry = round(price, 4)
    mul = 1 if signal == "BUY" else -1
    tp = [round(price + (atr * m) * mul, 4) for m in [1, 1.5, 2.5]]
    sl = round(price - (atr * 1.5) * mul, 4)

    text = (
        f"{'🚀' if signal == 'BUY' else '📉'} <b>{signal} {symbol}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"Вход: <code>{entry}</code>\n"
        f"TP1: <code>{tp[0]}</code> | TP2: <code>{tp[1]}</code>\n"
        f"SL: <code>{sl}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"RSI: {round(rsi, 2)}"
    )

    try:
        plot_df = df.tail(40).copy()
        plot_df.index = pd.to_datetime(plot_df.index)
        buf = BytesIO()
        mpf.plot(plot_df, type='candle', style='nightclouds', savefig=buf)
        buf.seek(0)
        bot.send_photo(CHAT_ID, photo=buf, caption=text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(CHAT_ID, text, parse_mode="HTML")

def scanner():
    logger.info(">>> СИСТЕМА ЗАПУЩЕНА.")
    while True:
        for symbol in SYMBOLS:
            try:
                time.sleep(10) 
                ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=150)
                
                # ИСПРАВЛЕНИЕ ОШИБКИ NoneType
                if not ohlcv or len(ohlcv) < 100:
                    continue
                    
                df = pd.DataFrame(ohlcv, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
                price = df['Close'].iloc[-1]
                state["last_prices"][symbol] = price # Сохраняем для команды /status

                rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                ema = ta.ema(df['Close'], length=200).iloc[-1]
                atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]

                if rsi < 30 and price > ema:
                    send_signal(symbol, df, "BUY", price, atr, rsi)
                elif rsi > 70 and price < ema:
                    send_signal(symbol, df, "SELL", price, atr, rsi)
                
            except Exception as e:
                logger.error(f"Ошибка {symbol}: {e}")
        time.sleep(600)

# --- ЗАПУСК ---
app = Flask(__name__)
@app.route("/")
def health(): return "OK", 200

if __name__ == "__main__":
    # 1. Сканер в фоне
    Thread(target=scanner, daemon=True).start()
    
    # 2. Flask в фоне
    port = int(os.environ.get("PORT", 10000))
    Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False), daemon=True).start()
    
    # 3. Бот в основном потоке (теперь он будет отвечать!)
    logger.info(">>> БОТ ОЖИДАЕТ КОМАНД...")
    bot.infinity_polling(timeout=20)
                
