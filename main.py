import os
import time
import json
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import requests
from flask import Flask
from threading import Thread, Lock

# --- НАСТРОЙКИ ---
TOKEN = '8758242353:AAE4E9WG7U1IrYaxdvdcwKJX_nkFbQQ9x9U' 
CHAT_ID = '737143225'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Сброс сессии при старте
def force_reset():
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=10)
        logger.info("Сессия Telegram очищена.")
    except: pass

force_reset()

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({'enableRateLimit': True})
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT']

lock = Lock()
# Инициализируем словарь трендов заранее, чтобы /report не был пустым
state = {
    'sent_signals': {}, 
    'trend_states': {s: "Ожидание данных..." for s in symbols},
    'rsi_values': {s: 0.0 for s in symbols}
}

def analyze_market():
    logger.info(">>> Проверка рынка...")
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=210)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df['rsi'] = ta.rsi(df['c'], length=14)
            df['ema'] = ta.ema(df['c'], length=200)
            
            p = df['c'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            ema = df['ema'].iloc[-1]
            
            with lock:
                state['trend_states'][symbol] = "LONG 📈" if p > ema else "SHORT 📉"
                state['rsi_values'][symbol] = round(rsi, 2)

            # Логика сигналов
            if (rsi < 30 and p > ema) or (rsi > 70 and p < ema):
                now = time.time()
                if now - state['sent_signals'].get(symbol, 0) > 7200:
                    side = "BUY" if rsi < 30 else "SELL"
                    bot.send_message(CHAT_ID, f"🔔 **СИГНАЛ {side}**\nМонета: {symbol}\nЦена: {p}\nRSI: {round(rsi, 2)}")
                    state['sent_signals'][symbol] = now
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

app = Flask(__name__)
@app.route('/')
def home(): return "Бот работает"

@bot.message_handler(commands=['status'])
def cmd_status(m):
    bot.reply_to(m, "🤖 Бот онлайн и мониторит рынок!")

@bot.message_handler(commands=['report'])
def cmd_report(m):
    # Формируем отчет аккуратно, без сложных символов
    logger.info("Запрос отчета...")
    text = "📊 **ТЕКУЩИЙ ОТЧЕТ**\n\n"
    with lock:
        for s in symbols:
            trend = state['trend_states'].get(s, "Нет данных")
            rsi = state['rsi_values'].get(s, 0.0)
            text += f"🔹 {s}\nТренд: {trend}\nRSI: {rsi}\n\n"
    
    try:
        bot.send_message(m.chat.id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка отправки отчета: {e}")
        # Запасной вариант без Markdown
        bot.send_message(m.chat.id, text.replace("*", ""))

if __name__ == "__main__":
    Thread(target=lambda: (time.sleep(5), analyze_market()), daemon=True).start()
    
    # Цикл анализа каждые 5 минут
    def loop_analyze():
        while True:
            time.sleep(300)
            analyze_market()
    Thread(target=loop_analyze, daemon=True).start()

    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False)).start()
    
    while True:
        try:
            bot.polling(non_stop=True, interval=3, timeout=20)
        except:
            time.sleep(5)
            
