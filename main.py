import os
import time
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
# Рекомендую вынести их в Environment Variables на Render для безопасности
TOKEN = '8758242353:AAGUxGAMz_8DD3fOvKtuL5kgK9K3JusIoJo'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

sent_signals = {}  
trend_states = {}  

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот активен. Сервер Flask работает!"

# --- КОМАНДЫ TELEGRAM ---

@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    bot.reply_to(message, "🤖 Бот на связи! Анализ рынка продолжается.")

# --- ЛОГИКА ТОРГОВЛИ ---

def calculate_trade_params(current_price, side="buy", balance=100, risk_percent=0.01):
    risk_amount = balance * risk_percent
    prec = 2 if current_price > 1 else 4
    tp = current_price * 1.02 if side == "buy" else current_price * 0.98
    sl = current_price * 0.99 if side == "buy" else current_price * 1.01
    
    price_change_to_sl = abs(current_price - sl) / current_price
    position_size = risk_amount / price_change_to_sl
    return round(tp, prec), round(sl, prec), round(position_size, 2)

def analyze_market():
    print(f"[{time.strftime('%H:%M:%S')}] Начинаю цикл анализа...")
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

            # Проверка тренда
            current_trend = "long" if price > ema_val else "short"
            if symbol in trend_states and trend_states[symbol] != current_trend:
                msg = f"🔄 **СМЕНА ТРЕНДА: {symbol}**\n{'📈' if current_trend == 'long' else '📉'} Теперь: {current_trend.upper()}"
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
            trend_states[symbol] = current_trend

            # Сигналы
            if (last_rsi < 30 and current_trend == "long") or (last_rsi > 70 and current_trend == "short"):
                direction = "LONG" if last_rsi < 30 else "SHORT"
                now = time.time()
                if symbol not in sent_signals or (now - sent_signals[symbol]) > 7200:
                    sent_signals[symbol] = now
                    tp, sl, pos = calculate_trade_params(price, side=direction.lower())
                    vol_stat = "✅ High Vol" if last_vol > (avg_vol * 1.5) else "⚠️ Low Vol"
                    
                    text = f"🚨 **{direction}: {symbol}**\n💰 Вход: {price}\n🎯 TP: {tp} | SL: {sl}\n📊 {vol_stat} | RSI: {round(last_rsi, 2)}"
                    bot.send_message(CHAT_ID, text, parse_mode="Markdown")
                    
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

# --- ФУНКЦИИ ЗАПУСКА ---

def run_analysis_loop():
    while True:
        analyze_market()
        time.sleep(600)

def start_polling():
    print("Запуск прослушивания команд Telegram...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Ошибка поллинга: {e}")
        time.sleep(5)

if __name__ == "__main__":
    # Запускаем фоновые потоки
    Thread(target=run_analysis_loop, daemon=True).start()
    Thread(target=start_polling, daemon=True).start()
    
    # Запускаем Flask (блокирующий вызов, который держит процесс)
    port = int(os.environ.get("PORT", 8080))
    print(f"Запуск веб-сервера на порту {port}...")
    app.run(host='0.0.0.0', port=port)
    
