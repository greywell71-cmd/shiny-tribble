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
from datetime import datetime

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAGUxGAMz_8DD3fOvKtuL5kgK9K3JusIoJo'
CHAT_ID = '737143225'
DATA_FILE = 'bot_state.json'

# Настройка логирования в консоль
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()
state = {
    'sent_signals': {}, 
    'active_trades': {}, 
    'trend_states': {},
    'history': [] # Для ежедневных отчетов
}

# --- СИСТЕМА ХРАНЕНИЯ ---

def save_state():
    with lock:
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения: {e}")

def load_state():
    global state
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                loaded = json.load(f)
                state.update(loaded)
                logger.info("Состояние успешно загружено")
        except Exception as e:
            logger.error(f"Ошибка загрузки: {e}")

# --- ЛОГИКА ТОРГОВЛИ ---

def get_precision_price(symbol, price):
    try:
        if not exchange.markets: exchange.load_markets()
        market = exchange.market(symbol)
        prec = market['precision']['price']
        return round(price, int(prec)) if isinstance(prec, (int, float)) and prec >= 1 else round(price, 4)
    except:
        return round(price, 2 if price > 1 else 4)

def check_exits(symbol, current_price):
    with lock:
        trade = state['active_trades'].get(symbol)
    if not trade: return

    side, tp, sl = trade['side'], trade['tp'], trade['sl']
    exit_triggered = False
    result_type = ""

    if side == "LONG":
        if current_price >= tp: exit_triggered, result_type = True, "PROFIT"
        elif current_price <= sl: exit_triggered, result_type = True, "LOSS"
    else:
        if current_price <= tp: exit_triggered, result_type = True, "PROFIT"
        elif current_price >= sl: exit_triggered, result_type = True, "LOSS"

    if exit_triggered:
        res_emoji = "✅" if result_type == "PROFIT" else "❌"
        text = f"{res_emoji} **ЗАКРЫТИЕ {symbol}**\nРезультат: {result_type}\nЦена выхода: {current_price}"
        bot.send_message(CHAT_ID, text, parse_mode="Markdown")
        
        with lock:
            state['history'].append({'symbol': symbol, 'result': result_type, 'time': time.time()})
            del state['active_trades'][symbol]
        save_state()

def analyze_market():
    logger.info("Запуск цикла анализа...")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            
            price = df['close'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema200'].iloc[-1]

            if pd.isna(ema): continue

            current_trend = "long" if price > ema else "short"
            state['trend_states'][symbol] = current_trend

            check_exits(symbol, price)

            if symbol not in state['active_trades']:
                # Условие входа
                if (rsi < 30 and current_trend == "long") or (rsi > 70 and current_trend == "short"):
                    now = time.time()
                    if now - state['sent_signals'].get(symbol, 0) > 7200:
                        direction = "LONG" if rsi < 30 else "SHORT"
                        
                        # Расчет TP/SL (2% / 1.5%)
                        tp = price * (1.02 if direction == "LONG" else 0.98)
                        sl = price * (0.985 if direction == "LONG" else 1.015)
                        
                        tp, sl = get_precision_price(symbol, tp), get_precision_price(symbol, sl)

                        with lock:
                            state['active_trades'][symbol] = {'side': direction, 'tp': tp, 'sl': sl}
                            state['sent_signals'][symbol] = now
                        save_state()

                        msg = (f"🚨 **СИГНАЛ: {symbol}**\nНаправление: {direction}\n"
                               f"💰 Вход: {price}\n🎯 TP: {tp} | 🛑 SL: {sl}")
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

# --- КОМАНДЫ ---

@bot.message_handler(commands=['report'])
def send_report(message):
    res = "📊 **ОТЧЕТ**\n"
    for s in symbols:
        t = state['trend_states'].get(s, "н/д")
        res += f"• {s}: {t.upper()} {'🔥' if s in state['active_trades'] else ''}\n"
    bot.reply_to(message, res, parse_mode="Markdown")

# --- ВЕБ-ИНТЕРФЕЙС И ЗАПУСК ---

app = Flask(__name__)
@app.route('/')
def home(): return "OK"

def main_loop():
    load_state()
    while True:
        analyze_market()
        time.sleep(300)

if __name__ == "__main__":
    Thread(target=main_loop, daemon=True).start()
    Thread(target=lambda: bot.infinity_polling(), daemon=True).start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
