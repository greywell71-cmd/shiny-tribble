import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd

# 1. Сервер для Render
app = Flask(__name__)
@app.route('/')
def home(): return "Бот в эфире!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Настройки (ВСТАВЬ СВОИ ДАННЫЕ)
TOKEN = '8758242353:AAFt4tlgTrZBikosPCY19y6MAtPlFeprxO0'
chat_id = '737143225'
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

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
    bot.reply_to(message, f"✅ Я работаю!\n{fng}\nМониторю: {', '.join(symbols)}")

def get_signal(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        last_rsi = df['rsi'].iloc[-1]
        
        if last_rsi > 70:
            return f"🚨 ПРОДАЖА {symbol}\nRSI: {round(last_rsi, 2)}\n{get_fear_greed()}"
        if last_rsi < 30:
            return f"✅ ПОКУПКА {symbol}\nRSI: {round(last_rsi, 2)}\n{get_fear_greed()}"
    except Exception as e:
        print(f"Ошибка {symbol}: {e}")
    return None

def main_logic():
    print("💎 Бот-Терминатор v4.0 запущен!")
    # Запускаем прослушку сообщений в отдельном потоке
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    
    while True:
        for symbol in symbols:
            signal = get_signal(symbol)
            if signal:
                bot.send_message(chat_id, signal)
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_web_server).start()
    main_logic()
    
