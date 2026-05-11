"""
scripts/run_per_edge_isolation.py
==================================
Per-edge isolation harness (T-2026-05-10-020).

Runs each of the 5 new paused edges (added 2026-05-09) at FULL weight
in ISOLATION on the substrate-honest 5-year window:

  1. momentum_12_1_v1
  2. momentum_6_1_v1
  3. short_term_reversal_v1
  4. pairs_trading_MA_V_v1
  5. dividend_initiation_drift_v1

Per edge per year, runs ONE backtest with `exact_edge_ids=[<edge_id>]`,
forcing only that edge to load and trade at full weight (bypasses both
soft-pause 0.25× weighting AND ensemble dilution). This is the
gauntlet-equivalent measurement for hand-written edges that don't have
Discovery candidacy or revival-evidence history.

Configuration matches T-002 / T-019 exactly:
  - Universe: F6 historical S&P 500 (use_historical_universe=True)
  - Window: 2021-2025 calendar years, 1 rep × 5 years per edge
  - Mode: prod, apply_journal_at_end=True (F11 invariant)
  - Realistic costs ON, wash-sale OFF, lt-hold OFF, HMM OFF

5 edges × 5 years × 1 rep = 25 isolated runs total. Wall ~10-15 min each
local → expect 4-6 hours total. Incremental JSON persistence so a
partial grid (interrupted run) is recoverable.

Usage:
  PYTHONHASHSEED=0 python -m scripts.run_per_edge_isolation
  PYTHONHASHSEED=0 python -m scripts.run_per_edge_isolation --edges momentum_12_1_v1
  PYTHONHASHSEED=0 python -m scripts.run_per_edge_isolation --years 2021
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    TRADES_DIR,
    isolated,
    _find_run_id,
    _trades_canon_md5,
)

RESULTS_DIR = ROOT / "data" / "measurements" / "per_edge_isolation_2026_05_10"
RESULTS_PATH = RESULTS_DIR / "per_edge_grid.json"

TARGET_EDGES = [
    "momentum_12_1_v1",
    "momentum_6_1_v1",
    "short_term_reversal_v1",
    "pairs_trading_MA_V_v1",
    "dividend_initiation_drift_v1",
]

# Each target edge_id maps to the module that must be imported so the
# EdgeRegistry's auto-register-on-import sees it. Without this pre-import
# step, `exact_edge_ids=[<id>]` resolves to a None spec and ModeController
# falls through to AlphaEngine defaults (rsi_bounce + xsec_momentum +
# news_sentiment_edge), silently measuring the WRONG edge.
TARGET_MODULES = [
    "engines.engine_a_alpha.edges.momentum_12_1_v1",
    "engines.engine_a_alpha.edges.momentum_6_1_v1",
    "engines.engine_a_alpha.edges.short_term_reversal_v1",
    "engines.engine_a_alpha.edges.pairs_trading_v1",          # holds pairs_trading_*_v1 specs
    "engines.engine_a_alpha.edges.dividend_initiation_drift_v1",
]

DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025]


def _preimport_target_modules() -> None:
    """Ensure every target edge module is imported so its
    auto-register-on-import block populates the registry (and the
    on-disk edges.yml) before `isolated()` takes its snapshot.

    Bug class: without this, `EdgeRegistry().get(target_id)` returns
    None inside `_run_one`, ModeController's `_load_edges_via_registry`
    builds an empty specs map, AlphaEngine.__init__ falls through to
    defaults (rsi_bounce + xsec_momentum) — silently measuring the
    wrong edge. Discovered 2026-05-10 mid-task; the initial smoke
    appeared to PASS but was actually measuring `xsec_momentum_v1` +
    `news_sentiment_edge_v1` against the q1 substrate, not the target.
    """
    import importlib
    from engines.engine_a_alpha.edge_registry import EdgeRegistry
    for mod_path in TARGET_MODULES:
        importlib.import_module(mod_path)
    reg = EdgeRegistry()
    for eid in TARGET_EDGES:
        s = reg.get(eid)
        if s is None:
            raise RuntimeError(
                f"Pre-import failed: registry still missing {eid} after "
                f"importing target modules. Inspect auto-register block in "
                f"the edge module."
            )
        print(f"[ISO] Pre-import OK: {eid} status={s.status} module={s.module}",
              flush=True)


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_per_edge_isolation", *sys.argv[1:]])


def _populate_registry_inside_isolation() -> None:
    """Re-import the 5 target edge modules INSIDE the isolated() context.

    `isolated()` restores edges.yml from the anchor on entry. Since the
    anchor was taken before these new edges existed, the on-disk
    edges.yml lacks them at this point. Re-importing forces the
    auto-register-on-import block to run `EdgeRegistry().ensure()`,
    which writes the new specs back to edges.yml so the
    backtest-side `EdgeRegistry()` instantiation can resolve
    `exact_edge_ids` correctly.

    Without this, mode_controller's `_load_edges_via_registry` calls
    `registry.get(<target_id>)` → None → empty specs map →
    AlphaEngine.__init__ falls through to defaults
    (rsi_bounce + xsec_momentum + news_sentiment_edge). The run still
    completes "successfully" but measures the wrong edges entirely.

    Side effect: edges.yml will gain the 5 new entries during this
    run. `isolated()` restores the anchor on exit, so the persistent
    edges.yml state is unchanged across reps.
    """
    import importlib
    for mod_path in TARGET_MODULES:
        # Use importlib.reload so a re-entry triggers the auto-register
        # block even if the module was already imported in a previous
        # rep of the same process. ensure() is idempotent so re-running
        # the registration is safe.
        try:
            mod = importlib.import_module(mod_path)
            importlib.reload(mod)
        except Exception as e:
            raise RuntimeError(
                f"Failed to re-import {mod_path} inside isolated(): "
                f"{type(e).__name__}: {e}"
            ) from e


def _flip_to_active_in_context(edge_id: str) -> None:
    """Flip target edge's status='paused' → 'active' WITHIN the
    isolated() context so the soft-pause 0.25× weight multiplier does
    NOT fire on the edge being measured.

    Brief requires "full weight (status='active') in isolation".
    `isolated()` will restore the anchor on exit, so this transient
    flip does not persist outside the run. CLAUDE.md's prohibition on
    manual edge promotion is satisfied because the on-disk state
    outside the context is unchanged.
    """
    from engines.engine_a_alpha.edge_registry import EdgeRegistry
    reg = EdgeRegistry()
    reg.set_status(edge_id, "active")


def _run_one(year: int, edge_id: str) -> dict:
    """Single isolated backtest with one edge at full weight, one year."""
    _populate_registry_inside_isolation()
    _flip_to_active_in_context(edge_id)
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
        exact_edge_ids=[edge_id],
        use_historical_universe=True,
        apply_journal_at_end=True,
        discover=False,
    )


def _execute_grid(edges: List[str], years: List[int]) -> List[dict]:
    """Run the (edge, year) grid. Each cell is one isolated run."""
    results: List[dict] = []
    if RESULTS_PATH.exists():
        try:
            results = json.loads(RESULTS_PATH.read_text())
        except json.JSONDecodeError:
            results = []

    completed = {(r["edge_id"], r["year"]) for r in results if r.get("ok")}
    total = len(edges) * len(years)
    counter = sum(1 for r in results if r.get("ok"))

    t_start = time.time()

    for edge_id in edges:
        for year in years:
            if (edge_id, year) in completed:
                print(f"[ISO] SKIP edge={edge_id} year={year} (already done)", flush=True)
                continue

            counter += 1
            elapsed = time.time() - t_start
            done_now = sum(1 for r in results if r.get("ok"))
            avg = elapsed / max(done_now, 1) if done_now > 0 else 0
            eta = avg * (total - counter + 1)
            print(
                f"\n===== [ISO] edge={edge_id} year={year} "
                f"({counter}/{total}, elapsed {elapsed/60:.1f}m, "
                f"ETA {eta/60:.1f}m) =====", flush=True,
            )

            before = {p.name for p in TRADES_DIR.iterdir()
                      if p.is_dir() and p.name != "backup"}
            t_run = time.time()
            try:
                with isolated(journal_mode=True):
                    summary = _run_one(year, edge_id)
                run_id = _find_run_id(before) or "?"
                record = {
                    "edge_id": edge_id,
                    "year": year,
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
                    "edge_id": edge_id,
                    "year": year,
                    "ok": False,
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
    parser.add_argument("--edges", type=str, default=",".join(TARGET_EDGES),
                        help="Comma-separated edge_ids (default: all 5 new paused edges)")
    parser.add_argument("--years", type=str, default=",".join(str(y) for y in DEFAULT_YEARS),
                        help="Comma-separated years (default 2021-2025)")
    args = parser.parse_args()

    edges = [e.strip() for e in args.edges.split(",") if e.strip()]
    years = [int(y) for y in args.years.split(",") if y.strip()]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[ISO] edges={edges}", flush=True)
    print(f"[ISO] years={years}", flush=True)
    print(f"[ISO] results -> {RESULTS_PATH}", flush=True)

    # CRITICAL: pre-import target modules so the registry sees them
    # BEFORE `isolated()` snapshots the governor state. Without this,
    # `exact_edge_ids` filters against a registry that hasn't been
    # populated yet → empty spec map → AlphaEngine loads defaults.
    _preimport_target_modules()

    results = _execute_grid(edges, years)
    n_ok = sum(1 for r in results if r.get("ok"))
    print(f"\n[ISO] Done. {n_ok}/{len(results)} runs ok.", flush=True)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
