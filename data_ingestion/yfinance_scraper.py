import yfinance as yf
import duckdb
import os
import pandas as pd
from datetime import datetime, timedelta

# Path to the duckdb database created by db_setup.py
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')
ALL_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", # Mag 7
    "ALAB", "AVGO", "MRVL", "AMD", "MU", "PLTR", "ASML", "TSM", "IREN", "CRWV", "CRDO", "TAN", "RKLB", # High Growth Tech
    "WLKP", "ECL", "LIN", "LXU", "CC", # Chemical/Industrial
    "SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B" # Standard Market ETFs & Blue Chips
]

def fetch_and_store_daily_prices():
    """Fetches daily prices from yfinance and stores them in DuckDB."""
    print("Starting YFinance data ingestion...")
    
    if not os.path.exists(DB_PATH):
        print("Database not found! Please run database/db_setup.py first.")
        return

    conn = duckdb.connect(f'md:?motherduck_token={os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")}')
    
    for ticker in ALL_TICKERS:
        print(f"Fetching data for {ticker}...")
        
        # Check the most recent date we have for this ticker to avoid re-downloading 15 years
        result = conn.execute(f"SELECT MAX(date) FROM daily_prices WHERE ticker = '{ticker}'").fetchone()
        last_date = result[0]
        
        if last_date:
            # Fetch from 5 days prior to account for any delayed corrections in Yahoo Finance
            start_date = (pd.to_datetime(last_date) - timedelta(days=5)).strftime('%Y-%m-%d')
            df = yf.download(ticker, start=start_date, progress=False)
        else:
            df = yf.download(ticker, start="2010-01-01", progress=False)
        
        if df.empty:
            print(f"No new data found for {ticker}")
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(ticker, axis=1, level=1)
            
        df = df.reset_index()
        df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        required_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_cols):
            print(f"Missing required columns in response for {ticker}.")
            continue
            
        df = df[required_cols].dropna()
        df['Ticker'] = ticker
        
        df = df.rename(columns={
            'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 
            'Close': 'close', 'Volume': 'volume', 'Ticker': 'ticker'
        })
        
        # UPSERT logic so we don't duplicate overlapping 5 days
        conn.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, volume)
            SELECT ticker, date, open, high, low, close, volume FROM df
            ON CONFLICT (ticker, date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume;
        """)
        print(f"Successfully updated {ticker} in database.")
        
    total_rows = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    print(f"\\nYFinance ingestion complete! Total rows in database: {total_rows}")
    conn.close()

if __name__ == "__main__":
    fetch_and_store_daily_prices()
