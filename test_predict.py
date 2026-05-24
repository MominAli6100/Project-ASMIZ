import duckdb
import joblib
import os
import traceback

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'quant_data.duckdb')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models', 'saved')

def test():
    conn = duckdb.connect(f'md:?motherduck_token={os.environ.get("MOTHERDUCK_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vbWluYWxpMDVAZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6Im1vbWluYWxpMDUuZ21haWwuY29tIiwicGF0IjoibGRwVDBFR2Y4RXFjQjNjWGF0Uko5YXNNYkVwT0hiMXBTNmpiMFdUTzB2ayIsInVzZXJJZCI6IjcxYWRlNjBmLTI2ZDctNGE1MS1iMzkwLTVhYzEzMjUxYjcwYiIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3OTQ2ODI0MX0.6AveIjL-8OfXm3t0Ygfe9QT2d9z2bszjPWLuILI2fns")}')
    
    query = "SELECT * FROM features WHERE date = (SELECT MAX(date) FROM features) ORDER BY ticker"
    df_latest = conn.execute(query).df()
    
    features_cols = [
        'return_1d', 'return_5d', 'rsi_14', 'sma_20_dist', 'sma_50_dist', 
        'volatility_20d', 'atr_percent', 'spy_sma_200', 'us_10y_yield', 'm2_money_supply'
    ]
    
    tickers_to_test = ['NFLX', 'ROKU', 'COIN', 'AAPL', 'MSFT']
    
    for ticker in tickers_to_test:
        ticker_data = df_latest[df_latest['ticker'] == ticker]
        if ticker_data.empty:
            print(f"{ticker}: No latest data found!")
            continue
            
        X_pred = ticker_data[features_cols]
        print(f"--- {ticker} Features ---")
        print(X_pred)
        
        model_path = os.path.join(MODEL_DIR, f"{ticker}_xgb.joblib")
        if not os.path.exists(model_path):
            print(f"{ticker}: No model found at {model_path}")
            continue
            
        try:
            model = joblib.load(model_path)
            prob = model.predict_proba(X_pred)
            print(f"{ticker} raw predict_proba: {prob}")
            if prob.shape[1] > 1:
                ai_prob = prob[0][1] * 100
                print(f"{ticker} AI Prob: {ai_prob}%")
            else:
                print(f"{ticker} only has 1 class in predict_proba!")
        except Exception as e:
            print(f"{ticker} Exception: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    test()
