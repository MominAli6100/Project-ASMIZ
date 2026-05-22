import duckdb
import pandas as pd
import numpy as np
import joblib
import os
from datetime import datetime

DB_PATH = os.path.join('database', 'quant_data.duckdb')
MODEL_DIR = os.path.join('models', 'saved')

CRISIS_WINDOWS = [
    ("2018-10-01", "2018-12-31"), # US/China Trade War & Rate Tantrum
    ("2020-02-20", "2020-04-15"), # COVID-19 Global Crash
    ("2022-02-20", "2022-04-01"), # Russia Invades Ukraine
    ("2026-01-01", "2026-05-20")  # Current Iran/Hormuz Conflict
]

def is_in_crisis(date_val):
    for start, end in CRISIS_WINDOWS:
        if pd.to_datetime(start) <= date_val <= pd.to_datetime(end):
            return True
    return False

def simulate_triple_barrier(df, index, entry_price, atr_pct, max_days=40):
    tp_price = entry_price * (1 + (atr_pct * 2.0))
    sl_price = entry_price * (1 - (atr_pct * 1.0))
    
    for j in range(1, max_days + 1):
        if index + j >= len(df):
            break
        future_price = df.iloc[index + j]['close']
        
        if future_price <= sl_price:
            return (future_price - entry_price) / entry_price
        elif future_price >= tp_price:
            return (future_price - entry_price) / entry_price
            
    # Time barrier hit
    final_price = df.iloc[min(index + max_days, len(df)-1)]['close']
    return (final_price - entry_price) / entry_price

def run_backtest():
    print("Loading data from DuckDB...")
    conn = duckdb.connect(DB_PATH, read_only=True)
    df_all = conn.execute("SELECT * FROM features ORDER BY ticker, date").df()
    conn.close()
    
    features_cols = ['return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply']

    
    all_trades = []
    
    tickers = df_all['ticker'].unique()
    for ticker in tickers:
        model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
        if not os.path.exists(model_path): continue
            
        try:
            model = joblib.load(model_path)
        except:
            continue
            
        ticker_df = df_all[df_all['ticker'] == ticker].copy()
        ticker_df = ticker_df.dropna(subset=features_cols).reset_index(drop=True)
        if ticker_df.empty: continue
            
        X = ticker_df[features_cols]
        # Get AI buy signals (Prob > 55%)
        probs = model.predict_proba(X)[:, 1]
        
        for i in range(len(ticker_df)):
            if probs[i] > 0.55:
                row = ticker_df.iloc[i]
                
                # Check Macro Safe (200-DMA rule - basic AI filter)
                if row['spy_close'] < row['spy_sma_200']:
                    continue
                    
                entry_date = pd.to_datetime(row['date'])
                entry_price = row['close']
                atr_pct = row['atr_percent']
                
                trade_return = simulate_triple_barrier(ticker_df, i, entry_price, atr_pct)
                
                all_trades.append({
                    'ticker': ticker,
                    'entry_date': entry_date,
                    'return': trade_return,
                    'in_crisis': is_in_crisis(entry_date)
                })

    df_trades = pd.DataFrame(all_trades)
    
    # Portfolio A: Standard AI (Takes all trades)
    p_a = df_trades.copy()
    
    # Portfolio B: Kill Switch (Rejects trades during crises)
    p_b = df_trades[df_trades['in_crisis'] == False].copy()
    
    # Crisis Trades (The trades the Kill Switch saved us from)
    crisis_trades = df_trades[df_trades['in_crisis'] == True].copy()
    
    def print_metrics(name, subset):
        wins = len(subset[subset['return'] > 0])
        total = len(subset)
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = subset['return'].mean() * 100 if total > 0 else 0
        print(f"\\n[{name}]")
        print(f"  Total Trades Taken: {total}")
        print(f"  Win Rate:           {win_rate:.1f}%")
        print(f"  Average Return/Trade: {avg_ret:.2f}%")
        
    print_metrics("Portfolio A (Standard AI without Kill Switch)", p_a)
    print_metrics("Portfolio B (Advanced AI WITH Geopolitical Kill Switch)", p_b)
    print_metrics("Global Crisis Window Performance (All Avoided Trades)", crisis_trades)
    
    print("\n=======================================================")
    print("        DEEP DIVE: EVENT-BY-EVENT BREAKDOWN            ")
    print("=======================================================\n")
    
    event_names = [
        "Q4 2018 (Trade War & Rate Tantrum)",
        "Feb-April 2020 (COVID-19 Crash)",
        "Feb-April 2022 (Russia/Ukraine)",
        "Jan-May 2026 (Current Hormuz Conflict)"
    ]
    
    for i, (start, end) in enumerate(CRISIS_WINDOWS):
        start_dt, end_dt = pd.to_datetime(start), pd.to_datetime(end)
        event_trades = df_trades[(df_trades['entry_date'] >= start_dt) & (df_trades['entry_date'] <= end_dt)]
        
        total = len(event_trades)
        wins = len(event_trades[event_trades['return'] > 0])
        win_rate = (wins / total * 100) if total > 0 else 0
        avg_ret = event_trades['return'].mean() * 100 if total > 0 else 0
        
        # Calculate hypotetical dollar impact (assuming $1000 per trade)
        capital_risked = total * 1000
        net_pl_dollars = sum(event_trades['return'] * 1000)
        
        print(f"--- EVENT {i+1}: {event_names[i]} ---")
        print(f"Dates: {start} to {end}")
        if total == 0:
            print("  No trades triggered during this window.")
        else:
            print(f"  [Standard AI (Portfolio A) Performance]")
            print(f"    Trades Taken:  {total}")
            print(f"    Win Rate:      {win_rate:.1f}%")
            print(f"    Avg Return:    {avg_ret:.2f}%")
            print(f"    Net P&L ($1k/trade): ${net_pl_dollars:.2f}")
            print(f"  [Kill Switch AI (Portfolio B) Action]")
            print(f"    Trades Taken:  0 (Kill Switch Armed)")
            print(f"    Capital Saved from Risk: ${capital_risked:,.0f}")
            if net_pl_dollars < 0:
                print(f"    IMPACT: Saved portfolio from a ${abs(net_pl_dollars):.2f} loss.")
            else:
                print(f"    IMPACT: Missed a ${net_pl_dollars:.2f} gain (False Positive / V-Shape Recovery).")
        print()
    
if __name__ == '__main__':
    run_backtest()
