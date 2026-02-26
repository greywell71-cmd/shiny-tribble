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

# 1. Веб-сервер для предотвращения "засыпания" на Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Chart v10.0 LIVE - Monitoring Markets"

def run_web_server():
    # Render автоматически назначает порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Конфигурация
TOKEN = '8758242353:AAGh4-1UM8MCAOjTlsdh62PXs6TRInLqe60'  # ЗАМЕНИТЕ ЭТО
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
sent_signals = {}

# 3. Вспомогательные функции
def get_fear_greed_index():
    try:
        r = requests.get('https://api.alternative.me/fng/', timeout=5).json()
        return f"📊 Fear & Greed Index: {r['data'][0]['value']} ({r['data'][0]['value_classification']})"
    except:
        return "📊 Index N/A"

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
                # Анти-спам: 1 сигнал в 2 часа для одной монеты
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200:
                    continue
                
                sent_signals[symbol] = now
                chart_file = create_chart(symbol, df)
                caption = f"{signal}: {symbol}\nPrice: {price}\nRSI: {round(last_rsi, 2)}\n{get_fear_greed_index()}"
                
                with open(chart_file, 'rb') as photo:
                    bot.send_photo(CHAT_ID, photo, caption=caption)
                os.remove(chart_file)
        except Exception as e:
            print(f"Ошибка анализа {symbol}: {e}")

# 4. Обработчики команд
@bot.message_handler(commands=['status'])
def status(m):
    bot.reply_to(m, f"✅ Bot is Online\nMonitoring: {len(symbols)} pairs\n{get_fear_greed_index()}")

@bot.message_handler(commands=['report'])
def report(m):
    res = "📊 **Market Report (1h):**\n\n"
    for s in symbols:
        try:
            p = exchange.fetch_ticker(s)['last']
            bars = exchange.fetch_ohlcv(s, timeframe='1h', limit=50)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            rsi = round(ta.rsi(df['close'], length=14).iloc[-1], 1)
            res += f"🔹 {s}: ${p} (RSI: {rsi})\n"
        except: continue
    bot.send_message(m.chat.id, res, parse_mode="Markdown")

# 5. Главные циклы
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
    # Уведомление в ТГ о запуске (опционально)
    try: bot.send_message(CHAT_ID, "🚀 Бот запущен и мониторит рынок!")
    except: pass

    while True:
        try:
            analyze_market()
            # Проверка каждые 10 минут, чтобы не нагружать систему
            time.sleep(600)
        except Exception as e:
            error_stack = traceback.format_exc()
            print(f"Критическая ошибка:\n{error_stack}")
            time.sleep(60)

if __name__ == "__main__":
    # Запуск сервера
    Thread(target=run_web_server, daemon=True).start()
    # Запуск бота
    Thread(target=bot_polling, daemon=True).start()
    # Запуск анализатора в основном потоке
    market_loop()
            
