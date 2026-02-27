import os
import time
import json
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import requests
from flask import Flask
from threading import Thread, Lock

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U'
CHAT_ID = '737143225'
DATA_FILE = 'bot_state.json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- СБРОС КОНФЛИКТА (Самое важное) ---
def force_reset():
    logger.info("Удаление старых сессий Telegram...")
    try:
        # Прямой запрос на очистку очереди и вебхуков
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        time.sleep(5) # Ждем, чтобы сервера Telegram обновились
        logger.info("Сессии очищены.")
    except Exception as e:
        logger.error(f"Ошибка сброса: {e}")

force_reset()

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()
state = {'sent_signals': {}, 'active_trades': {}, 'trend_states': {}}

# --- ЛОГИКА АНАЛИЗА ---
def analyze_market():
    logger.info(">>> Цикл анализа рынка запущен")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            
            p, rsi, ema = df['c'].iloc[-1], df['rsi'].iloc[-1], df['ema'].iloc[-1]
            if pd.isna(ema): continue

            trend = "long" if p > ema else "short"
            state['trend_states'][symbol] = trend

            # Условие для сигнала
            if (rsi < 30 and trend == "long") or (rsi > 70 and trend == "short"):
                now = time.time()
                if now - state['sent_signals'].get(symbol, 0) > 7200:
                    side = "LONG" if rsi < 30 else "SHORT"
                    bot.send_message(CHAT_ID, f"🚨 **{side} {symbol}**\nЦена: {p}\nRSI: {round(rsi, 2)}")
                    state['sent_signals'][symbol] = now
        except Exception as e:
            logger.error(f"Ошибка {symbol}: {e}")

# --- WEB И POLLING ---
app = Flask(__name__)
@app.route('/')
def home(): return "OK"

def run_logic():
    while True:
        analyze_market()
        time.sleep(300)

@bot.message_handler(commands=['status'])
def status(m): bot.reply_to(m, "🤖 Бот онлайн!")

if __name__ == "__main__":
    Thread(target=run_logic, daemon=True).start()
    
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False)).start()
    
    while True:
        try:
            logger.info("Старт Polling...")
            bot.polling(non_stop=True, interval=5, timeout=40)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(10)
            
