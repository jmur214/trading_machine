
import sys
import os
import pandas as pd
from engines.data_manager.data_manager import DataManager

def reproduce():
    dm = DataManager()
    ticker = "AAPL"
    print(f"Fetching fundamentals for {ticker}...")
    try:
        df = dm.fetch_historical_fundamentals(ticker)
        if df.empty:
            print("FAILURE: Returned empty DataFrame")
        else:
            print("SUCCESS:")
            print(df.head()) # Head shows start (2023)
            if "2023" in str(df.index[0]):
                print("VERIFIED: 2023 data present (Static Load successful)")
            else:
                print("WARNING: Data start date mismatch (likely still pulling yfinance?)")
    except Exception as e:
        print(f"CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reproduce()
