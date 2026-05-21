"""scripts/lifecycle_factor_alpha_reeval_t043.py
==================================================
Applies T-043's factor-α retirement gate to the 6 current active edges
using cockpit-fixed trade logs from T-035 (rep 1) and STR's T-036
Part A run.

Outputs:
  docs/Audit/engine_f_lifecycle_factor_alpha_reeval_2026_05_12.{md,json}

Read-only / journal-mode: NEVER mutates `data/governor/edges.yml`.
The gate's `factor_alpha_state.yml` is also written to a one-shot
scratch path under `data/measurements/` so we don't pollute the real
governor state during this exploratory run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.factor_decomposition import load_factor_data  # noqa: E402
from engines.engine_f_governance.factor_alpha_gate import (  # noqa: E402
    check_factor_alpha_retirement,
)
from scripts.factor_decomp_substrate_honest import INITIAL_CAPITAL  # noqa: E402

T035_RESULTS = ROOT / "data" / "measurements" / "substrate_arm1_cockpit_fixed_2026_05_12" / "arm1_results.json"
T036A_RESULTS = ROOT / "data" / "measurements" / "str_3rep_cockpit_fixed_2026_05_12" / "results.json"

T035_ACTIVE_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]
STR_EDGE = "short_term_reversal_v1"

# T-029 / T-036 per-regime verdicts for cross-reference
T036_VERDICTS = {
    "gap_fill_v1": "UNIFORMLY NEGATIVE",
    "volume_anomaly_v1": "UNIFORMLY NEGATIVE",
    "value_earnings_yield_v1": "UNIFORMLY NEGATIVE",
    "value_book_to_market_v1": "UNIFORMLY NEGATIVE",
    "accruals_inv_sloan_v1": "UNIFORMLY NEGATIVE",
    "accruals_inv_asset_growth_v1": "UNIFORMLY NEGATIVE",
    "short_term_reversal_v1": "UNIFORMLY NOISY",
}

# Persist state to a scratch path so the real governor file is
# untouched. Caller can review and decide whether to journal-apply.
SCRATCH_STATE_PATH = (
    ROOT / "data" / "measurements"
    / "engine_f_lifecycle_factor_alpha_reeval_2026_05_12"
    / "factor_alpha_state.yml"
)

OUT_MD = ROOT / "docs" / "Audit" / "engine_f_lifecycle_factor_alpha_reeval_2026_05_12.md"
OUT_JSON = ROOT / "docs" / "Audit" / "engine_f_lifecycle_factor_alpha_reeval_2026_05_12.json"


def _rep1_run_ids_by_year(results_path: Path) -> dict:
    d = json.loads(results_path.read_text())
    out = {}
    for r in d:
        if not r.get("ok") or r.get("rep") != 1:
            continue
        out[r["year"]] = r["run_id"]
    return out


def _load_closed_trades_for_edge(
    edge_id: str, run_ids: dict,
) -> pd.DataFrame:
    frames = []
    for _year, rid in run_ids.items():
        p = ROOT / "data" / "trade_logs" / rid / "trades.csv"
        if not p.exists():
            continue
        df = pd.read_csv(
            p, low_memory=False,
            usecols=["timestamp", "edge_id", "pnl", "regime_label"],
        )
        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
        df = df.dropna(subset=["pnl"])
        df = df[df["edge_id"] == edge_id]
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["timestamp", "edge_id", "pnl", "regime_label"])
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    SCRATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Fresh state per run so the test always shows "what would happen
    # over N consecutive cycles starting from scratch."
    if SCRATCH_STATE_PATH.exists():
        SCRATCH_STATE_PATH.unlink()

    if not T035_RESULTS.exists() or not T036A_RESULTS.exists():
        print("[T-043] missing T-035 or T-036A results; aborting", file=sys.stderr)
        return 1

    t035_ids = _rep1_run_ids_by_year(T035_RESULTS)
    str_ids = _rep1_run_ids_by_year(T036A_RESULTS)

    factors = load_factor_data()
    if factors is None or factors.empty:
        print("[T-043] no factor data; aborting", file=sys.stderr)
        return 2

    rows = []
    # All 6 active edges share the T-035 trade logs (per-year aggregate).
    # STR uses its own per-year run logs.
    cycle_results: dict = {}  # edge_id -> [cycle1, cycle2] results
    for edge_id in T035_ACTIVE_EDGES + [STR_EDGE]:
        run_ids = str_ids if edge_id == STR_EDGE else t035_ids
        closed = _load_closed_trades_for_edge(edge_id, run_ids)

        cycle_results[edge_id] = []
        for cycle in (1, 2):
            fired, reason, result, count = check_factor_alpha_retirement(
                edge_id=edge_id,
                closed_trades_for_edge=closed,
                factors=factors,
                state_path=SCRATCH_STATE_PATH,
                t_threshold=-2.0,
                sustained_cycles_required=2,
                min_obs=30,
                n_iter=1000,
                seed=0,
                initial_capital=INITIAL_CAPITAL,
                as_of_ts=f"2026-05-12T{cycle:02d}:00:00",
            )
            cycle_results[edge_id].append({
                "cycle": cycle,
                "fired": fired,
                "reason": reason,
                "n_obs": result.n_obs,
                "alpha_tstat_point": result.alpha_tstat_point,
                "alpha_tstat_ci_low": result.alpha_tstat_ci_low,
                "alpha_tstat_ci_high": result.alpha_tstat_ci_high,
                "consecutive_count": count,
            })

        final = cycle_results[edge_id][-1]
        rows.append({
            "edge_id": edge_id,
            "t036_perregime_verdict": T036_VERDICTS.get(edge_id, "?"),
            "n_closed_trades": int(len(closed)),
            "alpha_tstat_point": final["alpha_tstat_point"],
            "alpha_tstat_ci_low": final["alpha_tstat_ci_low"],
            "alpha_tstat_ci_high": final["alpha_tstat_ci_high"],
            "ci_low_below_threshold": final["alpha_tstat_ci_low"] < -2.0,
            "gate_fires_after_2_cycles": final["fired"],
            "disposition": "RETIRE" if final["fired"] else "KEEP/WATCH",
            "cycle_history": cycle_results[edge_id],
        })

    payload = {
        "task_id": "T-2026-05-12-043",
        "scope": "factor-α retirement re-evaluation on 7 edges (6 actives + STR)",
        "t035_run_ids_rep1": t035_ids,
        "str_run_ids_rep1": str_ids,
        "gate_config": {
            "t_threshold": -2.0,
            "sustained_cycles_required": 2,
            "min_obs": 30,
            "bootstrap_iter": 1000,
            "seed": 0,
        },
        "edges": rows,
        "summary": {
            "total_evaluated": len(rows),
            "n_retire": sum(1 for r in rows if r["gate_fires_after_2_cycles"]),
            "n_keep_or_watch": sum(1 for r in rows if not r["gate_fires_after_2_cycles"]),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[T-043] wrote {OUT_JSON}")
    print(f"[T-043] retire={payload['summary']['n_retire']}/{payload['summary']['total_evaluated']}")
    for r in rows:
        print(
            f"  {r['edge_id']:>35}  "
            f"point={r['alpha_tstat_point']:+.2f}  "
            f"ci=[{r['alpha_tstat_ci_low']:+.2f}, {r['alpha_tstat_ci_high']:+.2f}]  "
            f"→ {r['disposition']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
