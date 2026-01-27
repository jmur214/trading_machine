
import yfinance as yf
import pandas as pd

def test_fetch():
    print("Fetching NVDA from yfinance...")
    df = yf.download("NVDA", start="2022-01-01", end="2024-12-31", progress=False)
    if not df.empty:
        print(f"Success! Fetched {len(df)} rows.")
        print(df.head())
    else:
        print("Failed to fetch data.")

if __name__ == "__main__":
    test_fetch()
