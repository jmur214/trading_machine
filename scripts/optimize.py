
import sys
import os
from pathlib import Path
import itertools
import pandas as pd
import numpy as np
from datetime import datetime

# Adjust path to allow import
sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.run_backtest import run_backtest_logic

def _safe_float(val, default=-999.0):
    if val is None: return default
    try: return float(val)
    except: return default


from engines.engine_a_alpha.edge_registry import EdgeRegistry

def main():
    print("--- 🧬 EVOLUTIONARY SELECTOR (DARWIN) ---")
    
    # 1. Load Candidates
    registry = EdgeRegistry()
    candidates = registry.list(status="candidate")
    
    if not candidates:
        print("[DARWIN] No 'candidate' edges found. Run discovery engine first!")
        print("Hint: python -m engines.engine_d_research.discovery")
        return

    print(f"[DARWIN] Found {len(candidates)} candidates awaiting validation.")
    
    # Validation Config
    TRAIN_START = "2023-01-01"
    TRAIN_END   = "2023-12-31" 
    MIN_SHARPE  = 0.5  # Low bar for demo purposes
    
    results = []
    
    for i, candidate in enumerate(candidates):
        print(f"\n[DARWIN] 🧪 Testing Candidate {i+1}/{len(candidates)}: {candidate.edge_id}")
        
        # Build override params
        # The EdgeRegistry stores candidates with their proposed params.
        # We need to pass them to run_backtest_logic.
        override_params = {
            candidate.edge_id: candidate.params
        }
        
        try:
            stats = run_backtest_logic(
                env="prod", 
                mode="prod",  # Use prod data
                fresh=True,
                no_governor=True, # Isolation mode
                alpha_debug=False,
                override_start=TRAIN_START,
                override_end=TRAIN_END,
                override_params=override_params,
                exact_edge_ids=[candidate.edge_id] # ISOLATION MODE
            )
            
            sharpe = _safe_float(stats.get("Sharpe Ratio"), -9.9)
            profit = _safe_float(stats.get("Net Profit"), 0.0)
            
            print(f"   >>> Result: Sharpe={sharpe:.2f}, Profit=${profit:.2f}")
            
            # Decision Logic
            if sharpe >= MIN_SHARPE and profit > 0:
                print(f"   >>> ✅ CANDIDATE PASSED! Promoting to 'active'.")
                registry.set_status(candidate.edge_id, "active")
                results.append((candidate.edge_id, "promoted", sharpe))
            else:
                print(f"   >>> ❌ Candidate Failed. Archiving.")
                registry.set_status(candidate.edge_id, "archived")
                results.append((candidate.edge_id, "archived", sharpe))
                
        except Exception as e:
            print(f"   >>> ⚠️ CRASH: {e}")
            
    print("\n" + "="*50)
    print(f"[DARWIN] SELECTION COMPLETE.")
    print(f"Processed: {len(results)}")
    for r in results:
        icon = "✅" if r[1] == "promoted" else "💀"
        print(f"{icon} {r[0]}: {r[1]} (Sharpe: {r[2]:.2f})")
    print("="*50)

if __name__ == "__main__":
    main()
