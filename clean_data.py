import pandas as pd
import json
import os
import shutil

# Paths
ROOT = "/Users/jacksonmurphy/Dev/trading_machine-2"

# File List to Clean (Expanded)
FILES_TO_CLEAN = [
    {"path": f"{ROOT}/data/trade_logs/trades.csv", "type": "csv"},
    {"path": f"{ROOT}/data/trade_logs/portfolio_snapshots.csv", "type": "csv"},
    {"path": f"{ROOT}/data/governor/allocation.json", "type": "json_dict"},
    {"path": f"{ROOT}/data/governor/system_state.json", "type": "json_dict"},
    {"path": f"{ROOT}/data/trade_logs/performance_summary.json", "type": "json_dict"},
    {"path": f"{ROOT}/data/governor/edge_weights.json", "type": "json_weights"},
    {"path": f"{ROOT}/data/governor/edge_weights_history.csv", "type": "csv"},
    {"path": f"{ROOT}/data/research/edge_results.json", "type": "json_list"},
    {"path": f"{ROOT}/data/research/edge_results.parquet", "type": "parquet"},
    {"path": f"{ROOT}/data/governor/genome_registry.json", "type": "json_dict"},
    # Also check for positions.csv if it exists in expected locations (usually not static but let's check common spots)
    # The user didn't have one in data/trade_logs, but I should check if DataManager stores it elsewhere or generates it on the fly.
    # DataManager logic suggests it might use trades to calc positions but if there's a file, we clean it.
]

print("Starting COMPREHENSIVE data cleanup...")

for file_info in FILES_TO_CLEAN:
    fpath = file_info["path"]
    ftype = file_info["type"]
    
    if os.path.exists(fpath):
        print(f"Cleaning {fpath}...")
        try:
            # Backup
            shutil.copy(fpath, fpath + ".bak")
            
            if ftype == "csv":
                # Keep header only
                try:
                    with open(fpath, "r") as f:
                        header = f.readline().strip()
                except Exception:
                    header = ""
                with open(fpath, "w") as f:
                    if header:
                        f.write(header + "\n")
                print(f"  - Reset CSV (header preserved)")
                
            elif ftype == "json_dict":
                # Empty dict
                with open(fpath, "w") as f:
                    f.write("{}")
                print(f"  - Reset JSON to {{}}")
            
            elif ftype == "json_list":
                # Empty list
                with open(fpath, "w") as f:
                    f.write("[]")
                print(f"  - Reset JSON to []")
                
            elif ftype == "json_weights":
                 # Weights dict
                with open(fpath, "w") as f:
                    f.write('{"weights": {}}')
                print(f"  - Reset JSON to {{'weights': {{}}}}")

            elif ftype == "parquet":
                 # Delete parquet file (pandas can recreate or handle missing)
                os.remove(fpath)
                print(f"  - Deleted Parquet file")

        except Exception as e:
            print(f"  - Error cleaning {fpath}: {e}")
    else:
        print(f"Skipping {fpath} (not found)")

print("Comprehensive cleanup complete.")
