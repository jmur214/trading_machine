"""
scripts/walk_forward_factor_edge.py
====================================
Walk-forward validation for `momentum_factor_v1` (and any future factor edges
added at weight > 0 in alpha_settings.prod.json).

Tests whether the in-sample +0.13 Sharpe lift from adding the factor edge
generalizes out-of-sample. The factor signal is a runtime computation
(no historical anchor fit), so OOS deltas are expected to approximate
in-sample deltas modulo window-specific volatility levels.

Mechanism per split:
- Phase 1 (eval ON): factor edge weight = 1.0 in alpha_settings, run backtest
  on eval window with --no-governor.
- Phase 2 (eval OFF): factor edge weight = 0.0, run backtest on eval window.
- Compare Sharpe, CAGR, MDD between the two.

No "training phase" — this edge has no training. Only the eval window matters.
That makes this harness simpler than walk_forward_regime.py / walk_forward_affinity.py.

Backs up alpha_settings.prod.json before mutating; auto-restores on exit
via try/finally.

Usage:
  PYTHONHASHSEED=0 python -m scripts.walk_forward_factor_edge \\
      --eval-start 2024-01-01 --eval-end 2025-12-30
"""

from __future__ import annotations

import os
import sys

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.walk_forward_factor_edge", *sys.argv[1:]])

import argparse
import json
import shutil
from pathlib import Path

from scripts.run_backtest import run_backtest_logic

ROOT = Path(__file__).resolve().parents[1]
ALPHA_CFG = ROOT / "config" / "alpha_settings.prod.json"
ALPHA_CFG_BACKUP = ALPHA_CFG.with_suffix(".json.factor-walkforward-backup")
TRADES_DIR = ROOT / "data" / "trade_logs"

EDGE_ID = "momentum_factor_v1"  # default; override via --edge-id


def backup(p, bp):
    if p.exists():
        shutil.copy(p, bp)


def restore(bp, p):
    if bp.exists():
        shutil.copy(bp, p)


def set_edge_weight(weight: float) -> None:
    cfg = json.loads(ALPHA_CFG.read_text())
    cfg.setdefault("edge_weights", {})[EDGE_ID] = float(weight)
    ALPHA_CFG.write_text(json.dumps(cfg, indent=2))


def latest_run_summary() -> dict:
    run_dirs = [d for d in TRADES_DIR.iterdir() if d.is_dir() and (d / "performance_summary.json").exists()]
    if not run_dirs:
        return {}
    latest = max(run_dirs, key=lambda d: (d / "performance_summary.json").stat().st_mtime)
    return json.loads((latest / "performance_summary.json").read_text())


def run_eval(label: str, edge_weight: float, eval_start: str, eval_end: str) -> dict:
    print(f"\n{'='*60}\n[EVAL — {label}] {EDGE_ID} weight={edge_weight}\n{'='*60}")
    set_edge_weight(edge_weight)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=True, alpha_debug=False,
        override_start=eval_start, override_end=eval_end, discover=False,
    )
    s = latest_run_summary()
    print(f"[EVAL — {label}] Sharpe={s.get('Sharpe Ratio')}  CAGR={s.get('CAGR (%)')}%  MDD={s.get('Max Drawdown (%)')}%  WR={s.get('Win Rate (%)')}%")
    return s


def main() -> int:
    global EDGE_ID
    p = argparse.ArgumentParser(description="Walk-forward validation for any edge by ID.")
    p.add_argument("--edge-id", default=EDGE_ID,
                   help=f"Edge ID to walk-forward (default: {EDGE_ID})")
    p.add_argument("--eval-start", required=True)
    p.add_argument("--eval-end", required=True)
    p.add_argument("--on-weight", type=float, default=1.0,
                   help="Edge weight when ON (default 1.0)")
    args = p.parse_args()
    EDGE_ID = args.edge_id

    backup(ALPHA_CFG, ALPHA_CFG_BACKUP)
    print(f"[SETUP] Backed up {ALPHA_CFG.name} → {ALPHA_CFG_BACKUP.name}")
    print(f"[SETUP] Eval window: {args.eval_start} → {args.eval_end}")

    try:
        on_result = run_eval("FACTOR ON", args.on_weight, args.eval_start, args.eval_end)
        off_result = run_eval("FACTOR OFF", 0.0, args.eval_start, args.eval_end)

        print(f"\n{'='*60}\n[FACTOR EDGE WALK-FORWARD REPORT] OOS {args.eval_start} → {args.eval_end}\n{'='*60}")
        print(f"{'Variant':<24} {'Sharpe':>8} {'CAGR%':>7} {'MDD%':>7} {'WR%':>7}")
        for label, s in [("FACTOR ON", on_result), ("FACTOR OFF", off_result)]:
            print(f"  {label:<22} {s.get('Sharpe Ratio','?'):>8} {s.get('CAGR (%)','?'):>7} {s.get('Max Drawdown (%)','?'):>7} {s.get('Win Rate (%)','?'):>7}")
        if isinstance(on_result.get('Sharpe Ratio'), (int, float)) and isinstance(off_result.get('Sharpe Ratio'), (int, float)):
            delta = on_result['Sharpe Ratio'] - off_result['Sharpe Ratio']
            print(f"\n[DELTA] ON vs OFF OOS Sharpe: {delta:+.3f}")
            if delta > 0.05:
                print("[RESULT] Factor edge adds material Sharpe OOS — generalizes.")
            elif delta > 0:
                print("[RESULT] Factor edge adds marginal Sharpe OOS — within noise band.")
            else:
                print("[RESULT] Factor edge does not add Sharpe OOS on this split.")
        return 0
    finally:
        restore(ALPHA_CFG_BACKUP, ALPHA_CFG)
        print(f"\n[CLEANUP] Restored {ALPHA_CFG.name}")


if __name__ == "__main__":
    sys.exit(main() or 0)
