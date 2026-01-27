# analysis_script_equity.py
import pandas as pd
import sys
import os

print("--- Analysis: Equity Consistency ---")
try:
    snap = pd.read_csv("data/trade_logs/portfolio_snapshots.csv")
except FileNotFoundError:
    print("No portfolio snapshots found.")
    sys.exit(0)

# 1. Computed Equity Mismatch
computed_equity = snap["cash"] + snap["market_value"]
snap["diff"] = snap["equity"] - computed_equity
mismatches = (abs(snap["diff"]) > 1e-9).sum()
print(f"Total equity mismatches (Equity != Cash + MV): {mismatches}")

if mismatches > 0:
    print("\nSample Mismatches:")
    print(snap[abs(snap["diff"]) > 1e-9][["timestamp", "cash", "market_value", "equity", "diff"]].head())

# 2. PnL Continuity Check
print("\n--- Analysis: PnL Continuity ---")
start_equity = snap["equity"].iloc[0]
end_equity = snap["equity"].iloc[-1]
realized_pnl = snap["realized_pnl"].iloc[-1]
unrealized_pnl = snap["unrealized_pnl"].iloc[-1]
derived_end_equity = start_equity + realized_pnl + unrealized_pnl

print(f"Start Equity: {start_equity:.2f}")
print(f"End Equity (Reported): {end_equity:.2f}")
print(f"End Equity (Derived from PnL): {derived_end_equity:.2f}")
diff_pnl = end_equity - derived_end_equity
print(f"Discrepancy: {diff_pnl:.4f}")

if abs(diff_pnl) > 1.0:
    print("WARNING: Significant PnL accounting discrepancy.")
else:
    print("PnL accounting looks consistent.")
