
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path

# Engine Imports
from engines.engine_d_research.regime_detector import RegimeDetector
from engines.engine_a_alpha.edges.composite_edge import CompositeEdge
from engines.engine_c_portfolio.policy import PortfolioPolicy, PortfolioPolicyConfig
from engines.engine_d_research.governor import StrategyGovernor, GovernorConfig
from research.edge_generator import EdgeGenerator

def run_system_check():
    print("==============================================")
    print("   TRADING MACHINE 2.0 - SYSTEM VALIDITY CHECK")
    print("==============================================\n")
    
    failures = []
    
    # --- STAGE 1: ALPHA & REGIME ---
    print("--- [Stage 1] Alpha & Regime Gating ---")
    try:
        # Mock Data (Bear Market)
        dates = pd.date_range("2023-01-01", periods=300)
        spy_bear = np.linspace(200, 100, 300) # Downtrend
        data = {"SPY": pd.DataFrame({"Close": spy_bear, "High": spy_bear+1, "Low": spy_bear-1}, index=dates)}
        
        # 1a. Test Bull Strategy in Bear Market (Should be blocked)
        genes_bull = [{"type": "regime", "is": "bull"}]
        edge_bull = CompositeEdge({"genes": genes_bull})
        
        # Run calculation
        scores = edge_bull.compute_signals(data, dates[-1])
        score = scores.get("SPY")
        
        if score is None or score == 0.0:
            print("✅ Regime Block: Bull Strategy blocked in Bear Market (Score 0.0).")
        else:
            print(f"❌ Regime Block FAILED: Bull Strategy active (Score {score}).")
            failures.append("Regime Gating")
            
        # 1b. Test Short Strategy (Direction)
        # Needs at least one gene to be active
        genes_dummy = [{"type": "technical", "indicator": "momentum_roc", "window": 10, "operator": "greater", "threshold": -100.0}] # Always true
        edge_short = CompositeEdge({"genes": genes_dummy, "direction": "short"})
        # No genes = always passes if data exists
        scores_s = edge_short.compute_signals(data, dates[-1])
        if scores_s.get("SPY") == -1.0:
            print("✅ Short Logic: Strategy returns -1.0 correctly.")
        else:
            print(f"❌ Short Logic FAILED: Expected -1.0, got {scores_s.get('SPY')}")
            failures.append("Short Logic")
            
    except Exception as e:
        print(f"❌ Stage 1 Crash: {e}")
        failures.append("Stage 1 Crash")

    # --- STAGE 2: PORTFOLIO REBALANCING ---
    print("\n--- [Stage 2] Portfolio Policy (Parrondo) ---")
    try:
        # Config: Fixed 50/50
        cfg = PortfolioPolicyConfig(mode="parrondo_fixed", fixed_allocations={"A": 0.5, "B": 0.5})
        policy = PortfolioPolicy(cfg)
        
        # Test Allocation (Should ignore signals)
        signals = {"A": 1.0, "B": -1.0, "C": 1.0} # C exists in signals but not in fixed plan
        prices = {} # Not used in fixed mode
        equity = 100000
        
        targets = policy.allocate(signals, prices, equity)
        
        if targets.get("A") == 0.5 and targets.get("B") == 0.5 and "C" not in targets:
            print("✅ Fixed Rebalancing: Exact 50/50 targets returned, ignoring Alpha.")
        else:
            print(f"❌ Fixed Rebalancing FAILED: Targets {targets}")
            failures.append("Portfolio Rebalancing")
            
    except Exception as e:
        print(f"❌ Stage 2 Crash: {e}")
        failures.append("Stage 2 Crash")

    # --- STAGE 3: GOVERNOR CORRELATION ---
    print("\n--- [Stage 3] Governor Correlation Logic ---")
    try:
        # Initialize Governor with fresh state
        gov = StrategyGovernor(state_path="data/governor/test_weights.json")
        gov.cfg.penalize_negative_correlation = True # We re-purposed this flag to mean "Apply Correlation Logic"
        
        # Mock Trades: Edge A and Edge B are identical (Corr = 1.0)
        dates_trade = pd.date_range("2023-01-01", periods=50)
        pnl_a = np.random.normal(100, 10, 50)
        
        df_trades = []
        for d, p in zip(dates_trade, pnl_a):
            df_trades.append({"timestamp": d, "edge": "Edge_A", "pnl": p})
            df_trades.append({"timestamp": d, "edge": "Edge_B", "pnl": p}) # Perfect correlation
            
        trades_df = pd.DataFrame(df_trades)
        
        # Mock Snapshots (Portfolio Equity matches Edge A perfectly)
        snap_df = pd.DataFrame({
            "timestamp": dates_trade,
            "equity": np.cumsum(pnl_a * 2) + 100000 
        })
        
        gov.update_from_trades(trades_df, snap_df)
        gov.save_weights() # Ensure metrics are saved
        
        # Check Penalty via Metrics (More precise)
        import json
        metrics_path = Path("data/governor/edge_metrics.json")
        if metrics_path.exists():
            with open(metrics_path) as f:
                metrics = json.load(f)["metrics"]
            
            penalty_a = metrics.get("Edge_A", {}).get("corr_penalty", 0.0)
            print(f"   Penalty A: {penalty_a:.4f}")
            
            if penalty_a > 0.0:
                print("✅ Correlation Penalty: High correlation detected and penalized.")
            else:
                print(f"❌ Correlation Penalty FAILED: Penalty is {penalty_a}")
                failures.append("Correlation Penalty")
        else:
            print("❌ Correlation Penalty FAILED: Metrics file not found.")
            failures.append("Metrics File Missing")
            
        # Clean up test files
        if Path("data/governor/test_weights.json").exists():
            Path("data/governor/test_weights.json").unlink()
        if metrics_path.exists():
            metrics_path.unlink()
            
    except Exception as e:
        print(f"❌ Stage 3 Crash: {e}")
        failures.append("Stage 3 Crash")

    # --- SUMMARY ---
    print("\n==============================================")
    if not failures:
        print("✅ SYSTEM VALIDITY CHECK PASSED. ALL SYSTEMS NOMINAL.")
    else:
        print(f"❌ SYSTEM CHECK FAILED. {len(failures)} Issues Found:")
        for f in failures:
            print(f"   - {f}")
    print("==============================================")

if __name__ == "__main__":
    run_system_check()
