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

# 1. Web Server for Render
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is LIVE"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Configuration (REPLACE THESE)
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

def get_markup(symbol):
    clean_symbol = symbol.replace('/', '_')
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_binance = types.InlineKeyboardButton("Binance", url=f"https://www.binance.com/en/trade/{clean_symbol}")
    btn_tv = types.InlineKeyboardButton("TradingView", url=f"https://www.tradingview.com/symbols/{clean_symbol.replace('_', '')}/")
    markup.add(btn_binance, btn_tv)
    return markup

def analyze_market(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        last_rsi = df['rsi'].iloc[-1]
        current_price = df['close'].iloc[-1]
        
        avg_vol = df['volume'].iloc[-21:-1].mean()
        current_vol = df['volume'].iloc[-1]
        vol_spike = "💎 High Volume!" if current_vol > (avg_vol * 2) else "⚙️ Normal Vol"

        report = ""
        if last_rsi < 30:
            report = f"✅ BUY: {symbol}\nPrice: {current_price}\nRSI: {round(last_rsi, 2)}\nVol: {vol_spike}\n"
        elif last_rsi > 70:
            report = f"🚨 SELL: {symbol}\nPrice: {current_price}\nRSI: {round(last_rsi, 2)}\nVol: {vol_spike}\n"

        if report:
            current_time = time.time()
            if symbol in sent_signals and (current_time - sent_signals[symbol]) < 3600:
                return None
            sent_signals[symbol] = current_time
            return report + get_fear_greed()
    except: return None

# --- Commands ---

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, f"✅ Online\n{get_fear_greed()}\nMonitoring: {len(symbols)} pairs")

@bot.message_handler(commands=['fng'])
def send_fng(message):
    bot.reply_to(message, get_fear_greed())

@bot.message_handler(commands=['report'])
def send_report(message):
    msg = "📊 **Market Report (1h):**\n\n"
    for s in symbols:
        try:
            ticker = exchange.fetch_ticker(s)
            bars = exchange.fetch_ohlcv(s, timeframe='1h', limit=20)
            df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
            rsi = ta.rsi(df['c'], length=14).iloc[-1]
            msg += f"🔹 {s}: ${ticker['last']} (RSI: {round(rsi, 1)})\n"
        except: continue
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_symbol(message):
    try:
        new_sym = message.text.split()[1].upper()
        if new_sym not in symbols:
            symbols.append(new_sym)
            bot.reply_to(message, f"✅ {new_sym} added!")
        else:
            bot.reply_to(message, "Already exists")
    except:
        bot.reply_to(message, "Use: /add BTC/USDT")

def main_logic():
    print("💎 Starting analysis...")
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    while True:
        for symbol in symbols:
            signal = analyze_market(symbol)
            if signal:
                bot.send_message(chat_id, signal, reply_markup=get_markup(symbol))
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_web_server).start()
    main_logic()
    
