import yfinance as yf

tk = yf.Ticker("AAPL")
insider = tk.insider_transactions
print("Insider Transactions for AAPL:")
print(insider.head(10) if insider is not None else "None found")

purchases = tk.insider_purchases
print("\nInsider Purchases for AAPL:")
print(purchases if purchases is not None else "None found")
