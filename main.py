import os
import time
import requests
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import mplfinance as mpf
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAGcSygEr0CAfuAM6KZzu9LMVdgNHMelMI4'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']
sent_signals = {}

app = Flask(__name__)

@app.route('/')
def home(): return "Bot is running!"

# --- УНИВЕРСАЛЬНЫЙ РАСЧЕТ И ОКРУГЛЕНИЕ ---
def calculate_trade_params(current_price, side="buy", balance=100, risk_percent=0.01):
    risk_amount = balance * risk_percent
    # Определяем точность округления в зависимости от цены
    prec = 2 if current_price > 1 else 4
    
    if side == "buy":
        tp = current_price * 1.02  # +2% 📈
        sl = current_price * 0.99  # -1% 🛡️
    else:
        tp = current_price * 0.98  # -2% 📉
        sl = current_price * 1.01  # +1% 🛡️
    
    price_change_to_sl = abs(current_price - sl) / current_price
    position_size = risk_amount / price_change_to_sl
    
    return round(tp, prec), round(sl, prec), round(position_size, 2)

def analyze_market():
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # ИНДИКАТОРЫ
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
            
            last_rsi = df['rsi'].iloc[-1]
            price = df['close'].iloc[-1]
            last_vol = df['volume'].iloc[-1]
            ema_val = df['ema200'].iloc[-1]
            
            signal = None
            # ЛОГИКА СИГНАЛОВ + ФИЛЬТР ТРЕНДА
            if last_rsi < 30 and price > ema_val: # Покупаем только если тренд растущий
                signal = "buy"
                emoji, direction = "✅", "LONG"
            elif last_rsi > 70 and price < ema_val: # Шортим только если тренд падающий
                signal = "sell"
                emoji, direction = "🚨", "SHORT"
            
            if signal:
                now = time.time()
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200: continue
                
                sent_signals[symbol] = now
                tp, sl, volume = calculate_trade_params(price, side=signal)
                
                # Проверка объема
                vol_status = "✅ High Volume" if last_vol > (avg_vol * 1.5) else "⚠️ Low Volume"
                
                caption = (
                    f"{emoji} **{direction} SIGNAL: {symbol}**\n"
                    f"💰 Вход: **{price}**\n"
                    f"🎯 Take Profit: **{tp}**\n"
                    f"🛡️ Stop Loss: **{sl}**\n\n"
                    f"📊 Подтверждение: {vol_status}\n"
                    f"💵 Позиция: **${volume}**\n"
                    f"📈 RSI: {round(last_rsi, 2)}"
                )
                
                # (код отправки фото остается прежним)
                
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

# Запуск...
