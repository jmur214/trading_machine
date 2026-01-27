import yfinance as yf
import pandas as pd

def check_history():
    ticker = "AAPL"
    t = yf.Ticker(ticker)
    
    print(f"--- Fetching Historical Financials for {ticker} ---")
    
    # Quarterly Income Statement (Revenue, Net Income)
    q_income = t.quarterly_income_stmt
    print("\n[Quarterly Income Stmt Head]:")
    print(q_income.iloc[:, :2] if not q_income.empty else "Empty")
    
    # Quarterly Balance Sheet (Total Assets, Debt)
    q_balance = t.quarterly_balance_sheet
    print("\n[Quarterly Balance Sheet Head]:")
    print(q_balance.iloc[:, :2] if not q_balance.empty else "Empty")
    
    # Check simple history
    hist = t.history(period="2y")
    print(f"\n[Price History]: {len(hist)} rows")
    
    if not q_income.empty:
        # P/E Reconstruction Test
        # Get 'Net Income' row
        try:
            # Row names can vary, usually "Net Income"
            net_income_row = q_income.loc["Net Income"] 
            print("\n[Net Income History]:")
            print(net_income_row)
            
            # We need shares outstanding to get EPS
            # yfinance shares data is often static or messy in history, 
            # but we can try 'Basic Average Shares' from income stmt
            shares_row = q_income.loc["Basic Average Shares"]
            print("\n[Shares History]:")
            print(shares_row)
            
        except KeyError as e:
            print(f"\nKeyError finding rows: {e}")
            print("Available rows:", q_income.index.tolist())

if __name__ == "__main__":
    check_history()
