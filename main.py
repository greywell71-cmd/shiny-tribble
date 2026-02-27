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
trend_states = {} # Для отслеживания смены тренда

app = Flask(__name__)

@app.route('/')
def home(): return "Bot is running!"

# --- УНИВЕРСАЛЬНЫЙ РАСЧЕТ И ОКРУГЛЕНИЕ ---
def calculate_trade_params(current_price, side="buy", balance=100, risk_percent=0.01):
    risk_amount = balance * risk_percent
    prec = 2 if current_price > 1 else 4 # Динамическое округление
    
    if side == "buy":
        tp = current_price * 1.02
        sl = current_price * 0.99
    else:
        tp = current_price * 0.98
        sl = current_price * 1.01
    
    price_change_to_sl = abs(current_price - sl) / current_price
    position_size = risk_amount / price_change_to_sl
    
    return round(tp, prec), round(sl, prec), round(position_size, 2)

# --- УВЕДОМЛЕНИЕ О СМЕНЕ ТРЕНДА ---
def send_trend_notification(symbol, trend, price, rsi_val):
    emoji = "📈" if trend == "long" else "📉"
    status = "LONG (Выше EMA 200)" if trend == "long" else "SHORT (Ниже EMA 200)"
    msg = (
        f"🔄 **СМЕНА ТРЕНДА: {symbol}**\n\n"
        f"{emoji} **Новый тренд:** {status}\n"
        f"💰 **Цена:** {price}\n"
        f"📊 **Текущий RSI:** {round(rsi_val, 2)}"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# --- ОСНОВНАЯ ФУНКЦИЯ ---
def analyze_market():
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
            
            price = df['close'].iloc[-1]
            last_rsi = df['rsi'].iloc[-1]
            last_vol = df['volume'].iloc[-1]
            ema_val = df['ema200'].iloc[-1]
            
            # 1. ПРОВЕРКА СМЕНЫ ТРЕНДА
            current_trend = "long" if price > ema_val else "short"
            if symbol in trend_states and trend_states[symbol] != current_trend:
                send_trend_notification(symbol, current_trend, price, last_rsi)
            trend_states[symbol] = current_trend

            # 2. ПОИСК СИГНАЛОВ
            signal = None
            if last_rsi < 30 and current_trend == "long":
                signal, emoji, direction = "buy", "✅", "LONG"
            elif last_rsi > 70 and current_trend == "short":
                signal, emoji, direction = "sell", "🚨", "SHORT"
            
            if signal:
                now = time.time()
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200: continue
                
                sent_signals[symbol] = now
                tp, sl, volume = calculate_trade_params(price, side=signal)
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
                
                # Здесь должен быть ваш код для создания и отправки графика (create_chart)
                bot.send_message(CHAT_ID, caption, parse_mode="Markdown")
                
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

def run_bot():
    while True:
        analyze_market()
        time.sleep(600)

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
    
