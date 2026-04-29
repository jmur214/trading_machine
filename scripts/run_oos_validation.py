"""
scripts/run_oos_validation.py
=============================
Phase 2.10b OOS validation driver. Runs Q1 (2025 OOS, prod universe) or
Q2 (universe-B held-out tickers, 2021-2024) under the realistic-cost
slippage model already wired as default in config/backtest_settings.json.

Both modes use --reset-governor for clean state.

Usage:
    python -m scripts.run_oos_validation --task q1
    python -m scripts.run_oos_validation --task q2
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Set

import numpy as np

from orchestration.mode_controller import ModeController
from core.benchmark import compute_multi_benchmark_metrics


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
RESEARCH_DIR = ROOT / "data" / "research"


def sample_universe_b(prod_tickers: Set[str], n_sample: int = 50, seed: int = 42) -> List[str]:
    """Mirror engines/engine_d_discovery/discovery.py::_load_universe_b
    sampling logic (seed=42, n=50, exclude prod, min length filtered later
    by data_manager). Returns ticker symbols only — DataFrames are loaded
    by the standard DataManager pipeline downstream.
    """
    all_csvs = {f.stem.replace("_1d", "") for f in PROCESSED_DIR.glob("*_1d.csv")}
    candidates = sorted(all_csvs - prod_tickers)
    if not candidates:
        return []
    rng = np.random.RandomState(seed)
    sampled = rng.choice(
        candidates, size=min(n_sample, len(candidates)), replace=False,
    ).tolist()
    return sampled


def find_run_id(before: Set[str]) -> str | None:
    after = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    # Multiple — pick newest by mtime
    candidates = [(p, p.stat().st_mtime) for p in (ROOT / "data" / "trade_logs").iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def run_q1() -> dict:
    """2025 OOS on prod universe. Same costs, shifted window, reset governor."""
    print("[OOS-Q1] 2025 OOS, prod universe, realistic costs, --reset-governor")
    before = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir() and p.name != "backup"}

    mc = ModeController(ROOT, env="prod")
    summary = mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_start="2025-01-01",
        override_end="2025-12-31",
    )
    run_id = find_run_id(before)
    summary["run_id"] = run_id
    summary["window"] = "2025-01-01 to 2025-12-31"
    summary["universe"] = "prod (109 tickers)"
    return summary


def run_q2() -> dict:
    """Universe-B (50 held-out tickers, seed=42) on same in-sample window."""
    print("[OOS-Q2] Universe-B, 2021-2024, realistic costs, --reset-governor")
    mc = ModeController(ROOT, env="prod")

    prod_tickers = set(mc.cfg_bt["tickers"])
    universe_b = sample_universe_b(prod_tickers, n_sample=50, seed=42)

    # Universe-B doesn't include SPY/QQQ/TLT by definition (they're in prod).
    # Add them so PortfolioEngine has benchmark / regime data without
    # contaminating the held-out universe (they aren't part of the
    # tradeable list, but the system needs them for regime detection).
    # Looking at mode_controller, all `tickers` ARE tradable. We don't add
    # SPY here since universe-B is meant to be a *blind* held-out test —
    # benchmark prices come from the cached benchmark loader in core/benchmark.py.
    print(f"[OOS-Q2] Universe-B sample (seed=42, n={len(universe_b)}): {universe_b[:10]}...")
    mc.cfg_bt["tickers"] = universe_b

    before = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir() and p.name != "backup"}
    summary = mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
    )
    run_id = find_run_id(before)
    summary["run_id"] = run_id
    summary["window"] = "2021-01-01 to 2024-12-31"
    summary["universe"] = f"universe-B ({len(universe_b)} tickers, seed=42)"
    summary["universe_tickers"] = universe_b
    return summary


def attach_benchmarks(summary: dict, start: str, end: str) -> dict:
    """Add SPY / QQQ / 60-40 metrics over the same window."""
    multi = compute_multi_benchmark_metrics(start=start, end=end)
    summary["benchmarks"] = {
        name: {
            "sharpe": round(bm.sharpe, 3),
            "cagr_pct": round(bm.cagr * 100, 2),
            "mdd_pct": round(bm.mdd * 100, 2),
            "vol_pct": round(bm.vol * 100, 2),
            "n_obs": bm.n_obs,
        }
        for name, bm in multi.items()
    }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["q1", "q2"], required=True)
    args = parser.parse_args()

    if args.task == "q1":
        summary = run_q1()
        summary = attach_benchmarks(summary, "2025-01-01", "2025-12-31")
        out_path = RESEARCH_DIR / "oos_validation_q1.json"
    else:
        summary = run_q2()
        summary = attach_benchmarks(summary, "2021-01-01", "2024-12-31")
        out_path = RESEARCH_DIR / "oos_validation_q2.json"

    summary["task"] = args.task
    summary["timestamp"] = datetime.utcnow().isoformat() + "Z"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[OOS-{args.task.upper()}] Saved to {out_path}")
    print(f"  run_id: {summary.get('run_id')}")
    print(f"  Sharpe: {summary.get('Sharpe Ratio')}")
    print(f"  CAGR%:  {summary.get('CAGR (%)')}")
    print(f"  MDD%:   {summary.get('Max Drawdown (%)')}")
    print(f"  Vol%:   {summary.get('Volatility (%)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
