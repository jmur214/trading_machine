"""
scripts/audit_per_edge_substrate.py
====================================
Per-edge substrate-honest audit.

For each `status: active` edge in `data/governor/edges.yml`, runs single-
edge backtests on both the static-109 universe and the survivorship-bias-
aware S&P 500 historical union, then computes the substrate-honest Sharpe
delta. Edges are classified per the F6-collapses audit schema:

    CONFIRMED  — |Δ Sharpe| ≤ 0.2 → keep active
    DEGRADED   — Sharpe drop 0.2-0.5 → mark paused
    FALSIFIED  — Sharpe drop > 0.5 → mark failed

Single-edge isolation is via the existing `exact_edge_ids` mechanism in
ModeController. The harness runs each backtest under `isolated()` so
governor state is anchored identically.

Note on time budget: a single-edge backtest on the historical universe
takes ~10-15 min (vs ~25 min for 9-edge), so 9 edges × 2 universes × 1
year ≈ 2-3 hours of wall time.

Usage:
    PYTHONHASHSEED=0 python -m scripts.audit_per_edge_substrate \\
        --year 2024 \\
        --output docs/Measurements/2026-05/substrate_collapse_edge_audit_2026_05_<DATE>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    ISOLATED_ANCHOR,
    TRADES_DIR,
    isolated,
    _find_run_id,
    _trades_canon_md5,
)


ACTIVE_EDGES_DEFAULT = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "herding_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "quality_roic_v1",
    "quality_gross_profitability_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.audit_per_edge_substrate", *sys.argv[1:]],
        )


def _run_single_edge_year(
    edge_id: str,
    year: int,
    use_historical_universe: bool,
) -> dict:
    """Run a single-edge backtest in isolation mode for one year."""
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
        use_historical_universe=use_historical_universe,
    )


def _execute_one(
    edge_id: str,
    year: int,
    universe_label: str,
    use_historical_universe: bool,
) -> dict:
    before = {
        p.name
        for p in TRADES_DIR.iterdir()
        if p.is_dir() and p.name != "backup"
    }
    t0 = time.time()
    try:
        with isolated():
            summary = _run_single_edge_year(edge_id, year, use_historical_universe)
        run_id = _find_run_id(before) or "?"
        rec = {
            "edge_id": edge_id,
            "year": year,
            "universe": universe_label,
            "use_historical_universe": use_historical_universe,
            "run_id": run_id,
            "sharpe": summary.get("Sharpe Ratio"),
            "cagr_pct": summary.get("CAGR (%)"),
            "max_drawdown_pct": summary.get("Max Drawdown (%)"),
            "win_rate_pct": summary.get("Win Rate (%)"),
            "total_trades": summary.get("Total Trades"),
            "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
            "wall_time_seconds": round(time.time() - t0, 1),
            "ok": True,
        }
    except Exception as e:
        rec = {
            "edge_id": edge_id,
            "year": year,
            "universe": universe_label,
            "use_historical_universe": use_historical_universe,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "wall_time_seconds": round(time.time() - t0, 1),
        }
    print(f"  [{universe_label}/{edge_id}/{year}] {rec}", flush=True)
    return rec


def _classify(delta_sharpe: float) -> str:
    """delta_sharpe = static_sharpe - historical_sharpe (positive = drop)."""
    if abs(delta_sharpe) <= 0.2:
        return "CONFIRMED"
    if delta_sharpe <= 0.5:  # drop is between 0.2 and 0.5
        return "DEGRADED"
    return "FALSIFIED"


def _summarize(results: list[dict]) -> dict:
    """Aggregate per-edge static vs historical Sharpes and classify."""
    by_edge: dict[str, dict] = {}
    for r in results:
        if not r.get("ok") or r.get("sharpe") is None:
            continue
        eid = r["edge_id"]
        by_edge.setdefault(eid, {"static": [], "historical": []})
        if r["use_historical_universe"]:
            by_edge[eid]["historical"].append(r["sharpe"])
        else:
            by_edge[eid]["static"].append(r["sharpe"])

    classifications: dict[str, dict] = {}
    for eid, group in by_edge.items():
        s_static = group["static"]
        s_hist = group["historical"]
        if not s_static or not s_hist:
            classifications[eid] = {
                "ok": False,
                "reason": "incomplete (missing static or historical run)",
                "static": s_static,
                "historical": s_hist,
            }
            continue
        static_mean = sum(s_static) / len(s_static)
        hist_mean = sum(s_hist) / len(s_hist)
        delta = static_mean - hist_mean  # positive = static beats historical
        verdict = _classify(delta)
        classifications[eid] = {
            "ok": True,
            "static_mean_sharpe": static_mean,
            "historical_mean_sharpe": hist_mean,
            "delta_sharpe_static_minus_historical": delta,
            "verdict": verdict,
        }

    confirmed = [e for e, c in classifications.items() if c.get("verdict") == "CONFIRMED"]
    degraded = [e for e, c in classifications.items() if c.get("verdict") == "DEGRADED"]
    falsified = [e for e, c in classifications.items() if c.get("verdict") == "FALSIFIED"]
    return {
        "per_edge": classifications,
        "n_confirmed": len(confirmed),
        "n_degraded": len(degraded),
        "n_falsified": len(falsified),
        "confirmed_edges": confirmed,
        "degraded_edges": degraded,
        "falsified_edges": falsified,
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--years",
        type=str,
        default="2024",
        help="Comma-separated years to run (e.g. '2021,2024').",
    )
    parser.add_argument(
        "--edges",
        type=str,
        default=",".join(ACTIVE_EDGES_DEFAULT),
        help="Comma-separated edge_ids to audit. Default = 9 active edges.",
    )
    parser.add_argument(
        "--universes",
        type=str,
        default="static,historical",
        help="Comma-separated subset of {static, historical}.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="docs/Measurements/2026-05/substrate_collapse_edge_audit_2026_05_09.json",
    )
    args = parser.parse_args()

    if not ISOLATED_ANCHOR.exists():
        print(f"[PER-EDGE] No anchor at {ISOLATED_ANCHOR}.", file=sys.stderr)
        return 1

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    edges = [e.strip() for e in args.edges.split(",") if e.strip()]
    universes = [u.strip() for u in args.universes.split(",") if u.strip()]

    results: list[dict] = []
    t_start = time.time()
    n_total = len(years) * len(edges) * len(universes)
    counter = 0

    # Order: for each universe, iterate edges so that universe-related caches
    # (membership parquet for historical, OHLCV slices) stay warm.
    for universe in universes:
        use_historical = universe == "historical"
        for edge_id in edges:
            for year in years:
                counter += 1
                elapsed = time.time() - t_start
                avg = elapsed / max(counter - 1, 1) if counter > 1 else 0
                eta = avg * (n_total - counter + 1)
                print(
                    f"\n===== [{counter}/{n_total}] universe={universe} "
                    f"edge={edge_id} year={year} elapsed={elapsed/60:.1f}m "
                    f"ETA={eta/60:.1f}m =====",
                    flush=True,
                )
                rec = _execute_one(edge_id, year, universe, use_historical)
                results.append(rec)
                _persist({"results": results}, args.output)

    summary = _summarize(results)
    final = {
        "metadata": {
            "years": years,
            "edges": edges,
            "universes": universes,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "wall_time_seconds": round(time.time() - t_start, 1),
        },
        "results": results,
        "summary": summary,
    }
    _persist(final, args.output)
    print(f"\n[PER-EDGE] Done in {(time.time()-t_start)/60:.1f}m.")
    print(json.dumps(summary, indent=2))
    return 0


def _persist(payload: dict, out_path: str) -> None:
    p = ROOT / out_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
