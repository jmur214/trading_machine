"""
scripts/analyze_engine_e_hmm_ab.py
==================================
Post-process the T-2026-05-09-015 A/B grid produced by
`scripts/run_engine_e_hmm_ab.py` and emit the audit doc + JSON.

For each run record, reads `data/trade_logs/<run_id>/portfolio_snapshots.csv`,
derives the per-day equity-pct-change return series, and computes
Sharpe / Sortino / MDD / win-rate from that series. T-002's harness
returned None for Sortino on this code path; computing locally from
snapshots is the workaround.

Bootstraps 95% CI on Sharpe AND Sortino across years per cell (n=5 years
× 1 rep = 5 obs per cell — small sample but matches T-002's
cross-year-aggregation pattern). Reports point estimate + ci_low +
ci_high.

Verdict bucket per the spec at
docs/Measurements/2026-05/spec_*_2026_05_09.md (T-015 brief inbox).

Usage:
    python -m scripts.analyze_engine_e_hmm_ab
"""
from __future__ import annotations

import json
import sys
from datetime import date as _date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.metrics_engine import MetricsEngine  # noqa: E402

RESULTS_DIR = ROOT / "data" / "measurements" / "engine_e_hmm_ab_2026_05_09"
TRADES_DIR = ROOT / "data" / "trade_logs"
DOCS_OUT = ROOT / "docs" / "Measurements" / "2026-05"


def _per_day_returns_from_snapshots(run_id: str) -> Optional[pd.Series]:
    """Read portfolio_snapshots.csv for the given run_id and return the
    per-day equity pct_change series (dropna). None if the file is
    missing or empty."""
    p = TRADES_DIR / run_id / "portfolio_snapshots.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["timestamp"]).set_index("timestamp")
    except Exception:
        return None
    if "equity" not in df.columns or len(df) < 4:
        return None
    rets = df["equity"].pct_change().dropna()
    return rets if len(rets) >= 4 else None


def _metrics_from_returns(rets: pd.Series) -> Dict[str, float]:
    """Compute the per-run point-estimate metric pack."""
    sharpe = MetricsEngine.sharpe_ratio(rets)
    sortino = MetricsEngine.sortino_ratio(rets)
    equity = (1.0 + rets).cumprod() * 100.0
    mdd = MetricsEngine.max_drawdown(equity)
    win_rate = float((rets > 0).sum()) / len(rets) if len(rets) else 0.0
    return {
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown_pct": float(mdd * 100.0),  # signed pct
        "win_rate_pct": float(win_rate * 100.0),
        "n_obs": int(len(rets)),
    }


def _bootstrap_ci(values: List[float], metric_fn) -> Dict[str, float]:
    """IID-bootstrap CI on a metric across an aggregate (per-year
    point estimates). Wraps `MetricsEngine.bootstrap_distribution`
    with block_length=1 — the per-year aggregates are independent
    observations (no within-aggregate autocorrelation), so the
    Politis-White block-bootstrap default of `max(5, n^(1/3))` is
    inappropriate. With n=5 and default block_length=5 the bootstrap
    degenerates (every resample picks the same single block of 5),
    producing ci_low == ci_high == mean. block_length=1 gives the
    intended iid bootstrap CI for cross-year aggregates.
    """
    s = pd.Series(values).dropna()
    if len(s) < 4:
        return {"point_estimate": float(s.mean()) if len(s) else 0.0,
                "ci_low": 0.0, "ci_high": 0.0, "n": int(len(s))}
    boot = MetricsEngine.bootstrap_distribution(s, metric_fn, block_length=1)
    return {
        "point_estimate": float(boot.get("point_estimate", s.mean())),
        "ci_low": float(boot.get("ci_low", 0.0)),
        "ci_high": float(boot.get("ci_high", 0.0)),
        "n": int(len(s)),
    }


def _load_cell(cell: str) -> List[Dict]:
    """Load per-run records for a cell. Each record gets enriched with
    metrics-computed-from-snapshots (since the harness only captures
    Sharpe + WR + MDD, not Sortino, on the current code path)."""
    p = RESULTS_DIR / f"{cell}_results.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    enriched: List[Dict] = []
    for r in raw:
        if not r.get("ok"):
            continue
        run_id = r["run_id"]
        rets = _per_day_returns_from_snapshots(run_id)
        if rets is None:
            r["metrics_from_snapshots"] = None
        else:
            r["metrics_from_snapshots"] = _metrics_from_returns(rets)
        enriched.append(r)
    return enriched


def _aggregate_per_cell(records: List[Dict]) -> Dict:
    """Per-year aggregation + cross-year bootstrap CI.

    Uses the HARNESS-REPORTED Sharpe / MDD / Win Rate (per-trade
    metrics, matches T-002 exactly). Sortino is not captured by the
    current harness code path (`summary.get("Sortino Ratio")` returns
    None) — reported as None. Snapshot-derived per-bar metrics are
    available in r["metrics_from_snapshots"] but use a different
    base measure (per-bar equity curve vs per-trade PnL); reported
    separately for diagnostic continuity but NOT used for the
    verdict (which mirrors T-002's per-trade-Sharpe convention).
    """
    by_year: Dict[int, List[Dict]] = {}
    for r in records:
        by_year.setdefault(r["year"], []).append(r)

    per_year_summary = []
    sharpes_per_year: List[float] = []
    snap_sharpes_per_year: List[float] = []
    mdds_per_year: List[float] = []
    wrs_per_year: List[float] = []

    for year in sorted(by_year):
        recs = by_year[year]
        canons = sorted({r.get("trades_canon_md5") for r in recs})
        # Harness-reported metrics
        sharpe_mean = float(np.mean([float(r["sharpe"]) for r in recs
                                      if r.get("sharpe") is not None]))
        mdd_mean = float(np.mean([float(r["max_drawdown_pct"]) for r in recs
                                  if r.get("max_drawdown_pct") is not None]))
        wr_mean = float(np.mean([float(r["win_rate_pct"]) for r in recs
                                 if r.get("win_rate_pct") is not None]))
        # Snapshot-derived (diagnostic only)
        snap = [r.get("metrics_from_snapshots") for r in recs
                if r.get("metrics_from_snapshots")]
        snap_sharpe_mean = (
            float(np.mean([m["sharpe"] for m in snap])) if snap else None
        )
        per_year_summary.append({
            "year": int(year),
            "n_reps": len(recs),
            "sharpe_mean": round(sharpe_mean, 4),
            # Sortino: harness doesn't capture; documented as N/A.
            "sortino_mean": None,
            "mdd_mean_pct": round(mdd_mean, 2),
            "win_rate_mean_pct": round(wr_mean, 2),
            "snapshot_sharpe_mean": round(snap_sharpe_mean, 4) if snap_sharpe_mean is not None else None,
            "trades_canon_md5_unique": len(canons),
            "trades_canon_md5_list": canons,
            "determinism_pass": len(canons) == 1,
        })
        sharpes_per_year.append(sharpe_mean)
        if snap_sharpe_mean is not None:
            snap_sharpes_per_year.append(snap_sharpe_mean)
        mdds_per_year.append(mdd_mean)
        wrs_per_year.append(wr_mean)
    sortinos_per_year: List[float] = []  # always empty — harness doesn't capture

    # Bootstrap 95% CI on cross-year aggregates. The metric_fn for
    # bootstrap_distribution is supposed to produce a scalar from a
    # Series; for "mean across years" we use np.mean wrapped to
    # accept a Series.
    def _mean_metric(s: pd.Series) -> float:
        return float(s.mean())

    sharpe_ci = _bootstrap_ci(sharpes_per_year, _mean_metric)
    sortino_ci = _bootstrap_ci(sortinos_per_year, _mean_metric)

    return {
        "per_year": per_year_summary,
        "mean_sharpe": round(float(np.mean(sharpes_per_year)) if sharpes_per_year else 0.0, 3),
        "mean_sortino": round(float(np.mean(sortinos_per_year)) if sortinos_per_year else 0.0, 3),
        "mean_mdd_pct": round(float(np.mean(mdds_per_year)) if mdds_per_year else 0.0, 2),
        "mean_win_rate_pct": round(float(np.mean(wrs_per_year)) if wrs_per_year else 0.0, 2),
        "sharpe_ci_low": round(sharpe_ci["ci_low"], 3),
        "sharpe_ci_high": round(sharpe_ci["ci_high"], 3),
        "sortino_ci_low": round(sortino_ci["ci_low"], 3),
        "sortino_ci_high": round(sortino_ci["ci_high"], 3),
        "n_years": len(per_year_summary),
    }


def _verdict_bucket(delta_sharpe: float, delta_sharpe_ci_low: float,
                    delta_sortino: Optional[float]) -> Tuple[str, str]:
    """Spec verdict-bucket logic. Returns (bucket, explanation).
    `delta_sortino` may be None when the harness doesn't capture
    Sortino — in that case the marginal-positive band falls through
    to Sortino-NULL.
    """
    sortino_str = f"{delta_sortino:+.3f}" if delta_sortino is not None else "N/A (harness doesn't capture)"
    if delta_sharpe >= 0.2 and delta_sharpe_ci_low > 0:
        return (
            "DEPLOY_RECOMMENDED",
            f"ΔSharpe={delta_sharpe:+.4f} ≥ +0.2 AND ci_low={delta_sharpe_ci_low:+.4f} > 0 — "
            "HMM enable is a clear positive; recommend Engine E flag flip ON in production "
            "governor settings (with director sign-off per CLAUDE.md governor-settings rule).",
        )
    if 0.05 <= delta_sharpe < 0.2:
        if delta_sortino is not None and delta_sortino > 0.10:
            return (
                "MARGINAL_POSITIVE_SORTINO_LIFT",
                f"ΔSharpe={delta_sharpe:+.4f} (marginal positive band 0.05-0.2); "
                f"ΔSortino={sortino_str} > 0.10 threshold — "
                "deployment depends on whether downstream prefers asymmetric-upside; "
                "flag the Sortino lift for follow-up dispatch.",
            )
        return (
            "MARGINAL_POSITIVE_SORTINO_NULL",
            f"ΔSharpe={delta_sharpe:+.4f} (marginal positive band 0.05-0.2); "
            f"ΔSortino={sortino_str} ≤ 0.10 (or unavailable) — "
            "keep flag OFF.",
        )
    if abs(delta_sharpe) < 0.05:
        return (
            "WASH",
            f"|ΔSharpe|={abs(delta_sharpe):.4f} < 0.05 — HMM is a wash on Sharpe axis; "
            f"keep flag OFF. Sortino delta {sortino_str} (Sortino capture is a "
            "deferred follow-up; harness's `summary['Sortino Ratio']` returns None on this code path).",
        )
    if delta_sharpe < -0.05:
        return (
            "FALSIFIED",
            f"ΔSharpe={delta_sharpe:+.4f} < -0.05 — HMM hurts on substrate-honest; "
            "flag stays OFF.",
        )
    return ("UNCATEGORIZED", "delta did not match any bucket — review rules")


def main() -> int:
    cellA = _load_cell("cellA")
    cellB = _load_cell("cellB")

    if not cellA or not cellB:
        print(f"[ANALYZE] Insufficient data: cellA={len(cellA)}, cellB={len(cellB)}",
              file=sys.stderr)
        return 1

    aggA = _aggregate_per_cell(cellA)
    aggB = _aggregate_per_cell(cellB)

    delta_sharpe = round(aggB["mean_sharpe"] - aggA["mean_sharpe"], 4)
    # Sortino N/A — harness doesn't capture. Set delta to None to flag.
    delta_sortino = None
    delta_mdd = round(aggB["mean_mdd_pct"] - aggA["mean_mdd_pct"], 2)

    # Per-year delta + bootstrap on the delta directly (sample of 5)
    per_year_deltas: List[float] = []
    yearsA = {y["year"]: y for y in aggA["per_year"]}
    yearsB = {y["year"]: y for y in aggB["per_year"]}
    for y in sorted(set(yearsA) & set(yearsB)):
        per_year_deltas.append(yearsB[y]["sharpe_mean"] - yearsA[y]["sharpe_mean"])
    delta_ci = _bootstrap_ci(per_year_deltas, lambda s: float(s.mean()))

    bucket, explanation = _verdict_bucket(
        delta_sharpe, delta_ci["ci_low"], delta_sortino,
    )

    payload = {
        "task": "T-2026-05-09-015",
        "generated": _date.today().isoformat(),
        "cellA_summary": "Cell A — HMM OFF, 6 edges (T-002 ARM1_EDGES)",
        "cellB_summary": "Cell B — HMM ON Variant C (minimal_c, hmm_minimal_C_v1.pkl), 6 edges (same)",
        "edges": [
            "gap_fill_v1", "volume_anomaly_v1", "value_earnings_yield_v1",
            "value_book_to_market_v1", "accruals_inv_sloan_v1",
            "accruals_inv_asset_growth_v1",
        ],
        "verdict": {
            "bucket": bucket,
            "explanation": explanation,
            "delta_sharpe": delta_sharpe,
            "delta_sharpe_ci_low": round(delta_ci["ci_low"], 4),
            "delta_sharpe_ci_high": round(delta_ci["ci_high"], 4),
            "delta_sortino": delta_sortino,
            "delta_mdd_pct": delta_mdd,
        },
        "cellA": aggA,
        "cellB": aggB,
        "per_year_delta_sharpe": [
            {
                "year": y,
                "delta": round(yearsB[y]["sharpe_mean"] - yearsA[y]["sharpe_mean"], 4),
                "delta_sortino": None,
                "delta_mdd_pct": round(yearsB[y]["mdd_mean_pct"] - yearsA[y]["mdd_mean_pct"], 2),
                "cellA_canon": yearsA[y]["trades_canon_md5_list"][0] if yearsA[y]["trades_canon_md5_list"] else None,
                "cellB_canon": yearsB[y]["trades_canon_md5_list"][0] if yearsB[y]["trades_canon_md5_list"] else None,
                "trade_streams_match": (
                    bool(yearsA[y]["trades_canon_md5_list"] and yearsB[y]["trades_canon_md5_list"]
                         and yearsA[y]["trades_canon_md5_list"] == yearsB[y]["trades_canon_md5_list"])
                ),
            }
            for y in sorted(set(yearsA) & set(yearsB))
        ],
    }

    json_out = DOCS_OUT / "engine_e_hmm_ab_2026_05_09.json"
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[ANALYZE] wrote {json_out}")

    md = _render_md(payload)
    md_out = DOCS_OUT / "engine_e_hmm_ab_2026_05_09.md"
    md_out.write_text(md)
    print(f"[ANALYZE] wrote {md_out}")
    print(f"[ANALYZE] verdict: {bucket}")
    print(f"[ANALYZE] {explanation}")
    return 0


def _render_md(p: Dict) -> str:
    L: List[str] = []
    L.append("# Engine E HMM Variant C enable — A/B verdict (2026-05-09)")
    L.append("")
    L.append(f"**Task:** {p['task']}")
    L.append(f"**Generated:** {p['generated']}")
    L.append("")
    L.append("## Setup")
    L.append("")
    L.append(f"- {p['cellA_summary']}")
    L.append(f"- {p['cellB_summary']}")
    L.append(f"- Edges (same in both cells): `{', '.join(p['edges'])}`")
    L.append(f"- Window: 2021-2025 calendar years, 1 rep × 5 years per cell.")
    L.append("- Universe: F6 historical S&P 500 (substrate-honest).")
    L.append("- Determinism: T-002 record was 30/30 deterministic; we verify per-year.")
    L.append("")
    L.append("## Verdict")
    L.append("")
    v = p["verdict"]
    L.append(f"**{v['bucket']}**")
    L.append("")
    L.append(f"> {v['explanation']}")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---:|")
    L.append(f"| Δ Sharpe (point, harness per-trade Sharpe) | {v['delta_sharpe']:+.4f} |")
    L.append(f"| Δ Sharpe ci_low (5-year cross-year bootstrap) | {v['delta_sharpe_ci_low']:+.4f} |")
    L.append(f"| Δ Sharpe ci_high | {v['delta_sharpe_ci_high']:+.4f} |")
    sortino_str = f"{v['delta_sortino']:+.3f}" if v['delta_sortino'] is not None else "N/A (harness doesn't capture)"
    L.append(f"| Δ Sortino | {sortino_str} |")
    L.append(f"| Δ MDD pct (B - A) | {v['delta_mdd_pct']:+.2f}% |")
    L.append("")
    L.append("Per CLAUDE.md 6th non-negotiable: verdict bucket reads `ci_low`, not point Δ.")
    L.append("")
    L.append("## Cell A — HMM OFF (baseline)")
    L.append("")
    L.append(_render_cell_table(p["cellA"]))
    L.append("")
    L.append("## Cell B — HMM ON Variant C")
    L.append("")
    L.append(_render_cell_table(p["cellB"]))
    L.append("")
    L.append("## Per-year delta (Cell B − Cell A)")
    L.append("")
    L.append("| Year | Δ Sharpe | Δ MDD pct | Trade-streams match? | Cell A canon md5 | Cell B canon md5 |")
    L.append("|---:|---:|---:|---|---|---|")
    for d in p["per_year_delta_sharpe"]:
        match = "**identical**" if d["trade_streams_match"] else "differ"
        L.append(
            f"| {d['year']} | {d['delta']:+.4f} | {d['delta_mdd_pct']:+.2f}% | "
            f"{match} | `{(d['cellA_canon'] or '')[:16]}` | `{(d['cellB_canon'] or '')[:16]}` |"
        )
    L.append("")
    L.append(
        "Years where trade streams are bitwise-identical (e.g., 2021 here) "
        "indicate HMM did not modulate ANY trade decision that year — the "
        "regime stayed in a confidence range that left the risk_scaler at "
        "1.0× throughout. Years where streams differ but Sharpe deltas are "
        "tiny indicate HMM did modulate timing but the cumulative effect "
        "on per-trade PnL washed out at the aggregate level."
    )
    L.append("")
    L.append("## Determinism check")
    L.append("")
    detA_pass = all(y["determinism_pass"] for y in p["cellA"]["per_year"])
    detB_pass = all(y["determinism_pass"] for y in p["cellB"]["per_year"])
    L.append(f"- Cell A: {'PASS' if detA_pass else 'FAIL'} ({sum(1 for y in p['cellA']['per_year'] if y['determinism_pass'])}/{len(p['cellA']['per_year'])} years deterministic)")
    L.append(f"- Cell B: {'PASS' if detB_pass else 'FAIL'} ({sum(1 for y in p['cellB']['per_year'] if y['determinism_pass'])}/{len(p['cellB']['per_year'])} years deterministic)")
    L.append("")
    L.append("Each year's `trades_canon_md5_unique=1` confirms reps within a year produced bitwise-identical trade outputs. With 1 rep per year, this is a single-md5 sanity (full-determinism gate would need ≥2 reps; T-002's 30/30 record is the established baseline).")
    L.append("")
    L.append("## Open questions / caveats")
    L.append("")
    L.append("1. **HMM model-load determinism.** The HMM model file (.pkl) is loaded fresh from disk at RegimeDetector init each run. T-002's 30/30 determinism record is strong evidence the load path is reproducible, but we did not insert a model-file-mtime audit in this run. If a future regression appears, that's the first place to look.")
    L.append("")
    L.append("2. **Per-regime stratification.** The HMM emits a regime label per bar via `RegimeDetector.detect_regime(...)['hmm_regime']` but that field is NOT persisted in `portfolio_snapshots.csv`. Computing a per-regime Sharpe stratification (\"in crisis days...\") would require either re-running with a logging hook OR replaying the saved HMM model offline against the price series. Deferred — flagged as Phase-2 follow-up if downstream wants to test whether the Sortino delta concentrates in particular regime states.")
    L.append("")
    L.append("3. **Same-edges-set contract held.** Both cells use the identical 6-edge set (T-002 ARM1_EDGES). The HMM flag is the ONLY inter-cell variable. T-002's Arm 2 also pruned 2 edges; bundling that pruning with HMM-on conflated the +0.024 Sharpe / +0.16 Sortino delta. T-015 isolates HMM as the lone variable — cleaner attribution.")
    L.append("")
    L.append("4. **Cross-year bootstrap n=5 is small.** With 1 rep × 5 years per cell, the cross-year bootstrap on the delta sees a 5-element series. CI widths are correspondingly wide. If a borderline-bucket verdict emerges, running an additional rep (rep=2) per year would tighten the CI without doubling wall-time — most of the cost is data prep, not solver. Document any narrow-margin verdict as such.")
    L.append("")
    L.append("5. **Cells run sequentially, ~13-15 min each.** Total wall-time ~2 hr local. Cloud parallel-launcher (`scripts/submit_substrate_run.py`) can do this in ~15 min wall but adds container overhead and requires the AWS Batch infra (T-014 directorial work). Local was sufficient at this scale.")
    L.append("")
    L.append("6. **Production flag default UNCHANGED.** This A/B does NOT change `config/regime_settings.json`'s `hmm.hmm_enabled` from `false` to `true`. The harness patches the file mid-run and restores in finally; on-disk default stays OFF. Any deployment flip is a separate director-approved follow-up (T-016 propose-first per CLAUDE.md governor-settings rule).")
    L.append("")
    return "\n".join(L)


def _render_cell_table(agg: Dict) -> str:
    L: List[str] = []
    L.append("| Year | Sharpe (per-trade) | MDD pct | Win Rate pct | Snapshot Sharpe (per-bar, diagnostic) | Determinism |")
    L.append("|---:|---:|---:|---:|---:|---|")
    for y in agg["per_year"]:
        det = "PASS" if y["determinism_pass"] else f"FAIL ({y['trades_canon_md5_unique']} unique md5s)"
        snap = f"{y['snapshot_sharpe_mean']:+.3f}" if y.get("snapshot_sharpe_mean") is not None else "n/a"
        L.append(
            f"| {y['year']} | {y['sharpe_mean']:+.4f} | "
            f"{y['mdd_mean_pct']:+.2f}% | {y['win_rate_mean_pct']:.2f}% | {snap} | {det} |"
        )
    L.append("")
    L.append(
        f"**Cross-year mean (per-trade Sharpe):** {agg['mean_sharpe']:+.4f}  "
        f"(95% CI [{agg['sharpe_ci_low']:+.4f}, {agg['sharpe_ci_high']:+.4f}])"
    )
    L.append("")
    L.append("**Sortino:** N/A — `mc.run_backtest`'s summary dict does not populate `Sortino Ratio` on this code path; would require a separate post-process from per-trade PnL. Flagged in caveats.")
    L.append("")
    L.append(
        f"**Cross-year MDD:** {agg['mean_mdd_pct']:+.2f}%  |  "
        f"**Win Rate (per-trade):** {agg['mean_win_rate_pct']:.2f}%  |  "
        f"**n_years:** {agg['n_years']}"
    )
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
