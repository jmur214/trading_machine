"""
Edge Feedback Loop — Backward-compatible shim.

Core logic now lives in engines/engine_f_governance/governor.py
(StrategyGovernor.update_from_trade_log).

This module re-exports the function for callers that import from here.
"""
from __future__ import annotations

from pathlib import Path
from engines.engine_f_governance.governor import StrategyGovernor


def update_edge_weights_from_latest_trades(
    trade_log_path: str | Path = "data/trade_logs/trades.csv",
    snapshot_path: str | Path | None = "data/trade_logs/snapshots.csv",
    config_path: str | Path = "config/governor_settings.json",
    state_path: str | Path = "data/governor/edge_weights.json",
) -> None:
    """Delegate to StrategyGovernor.update_from_trade_log()."""
    gov = StrategyGovernor(config_path=config_path, state_path=state_path)
    gov.update_from_trade_log(trade_log_path=trade_log_path, snapshot_path=snapshot_path)


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Update edge weights from latest trades or show feedback history.")
    parser.add_argument("--history", action="store_true", help="Print the full feedback history log and exit.")
    parser.add_argument("--mode", choices=["sandbox", "prod"], default="prod")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    base_dir = Path("data/governor")
    if args.mode == "sandbox":
        base_dir = base_dir / "sandbox"

    history_log_path = base_dir / "feedback_history.log"
    config_path = Path("config/governor_settings.json")
    state_path = base_dir / "edge_weights.json"

    if args.history:
        if not history_log_path.exists():
            print("No feedback history log found.")
            sys.exit(0)
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
                print(f"Timestamp: {entry.get('timestamp', '')}")
                for label in ("old_weights", "new_weights"):
                    print(f"{label.replace('_', ' ').title()}:")
                    for edge, w in entry.get(label, {}).items():
                        print(f"   {edge:<25s}: {w:.3f}")
                metrics = entry.get("metrics", {})
                if metrics:
                    print("Metrics:")
                    for k, v in metrics.items():
                        print(f"   {k}: {v if v is not None else 'N/A'}")
            except Exception:
                print("  [ERROR] Could not parse entry.")
        print("-" * 40)
        sys.exit(0)

    update_edge_weights_from_latest_trades(config_path=config_path, state_path=state_path)
