import yfinance as yf
import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

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

NEW_TICKERS = ["ARM", "CDNS", "SNPS", "AMKR", "ASX", "RMBS", "SITM", "005930.KS", "000660.KS", "WDC", "STX", "LITE", "COHR", "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", "JBL", "FLEX", "TTMI", "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP"]

features_cols = [
    'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
    'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
]

def build_sandbox_features(ticker, spy_df):
    try:
        df = yf.download(ticker, period="10y", interval="1d", progress=False)
        if df.empty or len(df) < 100: return pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.dropna()
        
        # Technicals
        df['return_1d'] = df['Close'].pct_change()
        df['return_5d'] = df['Close'].pct_change(5)
        df['rsi_14'] = RSI(df['Close'], 14)
        df['sma_20_dist'] = (df['Close'] - df['Close'].rolling(20).mean()) / df['Close'].rolling(20).mean()
        df['sma_50_dist'] = (df['Close'] - df['Close'].rolling(50).mean()) / df['Close'].rolling(50).mean()
        df['volatility_20d'] = df['return_1d'].rolling(20).std() * np.sqrt(252)
        df['atr_percent'] = ATR(df['High'], df['Low'], df['Close'], 14)
        
        df = df.reset_index()
        df['date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
        
        # Merge SPY macro
        df = pd.merge(df, spy_df, on='date', how='left').ffill().dropna()
        
        # Triple Barrier Labels
        labels = []
        for i in range(len(df)):
            if i + 40 >= len(df):
                labels.append(0)
                continue
                
            entry_price = df.iloc[i]['Close']
            atr = df.iloc[i]['atr_percent']
            tp = entry_price * (1 + (atr * 2.0))
            sl = entry_price * (1 - (atr * 1.0))
            
            future_window = df.iloc[i+1 : i+41]
            label = 0
            for _, row in future_window.iterrows():
                if row['High'] >= tp:
                    label = 1
                    break
                elif row['Low'] <= sl:
                    label = 0
                    break
            labels.append(label)
            
        df['target'] = labels
        return df
    except Exception as e:
        print(f"Failed extracting {ticker}: {e}")
        return pd.DataFrame()

def run_sandbox():
    print("="*60)
    print("--- ISOLATED AI SANDBOX: TESTING NEW STOCK UNIVERSE ---")
    print("="*60)
    
    # 1. Get Macro Data (SPY)
    print("Downloading S&P 500 Macro Data...")
    spy = yf.download("SPY", period="10y", interval="1d", progress=False)
    if isinstance(spy.columns, pd.MultiIndex): spy.columns = spy.columns.get_level_values(0)
    spy = spy.reset_index()
    spy['date'] = pd.to_datetime(spy['Date']).dt.tz_localize(None)
    spy['spy_close'] = spy['Close']
    spy['spy_sma_200'] = spy['Close'].rolling(200).mean()
    spy = spy[['date', 'spy_close', 'spy_sma_200']]
    
    # Dummy mock for Treasury and M2 (to fit existing feature shape)
    spy['us_10y_yield'] = 4.0
    spy['m2_money_supply'] = 20000.0
    
    trade_history = []
    
    for ticker in NEW_TICKERS:
        print(f"\nAnalyzing {ticker}...")
        df = build_sandbox_features(ticker, spy)
        if df.empty:
            print(f"--> SKIPPING {ticker}: Not enough historical data (likely a very recent IPO like CRWV).")
            continue
            
        # 2. Train XGBoost
        X = df[features_cols]
        y = df['target']
        model = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
        model.fit(X, y)
        df['ai_prob'] = model.predict_proba(X)[:, 1]
        
        # 3. Run Walk-Forward Backtest
        in_trade = False
        entry_price = 0
        take_profit = 0
        stop_loss = 0
        days_held = 0
        
        for idx, row in df.iterrows():
            close = row['Close']
            atr = row['atr_percent']
            prob = row['ai_prob']
            macro_safe = row['spy_close'] > row['spy_sma_200']
            
            if not in_trade:
                if macro_safe and prob > 0.55:
                    in_trade = True
                    entry_price = close
                    take_profit = entry_price * (1 + (atr * 2.0))
                    stop_loss = entry_price * (1 - (atr * 1.0))
                    days_held = 0
            else:
                days_held += 1
                new_sl = close * (1 - (atr * 1.0))
                if new_sl > stop_loss: stop_loss = new_sl
                
                if close >= take_profit or close <= stop_loss or days_held >= 40:
                    pl_percent = ((close - entry_price) / entry_price) * 100
                    trade_history.append({'Ticker': ticker, 'Return %': pl_percent})
                    in_trade = False

    # Aggregate Results
    if not trade_history:
        print("\nNo trades executed. Market conditions never met strict criteria.")
        return
        
    results_df = pd.DataFrame(trade_history)
    total_trades = len(results_df)
    wins = len(results_df[results_df['Return %'] > 0])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100
    
    avg_win = results_df[results_df['Return %'] > 0]['Return %'].mean() if wins > 0 else 0
    avg_loss = results_df[results_df['Return %'] <= 0]['Return %'].mean() if losses > 0 else 0
    
    print("\n" + "="*50)
    print("--- EXPERIMENTAL PORTFOLIO BACKTEST RESULTS ---")
    print("="*50)
    print(f"Total Trades Executed: {total_trades}")
    print(f"Overall Win Rate:      {win_rate:.1f}% ({wins}W / {losses}L)")
    print(f"Average Winning Trade: +{avg_win:.2f}%")
    print(f"Average Losing Trade:  {avg_loss:.2f}%")
    print("="*50)

if __name__ == "__main__":
    run_sandbox()
