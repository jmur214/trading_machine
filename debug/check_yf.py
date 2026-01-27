
import yfinance as yf
print("Testing YFinance...")
df = yf.download("AAPL", period="1mo", progress=False)
print("AAPL Data:")
print(df.head())
print("Columns:", df.columns)
if df.empty:
    print("FAIL: Empty dataframe")
else:
    print("SUCCESS")
