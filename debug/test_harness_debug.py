
import sys
import os
import json
import logging
from pathlib import Path

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.edge_harness import _run_single_bt
from debug_config import DEBUG_LEVELS

DEBUG_LEVELS["ALPHA"] = True
DEBUG_LEVELS["HARNESS"] = True

def main():
    print("running debug backtest...")
    
    # Minimal config
    bt_cfg = {
        "tickers": ["AAPL", "SPY"],
        "timeframe": "1d",
        "initial_capital": 100000,
        "cache_dir": "data/processed"
    }
    
    risk_cfg = {
        "max_risk_per_trade": 0.02,
        "stop_loss_atr": 2.0
    }
    
    # Create temp edge config
    edge_cfg_path = Path("debug/temp_edge_config.json")
    with open(edge_cfg_path, "w") as f:
        json.dump({
            "active_edges": ["rsi_bounce_v1"],
            "edge_params": {},
            "edge_weights": {}
        }, f)
        
    start = "2024-01-01"
    end = "2024-02-01"
    
    try:
        snaps, trades, stats = _run_single_bt(
            bt_cfg=bt_cfg,
            risk_cfg=risk_cfg,
            edge_cfg_path=edge_cfg_path,
            start=start,
            end=end,
            slippage_bps=5.0,
            commission=0.0,
            edge_name="rsi_bounce_v1"
        )
        
        print("\n--- RESULTS ---")
        print(f"Trades: {len(trades)}")
        print(stats)
        
    except Exception as e:
        print(f"CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
