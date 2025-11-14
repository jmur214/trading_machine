#!/usr/bin/env python3
"""
Trading Machine - Unified Healthcheck Script
--------------------------------------------

This script runs:
1. A trimmed pytest suite for high‑signal tests.
2. A very fast development backtest.
3. Core invariants:
   • Equity consistency
   • run_id presence
   • Snapshot count sanity
   • Trade file sanity

Exit codes:
0 = healthy
1 = failures found
"""

import subprocess
import sys
import os
from pathlib import Path
import pandas as pd
import argparse
import traceback


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "trade_logs"


def run_cmd(cmd: list[str], name: str) -> bool:
    """
    Run a shell command, stream output, and return success boolean.
    """
    print(f"\n===== Running {name} =====\n", flush=True)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            print(line, end="")
        proc.wait()
        return proc.returncode == 0
    except Exception as e:
        print(f"[ERROR] Failed running {name}: {e}")
        traceback.print_exc()
        return False


def run_pytests() -> bool:
    """
    Run only the high‑signal tests that verify portfolio math + controller logic.
    """
    test_paths = [
        "tests/test_portfolio_engine.py",
        "tests/test_backtest_controller.py",
        "tests/test_governor.py",
    ]
    for path in test_paths:
        if not run_cmd(["pytest", "-q", path], f"pytest: {path}"):
            return False
    return True


def run_dev_backtest() -> bool:
    """
    Run the small/fast dev backtest. User may later customize flags.
    """
    cmd = ["python", "scripts/run_backtest.py", "--env", "dev", "--fresh"]
    return run_cmd(cmd, "dev backtest")


def run_invariants() -> bool:
    """
    Perform core snapshot/trade invariants.
    """
    print("\n===== Running invariants =====\n")

    # Ensure logs exist
    snap_path = DATA_DIR / "portfolio_snapshots.csv"
    trade_path = DATA_DIR / "trades.csv"

    missing = []
    if not snap_path.exists():
        missing.append(str(snap_path))
    if not trade_path.exists():
        missing.append(str(trade_path))

    if missing:
        print("[FAIL] Missing expected output files:", missing)
        return False

    # Load snapshots
    try:
        snap = pd.read_csv(snap_path)
    except Exception as e:
        print("[FAIL] Could not read snapshots CSV:", e)
        return False

    if len(snap) < 10:
        print("[FAIL] Snapshot count too low:", len(snap))
        return False

    # Basic fields
    required_cols = ["cash", "market_value", "equity", "realized_pnl", "unrealized_pnl"]
    for col in required_cols:
        if col not in snap.columns:
            print(f"[FAIL] Missing snapshot column: {col}")
            return False

    # Equity consistency check
    eq_calc = snap["cash"] + snap["market_value"]
    diff = (snap["equity"] - eq_calc).abs()
    bad = diff > 1e-9
    if bad.any():
        print("[FAIL] Equity mismatch detected. Example rows:")
        print(snap[bad].head())
        return False

    # run_id uniqueness check
    run_ids = snap["run_id"].unique()
    if len(run_ids) != 1:
        print("[FAIL] Multiple run_ids detected:", run_ids)
        return False

    print("[OK] Invariants passed.")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest tests")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip dev backtest")
    args = parser.parse_args()

    all_good = True

    if not args.skip_tests:
        all_good &= run_pytests()

    if not args.skip_backtest:
        all_good &= run_dev_backtest()

    all_good &= run_invariants()

    if all_good:
        print("\n===== HEALTHCHECK PASSED =====")
        sys.exit(0)
    else:
        print("\n===== HEALTHCHECK FAILED =====")
        sys.exit(1)


if __name__ == "__main__":
    main()
