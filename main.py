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

# --- 1. НАСТРОЙКИ ---
TOKEN = '8758242353:AAGcSygEr0CAfuAM6KZzu9LMVdgNHMelMI4'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']
sent_signals = {}  # Для защиты от спама

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# --- 2. УНИВЕРСАЛЬНЫЙ РАСЧЕТ РИСКОВ ---
def calculate_trade_params(current_price, side="buy", balance=100, risk_percent=0.01):
    risk_amount = balance * risk_percent
    
    if side == "buy":
        tp = current_price * 1.02  # +2% 📈
        sl = current_price * 0.99  # -1% 🛡️
    else:  # side == "sell"
        tp = current_price * 0.98  # -2% 📉
        sl = current_price * 1.01  # +1% 🛡️
    
    # Считаем дистанцию до стопа через модуль abs()
    price_change_to_sl = abs(current_price - sl) / current_price
    position_size = risk_amount / price_change_to_sl
    
    return round(tp, 4), round(sl, 4), round(position_size, 2)

# --- 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_fear_greed_index():
    try:
        r = requests.get('https://api.alternative.me/fng/').json()
        return f"📊 Индекс страха и жадности: {r['data'][0]['value']} ({r['data'][0]['value_classification']})"
    except:
        return "📊 Индекс страха: N/A"

def create_chart(symbol, df):
    plot_df = df.tail(45).copy()
    plot_df['timestamp'] = pd.to_datetime(plot_df['timestamp'], unit='ms')
    plot_df.set_index('timestamp', inplace=True)
    
    file_name = f"{symbol.replace('/', '')}.png"
    ap = mpf.make_addplot(plot_df['rsi'], panel=1, color='orange', ylabel='RSI')
    
    mpf.plot(plot_df, type='candle', style='charles', addplot=ap, 
             savefig=file_name, title=f"{symbol} 1H Signal", 
             volume=False, panel_ratios=(2, 1), figsize=(10, 7))
    return file_name

# --- 4. ОСНОВНОЙ АНАЛИЗ ---
def analyze_market():
    for symbol in symbols:
        try:
            # Получаем данные 1-часовых свечей
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['rsi'] = ta.rsi(df['close'], length=14)
            
            last_rsi = df['rsi'].iloc[-1]
            price = df['close'].iloc[-1]
            
            signal = None
            # Логика сигналов
            if last_rsi < 30:
                signal = "buy"
                emoji, direction = "✅", "LONG"
            elif last_rsi > 70:
                signal = "sell"
                emoji, direction = "🚨", "SHORT"
            
            if signal:
                now = time.time()
                # Анти-спам: 1 сигнал раз в 2 часа
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200:
                    continue
                
                sent_signals[symbol] = now
                tp, sl, volume = calculate_trade_params(price, side=signal)
                
                caption = (
                    f"{emoji} **{direction} SIGNAL: {symbol}**\n"
                    f"💰 Цена входа: **{price}**\n"
                    f"🎯 Take Profit: **{tp}**\n"
                    f"🛡️ Stop Loss: **{sl}**\n\n"
                    f"💵 Сумма входа: **${volume}**\n"
                    f"📊 RSI: {round(last_rsi, 2)}\n"
                    f"{get_fear_greed_index()}"
                )
                
                chart_file = create_chart(symbol, df)
                with open(chart_file, 'rb') as photo:
                    bot.send_photo(CHAT_ID, photo, caption=caption, parse_mode="Markdown")
                os.remove(chart_file)
                
        except Exception as e:
            print(f"Ошибка анализа {symbol}: {e}")

# --- 5. ЗАПУСК ПОТОКОВ ---
def run_bot():
    while True:
        analyze_market()
        time.sleep(600)  # Проверка каждые 10 минут

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
        
