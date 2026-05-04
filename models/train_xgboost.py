import duckdb
import os
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
import joblib

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'quant_data.duckdb')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'saved')

if not os.path.exists(MODEL_DIR):
    os.makedirs(MODEL_DIR)

def apply_triple_barrier_labels(df, tp_multiplier=2.0, sl_multiplier=1.0, max_days=30):
    """
    Applies the Triple Barrier Method to generate targets.
    1 if Take Profit is hit before Stop Loss and within max_days.
    0 otherwise.
    """
    closes = df['close'].values
    atrs = df['atr_percent'].values
    targets = np.zeros(len(closes))
    
    # Using a simple forward scan for speed
    for i in range(len(closes)):
        if pd.isna(atrs[i]) or i + max_days >= len(closes):
            targets[i] = np.nan
            continue
            
        entry_price = closes[i]
        # Dynamic targets based on recent volatility
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

def train_models():
    print("Initializing AI Training Engine (Phase 3)...")
    conn = duckdb.connect(DB_PATH)
    
    df = conn.execute("SELECT * FROM features ORDER BY ticker, date").df()
    if df.empty:
        print("No features found.")
        return
        
    features_cols = [
        'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
        'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
    ]
    
    overall_accuracy = []
    
    for ticker, group in df.groupby('ticker'):
        print(f"Training XGBoost Model for {ticker}...")
        group = group.sort_values('date').copy()
        
        # 1. Generate Advanced Labels
        group = apply_triple_barrier_labels(group)
        group = group.dropna(subset=['target'] + features_cols)
        
        # 2. Train/Test Split (Walk-forward out of sample test)
        # Train on pre-2023, Test on 2023-2024
        train = group[pd.to_datetime(group['date']) < pd.to_datetime('2023-01-01')]
        test = group[pd.to_datetime(group['date']) >= pd.to_datetime('2023-01-01')]
        
        if train.empty or test.empty:
            print(f"Not enough data for {ticker}")
            continue
            
        X_train, y_train = train[features_cols], train['target']
        X_test, y_test = test[features_cols], test['target']
        
        # 3. Train
        model = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
        model.fit(X_train, y_train)
        
        # 4. Evaluate (Did we hit the 60% threshold?)
        preds = model.predict(X_test)
        accuracy = np.mean(preds == y_test)
        overall_accuracy.append(accuracy)
        
        print(f"   --> {ticker} Out-of-Sample Target Accuracy: {accuracy*100:.1f}%")
        
        # 5. Save the Model
        model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
        joblib.dump(model, model_path)
        
    print(f"\nAverage System Accuracy (Test Set 2023-2024): {np.mean(overall_accuracy)*100:.1f}%")
    print("All models successfully trained and saved to 'models/saved/'")
    conn.close()

if __name__ == "__main__":
    train_models()
