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
import sys
import json
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
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
    # Only configure logging if root logger has no handlers (to avoid interfering with debug_config or LOGGER)
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    trade_log_path = Path(trade_log_path)
    snapshot_path = Path(snapshot_path) if snapshot_path else None

    if not trade_log_path.exists() or trade_log_path.stat().st_size == 0:
        logging.info("[EDGE_FEEDBACK] No trades found — skipping weight update.")
        return

    try:
        trades = pd.read_csv(trade_log_path)
        logging.info(f"[EDGE_FEEDBACK] Loaded {len(trades)} trades from {trade_log_path}")
    except Exception as e:
        logging.info(f"[EDGE_FEEDBACK][ERROR] Failed to read trade log: {e}")
        return

    snapshots = None
    if snapshot_path and snapshot_path.exists() and snapshot_path.stat().st_size > 0:
        try:
            snapshots = pd.read_csv(snapshot_path)
            logging.info(f"[EDGE_FEEDBACK] Loaded {len(snapshots)} snapshots from {snapshot_path}")
        except Exception as e:
            logging.info(f"[EDGE_FEEDBACK][WARN] Could not read snapshots: {e}")

    # Initialize and update the StrategyGovernor
    gov = StrategyGovernor(config_path=config_path, state_path=state_path)

    old_weights = gov.get_edge_weights() if hasattr(gov, "get_edge_weights") else None

    gov.update_from_trades(trades, snapshots)
    gov.save_weights()

    # Automatically merge evaluator recommendations after updating weights
    merged_weights = None
    try:
        gov.merge_evaluator_recommendations()
        merged_weights = gov.get_merged_weights() if hasattr(gov, "get_merged_weights") else None
    except Exception as e:
        logging.info(f"[EDGE_FEEDBACK][WARN] Could not merge evaluator recommendations: {e}")

    new_weights = gov.get_edge_weights()
    if not new_weights:
        logging.info("[EDGE_FEEDBACK] No weights were updated (possibly insufficient trade data).")
        return

    logging.info("[EDGE_FEEDBACK] Updated edge weights:")
    for edge, w in new_weights.items():
        logging.info(f"   • {edge:<25s}: {w:.3f}")

    if merged_weights:
        logging.info("[EDGE_FEEDBACK] Merged edge weights (after evaluator recommendations):")
        for edge, w in merged_weights.items():
            logging.info(f"   • {edge:<25s}: {w:.3f}")

    logging.info(f"[EDGE_FEEDBACK] Weights saved to {state_path}")

    # Attempt to gather metrics if available
    metrics = {}
    try:
        # Try to get metrics from governor if available
        if hasattr(gov, "get_metrics"):
            metrics = gov.get_metrics()
        else:
            # fallback: try to infer some metrics from trades DataFrame
            if not trades.empty:
                pnl = trades['pnl'] if 'pnl' in trades.columns else None
                if pnl is not None:
                    sharpe = pnl.mean() / (pnl.std() + 1e-9) * (252**0.5) if pnl.std() > 0 else None
                    max_drawdown = None
                    cum_pnl = pnl.cumsum()
                    if not cum_pnl.empty:
                        roll_max = cum_pnl.cummax()
                        drawdown = roll_max - cum_pnl
                        max_drawdown = drawdown.max()
                    metrics = {
                        "sharpe": sharpe,
                        "max_drawdown": max_drawdown,
                        "num_trades": len(trades),
                    }
    except Exception:
        pass

    write_feedback_history(old_weights, new_weights, metrics, merged_weights)


def write_feedback_history(
    old_weights: dict | None,
    new_weights: dict,
    metrics: dict | None,
    merged_weights: dict | None = None,
    history_log_path: str | Path = "data/governor/feedback_history.log"
) -> None:
    """
    Append a structured log entry of the feedback run to a history log file.

    Parameters
    ----------
    old_weights : dict or None
        Edge weights before update.
    new_weights : dict
        Updated edge weights.
    metrics : dict or None
        Performance metrics such as Sharpe, max drawdown, number of trades.
    merged_weights : dict or None
        Merged edge weights after evaluator recommendations.
    history_log_path : str or Path
        Path to the feedback history log file.
    """
    history_log_path = Path(history_log_path)
    timestamp = datetime.utcnow().isoformat() + "Z"

    entry = {
        "timestamp": timestamp,
        "old_weights": old_weights if old_weights is not None else {},
        "new_weights": new_weights,
        "metrics": metrics if metrics is not None else {},
        "merged_weights": merged_weights if merged_weights is not None else {},
    }

    try:
        history_log_path.parent.mkdir(parents=True, exist_ok=True)
        with history_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logging.info(f"[EDGE_FEEDBACK][WARN] Failed to write feedback history: {e}")


# --------------------------------------------------------------------- #
# Optional CLI Entry Point
# --------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Update edge weights from latest trades or show feedback history.")
    parser.add_argument("--history", action="store_true", help="Print the full feedback history log and exit.")
    args = parser.parse_args()

    history_log_path = Path("data/governor/feedback_history.log")

    if args.history:
        if not history_log_path.exists():
            print("No feedback history log found.")
            sys.exit(0)
        try:
            with history_log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines:
                    print("Feedback history log is empty.")
                    sys.exit(0)
                print("Feedback History Log:")
                for line in lines:
                    try:
                        entry = json.loads(line)
                        print("-" * 40)
                        print(f"Timestamp: {entry.get('timestamp','')}")
                        print("Old Weights:")
                        for edge, w in entry.get("old_weights", {}).items():
                            print(f"   • {edge:<25s}: {w:.3f}")
                        print("New Weights:")
                        for edge, w in entry.get("new_weights", {}).items():
                            print(f"   • {edge:<25s}: {w:.3f}")
                        metrics = entry.get("metrics", {})
                        if metrics:
                            print("Metrics:")
                            for k, v in metrics.items():
                                if v is None:
                                    val_str = "N/A"
                                elif isinstance(v, float):
                                    val_str = f"{v:.4f}"
                                else:
                                    val_str = str(v)
                                print(f"   • {k}: {val_str}")
                        merged = entry.get("merged_weights", {})
                        if merged:
                            print("Merged Weights:")
                            for edge, w in merged.items():
                                print(f"   • {edge:<25s}: {w:.3f}")
                    except Exception:
                        print("  [ERROR] Could not parse entry.")
                print("-" * 40)
        except Exception as e:
            print(f"Error reading feedback history log: {e}")
        sys.exit(0)

    update_edge_weights_from_latest_trades()