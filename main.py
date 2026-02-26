import os
import time
import requests
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import mplfinance as mpf
import traceback
from flask import Flask
from threading import Thread

# 1. Настройка Flask (WSGI-интерфейс)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Chart v11.0 LIVE - WSGI Mode Active"

# 2. Конфигурация
TOKEN = '8758242353:AAECWJLY99i-QcZfU3iXmMfcWC8-PQDCHeY'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
sent_signals = {}

# 3. Функции анализа и графиков
def get_fear_greed_index():
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=5).json()
        return f"📊 Fear & Greed Index: {r['data'][0]['value']} ({r['data'][0]['value_classification']})"
    except:
        return "📊 Fear & Greed Index: N/A"

def create_chart(symbol, df):
    plot_df = df.tail(45).copy()
    plot_df['timestamp'] = pd.to_datetime(plot_df['timestamp'], unit='ms')
    plot_df.set_index('timestamp', inplace=True)
    
    file_name = f"{symbol.replace('/', '')}.png"
    ap = mpf.make_addplot(plot_df['rsi'], panel=1, color='orange', ylabel='RSI')
    
    mpf.plot(plot_df, type='candle', style='charles', addplot=ap, 
             savefig=file_name, title=f"\n{symbol} 1H Signal", 
             volume=False, panel_ratios=(2, 1), figsize=(10, 7))
    return file_name

def analyze_market():
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['rsi'] = ta.rsi(df['close'], length=14)
            
            last_rsi = df['rsi'].iloc[-1]
            price = df['close'].iloc[-1]
            
            signal = None
            if last_rsi < 30: signal = "✅ BUY SIGNAL (Oversold)"
            elif last_rsi > 70: signal = "🚨 SELL SIGNAL (Overbought)"
            
            if signal:
                now = time.time()
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200:
                    continue
                
                sent_signals[symbol] = now
                chart_file = create_chart(symbol, df)
                caption = f"{signal}: {symbol}\nPrice: {price}\nRSI: {round(last_rsi, 2)}\n{get_fear_greed_index()}"
                
                with open(chart_file, 'rb') as photo:
                    bot.send_photo(CHAT_ID, photo, caption=caption)
                if os.path.exists(chart_file):
                    os.remove(chart_file)
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")

# 4. Обработчики команд (Формат как на вашем скриншоте)
@bot.message_handler(commands=['status'])
def status(m):
    bot.reply_to(m, f"✅ Bot is Online\nMonitoring: {', '.join(symbols)}\n{get_fear_greed_index()}")

@bot.message_handler(commands=['report'])
def report(m):
    res = "📊 **Market Report (1h):**\n\n"
    for s in symbols:
        try:
            p = exchange.fetch_ticker(s)['last']
            bars = exchange.fetch_ohlcv(s, timeframe='1h', limit=50)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            rsi_val = round(ta.rsi(df['close'], length=14).iloc[-1], 1)
            res += f"🔹 {s}: ${p} (RSI: {rsi_val})\n"
        except: continue
    bot.send_message(m.chat.id, res, parse_mode="Markdown")

# 5. Потоки для работы под управлением Gunicorn
def bot_polling():
    while True:
        try:
            print("🤖 Starting Telegram Polling...")
            bot.remove_webhook()
            bot.polling(none_stop=True, interval=0, timeout=40)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(15)

def market_loop():
    print("📈 Market Monitor Started")
    while True:
        try:
            analyze_market()
            time.sleep(600) # Интервал 10 минут
        except Exception as e:
            print(f"Loop error: {traceback.format_exc()}")
            time.sleep(60)

# ЭТА ЧАСТЬ ЗАПУСКАЕТ ПОТОКИ ПРИ ИМПОРТЕ МОДУЛЯ GUNICORN-ОМ
def start_threads():
    t1 = Thread(target=bot_polling, daemon=True)
    t1.start()
    t2 = Thread(target=market_loop, daemon=True)
    t2.start()

start_threads()

if __name__ == "__main__":
    # Локальный запуск (если не через gunicorn)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
    
