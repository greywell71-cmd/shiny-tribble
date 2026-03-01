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
TOKEN = "8758242353:AAFuMgWHFtg78jDF3MM8tyVJlVxCGzUNzJw8758242353:AAFuMgWHFtg78jDF3MM8tyVJlVxCGzUNzJw" 
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
# Добавлен таймаут и расширенный лимит для стабильности на Render
exchange = ccxt.binance({
    "enableRateLimit": True, 
    "timeout": 30000,
    "options": {"defaultType": "spot"}
})
lock = Lock()
state = {"sent_signals": {}, "history": {}}

SYMBOLS_TO_SCAN = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'LINK/USDT'
]

def generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    try:
        # Работаем с копией последних 40 свечей
        plot_df = df.tail(40).copy()
        
        # Убеждаемся, что индекс — это Datetime (критично для mplfinance)
        plot_df.index = pd.to_datetime(plot_df.index, unit='ms')

        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        s = mpf.make_mpf_style(
            base_mpf_style='nightclouds', 
            marketcolors=colors, 
            gridcolor='#222233', 
            facecolor='#050519', 
            figcolor='#050519'
        )

        levels = [entry, tp1, tp2, tp3, sl]
        level_colors = ['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000']
        
        buf = BytesIO()
        mpf.plot(
            plot_df,
            type='candle',
            style=s,
            title=f"\nPREMIUM {signal} {symbol}",
            ylabel='Price (USDT)',
            hlines=dict(hlines=levels, colors=level_colors, linestyle='-.', linewidths=1.5),
            figsize=(12, 8),
            datetime_format='%H:%M',
            tight_layout=True,
            savefig=buf
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
    if signal == "BUY":
        tp1, tp2, tp3 = round(price + atr, 4), round(price + atr*1.5, 4), round(price + atr*2.5, 4)
        sl = round(price - atr*1.2, 4)
    else:
        tp1, tp2, tp3 = round(price - atr, 4), round(price - atr*1.5, 4), round(price - atr*2.5, 4)
        sl = round(price + atr*1.2, 4)

    symbol_bin = symbol.replace("/", "")
    emoji = "🚀" if signal == "BUY" else "📉"
    
    params_text = (
        f"<b>🔔 PREMIUM {signal} {symbol} {emoji}</b>\n\n"
        f"<code>"
        f"Entry:  {entry:.4f}\n"
        f"TP1:    {tp1:.4f}\n"
        f"TP2:    {tp2:.4f}\n"
        f"TP3:    {tp3:.4f}\n"
        f"SL:     {sl:.4f}\n\n"
        f"RSI:    {round(rsi, 2)}\n"
        f"ATR:    {round(atr, 4)}\n"
        f"TF:     1h | R/R: 1:2+"
        f"</code>\n\n"
        f"🔗 <a href='https://www.binance.com/en/trade/{symbol_bin}'>Spot</a> | <a href='https://www.binance.com/en/futures/{symbol_bin}'>Futures</a>"
    )

    try:
        img_buf = generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl)
        if img_buf:
            bot.send_photo(CHAT_ID, photo=img_buf, caption=params_text, parse_mode="HTML")
            img_buf.close()
        else:
            bot.send_message(CHAT_ID, params_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Telegram error {symbol}: {e}")

def safe_fetch_ohlcv(symbol):
    try:
        return exchange.fetch_ohlcv(symbol, "1h", limit=250)
    except Exception as e:
        logger.error(f"Ошибка получения {symbol}: {e}")
        return None

def analyze_market():
    logger.info("--- Новый цикл анализа ---")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            bars = safe_fetch_ohlcv(symbol)
            if not bars or len(bars) < 200:
                continue

            # ИСПРАВЛЕНИЕ: Названия столбцов теперь на английском
            df = pd.DataFrame(bars, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            
            # Расчет индикаторов по новым именам столбцов
            rsi = ta.rsi(df['Close'], length=14).iloc[-1]
            ema = ta.ema(df['Close'], length=200).iloc[-1]
            atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
            price = df['Close'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema): continue

            # Устанавливаем дату как индекс для индикаторов и графиков
            df.set_index('Date', inplace=False) 

            if rsi < 55 and price > ema:
                send_signal(symbol, df.set_index('Date'), "BUY", price, atr, rsi)
            elif rsi > 45 and price < ema:
                send_signal(symbol, df.set_index('Date'), "SELL", price, atr, rsi)

            time.sleep(1) # Увеличенная пауза для обхода 418 ошибки
        except Exception as e:
            logger.error(f"Ошибка в цикле для {symbol}: {e}")
    logger.info("Цикл завершен.")

def loop_analyze():
    while True:
        analyze_market()
        time.sleep(600) # Увеличил до 10 минут, чтобы снизить риск бана IP

app = Flask(__name__)
@app.route("/")
def home(): return "Бот запущен и сканирует рынок."

if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    Thread(target=lambda: bot.polling(non_stop=True), daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
    
