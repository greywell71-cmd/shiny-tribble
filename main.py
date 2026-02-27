import os
import time
import json
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U'
CHAT_ID = '737143225'
DATA_FILE = 'bot_state.json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()
state = {'sent_signals': {}, 'active_trades': {}, 'trend_states': {}, 'history': []}

# --- ХРАНИЛИЩЕ ---
def save_state():
    with lock:
        with open(DATA_FILE, 'w') as f:
            json.dump(state, f)

def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                state.update(json.load(f))
        except: pass

# --- ЛОГИКА ---
def get_prec_price(symbol, price):
    try:
        market = exchange.market(symbol)
        prec = market['precision']['price']
        return round(price, int(prec)) if prec >= 1 else round(price, 4)
    except: return round(price, 2)

def analyze_market():
    logger.info("Проверка рынка...")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            
            p, rsi, ema = df['c'].iloc[-1], df['rsi'].iloc[-1], df['ema'].iloc[-1]
            if pd.isna(ema): continue

            trend = "long" if p > ema else "short"
            state['trend_states'][symbol] = trend

            # Проверка выхода
            if symbol in state['active_trades']:
                t = state['active_trades'][symbol]
                done = False
                if t['side'] == "LONG":
                    if p >= t['tp']: done, res = True, "✅ TP"
                    elif p <= t['sl']: done, res = True, "❌ SL"
                else:
                    if p <= t['tp']: done, res = True, "✅ TP"
                    elif p >= t['sl']: done, res = True, "❌ SL"
                
                if done:
                    bot.send_message(CHAT_ID, f"{res} {symbol}\nЦена: {p}")
                    with lock: del state['active_trades'][symbol]
                    save_state()

            # Поиск входа
            elif (rsi < 30 and trend == "long") or (rsi > 70 and trend == "short"):
                if time.time() - state['sent_signals'].get(symbol, 0) > 7200:
                    side = "LONG" if rsi < 30 else "SHORT"
                    tp = p * (1.02 if side == "LONG" else 0.98)
                    sl = p * (0.985 if side == "LONG" else 1.015)
                    
                    with lock:
                        state['active_trades'][symbol] = {'side': side, 'tp': get_prec_price(symbol, tp), 'sl': get_prec_price(symbol, sl)}
                        state['sent_signals'][symbol] = time.time()
                    save_state()
                    
                    bot.send_message(CHAT_ID, f"🚨 **{side} {symbol}**\nВход: {p}\nTP: {state['active_trades'][symbol]['tp']}")
        except Exception as e:
            logger.error(f"Ошибка {symbol}: {e}")

# --- ЗАПУСК ---
app = Flask(__name__)
@app.route('/')
def home(): return "Бот запущен"

def run_logic():
    load_state()
    exchange.load_markets()
    while True:
        analyze_market()
        time.sleep(300)

if __name__ == "__main__":
    # Фоновые процессы
    Thread(target=run_logic, daemon=True).start()
    
    # Flask для Render (не дает серверу уснуть)
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False)).start()
    
    # Запуск ТГ бота с защитой от конфликтов
    while True:
        try:
            logger.info("Подключение к Telegram...")
            bot.polling(non_stop=True, interval=3, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка Polling: {e}")
            time.sleep(5)
                  
