import duckdb
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'quant_data.duckdb')

def initialize_database():
    """Initializes the local DuckDB database with the required tables."""
    print(f"Connecting to DuckDB at {DB_PATH}")
    conn = duckdb.connect(DB_PATH)
    
    # Create the core Daily Prices table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker VARCHAR,
            date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            PRIMARY KEY (ticker, date)
        );
    """)
    
    # Create Macro Data table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_data (
            date DATE PRIMARY KEY,
            spy_close DOUBLE,
            spy_sma_200 DOUBLE,
            us_10y_yield DOUBLE,
            m2_money_supply DOUBLE
        );
    """)
    
    print("Database initialized successfully.")
    conn.close()

if __name__ == "__main__":
    initialize_database()
