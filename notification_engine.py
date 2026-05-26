import os
import duckdb
import pandas as pd
import joblib
from datetime import datetime, timedelta
import requests

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'quant_data.duckdb')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models', 'saved')

def send_telegram(message):
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not all([bot_token, chat_id]):
        print("Telegram credentials not fully configured. Skipping message.")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Sent Telegram message.")
    except Exception as e:
        print(f"Error sending Telegram: {e}")

def run_engine():
    conn = duckdb.connect(f'md:?motherduck_token={os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")}')
    
    # 1. Setup State Table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_state (
            ticker VARCHAR,
            signal_type VARCHAR,
            last_sent TIMESTAMP
        )
    """)
    
    # 2. Check for Buy Signals
    print("Checking for AI Buy Signals...")
    try:
        df_latest = conn.execute("SELECT * FROM features WHERE date = (SELECT MAX(date) FROM features) ORDER BY ticker").df()
    except Exception as e:
        print(f"Could not fetch features: {e}")
        conn.close()
        return

    features_cols = [
        'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
        'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
    ]
    
    if not df_latest.empty:
        spy_close = df_latest['spy_close'].iloc[0]
        spy_sma = df_latest['spy_sma_200'].iloc[0]
        macro_safe = spy_close > spy_sma
        
        if macro_safe:
            for _, row in df_latest.iterrows():
                ticker = row['ticker']
                X_pred = pd.DataFrame([row[features_cols]])
                model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
                
                if os.path.exists(model_path):
                    model = joblib.load(model_path)
                    try:
                        ai_prob = model.predict_proba(X_pred)[0][1] * 100
                    except:
                        continue
                        
                    if ai_prob > 55.0:
                        # Check Cooldown
                        cooldown_check = conn.execute(f"""
                            SELECT last_sent FROM notification_state 
                            WHERE ticker = '{ticker}' AND signal_type = 'BUY' 
                            ORDER BY last_sent DESC LIMIT 1
                        """).fetchone()
                        
                        can_send = True
                        if cooldown_check:
                            last_sent = pd.to_datetime(cooldown_check[0])
                            if (datetime.now() - last_sent) < timedelta(hours=24):
                                can_send = False
                                
                        if can_send:
                            entry_price = row['close']
                            atr = row['atr_percent']
                            tp = entry_price * (1 + (atr * 2.0))
                            sl = entry_price * (1 - (atr * 1.0))
                            
                            msg = (
                                f"🟢 *AI BUY SIGNAL ALERT* 🟢\n\n"
                                f"Ticker: {ticker}\n"
                                f"AI Confidence: {ai_prob:.1f}%\n"
                                f"Current Price: ${entry_price:.2f}\n"
                                f"🎯 Target: ${tp:.2f}\n"
                                f"🛡️ Stop Loss: ${sl:.2f}\n\n"
                                f"Log this trade in the Active Portfolio tab if you take it!"
                            )
                            send_telegram(msg)
                            conn.execute(f"INSERT INTO notification_state VALUES ('{ticker}', 'BUY', CURRENT_TIMESTAMP)")
    
    # 3. Check Active Portfolio for Sell Signals (TP/SL Hits)
    print("Checking Active Portfolio for Exits...")
    try:
        active_trades = conn.execute("SELECT * FROM active_trades WHERE status = 'ACTIVE'").df()
        if not active_trades.empty:
            for _, trade in active_trades.iterrows():
                ticker = trade['ticker']
                tp = trade['take_profit']
                sl = trade['stop_loss']
                # Get latest price
                live_price_df = conn.execute(f"SELECT close FROM features WHERE ticker = '{ticker}' ORDER BY date DESC LIMIT 1").df()
                if not live_price_df.empty:
                    current_price = live_price_df['close'].iloc[0]
                    
                    if current_price >= tp:
                        msg = f"🎯 *AI SELL ALERT (PROFIT)* 🎯\n\n{ticker} hit its Take Profit of ${tp:.2f}. Close your position to secure gains!"
                        send_telegram(msg)
                        conn.execute(f"UPDATE active_trades SET status = 'CLOSED_WIN' WHERE ticker = '{ticker}' AND status = 'ACTIVE'")
                    
                    elif current_price <= sl:
                        msg = f"🛑 *AI SELL ALERT (STOP LOSS)* 🛑\n\n{ticker} hit its Stop Loss of ${sl:.2f}. The AI recommends exiting to preserve capital."
                        send_telegram(msg)
                        conn.execute(f"UPDATE active_trades SET status = 'CLOSED_LOSS' WHERE ticker = '{ticker}' AND status = 'ACTIVE'")
    except Exception as e:
        print(f"Error checking active portfolio: {e}")

    conn.close()
    print("Notification Engine Finished.")

if __name__ == "__main__":
    run_engine()
