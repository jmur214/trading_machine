"""
scripts/run_str_3rep_t036.py
=========================================
T-2026-05-12-036 Part A: STR 3-rep re-measurement WITH cockpit fix.

Mirrors T-030's harness exactly but writes to a fresh output dir so
the original T-030 results stay intact for direct comparison. The
underlying behavior should be unchanged; only the reported metrics
shift because of T-034.

Question this answers: with peak_equity no longer mis-read into the
equity slot, what is STR's actual per-year Sharpe profile? T-030
reported 2022 = 0.000 (the bug-zeroed cell); the corrected number
should reflect the real -4.17% return seen in the raw equity series.

Output: data/measurements/str_3rep_cockpit_fixed_2026_05_12/results.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    TRADES_DIR, isolated, _find_run_id, _trades_canon_md5,
)
from scripts.run_per_edge_isolation import (  # noqa: E402
    _preimport_target_modules,
    _populate_registry_inside_isolation,
    _flip_to_active_in_context,
)

TARGET_EDGE = "short_term_reversal_v1"
YEARS = [2021, 2022, 2023, 2024, 2025]
REPS = 3

RESULTS_DIR = ROOT / "data" / "measurements" / "str_3rep_cockpit_fixed_2026_05_12"
RESULTS_PATH = RESULTS_DIR / "results.json"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.run_str_3rep_t036",
             *sys.argv[1:]],
        )


def _run_one_inner(year: int) -> dict:
    """Single isolated backtest of short_term_reversal_v1 for one year.
    Mirrors run_per_edge_isolation._run_one but inlined to avoid import
    coupling on a private helper."""
    _populate_registry_inside_isolation()
    _flip_to_active_in_context(TARGET_EDGE)

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
        exact_edge_ids=[TARGET_EDGE],
        use_historical_universe=True,
        apply_journal_at_end=True,
        discover=False,
    )


def _execute_grid() -> list:
    results = []
    if RESULTS_PATH.exists():
        try:
            results = json.loads(RESULTS_PATH.read_text())
        except Exception:
            results = []

    completed = {(r["year"], r["rep"]) for r in results if r.get("ok")}
    total = len(YEARS) * REPS
    counter = sum(1 for r in results if r.get("ok"))
    t_start = time.time()

    for year in YEARS:
        for rep in range(1, REPS + 1):
            if (year, rep) in completed:
                print(f"[STR-3REP] SKIP year={year} rep={rep} (already done)", flush=True)
                continue
            counter += 1
            elapsed = time.time() - t_start
            done_now = sum(1 for r in results if r.get("ok"))
            avg = elapsed / max(done_now, 1) if done_now > 0 else 0
            eta = avg * (total - counter + 1)
            print(
                f"\n===== [STR-3REP] year={year} rep={rep}/{REPS} "
                f"({counter}/{total}, elapsed {elapsed/60:.1f}m, "
                f"ETA {eta/60:.1f}m) =====", flush=True,
            )
            before = {p.name for p in TRADES_DIR.iterdir()
                      if p.is_dir() and p.name != "backup"}
            t_run = time.time()
            try:
                with isolated(journal_mode=True):
                    summary = _run_one_inner(year)
                run_id = _find_run_id(before) or "?"
                record = {
                    "year": year,
                    "rep": rep,
                    "run_id": run_id,
                    "sharpe": summary.get("Sharpe Ratio"),
                    "sortino": summary.get("Sortino Ratio"),
                    "cagr_pct": summary.get("CAGR (%)"),
                    "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                    "win_rate_pct": summary.get("Win Rate (%)"),
                    "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                    "ok": True,
                }
            except Exception as e:
                record = {
                    "year": year, "rep": rep, "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                }
            results.append(record)
            print(f"  -> {record}", flush=True)
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    return results


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(f"[STR-3REP] target edge: {TARGET_EDGE}", flush=True)
    print(f"[STR-3REP] years: {YEARS}", flush=True)
    print(f"[STR-3REP] reps: {REPS}", flush=True)
    print(f"[STR-3REP] results -> {RESULTS_PATH}", flush=True)
    _preimport_target_modules()
    results = _execute_grid()
    n_ok = sum(1 for r in results if r.get("ok"))
    print(f"\n[STR-3REP] Done. {n_ok}/{len(results)} runs ok.", flush=True)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
