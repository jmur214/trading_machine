"""scripts/run_spinoff_gauntlet_t041b.py
=========================================
T-041b Phase 3: run the 8-gate Discovery gauntlet on
`spinoff_reversion_v1`.

Sequencing:
  Phase 1 (universe-resolver wiring) — DONE (commit 9ad5c16)
  Phase 2 (EDGAR scraper + cache)    — DONE (commit 82d87c5)
  Phase 3 (gauntlet)                 — THIS SCRIPT
  Phase 4 (audit + commit)           — follows

Method
------
1. Resolve the universe via the T-041b-extended resolver, passing the
   merged curated + EDGAR spinoff event list as `spinoff_events=`. This
   adds child tickers to the universe in-window.
2. Filter to children that have OHLCV on disk (auto-fetching 100+
   tickers would explode wall-time; available data is the working set).
3. Build a `candidate_spec` shadow of `spinoff_reversion_v1`. The
   baseline ensemble runs WITHOUT it (treated as candidate); the
   with-candidate run adds it at full weight.
4. Invoke `DiscoveryEngine.validate_candidate(...)` which runs all
   8 gates and returns per-gate pass/fail + per-gate metrics.
5. Persist the result JSON for the audit doc.

Output:
  data/measurements/spinoff_reversion_t041b_gauntlet/result.json
  data/measurements/spinoff_reversion_t041b_gauntlet/diagnostic.log

Determinism: `PYTHONHASHSEED=0` honored via re-exec. Per CLAUDE.md
6th non-negotiable (bootstrap CI) and 7th non-negotiable (Gate 0 MBL
via n_trials_for_dsr).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "data" / "measurements" / "spinoff_reversion_t041b_gauntlet"
OUTPUT_PATH = OUTPUT_DIR / "result.json"
DIAG_LOG_PATH = OUTPUT_DIR / "diagnostic.log"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.run_spinoff_gauntlet_t041b",
             *sys.argv[1:]],
        )


def _build_universe_and_data_map(start: str, end: str):
    """Resolve the substrate-honest universe + filter to spinoff
    children that have on-disk OHLCV. Returns (data_map, info)."""
    from engines.data_manager.data_manager import DataManager
    from engines.data_manager.universe_resolver import (
        discover_cached_tickers,
        resolve_universe,
    )
    from engines.engine_a_alpha.edges._helpers.spinoff_detector import (
        get_events,
    )

    cache_root = ROOT / "data"
    cached = discover_cached_tickers(cache_root, timeframe="1d")
    events = get_events(use_yfinance=False, use_edgar_cache=True)

    # Substrate-honest S&P 500 + index ETF essentials + spinoff
    # children that we have data for. Filtering to cached avoids
    # 100+ unsynced yfinance fetches.
    tickers, uni_info = resolve_universe(
        static_tickers=[],
        start=start,
        end=end,
        use_historical=True,
        cache_dir=cache_root,
        anchor_dates=None,
        available_filter=cached,
        spinoff_events=events,
    )
    print(
        f"[T-041b] universe: mode={uni_info['mode']} → "
        f"historical={uni_info['n_historical_union']} → "
        f"+essentials={uni_info['n_after_essentials']} → "
        f"+filter={uni_info['n_after_available_filter']} → "
        f"spinoffs_added={uni_info['n_spinoff_children_added']}",
        flush=True,
    )

    dm = DataManager(cache_dir=str(cache_root / "processed"))
    data_map = dm.ensure_data(tickers, start, end, timeframe="1d")
    print(
        f"[T-041b] data_map loaded: {len(data_map)} tickers with data",
        flush=True,
    )
    return data_map, uni_info


def _candidate_spec() -> Dict:
    """Construct a fresh candidate spec for spinoff_reversion_v1.

    Use a candidate-only `edge_id` so the baseline ensemble (which
    pulls the registry's `status='paused'` entry at 0.25× weight)
    does NOT collide with the candidate's full-weight inclusion.
    """
    from engines.engine_a_alpha.edges.spinoff_reversion_v1 import (
        SpinoffReversionEdge,
    )
    return {
        "edge_id": "spinoff_reversion_v1_t041b_candidate",
        "module": SpinoffReversionEdge.__module__,
        "class": SpinoffReversionEdge.__name__,
        "category": SpinoffReversionEdge.CATEGORY,
        "params": dict(SpinoffReversionEdge.DEFAULT_PARAMS),
        "status": "candidate",
        "version": "1.0.0-t041b",
        "origin": "manual_dispatch_t041b",
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Window covers full EDGAR detection range. validate_candidate uses
    # the data_map index automatically when start/end are not supplied.
    start, end = "2015-01-01", "2024-12-31"
    t0 = time.time()
    print(f"[T-041b] window: {start} → {end}", flush=True)

    data_map, uni_info = _build_universe_and_data_map(start, end)

    from engines.engine_d_discovery.discovery import DiscoveryEngine
    disc = DiscoveryEngine()
    cand = _candidate_spec()
    print(f"[T-041b] candidate: {cand['edge_id']}", flush=True)

    # Per CLAUDE.md 7th non-negotiable: include MBL. Count of trials
    # consumed for this dispatch (curated + EDGAR + the candidate
    # itself = 1 effective trial for DSR purposes since we're testing
    # one specific edge, not sweeping hyperparameters).
    result = disc.validate_candidate(
        cand,
        data_map,
        start_date=start,
        end_date=end,
        diagnostic_log_path=str(DIAG_LOG_PATH),
        # Conservative thresholds — defaults.
        n_trials_for_dsr=1,  # one edge, not a sweep
    )
    elapsed = time.time() - t0

    # Persist result
    out = {
        "task_id": "T-2026-05-12-041b",
        "phase": "3-gauntlet",
        "candidate": cand,
        "window": [start, end],
        "wall_seconds": round(elapsed, 1),
        "universe_info": uni_info,
        "n_tickers_in_data_map": len(data_map),
        "gauntlet_result": result,
    }
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[T-041b] gauntlet complete in {elapsed/60:.1f} min", flush=True)
    print(f"[T-041b] wrote {OUTPUT_PATH}", flush=True)
    print("[T-041b] per-gate verdict:", flush=True)
    for k in (
        "gate_1_passed", "gate_2_passed", "gate_3_evaluated",
        "gate_4_passed", "gate_5_passed", "gate_6_passed",
        "gate_7_passed", "gate_8_passed", "passed_all_gates",
    ):
        print(f"  {k}: {result.get(k)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
