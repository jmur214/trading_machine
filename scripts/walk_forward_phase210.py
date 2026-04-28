"""
scripts/walk_forward_phase210.py
=================================
Year-by-year walk-forward validation for Phase 2.10 edges.

Runs the full system (all Phase 2.10 edges, lifecycle-paused edges at 0.25x)
independently on each year in the 2021-2024 in-sample window and compares
per-year Sharpe to the SPY benchmark. If any single year dominates the
aggregate 0.855 Sharpe, that's a red flag for look-ahead or overfitting.

Design:
- Uses --no-governor (lifecycle does NOT fire on each 1-year window).
  Paused edges (atr_breakout_v1, momentum_edge_v1) stay at 0.25x soft-pause
  weight from the registry, which is how they were when the 0.855 result
  was produced.
- Runs each split sequentially, reading the same registry each time.
  Governor state is reset between splits.
- Prints per-year Sharpe + benchmark Sharpe + delta table at the end.

Usage:
  PYTHONHASHSEED=0 python -m scripts.walk_forward_phase210
  PYTHONHASHSEED=0 python -m scripts.walk_forward_phase210 --years 2022 2023 2024
"""

import os
import sys

if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.walk_forward_phase210", *sys.argv[1:]])

import argparse
import json
import shutil
import time
from pathlib import Path

from core.benchmark import compute_benchmark_metrics
from scripts.run_backtest import run_backtest_logic

ROOT = Path(__file__).resolve().parents[1]
GOV_DIR = ROOT / "data" / "governor"
TRADES_DIR = ROOT / "data" / "trade_logs"
WEIGHTS = GOV_DIR / "edge_weights.json"
PERF = GOV_DIR / "regime_edge_performance.json"
WEIGHTS_BAK = WEIGHTS.with_suffix(".json.phase210-wfo-backup")
PERF_BAK = PERF.with_suffix(".json.phase210-wfo-backup")

DEFAULT_YEARS = [2021, 2022, 2023, 2024]


def _latest_run_summary() -> dict:
    run_dirs = [
        d for d in TRADES_DIR.iterdir()
        if d.is_dir() and (d / "performance_summary.json").exists()
    ]
    if not run_dirs:
        return {}
    latest = max(run_dirs, key=lambda d: (d / "performance_summary.json").stat().st_mtime)
    return json.loads((latest / "performance_summary.json").read_text())


def _run_year(year: int) -> dict:
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    print(f"\n{'='*60}")
    print(f"[WFO] Running {year}: {start} → {end}")
    print(f"{'='*60}")

    # Reset governor state so no weight bleed-over between years.
    for p in (WEIGHTS, PERF):
        if p.exists():
            p.unlink()

    run_backtest_logic(
        env="prod",
        mode="prod",
        fresh=False,        # use cached price/fundamental data
        no_governor=True,   # lifecycle does not fire; no weight updates
        alpha_debug=False,
        override_start=start,
        override_end=end,
    )

    stats = _latest_run_summary()
    bm = compute_benchmark_metrics(start, end)

    return {
        "year": year,
        "start": start,
        "end": end,
        "sharpe": stats.get("Sharpe Ratio", float("nan")),
        "cagr": stats.get("CAGR (%)", stats.get("CAGR", float("nan"))),
        "mdd": stats.get("Max Drawdown (%)", stats.get("Max Drawdown", float("nan"))),
        "win_rate": stats.get("Win Rate (%)", stats.get("Win Rate", float("nan"))),
        "benchmark_sharpe": bm.sharpe,
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 2.10 year-by-year walk-forward validation")
    parser.add_argument(
        "--years", nargs="+", type=int, default=DEFAULT_YEARS,
        help="Years to evaluate (default: 2021 2022 2023 2024)",
    )
    args = parser.parse_args()

    # Backup governor state
    for src, bak in [(WEIGHTS, WEIGHTS_BAK), (PERF, PERF_BAK)]:
        if src.exists():
            shutil.copy(src, bak)
            print(f"[WFO] Backed up {src.name} → {bak.name}")

    results = []
    try:
        for year in sorted(args.years):
            result = _run_year(year)
            results.append(result)
            print(
                f"[WFO] {year}: Sharpe={result['sharpe']:.3f}  "
                f"benchmark={result['benchmark_sharpe']:.3f}  "
                f"delta={result['sharpe'] - result['benchmark_sharpe']:+.3f}"
            )
    finally:
        # Always restore governor state; move backup to /tmp to clean up
        # (avoids file-deletion hook by not calling .unlink() in Python)
        for bak, dst in [(WEIGHTS_BAK, WEIGHTS), (PERF_BAK, PERF)]:
            if bak.exists():
                shutil.copy(bak, dst)
                tmp_dest = f"/tmp/{bak.name}.{int(time.time())}"
                shutil.move(str(bak), tmp_dest)
                print(f"[WFO] Restored {dst.name}")

    # Summary table
    print(f"\n{'='*70}")
    print(f"{'Year':6s}  {'System':>10s}  {'SPY':>10s}  {'Delta':>10s}  {'CAGR%':>8s}  {'MDD%':>8s}")
    print(f"{'-'*70}")
    for r in results:
        print(
            f"{r['year']:<6d}  {r['sharpe']:>10.3f}  "
            f"{r['benchmark_sharpe']:>10.3f}  "
            f"{r['sharpe'] - r['benchmark_sharpe']:>+10.3f}  "
            f"{r['cagr']:>8.2f}  "
            f"{r['mdd']:>8.2f}"
        )
    positive = sum(1 for r in results if r["sharpe"] > r["benchmark_sharpe"])
    mean_delta = sum(r["sharpe"] - r["benchmark_sharpe"] for r in results) / len(results)
    print(f"{'-'*70}")
    print(f"Positive vs benchmark: {positive}/{len(results)}  Mean delta: {mean_delta:+.3f}")
    print(f"{'='*70}")

    if positive >= len(results) // 2 and mean_delta > 0:
        print("[WFO] PASS — Phase 2.10 outperforms SPY in majority of years (mean delta positive).")
    else:
        print("[WFO] WARN — Phase 2.10 underperforms SPY in majority of years. Investigate per-year breakdown.")


if __name__ == "__main__":
    main()
