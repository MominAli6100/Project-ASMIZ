import duckdb
import os
import yfinance as yf
import pandas as pd
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')
MAG_7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

def scrape_whale_data():
    conn = duckdb.connect(DB_PATH)
    fetch_time = datetime.now()
    
    # 1. Dark Pool Engine (Synthetic Block Detection)
    print("Executing Synthetic Dark Pool Engine...")
    for ticker in MAG_7:
        try:
            df = yf.download(ticker, period='5d', interval='5m', progress=False)
            if df.empty: continue
            
            # Fix Yahoo Finance multi-index formatting if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df['Vol_SMA'] = df['Volume'].rolling(20).mean()
            # Calculate intraday volatility range
            df['Price_Range_Pct'] = (df['High'] - df['Low']) / df['Close']
            
            # Analyze only the last 1 trading day (~78 5-minute candles)
            recent = df.tail(78)
            # Mathematical trigger: Volume > 4x Average AND Price moved less than 0.5%
            spikes = recent[(recent['Volume'] > recent['Vol_SMA'] * 4) & (recent['Price_Range_Pct'] < 0.005)]
            
            for idx, row in spikes.iterrows():
                vol = float(row['Volume'])
                price = float(row['Close'])
                dt_str = str(idx.replace(tzinfo=None))
                
                conn.execute(f"""
                    INSERT INTO dark_pool_blocks (ticker, datetime, volume, price)
                    VALUES ('{ticker}', '{dt_str}', {vol}, {price})
                    ON CONFLICT (ticker, datetime) DO NOTHING
                """)
        except Exception as e:
            print(f"Error in Dark Pool {ticker}: {e}")

    # 2. Options Flow Engine
    print("Executing Unusual Options Flow Engine...")
    conn.execute("DELETE FROM options_flow") # Clear old flow so we only show LIVE data
    for ticker in MAG_7:
        try:
            tk = yf.Ticker(ticker)
            exps = tk.options
            if not exps: continue
            
            exp = exps[0] # Nearest expiration date
            chain = tk.option_chain(exp)
            
            for o_type, data, sentiment in [('CALL', chain.calls, 'BULLISH'), ('PUT', chain.puts, 'BEARISH')]:
                # Trigger: Volume is Double the Open Interest AND > 500 contracts
                unusual = data[(data['volume'] > data['openInterest'] * 2) & (data['volume'] > 500)]
                for _, row in unusual.iterrows():
                    conn.execute(f"""
                        INSERT INTO options_flow (ticker, fetch_time, expiration, type, strike, volume, open_interest, sentiment)
                        VALUES ('{ticker}', '{fetch_time}', '{exp}', '{o_type}', {row['strike']}, {row['volume']}, {row['openInterest']}, '{sentiment}')
                    """)
        except Exception as e:
            print(f"Error in Options Flow {ticker}: {e}")
            
    conn.close()
    print("Whale Sync Complete.")

if __name__ == "__main__":
    scrape_whale_data()
