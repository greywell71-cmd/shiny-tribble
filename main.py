import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd

# 1. Веб-сервер для поддержания жизни на Render
app = Flask(__name__)
@app.route('/')
def home(): return "Бот-Терминатор v5.0 в эфире!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Настройки (ВСТАВЬ СВОИ ДАННЫЕ)
TOKEN = '8758242353:AAFt4tlgTrZBikosPCY19y6MAtPlFeprxO0'
chat_id = '737143225'
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

# Список монет и хранилище цен для отслеживания скачков
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
last_prices = {} 

# Функция получения Индекса Страха и Жадности
def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/').json()
        val = r['data'][0]['value']
        cls = r['data'][0]['value_classification']
        return f"📊 Индекс страха: {val} ({cls})"
    except: return "📊 Индекс недоступен"

# Обработка команды /status
@bot.message_handler(commands=['status'])
def send_status(message):
    fng = get_fear_greed()
    status_text = f"✅ Бот активен!\n{fng}\nМониторю: {len(symbols)} пар."
    bot.reply_to(message, status_text)

# Логика анализа рынка
def analyze_market(symbol):
    try:
        # Получаем данные (таймфрейм 1 час для надежности)
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        current_price = df['close'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        report = ""

        # --- ПРОВЕРКА НА PUMP / DUMP (изменение > 2% за цикл) ---
        if symbol in last_prices:
            old_price = last_prices[symbol]
            change = ((current_price - old_price) / old_price) * 100
            if abs(change) >= 2.0:
                emoji = "🚀 PUMP" if change > 0 else "📉 DUMP"
                report += f"{emoji} {symbol}!\nИзменение: {round(change, 2)}%\nЦена: {current_price}\n"
        
        last_prices[symbol] = current_price

        # --- СИГНАЛЫ RSI ---
        if last_rsi > 70:
            report += f"🚨 СИГНАЛ ПРОДАЖИ: {symbol}\nRSI: {round(last_rsi, 2)}\n"
        elif last_rsi < 30:
            report += f"✅ СИГНАЛ ПОКУПКИ: {symbol}\nRSI: {round(last_rsi, 2)}\n"

        if report:
            return report + get_fear_greed()
            
    except Exception as e:
        print(f"Ошибка анализа {symbol}: {e}")
    return None

def main_logic():
    print("💎 Запуск основного цикла анализа...")
    # Запускаем прослушку команд в фоне
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    
    while True:
        for symbol in symbols:
            signal = analyze_market(symbol)
            if signal:
                bot.send_message(chat_id, signal)
        time.sleep(60) # Проверка каждую минуту

if __name__ == "__main__":
    # Запуск сервера и бота
    Thread(target=run_web_server).start()
    main_logic()
