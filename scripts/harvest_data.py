import pandas as pd
import numpy as np
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.run_backtest import run_backtest_logic
from engines.engine_a_alpha.learning.signal_gate import SignalGate

def harvest():
    """
    Run a simulation to collect (Features, Label) pairs for ML training.
    """
    print("[HARVEST] Starting Data Harvest...")
    
    # 1. Run Backtest with a specific flag or just capture logs?
    # Since run_backtest_logic is a bit opaque for row-level extraction, 
    # we might need to instantiate components manually or parse the trade logs + price data.
    
    # EASIER APPROACH: 
    # Use the 'AlphaEngine' debug traces? No, hard to parse.
    # Instantiate components here and run a "Silent" simulation that yields signals.
    
    # Lets repurpose run_backtest.py logic but keep the dataframe.
    # Actually, we can just run a normal backtest, and then Post-Process the trade logs!
    # Trade Log contains: Entry Time, Ticker, Direction, PnL.
    # We can join this with Market Data to get Features at Entry Time.
    
    # Step 1: Run Backtest (Optional if trades.csv exists)
    # summary = run_backtest_logic(
    #    override_start="2022-01-01",
    #    override_end="2024-01-01",
    #    fresh=True
    # )
    
    # Step 2: Load Trades
    if not (Path("data/trade_logs/trades.csv").exists()):
         print("[HARVEST] No trades.csv found. Running backtest...")
         run_backtest_logic(override_start="2022-01-01", override_end="2024-01-01", fresh=True)
         
    trades = pd.read_csv("data/trade_logs/trades.csv")
    if trades.empty:
        print("[HARVEST] No trades generated. Cannot train.")
        return
        
    print(f"[HARVEST] Analying {len(trades)} trades for training data...")
    
    # Step 3: Load Market Data
    from engines.data_manager.data_manager import DataManager
    dm = DataManager()
    tickers = trades["ticker"].unique()
    data_map = {}
    
    print(f"[HARVEST] Loading cached data for {len(tickers)} tickers...")
    for t in tickers:
        df = dm.load_cached(t, "1d")
        if df is not None and not df.empty:
            data_map[t] = df
        else:
            print(f"[HARVEST] Warn: No data found for {t}")

    dataset = []
    
    gate = SignalGate() # Helper for feature extraction
    
    for i, trade in trades.iterrows():
        t = trade["ticker"]
        entry_dt = pd.to_datetime(trade["timestamp"])
        
        if t not in data_map: continue
        df = data_map[t]
        
        # Get data UP TO entry time
        # We need exact index location
        try:
             # Find loc
             # Ensure index is datetime
             if not isinstance(df.index, pd.DatetimeIndex):
                 df.index = pd.to_datetime(df.index)
                 
             idx_loc_arr = df.index.get_indexer([entry_dt], method='pad')
             if idx_loc_arr[0] == -1: continue # Date before start of data
             
             idx_loc = idx_loc_arr[0]
             history = df.iloc[:idx_loc+1]
             
             # Extract Features
             # We use a dummy signal dict just to pass metadata if needed
             dummy_sig = {"ticker": t, "edge_id": "unknown"} 
             features = gate.extract_features(t, history, dummy_sig)
             
             if features is not None:
                 # Target: Did this trade make money?
                 label = 1 if trade["pnl"] > 0 else 0
                 
                 row = list(features[0]) + [label]
                 dataset.append(row)
                 
        except Exception as e:
            # print(f"Error processing {t} at {entry_dt}: {e}")
            pass

            
    # Save CSV
    cols = ["vol_20", "trend_dist", "mom_14", "target"]
    df_train = pd.DataFrame(dataset, columns=cols)
    df_train.to_csv("data/brain/training_data.csv", index=False)
    print(f"[HARVEST] Saved {len(df_train)} training samples to data/brain/training_data.csv")

if __name__ == "__main__":
    harvest()
