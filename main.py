import os
import time
import json
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAGUxGAMz_8DD3fOvKtuL5kgK9K3JusIoJo'
CHAT_ID = '737143225'
DATA_FILE = 'bot_state.json'  # Файл для сохранения сделок

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

# Потокобезопасность
lock = Lock()

# Состояние бота
state = {
    'sent_signals': {},  # {symbol: timestamp}
    'active_trades': {}, # {symbol: {side, tp, sl, entry_price}}
    'trend_states': {}   # {symbol: "long"/"short"}
}

# --- ФУНКЦИИ ХРАНЕНИЯ ДАННЫХ ---

def save_state():
    with lock:
        with open(DATA_FILE, 'w') as f:
            json.dump(state, f)

def load_state():
    global state
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                state = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки состояния: {e}")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_precision_price(symbol, price):
    """Округляет цену согласно правилам биржи"""
    try:
        if not exchange.markets:
            exchange.load_markets()
        market = exchange.market(symbol)
        # В ccxt precision может быть целым числом (знаки после запятой) или десятичным шагом
        prec = market['precision']['price']
        return round(price, int(prec)) if isinstance(prec, (int, float)) and prec >= 1 else round(price, 4)
    except:
        return round(price, 2 if price > 1 else 4)

def calculate_trade_params(symbol, current_price, side="long"):
    if side == "long":
        tp = current_price * 1.02  # +2%
        sl = current_price * 0.985 # -1.5% (более безопасный стоп)
    else:
        tp = current_price * 0.98  # -2%
        sl = current_price * 1.015 # +1.5%
    
    return get_precision_price(symbol, tp), get_precision_price(symbol, sl)

# --- ОБРАБОТЧИКИ ТЕЛЕГРАМ ---

@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    bot.reply_to(message, "🤖 Бот активен. Мониторинг EMA 200 + RSI запущен.")

@bot.message_handler(commands=['report'])
def send_report(message):
    report_text = "📋 **ОТЧЕТ ПО РЫНКУ**\n\n"
    for s in symbols:
        trend = state['trend_states'].get(s, "Ожидание")
        trade = state['active_trades'].get(s)
        
        status = f"✅ В сделке ({trade['side']})" if trade else "👀 Поиск входа"
        report_text += f"🔹 **{s}**: {trend.upper()}\n   Статус: {status}\n"
    
    bot.send_message(message.chat.id, report_text, parse_mode="Markdown")

# --- ЛОГИКА АНАЛИЗА ---

def check_exits(symbol, current_price):
    """Проверка закрытия сделок по TP/SL"""
    with lock:
        trade = state['active_trades'].get(symbol)
    
    if not trade:
        return

    side = trade['side']
    tp, sl = trade['tp'], trade['sl']
    exit_triggered = False
    msg = ""

    if side == "LONG":
        if current_price >= tp: exit_triggered, msg = True, "✅ **TAKE PROFIT**"
        elif current_price <= sl: exit_triggered, msg = True, "❌ **STOP LOSS**"
    else: # SHORT
        if current_price <= tp: exit_triggered, msg = True, "✅ **TAKE PROFIT**"
        elif current_price >= sl: exit_triggered, msg = True, "❌ **STOP LOSS**"

    if exit_triggered:
        text = f"{msg} #{symbol}\n💰 Выход: {current_price}\nРезультат: {'+2%' if 'TAKE' in msg else '-1.5%'}"
        bot.send_message(CHAT_ID, text, parse_mode="Markdown")
        with lock:
            del state['active_trades'][symbol]
        save_state()

def analyze_market():
    print(f"[{time.strftime('%H:%M:%S')}] Анализ инструментов...")
    for symbol in symbols:
        try:
            # Загружаем чуть больше данных для точности EMA
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=300)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Технический анализ
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            
            last_row = df.iloc[-1]
            price = last_row['close']
            rsi = last_row['rsi']
            ema = last_row['ema200']

            if pd.isna(ema): continue

            # Обновляем тренд
            current_trend = "long" if price > ema else "short"
            state['trend_states'][symbol] = current_trend

            # 1. Сначала проверяем выход
            check_exits(symbol, price)

            # 2. Ищем вход, если еще не в сделке
            if symbol not in state['active_trades']:
                is_long_signal = (rsi < 30 and current_trend == "long")
                is_short_signal = (rsi > 70 and current_trend == "short")

                if is_long_signal or is_short_signal:
                    now = time.time()
                    last_sig = state['sent_signals'].get(symbol, 0)
                    
                    if (now - last_sig) > 7200: # 2 часа перерыв
                        direction = "LONG" if is_long_signal else "SHORT"
                        tp, sl = calculate_trade_params(symbol, price, direction.lower())
                        
                        with lock:
                            state['active_trades'][symbol] = {
                                'side': direction, 'tp': tp, 'sl': sl, 'entry': price
                            }
                            state['sent_signals'][symbol] = now
                        
                        save_state()
                        
                        text = (f"🚨 **СИГНАЛ: {symbol} ({direction})**\n"
                                f"💵 Вход: {price}\n"
                                f"🎯 TP: {tp} | 🛑 SL: {sl}\n"
                                f"📊 RSI: {round(rsi, 1)}")
                        bot.send_message(CHAT_ID, text, parse_mode="Markdown")

        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

# --- ВЕБ-СЕРВЕР И ЗАПУСК ---

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает. Мониторинг активен."

def run_loop():
    load_state()
    while True:
        analyze_market()
        time.sleep(300) # Проверка каждые 5 минут

if __name__ == "__main__":
    # Запуск логики в отдельном потоке
    Thread(target=run_loop, daemon=True).start()
    
    # Запуск Telegram Polling в отдельном потоке
    Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    
    # Flask для Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
                        
