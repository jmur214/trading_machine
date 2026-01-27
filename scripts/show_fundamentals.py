from engines.data_manager.data_manager import DataManager
import pandas as pd

def show_data():
    dm = DataManager()
    ticker = "AAPL"
    print(f"\n--- Fetching Integrated History for {ticker} ---")
    
    df = dm.fetch_historical_fundamentals(ticker)
    
    if df.empty:
        print("No data found.")
        return

    print(f"\n[DataFrame Info] Shape: {df.shape}")
    print(f"Date Range: {df.index.min().date()} to {df.index.max().date()}")
    
    # Columns to show
    cols = [c for c in ["PE_Ratio", "PS_Ratio", "PB_Ratio", "Debt_to_Equity"] if c in df.columns]
    
    print("\n[Ratios Only]:")
    print(df[cols].tail(5))

if __name__ == "__main__":
    show_data()
