import yfinance as yf
import pandas as pd

ticker = "AAPL"
tk = yf.Ticker(ticker)

# 1. Dark Pool Math Test
print("Testing Dark Pool Math...")
try:
    df = yf.download(ticker, period='5d', interval='5m', progress=False)
    if not df.empty:
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df['Vol_SMA'] = df['Volume'].rolling(20).mean()
        df['Price_Range_Pct'] = (df['High'] - df['Low']) / df['Close']
        
        # Look for spikes in the last day
        recent = df.tail(78) # ~1 day of 5m candles
        spikes = recent[(recent['Volume'] > recent['Vol_SMA'] * 4) & (recent['Price_Range_Pct'] < 0.005)]
        
        if not spikes.empty:
            for idx, row in spikes.iterrows():
                print(f"Dark Pool Block detected at {idx}: Vol {row['Volume']}, Price {row['Close']}")
        else:
            print("No dark pool blocks detected recently.")
except Exception as e:
    print(f"Error testing dark pool: {e}")

# 2. Options Flow Test
print("\nTesting Options Flow...")
try:
    exps = tk.options
    if exps:
        chain = tk.option_chain(exps[0])
        calls = chain.calls
        puts = chain.puts
        
        # Filter for unusual volume
        unusual_calls = calls[(calls['volume'] > calls['openInterest'] * 2) & (calls['volume'] > 500)]
        unusual_puts = puts[(puts['volume'] > puts['openInterest'] * 2) & (puts['volume'] > 500)]
        
        for _, row in unusual_calls.iterrows():
            print(f"🚨 UNUSUAL CALL: Strike ${row['strike']} | Vol: {row['volume']} | OI: {row['openInterest']}")
            
        for _, row in unusual_puts.iterrows():
            print(f"🚨 UNUSUAL PUT: Strike ${row['strike']} | Vol: {row['volume']} | OI: {row['openInterest']}")
except Exception as e:
    print(f"Error testing options flow: {e}")
