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
def home(): return "Bot Chart v9.5 LIVE"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Configuration (REPLACE WITH YOUR DATA)
TOKEN = '8758242353:AAHTOpRSy5kBt5ExNmFhaOmL3opAcT7GaOk'
chat_id = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
sent_signals = {}

def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/').json()
        val = r['data'][0]['value']
        cls = r['data'][0]['value_classification']
        return f"📊 F&G Index: {val} ({cls})"
    except: return "📊 Index N/A"

def create_chart(symbol, df):
    # Take last 40 candles for clarity
    plot_df = df.tail(40).copy()
    plot_df['timestamp'] = pd.to_datetime(plot_df['timestamp'], unit='ms')
    plot_df.set_index('timestamp', inplace=True)
    
    file_name = f"{symbol.replace('/', '')}.png"
    
    # Setup RSI plot on the second panel
    ap = mpf.make_addplot(plot_df['rsi'], panel=1, color='orange', ylabel='RSI')
    
    # Save the candlestick chart
    mpf.plot(plot_df, type='candle', style='charles', addplot=ap, 
             savefig=file_name, title=f"\n{symbol} Signal", 
             volume=False, panel_ratios=(2,1), figsize=(10, 7))
    return file_name

def analyze_market(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        last_rsi = df['rsi'].iloc[-1]
        price = df['close'].iloc[-1]
        
        signal = None
        if last
        
