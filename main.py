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

# --- НАСТРОЙКИ ---
TOKEN = "8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U"
CHAT_ID = '737143225'

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

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
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()

state = {
    'sent_signals': {},
    'last_direction': {},
    'trend_states': {s: "Ожидание данных..." for s in symbols},
    'rsi_values': {s: 0.0 for s in symbols}
}

# --- Анализ ---
def analyze_market():
    logger.info(">>> Проверка рынка...")

    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=210)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])

            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            df['atr'] = ta.atr(df['h'], df['l'], df['c'], length=14)
            df['vol_avg'] = df['v'].rolling(20).mean()

            p = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            atr = df['atr'].iloc[-1]
            vol = df['v'].iloc[-1]
            vol_avg = df['vol_avg'].iloc[-1]

            if any(pd.isna(x) for x in [rsi, ema, atr, vol_avg]):
                continue

            with lock:
                state['trend_states'][symbol] = "LONG 📈" if p > ema else "SHORT 📉"
                state['rsi_values'][symbol] = round(rsi, 2)

            # --- ФИЛЬТР ВОЛАТИЛЬНОСТИ ---
            volatility_ok = atr > (p * 0.003)  # минимум 0.3% движения

            # --- ФИЛЬТР ОБЪЁМА ---
            volume_ok = vol > vol_avg

            signal = None

            if rsi < 30 and p > ema and volatility_ok and volume_ok:
                signal = "BUY"

            elif rsi > 70 and p < ema and volatility_ok and volume_ok:
                signal = "SELL"

            if signal:
                now = time.time()

                with lock:
                    last_time = state['sent_signals'].get(symbol, 0)
                    last_dir = state['last_direction'].get(symbol)

                    time_ok = now - last_time > 7200
                    direction_changed = last_dir != signal

                    if time_ok and direction_changed:
                        text = (
                            f"🔔 *СИГНАЛ {signal}*\n"
                            f"Монета: `{symbol}`\n"
                            f"Цена: {round(p,4)}\n"
                            f"RSI: {round(rsi,2)}\n"
                            f"ATR: {round(atr,4)}\n"
                            f"Объём ↑"
                        )

                        try:
                            bot.send_message(CHAT_ID, text, parse_mode="Markdown")
                            state['sent_signals'][symbol] = now
                            state['last_direction'][symbol] = signal
                            logger.info(f"{signal} отправлен для {symbol}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки: {e}")

        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

# --- Flask ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает"

# --- Команды ---
@bot.message_handler(commands=['status'])
def cmd_status(m):
    bot.reply_to(m, "🤖 Бот онлайн и анализирует рынок!")

@bot.message_handler(commands=['report'])
def cmd_report(m):
    text = "📊 *ТЕКУЩИЙ ОТЧЕТ*\n\n"

    with lock:
        for s in symbols:
            trend = state['trend_states'].get(s, "Нет данных")
            rsi = state['rsi_values'].get(s, 0.0)

            text += (
                f"🔹 `{s}`\n"
                f"Тренд: {trend}\n"
                f"RSI: {rsi}\n\n"
            )

    try:
        bot.send_message(m.chat.id, text, parse_mode="Markdown")
    except:
        bot.send_message(m.chat.id, text.replace("*", "").replace("`", ""))

# --- Запуск ---
if __name__ == "__main__":

    def initial():
        time.sleep(5)
        analyze_market()

    Thread(target=initial, daemon=True).start()

    def loop():
        while True:
            time.sleep(300)
            analyze_market()

    Thread(target=loop, daemon=True).start()

    port = int(os.environ.get("PORT", 8080))
    Thread(
        target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False),
        daemon=True
    ).start()

    while True:
        try:
            bot.polling(non_stop=True, interval=3, timeout=20)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)
