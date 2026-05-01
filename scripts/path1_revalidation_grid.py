"""
scripts/path1_revalidation_grid.py
==================================
Phase 2.10d Path 1 ship-state re-validation under the determinism harness.

Runs a 4-cell × 3-run grid on 2025 OOS prod-109:

| Cell  | fill_share_cap | metalearner.enabled |
|-------|----------------|---------------------|
| A1.0  | 0.25           | false (anchor)      |
| A1.1  | 0.20           | false (cap-only)    |
| A1.2  | 0.25           | true  (ML-only)     |
| A1.3  | 0.20           | true  (ship state)  |

For each cell:
  1. Patch config/alpha_settings.prod.json with the cell's (cap, ML).
  2. Run scripts.run_isolated.isolated() 3 times around 2025 Q1 OOS.
  3. Capture Sharpe, CAGR, MDD, vol, win-rate + trades_canon_md5 per run.
  4. Restore config/alpha_settings.prod.json from backup.

Within-cell variance MUST be 0 if the harness is working — that's the
4-23-floor invariant. Any cell with Sharpe range > 0.02 is a harness
bug; the grid stops and reports.

The isolated anchor (data/governor/_isolated_anchor) is snapshotted
ONCE at the start of the grid so all 4 cells start from the same
governor state. Different cells diverge only via config knobs.

Usage:
  PYTHONHASHSEED=0 python -m scripts.path1_revalidation_grid
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
from typing import List


def _reexec_if_hashseed_unset() -> None:
    """Re-exec with PYTHONHASHSEED=0 if not set. Called only from main()
    so importing this module (e.g. from tests) is side-effect-free."""
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable,
                 [sys.executable, "-m", "scripts.path1_revalidation_grid",
                  *sys.argv[1:]])


ROOT = Path(__file__).resolve().parents[1]
ALPHA_PROD = ROOT / "config" / "alpha_settings.prod.json"
TRADES_DIR = ROOT / "data" / "trade_logs"
RESEARCH_DIR = ROOT / "data" / "research"


CELLS = [
    {"label": "A1.0", "cap": 0.25, "ml": False, "tag": "anchor (cap=0.25, ML=false)"},
    {"label": "A1.1", "cap": 0.20, "ml": False, "tag": "cap-only (cap=0.20, ML=false)"},
    {"label": "A1.2", "cap": 0.25, "ml": True,  "tag": "ML-only (cap=0.25, ML=true)"},
    {"label": "A1.3", "cap": 0.20, "ml": True,  "tag": "ship state (cap=0.20, ML=true)"},
]


def _patch_alpha_config(cap: float, ml: bool) -> None:
    """Mutate alpha_settings.prod.json to set fill_share_cap +
    metalearner.enabled. Other keys preserved verbatim."""
    with open(ALPHA_PROD) as f:
        cfg = json.load(f)
    cfg["fill_share_cap"] = cap
    if "metalearner" not in cfg:
        cfg["metalearner"] = {"profile_name": "balanced", "contribution_weight": 0.1}
    cfg["metalearner"]["enabled"] = bool(ml)
    with open(ALPHA_PROD, "w") as f:
        json.dump(cfg, f, indent=2)


def _trades_canon_md5(run_id: str) -> str:
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


def _find_run_id(before: set[str]) -> str | None:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    candidates = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def _run_one_isolated(start: str, end: str) -> dict:
    """Single 2025 OOS Q1 run wrapped in run_isolated.isolated()."""
    from orchestration.mode_controller import ModeController
    from scripts.run_isolated import isolated

    before = {p.name for p in TRADES_DIR.iterdir()
              if p.is_dir() and p.name != "backup"}
    with isolated():
        mc = ModeController(ROOT, env="prod")
        summary = mc.run_backtest(
            mode="prod", fresh=False, no_governor=False, reset_governor=True,
            alpha_debug=False,
            override_start=start, override_end=end,
        )
    run_id = _find_run_id(before) or "?"
    return {
        "run_id": run_id,
        "sharpe": summary.get("Sharpe Ratio"),
        "cagr_pct": summary.get("CAGR (%)"),
        "mdd_pct": summary.get("Max Drawdown (%)"),
        "vol_pct": summary.get("Volatility (%)"),
        "wr_pct": summary.get("Win Rate (%)"),
        "net_profit": summary.get("Net Profit"),
        "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
    }


def run_cell(cell: dict, runs_per_cell: int, start: str, end: str) -> dict:
    print(f"\n{'=' * 78}")
    print(f"CELL {cell['label']} — {cell['tag']}")
    print(f"{'=' * 78}")

    alpha_bak = ALPHA_PROD.with_suffix(".json.grid_bak")
    shutil.copy(ALPHA_PROD, alpha_bak)
    try:
        _patch_alpha_config(cell["cap"], cell["ml"])
        print(f"[GRID] Patched alpha_settings.prod.json: fill_share_cap={cell['cap']}, "
              f"metalearner.enabled={cell['ml']}")

        runs: List[dict] = []
        for i in range(runs_per_cell):
            print(f"\n----- {cell['label']} run {i + 1} / {runs_per_cell} -----")
            r = _run_one_isolated(start, end)
            runs.append(r)
            print(f"  Sharpe: {r['sharpe']}")
            print(f"  CAGR%:  {r['cagr_pct']}")
            print(f"  MDD%:   {r['mdd_pct']}")
            print(f"  Vol%:   {r['vol_pct']}")
            print(f"  trades_canon_md5: {r['trades_canon_md5']}")
    finally:
        shutil.copy(alpha_bak, ALPHA_PROD)
        alpha_bak.unlink(missing_ok=True)
        print(f"\n[GRID] Restored alpha_settings.prod.json")

    sharpes = [r["sharpe"] for r in runs if r["sharpe"] is not None]
    canons = [r["trades_canon_md5"] for r in runs]
    sharpe_range = (max(sharpes) - min(sharpes)) if sharpes else 0
    canon_unique = len(set(canons))
    print(f"\n[GRID-{cell['label']}] within-cell Sharpe range: {sharpe_range:.4f}")
    print(f"[GRID-{cell['label']}] within-cell canon md5 unique: {canon_unique}/{len(canons)}")
    determinism_ok = sharpe_range <= 0.02 and canon_unique == 1
    print(f"[GRID-{cell['label']}] determinism invariant: "
          f"{'PASS' if determinism_ok else 'FAIL'}")

    return {
        "cell": cell,
        "runs": runs,
        "sharpe_range": sharpe_range,
        "canon_unique": canon_unique,
        "determinism_ok": determinism_ok,
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-per-cell", type=int, default=3)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cell", default=None,
                        help="Optional: run only one cell (e.g. A1.3) for debugging.")
    args = parser.parse_args()

    # Snapshot the isolated anchor ONCE at grid start. All cells reuse it.
    print("[GRID] Saving isolated anchor at grid start (all cells share)...")
    from scripts.run_isolated import save_anchor
    save_anchor()

    cells_to_run = (
        [c for c in CELLS if c["label"] == args.cell] if args.cell else CELLS
    )
    if args.cell and not cells_to_run:
        print(f"[GRID] Unknown cell: {args.cell}", file=sys.stderr)
        return 1

    cell_results = []
    for cell in cells_to_run:
        cell_results.append(run_cell(cell, args.runs_per_cell, args.start, args.end))

        # Halt-on-bug: harness invariant violation in any cell stops the grid.
        if not cell_results[-1]["determinism_ok"]:
            print(f"\n[GRID] HALT — cell {cell['label']} violated the determinism "
                  "invariant. Investigate before continuing the grid.")
            break

    print("\n" + "=" * 78)
    print("GRID SUMMARY")
    print("=" * 78)
    print(f"{'Cell':<6}{'Cap':>6}{'ML':>6}{'Sharpe':>10}{'CAGR%':>8}{'MDD%':>8}"
          f"{'Vol%':>8}{'Range':>8} {'CanonU':>8}  Verdict")
    for cr in cell_results:
        cell = cr["cell"]
        runs = cr["runs"]
        if not runs or not runs[0]["sharpe"]:
            continue
        first = runs[0]
        verdict = "PASS" if cr["determinism_ok"] else "FAIL"
        print(f"{cell['label']:<6}{cell['cap']:>6}{str(cell['ml']):>6}"
              f"{first['sharpe']:>10.4f}{first['cagr_pct']:>8.2f}"
              f"{first['mdd_pct']:>8.2f}{first['vol_pct']:>8.2f}"
              f"{cr['sharpe_range']:>8.4f} {cr['canon_unique']:>8}  {verdict}")

    out = RESEARCH_DIR / "path1_revalidation_grid.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "window": [args.start, args.end],
        "cells": cell_results,
    }, indent=2, default=str))
    print(f"\n[GRID] Saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
