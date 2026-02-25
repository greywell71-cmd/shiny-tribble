
import ccxt, pandas_ta as ta, requests, pandas as pd, time

TOKEN = "8758242353:AAFt4tlgTrZBikosPCY19y6MAtPlFeprxO0"
CHAT_ID = "737143225"
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LTC/USDT']

exchange = ccxt.kucoin()
cache = {'signals': {}, 'prices': {}}

def send_tg(text, symbol, category="SIGNAL"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    link = f"https://www.tradingview.com/chart/?symbol=KUCOIN:{symbol.replace('/', '')}"
    icons = {"SIGNAL": "🔔", "PUMP": "⚡️", "LIQ": "💀"}
    
    payload = {
        "chat_id": CHAT_ID,
        "text": f"{icons.get(category, 'ℹ️')} {category}\n{'-'*20}\n{text}",
        "reply_markup": {"inline_keyboard": [[{"text": f"📊 График {symbol}", "url": link}]]}
    }
    try: requests.post(url, json=payload, timeout=10)
    except: print("Ошибка связи с TG")

def check_market():
    print(f"[{time.strftime('%H:%M:%S')}] Сканирование...")
    for s in SYMBOLS:
        try:
            # Загружаем данные и СРАЗУ делаем их понятными для Python
            bars = exchange.fetch_ohlcv(s, timeframe='1h', limit=250)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.astype({'close': float, 'low': float, 'high': float}) # ПРИНУДИТЕЛЬНО В ЧИСЛА
            
            # Считаем индикаторы
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['sma'] = ta.sma(df['close'], length=200)
            
            p = df['close'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            sma = df['sma'].iloc[-1] if pd.notnull(df['sma'].iloc[-1]) else p
            
            # 1. Проверка Пампа/Дампа
            if s in cache['prices']:
                diff = ((p - cache['prices'][s]) / cache['prices'][s]) * 100
                if abs(diff) >= 1.5:
                    send_tg(f"{s}: {'ВВЕРХ 🚀' if diff > 0 else 'ВНИЗ 📉'}\nИзменение: {diff:.2f}%\nЦена: {p}", s, "PUMP")
            cache['prices'][s] = p

            # 2. Торговые сигналы
            trend = "📈 UP" if p > sma else "📉 DOWN"
            if rsi <= 30 and cache['signals'].get(s) != 'buy':
                send_tg(f"ПОКУПКА {s}\nЦена: {p}\nТренд: {trend}\nRSI: {rsi:.2f}", s, "SIGNAL")
                cache['signals'][s] = 'buy'
            elif rsi >= 70 and cache['signals'].get(s) != 'sell':
                send_tg(f"ПРОДАЖА {s}\nЦена: {p}\nТренд: {trend}\nRSI: {rsi:.2f}", s, "SIGNAL")
                cache['signals'][s] = 'sell'
            elif 45 < rsi < 55: cache['signals'][s] = None

        except Exception as e:
            print(f"Ошибка {s}: {str(e)}")

if __name__ == "__main__":
    print("💎 Бот-Терминатор v3.0 запущен!")
    while True:
        check_market()
        time.sleep(60
