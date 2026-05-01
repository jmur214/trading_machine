"""scripts/run_per_ticker_oos.py
==================================
Phase 2.11 B4 — run the 2025 OOS Q1 validation under the per-ticker
meta-learner.

Flips `metalearner.enabled` + `metalearner.per_ticker` to True in
`config/alpha_settings.prod.json` on this worktree only, runs
`scripts.run_oos_validation --task q1`, then restores the original
config.

Output: same as run_oos_validation — `data/research/oos_validation_q1.json`
plus the standard backtest run-id directory.

Usage:
    python scripts/run_per_ticker_oos.py
    python scripts/run_per_ticker_oos.py --mode portfolio  # ML on, per_ticker off
    python scripts/run_per_ticker_oos.py --mode off        # ML off (Task C reference)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALPHA_SETTINGS = ROOT / "config" / "alpha_settings.prod.json"


def _flip_config(mode: str) -> dict:
    """Set metalearner config for the requested mode and return the
    original dict so we can restore it."""
    original = json.loads(ALPHA_SETTINGS.read_text())
    cfg = json.loads(json.dumps(original))  # deep copy
    cfg.setdefault("metalearner", {})
    if mode == "off":
        cfg["metalearner"]["enabled"] = False
        cfg["metalearner"]["per_ticker"] = False
    elif mode == "portfolio":
        cfg["metalearner"]["enabled"] = True
        cfg["metalearner"]["per_ticker"] = False
        cfg["metalearner"].setdefault("profile_name", "balanced")
        cfg["metalearner"].setdefault("contribution_weight", 0.1)
    elif mode == "per_ticker":
        cfg["metalearner"]["enabled"] = True
        cfg["metalearner"]["per_ticker"] = True
        cfg["metalearner"].setdefault("profile_name", "balanced")
        cfg["metalearner"].setdefault("contribution_weight", 0.1)
        cfg["metalearner"].setdefault(
            "per_ticker_model_dir",
            "data/governor/per_ticker_metalearners",
        )
    else:
        raise ValueError(f"unknown mode: {mode}")
    ALPHA_SETTINGS.write_text(json.dumps(cfg, indent=2))
    return original


def _restore_config(original: dict) -> None:
    ALPHA_SETTINGS.write_text(json.dumps(original, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mode",
        choices=["off", "portfolio", "per_ticker"],
        default="per_ticker",
        help="Meta-learner configuration for this OOS run.",
    )
    args = ap.parse_args()

    print(f"[OOS-PT] Mode: {args.mode}")
    original = _flip_config(args.mode)
    print(f"[OOS-PT] config flipped → metalearner = "
          f"{json.loads(ALPHA_SETTINGS.read_text()).get('metalearner', {})}")

    try:
        # Delegate to the existing OOS runner
        sys.argv = ["run_oos_validation", "--task", "q1"]
        from scripts.run_oos_validation import main as oos_main
        oos_main()
    finally:
        _restore_config(original)
        print(f"[OOS-PT] config restored")

    return 0


if __name__ == "__main__":
    sys.exit(main())
