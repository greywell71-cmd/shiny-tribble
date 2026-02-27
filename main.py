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

# --- ЛОГИКА АНАЛИЗА ---

def calculate_trade_params(current_price, side="buy"):
    prec = 2 if current_price > 1 else 4
    if side == "buy":
        tp = current_price * 1.02  # +2%
        sl = current_price * 0.99  # -1%
    else:
        tp = current_price * 0.98  # -2% для шорта
        sl = current_price * 1.01  # +1% для шорта
    return round(tp, prec), round(sl, prec)

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
            ema_val =
            
