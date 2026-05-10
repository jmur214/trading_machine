"""
scripts/run_engine_e_hmm_ab.py
==============================
Engine E HMM Variant C enable A/B (T-2026-05-09-015).

Lighter version of T-2026-05-08-002's substrate-honest harness — only
two cells (A vs B), only the HMM flag varies, no other axis changes.

  Cell A: 6 edges (T-002's ARM1_EDGES), HMM OFF.
  Cell B: 6 edges (same), HMM ON (Variant C: minimal_c feature set,
          hmm_minimal_C_v1.pkl model).

T-002's Arm 2 had 4 edges (pruned) — the +0.024 Sharpe / +0.16 Sortino
delta from T-002 bundles HMM-on-with-pruning. T-015 isolates HMM as the
lone variable for clean attribution.

Reuses isolated() + _trades_canon_md5 + _find_run_id from
run_isolated.py for governor-state + module-globals isolation. The
HMM flag is patched into config/regime_settings.json for Cell B and
restored in finally.

Each run produces a record with:
  - sharpe / sortino / mdd / win_rate (point estimates)
  - per-day returns series (for downstream bootstrap CI)
  - trades_canon_md5 (determinism check)

Audit aggregation happens in a separate post-process step that reads
the raw per-run records.

Usage:
  PYTHONHASHSEED=0 python -m scripts.run_engine_e_hmm_ab           # full
  PYTHONHASHSEED=0 python -m scripts.run_engine_e_hmm_ab --smoke   # 2024 cellA single rep
  PYTHONHASHSEED=0 python -m scripts.run_engine_e_hmm_ab --cells A --years 2024
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    ISOLATED_ANCHOR,
    TRADES_DIR,
    isolated,
    _find_run_id,
    _trades_canon_md5,
)

REGIME_CONFIG_PATH = ROOT / "config" / "regime_settings.json"
RESULTS_DIR = ROOT / "data" / "measurements" / "engine_e_hmm_ab_2026_05_09"

# Same 6 edges in BOTH cells — the only variable is the HMM flag.
# Mirrors T-002's ARM1_EDGES.
HMM_AB_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]

# Variant C HMM patch (matches T-002's ARM2_HMM_PATCH; verified per memory
# `project_e_rebuild_phase_1_variant_c_validated_2026_05_07.md`).
HMM_C_PATCH = {
    "hmm_enabled": True,
    "model_path": "engines/engine_e_regime/models/hmm_minimal_C_v1.pkl",
    "feature_set": "minimal_c",
    "min_confidence_floor": 0.6,
    "on_model_missing": "warn",
}

DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025]
EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_engine_e_hmm_ab", *sys.argv[1:]])


@contextmanager
def hmm_patch(enabled: bool) -> Iterator[None]:
    """Patch config/regime_settings.json's `hmm` block to enable Variant
    C. For `enabled=False` this is a no-op (Cell A reads the
    on-disk config which has `hmm_enabled: false` by production
    default). The original file content is captured before the patch
    so it's restored even if the run errors."""
    if not enabled:
        yield
        return

    original = REGIME_CONFIG_PATH.read_text()
    try:
        cfg = json.loads(original)
        cfg["hmm"] = dict(HMM_C_PATCH)
        REGIME_CONFIG_PATH.write_text(json.dumps(cfg, indent=4))
        yield
    finally:
        REGIME_CONFIG_PATH.write_text(original)


def _run_one(year: int) -> dict:
    """Run a single full-calendar-year backtest with the same 6-edge
    set both cells use. The only inter-cell difference is the HMM flag,
    which is owned by `hmm_patch()` at the cell level."""
    from orchestration.mode_controller import ModeController
    mc = ModeController(ROOT, env="prod")
    return mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_start=f"{year}-01-01",
        override_end=f"{year}-12-31",
        exact_edge_ids=list(HMM_AB_EDGES),
        use_historical_universe=True,
        apply_journal_at_end=True,
        discover=False,
    )


def _execute_grid(cell_label: str, years: list[int], reps: int,
                  hmm_on: bool, results_path: Path) -> list[dict]:
    """Run a single cell's full year × rep grid. Mirrors
    run_substrate_arms._execute_grid; difference is the per-cell-only
    HMM patch + cell-naming. Writes incremental JSON for resumability."""
    results: list[dict] = []
    if results_path.exists():
        try:
            results = json.loads(results_path.read_text())
        except Exception:
            results = []

    completed = {(r["year"], r["rep"]) for r in results if r.get("ok")}
    total = len(years) * reps
    counter = sum(1 for r in results if r.get("ok"))
    t_start = time.time()

    with hmm_patch(hmm_on):
        for year in years:
            for rep in range(1, reps + 1):
                if (year, rep) in completed:
                    print(f"[{cell_label}] SKIP year={year} rep={rep}", flush=True)
                    continue

                counter += 1
                elapsed = time.time() - t_start
                done = sum(1 for r in results if r.get("ok") and r.get("cell") == cell_label)
                avg = elapsed / max(done, 1) if done > 0 else 0
                eta = avg * (total - counter + 1)
                print(
                    f"\n===== [{cell_label}] year={year} rep={rep}/{reps} "
                    f"(run {counter}/{total}, elapsed {elapsed/60:.1f}m, "
                    f"ETA {eta/60:.1f}m) =====",
                    flush=True,
                )

                before = {p.name for p in TRADES_DIR.iterdir()
                          if p.is_dir() and p.name != "backup"}
                t_run = time.time()
                try:
                    with isolated(journal_mode=True):
                        summary = _run_one(year)
                    run_id = _find_run_id(before) or "?"
                    record = {
                        "cell": cell_label,
                        "hmm_on": hmm_on,
                        "year": year,
                        "rep": rep,
                        "run_id": run_id,
                        "sharpe": summary.get("Sharpe Ratio"),
                        "sortino": summary.get("Sortino Ratio"),
                        "cagr_pct": summary.get("CAGR (%)"),
                        "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                        "win_rate_pct": summary.get("Win Rate (%)"),
                        "total_trades": summary.get("Total Trades"),
                        "trades_canon_md5": (
                            _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)"
                        ),
                        "wall_time_seconds": round(time.time() - t_run, 1),
                        "ok": True,
                    }
                except Exception as e:
                    record = {
                        "cell": cell_label,
                        "hmm_on": hmm_on,
                        "year": year,
                        "rep": rep,
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}",
                        "wall_time_seconds": round(time.time() - t_run, 1),
                    }
                results.append(record)
                print(f"  Result: {record}", flush=True)

                results_path.parent.mkdir(parents=True, exist_ok=True)
                results_path.write_text(json.dumps(results, indent=2, default=str))

    return results


def run_smoke() -> int:
    """Smoke gate: 2024 Cell A single rep. Kill on zero-trade md5."""
    print("[HMM_AB] SMOKE — 2024 Cell A, 1 rep, kill on empty trades.csv", flush=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    smoke_path = RESULTS_DIR / "smoke_2024_cellA.json"

    if not ISOLATED_ANCHOR.exists():
        print("[HMM_AB] No anchor — run scripts.run_isolated --save-anchor first.", file=sys.stderr)
        return 1

    results = _execute_grid("cellA", [2024], 1, hmm_on=False, results_path=smoke_path)

    if not results or not results[-1].get("ok"):
        sentinel = RESULTS_DIR / "SMOKE_BLOCKED.txt"
        sentinel.write_text(f"smoke run failed: {results[-1] if results else 'no result'}\n")
        print(f"[HMM_AB] SMOKE BLOCKED — see {sentinel}", flush=True)
        return 2

    rec = results[-1]
    canon = rec.get("trades_canon_md5", "")
    sharpe = rec.get("sharpe")
    if canon == EMPTY_MD5:
        sentinel = RESULTS_DIR / "SMOKE_BLOCKED.txt"
        sentinel.write_text(
            f"BLOCKED — 2024 Cell A produced empty trades.csv (md5 {canon}).\n"
            f"sharpe: {sharpe}\n"
        )
        print(f"[HMM_AB] SMOKE BLOCKED (zero-trade) — see {sentinel}", flush=True)
        return 3

    sentinel = RESULTS_DIR / "SMOKE_PASS.txt"
    sentinel.write_text(f"smoke 2024 cellA: Sharpe {sharpe}, canon {canon}\n")
    print(f"[HMM_AB] SMOKE PASS — Sharpe {sharpe}, canon {canon}", flush=True)
    return 0


def run_full(years: list[int], reps: int, smoke_first: bool = True) -> int:
    """Run both cells end-to-end. Smoke gate first by default."""
    if not ISOLATED_ANCHOR.exists():
        print("[HMM_AB] No anchor — run scripts.run_isolated --save-anchor first.", file=sys.stderr)
        return 1

    if smoke_first:
        rc = run_smoke()
        if rc != 0:
            print(f"[HMM_AB] Smoke gate failed (rc={rc}); aborting full run.", flush=True)
            return rc

    cellA_path = RESULTS_DIR / "cellA_results.json"
    cellB_path = RESULTS_DIR / "cellB_results.json"

    print(f"\n[HMM_AB] Cell A — HMM OFF — years={years} reps={reps}", flush=True)
    _execute_grid("cellA", years, reps, hmm_on=False, results_path=cellA_path)

    print(f"\n[HMM_AB] Cell B — HMM ON (Variant C) — years={years} reps={reps}", flush=True)
    _execute_grid("cellB", years, reps, hmm_on=True, results_path=cellB_path)

    sentinel = RESULTS_DIR / "FULL_DONE.txt"
    sentinel.write_text(f"full grid complete at {datetime.now().isoformat(timespec='seconds')}\n")
    print(f"[HMM_AB] FULL DONE — see {sentinel}", flush=True)
    return 0


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="Run only 2024 Cell A single rep; kill on zero trades.")
    parser.add_argument("--full", action="store_true",
                        help="Run both cells (smoke gate first).")
    parser.add_argument("--no-smoke-gate", action="store_true",
                        help="Skip smoke gate when --full is used.")
    parser.add_argument("--cells", choices=["A", "B", "AB"], default="AB",
                        help="Which cells to run (debug/iterative).")
    parser.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    parser.add_argument("--reps", type=int, default=1)
    args = parser.parse_args()

    if args.smoke:
        return run_smoke()

    if args.full:
        return run_full(args.years, args.reps, smoke_first=not args.no_smoke_gate)

    # Custom cell-subset path
    if not ISOLATED_ANCHOR.exists():
        print("[HMM_AB] No anchor — run scripts.run_isolated --save-anchor first.", file=sys.stderr)
        return 1

    if "A" in args.cells:
        path = RESULTS_DIR / "cellA_results.json"
        _execute_grid("cellA", args.years, args.reps, hmm_on=False, results_path=path)
    if "B" in args.cells:
        path = RESULTS_DIR / "cellB_results.json"
        _execute_grid("cellB", args.years, args.reps, hmm_on=True, results_path=path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
