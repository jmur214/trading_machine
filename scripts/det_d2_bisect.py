"""
scripts/det_d2_bisect.py
========================
Determinism investigation D2: bisect which `data/governor/` file
mutation is the source of intra-worktree Sharpe variance.

Method
------
Two reference states must already exist in the worktree:
  - data/governor/_clean_pre_d1/   (pre-D1 state captured from
                                    trading_machine-2's idle copy)
  - the current live data/governor/ (post-D1, "drifted")

For each candidate file F in {edges.yml, edge_weights.json,
regime_edge_performance.json, lifecycle_history.csv}:
  1. Restore the live data/governor/ to match the *drifted* state
     (this is the no-op starting position).
  2. Override only F with its _clean_pre_d1 version.
  3. Run a single 2025 OOS Q1 backtest with --reset-governor.
  4. Record Sharpe, run_id, trades_canon_md5.
  5. Compute Δ Sharpe vs the unmodified-drifted baseline.

Interpretation:
  - If restoring F brings Sharpe close to D1 run-1's value (the clean
    starting Sharpe), F is the (or a) drift driver.
  - If restoring F leaves Sharpe close to D1 run-5's value, F is innocent.
  - If multiple files each individually move Sharpe by a meaningful
    fraction, drift is multi-factor.

Usage:
  PYTHONHASHSEED=0 python -m scripts.det_d2_bisect

Prerequisites:
  - data/governor/_clean_pre_d1/ exists (snapshot of pre-D1 state)
  - D1 has run (current live state is "drifted")
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict


if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.det_d2_bisect", *sys.argv[1:]])


ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "data" / "governor"
CLEAN = GOV / "_clean_pre_d1"
DRIFTED = GOV / "_drifted_post_d1"
TRADES_DIR = ROOT / "data" / "trade_logs"
RESEARCH_DIR = ROOT / "data" / "research"

CANDIDATES = [
    "edges.yml",
    "edge_weights.json",
    "regime_edge_performance.json",
    "lifecycle_history.csv",
]


def md5(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_drifted() -> None:
    """Capture the current live governor state as the 'drifted' anchor."""
    DRIFTED.mkdir(parents=True, exist_ok=True)
    for name in CANDIDATES:
        src = GOV / name
        if src.exists():
            shutil.copy(src, DRIFTED / name)
    print(f"[D2] Drifted state snapshotted: {DRIFTED}")


def restore_from_drifted() -> None:
    """Restore the four candidate files from the drifted snapshot.

    For files absent in DRIFTED, delete the live copy."""
    for name in CANDIDATES:
        src = DRIFTED / name
        dst = GOV / name
        if src.exists():
            shutil.copy(src, dst)
        elif dst.exists():
            dst.unlink()


def override_one_from_clean(file_to_override: str) -> None:
    """After restore_from_drifted(), copy `file_to_override` from CLEAN
    over the live copy. If CLEAN doesn't have the file (e.g. lifecycle_history
    was empty pre-D1), delete the live copy instead."""
    src = CLEAN / file_to_override
    dst = GOV / file_to_override
    if src.exists():
        shutil.copy(src, dst)
    elif dst.exists():
        dst.unlink()


def find_run_id(before: set[str]) -> str | None:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    candidates = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def trades_canon_md5(run_id: str) -> str:
    p = TRADES_DIR / run_id / f"trades_{run_id}.csv"
    if not p.exists():
        return "(missing)"
    try:
        import pandas as pd
        df = pd.read_csv(p)
        for col in ("run_id", "meta"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=False).values.tobytes()
        ).hexdigest()
    except Exception as e:
        return f"(error: {e})"


def run_one(label: str) -> dict:
    """Single 2025 OOS Q1 run. Caller is responsible for governor-state
    setup; this function does not restore."""
    from orchestration.mode_controller import ModeController
    print(f"\n========== {label} ==========")
    print("[D2] live governor hashes pre-run:")
    for name in CANDIDATES:
        print(f"  {name}: {md5(GOV / name)}")

    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    mc = ModeController(ROOT, env="prod")
    summary = mc.run_backtest(
        mode="prod", fresh=False, no_governor=False, reset_governor=True,
        alpha_debug=False,
        override_start="2025-01-01", override_end="2025-12-31",
    )
    run_id = find_run_id(before) or "?"
    return {
        "label": label,
        "run_id": run_id,
        "sharpe": summary.get("Sharpe Ratio"),
        "cagr_pct": summary.get("CAGR (%)"),
        "trades_canon_md5": trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-drifted", action="store_true",
                        help="Capture current live governor state as the "
                             "'drifted_post_d1' anchor and exit.")
    args = parser.parse_args()

    if args.snapshot_drifted:
        snapshot_drifted()
        return 0

    if not CLEAN.exists():
        print(f"[D2] Missing clean anchor at {CLEAN}", file=sys.stderr)
        return 1
    if not DRIFTED.exists():
        print(f"[D2] Missing drifted anchor at {DRIFTED}. Run with "
              "--snapshot-drifted first (after D1 finishes).", file=sys.stderr)
        return 1

    results = []

    # Baseline 1: full drifted state, no override. Sets the run-N benchmark.
    restore_from_drifted()
    results.append(run_one("BASELINE_DRIFTED"))

    # Baseline 2: full clean state. Sets the run-1 benchmark.
    for name in CANDIDATES:
        src = CLEAN / name
        dst = GOV / name
        if src.exists():
            shutil.copy(src, dst)
        elif dst.exists():
            dst.unlink()
    results.append(run_one("BASELINE_CLEAN"))

    # Bisect: drifted state with each candidate restored from clean, one at a time.
    for name in CANDIDATES:
        restore_from_drifted()
        override_one_from_clean(name)
        results.append(run_one(f"OVERRIDE_{name}"))

    # Restore drifted to leave the worktree in a known state.
    restore_from_drifted()

    print("\n========== D2 SUMMARY ==========")
    drifted_sharpe = results[0]["sharpe"]
    clean_sharpe = results[1]["sharpe"]
    print(f"BASELINE_DRIFTED Sharpe: {drifted_sharpe}")
    print(f"BASELINE_CLEAN   Sharpe: {clean_sharpe}")
    print(f"GAP (clean - drifted):   {(clean_sharpe or 0) - (drifted_sharpe or 0):.4f}")
    print()
    print(f"{'Override':<35}{'Sharpe':>10}{'Δ vs drifted':>15}{'Δ vs clean':>15}")
    for r in results[2:]:
        s = r["sharpe"] or 0
        dd = s - (drifted_sharpe or 0)
        dc = s - (clean_sharpe or 0)
        print(f"{r['label']:<35}{s:>10.4f}{dd:>+15.4f}{dc:>+15.4f}")

    out_path = RESEARCH_DIR / "determinism_d2_bisect.json"
    out_path.write_text(json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "results": results,
    }, indent=2))
    print(f"\n[D2] Saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
