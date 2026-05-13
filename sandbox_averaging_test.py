import yfinance as yf
import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime
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
    return atr / close 

NEW_TICKERS = ["SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B"]
features_cols = ['return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 'volatility_20d', 'atr_percent', 'spy_sma_200', 'spy_close']

REGIMES = {
    "2018 Sideways/Volatile": ("2018-01-01", "2018-12-31"),
    "2020-2021 Bull Market": ("2020-01-01", "2021-12-31"),
    "2022 Tech Bear Market": ("2022-01-01", "2022-12-31")
}

def build_sandbox_features(ticker, spy_df):
    try:
        df = yf.download(ticker, period="10y", interval="1d", progress=False)
        if df.empty or len(df) < 100: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        
        df['return_1d'] = df['Close'].pct_change()
        df['return_5d'] = df['Close'].pct_change(5)
        df['rsi_14'] = RSI(df['Close'], 14)
        df['sma_20_dist'] = (df['Close'] - df['Close'].rolling(20).mean()) / df['Close'].rolling(20).mean()
        df['sma_50_dist'] = (df['Close'] - df['Close'].rolling(50).mean()) / df['Close'].rolling(50).mean()
        df['volatility_20d'] = df['return_1d'].rolling(20).std() * np.sqrt(252)
        df['atr_percent'] = ATR(df['High'], df['Low'], df['Close'], 14)
        
        df = df.reset_index()
        df['date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
        df = pd.merge(df, spy_df, on='date', how='left').ffill().dropna()
        
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
        return pd.DataFrame()

def run_regime_test():
    spy = yf.download("SPY", period="10y", interval="1d", progress=False)
    if isinstance(spy.columns, pd.MultiIndex): spy.columns = spy.columns.get_level_values(0)
    spy = spy.reset_index()
    spy['date'] = pd.to_datetime(spy['Date']).dt.tz_localize(None)
    spy['spy_close'] = spy['Close']
    spy['spy_sma_200'] = spy['Close'].rolling(200).mean()
    spy = spy[['date', 'spy_close', 'spy_sma_200']]
    
    all_trades = {regime: [] for regime in REGIMES.keys()}
    
    for ticker in NEW_TICKERS:
        df = build_sandbox_features(ticker, spy)
        if df.empty: continue
            
        X = df[features_cols]
        y = df['target']
        model = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
        model.fit(X, y)
        df['ai_prob'] = model.predict_proba(X)[:, 1]
        
        for regime_name, (start_date, end_date) in REGIMES.items():
            mask = (df['date'] >= start_date) & (df['date'] <= end_date)
            regime_df = df.loc[mask]
            
            in_trade = False
            shares_owned = 0
            total_invested = 0
            avg_entry_price = 0
            
            take_profit = 0
            stop_loss = 0
            days_held = 0
            
            for idx, row in regime_df.iterrows():
                close = row['Close']
                atr = row['atr_percent']
                prob = row['ai_prob']
                macro_safe = row['spy_close'] > row['spy_sma_200']
                
                is_buy_signal = macro_safe and prob > 0.55
                
                # 1. EVALUATE BUYS / AVERAGING DOWN
                if is_buy_signal:
                    if not in_trade:
                        # Initial Buy
                        in_trade = True
                        shares_owned = 1.0
                        total_invested = close
                        avg_entry_price = close
                        take_profit = close * (1 + (atr * 2.0))
                        stop_loss = close * (1 - (atr * 1.0))
                        days_held = 0
                    else:
                        # AVERAGING DOWN (Pyramiding): We already own it, but a NEW buy signal fired.
                        # Do not average down if the signal fired consecutively within 3 days to avoid spam buying.
                        if days_held > 3:
                            shares_owned += 1.0
                            total_invested += close
                            avg_entry_price = total_invested / shares_owned
                            
                            # RESET AI TARGETS TO THE NEW SETUP
                            take_profit = close * (1 + (atr * 2.0))
                            stop_loss = close * (1 - (atr * 1.0))
                            days_held = 0 # Reset the 40-day time barrier since it's a new setup
                            
                # 2. EVALUATE HOLDS AND SELLS
                if in_trade:
                    days_held += 1
                    
                    # Trailing Stop-Loss Ratchet
                    new_sl = close * (1 - (atr * 1.0))
                    if new_sl > stop_loss: stop_loss = new_sl
                    
                    # Check Triggers (TP, SL, or Time Barrier)
                    if close >= take_profit or close <= stop_loss or days_held >= 40:
                        pl_percent = ((close - avg_entry_price) / avg_entry_price) * 100
                        all_trades[regime_name].append({'Ticker': ticker, 'Return %': pl_percent})
                        # Reset
                        in_trade = False
                        shares_owned = 0
                        total_invested = 0
                        avg_entry_price = 0

    for regime_name in REGIMES.keys():
        trades = all_trades[regime_name]
        print(f"\n[{regime_name}] AVERAGING DOWN PROTOCOL")
        if not trades:
            print("  -> ZERO TRADES")
        else:
            results_df = pd.DataFrame(trades)
            total_trades = len(results_df)
            wins = len(results_df[results_df['Return %'] > 0])
            losses = total_trades - wins
            win_rate = (wins / total_trades) * 100
            avg_win = results_df[results_df['Return %'] > 0]['Return %'].mean() if wins > 0 else 0
            avg_loss = results_df[results_df['Return %'] <= 0]['Return %'].mean() if losses > 0 else 0
            print(f"  Total Trades: {total_trades}")
            print(f"  Win Rate:     {win_rate:.1f}% ({wins}W / {losses}L)")
            print(f"  Avg Win:      +{avg_win:.2f}%")
            print(f"  Avg Loss:     {avg_loss:.2f}%")

if __name__ == "__main__":
    run_regime_test()
