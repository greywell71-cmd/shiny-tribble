import os
import time
import logging
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
from flask import Flask
from threading import Thread, Lock
from telebot import types
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# --- Настройки ---
TOKEN = "8758242353:AAG5DoNU8Im5TXaXFeeWgHSj1_nSB4OwblI"
CHAT_ID = os.getenv('737143225')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance({
    "enableRateLimit": True,  # Включаем встроенную защиту от rate limit
    "options": {"defaultType": "spot"}  # Уточняем spot, чтобы избежать фьючерсов
})
lock = Lock()
state = {"sent_signals": {}, "last_direction": {}, "history": {}}

# --- Командное меню ---
bot.set_my_commands(
    [
        types.BotCommand("status", "Проверить онлайн статус бота"),
        types.BotCommand("report", "Показать последний сигнал по всем парам"),
        types.BotCommand("history", "Показать историю сигналов"),
        types.BotCommand("pairs", "Список всех сканируемых пар"),
        types.BotCommand("help", "Инструкция по использованию бота"),
    ]
)

# --- Список сканируемых пар (ограничен топ-50 ликвидными, чтобы избежать бана по rate limit) ---
SYMBOLS_TO_SCAN = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'SHIB/USDT', 'LINK/USDT',
    'TON/USDT', 'DOT/USDT', 'SUI/USDT', 'NEAR/USDT', 'TRX/USDT',
    'PEPE/USDT', 'LTC/USDT', 'UNI/USDT', 'APT/USDT', 'ICP/USDT',
    'HBAR/USDT', 'KAS/USDT', 'ETC/USDT', 'FET/USDT', 'VET/USDT',
    'OP/USDT', 'FIL/USDT', 'INJ/USDT', 'ARB/USDT', 'MNT/USDT',
    'IMX/USDT', 'WIF/USDT', 'JUP/USDT', 'ONDO/USDT', 'AR/USDT',
    'FLOKI/USDT', 'GRT/USDT', 'RUNE/USDT', 'SEI/USDT', 'TIA/USDT',
    'ALGO/USDT', 'AAVE/USDT', 'QNT/USDT', 'MKR/USDT', 'FLOW/USDT',
    'BCH/USDT', 'THETA/USDT', 'FTM/USDT', 'STX/USDT', 'ATOM/USDT',
]

# --- Генерация VIP PNG (используем дефолтный шрифт, чтобы избежать ошибок на серверах) ---
def generate_vip_png(symbol, signal, entry, tp1, tp2, tp3, sl, rsi, atr, tf, rr):
    WIDTH, HEIGHT = 1024, 1024
    BG_COLOR = (18, 18, 18)
    TEXT_COLOR = (255, 255, 255)
    HIGHLIGHT_COLOR = (0, 220, 0) if signal == "BUY" else (255, 60, 60)
    BUTTON_BG = (40, 40, 40)
    BUTTON_HIGHLIGHT = HIGHLIGHT_COLOR

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    font_large = ImageFont.load_default()  # Дефолтный шрифт, чтобы работал везде
    font_medium = ImageFont.load_default()
    font_small = ImageFont.load_default()

    draw.text((50, 40), f"VIP SIGNAL {signal} {symbol}", fill=HIGHLIGHT_COLOR, font=font_large)

    y = 160
    data = {
        "Entry": entry,
        "TP1": tp1,
        "TP2": tp2,
        "TP3": tp3,
        "SL": sl,
        "RSI": rsi,
        "ATR": atr,
        "TF": tf,
        "R/R": rr,
    }
    for k, v in data.items():
        draw.text((50, y), f"{k}: {v}", fill=TEXT_COLOR, font=font_medium)
        y += 55

    buttons = ["🟢 Spot BUY", "🔴 Spot SELL", "📈 Futures LONG", "📉 Futures SHORT", "📊 Open Chart"]
    y_button = HEIGHT - 150
    button_width, button_height = 180, 60
    gap = 20
    for i, btn in enumerate(buttons):
        x = 50 + i * (button_width + gap)
        color = BUTTON_HIGHLIGHT if ("BUY" in btn and signal == "BUY") or ("SELL" in btn and signal == "SELL") else BUTTON_BG
        draw.rectangle([x, y_button, x + button_width, y_button + button_height], fill=color)
        w, h = draw.textsize(btn, font=font_small)
        draw.text((x + (button_width - w) / 2, y_button + (button_height - h) / 2), btn, fill=(255, 255, 255), font=font_small)

    output = BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output

# --- Отправка сигнала (добавлена обработка ошибок) ---
def send_signal(symbol, signal, price, atr, rsi):
    now = time.time()
    with lock:
        key = f"{symbol}_{signal}"
        last_time = state["sent_signals"].get(key, 0)
        if now - last_time < 7200:
            logger.info(f"Сигнал {symbol} {signal} пропущен: недавно отправлен")
            return
        state["sent_signals"][key] = now
        if symbol not in state["history"]:
            state["history"][symbol] = []

    entry_price = round(price, 4)
    tp1 = round(price + atr if signal == "BUY" else price - atr, 4)
    tp2 = round(price + atr * 1.5 if signal == "BUY" else price - atr * 1.5, 4)
    tp3 = round(price + atr * 2 if signal == "BUY" else price - atr * 2, 4)
    sl_price = round(price - atr if signal == "BUY" else price + atr, 4)
    rr_ratio = "1:2"
    tf = "1H"

    symbol_binance = symbol.replace("/", "_")
    urls = {
        "spot_buy": f"https://www.binance.com/en/trade/{symbol_binance}?type=MARKET",
        "spot_sell": f"https://www.binance.com/en/trade/{symbol_binance}?type=MARKET",
        "futures_buy": f"https://www.binance.com/en/futures/{symbol_binance}?type=MARKET",
        "futures_sell": f"https://www.binance.com/en/futures/{symbol_binance}?type=MARKET",
        "chart": f"https://www.tradingview.com/symbols/{symbol_binance}/",
    }

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Spot BUY", url=urls["spot_buy"]),
        types.InlineKeyboardButton("🔴 Spot SELL", url=urls["spot_sell"]),
        types.InlineKeyboardButton("📈 Futures LONG", url=urls["futures_buy"]),
        types.InlineKeyboardButton("📉 Futures SHORT", url=urls["futures_sell"]),
        types.InlineKeyboardButton("📊 Open Chart", url=urls["chart"]),
    )

    try:
        image = generate_vip_png(symbol, signal, entry_price, tp1, tp2, tp3, sl_price, round(rsi, 2), round(atr, 4), tf, rr_ratio)
        bot.send_photo(CHAT_ID, photo=image, caption=f"🔔 VIP сигнал {signal} {symbol}", reply_markup=markup)
        logger.info(f"Сигнал отправлен: {symbol} {signal}")
        state["history"][symbol].append({"signal": signal, "entry": entry_price, "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl_price, "time": now})
    except Exception as e:
        logger.error(f"Ошибка отправки сигнала {symbol}: {e}")

# --- Безопасный fetch_ohlcv с защитой от rate limit (рекурсия до 3 попыток) ---
def safe_fetch_ohlcv(symbol, timeframe="1h", limit=210, attempts=3):
    for attempt in range(attempts):
        try:
            return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except ccxt.RateLimitExceeded as e:
            wait_time = 30 * (attempt + 1)  # 30, 60, 90 сек
            logger.warning(f"Rate limit на {symbol} (попытка {attempt+1}): {e} → ждём {wait_time} сек")
            time.sleep(wait_time)
        except ccxt.NetworkError as e:
            logger.warning(f"Сетевая ошибка на {symbol}: {e} → ждём 10 сек")
            time.sleep(10)
        except Exception as e:
            logger.error(f"{symbol} fetch_ohlcv упал: {e}")
            return None
    logger.error(f"Не удалось загрузить данные для {symbol} после {attempts} попыток")
    return None

# --- Анализ рынка (используем фиксированный список пар, добавлены логи) ---
def analyze_market():
    try:
        markets = exchange.load_markets()
        if not markets or not isinstance(markets, dict):
            logger.error("Ошибка загрузки markets")
            return
        symbols_to_scan = [s for s in SYMBOLS_TO_SCAN if s in markets]  # Только активные
        logger.info(f"Сканируем {len(symbols_to_scan)} пар")
    except Exception as e:
        logger.error(f"Ошибка загрузки рынка: {e}")
        return

    for symbol in symbols_to_scan:
        try:
            bars = safe_fetch_ohlcv(symbol)
            if bars is None:
                continue
            df = pd.DataFrame(bars, columns=["t", "o", "h", "l", "c", "v"])
            df["rsi"] = ta.rsi(df["c"], length=14)
            df["ema"] = ta.ema(df["c"], length=200)
            df["atr"] = ta.atr(df["h"], df["l"], df["c"], length=14)
            df["macd"] = ta.macd(df["c"])["MACD_12_26_9"]
            df["vol_avg"] = df["v"].rolling(20).mean()

            price = df["c"].iloc[-1]
            rsi = df["rsi"].iloc[-1]
            ema = df["ema"].iloc[-1]
            atr = df["atr"].iloc[-1]
            vol = df["v"].iloc[-1]
            vol_avg = df["vol_avg"].iloc[-1]
            macd = df["macd"].iloc[-1]

            if any(pd.isna(x) for x in [rsi, ema, atr, vol_avg, macd]):
                logger.warning(f"{symbol}: NaN в индикаторах, пропуск")
                continue

            candle_body = abs(df["c"].iloc[-1] - df["o"].iloc[-1])
            if candle_body < 0.5 * atr or vol <= vol_avg:
                continue

            # Условия сигнала (ослаблены для теста: RSI <35 вместо 30, >65 вместо 70; убрал macd >0/<0 для частоты)
            # Если сигналы всё равно редкие - уберите фильтр по vol/candle_body временно
            if rsi < 35 and price > ema:  # and macd > 0:  # закомментировал macd для теста
                send_signal(symbol, "BUY", price, atr, rsi)
            if rsi > 65 and price < ema:  # and macd < 0:
                send_signal(symbol, "SELL", price, atr, rsi)

            time.sleep(0.5)  # Минимальная пауза между парами
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")

def loop_analyze():
    while True:
        analyze_market()
        time.sleep(300)  # 5 минут

# --- Flask ---
app = Flask(__name__)

@app.route("/")
def home():
    return "VIP Бот работает"

# --- Команды Telegram ---
@bot.message_handler(commands=["status"])
def cmd_status(m):
    bot.reply_to(m, "🤖 VIP Бот онлайн, сканирует топ-пары USDT!")

@bot.message_handler(commands=["report"])
def cmd_report(m):
    text = "📊 *ТЕКУЩИЙ ОТЧЕТ*\n\n"
    with lock:
        if not state["history"]:
            text += "Нет сигналов пока."
        for s, h in state["history"].items():
            last = h[-1]
            text += f"🔹 `{s}` — Последний сигнал: {last['signal']} (Entry: {last['entry']})\n"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["history"])
def cmd_history(m):
    msg = "📜 История сигналов:\n\n"
    with lock:
        if not state["history"]:
            msg += "Нет истории."
        for s, h in state["history"].items():
            msg += f"{s}:\n"
            for sig in h[-5:]:
                msg += f"  - {sig['signal']} Entry:{sig['entry']} TP1:{sig['tp1']} SL:{sig['sl']}\n"
    bot.send_message(m.chat.id, msg)

@bot.message_handler(commands=["pairs"])
def cmd_pairs(m):
    text = "🔹 Скандируемые пары:\n" + "\n".join(SYMBOLS_TO_SCAN)
    bot.send_message(m.chat.id, text)

@bot.message_handler(commands=["help"])
def cmd_help(m):
    text = (
        "🤖 VIP Crypto Bot команды:\n"
        "/status - проверить статус бота\n"
        "/report - последний сигнал по всем парам\n"
        "/history - последние 5 сигналов по каждой паре\n"
        "/pairs - список всех сканируемых пар\n"
        "/help - эта инструкция\n\n"
        "Сигналы отправляются с LONG и SHORT сразу и включают Entry, TP, SL, RSI, ATR, R/R и таймфрейм."
    )
    bot.send_message(m.chat.id, text)

# --- Запуск ---
if __name__ == "__main__":
    Thread(target=loop_analyze, daemon=True).start()
    Thread(target=lambda: bot.polling(non_stop=True, interval=3, timeout=20), daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
