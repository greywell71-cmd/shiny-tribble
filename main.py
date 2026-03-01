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

# --- НАСТРОЙКИ ---
TOKEN = "8758242353:AAFuMgWHFtg78jDF3MM8tyVJlVxCGzUNzJw" 
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Проверка токена перед созданием бота
if not TOKEN or ":" not in TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram не задан или имеет неверный формат!")
    exit(1)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({
    "enableRateLimit": True, 
    "timeout": 30000,
    "options": {"defaultType": "spot"}
})
lock = Lock()
state = {"sent_signals": {}, "history": {}}

SYMBOLS_TO_SCAN = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT']

def generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    try:
        plot_df = df.tail(40).copy()
        # Убеждаемся, что индекс — это время
        plot_df.index = pd.to_datetime(plot_df.index)

        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=colors, facecolor='#050519', figcolor='#050519')

        levels = [entry, tp1, tp2, tp3, sl]
        level_colors = ['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000']
        
        buf = BytesIO()
        mpf.plot(
            plot_df, type='candle', style=s,
            title=f"\nPREMIUM {signal} {symbol}",
            hlines=dict(hlines=levels, colors=level_colors, linestyle='-.', linewidths=1.5),
            figsize=(12, 8), savefig=buf
        )
        buf.seek(0)
        plt.close('all') 
        return buf
    except Exception as e:
        logger.error(f"Ошибка отрисовки {symbol}: {e}")
        plt.close('all')
        return None

def send_signal(symbol, df, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        if now - state["sent_signals"].get(key, 0) < 3600: return
        state["sent_signals"][key] = now

    entry = round(price, 4)
    mul = 1 if signal == "BUY" else -1
    tp1, tp2, tp3 = round(price + atr*mul, 4), round(price + (atr*1.5)*mul, 4), round(price + (atr*2.5)*mul, 4)
    sl = round(price - (atr*1.2)*mul, 4)

    symbol_bin = symbol.replace("/", "")
    emoji = "🚀" if signal == "BUY" else "📉"
    
    params_text = (
        f"<b>🔔 PREMIUM {signal} {symbol} {emoji}</b>\n\n"
        f"<code>Entry: {entry:.4f}\nTP1:   {tp1:.4f}\nTP2:   {tp2:.4f}\nTP3:   {tp3:.4f}\nSL:    {sl:.4f}\n\nRSI:   {round(rsi, 2)}</code>"
    )

    try:
        img_buf = generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl)
        if img_buf:
            bot.send_photo(CHAT_ID, photo=img_buf, caption=params_text, parse_mode="HTML")
        else:
            bot.send_message(CHAT_ID, params_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Telegram error {symbol}: {e}")

def analyze_market():
    for symbol in SYMBOLS_TO_SCAN:
        try:
            bars = exchange.fetch_ohlcv(symbol, "1h", limit=250)
            if not bars: continue

            # ЯВНОЕ ПРИСВОЕНИЕ ИМЕН СТОЛБЦОВ
            df = pd.DataFrame(bars, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Date'] = pd.to_datetime(df['Date'], unit='ms')
            
            rsi = ta.rsi(df['Close'], length=14).iloc[-1]
            ema = ta.ema(df['Close'], length=200).iloc[-1]
            atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
            price = df['Close'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema): continue

            # Сохраняем Date как индекс перед отправкой в отрисовку
            df_for_plot = df.set_index('Date')

            if rsi < 55 and price > ema:
                send_signal(symbol, df_for_plot, "BUY", price, atr, rsi)
            elif rsi > 45 and price < ema:
                send_signal(symbol, df_for_plot, "SELL", price, atr, rsi)

            time.sleep(2) # Замедление для обхода бана
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

def loop_analyze():
    while True:
        analyze_market()
        time.sleep(600) # Проверка раз в 10 минут

app = Flask(__name__)
@app.route("/")
def home(): return "OK"

if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    bot.infinity_polling()
    
