import duckdb
import os
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')

def fetch_and_store_macro_data():
    """Fetches macro data from FRED CSV exports without needing an API key."""
    print("Starting FRED Macro data ingestion...")
    
    conn = duckdb.connect(f'md:?motherduck_token={os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")}')
    
    result = conn.execute("SELECT MAX(date) FROM macro_data").fetchone()
    last_date = result[0]
    
    print("Fetching DGS10 (10Y Yield) and M2SL (Money Supply) from FRED CSVs...")
    try:
        dgs10 = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", na_values='.')
        m2sl = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL", na_values='.')
    except Exception as e:
        print(f"Failed to fetch FRED data: {e}")
        conn.close()
        return

    # Merge FRED data
    dgs10['observation_date'] = pd.to_datetime(dgs10['observation_date']).dt.date
    m2sl['observation_date'] = pd.to_datetime(m2sl['observation_date']).dt.date
    
    macro_df = pd.merge(dgs10, m2sl, on='observation_date', how='outer').sort_values('observation_date')
    macro_df = macro_df.rename(columns={'observation_date': 'DATE'})
    
    # Forward fill monthly M2SL data to create daily macro context
    macro_df['M2SL'] = macro_df['M2SL'].ffill()
    
    print("Fetching SPY benchmark for macro filter...")
    # Fetch SPY data
    spy_full = yf.download("SPY", start="2008-01-01", progress=False)
    
    if isinstance(spy_full.columns, pd.MultiIndex):
        spy_full = spy_full.xs("SPY", axis=1, level=1)
        
    spy_full['spy_sma_200'] = spy_full['Close'].rolling(200).mean()
    spy_full = spy_full.reset_index()
    spy_full['Date'] = pd.to_datetime(spy_full['Date']).dt.date
    
    # Merge spy data with macro data
    final_df = pd.merge(spy_full[['Date', 'Close', 'spy_sma_200']], macro_df, left_on='Date', right_on='DATE', how='left')
    
    # Forward fill FRED data over weekends to match SPY trading days
    final_df['DGS10'] = final_df['DGS10'].ffill()
    final_df['M2SL'] = final_df['M2SL'].ffill()
    
    final_df = final_df.dropna(subset=['spy_sma_200']) # Drop early rows missing 200 SMA
    
    # Restrict to 2010 onwards
    final_df = final_df[final_df['Date'] >= pd.to_datetime("2010-01-01").date()]

    final_df = final_df.rename(columns={
        'Date': 'date',
        'Close': 'spy_close',
        'DGS10': 'us_10y_yield',
        'M2SL': 'm2_money_supply'
    })
    
    final_df = final_df[['date', 'spy_close', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply']]

    # UPSERT into DuckDB
    conn.execute("""
        INSERT INTO macro_data (date, spy_close, spy_sma_200, us_10y_yield, m2_money_supply)
        SELECT date, spy_close, spy_sma_200, us_10y_yield, m2_money_supply FROM final_df
        ON CONFLICT (date) DO UPDATE SET
            spy_close = EXCLUDED.spy_close,
            spy_sma_200 = EXCLUDED.spy_sma_200,
            us_10y_yield = EXCLUDED.us_10y_yield,
            m2_money_supply = EXCLUDED.m2_money_supply;
    """)
    
    total_rows = conn.execute("SELECT COUNT(*) FROM macro_data").fetchone()[0]
    print(f"\\nFRED Macro ingestion complete! Total rows: {total_rows}")
    conn.close()

if __name__ == "__main__":
    fetch_and_store_macro_data()
