import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import requests
from flask import Flask
from threading import Thread, Lock
from telebot import types

# --- Настройки ---
TOKEN = '8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U'
CHAT_ID = '737143225'

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Сброс webhook ---
def force_reset():
    try:
        requests.get(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True",
            timeout=10
        )
        logger.info("Сессия Telegram очищена.")
    except Exception as e:
        logger.error(f"Ошибка сброса webhook: {e}")

force_reset()

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
lock = Lock()
state = {
    'sent_signals': {},
    'last_direction': {}
}

# --- Функция анализа рынка ---
def analyze_market():
    logger.info(">>> Сканирование рынка...")
    try:
        markets = exchange.load_markets()
        symbols_to_scan = [s for s in markets if '/USDT' in s]  # все пары с USDT
    except Exception as e:
        logger.error(f"Ошибка загрузки рынка: {e}")
        return

    for symbol in symbols_to_scan:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=210)
            df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)
            df['vol_avg'] = df['v'].rolling(20).mean()

            price = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]
            vol = df['v'].iloc[-1]
            vol_avg = df['vol_avg'].iloc[-1]

            if any(pd.isna(x) for x in [rsi, ema, atr, vol_avg]):
                continue

            # --- Логика сигналов ---
            signal = None
            volatility_ok = atr > (price * 0.003)
            volume_ok = vol > vol_avg

            if rsi < 30 and price > ema and volatility_ok and volume_ok:
                signal = "BUY"
            elif rsi > 70 and price < ema and volatility_ok and volume_ok:
                signal = "SELL"

            if signal:
                now = time.time()
                with lock:
                    last_time = state['sent_signals'].get(symbol, 0)
                    last_dir = state['last_direction'].get(symbol)
                    time_ok = now - last_time > 7200
                    direction_changed = last_dir != signal

                    if time_ok and direction_changed:
                        state['sent_signals'][symbol] = now
                        state['last_direction'][symbol] = signal

                        # --- Точки
