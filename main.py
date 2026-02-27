import os
import time
import requests
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAGcSygEr0CAfuAM6KZzu9LMVdgNHMelMI4'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

sent_signals = {}  # Время последней отправки сигнала по монете
trend_states = {}  # Текущий тренд (long/short) для каждой монеты

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот активен и анализирует рынок!"

# --- ЛОГИКА ТОРГОВЛИ ---

def calculate_trade_params(current_price, side="buy", balance=100, risk_percent=0.01):
    risk_amount = balance * risk_percent
    prec = 2 if current_price > 1 else 4
    
    if side == "buy":
        tp = current_price * 1.02  # Тейк +2%
        sl = current_price * 0.99  # Стоп -1%
    else:
        tp = current_price * 0.98
        sl = current_price * 1.01
    
    price_change_to_sl = abs(current_price - sl) / current_price
    position_size = risk_amount / price_change_to_sl
    return round(tp, prec), round(sl, prec), round(position_size, 2)

def analyze_market():
    for symbol in symbols:
        try:
            # Получаем данные (1 час)
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Индикаторы
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['ema200'] = ta.ema(df['close'], length=200)
            avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
            
            price = df['close'].iloc[-1]
            last_rsi = df['rsi'].iloc[-1]
            last_vol = df['volume'].iloc[-1]
            ema_val = df['ema200'].iloc[-1]

            # 1. Проверка смены тренда
            current_trend = "long" if price > ema_val else "short"
            if symbol in trend_states and trend_states[symbol] != current_trend:
                msg = (f"🔄 **СМЕНА ТРЕНДА: {symbol}**\n"
                       f"{'📈' if current_trend == 'long' else '📉'} Теперь: {current_trend.upper()}\n"
                       f"📊 RSI: {round(last_rsi, 2)}")
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
            trend_states[symbol] = current_trend

            # 2. Поиск сигналов
            signal = None
            if last_rsi < 30 and current_trend == "long":
                signal, emoji, direction = "buy", "✅", "LONG"
            elif last_rsi > 70 and current_trend == "short":
                signal, emoji, direction = "sell", "🚨", "SHORT"

            if signal:
                now = time.time()
                # Анти-спам: 2 часа между сигналами по одной монете
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200:
                    continue
                
                sent_signals[symbol] = now
                tp, sl, pos_size = calculate_trade_params(price, side=signal)
                vol_status = "✅ High Volume" if last_vol > (avg_vol * 1.5) else "⚠️ Low Volume"

                text = (
                    f"{emoji} **{direction} SIGNAL: {symbol}**\n"
                    f"💰 Вход: **{price}**\n"
                    f"🎯 TP: **{tp}** | 🛡️ SL: **{sl}**\n\n"
                    f"📊 Подтверждение: {vol_status}\n"
                    f"💵 Позиция: **${pos_size}**\n"
                    f"📈 RSI: {round(last_rsi, 2)}"
                )
                bot.send_message(CHAT_ID, text, parse_mode="Markdown")
                
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

# --- ЗАПУСК ПОТОКОВ ---

def run_analysis_loop():
    print("Запуск цикла анализа рынка...")
    while True:
        analyze_market()
        time.sleep(600) # Проверка каждые 10 минут

def start_polling():
    print("Бот начинает слушать команды...")
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    # Фоновые задачи
    Thread(target=run_analysis_loop, daemon=True).start()
    Thread(target=start_polling, daemon=True).start()
    
    # Основной сервер для Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
    
