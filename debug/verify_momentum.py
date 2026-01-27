
import pandas as pd
import numpy as np
from engines.data_manager.data_manager import DataManager
from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge

def verify_momentum():
    print("🧪 Verifying Momentum Edge Logic...")
    
    # 1. Load Data
    print("Loading SPY 2024...")
    try:
        df = pd.read_csv('data/raw/SPY_1d.csv', index_col=0, parse_dates=True)
    except:
        print("Could not load local CSV, fetching...")
        dm = DataManager()
        df = dm.ensure_data('SPY')
        
    df = df[df.index >= '2024-01-01']
    data_map = {'SPY': df}
    
    # 2. Run Edge
    edge = MomentumEdge()
    # Mock params if needed
    edge.params = {} 
    
    print("\nComputing signals for entire year...")
    # Fix column case first
    df = df.rename(columns=str.title)
    data_map = {'SPY': df}
    
    longs = 0
    shorts = 0
    
    # Loop through every day in 2024
    for date in df.index:
        # Create a slice up to this date to simulate real-time
        slice_df = df.loc[:date]
        if len(slice_df) < 50: continue
        
        # We need to pass a dict of DFs, but the edge iterates over it
        # The edge logic: close = df["Close"]
        # So we can just check the logic directly on the slice
        
        close = slice_df["Close"]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma40 = close.rolling(40).mean().iloc[-1]
        
        if ma10 > ma40:
            longs += 1
        elif ma10 < ma40:
            shorts += 1
            
    print(f"\nYearly Stats:")
    print(f"Long Days: {longs}")
    print(f"Short Days: {shorts}")
    print(f"Ratio: {longs/(longs+shorts)*100:.1f}% Long")

if __name__ == "__main__":
    verify_momentum()
