import os
import time
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAGUxGAMz_8DD3fOvKtuL5kgK9K3JusIoJo'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

# Словари для хранения состояния
sent_signals = {}  
trend_states = {}  
active_trades = {} # Храним цели для отслеживания выхода

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот активен и анализирует рынок!"

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    bot.reply_to(message, "🤖 Бот на связи! Анализ рынка продолжается.")

@bot.message_handler(commands=['report'])
def send_report(message):
    report_text = "📋 **ТЕКУЩИЙ ОТЧЕТ ПО РЫНКУ**\n\n"
    for symbol in symbols:
        trend = trend_states.get(symbol)
        if trend == "long":
            trend_display = "📈 LONG (Выше EMA 200)"
        elif trend == "short":
            trend_display = "📉 SHORT (Ниже EMA 200)"
        else:
            trend_display = "🔘 Ожидание первого анализа"

        last_sig_time = sent_signals.get(symbol)
        time_str = time.strftime('%H:%M', time.localtime(last_sig_time)) if last_sig_time else "Сигналов не было"
            
        report_text += f"🔹 **{symbol}**\n• Тренд: {trend_display}\n• Последний сигнал: {time_str}\n\n"
    
    bot.send_message(message.chat.id, report_text, parse_mode="Markdown")

# --- ЛОГИКА АНАЛИЗА И ТОРГОВЛИ ---

def calculate_trade_params(current_price, side="buy"):
    prec = 2 if current_price > 1 else 4
    if side == "buy":
        tp = current_price * 1.02  # +2%
        sl = current_price * 0.99  # -1%
    else:
        tp = current_price * 0.98  # -2% для шорта
        sl = current_price * 1.01  # +1% для шорта
    return round(tp, prec), round(sl, prec)

def check_exits(symbol, current_price):
    """Проверка достижения TP или SL"""
    if symbol in active_trades:
        trade = active_trades[symbol]
        side = trade['side']
        tp = trade['tp']
        sl = trade['sl']

        is_exit = False
        result_text = ""

        if side == "LONG":
            if current_price >= tp:
                is_exit, result_text = True, f"✅ **{symbol} ТЕЙК-ПРОФИТ (+2%)**"
            elif current_price <= sl:
                is_exit, result_text = True, f"❌ **{symbol} СТОП-ЛОСС (-1%)**"
        else: # SHORT
            if current_price <= tp:
                is_exit, result_text = True, f"✅ **{symbol} ТЕЙК-ПРОФИТ (+2%)**"
            elif current_price >= sl:
                is_exit, result_text = True, f"❌ **{symbol} СТОП-ЛОСС (-1%)**"

        if is_exit:
            bot.send_message(CHAT_ID, f"{result_text}\n💰 Цена выхода: {current_price}", parse_mode="Markdown")
            del active_trades[symbol]

def analyze_market():
    print(f"[{time.strftime('%H:%M:%S')}] Запуск цикла анализа...")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            
            price = df['close'].iloc[-1]
            last_rsi = df['rsi'].iloc[-1]
            ema_val = df['ema200'].iloc[-1]

            # Определение тренда
            current_trend = "long" if price > ema_val else "short"
            trend_states[symbol] = current_trend

            # Проверка выходов из текущих сделок
            check_exits(symbol, price)

            # Поиск сигналов на вход
            if (last_rsi < 30 and current_trend == "long") or (last_rsi > 70 and current_trend == "short"):
                now = time.time()
                # Анти-спам 2 часа
                if symbol not in sent_signals or (now - sent_signals[symbol]) > 7200:
                    sent_signals[symbol] = now
                    direction = "LONG" if last_rsi < 30 else "SHORT"
                    tp, sl = calculate_trade_params(price, side=direction.lower())
                    
                    # Запоминаем сделку для отслеживания выхода
                    active_trades[symbol] = {'side': direction, 'tp': tp, 'sl': sl}
                    
                    text = (f"🚨 **{direction} SIGNAL: {symbol}**\n"
                            f"💰 Вход: {price}\n"
                            f"🎯 TP: {tp} | SL: {sl}\n"
                            f"📈 RSI: {round(last_rsi, 2)}")
                    bot.send_message(CHAT_ID, text, parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка анализа {symbol}: {e}")

# --- ЗАПУСК ПОТОКОВ ---

def run_analysis_loop():
    while True:
        analyze_market()
        time.sleep(300)  # Уменьшили до 5 минут для более частого контроля цены

def start_polling():
    print("Запуск Telegram Polling...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    # Фоновые задачи
    Thread(target=run_analysis_loop, daemon=True).start()
    Thread(target=start_polling, daemon=True).start()
    
    # Flask для Render (порт 8080 по умолчанию)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
