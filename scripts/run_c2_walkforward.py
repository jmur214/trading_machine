"""
scripts/run_c2_walkforward.py
=============================
Phase 2.11 robustness gate C2 — three-fold hold-one-year-out walk-forward
with the portfolio meta-learner re-trained per fold.

For each test_year in {2022, 2023, 2024}:
  1. Build a filtered training trade-log (source run abf68c8e, excluding
     test_year rows). Write to a temp run dir.
  2. Re-train the metalearner via subprocess on the filtered run. Saves
     to data/governor/metalearner_balanced.pkl (this worktree's per-agent
     copy — does not contaminate other agents).
  3. Run a single-year backtest of test_year with metalearner.enabled=true
     in alpha_settings.prod.json (caller must have flipped this).
  4. Capture Sharpe + supporting metrics.

Output: data/research/c2_walkforward_results.json with per-fold + summary.

Usage: python -m scripts.run_c2_walkforward
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.mode_controller import ModeController
from core.benchmark import compute_multi_benchmark_metrics


SOURCE_RUN_ID = "abf68c8e-1384-4db4-822c-d65894af70a1"
TEST_YEARS = [2022, 2023, 2024]
RESEARCH_DIR = ROOT / "data" / "research"


def find_run_id(before_set: set) -> str:
    after = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir()}
    new = after - before_set
    if not new:
        return ""
    candidates = [(p, p.stat().st_mtime) for p in (ROOT / "data" / "trade_logs").iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def build_filtered_run(test_year: int) -> str:
    """Copy the source run's trades + snapshots, filter out test_year rows,
    save under a fresh UUID under data/trade_logs/. Returns the new UUID.

    Excluding test_year drops a contiguous block of training data; the
    metalearner training script's date-aware feature build will skip
    fold boundaries where forward returns can't be computed (NaN drop).
    """
    src = ROOT / "data" / "trade_logs" / SOURCE_RUN_ID
    new_uuid = f"c2-fold-{test_year}-{uuid.uuid4().hex[:8]}"
    dst = ROOT / "data" / "trade_logs" / new_uuid
    dst.mkdir(parents=True, exist_ok=False)

    trades = pd.read_csv(src / "trades.csv")
    trades["ts"] = pd.to_datetime(trades["timestamp"])
    trades = trades[trades["ts"].dt.year != test_year].drop(columns=["ts"])
    trades.to_csv(dst / "trades.csv", index=False)

    snaps = pd.read_csv(src / "portfolio_snapshots.csv")
    snaps["ts"] = pd.to_datetime(snaps["timestamp"])
    snaps = snaps[snaps["ts"].dt.year != test_year].drop(columns=["ts"])
    snaps.to_csv(dst / "portfolio_snapshots.csv", index=False)

    print(f"[C2] Built fold dir {new_uuid}: {len(trades)} trades, {len(snaps)} snapshots "
          f"(excluding year {test_year})")
    return new_uuid


def retrain_metalearner(filtered_run_id: str) -> dict:
    """Invoke train_metalearner.py on the filtered run. Returns the
    per-fold metadata captured from the saved model.
    """
    cmd = [
        sys.executable, "-m", "scripts.train_metalearner",
        "--run-id", filtered_run_id,
        "--profile", "balanced",
    ]
    print(f"[C2] Retraining: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        print(f"[C2] Train STDERR:\n{result.stderr}")
        raise RuntimeError(f"Training failed for fold rooted at {filtered_run_id}")
    print(f"[C2] Training stdout tail:\n{result.stdout[-500:]}")

    # Load the just-trained model to capture metadata
    from engines.engine_a_alpha.metalearner import MetaLearner
    ml = MetaLearner.load(profile_name="balanced")
    return {
        "n_train_samples": ml.n_train_samples,
        "feature_names": ml.feature_names,
        "train_score_r2": ml.train_metadata.get("train_score_r2"),
    }


def backtest_year(test_year: int) -> dict:
    """Backtest single-year window with the currently-loaded metalearner."""
    start = f"{test_year}-01-01"
    end = f"{test_year}-12-31"
    print(f"[C2] Backtest {test_year} ({start} → {end}) with ML-on")

    before = {p.name for p in (ROOT / "data" / "trade_logs").iterdir() if p.is_dir() and p.name != "backup"}

    mc = ModeController(ROOT, env="prod")
    summary = mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_start=start,
        override_end=end,
    )

    summary["run_id"] = find_run_id(before)
    summary["window"] = f"{start} to {end}"
    summary["test_year"] = test_year
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
    fold_results = []

    for test_year in TEST_YEARS:
        print(f"\n========== FOLD: test_year={test_year} ==========")
        filtered_id = build_filtered_run(test_year)

        train_meta = retrain_metalearner(filtered_id)
        bt = backtest_year(test_year)
        bt = attach_benchmarks(bt, f"{test_year}-01-01", f"{test_year}-12-31")

        fold = {
            "test_year": test_year,
            "training_excluded_year": test_year,
            "training_run_id": filtered_id,
            "n_train_samples": train_meta["n_train_samples"],
            "train_score_r2": train_meta["train_score_r2"],
            "test_run_id": bt.get("run_id"),
            "Sharpe Ratio": bt.get("Sharpe Ratio"),
            "CAGR (%)": bt.get("CAGR (%)"),
            "Max Drawdown (%)": bt.get("Max Drawdown (%)"),
            "Volatility (%)": bt.get("Volatility (%)"),
            "Win Rate (%)": bt.get("Win Rate (%)"),
            "Net Profit": bt.get("Net Profit"),
            "benchmarks": bt.get("benchmarks"),
        }
        fold_results.append(fold)
        print(f"[C2] FOLD {test_year} done: Sharpe={fold['Sharpe Ratio']}, "
              f"CAGR={fold['CAGR (%)']}%")

    sharpes = [f["Sharpe Ratio"] for f in fold_results if f["Sharpe Ratio"] is not None]
    n_pos = sum(1 for s in sharpes if s > 0)
    mean_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0.0

    summary = {
        "task": "c2_walkforward",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source_training_run": SOURCE_RUN_ID,
        "test_years": TEST_YEARS,
        "n_folds": len(fold_results),
        "n_positive_sharpe": n_pos,
        "mean_sharpe": round(mean_sharpe, 3),
        "pass_criterion": "≥2/3 folds Sharpe>0 AND mean Sharpe ≥ 0.5",
        "passes": (n_pos >= 2) and (mean_sharpe >= 0.5),
        "folds": fold_results,
    }

    out_path = RESEARCH_DIR / "c2_walkforward_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[C2] Saved to {out_path}")
    print(f"[C2] Per-fold Sharpes: {[round(s, 3) for s in sharpes]}")
    print(f"[C2] Mean Sharpe: {summary['mean_sharpe']}")
    print(f"[C2] Pass: {summary['passes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
