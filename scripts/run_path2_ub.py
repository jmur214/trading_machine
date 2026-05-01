"""Path-2 Universe-B driver — runs Q2 with optional metalearner override.

Mirrors scripts/run_oos_validation.run_q2 but exposes --metalearner so we
can A/B floors-only vs floors+ML without modifying config on disk
(which would violate the Path-1 boundary).

Usage:
    PYTHONHASHSEED=0 python -m scripts.run_path2_ub --metalearner off
    PYTHONHASHSEED=0 python -m scripts.run_path2_ub --metalearner on
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
    candidates = [(p, p.stat().st_mtime) for p in (ROOT / "data" / "trade_logs").iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def run_q2_with_metalearner(metalearner_enabled: bool) -> dict:
    print(f"[PATH-2] Universe-B 2021-2024, ADV floors active, metalearner.enabled={metalearner_enabled}")
    mc = ModeController(ROOT, env="prod")

    prod_tickers = set(mc.cfg_bt["tickers"])
    universe_b = sample_universe_b(prod_tickers, n_sample=50, seed=42)
    print(f"[PATH-2] Universe-B sample (seed=42, n={len(universe_b)}): {universe_b[:10]}...")
    mc.cfg_bt["tickers"] = universe_b

    before = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir() and p.name != "backup"}

    override_params = None
    if metalearner_enabled:
        override_params = {"alpha": {"metalearner": {
            "enabled": True,
            "profile_name": "balanced",
            "contribution_weight": 0.1,
        }}}

    summary = mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_params=override_params,
    )
    run_id = find_run_id(before)
    summary["run_id"] = run_id
    summary["window"] = "2021-01-01 to 2024-12-31"
    summary["universe"] = f"universe-B ({len(universe_b)} tickers, seed=42)"
    summary["universe_tickers"] = universe_b
    summary["metalearner_enabled"] = metalearner_enabled
    return summary


def attach_benchmarks(summary: dict, start: str, end: str) -> dict:
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
    parser.add_argument("--metalearner", choices=["on", "off"], default="off")
    args = parser.parse_args()

    enabled = args.metalearner == "on"
    summary = run_q2_with_metalearner(enabled)
    summary = attach_benchmarks(summary, "2021-01-01", "2024-12-31")
    summary["task"] = f"path2_ub_ml_{args.metalearner}"
    summary["timestamp"] = datetime.utcnow().isoformat() + "Z"

    out_path = RESEARCH_DIR / f"path2_ub_ml_{args.metalearner}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[PATH-2 ml={args.metalearner}] Saved to {out_path}")
    print(f"  run_id: {summary.get('run_id')}")
    print(f"  Sharpe: {summary.get('Sharpe Ratio')}")
    print(f"  CAGR%:  {summary.get('CAGR (%)')}")
    print(f"  MDD%:   {summary.get('Max Drawdown (%)')}")
    print(f"  Vol%:   {summary.get('Volatility (%)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
