"""
scripts/run_path2_revalidation.py
==================================
Phase 2.10d Path 2 + walk-forward re-validation under the determinism
harness (scripts/run_isolated.py's `isolated()` context manager).

C1 — Universe-B re-validation (3 cells × 3 runs each = 9 q2 backtests):
  C1.0  floors=off  ML=off    (UB anchor)
  C1.1  floors=on   ML=off    (floors only)
  C1.2  floors=on   ML=on     (floors + ML — the breakthrough)

C2 — Walk-forward re-validation (3 folds × 3 runs each = 9 backtests):
  fold 2022: train 2021+2023+2024, test 2022, ML=on, floors=on
  fold 2023: train 2021+2022+2024, test 2023, ML=on, floors=on
  fold 2024: train 2021+2022+2023, test 2024, ML=on, floors=on

For each cell/fold, three same-config runs under `isolated()` produce
bit-identical canon md5 (Sharpe range ~0).

All edits to alpha_settings.prod.json are in-process, written before
each cell, so the harness sees a static config when it runs the
backtest. The original config is restored at end of each task.

Usage:
  PYTHONHASHSEED=0 python -m scripts.run_path2_revalidation --task c1
  PYTHONHASHSEED=0 python -m scripts.run_path2_revalidation --task c2
  PYTHONHASHSEED=0 python -m scripts.run_path2_revalidation --task c1 --runs 3
  PYTHONHASHSEED=0 python -m scripts.run_path2_revalidation --task c1 --runs 1 --cells C1.2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Re-exec under PYTHONHASHSEED=0 if not set (mirrors run_isolated.py guard)
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.run_path2_revalidation", *sys.argv[1:]])

from orchestration.mode_controller import ModeController
from core.benchmark import compute_multi_benchmark_metrics
from scripts.run_isolated import isolated, save_anchor, ISOLATED_ANCHOR
from scripts.run_oos_validation import sample_universe_b


CONFIG_PATH = ROOT / "config" / "alpha_settings.prod.json"
TRADES_DIR = ROOT / "data" / "trade_logs"
RESEARCH_DIR = ROOT / "data" / "research"


# Five edges with class-level DEFAULT_MIN_ADV_USD per Path 2 audit.
# Override with min_adv_usd: 0 in edge_params to disable the floor.
ADV_FLOOR_EDGES = [
    "atr_breakout_v1",
    "momentum_edge_v1",
    "volume_anomaly_v1",
    "herding_v1",
    "gap_fill_v1",
]


def write_config(metalearner_on: bool, floors_on: bool) -> None:
    """Edit alpha_settings.prod.json in place: set metalearner.enabled
    and override edge_params.min_adv_usd=0 for the 5 ADV-floor edges
    when floors_on=False.
    """
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["metalearner"] = {
        "enabled": bool(metalearner_on),
        "profile_name": "balanced",
        "contribution_weight": 0.1,
    }
    edge_params = dict(cfg.get("edge_params", {}))
    if not floors_on:
        for edge in ADV_FLOOR_EDGES:
            existing = dict(edge_params.get(edge, {}))
            existing["min_adv_usd"] = 0
            edge_params[edge] = existing
    else:
        # Floors on: clear any per-edge min_adv_usd override (let class
        # default reign). Idempotent if no override existed.
        for edge in ADV_FLOOR_EDGES:
            if edge in edge_params and "min_adv_usd" in edge_params[edge]:
                del edge_params[edge]["min_adv_usd"]
                if not edge_params[edge]:
                    del edge_params[edge]
    cfg["edge_params"] = edge_params
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def find_run_id(before: set) -> Optional[str]:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    cands = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    cands.sort(key=lambda x: x[1], reverse=True)
    return cands[0][0].name


def trades_canon_md5(run_id: str) -> str:
    p = TRADES_DIR / run_id / f"trades_{run_id}.csv"
    if not p.exists():
        return "(missing)"
    try:
        df = pd.read_csv(p)
        for col in ("run_id", "meta"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=False).values.tobytes()
        ).hexdigest()
    except Exception as e:
        return f"(error: {e})"


def attach_benchmarks(summary: dict, start: str, end: str) -> dict:
    multi = compute_multi_benchmark_metrics(start=start, end=end)
    summary["benchmarks"] = {
        name: {
            "sharpe": round(bm.sharpe, 3),
            "cagr_pct": round(bm.cagr * 100, 2),
            "mdd_pct": round(bm.mdd * 100, 2),
            "vol_pct": round(bm.vol * 100, 2),
        }
        for name, bm in multi.items()
    }
    return summary


def run_q2_under_harness(label: str) -> dict:
    """Single Universe-B (q2) backtest under isolated() context."""
    print(f"[{label}] starting q2 backtest")
    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    with isolated():
        mc = ModeController(ROOT, env="prod")
        prod_tickers = set(mc.cfg_bt["tickers"])
        ub_tickers = sample_universe_b(prod_tickers, n_sample=50, seed=42)
        mc.cfg_bt["tickers"] = ub_tickers
        summary = mc.run_backtest(
            mode="prod", fresh=False, no_governor=False, reset_governor=True,
            alpha_debug=False,
        )
    run_id = find_run_id(before) or "?"
    return {
        "run_id": run_id,
        "Sharpe Ratio": summary.get("Sharpe Ratio"),
        "CAGR (%)": summary.get("CAGR (%)"),
        "Max Drawdown (%)": summary.get("Max Drawdown (%)"),
        "Volatility (%)": summary.get("Volatility (%)"),
        "Win Rate (%)": summary.get("Win Rate (%)"),
        "Net Profit": summary.get("Net Profit"),
        "trades_canon_md5": trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
    }


def run_single_year_under_harness(test_year: int, label: str) -> dict:
    """Single-year prod-109 backtest under isolated() context."""
    print(f"[{label}] starting single-year backtest {test_year}")
    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    with isolated():
        mc = ModeController(ROOT, env="prod")
        summary = mc.run_backtest(
            mode="prod", fresh=False, no_governor=False, reset_governor=True,
            alpha_debug=False,
            override_start=f"{test_year}-01-01", override_end=f"{test_year}-12-31",
        )
    run_id = find_run_id(before) or "?"
    return {
        "run_id": run_id,
        "Sharpe Ratio": summary.get("Sharpe Ratio"),
        "CAGR (%)": summary.get("CAGR (%)"),
        "Max Drawdown (%)": summary.get("Max Drawdown (%)"),
        "Volatility (%)": summary.get("Volatility (%)"),
        "Win Rate (%)": summary.get("Win Rate (%)"),
        "Net Profit": summary.get("Net Profit"),
        "trades_canon_md5": trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
    }


def cell_runs(cell: str, n_runs: int, runner_fn, runner_args: tuple = ()) -> dict:
    runs = []
    for i in range(n_runs):
        r = runner_fn(*runner_args, label=f"{cell}.run{i+1}")
        print(f"[{cell}.run{i+1}] Sharpe={r['Sharpe Ratio']}, "
              f"canon_md5={r['trades_canon_md5'][:16]}")
        runs.append(r)
    sharpes = [r["Sharpe Ratio"] for r in runs if r["Sharpe Ratio"] is not None]
    canons = [r["trades_canon_md5"] for r in runs]
    sharpe_range = max(sharpes) - min(sharpes) if sharpes else 0
    canon_unique = len(set(canons))
    return {
        "cell": cell,
        "n_runs": n_runs,
        "runs": runs,
        "sharpes": sharpes,
        "sharpe_range": sharpe_range,
        "canon_unique": canon_unique,
        "deterministic": (sharpe_range <= 0.001) and (canon_unique == 1),
    }


# ---------------------------------------------------------------------------
# C1 — Universe-B 3 cells × 3 runs
# ---------------------------------------------------------------------------

def task_c1(n_runs: int, restrict_cells: Optional[list]) -> dict:
    cells = [
        ("C1.0", False, False, "floors=off, ML=off"),
        ("C1.1", True, False, "floors=on,  ML=off"),
        ("C1.2", True, True, "floors=on,  ML=on"),
    ]
    if restrict_cells:
        cells = [c for c in cells if c[0] in restrict_cells]

    results = {}
    for cell, floors_on, ml_on, desc in cells:
        print(f"\n========== {cell}: {desc} ==========")
        write_config(metalearner_on=ml_on, floors_on=floors_on)
        out = cell_runs(cell, n_runs, run_q2_under_harness)
        out["floors_on"] = floors_on
        out["metalearner_on"] = ml_on
        out["description"] = desc
        # benchmarks once per cell
        if out["runs"] and out["runs"][0]["Sharpe Ratio"] is not None:
            attach_benchmarks(out, "2021-01-01", "2024-12-31")
        results[cell] = out

    return {
        "task": "c1_universe_b_revalidation",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "n_runs_per_cell": n_runs,
        "cells": results,
    }


# ---------------------------------------------------------------------------
# C2 — Walk-forward 3 folds × 3 runs
# ---------------------------------------------------------------------------

SOURCE_TRAIN_RUN = "abf68c8e-1384-4db4-822c-d65894af70a1"


def build_filtered_run(test_year: int) -> str:
    src = TRADES_DIR / SOURCE_TRAIN_RUN
    new_uuid = f"c2rev-fold-{test_year}-{uuid.uuid4().hex[:8]}"
    dst = TRADES_DIR / new_uuid
    dst.mkdir(parents=True, exist_ok=False)
    trades = pd.read_csv(src / "trades.csv")
    trades["ts"] = pd.to_datetime(trades["timestamp"])
    trades = trades[trades["ts"].dt.year != test_year].drop(columns=["ts"])
    trades.to_csv(dst / "trades.csv", index=False)
    snaps = pd.read_csv(src / "portfolio_snapshots.csv")
    snaps["ts"] = pd.to_datetime(snaps["timestamp"])
    snaps = snaps[snaps["ts"].dt.year != test_year].drop(columns=["ts"])
    snaps.to_csv(dst / "portfolio_snapshots.csv", index=False)
    print(f"[C2] Built fold dir {new_uuid}: {len(trades)} trades")
    return new_uuid


def retrain_metalearner_on_fold(filtered_run_id: str) -> dict:
    cmd = [
        sys.executable, "-m", "scripts.train_metalearner",
        "--run-id", filtered_run_id, "--profile", "balanced",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"[C2] Train STDERR:\n{result.stderr[-500:]}")
        raise RuntimeError(f"Training failed for fold {filtered_run_id}")
    print(f"[C2] training stdout tail: {result.stdout[-300:]}")
    from engines.engine_a_alpha.metalearner import MetaLearner
    ml = MetaLearner.load(profile_name="balanced")
    return {
        "n_train_samples": ml.n_train_samples,
        "train_score_r2": ml.train_metadata.get("train_score_r2"),
    }


def task_c2(n_runs: int, restrict_folds: Optional[list]) -> dict:
    # All C2 cells: floors on, ML on
    write_config(metalearner_on=True, floors_on=True)

    folds = [2022, 2023, 2024]
    if restrict_folds:
        folds = [f for f in folds if str(f) in restrict_folds]

    results = {}
    for year in folds:
        cell = f"C2.fold{year}"
        print(f"\n========== {cell}: train 3-of-4-years, test {year} ==========")
        # 1. Build filtered training run (deterministic with seed inside uuid)
        filtered_id = build_filtered_run(year)
        # 2. Retrain metalearner on that fold
        train_meta = retrain_metalearner_on_fold(filtered_id)
        print(f"[{cell}] retrained: {train_meta['n_train_samples']} samples, "
              f"R²={train_meta['train_score_r2']:.3f}")
        # 3. Run N times under harness
        out = cell_runs(cell, n_runs, run_single_year_under_harness, runner_args=(year,))
        out["test_year"] = year
        out["training_excluded_year"] = year
        out["training_run_id"] = filtered_id
        out["n_train_samples"] = train_meta["n_train_samples"]
        out["train_score_r2"] = train_meta["train_score_r2"]
        if out["runs"] and out["runs"][0]["Sharpe Ratio"] is not None:
            attach_benchmarks(out, f"{year}-01-01", f"{year}-12-31")
        results[cell] = out

    return {
        "task": "c2_walkforward_revalidation",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "n_runs_per_fold": n_runs,
        "folds": results,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["c1", "c2"], required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cells", default=None,
                        help="Restrict to specific cell ids (comma-separated, e.g. C1.2)")
    parser.add_argument("--folds", default=None,
                        help="Restrict to specific test years (comma-separated, e.g. 2024)")
    args = parser.parse_args()

    if not ISOLATED_ANCHOR.exists():
        print("[C-rev] No isolation anchor — run `python -m scripts.run_isolated --save-anchor` first.",
              file=sys.stderr)
        return 1

    cells = args.cells.split(",") if args.cells else None
    folds = args.folds.split(",") if args.folds else None

    # Backup config so we can restore at end
    config_backup = CONFIG_PATH.read_text()
    try:
        if args.task == "c1":
            summary = task_c1(args.runs, cells)
            out_path = RESEARCH_DIR / "c1_path2_revalidation.json"
        else:
            summary = task_c2(args.runs, folds)
            out_path = RESEARCH_DIR / "c2_walkforward_revalidation.json"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\n[C-rev] Saved to {out_path}")
    finally:
        # Restore the original config (no leaked metalearner.enabled or
        # min_adv_usd overrides)
        CONFIG_PATH.write_text(config_backup)
        print("[C-rev] Restored alpha_settings.prod.json to pre-task state")

    return 0


if __name__ == "__main__":
    sys.exit(main())
