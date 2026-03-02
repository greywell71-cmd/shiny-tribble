import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock
from io import BytesIO
import mplfinance as mpf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- КОНФИГУРАЦИЯ (ВСТАВЬ СВОИ ДАННЫЕ ТУТ) ---
TOKEN = "8758242353:AAFi-6vGtHgQoOUsWcN3XaLBAtjh6SHaxac" # Вставь сюда свой токен от BotFather
CHAT_ID = "737143225" 

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация бота и биржи
bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
lock = Lock()
state = {"sent_signals": {}}
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

def send_signal(symbol, df, signal, price, atr, rsi):
    with lock:
        key = f"{symbol}_{signal}"
        # Защита от спама: один и тот же сигнал не чаще чем раз в 2 часа
        if time.time() - state["sent_signals"].get(key, 0) < 7200: 
            return
        state["sent_signals"][key] = time.time()

    entry = round(price, 4)
    mul = 1 if signal == "BUY" else -1
    tp = [round(price + (atr * m) * mul, 4) for m in [1, 1.5, 2.5]]
    sl = round(price - (atr * 1.5) * mul, 4)

    m_emoji = "🚀" if signal == "BUY" else "📉"
    text = (
        f"{m_emoji} <b>{signal} {symbol}</b> {m_emoji}\n"
        f"━━━━━━━━━━━━━━\n"
        f"Вход: <code>{entry}</code>\n"
        f"🎯 TP1: <code>{tp[0]}</code>\n"
        f"🎯 TP2: <code>{tp[1]}</code>\n"
        f"🛑 SL: <code>{sl}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 RSI: {round(rsi, 2)}"
    )

    try:
        # Подготовка данных для графика
        plot_df = df.tail(40).copy()
        plot_df.index = pd.to_datetime(plot_df.index)
        
        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit')
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=colors, facecolor='#050519')
        
        buf = BytesIO()
        fig, _ = mpf.plot(plot_df, type='candle', style=s, figsize=(10, 6), savefig=buf, returnfig=True)
        buf.seek(0)
        
        bot.send_photo(CHAT_ID, photo=buf, caption=text, parse_mode="HTML")
        plt.close(fig) 
        logger.info(f"Сигнал отправлен: {symbol} {signal}")
    except Exception as e:
        logger.error(f"Ошибка при отправке графика {symbol}: {e}")
        bot.send_message(CHAT_ID, text, parse_mode="HTML")

def scanner():
    logger.info(">>> СИСТЕМА ЗАПУЩЕНА. ОЖИДАНИЕ СИГНАЛОВ...")
    while True:
        for symbol in SYMBOLS:
            try:
                # Берем данные 1-часовых свечей
                ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=150)
                df = pd.DataFrame(ohlcv, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
                
                # Индикаторы
                rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                ema = ta.ema(df['Close'], length=200).iloc[-1]
                atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
                price = df['Close'].iloc[-1]

                # Логика стратегии
                if rsi < 30 and price > ema:
                    send_signal(symbol, df, "BUY", price, atr, rsi)
                elif rsi > 70 and price < ema:
                    send_signal(symbol, df, "SELL", price, atr, rsi)
                
                time.sleep(2) # Пауза между монетами
            except Exception as e:
                logger.error(f"Ошибка сканера на {symbol}: {e}")
        
        time.sleep(600) # Проверка раз в 10 минут

# Flask-сервер для "обмана" Render (чтобы он видел активный порт)
app = Flask(__name__)
@app.route("/")
def health(): return "Status: Active", 200

if __name__ == "__main__":
    # 1. Запуск сканера
    Thread(target=scanner, daemon=True).start()
    
    # 2. Запуск бота (обработка команд, если они будут)
    def run_bot():
        while True:
            try:
                bot.infinity_polling(timeout=20)
            except Exception:
                time.sleep(10)
    Thread(target=run_bot, daemon=True).start()
    
    # 3. Запуск веб-сервера на порту Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    
