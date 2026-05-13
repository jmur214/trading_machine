"""scripts/factor_decomp_per_regime_t036.py
============================================
T-2026-05-12-036 Part B: per-regime factor decomp regenerate WITH
cockpit fix (T-034) applied to underlying trade logs.

Mirrors T-029's `factor_decomp_per_regime` exactly. Substitutes:
- T-035's 6-active-edge run_ids for what T-029 used from T-002 Arm 1
- T-036 Part A's STR run_ids for what T-029 used from T-020

The other 4 paused edges (momentum_12_1, momentum_6_1, pairs_MA_V,
dividend_init) used T-020's run_ids in T-029. Their trade logs are
pre-T-034 but the trade ledger is largely unaffected by the snapshot
bug (pnl is computed from cash + price math, not from snapshot
reads). They carry through unchanged from T-029.

Question: which (edge, regime) cells had their α / t-stat shift
materially from T-029? And did any edge change verdict bucket?

Output:
  docs/Audit/str_and_perregime_rerun_cockpit_fixed_2026_05_12.md
  docs/Audit/str_and_perregime_rerun_cockpit_fixed_2026_05_12.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.factor_decomp_per_regime import (  # noqa: E402
    analyze_edge, T002_ACTIVE_EDGES,
)
from scripts.factor_decomp_substrate_honest import FACTOR_COLS  # noqa: E402
from core.factor_decomposition import load_factor_data  # noqa: E402

T035_RESULTS = ROOT / "data" / "measurements" / "substrate_arm1_cockpit_fixed_2026_05_12" / "arm1_results.json"
T036A_RESULTS = ROOT / "data" / "measurements" / "str_3rep_cockpit_fixed_2026_05_12" / "results.json"

OUT_MD = ROOT / "docs" / "Audit" / "str_and_perregime_rerun_cockpit_fixed_2026_05_12.md"
OUT_JSON = ROOT / "docs" / "Audit" / "str_and_perregime_rerun_cockpit_fixed_2026_05_12.json"

T029_JSON = ROOT / "docs" / "Audit" / "per_regime_factor_decomp_2026_05_11.json"


def _rep1_run_ids_by_year(results_path: Path) -> Dict[int, str]:
    """Extract rep-1 run_id per year from a substrate-arms style
    results.json. T-029 only used rep 1 for its per-edge decomp."""
    d = json.loads(results_path.read_text())
    out: Dict[int, str] = {}
    for r in d:
        if not r.get("ok"):
            continue
        if r.get("rep") != 1:
            continue
        out[r["year"]] = r["run_id"]
    return out


def _verdict_head(verdict: str) -> str:
    return verdict.split("—")[0].strip()


def main() -> int:
    if not T035_RESULTS.exists():
        print(f"[T-036B] Missing T-035 results: {T035_RESULTS}", file=sys.stderr)
        return 1
    if not T036A_RESULTS.exists():
        print(f"[T-036B] Missing T-036 Part A results: {T036A_RESULTS}", file=sys.stderr)
        return 2

    t035_run_ids = _rep1_run_ids_by_year(T035_RESULTS)
    t036a_run_ids = _rep1_run_ids_by_year(T036A_RESULTS)

    print(f"[T-036B] T-035 rep-1 run_ids: {t035_run_ids}")
    print(f"[T-036B] T-036A rep-1 run_ids: {t036a_run_ids}")

    factors = load_factor_data()
    if factors is None or factors.empty:
        print("[T-036B] No factor data available", file=sys.stderr)
        return 3

    # Load T-029 baseline for comparison
    t029 = json.loads(T029_JSON.read_text())
    t029_by_edge = {e["edge_id"]: e for e in t029["per_edge"]}

    re_measured_edges = T002_ACTIVE_EDGES + ["short_term_reversal_v1"]

    per_edge: List[dict] = []
    for edge_id in re_measured_edges:
        if edge_id == "short_term_reversal_v1":
            run_ids = t036a_run_ids
        else:
            run_ids = t035_run_ids
        print(f"[T-036B] Analyzing {edge_id} on run_ids {list(run_ids.values())[:1]}...")
        result = analyze_edge(edge_id, run_ids, factors)
        # Attach T-029 comparison
        if edge_id in t029_by_edge:
            t029_edge = t029_by_edge[edge_id]
            result["t029_verdict_head"] = _verdict_head(t029_edge.get("verdict", ""))
            result["t029_n_closed_trades"] = t029_edge.get("n_closed_trades")
            result["t036_verdict_head"] = _verdict_head(result["verdict"])
            result["verdict_changed"] = result["t036_verdict_head"] != result["t029_verdict_head"]
            # Per-regime α t-stat diff vs T-029
            t029_per_regime = t029_edge.get("per_regime", {})
            shifts = {}
            for regime, t036_r in result["per_regime"].items():
                t029_r = t029_per_regime.get(regime, {})
                if t036_r.get("ok") and t029_r.get("ok"):
                    shifts[regime] = {
                        "t029_alpha_tstat": t029_r.get("alpha_tstat_hac"),
                        "t036_alpha_tstat": t036_r.get("alpha_tstat_hac"),
                        "delta_tstat": (t036_r.get("alpha_tstat_hac", 0)
                                        - t029_r.get("alpha_tstat_hac", 0)),
                        "t029_alpha_annual": t029_r.get("alpha_annualized"),
                        "t036_alpha_annual": t036_r.get("alpha_annualized"),
                    }
            result["regime_shifts_vs_t029"] = shifts
        per_edge.append(result)

    # Pass through unchanged edges from T-029 for full comparison context
    unchanged_edges = [
        e for e in t029["per_edge"]
        if e["edge_id"] not in re_measured_edges
    ]

    payload = {
        "task_id": "T-2026-05-12-036",
        "description": "Per-regime factor decomp regenerate with T-034 cockpit fix applied to T-035 (6 actives) + T-036 Part A (STR) trade logs. Other 4 edges (momentum_12_1, momentum_6_1, pairs_MA_V, dividend_init) carry through from T-029 unchanged (their trade logs predate T-034 but trade pnl is unaffected by the snapshot read bug).",
        "t035_run_ids_rep1": t035_run_ids,
        "t036a_run_ids_rep1": t036a_run_ids,
        "re_measured_edges": re_measured_edges,
        "carried_through_edges": [e["edge_id"] for e in unchanged_edges],
        "per_edge_re_measured": per_edge,
        "per_edge_carried_through": unchanged_edges,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[T-036B] Wrote {OUT_JSON}")

    # Render summary md
    lines = []
    lines.append("# T-036 Part B — Per-Regime Factor Decomp with Cockpit Fix")
    lines.append("")
    lines.append("Re-runs T-029's per-regime factor decomp on the 7 edges that")
    lines.append("have cockpit-fixed trade logs (T-035's 6 actives + T-036A's STR).")
    lines.append("The other 4 edges from T-029 carry through unchanged because")
    lines.append("their trade logs predate T-034 but the trade ledger pnl is")
    lines.append("computed from cash + price math (not snapshot reads) and is")
    lines.append("unaffected by the cockpit bug.")
    lines.append("")
    lines.append("## Verdict comparison (re-measured edges only)")
    lines.append("")
    lines.append("| Edge | T-029 verdict | T-036 verdict | Changed? | n_trades T-029→T-036 |")
    lines.append("|------|---------------|---------------|----------|----------------------|")
    for r in per_edge:
        edge = r["edge_id"]
        t029_v = r.get("t029_verdict_head", "(no T-029 baseline)")
        t036_v = r.get("t036_verdict_head", "?")
        changed = "**YES**" if r.get("verdict_changed") else "no"
        n_t029 = r.get("t029_n_closed_trades", "?")
        n_t036 = r.get("n_closed_trades", "?")
        lines.append(f"| {edge} | {t029_v} | {t036_v} | {changed} | {n_t029} → {n_t036} |")
    lines.append("")
    lines.append("## Material regime-α shifts (|Δ t| > 0.5)")
    lines.append("")
    lines.append("| Edge | Regime | T-029 α t-stat | T-036 α t-stat | Δ |")
    lines.append("|------|--------|---------------:|---------------:|---|")
    for r in per_edge:
        edge = r["edge_id"]
        for regime, shift in r.get("regime_shifts_vs_t029", {}).items():
            dt = shift["delta_tstat"]
            if abs(dt) >= 0.5:
                lines.append(
                    f"| {edge} | {regime} | "
                    f"{shift['t029_alpha_tstat']:.2f} | "
                    f"{shift['t036_alpha_tstat']:.2f} | "
                    f"{dt:+.2f} |"
                )
    lines.append("")
    lines.append("## Edges carried through unchanged")
    lines.append("")
    for e in unchanged_edges:
        v = _verdict_head(e.get("verdict", ""))
        lines.append(f"- `{e['edge_id']}`: {v} (T-029 baseline, unchanged)")
    lines.append("")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))
    print(f"[T-036B] Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
