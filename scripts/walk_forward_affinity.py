"""
scripts/walk_forward_affinity.py
================================
Walk-forward validation for `learned_affinity_enabled` in GovernorConfig.

Tests whether the learned-affinity advisory (0.3-1.5x edge-category multiplier
sourced from regime_tracker per-category stats) actually generalizes OOS, or
whether its +0.11 in-sample Sharpe contribution is circular fitting (same
concern as the per-edge-per-regime kill-switch which failed 2 of 3 OOS splits).

Per split: phase 1 trains regime_tracker on a window; phase 2/3 restore that
anchor and evaluate affinity-ON vs affinity-OFF on held-out window.

Usage:
  PYTHONHASHSEED=0 python -m scripts.walk_forward_affinity \\
      --train-start 2021-01-01 --train-end 2023-12-31 \\
      --eval-start  2024-01-01 --eval-end  2025-12-30
"""

import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.walk_forward_affinity", *sys.argv[1:]])

import argparse
import json
import shutil
from pathlib import Path

from scripts.run_backtest import run_backtest_logic

ROOT = Path(__file__).resolve().parents[1]
GOV_DIR = ROOT / "data" / "governor"
CFG_PATH = ROOT / "config" / "governor_settings.json"
WEIGHTS = GOV_DIR / "edge_weights.json"
PERF = GOV_DIR / "regime_edge_performance.json"
WEIGHTS_OOS = GOV_DIR / "edge_weights.json.oos-window-a"
PERF_OOS = GOV_DIR / "regime_edge_performance.json.oos-window-a"
CFG_BACKUP = CFG_PATH.with_suffix(".json.walk-forward-backup")
WEIGHTS_BACKUP = WEIGHTS.with_suffix(".json.walk-forward-backup")
PERF_BACKUP = PERF.with_suffix(".json.walk-forward-backup")

TRADES_DIR = ROOT / "data" / "trade_logs"


def backup(p: Path, bp: Path) -> None:
    if p.exists():
        shutil.copy(p, bp)


def restore(bp: Path, p: Path) -> None:
    if bp.exists():
        shutil.copy(bp, p)


def write_gov_config(**overrides) -> None:
    cfg = json.loads(CFG_PATH.read_text())
    cfg.update(overrides)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))


def latest_run_summary() -> dict:
    run_dirs = [d for d in TRADES_DIR.iterdir() if d.is_dir() and (d / "performance_summary.json").exists()]
    if not run_dirs:
        return {}
    latest = max(run_dirs, key=lambda d: (d / "performance_summary.json").stat().st_mtime)
    return json.loads((latest / "performance_summary.json").read_text())


def phase_train(train_start: str, train_end: str) -> None:
    print(f"\n{'='*60}\n[PHASE 1] TRAIN regime_tracker on {train_start} → {train_end}\n{'='*60}")
    if WEIGHTS.exists():
        WEIGHTS.unlink()
    if PERF.exists():
        PERF.unlink()
    # regime_conditional_enabled=True during training to accumulate regime stats.
    # affinity doesn't affect training (it's read downstream during eval).
    write_gov_config(regime_conditional_enabled=True, disable_sr_threshold=0.0, learned_affinity_enabled=True)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=False, alpha_debug=False,
        override_start=train_start, override_end=train_end, discover=False,
    )
    shutil.copy(WEIGHTS, WEIGHTS_OOS)
    shutil.copy(PERF, PERF_OOS)
    print(f"[PHASE 1] OOS anchor saved.")


def phase_eval(label: str, affinity_enabled: bool, eval_start: str, eval_end: str) -> dict:
    print(f"\n{'='*60}\n[PHASE EVAL — {label}] learned_affinity_enabled={affinity_enabled}\n{'='*60}")
    shutil.copy(WEIGHTS_OOS, WEIGHTS)
    shutil.copy(PERF_OOS, PERF)
    # regime_conditional stays false in eval (we are NOT testing kill-switch here).
    # Only affinity toggles.
    write_gov_config(regime_conditional_enabled=False, disable_sr_threshold=0.0, learned_affinity_enabled=affinity_enabled)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=True, alpha_debug=False,
        override_start=eval_start, override_end=eval_end, discover=False,
    )
    summary = latest_run_summary()
    print(f"[PHASE EVAL — {label}] Sharpe={summary.get('Sharpe Ratio')}  CAGR={summary.get('CAGR (%)')}%  MDD={summary.get('Max Drawdown (%)')}%  WR={summary.get('Win Rate (%)')}%")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-forward validation for learned_affinity.")
    p.add_argument("--train-start", required=True)
    p.add_argument("--train-end", required=True)
    p.add_argument("--eval-start", required=True)
    p.add_argument("--eval-end", required=True)
    args = p.parse_args()

    backup(CFG_PATH, CFG_BACKUP)
    backup(WEIGHTS, WEIGHTS_BACKUP)
    backup(PERF, PERF_BACKUP)
    print(f"[SETUP] Backed up config + governor state.")
    print(f"[SETUP] Train: {args.train_start} → {args.train_end}  |  Eval: {args.eval_start} → {args.eval_end}")

    try:
        phase_train(args.train_start, args.train_end)
        affinity_on = phase_eval("AFFINITY ON", True, args.eval_start, args.eval_end)
        affinity_off = phase_eval("AFFINITY OFF", False, args.eval_start, args.eval_end)

        print(f"\n{'='*60}\n[WALK-FORWARD AFFINITY REPORT] OOS window {args.eval_start} → {args.eval_end}\n{'='*60}")
        print(f"{'Variant':<24} {'Sharpe':>8} {'CAGR%':>7} {'MDD%':>7} {'WR%':>7}")
        for label, s in [("AFFINITY ON", affinity_on), ("AFFINITY OFF", affinity_off)]:
            print(f"  {label:<22} {s.get('Sharpe Ratio','?'):>8} {s.get('CAGR (%)','?'):>7} {s.get('Max Drawdown (%)','?'):>7} {s.get('Win Rate (%)','?'):>7}")
        if isinstance(affinity_on.get('Sharpe Ratio'), (int, float)) and isinstance(affinity_off.get('Sharpe Ratio'), (int, float)):
            delta = affinity_on['Sharpe Ratio'] - affinity_off['Sharpe Ratio']
            print(f"\n[DELTA] affinity-ON vs affinity-OFF OOS Sharpe: {delta:+.3f}")
            if delta > 0:
                print("[RESULT] Affinity adds Sharpe OOS — generalizes.")
            else:
                print("[RESULT] Affinity costs Sharpe OOS — likely circular fit.")
        return 0
    finally:
        restore(CFG_BACKUP, CFG_PATH)
        restore(WEIGHTS_BACKUP, WEIGHTS)
        restore(PERF_BACKUP, PERF)
        print(f"\n[CLEANUP] Restored original config + governor state")


if __name__ == "__main__":
    sys.exit(main() or 0)
