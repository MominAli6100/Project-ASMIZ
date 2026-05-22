import duckdb
import os
import pandas as pd

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns"
LOCAL_DB = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')

def migrate():
    print("Connecting to MotherDuck...")
    md_conn = duckdb.connect(f'md:?motherduck_token={TOKEN}')
    
    print("Connecting to Local DB and extracting data...")
    local_conn = duckdb.connect(LOCAL_DB, read_only=True)
    df_features = local_conn.execute("SELECT * FROM features").df()
    
    try:
        df_closed_trades = local_conn.execute("SELECT * FROM closed_trades").df()
    except Exception as e:
        print(f"Warning: closed_trades table might not exist or is empty. {e}")
        df_closed_trades = pd.DataFrame()
        
    local_conn.close()
    
    print(f"Extracted {len(df_features)} feature rows and {len(df_closed_trades)} closed trades.")
    
    print("Uploading to MotherDuck...")
    md_conn.execute("CREATE TABLE IF NOT EXISTS features AS SELECT * FROM df_features")
    # Replace the table if it exists so we overwrite with fresh local data
    md_conn.execute("CREATE OR REPLACE TABLE features AS SELECT * FROM df_features")
    
    if not df_closed_trades.empty:
        md_conn.execute("CREATE OR REPLACE TABLE closed_trades AS SELECT * FROM df_closed_trades")
    else:
        # Create empty table schema if needed
        md_conn.execute("""
            CREATE TABLE IF NOT EXISTS closed_trades (
                ticker VARCHAR, entry_date TIMESTAMP, exit_date TIMESTAMP,
                entry_price DOUBLE, exit_price DOUBLE, pl_percent DOUBLE,
                profit_loss DOUBLE
            )
        """)
        
    print("Migration Complete! Verifying...")
    res = md_conn.execute("SELECT COUNT(*) FROM features").fetchone()
    print(f"MotherDuck currently has {res[0]} rows in the features table.")
    md_conn.close()

if __name__ == "__main__":
    migrate()
