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
TOKEN = '8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U'  # Вставьте сюда ваш токен аккуратно
CHAT_ID = '737143225'
DATA_FILE = 'bot_state.json'

# Настройка логирования для Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()
state = {'sent_signals': {}, 'active_trades': {}, 'trend_states': {}, 'history': []}

# --- ХРАНИЛИЩЕ ДАННЫХ ---
def save_state():
    with lock:
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения файла: {e}")

def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                state.update(json.load(f))
                logger.info("Состояние успешно загружено из файла.")
        except Exception as e:
            logger.error(f"Ошибка загрузки файла: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_prec_price(symbol, price):
    try:
        market = exchange.market(symbol)
        prec = market['precision']['price']
        return round(price, int(prec)) if prec >= 1 else round(price, 4)
    except:
        return round(price, 2 if price > 1 else 4)

def check_exits(symbol, current_price):
    with lock:
        trade = state['active_trades'].get(symbol)
    
    if not trade:
        return

    side, tp, sl = trade['side'], trade['tp'], trade['sl']
    exit_triggered = False
    result_text = ""

    if side == "LONG":
        if current_price >= tp: exit_triggered, result_text = True, "✅ TAKE PROFIT"
        elif current_price <= sl: exit_triggered, result_text = True, "❌ STOP LOSS"
    else: # SHORT
        if current_price <= tp: exit_triggered, result_text = True, "✅ TAKE PROFIT"
        elif current_price >= sl: exit_triggered, result_text = True, "❌ STOP LOSS"

    if exit_triggered:
        bot.send_message(CHAT_ID, f"{result_text} #{symbol}\nЦена выхода: {current_price}")
        with lock:
            del state['active_trades'][symbol]
        save_state()

# --- ОСНОВНАЯ ЛОГИКА ---
def analyze_market():
    logger.info("Цикл анализа запущен...")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            
            last_row = df.iloc[-1]
            p, rsi, ema = last_row['c'], last_row['rsi'], last_row['ema']
            
            if pd.isna(ema): continue

            # Определение тренда
            trend = "long" if p > ema else "short"
            state['trend_states'][symbol] = trend

            # Проверка выходов
            check_exits(symbol, p)

            # Поиск входа
            if symbol not in state['active_trades']:
                is_long = (rsi < 30 and trend == "long")
                is_short = (rsi > 70 and trend == "short")

                if is_long or is_short:
                    now = time.time()
                    if now - state['sent_signals'].get(symbol, 0) > 7200:
                        side = "LONG" if is_long else "SHORT"
                        tp = p * (1.02 if side == "LONG" else 0.98)
                        sl = p * (0.985 if side == "LONG" else 1.015)
                        
                        with lock:
                            state['active_trades'][symbol] = {
                                'side': side, 
                                'tp': get_prec_price(symbol, tp), 
                                'sl': get_prec_price(symbol, sl)
                            }
                            state['sent_signals'][symbol] = now
                        save_state()
                        
                        msg = (f"🚨 **СИГНАЛ {side}: {symbol}**\n"
                               f"💵 Вход: {p}\n🎯 TP: {state['active_trades'][symbol]['tp']}\n"
                               f"🛑 SL: {state['active_trades'][symbol]['sl']}\n📊 RSI: {round(rsi, 1)}")
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

# --- ВЕБ-СЕРВЕР ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Бот работает. Статус: Live"

# --- ПОТОКИ ---
def run_logic():
    load_state()
    try:
        exchange.load_markets()
    except: pass
    while True:
        analyze_market()
        time.sleep(300)

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "🤖 Бот на связи! Анализ продолжается.")

@bot.message_handler(commands=['report'])
def send_report(message):
    report = "📋 **ТЕКУЩИЙ ОТЧЕТ**\n\n"
    for s in symbols:
        t = state['trend_states'].get(s, "н/д")
        status = "🔥 В сделке" if s in state['active_trades'] else "💤 Поиск"
        report += f"🔹 **{s}**: {t.upper()} | {status}\n"
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

if __name__ == "__main__":
    # 1. Запуск торговой логики
    Thread(target=run_logic, daemon=True).start()
    
    # 2. Запуск веб-сервера (Flask)
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False)).start()
    
    # 3. Бесконечный цикл Polling с защитой от ошибок
    while True:
        try:
            logger.info("Запуск Telegram Polling...")
            bot.polling(non_stop=True, interval=2, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка Polling: {e}. Повтор через 5 секунд...")
            time.sleep(5)
    
