import yfinance as yf

current_tickers = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "ALAB", "AVGO", "MRVL", "AMD", "MU", "PLTR", "ASML", "TSM", "IREN", "CRWV", "CRDO", "TAN", "RKLB",
    "WLKP", "ECL", "LIN", "LXU", "CC",
    "SPY", "QQQ", "DIA", "XLF", "COST", "BRK-B"
}

requested = [
    "ARM", "CDNS", "SNPS", "TSM", "AMKR", "ASX", "MRVL", "ALAB", "CRDO", "RMBS", 
    "SITM", "SK Hynix", "Samsung Electronics", "MU", "WDC", "STX", "LITE", "COHR", 
    "FN", "APH", "GLW", "LUNA", "ANET", "CIEN", "CLS", "JBL", "FLEX", "TTMI", 
    "VICR", "VRT", "NVT", "PH", "WULF", "CIFR", "IPGP"
]

ticker_map = {
    "SK Hynix": "HXSCF", # OTC ticker for SK Hynix
    "Samsung Electronics": "SSNLF" # OTC ticker for Samsung
}

valid_new_tickers = []
for item in requested:
    ticker = ticker_map.get(item, item)
    if ticker in current_tickers:
        continue
    
    # Try fetching info
    t = yf.Ticker(ticker)
    hist = t.history(period="5d")
    if not hist.empty:
        valid_new_tickers.append(ticker)
    else:
        print(f"Invalid ticker or no data: {ticker} (Original: {item})")

print("VALID NEW TICKERS:", ",".join(valid_new_tickers))
