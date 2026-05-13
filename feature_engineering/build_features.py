import duckdb
import os
import pandas as pd
import numpy as np

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')

def RSI(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.rolling(window=period).mean()
    roll_down = down.rolling(window=period).mean()
    rs = roll_up / roll_down
    rs.replace([np.inf, -np.inf], 100, inplace=True)
    return 100 - (100 / (1 + rs))

def ATR(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr / close # Normalized

def generate_features():
    print("Starting Advanced Feature Engineering Engine...")
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = duckdb.connect(DB_PATH)
    
    # HOLE FIXED: Create the features table schema properly with a Primary Key to allow UPSERT
    conn.execute("""
        CREATE TABLE IF NOT EXISTS features (
            ticker VARCHAR,
            date DATE,
            close DOUBLE,
            return_1d DOUBLE,
            return_5d DOUBLE,
            rsi_14 DOUBLE,
            sma_20_dist DOUBLE,
            sma_50_dist DOUBLE,
            volatility_20d DOUBLE,
            atr_percent DOUBLE,
            spy_close DOUBLE,
            spy_sma_200 DOUBLE,
            us_10y_yield DOUBLE,
            m2_money_supply DOUBLE,
            PRIMARY KEY (ticker, date)
        );
    """)
    
    # HOLE FIXED: Incremental Calculation check MUST be per-ticker to avoid breaking when adding new stocks
    query = """
        SELECT dp.* 
        FROM daily_prices dp
        LEFT JOIN (
            SELECT ticker, MAX(date) as max_date 
            FROM features 
            GROUP BY ticker
        ) f ON dp.ticker = f.ticker
        WHERE f.max_date IS NULL OR dp.date >= (f.max_date - INTERVAL 75 DAY)
        ORDER BY dp.ticker, dp.date
    """
        
    df = conn.execute(query).df()
    
    if df.empty:
        print("No new price data found for feature engineering.")
        conn.close()
        return

    features_list = []
    
    for ticker, group in df.groupby('ticker'):
        group = group.sort_values('date').copy()
        
        group['return_1d'] = group['close'].pct_change()
        group['return_5d'] = group['close'].pct_change(5)
        group['rsi_14'] = RSI(group['close'], 14)
        group['sma_20'] = group['close'].rolling(20).mean()
        group['sma_50'] = group['close'].rolling(50).mean()
        group['sma_20_dist'] = (group['close'] / group['sma_20']) - 1
        group['sma_50_dist'] = (group['close'] / group['sma_50']) - 1
        group['volatility_20d'] = group['return_1d'].rolling(20).std()
        group['atr_percent'] = ATR(group['high'], group['low'], group['close'], 14)
        
        # Drop the NaN rows caused by rolling windows
        group = group.dropna(subset=['sma_50_dist', 'volatility_20d', 'atr_percent'])
        features_list.append(group)
        
    final_features = pd.concat(features_list, ignore_index=True)
    
    # HOLE FIXED: The AI previously couldn't see the Macro data. Joining it into the training set.
    print("Joining Macro-Economic Data...")
    macro_df = conn.execute("SELECT * FROM macro_data").df()
    
    final_features['date'] = pd.to_datetime(final_features['date']).dt.date
    macro_df['date'] = pd.to_datetime(macro_df['date']).dt.date
    
    final_features = pd.merge(final_features, macro_df, on='date', how='left')
    
    # Forward fill macro data for trading days where macro data wasn't explicitly published
    final_features = final_features.sort_values(['ticker', 'date'])
    final_features[['spy_close', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply']] = final_features.groupby('ticker')[['spy_close', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply']].ffill()

    final_features = final_features.dropna(subset=['us_10y_yield'])
    
    columns_to_store = [
        'ticker', 'date', 'close', 'return_1d', 'return_5d', 
        'rsi_14', 'sma_20_dist', 'sma_50_dist', 'volatility_20d', 'atr_percent',
        'spy_close', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
    ]
    final_features = final_features[columns_to_store]
    
    print("Writing enriched features to DuckDB...")
    conn.execute("""
        INSERT INTO features 
        SELECT * FROM final_features
        ON CONFLICT (ticker, date) DO UPDATE SET
            close = EXCLUDED.close,
            return_1d = EXCLUDED.return_1d,
            return_5d = EXCLUDED.return_5d,
            rsi_14 = EXCLUDED.rsi_14,
            sma_20_dist = EXCLUDED.sma_20_dist,
            sma_50_dist = EXCLUDED.sma_50_dist,
            volatility_20d = EXCLUDED.volatility_20d,
            atr_percent = EXCLUDED.atr_percent,
            spy_close = EXCLUDED.spy_close,
            spy_sma_200 = EXCLUDED.spy_sma_200,
            us_10y_yield = EXCLUDED.us_10y_yield,
            m2_money_supply = EXCLUDED.m2_money_supply;
    """)
    
    total_rows = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    print(f"Feature engineering complete! Total rows in 'features' table: {total_rows}")
    conn.close()

if __name__ == "__main__":
    generate_features()
