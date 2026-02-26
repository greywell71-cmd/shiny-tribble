import os
import time
import requests
import telebot
import ccxt
import pandas_ta as ta
import pandas as pd
import mplfinance as mpf
from flask import Flask
from threading import Thread

# 1. Flask Web Server for Render Health Checks
# Render requires a web service to bind to a port, otherwise it restarts the container.
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Chart v9.7 LIVE - Systems Operational"

def run_web_server():
    # Render assigns a port dynamically via the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Configuration
# SECURITY NOTE: In a real production environment, use os.environ.get('BOT_TOKEN')
TOKEN = '8758242353:AAGh4-1UM8MCAOjTlsdh62PXs6TRInLqe60'
CHAT_ID = '737143225'

bot = telebot.TeleBot(TOKEN)
exchange = ccxt.binance()
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'MATIC/USDT']
sent_signals = {}

# 3. Market Analysis Functions
def get_fear_greed_index():
    try:
        response = requests.get('https://api.alternative.me/fng/', timeout=5).json()
        value = response['data'][0]['value']
        classification = response['data'][0]['value_classification']
        return f"📊 Fear & Greed Index: {value} ({classification})"
    except Exception:
        return "📊 Fear & Greed Index: N/A"

def generate_chart(symbol, df):
    # Prepare data for the last 45 hours
    plot_df = df.tail(45).copy()
    plot_df['timestamp'] = pd.to_datetime(plot_df['timestamp'], unit='ms')
    plot_df.set_index('timestamp', inplace=True)
    
    file_name = f"{symbol.replace('/', '')}_chart.png"
    
    # Define the RSI indicator plot
    rsi_plot = mpf.make_addplot(plot_df['rsi'], panel=1, color='orange', ylabel='RSI')
    
    # Save the candlestick chart
    mpf.plot(
        plot_df, 
        type='candle', 
        style='charles', 
        addplot=rsi_plot, 
        savefig=file_name, 
        title=f"\n{symbol} 1H Signal", 
        volume=False, 
        panel_ratios=(2, 1), 
        figsize=(10, 7)
    )
    return file_name

def analyze_market():
    for symbol in symbols:
        try:
            # Fetch 1-hour candles
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calculate RSI using pandas_ta
            df['rsi'] = ta.rsi(df['close'], length=14)
            
            last_rsi = df['rsi'].iloc[-1]
            current_price = df['close'].iloc[-1]
            
            signal = None
            if last_rsi < 30: 
                signal = "✅ BUY SIGNAL (Oversold)"
            elif last_rsi > 70: 
                signal = "🚨 SELL SIGNAL (Overbought)"
            
            if signal:
                now = time.time()
                # Anti-spam: Only send one signal per symbol every 2 hours (7200 seconds)
                if symbol in sent_signals and (now - sent_signals[symbol]) < 7200:
                    continue
                
                sent_signals[symbol] = now
                chart_filename = generate_chart(symbol, df)
                
                message_caption = (
                    f"{signal}: {symbol}\n"
                    f"Current Price: {current_price}\n"
                    f"RSI Value: {round(last_rsi, 2)}\n"
                    f"{get_fear_greed_index()}"
                )
                
                with open(chart_filename, 'rb') as photo:
                    bot.send_photo(CHAT_ID, photo, caption=message_caption)
                
                # Clean up the local file after sending
                if os.path.exists(chart_filename):
                    os.remove(chart_filename)
                    
        except Exception as e:
            print(f"Analysis Error for {symbol}: {e}")

# 4. Telegram Bot Commands
@bot.message_handler(commands=['start', 'status'])
def handle_status(message):
    status_text = (
        f"✅ Bot is Online\n"
        f"Monitoring: {', '.join(symbols)}\n"
        f"{get_fear_greed_index()}"
    )
    bot.reply_to(message, status_text)

@bot.message_handler(commands=['report'])
def handle_report(message):
    report_text = "💰 **Latest Market Prices:**\n"
    for s in symbols:
        try:
            ticker = exchange.fetch_ticker(s)
            price = ticker['last']
            report_text += f"🔹 {s}: `${price}`\n"
        except Exception:
            continue
    bot.send_message(message.chat.id, report_text, parse_mode="Markdown")

# 5. Main Execution Threads
def start_bot_polling():
    """Starts the bot with error handling and conflict resolution."""
    while True:
        try:
            print("🤖 Initializing Telegram Polling...")
            # Remove any existing webhooks or conflicting sessions
            bot.remove_webhook()
            time.sleep(1)
            bot.polling(none_stop=True, interval=0, timeout=40)
        except Exception as e:
            print(f"Polling Conflict or Error: {e}")
            # Wait 15 seconds before retrying to let Render's old instance expire
            time.sleep(15)

def start_market_monitoring():
    """Main loop for scanning crypto markets."""
    print("📈 Market Monitor Started")
    while True:
        analyze_market()
        # Wait 5 minutes between full market scans
        time.sleep(300)

if __name__ == "__main__":
    # 1. Start Web Server in background for Render compatibility
    server_thread = Thread(target=run_web_server, daemon=True)
    server_thread.start()
    
    # 2. Start Telegram Bot in background
    bot_thread = Thread(target=start_bot_polling, daemon=True)
    bot_thread.start()
    
    # 3. Start Market Analysis in the main thread
    start_market_monitoring()
    
