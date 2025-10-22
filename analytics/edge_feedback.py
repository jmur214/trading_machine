# analytics/edge_feedback.py
"""
Edge Feedback Loop
==================

Bridges the CockpitLogger trade logs and StrategyGovernor for adaptive
edge reweighting based on recent performance.

This module reads the latest trade and snapshot logs, computes per-edge
PnL statistics, and updates the Governor’s edge weights automatically.

Usage (standalone or post-backtest):
------------------------------------
>>> from analytics.edge_feedback import update_edge_weights_from_latest_trades
>>> update_edge_weights_from_latest_trades(
...     trade_log_path="data/trade_logs/trades.csv",
...     snapshot_path="data/trade_logs/snapshots.csv"
... )

This will update and save new weights to:
    data/governor/edge_weights.json
"""

from __future__ import annotations

import os
import pandas as pd
from pathlib import Path
from engines.engine_d_research.governor import StrategyGovernor


# --------------------------------------------------------------------- #
# Core Function
# --------------------------------------------------------------------- #

def update_edge_weights_from_latest_trades(
    trade_log_path: str | Path = "data/trade_logs/trades.csv",
    snapshot_path: str | Path | None = "data/trade_logs/snapshots.csv",
    config_path: str | Path = "config/governor_settings.json",
    state_path: str | Path = "data/governor/edge_weights.json"
) -> None:
    """
    Load recent trades and snapshots, update edge weights, and persist.

    Parameters
    ----------
    trade_log_path : str or Path
        Path to trade log CSV produced by CockpitLogger.
    snapshot_path : str or Path, optional
        Path to snapshot log CSV (optional; for equity correlation calc).
    config_path : str or Path
        Governor configuration file.
    state_path : str or Path
        Output path for updated weights JSON.
    """
    trade_log_path = Path(trade_log_path)
    snapshot_path = Path(snapshot_path) if snapshot_path else None

    if not trade_log_path.exists() or trade_log_path.stat().st_size == 0:
        print("[EDGE_FEEDBACK] No trades found — skipping weight update.")
        return

    try:
        trades = pd.read_csv(trade_log_path)
        print(f"[EDGE_FEEDBACK] Loaded {len(trades)} trades from {trade_log_path}")
    except Exception as e:
        print(f"[EDGE_FEEDBACK][ERROR] Failed to read trade log: {e}")
        return

    snapshots = None
    if snapshot_path and snapshot_path.exists() and snapshot_path.stat().st_size > 0:
        try:
            snapshots = pd.read_csv(snapshot_path)
            print(f"[EDGE_FEEDBACK] Loaded {len(snapshots)} snapshots from {snapshot_path}")
        except Exception as e:
            print(f"[EDGE_FEEDBACK][WARN] Could not read snapshots: {e}")

    # Initialize and update the StrategyGovernor
    gov = StrategyGovernor(config_path=config_path, state_path=state_path)
    gov.update_from_trades(trades, snapshots)
    gov.save_weights()

    new_weights = gov.get_edge_weights()
    if not new_weights:
        print("[EDGE_FEEDBACK] No weights were updated (possibly insufficient trade data).")
        return

    print("[EDGE_FEEDBACK] ✅ Updated edge weights:")
    for edge, w in new_weights.items():
        print(f"   • {edge:<25s}: {w:.3f}")

    print(f"[EDGE_FEEDBACK] Weights saved to {state_path}")


# --------------------------------------------------------------------- #
# Optional CLI Entry Point
# --------------------------------------------------------------------- #

if __name__ == "__main__":
    update_edge_weights_from_latest_trades()