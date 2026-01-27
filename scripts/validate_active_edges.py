
import sys
import os
import json
import pandas as pd
import subprocess
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.engine_d_research.regime_detector import RegimeDetector

def main():
    print("==================================================")
    print("   ACTIVE STRATEGY VALIDATION REPORT")
    print("==================================================")
    
    # 1. Load Active Edges
    active_edges = []
    try:
        import yaml
        with open("data/governor/edges.yml", "r") as f:
            data = yaml.safe_load(f)
            active_edges = [e for e in data.get("edges", []) if e.get("status") == "active"]
    except Exception as e:
        print(f"Error loading edges: {e}")
        return

    print(f"Found {len(active_edges)} ACTIVE strategies.")
    print(f"Validation Period: 2024-01-01 to 2025-01-01 (1 Year Stress Test)")
    print("-" * 50)
    print(f"{'Strategy':<25} | {'Sharpe':<8} | {'Return':<8} | {'Drawdown':<8} | {'Outcome':<10}")
    print("-" * 50)

    results = []

    # 2. Test Each Edge
    for edge in active_edges:
        edge_id = edge["edge_id"]
        # Use module name for harness import (e.g. 'rsi_bounce' not 'rsi_bounce_v1')
        # Handle full path modules (engines.engine_a... -> take last part) or simple names
        raw_module = edge.get("module", edge_id)
        if "." in raw_module:
            edge_module = raw_module.split(".")[-1]
        else:
            edge_module = raw_module
        
        # Create a temp grid for this single edge (default params)
        params = edge.get("params", {})
        grid_path = f"data/research/temp_validation_{edge_id}.json"
        
        # Format params as list for grid
        grid = {k: [v] for k, v in params.items()}
        
        Path(grid_path).parent.mkdir(parents=True, exist_ok=True)
        with open(grid_path, "w") as f:
            json.dump(grid, f)
            
        # Run Edge Harness
        # We use a single walk-forward slice for the validation year
        wf_slice = '[["2024-01-01", "2025-01-01"]]'
        
        cmd = [
            sys.executable, "research/edge_harness.py",
            "--edge", edge_module,
            "--param-grid", grid_path,
            "--walk-forward", wf_slice,
            "--out", "data/research/validation"
        ]
        
        try:
            # Run silently
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            # Find result csv
            out_dir = Path("data/research/validation")
            # Find the directory created for this edge (most recent)
            # This is tricky as edge_harness creates timestamps. 
            # We rely on the fact we just ran it.
            
            # Better approach: check stdout/stderr if failed
            if res.returncode != 0:
                print(f"{edge_id:<25} | ERROR    |          |          | CRASHED")
                continue

            # Scan for results
            dfs = []
            for d in out_dir.glob(f"{edge_id}_*"):
                 if (d / "results.csv").exists():
                     dfs.append(pd.read_csv(d / "results.csv"))
            
            if not dfs:
                 print(f"{edge_id:<25} | NO DATA  |          |          | FAILED")
                 continue
                 
            # Get the latest result
            df = dfs[-1] 
            if df.empty:
                print(f"{edge_id:<25} | EMPTY    |          |          | FAILED")
                continue
                
            row = df.iloc[0]
            sharpe = row.get("sharpe", 0.0)
            ret = row.get("total_return_pct", 0.0)
            dd = row.get("max_drawdown_pct", 0.0)
            
            # Outcome Logic
            outcome = "✅ PASS" if sharpe > 0.5 else "⚠️ WEAK"
            if ret < 0: outcome = "❌ LOSS"
            
            print(f"{edge_id:<25} | {sharpe:>6.2f}   | {ret:>7.2f}% | {dd:>7.2f}% | {outcome}")
            
            results.append({
                "edge": edge_id,
                "sharpe": sharpe,
                "return": ret,
                "dd": dd
            })
            
        except Exception as e:
            print(f"{edge_id:<25} | ERROR: {str(e)[:10]}")

    print("-" * 50)
    
    # 3. Portfolio Summary (Simple Sum)
    if results:
        avg_ret = sum(r["return"] for r in results) 
        print(f"Projected Uncorrelated Return: {avg_ret:.2f}% (Sum of Parts)")
        print("Note: Actual portfolio return will vary due to diversification.")

if __name__ == "__main__":
    main()
