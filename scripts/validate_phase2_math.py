
import sys
import os
import pandas as pd
import numpy as np
from research.edge_generator import EdgeGenerator
from engines.engine_e_regime.regime_detector import RegimeDetector

def test_phase2_math():
    print("--- 1. Generating Strategy with New Math ---")
    gen = EdgeGenerator(output_dir="engines/engine_a_alpha/edges")
    
    # Complex Genome:
    # 1. Regime must be Bull.
    # 2. Residual Momentum (Alpha) must be positive (> 0.0).
    # 3. Price Momentum (ROC) must be in top 50% of universe.
    genes = [
        {"type": "regime", "is": "bull"},
        {"type": "technical", "indicator": "residual_momentum", "window": 20, "operator": "greater", "threshold": 0.0},
        {"type": "technical", "indicator": "momentum_roc", "window": 20, "operator": "top_percentile", "threshold": 50}
    ]
    
    edge_path = gen.save_edge("autogen_phase2_complex_test", genes)
    print(f"Generated: {edge_path}")
    
    print("\n--- 2. Validating Generated Code Execution ---")
    import importlib.util
    spec = importlib.util.spec_from_file_location("AutogenPhase2ComplexTest", edge_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    EdgeClass = module.AutogenPhase2ComplexTest
    
    edge = EdgeClass({"genes": genes})
    
    print("\n--- 3. Running Compute Signals (Synthetic Data 300 days) ---")
    # Increase to 300 days to satisfy RegimeDetector(MA200)
    dates = pd.date_range("2023-01-01", periods=300)
    data_map = {}
    
    # SPY (Benchmark) - Trending Up consistently
    # Price 100 -> 400
    spy_close = np.linspace(100, 400, 300)
    data_map["SPY"] = pd.DataFrame({"Close": spy_close, "High": spy_close+1, "Low": spy_close-1}, index=dates)
    
    # Stock A (High Alpha) - Goes up faster than SPY
    # Price 10 -> 100 (10x) vs SPY (4x)
    stock_a = np.linspace(10, 100, 300)
    data_map["A"] = pd.DataFrame({"Close": stock_a, "High": stock_a+1, "Low": stock_a-1}, index=dates)
    
    # Stock B (Loser) - Flat/Down
    stock_b = np.linspace(50, 40, 300)
    data_map["B"] = pd.DataFrame({"Close": stock_b, "High": stock_b+1, "Low": stock_b-1}, index=dates)
    
    # Run Signal Calculation
    last_date = dates[-1]
    scores = edge.compute_signals(data_map, last_date)
    
    print(f"Scores at {last_date}: {scores}")
    
    if scores.get("A") == 1.0:
        print("✅ Stock A (Winner) selected correctly.")
    else:
        print("❌ Stock A NOT selected (Unexpected). Check Regime/Alpha logic.")
        
    if scores.get("B") == 0.0:
        print("✅ Stock B (Loser) rejected correctly.")
    else:
        print("❌ Stock B selected (Unexpected).")

if __name__ == "__main__":
    test_phase2_math()
