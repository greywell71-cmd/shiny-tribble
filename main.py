import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
from telebot import types
import ccxt
import pandas_ta as ta
import pandas as pd
import mplfinance as mpf

# 1. Web Server for Render
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Chart v9.6 LIVE"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Configuration
TOKEN = '8758242353:AAHTOpRSy5kBt5ExNmFhaOmL3opAcT7GaOk'
chat_id = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
sent_signals = {}

def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/').json()
        return f"📊 F&G Index: {r['data'][0]['value']} ({r['data'][0]['value_classification']})"
    except: return "📊 Index N/A"

def create_chart(symbol, df):
    plot_df = df.tail(40).copy()
    plot_df['timestamp'] = pd.to_datetime(plot_df['timestamp'], unit='ms')
    plot_df.set_index('timestamp', inplace=True)
    file_name = f"{symbol.replace('/', '')}.png"
    ap = mpf.make_addplot(plot_df['rsi'], panel=1, color='orange', ylabel='RSI')
    mpf.plot(plot_df, type='candle', style='charles', addplot=ap, savefig=file_name, 
             title=f"\n{symbol} Signal", volume=False, panel_ratios=(2,1), figsize=(10, 7))
    return file_name

def analyze_market(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        last_rsi = df['rsi'].iloc[-1]
        price = df['close'].iloc[-1]
        
        signal = None
        if last_rsi < 30: signal = "✅ BUY SIGNAL"
        elif last_rsi > 70: signal = "🚨 SELL SIGNAL"
        
        if signal:
            now = time.time()
            if symbol in sent_signals and (now - sent_signals[symbol]) < 3600:
                return
            sent_signals[symbol] = now
            chart_file = create_chart(symbol, df)
            caption = f"{signal}: {symbol}\nPrice: {price}\nRSI: {round(last_rsi, 2)}\n{get_fear_greed()}"
            with open(chart_file, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=caption)
            os.remove(chart_file)
    except Exception as e:
        print(f"Error {symbol}: {e}")

# --- Bot Commands ---
@bot.message_handler(commands=['status'])
def status(m): bot.reply_to(m, f"✅ Online\n{get_fear_greed()}")

@bot.message_handler(commands=['report'])
def report(m):
    res = "📊 **Prices:**\n"
    for s in symbols:
        try:
            p = exchange.fetch_ticker(s)['last']
            res += f"🔹 {s}: ${p}\n"
        except: continue
    bot.send_message(m.chat.id, res, parse_mode="Markdown")

def main_logic():
    print("💎 Starting...")
    Thread(target=lambda: bot.polling(none_stop=True)).start()
    while True:
        for s in symbols: analyze_market(s)
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_web_server).start()
    main_logic()
            
