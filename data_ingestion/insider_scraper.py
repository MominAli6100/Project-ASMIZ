import yfinance as yf
import duckdb
import os
import pandas as pd
from datetime import datetime

# Path to the duckdb database
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')

ALL_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", # Mag 7
    "ALAB", "AVGO", "MRVL", "AMD", "MU", "PLTR", "ASML", "TSM", "IREN", "CRWV", "CRDO", "TAN", "RKLB", # High Growth Tech
    "WLKP", "ECL", "LIN", "LXU", "CC", # Chemical/Industrial
    "ARM", "CDNS", "SNPS", "AMKR", "ASX", "RMBS", "SITM", "WDC", "STX", "LITE", "COHR", "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", "JBL", "FLEX", "TTMI", "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP", # Advanced Semiconductors & Networking
    "CRM", "NOW", "PANW", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ADBE", "INTU", "UBER", "ABNB", "SMCI", "SHOP", "MELI", "SPOT", "NFLX", "ROKU", "COIN", "HOOD", # High-Momentum Growth
    "SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B" # Standard Market ETFs & Blue Chips
]

def fetch_insider_data():
    print("Starting Insider Trading Data Ingestion...")
    
    conn = duckdb.connect(f'md:?motherduck_token={os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")}')
    
    # Create the table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS insider_trades (
            ticker VARCHAR,
            fetch_date DATE,
            net_shares_purchased_6m DOUBLE,
            total_insider_shares_held DOUBLE,
            recent_buy_transactions INT,
            recent_sell_transactions INT
        )
    """)
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Delete today's data so we can re-run idempotently
    conn.execute(f"DELETE FROM insider_trades WHERE fetch_date = '{today}'")
    
    for ticker in ALL_TICKERS:
        try:
            tk = yf.Ticker(ticker)
            purchases = tk.insider_purchases
            
            if purchases is not None and not purchases.empty:
                # yfinance returns a dataframe with rows like 'Purchases', 'Sales', 'Net Shares Purchased (Sold)'
                # The columns are usually ['Insider Purchases Last 6m', 'Shares', 'Trans']
                
                # Default values
                net_shares = 0.0
                total_held = 0.0
                buys = 0
                sells = 0
                
                # Parse the DF safely
                for _, row in purchases.iterrows():
                    metric = str(row.iloc[0]).lower()
                    shares = float(row.iloc[1]) if pd.notna(row.iloc[1]) else 0.0
                    trans = int(row.iloc[2]) if pd.notna(row.iloc[2]) else 0
                    
                    if 'net shares purchased' in metric:
                        net_shares = shares
                    elif 'total insider shares' in metric:
                        total_held = shares
                    elif 'purchases' == metric:
                        buys = trans
                    elif 'sales' == metric:
                        sells = trans
                        
                conn.execute(f"""
                    INSERT INTO insider_trades VALUES (
                        '{ticker}', '{today}', {net_shares}, {total_held}, {buys}, {sells}
                    )
                """)
                print(f"[{ticker}] Recorded {buys} buys, {sells} sells. Net: {net_shares}")
            else:
                print(f"[{ticker}] No insider data found.")
                
        except Exception as e:
            print(f"Error fetching insider data for {ticker}: {e}")

    conn.close()
    print("Insider Tracking Sync Complete.")

if __name__ == "__main__":
    fetch_insider_data()
