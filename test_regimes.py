import duckdb
import pandas as pd
import joblib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'quant_data.duckdb')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models', 'saved')
MAG_7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

features_cols = [
    'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
    'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
]

def test_regime(start_date, end_date, regime_name):
    conn = duckdb.connect(DB_PATH)
    df = conn.execute(f"SELECT * FROM features WHERE date >= '{start_date}' AND date <= '{end_date}' ORDER BY date ASC").df()
    conn.close()
    
    trade_history = []
    
    for ticker in MAG_7:
        ticker_df = df[df['ticker'] == ticker].copy()
        if ticker_df.empty: continue
            
        model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
        if not os.path.exists(model_path): continue
        model = joblib.load(model_path)
        
        X = ticker_df[features_cols].fillna(0)
        ticker_df['ai_prob'] = model.predict_proba(X)[:, 1]
        
        in_trade = False
        entry_price = 0
        take_profit = 0
        stop_loss = 0
        days_held = 0
        
        for idx, row in ticker_df.iterrows():
            date = row['date']
            close = row['close']
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
                new_theoretical_sl = close * (1 - (atr * 1.0))
                if new_theoretical_sl > stop_loss: stop_loss = new_theoretical_sl
                
                if close >= take_profit or close <= stop_loss or days_held >= 40:
                    profit_loss = close - entry_price
                    pl_percent = (profit_loss / entry_price) * 100
                    trade_history.append({'Return %': pl_percent})
                    in_trade = False

    if not trade_history:
        print(f"\n--- {regime_name} ({start_date} to {end_date}) ---")
        print("Total Trades: 0 (The AI successfully held cash and avoided the market entirely).")
        return
        
    results_df = pd.DataFrame(trade_history)
    total_trades = len(results_df)
    winning_trades = len(results_df[results_df['Return %'] > 0])
    win_rate = (winning_trades / total_trades) * 100
    avg_win = results_df[results_df['Return %'] > 0]['Return %'].mean() if winning_trades > 0 else 0
    avg_loss = results_df[results_df['Return %'] <= 0]['Return %'].mean() if winning_trades < total_trades else 0
    
    print(f"\n--- {regime_name} ({start_date} to {end_date}) ---")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {win_rate:.1f}%")
    print(f"Average Win:  +{avg_win:.2f}% | Average Loss: {avg_loss:.2f}%")

if __name__ == "__main__":
    # 2022 Brutal Bear Market (Inflation & Rate Hikes)
    test_regime("2022-01-01", "2022-12-31", "2022 Brutal Bear Market")
    
    # 2018 Sideways/Volatile Market
    test_regime("2018-01-01", "2018-12-31", "2018 Sideways & Volatile Market")
    
    # 2015 Sideways Market
    test_regime("2015-01-01", "2015-12-31", "2015 Sideways Market")
