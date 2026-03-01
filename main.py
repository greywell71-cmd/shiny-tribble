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
# Новые библиотеки для графиков
import mplfinance as mpf
import matplotlib
# Используем неинтерактивный бэкенд для корректной работы в потоках
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- НАСТРОЙКИ ---
TOKEN = "8758242353:AAFuMgWHFtg78jDF3MM8tyVJlVxCGzUNzJw" 
CHAT_ID = "737143225"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
lock = Lock()
state = {"sent_signals": {}, "history": {}}

# Топ пар (сокращено для теста)
SYMBOLS_TO_SCAN = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'LINK/USDT'
]

def generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl):
    """Генерирует реальный свечной график с уровнями сделки"""
    try:
        # Берем последние 40 свечей для наглядности
        plot_df = df.tail(40).copy()
        plot_df.set_index('t', inplace=True)
        # mplfinance требует индекс DatetimeIndex
        plot_df.index = pd.to_datetime(plot_df.index, unit='ms')

        # Цветовая гамма в зависимости от сигнала
        colors = mpf.make_marketcolors(up='#00ff88', down='#ff3355', wick='inherit', edge='inherit', volume='in')
        
        # Настройка стиля (фон, сетка, шрифты)
        s = mpf.make_mpf_style(
            base_mpf_style='nightclouds', # Темная тема
            marketcolors=colors, 
            gridcolor='#222233', 
            facecolor='#050519', # Глубокий синий фон
            figcolor='#050519'
        )

        # Подготовка дополнительных линий (Levels)
        # hlines - горизонтальные линии
        levels = [entry, tp1, tp2, tp3, sl]
        level_colors = ['#0088ff', '#00ff00', '#00ee00', '#00cc00', '#ff0000'] # Blue, Green x3, Red
        
        # Создаем буфер для сохранения картинки
        buf = BytesIO()
        
        # Отрисовка
        mpf.plot(
            plot_df,
            type='candle',        # Тип: свечи
            style=s,              # Наш стиль
            title=f"\nPREMIUM {signal} {symbol}",
            ylabel='Price (USDT)',
            hlines=dict(hlines=levels, colors=level_colors, linestyle='-.', linewidths=1.5),
            figsize=(12, 8),      # Размер окна (соотношение)
            datetime_format='%H:%M', # Формат времени на оси X
            tight_layout=True,    # Убрать лишние отступы
            savefig=buf           # Сохранить в буфер, а не показать
        )
        
        buf.seek(0)
        # Очищаем matplotlib во избежание утечек памяти
        plt.close('all') 
        return buf
        
    except Exception as e:
        logger.error(f"Ошибка генерации графика для {symbol}: {e}")
        plt.close('all')
        return None

def send_signal(symbol, df, signal, price, atr, rsi):
    """Формирует сигнал, график и отправляет в Telegram"""
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        # Анти-спам: 1 сигнал в час для одной пары
        if now - state["sent_signals"].get(key, 0) < 3600: return
        state["sent_signals"][key] = now

    entry = round(price, 4)
    # Расчет уровней на основе ATR
    if signal == "BUY":
        tp1 = round(price + atr, 4)
        tp2 = round(price + atr*1.5, 4)
        tp3 = round(price + atr*2.5, 4)
        sl  = round(price - atr*1.2, 4)
    else: # SELL
        tp1 = round(price - atr, 4)
        tp2 = round(price - atr*1.5, 4)
        tp3 = round(price - atr*2.5, 4)
        sl  = round(price + atr*1.2, 4)

    symbol_bin = symbol.replace("/", "")
    emoji = "🚀" if signal == "BUY" else "📉"
    
    # Моноширинный текст для Telegram (красивое выравнивание)
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
        f"🔗 <a href='https://www.binance.com/en/trade/{symbol_bin}'>Binance Spot</a> | "
        f"<a href='https://www.binance.com/en/futures/{symbol_bin}'>Futures</a>"
    )

    try:
        # Генерируем график, передавая DataFrame и уровни
        img_buf = generate_vip_png(symbol, df, signal, entry, tp1, tp2, tp3, sl)
        
        if img_buf:
            # Отправляем фото с подписью
            bot.send_photo(CHAT_ID, photo=img_buf, caption=params_text, parse_mode="HTML")
            img_buf.close() # Закрываем буфер
        else:
            # Если график не удался, отправляем просто текст
            bot.send_message(CHAT_ID, params_text, parse_mode="HTML")

        with lock:
            if symbol not in state["history"]: state["history"][symbol] = []
            state["history"][symbol].append({"signal": signal, "entry": entry, "time": now})
            
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения для {symbol}: {e}")

def safe_fetch_ohlcv(symbol):
    try:
        # Лимит 205, чтобы хватило на EMA200 и +40 для графика
        return exchange.fetch_ohlcv(symbol, "1h", limit=250)
    except Exception as e:
        logger.error(f"{symbol} fetch error: {e}")
        return None

def analyze_market():
    logger.info("Запуск цикла анализа...")
    for symbol in SYMBOLS_TO_SCAN:
        try:
            bars = safe_fetch_ohlcv(symbol)
            if not bars or len(bars) < 200: continue

            # Подготовка данных
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            
            # Расчет индикаторов
            rsi_series = ta.rsi(df['c'], length=14)
            ema_series = ta.ema(df['c'], length=200)
            atr_series = ta.atr(df['h'], df['l'], df['c'], length=14)

            # Проверка на наличие данных (NaN)
            if rsi_series is None or ema_series is None or atr_series is None: continue

            rsi = rsi_series.iloc[-1]
            ema = ema_series.iloc[-1]
            atr = atr_series.iloc[-1]
            price = df['c'].iloc[-1]

            if pd.isna(rsi) or pd.isna(ema) or pd.isna(atr): continue

            # ВАША ЛОГИКА RSI (БЕЗ ИЗМЕНЕНИЙ)
            if rsi < 55 and price > ema:
                # Передаем df в send_signal для отрисовки
                send_signal(symbol, df, "BUY", price, atr, rsi)
            elif rsi > 45 and price < ema:
                send_signal(symbol, df, "SELL", price, atr, rsi)

            # Небольшая пауза, чтобы не превысить лимиты API
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")
    logger.info("Цикл анализа завершен.")

def loop_analyze():
    while True:
        analyze_market()
        # Пауза 5 минут между кругами сканирования
        time.sleep(300)

app = Flask(__name__)
@app.route("/")
def home(): return "Бот-аналитик работает."

if __name__ == "__main__":
    # 1. Запуск потока анализа рынка
    analysis_thread = Thread(target=loop_analyze, daemon=True)
    analysis_thread.start()
    
    # 2. Запуск потока Telegram бота (для обработки команд, если появятся)
    polling_thread = Thread(target=lambda: bot.polling(non_stop=True), daemon=True)
    polling_thread.start()
    
    # 3. Запуск веб-сервера (для деплоя, например, на Render/Heroku)
    port = int(os.environ.get("PORT", 10000))
    # use_reloader=False обязателен при использовании Threading
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        
