import os
import time
from flask import Flask          # Импорт с большой буквы 'F'
from threading import Thread
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd

# 1. Создаем сервер для Render
app = Flask(__name__) 

@app.route('/')
def home():
    return "Бот работает!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# 2.
TOKEN = '8758242353:AAFt4tlgTrZBikosPCY19y6MAtPlFeprxO0'
chat_id = '737143225'
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 
    'ADA/USDT', 'DOT/USDT', 'MATIC/USDT', 'LINK/USDT', 
    'LTC/USDT', 'AVAX/USDT', 'DOGE/USDT', 'TRX/USDT'
]

# 3. Логика сигналов
def get_signal(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='30m', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        last_rsi = df['rsi'].iloc[-1]
        if last_rsi > 70: return f"🚨 ПРОДАЖА {symbol} (RSI: {round(last_rsi, 2)})"
        if last_rsi < 30: return f"✅ ПОКУПКА {symbol} (RSI: {round(last_rsi, 2)})"
    except Exception as e:
        print(f"Ошибка {symbol}: {e}")
    return None

# 4. Главный цикл
def main_logic():
    print("💎 Бот запущен!")
    while True:
        for symbol in symbols:
            signal = get_signal(symbol)
            if signal:
                bot.send_message(chat_id, signal)
        time.sleep(60)

if __name__ == "__main__":
    keep_alive()  # Запуск сервера для Render
    main_logic()  # Запуск бота
