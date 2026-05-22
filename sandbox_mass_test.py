import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from xgboost import XGBClassifier
warnings.filterwarnings('ignore')

NEW_TICKERS = [
    "ARM", "CDNS", "SNPS", "AMKR", "ASX", "RMBS", "SITM", "WDC", "STX", 
    "LITE", "COHR", "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", 
    "JBL", "FLEX", "TTMI", "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP"
]

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def apply_triple_barrier_labels(df, tp_multiplier=2.0, sl_multiplier=1.0, max_days=30):
    closes = df['close'].values
    atrs = df['atr_percent'].values
    targets = np.zeros(len(closes))
    
    for i in range(len(closes)):
        if pd.isna(atrs[i]) or i + max_days >= len(closes):
            targets[i] = np.nan
            continue
            
        entry_price = closes[i]
        tp_price = entry_price * (1 + (atrs[i] * tp_multiplier))
        sl_price = entry_price * (1 - (atrs[i] * sl_multiplier))
        
        target = 0
        for j in range(1, max_days + 1):
            future_price = closes[i+j]
            if future_price <= sl_price:
                target = 0
                break
            elif future_price >= tp_price:
                target = 1
                break
        targets[i] = target
        
    df['target'] = targets
    return df

def run_test():
    print("Downloading SPY reference data...")
    spy = yf.download("SPY", start="2014-01-01", progress=False)
    spy = spy.reset_index()
    spy.columns = [(c[0] if isinstance(c, tuple) else c).lower().replace(' ', '_') for c in spy.columns]
    if 'adj_close' in spy.columns:
        spy = spy.drop(columns=['adj_close'])
    spy['date'] = pd.to_datetime(spy['date']).dt.tz_localize(None)
    spy['spy_sma_200'] = spy['close'].rolling(200).mean()
    spy = spy[['date', 'close', 'spy_sma_200']].rename(columns={'close': 'spy_close'})
    
    # We will skip US_10Y and M2 to keep the test fast, but we'll include the standard tech features
    features_cols = ['return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 'volatility_20d', 'atr_percent', 'spy_sma_200']
    
    results = []
    
    for ticker in NEW_TICKERS:
        print(f"Testing {ticker}...", end=" ")
        try:
            df = yf.download(ticker, start="2014-01-01", progress=False)
            if df.empty:
                print("No data.")
                continue
                
            df = df.reset_index()
            df.columns = [(c[0] if isinstance(c, tuple) else c).lower().replace(' ', '_') for c in df.columns]
            if 'adj_close' in df.columns:
                df = df.drop(columns=['adj_close'])
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            
            # Features
            df['return_1d'] = df['close'].pct_change()
            df['return_5d'] = df['close'].pct_change(5)
            df['rsi_14'] = rsi(df['close'], 14)
            df['sma_20_dist'] = df['close'] / df['close'].rolling(20).mean() - 1
            df['sma_50_dist'] = df['close'] / df['close'].rolling(50).mean() - 1
            df['volatility_20d'] = df['return_1d'].rolling(20).std()
            
            df['high_low'] = df['high'] - df['low']
            df['high_close'] = np.abs(df['high'] - df['close'].shift())
            df['low_close'] = np.abs(df['low'] - df['close'].shift())
            df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
            df['atr_percent'] = (df['tr'].rolling(14).mean() / df['close'])
            
            # Merge SPY
            df = pd.merge(df, spy, on='date', how='left')
            
            df = apply_triple_barrier_labels(df)
            df = df.dropna(subset=['target'] + features_cols)
            
            train = df[df['date'] < pd.to_datetime('2023-01-01')]
            test = df[df['date'] >= pd.to_datetime('2023-01-01')]
            
            if len(train) < 100 or len(test) < 50:
                print("Not enough history.")
                continue
                
            X_train, y_train = train[features_cols], train['target']
            X_test, y_test = test[features_cols], test['target']
            
            model = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
            model.fit(X_train, y_train)
            
            preds = model.predict(X_test)
            accuracy = np.mean(preds == y_test)
            
            results.append({'Ticker': ticker, 'Accuracy': accuracy*100})
            print(f"Accuracy: {accuracy*100:.1f}%")
            
        except Exception as e:
            print(f"Error: {e}")
            
    print("\n================ SUMMARY ================")
    res_df = pd.DataFrame(results).sort_values('Accuracy', ascending=False)
    print(res_df.to_string(index=False))
    
    passed = res_df[res_df['Accuracy'] >= 60.0]
    print(f"\n{len(passed)} out of {len(results)} stocks passed the 60% accuracy threshold.")

if __name__ == "__main__":
    run_test()
