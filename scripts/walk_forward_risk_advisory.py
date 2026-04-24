"""
scripts/walk_forward_risk_advisory.py
=====================================
Walk-forward validation for `risk_advisory_enabled` in RiskConfig.

This is the largest in-sample contributor in the audit (-0.24 Sharpe when
disabled). It bundles four runtime mechanisms: suggested_max_positions,
suggested_exposure_cap (order-level), risk_scalar (0.3-1.2x ATR sizing),
and correlation-regime sector cap. All four derive from Engine E advisory
which is runtime-current-state-driven — so the expectation is that OOS
and in-sample deltas should agree (modulo window-specific vol levels).

If they don't agree, the "runtime-state features are trustworthy" heuristic
needs revision.

Usage:
  PYTHONHASHSEED=0 python -m scripts.walk_forward_risk_advisory \\
      --train-start 2021-01-01 --train-end 2023-12-31 \\
      --eval-start  2024-01-01 --eval-end  2025-12-30
"""

import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.walk_forward_risk_advisory", *sys.argv[1:]])

import argparse
import json
import shutil
from pathlib import Path

from scripts.run_backtest import run_backtest_logic

ROOT = Path(__file__).resolve().parents[1]
GOV_DIR = ROOT / "data" / "governor"
GOV_CFG = ROOT / "config" / "governor_settings.json"
RISK_CFG = ROOT / "config" / "risk_settings.prod.json"
WEIGHTS = GOV_DIR / "edge_weights.json"
PERF = GOV_DIR / "regime_edge_performance.json"
WEIGHTS_OOS = GOV_DIR / "edge_weights.json.oos-window-a"
PERF_OOS = GOV_DIR / "regime_edge_performance.json.oos-window-a"
GOV_CFG_BACKUP = GOV_CFG.with_suffix(".json.walk-forward-backup")
RISK_CFG_BACKUP = RISK_CFG.with_suffix(".json.walk-forward-backup")
WEIGHTS_BACKUP = WEIGHTS.with_suffix(".json.walk-forward-backup")
PERF_BACKUP = PERF.with_suffix(".json.walk-forward-backup")

TRADES_DIR = ROOT / "data" / "trade_logs"


def backup(p, bp):
    if p.exists(): shutil.copy(p, bp)


def restore(bp, p):
    if bp.exists(): shutil.copy(bp, p)


def write_cfg(path: Path, **overrides) -> None:
    cfg = json.loads(path.read_text())
    cfg.update(overrides)
    path.write_text(json.dumps(cfg, indent=2))


def latest_run_summary() -> dict:
    run_dirs = [d for d in TRADES_DIR.iterdir() if d.is_dir() and (d / "performance_summary.json").exists()]
    if not run_dirs:
        return {}
    latest = max(run_dirs, key=lambda d: (d / "performance_summary.json").stat().st_mtime)
    return json.loads((latest / "performance_summary.json").read_text())


def phase_train(train_start: str, train_end: str) -> None:
    print(f"\n{'='*60}\n[PHASE 1] TRAIN on {train_start} → {train_end}\n{'='*60}")
    if WEIGHTS.exists(): WEIGHTS.unlink()
    if PERF.exists(): PERF.unlink()
    # Training uses the default (full) advisory path — we're building anchor,
    # not testing the advisory toggle during train.
    write_cfg(GOV_CFG, regime_conditional_enabled=True, disable_sr_threshold=0.0, learned_affinity_enabled=True)
    write_cfg(RISK_CFG, risk_advisory_enabled=True)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=False, alpha_debug=False,
        override_start=train_start, override_end=train_end, discover=False,
    )
    shutil.copy(WEIGHTS, WEIGHTS_OOS)
    shutil.copy(PERF, PERF_OOS)
    print(f"[PHASE 1] OOS anchor saved.")


def phase_eval(label: str, risk_advisory_enabled: bool, eval_start: str, eval_end: str) -> dict:
    print(f"\n{'='*60}\n[PHASE EVAL — {label}] risk_advisory_enabled={risk_advisory_enabled}\n{'='*60}")
    shutil.copy(WEIGHTS_OOS, WEIGHTS)
    shutil.copy(PERF_OOS, PERF)
    # Keep other features at baseline (regime_cond OFF, affinity ON) so we
    # isolate risk_advisory's contribution.
    write_cfg(GOV_CFG, regime_conditional_enabled=False, disable_sr_threshold=0.0, learned_affinity_enabled=True)
    write_cfg(RISK_CFG, risk_advisory_enabled=risk_advisory_enabled)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=True, alpha_debug=False,
        override_start=eval_start, override_end=eval_end, discover=False,
    )
    summary = latest_run_summary()
    print(f"[PHASE EVAL — {label}] Sharpe={summary.get('Sharpe Ratio')}  CAGR={summary.get('CAGR (%)')}%  MDD={summary.get('Max Drawdown (%)')}%  WR={summary.get('Win Rate (%)')}%")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-forward validation for risk_advisory_enabled.")
    p.add_argument("--train-start", required=True)
    p.add_argument("--train-end", required=True)
    p.add_argument("--eval-start", required=True)
    p.add_argument("--eval-end", required=True)
    args = p.parse_args()

    backup(GOV_CFG, GOV_CFG_BACKUP)
    backup(RISK_CFG, RISK_CFG_BACKUP)
    backup(WEIGHTS, WEIGHTS_BACKUP)
    backup(PERF, PERF_BACKUP)
    print(f"[SETUP] Backed up configs + governor state.")
    print(f"[SETUP] Train: {args.train_start} → {args.train_end}  |  Eval: {args.eval_start} → {args.eval_end}")

    try:
        phase_train(args.train_start, args.train_end)
        adv_on = phase_eval("ADVISORY ON", True, args.eval_start, args.eval_end)
        adv_off = phase_eval("ADVISORY OFF", False, args.eval_start, args.eval_end)

        print(f"\n{'='*60}\n[WALK-FORWARD RISK_ADVISORY REPORT] OOS window {args.eval_start} → {args.eval_end}\n{'='*60}")
        print(f"{'Variant':<24} {'Sharpe':>8} {'CAGR%':>7} {'MDD%':>7} {'WR%':>7}")
        for label, s in [("ADVISORY ON", adv_on), ("ADVISORY OFF", adv_off)]:
            print(f"  {label:<22} {s.get('Sharpe Ratio','?'):>8} {s.get('CAGR (%)','?'):>7} {s.get('Max Drawdown (%)','?'):>7} {s.get('Win Rate (%)','?'):>7}")
        if isinstance(adv_on.get('Sharpe Ratio'), (int, float)) and isinstance(adv_off.get('Sharpe Ratio'), (int, float)):
            delta = adv_on['Sharpe Ratio'] - adv_off['Sharpe Ratio']
            print(f"\n[DELTA] ON vs OFF OOS Sharpe: {delta:+.3f}")
            if delta > 0:
                print("[RESULT] Risk_advisory adds Sharpe OOS — in-sample assumption validated.")
            else:
                print("[RESULT] Risk_advisory costs Sharpe OOS — needs revisit.")
        return 0
    finally:
        restore(GOV_CFG_BACKUP, GOV_CFG)
        restore(RISK_CFG_BACKUP, RISK_CFG)
        restore(WEIGHTS_BACKUP, WEIGHTS)
        restore(PERF_BACKUP, PERF)
        print(f"\n[CLEANUP] Restored original configs + governor state")


if __name__ == "__main__":
    sys.exit(main() or 0)
