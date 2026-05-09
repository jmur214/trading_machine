"""
scripts/run_substrate_arms.py
==============================
Substrate-honest re-measurement (T-2026-05-08-002).

Two-arm dispatcher matching `docs/Measurements/2026-05/spec_substrate_honest_remeasurement_2026_05_08.md`:

- Arm 1: Current production state (6 actives explicitly enumerated by spec,
  HMM OFF). Substrate-honest baseline post-CSV-closure, post-tz-fix.
- Arm 2: Recommended deployment state (4 surviving actives, HMM Variant C
  ON). Lifecycle pruning + HMM modulation applied.

Both arms run on F6 historical S&P 500 universe (use_historical_universe=True),
with apply_journal_at_end=True so edges.yml is NOT mutated mid-run.

The harness reuses `isolated()` from `run_isolated.py` for governor-state
+ module-globals isolation. Arm 2 additionally patches
`config/regime_settings.json` to flip HMM on; original is restored in
finally.

Smoke-mode (--smoke) runs ONLY 2021 Arm 1 single rep so we can detect
the zero-trade regression class before burning ~10hr on the full grid.
Kill condition: trades_canon_md5 == d41d8cd98f00b204e9800998ecf8427e
(empty-file md5) → write BLOCKED sentinel and exit non-zero.

Usage:
  # Smoke first — fail-fast check on 2021 single rep
  PYTHONHASHSEED=0 python -m scripts.run_substrate_arms --smoke

  # Full campaign (after smoke passes)
  PYTHONHASHSEED=0 python -m scripts.run_substrate_arms --full

  # Single arm, single year, single rep (debug)
  PYTHONHASHSEED=0 python -m scripts.run_substrate_arms --arm 1 --years 2024 --reps 1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
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

EMPTY_MD5 = "d41d8cd98f00b204e9800998ecf8427e"

REGIME_CONFIG_PATH = ROOT / "config" / "regime_settings.json"
RESULTS_DIR = ROOT / "data" / "measurements" / "substrate_2026_05_08"

ARM1_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]

ARM2_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
]

ARM2_HMM_PATCH = {
    "hmm_enabled": True,
    "model_path": "engines/engine_e_regime/models/hmm_minimal_C_v1.pkl",
    "feature_set": "minimal_c",
    "min_confidence_floor": 0.6,
    "on_model_missing": "warn",
}

DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025]


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_substrate_arms", *sys.argv[1:]])


@contextmanager
def hmm_patch(enabled: bool) -> Iterator[None]:
    """Patch config/regime_settings.json to enable HMM Variant C, restore on exit.

    For Arm 1 (enabled=False) this is a no-op. For Arm 2 it overwrites the
    `hmm` block with ARM2_HMM_PATCH. The original file content is captured
    in memory before the patch so it can be restored even if the run errors.
    """
    if not enabled:
        yield
        return

    original = REGIME_CONFIG_PATH.read_text()
    try:
        cfg = json.loads(original)
        cfg["hmm"] = dict(ARM2_HMM_PATCH)
        REGIME_CONFIG_PATH.write_text(json.dumps(cfg, indent=4))
        yield
    finally:
        REGIME_CONFIG_PATH.write_text(original)


def _run_one(year: int, exact_edge_ids: list[str]) -> dict:
    """Run a single full-calendar-year backtest under prod config.

    Always uses use_historical_universe=True (substrate-honest spec
    requirement) and apply_journal_at_end=True (F11 invariant).
    """
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
        exact_edge_ids=list(exact_edge_ids),
        use_historical_universe=True,
        apply_journal_at_end=True,
        discover=False,
    )


def _execute_grid(arm_label: str, years: list[int], reps: int,
                  exact_edge_ids: list[str], hmm_on: bool,
                  results_path: Path) -> list[dict]:
    """Run a single arm's full year × rep grid.

    Writes incremental JSON to results_path after every run so a partial
    grid (interrupted run, machine restart) is recoverable. Each run
    happens inside isolated(journal_mode=True) so governor + journal +
    mutable-globals reset between reps.
    """
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
                    print(f"[{arm_label}] SKIP (already done): year={year} rep={rep}", flush=True)
                    continue

                counter += 1
                elapsed = time.time() - t_start
                done_now = sum(1 for r in results if r.get("ok") and r.get("arm") == arm_label)
                avg = elapsed / max(done_now, 1) if done_now > 0 else 0
                eta = avg * (total - counter + 1)
                print(f"\n===== [{arm_label}] YEAR {year} REP {rep}/{reps} "
                      f"(run {counter}/{total}, elapsed {elapsed/60:.1f}m, "
                      f"ETA {eta/60:.1f}m) =====", flush=True)

                before = {p.name for p in TRADES_DIR.iterdir()
                          if p.is_dir() and p.name != "backup"}
                t_run = time.time()
                try:
                    with isolated(journal_mode=True):
                        summary = _run_one(year, exact_edge_ids)
                    run_id = _find_run_id(before) or "?"
                    record = {
                        "arm": arm_label,
                        "year": year,
                        "rep": rep,
                        "run_id": run_id,
                        "sharpe": summary.get("Sharpe Ratio"),
                        "sortino": summary.get("Sortino Ratio"),
                        "cagr_pct": summary.get("CAGR (%)"),
                        "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                        "win_rate_pct": summary.get("Win Rate (%)"),
                        "total_trades": summary.get("Total Trades"),
                        "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
                        "wall_time_seconds": round(time.time() - t_run, 1),
                        "ok": True,
                    }
                except Exception as e:
                    record = {
                        "arm": arm_label,
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
    """Run 2021 Arm 1 single rep and check zero-trade kill condition."""
    print("[SUBSTRATE] SMOKE — 2021 Arm 1, single rep, kill on empty trades.csv", flush=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    smoke_path = RESULTS_DIR / "smoke_2021_arm1.json"

    if not ISOLATED_ANCHOR.exists():
        print("[SUBSTRATE] No anchor — run `python -m scripts.run_isolated --save-anchor` first.", file=sys.stderr)
        return 1

    results = _execute_grid(
        arm_label="arm1",
        years=[2021],
        reps=1,
        exact_edge_ids=ARM1_EDGES,
        hmm_on=False,
        results_path=smoke_path,
    )

    if not results or not results[-1].get("ok"):
        sentinel = RESULTS_DIR / "SMOKE_BLOCKED.txt"
        sentinel.write_text(f"smoke run failed: {results[-1] if results else 'no result'}\n")
        print(f"[SUBSTRATE] SMOKE BLOCKED — see {sentinel}", flush=True)
        return 2

    rec = results[-1]
    canon = rec.get("trades_canon_md5", "")
    trades = rec.get("total_trades", 0) or 0
    sharpe = rec.get("sharpe")

    if canon == EMPTY_MD5 or trades == 0:
        sentinel = RESULTS_DIR / "SMOKE_BLOCKED.txt"
        sentinel.write_text(
            f"BLOCKED — 2021 zero-trade reproduces; regression not fully fixed.\n"
            f"canon md5: {canon}\n"
            f"total trades: {trades}\n"
            f"sharpe: {sharpe}\n"
        )
        print(f"[SUBSTRATE] SMOKE BLOCKED (zero-trade) — see {sentinel}", flush=True)
        return 3

    sentinel = RESULTS_DIR / "SMOKE_PASS.txt"
    sentinel.write_text(
        f"smoke 2021 Arm 1: Sharpe {sharpe}, trades {trades}, canon {canon}\n"
    )
    print(f"[SUBSTRATE] SMOKE PASS — Sharpe {sharpe}, trades {trades}", flush=True)
    return 0


def run_full(years: list[int], reps: int, smoke_first: bool = True) -> int:
    """Run both arms end-to-end. Optionally do smoke gate first."""
    if not ISOLATED_ANCHOR.exists():
        print("[SUBSTRATE] No anchor — run `python -m scripts.run_isolated --save-anchor` first.", file=sys.stderr)
        return 1

    if smoke_first:
        rc = run_smoke()
        if rc != 0:
            print(f"[SUBSTRATE] Smoke gate failed (rc={rc}); aborting full run.", flush=True)
            return rc

    arm1_path = RESULTS_DIR / "arm1_results.json"
    arm2_path = RESULTS_DIR / "arm2_results.json"

    print(f"\n[SUBSTRATE] ARM 1 — years={years} reps={reps}", flush=True)
    _execute_grid("arm1", years, reps, ARM1_EDGES, False, arm1_path)

    print(f"\n[SUBSTRATE] ARM 2 — years={years} reps={reps} (HMM Variant C ON, 4 edges)", flush=True)
    _execute_grid("arm2", years, reps, ARM2_EDGES, True, arm2_path)

    sentinel = RESULTS_DIR / "FULL_DONE.txt"
    sentinel.write_text(f"full grid complete at {datetime.now().isoformat(timespec='seconds')}\n")
    print(f"[SUBSTRATE] FULL DONE — see {sentinel}", flush=True)
    return 0


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true",
                        help="Run only 2021 Arm 1 single rep; abort on zero trades.")
    parser.add_argument("--full", action="store_true",
                        help="Run both arms 5 years × 3 reps (smoke gate first).")
    parser.add_argument("--no-smoke-gate", action="store_true",
                        help="Skip the smoke gate when --full is used.")
    parser.add_argument("--arm", type=int, choices=[1, 2], default=None,
                        help="Run a single arm only (debug).")
    parser.add_argument("--years", type=str, default=",".join(str(y) for y in DEFAULT_YEARS),
                        help="Comma-separated years (default 2021-2025).")
    parser.add_argument("--reps", type=int, default=3,
                        help="Reps per (arm, year) (default 3).")
    args = parser.parse_args()

    if args.smoke:
        return run_smoke()

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]

    if args.arm is not None:
        edges = ARM1_EDGES if args.arm == 1 else ARM2_EDGES
        hmm_on = (args.arm == 2)
        path = RESULTS_DIR / f"arm{args.arm}_results.json"
        _execute_grid(f"arm{args.arm}", years, args.reps, edges, hmm_on, path)
        return 0

    if args.full:
        return run_full(years, args.reps, smoke_first=not args.no_smoke_gate)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
