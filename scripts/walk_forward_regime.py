"""
scripts/walk_forward_regime.py
================================
Walk-forward validation for regime-conditional governor activation.

Train on window A (2021-2022), evaluate on window B (2023-2024) with and
without regime_conditional_enabled. Prints OOS Sharpe delta.

This is the prerequisite check before re-enabling regime-conditional in
production: the current same-window anchor is overfit enough that even
soft-kill regime blending loses to regime-blind trading (see
project_regime_conditional_activation_blocked_2026_04_23.md).

Usage:
  PYTHONHASHSEED=0 python -m scripts.walk_forward_regime
"""

import os
import sys

# PYTHONHASHSEED=0 self-reexec, same pattern as run_deterministic.py
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.walk_forward_regime", *sys.argv[1:]])

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

DEFAULT_TRAIN_START = "2021-01-01"
DEFAULT_TRAIN_END = "2022-12-31"
DEFAULT_EVAL_START = "2023-01-01"
DEFAULT_EVAL_END = "2024-12-31"

# Set by main() from CLI args before phase_train / phase_eval are called.
TRAIN_START = DEFAULT_TRAIN_START
TRAIN_END = DEFAULT_TRAIN_END
EVAL_START = DEFAULT_EVAL_START
EVAL_END = DEFAULT_EVAL_END

TRADES_DIR = ROOT / "data" / "trade_logs"


def backup(path: Path, backup_path: Path) -> None:
    if path.exists():
        shutil.copy(path, backup_path)


def restore(backup_path: Path, path: Path) -> None:
    if backup_path.exists():
        shutil.copy(backup_path, path)


def write_gov_config(**overrides) -> None:
    """Write governor_settings.json with overrides."""
    cfg = json.loads(CFG_PATH.read_text())
    cfg.update(overrides)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))


def latest_run_summary() -> dict:
    """Read performance_summary.json from the most-recently-modified run dir."""
    run_dirs = [d for d in TRADES_DIR.iterdir() if d.is_dir() and (d / "performance_summary.json").exists()]
    if not run_dirs:
        return {}
    latest = max(run_dirs, key=lambda d: (d / "performance_summary.json").stat().st_mtime)
    return json.loads((latest / "performance_summary.json").read_text())


def phase_train() -> None:
    """Phase 1: clean slate, run 2021-2022 with governor on → save OOS-anchor."""
    print(f"\n{'='*60}\n[PHASE 1] TRAIN on {TRAIN_START} → {TRAIN_END}\n{'='*60}")
    # Clear any existing governor state
    if WEIGHTS.exists():
        WEIGHTS.unlink()
    if PERF.exists():
        PERF.unlink()
    # Training MUST have regime_conditional_enabled=True — governor.py:351 only
    # accumulates regime_tracker stats when this flag is on (otherwise the tracker
    # stays empty). With an empty _regime_weights at init, the kill-switch doesn't
    # fire during the training run itself, so this doesn't corrupt the trades used
    # to build the anchor.
    write_gov_config(regime_conditional_enabled=True, disable_sr_threshold=0.0)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=False, alpha_debug=False,
        override_start=TRAIN_START, override_end=TRAIN_END, discover=False,
    )
    # Snapshot the trained state
    shutil.copy(WEIGHTS, WEIGHTS_OOS)
    shutil.copy(PERF, PERF_OOS)
    print(f"[PHASE 1] OOS anchor saved:\n  {WEIGHTS_OOS}\n  {PERF_OOS}")


def phase_eval(label: str, regime_conditional: bool, disable_sr: float) -> dict:
    """Phase 2/3: restore OOS anchor, run 2023-2024 --no-governor with given policy."""
    print(f"\n{'='*60}\n[PHASE EVAL — {label}] regime_conditional={regime_conditional}, disable_sr={disable_sr}\n{'='*60}")
    # Restore trained anchor
    shutil.copy(WEIGHTS_OOS, WEIGHTS)
    shutil.copy(PERF_OOS, PERF)
    # Configure policy
    write_gov_config(regime_conditional_enabled=regime_conditional, disable_sr_threshold=disable_sr)
    # Evaluate (no_governor=True so we don't mutate the anchor mid-run)
    run_backtest_logic(
        env="prod", mode="prod", fresh=False, no_governor=True, alpha_debug=False,
        override_start=EVAL_START, override_end=EVAL_END, discover=False,
    )
    summary = latest_run_summary()
    print(f"[PHASE EVAL — {label}] Sharpe={summary.get('Sharpe Ratio')}  CAGR={summary.get('CAGR (%)')}%  MDD={summary.get('Max Drawdown (%)')}%  WR={summary.get('Win Rate (%)')}%")
    return summary


def main() -> int:
    global TRAIN_START, TRAIN_END, EVAL_START, EVAL_END
    p = argparse.ArgumentParser(description="Walk-forward validation for regime-conditional governor.")
    p.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    p.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    p.add_argument("--eval-start", default=DEFAULT_EVAL_START)
    p.add_argument("--eval-end", default=DEFAULT_EVAL_END)
    args = p.parse_args()
    TRAIN_START = args.train_start
    TRAIN_END = args.train_end
    EVAL_START = args.eval_start
    EVAL_END = args.eval_end

    # Back up everything we touch so we can restore after the walk-forward run
    backup(CFG_PATH, CFG_BACKUP)
    backup(WEIGHTS, WEIGHTS_BACKUP)
    backup(PERF, PERF_BACKUP)
    print(f"[SETUP] Backed up config + governor state to {CFG_BACKUP.name}, {WEIGHTS_BACKUP.name}, {PERF_BACKUP.name}")
    print(f"[SETUP] Train window: {TRAIN_START} → {TRAIN_END}  |  Eval window: {EVAL_START} → {EVAL_END}")

    try:
        phase_train()
        baseline = phase_eval("BASELINE (regime_cond=false)", regime_conditional=False, disable_sr=0.0)
        hard_kill = phase_eval("HARD-KILL (regime_cond=true, sr_thresh=0)", regime_conditional=True, disable_sr=0.0)
        soft_kill = phase_eval("SOFT-KILL (regime_cond=true, sr_thresh=-1000)", regime_conditional=True, disable_sr=-1000.0)

        print(f"\n{'='*60}\n[WALK-FORWARD REPORT] OOS window {EVAL_START} → {EVAL_END}\n{'='*60}")
        print(f"{'Variant':<42} {'Sharpe':>8} {'CAGR%':>7} {'MDD%':>7} {'WR%':>7}")
        for label, s in [("BASELINE  (regime_cond=false)", baseline),
                         ("HARD-KILL (regime_cond=true, sr<=0)", hard_kill),
                         ("SOFT-KILL (regime_cond=true, sr<=-1000)", soft_kill)]:
            print(f"  {label:<40} {s.get('Sharpe Ratio','?'):>8} {s.get('CAGR (%)','?'):>7} {s.get('Max Drawdown (%)','?'):>7} {s.get('Win Rate (%)','?'):>7}")
        print()
        if isinstance(baseline.get('Sharpe Ratio'), (int, float)) and isinstance(soft_kill.get('Sharpe Ratio'), (int, float)):
            delta = soft_kill['Sharpe Ratio'] - baseline['Sharpe Ratio']
            print(f"[DELTA] soft-kill vs baseline OOS Sharpe: {delta:+.3f}")
            if delta > 0:
                print("[RESULT] OOS gain — activation is predictive out-of-sample.")
            else:
                print("[RESULT] No OOS gain — regime-tracker stats don't generalize.")
        return 0
    finally:
        # Always restore original state
        restore(CFG_BACKUP, CFG_PATH)
        restore(WEIGHTS_BACKUP, WEIGHTS)
        restore(PERF_BACKUP, PERF)
        print(f"\n[CLEANUP] Restored original config + governor state")


if __name__ == "__main__":
    sys.exit(main() or 0)
