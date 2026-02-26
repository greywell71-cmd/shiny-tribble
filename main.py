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

app = Flask(__name__)
@app.route('/')
def home(): return "Bot Terminator v6.0 is LIVE!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TOKEN = '8758242353:AAHTOpRSy5kBt5ExNmFhaOmL3opAcT7GaOk'
chat_id = '737143225'
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
last_prices = {}
sent_signals = {} # Память, чтобы не спамить

def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/').json()
        val = r['data'][0]['value']
        cls = r['data'][0]['value_classification']
        return f"📊 Индекс страха: {val} ({cls})"
    except: return "📊 Индекс недоступен"

def analyze_market(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        current_price = df['close'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        
        avg_vol = df['volume'].iloc[-21:-1].mean()
        current_vol = df['volume'].iloc[-1]
        vol_spike = "💎 High Volume!" if current_vol > (avg_vol * 2) else "⚙️ Normal Volume"

        report = ""
        
        if last_rsi < 30:
            report = f"✅ BUY SIGNAL: {symbol}\nPrice: {current_price}\nRSI: {round(last_rsi, 2)}\nVol: {vol_spike}\n"
        elif last_rsi > 70:
            report = f"🚨 SELL SIGNAL: {symbol}\nPrice: {current_price}\nRSI: {round(last_rsi, 2)}\nVol: {vol_spike}\n"

        if report:
            current_time = time.time()
            if symbol in sent_signals and (current_time - sent_signals[symbol]) < 3600:
                return None
            sent_signals[symbol] = current_time
            return report + get_fear_greed()
            
    except Exception as e:
        print(f"Error: {e}")
    return None

def get_markup(symbol):
    clean_symbol = symbol.replace('/', '_') # Для ссылок Binance
    markup = types.InlineKeyboardMarkup()
    btn_binance = types.InlineKeyboardButton("Открыть на Binance", url=f"https://www.binance.com/ru/trade/{clean_symbol}")
    btn_tv = types.InlineKeyboardButton("Анализ TradingView", url=f"https://www.tradingview.com/symbols/{clean_symbol.replace('_', '')}/")
    markup.add(btn_binance, btn_tv)
    return markup

@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, f"✅ Бот в сети!\n{get_fear_greed()}\nМониторинг 7 пар активен.")

def main_logic():
    print("💎 Бот запущен...")
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
    
