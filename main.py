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
TOKEN = "8758242353:AAH0qvtMx2VJXHMJyH1LhaLssge97boHwaA" 
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if not TOKEN or ":" not in TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram не задан!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# Настройка подключения к Binance с лимиттером
exchange = ccxt.binance({
    "enableRateLimit": True, 
    "timeout": 30000,
    "options": {"defaultType": "spot"}
})

lock = Lock()
state = {"sent_signals": {}}

SYMBOLS_TO_SCAN = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT']

def generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    try:
        plot_df = df.tail(40).copy()
        plot_df.index = pd.to_datetime(plot_df.index)

        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=colors, facecolor='#050519', figcolor='#050519')

        levels = [entry, tp1, tp2, tp3, sl]
        level_colors = ['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000']
        
        buf = BytesIO()
        fig, _ = mpf.plot(
            plot_df, type='candle', style=s,
            title=f"\nPREMIUM {signal} {symbol}",
            hlines=dict(hlines=levels, colors=level_colors, linestyle='-.', linewidths=1.5),
            figsize=(12, 8), savefig=buf, returnfig=True
        )
        buf.seek(0)
        plt.close(fig) # Очистка памяти
        return buf
    except Exception as e:
        logger.error(f"Ошибка отрисовки {symbol}: {e}")
        plt.close('all')
        return None

def send_signal(symbol, df, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        # Не спамим: одна и та же монета не чаще чем раз в 2 часа
        if now - state["sent_signals"].get(key, 0) < 7200: return
        state["sent_signals"][key] = now

    entry = round(price, 4)
    mul = 1 if signal == "BUY" else -1
    tp1, tp2, tp3 = round(price + atr*mul, 4), round(price + (atr*1.5)*mul, 4), round(price + (atr*2.5)*mul, 4)
    sl = round(price - (atr*1.2)*mul, 4)

    # Эмодзи-оформление
    if signal == "BUY":
        m_emoji, t_emoji, dot = "🚀", "📈", "🟢"
    else:
        m_emoji, t_emoji, dot = "📉", "📉", "🔴"
    
    params_text = (
        f"{m_emoji} <b>PREMIUM SIGNAL: {symbol}</b> {m_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Тип:</b> {signal} {t_emoji}\n"
        f"<b>Вход:</b> <code>{entry:.4f}</code>\n\n"
        f"🎯 <b>ЦЕЛИ:</b>\n"
        f"├ TP1: <code>{tp1:.4f}</code> ✅\n"
        f"├ TP2: <code>{tp2:.4f}</code> 🔥\n"
        f"└ TP3: <code>{tp3:.4f}</code> 🚀\n\n"
        f"🛑 <b>STOP LOSS:</b> <code>{sl:.4f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>АНАЛИЗ:</b>\n"
        f"{dot} RSI: <code>{round(rsi, 2)}</code>\n"
        f"💎 <i>Status: Active</i>"
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
    logger.info(">>> Запуск сканирования...")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            # 1. ПАУЗА 10 СЕКУНД (чтобы Binance не забанил за спам)
            time.sleep(10) 
            
            bars = exchange.fetch_ohlcv(symbol, "1h", limit=250)
            if not bars: continue

            df = pd.DataFrame(bars, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Date'] = pd.to_datetime(df['Date'], unit='ms')
            
            rsi = ta.rsi(df['Close'], length=14).iloc[-1]
            ema = ta.ema(df['Close'], length=200).iloc[-1]
            atr = ta.atr(df['High'], df['Low'], df['Close'], length=14).iloc[-1]
            price = df['Close'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema): continue

            df_for_plot = df.set_index('Date')

            # Уровни RSI 35/65 более надежны для Render-бота
            if rsi < 35 and price > ema:
                send_signal(symbol, df_for_plot, "BUY", price, atr, rsi)
            elif rsi > 65 and price < ema:
                send_signal(symbol, df_for_plot, "SELL", price, atr, rsi)

        except ccxt.DDoSProtection:
            logger.error("БАН 418! Binance ограничил IP. Спим 15 минут...")
            time.sleep(900)
            return 
        except Exception as e:
            logger.error(f"Ошибка {symbol}: {e}")
            time.sleep(5)

def loop_analyze():
    while True:
        try:
            analyze_market()
            # Отдыхаем 15 минут между кругами сканирования
            time.sleep(900) 
        except Exception as e:
            logger.error(f"Цикл упал: {e}")
            time.sleep(60)

app = Flask(__name__)
@app.route("/")
def home(): return "Бот Активен"

if __name__ == "__main__":
    # Поток для логики анализа
    Thread(target=loop_analyze, daemon=True).start()
    # Запуск бота (Flask не запускаем явно, Render сам подхватит gunicorn, если он прописан)
    logger.info("Бот запущен...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
    
