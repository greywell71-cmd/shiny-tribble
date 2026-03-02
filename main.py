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

# --- Инициализация ---
TOKEN = os.environ.get("8758242353:AAFi-6vGtHgQoOUsWcN3XaLBAtjh6SHaxac")
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if not TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден в Environment Variables!")
    exit(1)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30000})
lock = Lock()
state = {"sent_signals": {}}
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

def generate_chart(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    try:
        plot_df = df.tail(40).copy()
        # Новые версии pandas требуют явного преобразования индекса
        plot_df.index = pd.to_datetime(plot_df.index)
        
        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=colors, facecolor='#050519', figcolor='#050519')
        
        buf = BytesIO()
        fig, _ = mpf.plot(
            plot_df, type='candle', style=s,
            title=f"\n{signal} {symbol}",
            hlines=dict(hlines=[entry, tp1, tp2, tp3, sl], 
                        colors=['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000'], 
                        linestyle='-.', linewidths=1),
            figsize=(10, 6), savefig=buf, returnfig=True
        )
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        logger.error(f"Chart error {symbol}: {e}")
        return None

def send_signal(symbol, df, signal, price, atr, rsi):
    with lock:
        key = f"{symbol}_{signal}"
        if time.time() - state["sent_signals"].get(key, 0) < 7200: return
        state["sent_signals"][key] = time.time()

    entry = round(price, 4)
    mul = 1 if signal == "BUY" else -1
    tp = [round(price + (atr * m) * mul, 4) for m in [1, 1.5, 2.5]]
    sl = round(price - (atr * 1.2) * mul, 4)

    emoji = "🚀" if signal == "BUY" else "📉"
    text = (
        f"{emoji} <b>{signal} {symbol}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"Вход: <code>{entry}</code>\n"
        f"TP1: <code>{tp[0]}</code>\n"
        f"TP2: <code>{tp[1]}</code>\n"
        f"TP3: <code>{tp[2]}</code>\n"
        f"SL: <code>{sl}</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"RSI: <code>{round(rsi, 2)}</code>"
    )

    chart = generate_chart(symbol, df, signal, entry, tp[0], tp[1], tp[2], sl)
    try:
        if chart:
            bot.send_photo(CHAT_ID, photo=chart, caption=text, parse_mode="HTML")
        else:
            bot.send_message(CHAT_ID, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"TG Error: {e}")

def scanner():
    while True:
        logger.info("Сканирование рынка...")
        for symbol in SYMBOLS:
            try:
                time.sleep(5) # Плавные запросы
                ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=100)
                df = pd.DataFrame(ohlcv, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
                
                rsi = ta.rsi(df['Close'], length=14).iloc[-1]
                ema = ta.ema(df['Close'], length=200).iloc[-1]
                atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
                price = df['Close'].iloc[-1]

                if rsi < 30 and price > ema:
                    send_signal(symbol, df, "BUY", price, atr, rsi)
                elif rsi > 70 and price < ema:
                    send_signal(symbol, df, "SELL", price, atr, rsi)
            except Exception as e:
                logger.error(f"Scanner error {symbol}: {e}")
        time.sleep(600)

app = Flask(__name__)
@app.route("/")
def health(): return "OK"

if __name__ == "__main__":
    Thread(target=scanner, daemon=True).start()
    
    # Запуск бота в отдельном потоке
    def run_bot():
        while True:
            try:
                bot.infinity_polling(timeout=20, long_polling_timeout=10)
            except Exception:
                time.sleep(10)
    
    Thread(target=run_bot, daemon=True).start()
    
    # Flask для Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
