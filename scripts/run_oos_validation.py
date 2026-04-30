"""
scripts/run_oos_validation.py
=============================
Phase 2.10b OOS validation driver. Runs Q1 (2025 OOS, prod universe) or
Q2 (universe-B held-out tickers, 2021-2024) under the realistic-cost
slippage model already wired as default in config/backtest_settings.json.

Phase 2.10c precursor: also supports `--task counterfactual` which
re-runs Q1 with named edges temporarily un-paused (status: paused →
active in data/governor/edges.yml for the duration of the run, then
restored). Used to ask: did the lifecycle pause cause 2025 OOS
underperformance?

All modes use --reset-governor for clean state.

Usage:
    python -m scripts.run_oos_validation --task q1
    python -m scripts.run_oos_validation --task q2
    python -m scripts.run_oos_validation --task counterfactual \\
        --unpause-edges atr_breakout_v1,momentum_edge_v1
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Set

import numpy as np
import yaml

from orchestration.mode_controller import ModeController
from core.benchmark import compute_multi_benchmark_metrics


ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
RESEARCH_DIR = ROOT / "data" / "research"
EDGES_YML = ROOT / "data" / "governor" / "edges.yml"
TRADES_DIR = ROOT / "data" / "trade_logs"


@contextmanager
def temporarily_unpause(edge_ids: Iterable[str]):
    """Patch data/governor/edges.yml: flip status:paused → active for
    listed edge_ids for the duration of the run. Restore on exit
    (success or exception). Edges not currently paused are left alone.

    The on-disk yml is the lifecycle state read by EdgeRegistry — both
    the soft-pause weight cap in mode_controller.run_backtest and the
    edge instantiation path key off it.
    """
    target = set(edge_ids)
    backup_path = EDGES_YML.with_suffix(".yml.counterfactual_bak")
    shutil.copy(EDGES_YML, backup_path)

    with open(EDGES_YML) as f:
        registry = yaml.safe_load(f)

    flipped: List[str] = []
    for spec in registry.get("edges", []):
        if spec.get("edge_id") in target and spec.get("status") == "paused":
            spec["status"] = "active"
            flipped.append(spec["edge_id"])

    with open(EDGES_YML, "w") as f:
        yaml.safe_dump(registry, f, sort_keys=False)

    print(f"[COUNTERFACTUAL] Temporarily un-paused {len(flipped)} edge(s): {flipped}")
    print(f"[COUNTERFACTUAL] Backup at {backup_path}")
    try:
        yield flipped
    finally:
        shutil.copy(backup_path, EDGES_YML)
        backup_path.unlink(missing_ok=True)
        print(f"[COUNTERFACTUAL] Restored edges.yml from backup")


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


def run_counterfactual(unpause_edges: List[str]) -> dict:
    """Re-run Q1 (2025 OOS, prod universe) with named edges flipped
    paused→active in edges.yml for the duration. Mirrors run_q1() in
    every other respect.
    """
    print(f"[COUNTERFACTUAL] 2025 OOS, prod universe, --reset-governor, "
          f"un-pausing: {unpause_edges}")
    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}

    with temporarily_unpause(unpause_edges) as flipped:
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
    summary["unpaused_edges_requested"] = unpause_edges
    summary["unpaused_edges_actually_flipped"] = flipped
    summary["per_edge_stats"] = compute_per_edge_stats(run_id)
    return summary


def compute_per_edge_stats(run_id: str | None) -> dict:
    """Read trades.csv from the run dir; aggregate fill count + realized
    PnL by edge. Best-effort — if anything fails, return empty dict.
    """
    if not run_id:
        return {}
    import pandas as pd
    trades_path = TRADES_DIR / run_id / f"trades_{run_id}.csv"
    if not trades_path.exists():
        trades_path = TRADES_DIR / run_id / "trades.csv"
    if not trades_path.exists():
        return {}
    try:
        df = pd.read_csv(trades_path)
    except Exception:
        return {}
    if df.empty or "edge" not in df.columns:
        return {}
    pnl_col = "pnl" if "pnl" in df.columns else None
    out: dict = {}
    for edge, sub in df.groupby("edge"):
        out[str(edge)] = {
            "fills": int(len(sub)),
            "realized_pnl": float(sub[pnl_col].sum()) if pnl_col else None,
            "long_fills": int((sub.get("side", "") == "long").sum()) if "side" in sub.columns else None,
            "short_fills": int((sub.get("side", "") == "short").sum()) if "side" in sub.columns else None,
        }
    return out


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
    parser.add_argument("--task", choices=["q1", "q2", "counterfactual"], required=True)
    parser.add_argument(
        "--unpause-edges",
        type=str,
        default="",
        help="Comma-separated edge_ids to flip paused→active for the counterfactual run.",
    )
    args = parser.parse_args()

    if args.task == "q1":
        summary = run_q1()
        summary = attach_benchmarks(summary, "2025-01-01", "2025-12-31")
        out_path = RESEARCH_DIR / "oos_validation_q1.json"
    elif args.task == "q2":
        summary = run_q2()
        summary = attach_benchmarks(summary, "2021-01-01", "2024-12-31")
        out_path = RESEARCH_DIR / "oos_validation_q2.json"
    else:
        if not args.unpause_edges:
            parser.error("--task counterfactual requires --unpause-edges")
        unpause = [e.strip() for e in args.unpause_edges.split(",") if e.strip()]
        summary = run_counterfactual(unpause)
        summary = attach_benchmarks(summary, "2025-01-01", "2025-12-31")
        out_path = RESEARCH_DIR / "oos_validation_counterfactual_2025.json"

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
