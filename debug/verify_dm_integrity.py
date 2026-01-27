
"""
Script to validate the DataManager's ability to fetch data.
This version acts as a regression test for ensuring 'fetch_all.py'
and underlying engine logic remains sound.
"""
import sys
import os
import pandas as pd
from datetime import datetime

# Path Hack
sys.path.append(os.getcwd())

from engines.data_manager.data_manager import DataManager

def verify():
    print("[VERIFY_DM] Starting DataManager Integrity Check...")
    dm = DataManager()
    
    # Test 1: Load Existing
    t = "AAPL"
    print(f"[VERIFY_DM] Test 1: Loading cached {t}...")
    df = dm.load_cached(t, "1d")
    if df is not None and not df.empty:
        print(f"[VERIFY_DM] PASS: Loaded {len(df)} rows for {t}. Last date: {df.index[-1]}")
    else:
        print(f"[VERIFY_DM] FAIL: Could not load {t}")
        
    # Test 2: Synthetic
    print(f"[VERIFY_DM] Test 2: Generating Synthetic Data...")
    df_synth = dm._fetch_synthetic("SYNTH-TEST", "2024-01-01", "2024-02-01")
    if not df_synth.empty:
        print(f"[VERIFY_DM] PASS: Generated {len(df_synth)} synthetic rows.")
    else:
        print(f"[VERIFY_DM] FAIL: Synthetic generation empty.")

if __name__ == "__main__":
    verify()
