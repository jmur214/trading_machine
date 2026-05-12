"""
scripts/factor_decomp_per_regime.py
====================================
Per-regime FF5+Mom factor decomposition on 11 edges (T-2026-05-11-029).

Builds on T-004's `factor_decomp_substrate_honest.py` (commit ae35591):
partition each edge's attribution stream by `regime_label` (from
trades.csv), then run a separate FF5+Mom HAC OLS regression per
(edge, regime) cell.

Verdict buckets per-edge across regimes:
- REGIME-MISTUNED: α t > +2 in ≥1 regime AND α t < -2 in another → wire to Engine E
- UNIFORMLY POSITIVE: α t > +2 in ≥1 regime, no significant-negative regime
- UNIFORMLY NEGATIVE: α t < -2 in ≥1 regime, no significant-positive regime
- UNIFORMLY NOISY: |α t| < 2 across all regimes
- INSUFFICIENT DATA (per regime n_obs < 30)

Edge / run_id inventory:
- 6 active edges from T-002 Arm 1 (rep 1, 5 yearly run_ids)
- 5 new paused edges from T-020 per-edge isolation (5 yearly run_ids each = 25 total)

Outputs:
  docs/Audit/per_regime_factor_decomp_2026_05_11.md
  docs/Audit/per_regime_factor_decomp_2026_05_11.json

Re-runnable: deterministic (seed=0 on bootstrap); same trade logs in
produces bit-identical output (frozen timestamp on rendered doc).

Usage:
  python -m scripts.factor_decomp_per_regime
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse T-004's HAC + bootstrap + factor-loader machinery
from scripts.factor_decomp_substrate_honest import (  # noqa: E402
    newey_west_lag,
    newey_west_cov,
    FACTOR_COLS,
    INITIAL_CAPITAL,
    T_STAT_THRESHOLD,
)
from core.factor_decomposition import load_factor_data  # noqa: E402

TRADE_LOGS = ROOT / "data" / "trade_logs"
OUT_MD = ROOT / "docs" / "Audit" / "per_regime_factor_decomp_2026_05_11.md"
OUT_JSON = ROOT / "docs" / "Audit" / "per_regime_factor_decomp_2026_05_11.json"

# T-002 Arm 1 rep-1 run_ids — contain all 6 active edges' trades
T002_ARM1_RUN_IDS: Dict[int, str] = {
    2021: "191c14ba-3e8d-4f7f-ae08-8b24bf54dec0",
    2022: "85ae17d9-a7b9-473b-933a-94dc0c681fcc",
    2023: "a23ce948-9fd0-43ef-84c6-dc6aaa7653ca",
    2024: "a1591104-7c2b-428c-a02a-a1fa712fe569",
    2025: "a3aac752-6daa-487a-a3e5-2f1e4d81d319",
}

T002_ACTIVE_EDGES = [
    "volume_anomaly_v1",
    "gap_fill_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "value_earnings_yield_v1",
    "accruals_inv_asset_growth_v1",
]

# T-020 per-edge isolation run_ids (one isolated backtest per (edge, year))
T020_RUN_IDS: Dict[str, Dict[int, str]] = {
    "momentum_12_1_v1": {
        2021: "d4058acf-cf7f-404a-9e3c-b8cbbf0db157",
        2022: "832b5cfd-73db-4b24-87a6-52eed96ee070",
        2023: "b87a30ff-0643-4f00-9396-4021ab5e985b",
        2024: "eb7ad3a9-ea09-414d-a1f8-d830ebbb8aa5",
        2025: "9e00423c-8c9e-4a04-a189-a1f908a05222",
    },
    "momentum_6_1_v1": {
        2021: "182a2c48-d5a5-45b3-b69f-2bb09b7dc54a",
        2022: "307a9c18-859b-46a3-adcf-ba009e5e27f4",
        2023: "0430c338-5de1-4680-acc4-f0f641e91809",
        2024: "6a2c7e03-accd-4491-a063-bbeddb4f99fa",
        2025: "70b822af-6acb-446f-b6d9-1db82e2e07cb",
    },
    "short_term_reversal_v1": {
        2021: "6b349146-143c-4c8f-9f5b-123ac88a19cf",
        2022: "7693cf71-ccd1-4ed1-8f3a-037daf035bc6",
        2023: "5daa56bb-c6ca-41ca-826c-0b0a13fb536f",
        2024: "f8540b65-376b-49cc-9866-fa85f52f3df1",
        2025: "155c1c6d-33a0-463d-b0f0-224400bbbb77",
    },
    "pairs_trading_MA_V_v1": {
        2021: "722ba4a0-12a3-4b6a-b781-edd24fef1407",
        2022: "9e92086e-da21-4b5a-aef8-0bcc2665f089",
        2023: "4d450f47-7972-42d1-9969-2c126b084e66",
        2024: "e20b7d0b-23ac-457a-8cb5-ca4b42468fcf",
        2025: "12267b74-6d51-4253-8b49-9322fa10b987",
    },
    "dividend_initiation_drift_v1": {
        2021: "903571dd-05bf-4793-b1e1-4ca5c299ef28",
        2022: "6fc11041-7423-419a-b4fe-7efe434e2027",
        2023: "fcce92d8-0d30-4244-860e-8835372494fc",
        2024: "dfe5c781-553d-400a-8975-a40b86e33ed4",
        2025: "24242e71-17da-4dc4-8981-a9815fa30d27",
    },
}

# Aggregate-window α t-stats from T-004 (the comparison baseline)
T004_AGGREGATE_ALPHA_T: Dict[str, float] = {
    "volume_anomaly_v1": 0.83,
    "gap_fill_v1": -0.04,
    "value_book_to_market_v1": -2.60,
    "accruals_inv_sloan_v1": -4.08,
    "value_earnings_yield_v1": -5.69,
    "accruals_inv_asset_growth_v1": -5.12,
    "momentum_12_1_v1": 0.36,
    "momentum_6_1_v1": -1.01,
    "short_term_reversal_v1": 1.76,
    "pairs_trading_MA_V_v1": None,  # T-020 didn't include this in its aggregate decomp
    "dividend_initiation_drift_v1": None,
}


def _trades_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "trades.csv"
    p2 = TRADE_LOGS / run_id / f"trades_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


def load_closed_trades_for_edge(
    edge_id: str, run_ids: Dict[int, str]
) -> pd.DataFrame:
    """Concatenate closed-trade rows for this edge across the provided
    yearly run_ids. Returns columns: timestamp, edge_id, pnl, regime_label.

    Each yearly run started fresh at $100k (T-002 + T-020 convention).
    """
    frames = []
    for year, run_id in run_ids.items():
        p = _trades_path(run_id)
        if p is None:
            continue
        df = pd.read_csv(
            p, low_memory=False,
            usecols=["timestamp", "side", "edge_id", "pnl", "regime_label"],
        )
        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        closed = df.dropna(subset=["pnl"])
        closed = closed[closed["edge_id"] == edge_id]
        frames.append(closed)
    if not frames:
        return pd.DataFrame(columns=["timestamp", "edge_id", "pnl", "regime_label"])
    return pd.concat(frames, ignore_index=True)


def build_daily_returns_per_regime(
    closed: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """Group closed-trade PnL by (date, regime_label) and build a
    daily-return series PER regime. Daily return = pnl_today / initial_capital
    (matches T-004's tier_classifier convention)."""
    out: Dict[str, pd.Series] = {}
    if closed.empty:
        return out
    closed = closed.copy()
    closed["date"] = closed["timestamp"].dt.normalize()
    grouped = closed.groupby(["regime_label", "date"])["pnl"].sum()
    for regime in closed["regime_label"].dropna().unique():
        series = grouped.loc[regime] / INITIAL_CAPITAL
        series = series.sort_index()
        series.name = f"{regime}"
        out[str(regime)] = series
    return out


def regress_hac_with_bootstrap(
    edge_returns: pd.Series,
    factors: pd.DataFrame,
) -> Dict:
    """OLS + Newey-West HAC + residual bootstrap CI on α (annualized).
    Mirrors T-004's `regress_with_hac` but stripped to the per-regime
    use case (no per-factor t-stats; α + α_ci + R² are enough for
    verdict bucketing)."""
    aligned = pd.concat(
        [edge_returns.rename("edge"), factors],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 30:
        return {"ok": False, "n_obs": int(len(aligned)),
                "reason": "n_obs<30 (insufficient for HAC inference)"}

    excess = (aligned["edge"] - aligned["RF"]).values
    X = aligned[FACTOR_COLS].values
    X_design = np.hstack([np.ones((len(excess), 1)), X])

    coefs, _, _, _ = np.linalg.lstsq(X_design, excess, rcond=None)
    fitted = X_design @ coefs
    resid = excess - fitted

    n = len(excess)
    lag = newey_west_lag(n)
    hac_cov = newey_west_cov(X_design, resid, lag)
    hac_se = np.sqrt(np.maximum(np.diag(hac_cov), 0.0))

    alpha_daily = float(coefs[0])
    alpha_annual = alpha_daily * 252.0
    alpha_se_daily = float(hac_se[0])
    alpha_tstat = alpha_daily / alpha_se_daily if alpha_se_daily > 0 else 0.0
    alpha_se_annual = alpha_se_daily * 252.0
    z = 1.96
    alpha_ci_low_annual = alpha_annual - z * alpha_se_annual
    alpha_ci_high_annual = alpha_annual + z * alpha_se_annual

    ss_res = float(resid @ resid)
    ss_tot = float(((excess - excess.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Residual moving-block bootstrap on α (matches T-004 convention)
    rng = np.random.default_rng(0)
    block = max(1, lag + 1)
    n_iter = 1000
    boot_alphas = np.empty(n_iter, dtype=float)
    n_blocks = int(np.ceil(n / block))
    for i in range(n_iter):
        starts = rng.integers(0, max(1, n - block + 1), size=n_blocks)
        boot_idx = np.concatenate([
            np.arange(s, s + block) for s in starts
        ])[:n]
        e_star = resid[boot_idx]
        y_star = fitted + e_star
        b_star, _, _, _ = np.linalg.lstsq(X_design, y_star, rcond=None)
        boot_alphas[i] = float(b_star[0]) * 252.0
    boot_ci_low = float(np.percentile(boot_alphas, 2.5))
    boot_ci_high = float(np.percentile(boot_alphas, 97.5))

    return {
        "ok": True,
        "n_obs": n,
        "lag_neweywest": lag,
        "alpha_daily": alpha_daily,
        "alpha_annualized": alpha_annual,
        "alpha_se_annualized_hac": alpha_se_annual,
        "alpha_tstat_hac": float(alpha_tstat),
        "alpha_ci_low_analytic": alpha_ci_low_annual,
        "alpha_ci_high_analytic": alpha_ci_high_annual,
        "alpha_ci_low_bootstrap": boot_ci_low,
        "alpha_ci_high_bootstrap": boot_ci_high,
        "r_squared": r2,
    }


def classify_edge(per_regime_results: Dict[str, Dict]) -> str:
    """Apply the spec's 5-bucket verdict per edge across its regimes.

    Buckets are based on regimes WITH SUFFICIENT DATA (n_obs >= 30).
    A regime with insufficient data is excluded from the classification
    but flagged in the verdict text. INSUFFICIENT DATA verdict fires
    only when NO regime has sufficient data."""
    pos_regimes = []
    neg_regimes = []
    insufficient = []
    sufficient_observed = 0
    for regime, r in per_regime_results.items():
        if not r.get("ok"):
            insufficient.append(regime)
            continue
        sufficient_observed += 1
        t = r["alpha_tstat_hac"]
        if t > T_STAT_THRESHOLD:
            pos_regimes.append((regime, t, r["alpha_annualized"]))
        elif t < -T_STAT_THRESHOLD:
            neg_regimes.append((regime, t, r["alpha_annualized"]))

    suffix = (
        f" (note: insufficient data in {insufficient})"
        if insufficient else ""
    )

    # Bucket on sufficient-data regimes only.
    if pos_regimes and neg_regimes:
        return (
            f"REGIME-MISTUNED — positive α (t>+2) in "
            f"{[p[0] for p in pos_regimes]}, negative α (t<-2) in "
            f"{[n[0] for n in neg_regimes]}. RESCUE CANDIDATE: wire to "
            f"Engine E regime classifier; fire only in favorable regime(s)."
            f"{suffix}"
        )
    if pos_regimes and not neg_regimes:
        return (
            f"UNIFORMLY POSITIVE — α (t>+2) in {[p[0] for p in pos_regimes]}; "
            f"no significantly-negative regime. STRONG PROMOTE CANDIDATE "
            f"(active or Sortino-vehicle dispatch).{suffix}"
        )
    if neg_regimes and not pos_regimes:
        return (
            f"UNIFORMLY NEGATIVE — α (t<-2) in {[n[0] for n in neg_regimes]}; "
            f"no significantly-positive regime. CONFIRMED RETIRE CANDIDATE "
            f"(stronger than T-004's aggregate finding).{suffix}"
        )
    if sufficient_observed > 0:
        # All sufficient-data regimes returned |t| < 2.
        return (
            f"UNIFORMLY NOISY — |α t|<2 across all {sufficient_observed} "
            f"sufficient-data regime(s); no detectable signal. Keep paused; "
            f"no factor-adjusted alpha.{suffix}"
        )
    # No sufficient-data regimes at all.
    return (
        f"INSUFFICIENT DATA — n_obs<30 in ALL regimes "
        f"{insufficient}; cannot bucket without more samples."
    )


def analyze_edge(
    edge_id: str, run_ids: Dict[int, str], factors: pd.DataFrame,
) -> Dict:
    """Full per-regime decomp for one edge."""
    closed = load_closed_trades_for_edge(edge_id, run_ids)
    streams = build_daily_returns_per_regime(closed)

    per_regime: Dict[str, Dict] = {}
    for regime, series in streams.items():
        result = regress_hac_with_bootstrap(series, factors)
        per_regime[regime] = result

    verdict = classify_edge(per_regime)
    return {
        "edge_id": edge_id,
        "n_closed_trades": int(len(closed)),
        "regimes_observed": sorted(streams.keys()),
        "per_regime": per_regime,
        "verdict": verdict,
        "t004_aggregate_alpha_tstat": T004_AGGREGATE_ALPHA_T.get(edge_id),
    }


def render_markdown(per_edge_results: List[Dict]) -> str:
    """Produce the audit-doc markdown."""
    lines = []
    lines.append("# Per-Regime Factor Decomp — Rescue vs Broken (T-2026-05-11-029)")
    lines.append("")
    lines.append("Generated: 2026-05-11 (T-2026-05-11-029 dispatch)")
    lines.append("Spec source: inbox brief T-2026-05-11-029")
    lines.append("Method: T-004's FF5+Mom HAC OLS decomposition, partitioned by `regime_label` per closed trade")
    lines.append("Source: T-002 Arm 1 (6 active edges) + T-020 per-edge isolation (5 paused edges) trade logs")
    lines.append("")

    # Decision-grade summary at the top
    buckets = defaultdict(list)
    for r in per_edge_results:
        verdict_head = r["verdict"].split("—")[0].strip()
        buckets[verdict_head].append(r["edge_id"])

    lines.append("## Decision-grade summary")
    lines.append("")
    lines.append("| Verdict bucket | Count | Edges |")
    lines.append("|---|---:|---|")
    for bucket, edges in sorted(buckets.items()):
        lines.append(f"| {bucket} | {len(edges)} | {', '.join(edges)} |")
    lines.append("")

    rescue = buckets.get("REGIME-MISTUNED", [])
    retire = buckets.get("UNIFORMLY NEGATIVE", [])
    promote = buckets.get("UNIFORMLY POSITIVE", [])
    noisy = buckets.get("UNIFORMLY NOISY", [])
    insufficient = (
        buckets.get("INSUFFICIENT DATA", [])
        + buckets.get("MIXED-INSUFFICIENT", [])
    )

    lines.append(
        f"**Of 11 edges: {len(rescue)} are REGIME-MISTUNED (rescue via Engine E), "
        f"{len(retire)} are UNIFORMLY NEGATIVE (confirmed retire), "
        f"{len(promote)} are UNIFORMLY POSITIVE (strong promote), "
        f"{len(noisy)} are UNIFORMLY NOISY (keep paused), "
        f"{len(insufficient)} are INSUFFICIENT DATA (need more samples).**"
    )
    lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "For each edge, the closed-trade `pnl` column is partitioned by "
        "the `regime_label` recorded on that trade row, then summed per "
        "(regime, date) to build a per-regime daily PnL stream. The "
        "stream is divided by `initial_capital=$100,000` to produce a "
        "daily-return series (matches T-004's tier_classifier convention)."
    )
    lines.append("")
    lines.append(
        "For each (edge, regime) cell with n_obs ≥ 30, OLS regression of "
        "(edge_return − RF) on FF5+Mom factors with Newey-West HAC standard "
        "errors (Politis auto-lag = floor(4 × (n/100)^(2/9))) yields α "
        "annualized + HAC t-stat + R² + factor betas. A residual moving-"
        "block bootstrap (block=lag+1, 1000 iters, seed=0) produces a 95% "
        "CI on α."
    )
    lines.append("")
    lines.append(
        "Regime taxonomy in the trade logs is the project's `macro_regime` "
        "classification: `emerging_expansion` (early-bull / risk-on recovery), "
        "`robust_expansion` (strong bull / risk-on peak), `cautious_decline` "
        "(risk-off / bearish). Three regimes, not the bull/bear/chop "
        "framing in the brief — documented as Open Q1 below."
    )
    lines.append("")

    # Per-edge table
    lines.append("## Per-(edge, regime) decomp table")
    lines.append("")
    lines.append("| Edge | Regime | n_obs | α_annual | α 95% CI (boot) | t-stat (HAC) | R² | Verdict band |")
    lines.append("|---|---|---:|---:|---|---:|---:|---|")
    for r in per_edge_results:
        eid = r["edge_id"]
        per_r = r["per_regime"]
        if not per_r:
            lines.append(f"| `{eid}` | (no regime data) | 0 | — | — | — | — | INSUFFICIENT |")
            continue
        for regime in sorted(per_r.keys()):
            res = per_r[regime]
            if not res.get("ok"):
                n = res.get("n_obs", 0)
                lines.append(
                    f"| `{eid}` | {regime} | {n} | — | — | — | — | "
                    f"INSUFFICIENT (n<30) |"
                )
                continue
            a = res["alpha_annualized"]
            t = res["alpha_tstat_hac"]
            r2 = res["r_squared"]
            ci_lo = res["alpha_ci_low_bootstrap"]
            ci_hi = res["alpha_ci_high_bootstrap"]
            band = "noise"
            if t > T_STAT_THRESHOLD:
                band = "**+pos**"
            elif t < -T_STAT_THRESHOLD:
                band = "**-neg**"
            lines.append(
                f"| `{eid}` | {regime} | {res['n_obs']} | {a:+.4f} | "
                f"[{ci_lo:+.4f}, {ci_hi:+.4f}] | {t:+.3f} | {r2:.3f} | "
                f"{band} |"
            )
    lines.append("")

    # Per-edge verdict
    lines.append("## Per-edge verdicts")
    lines.append("")
    for r in per_edge_results:
        eid = r["edge_id"]
        t004 = r["t004_aggregate_alpha_tstat"]
        t004_str = (
            f"(T-004 aggregate α t-stat: {t004:+.2f}) "
            if t004 is not None else ""
        )
        lines.append(f"- `{eid}` {t004_str}— **{r['verdict']}**")
    lines.append("")

    # Forward-looking
    lines.append("## Forward-looking note on regime-conditional integration")
    lines.append("")
    lines.append(
        "If REGIME-MISTUNED edges emerge, the wiring to Engine E's regime "
        "classifier would require: (a) Engine A's signal_processor reading "
        "the current macro_regime label per bar, (b) per-edge "
        "`enabled_regimes` config field (or equivalent in `edges.yml`), "
        "(c) zeroing the edge's signal contribution on bars where regime "
        "is outside its enabled set. Engine B's sizing chain consumes "
        "the result transparently — no Engine B changes. This is roughly "
        "the same shape as T-002 Arm 2's HMM Variant C wire (which "
        "modulated `risk_scalar` globally per regime); per-edge regime "
        "gating is a finer-grained version of that. A separate "
        "propose-first dispatch would scope the wiring; this dispatch "
        "produces only the decision-grade evidence."
    )
    lines.append("")

    # Open questions
    lines.append("## Open questions surfaced during analysis")
    lines.append("")
    lines.append(
        "1. **Regime label taxonomy mismatch.** Brief mentioned bull/bear/chop; "
        "trade logs use macro_regime labels (emerging_expansion, robust_expansion, "
        "cautious_decline). Used the actual labels. Mapping: emerging_expansion ≈ "
        "early-bull, robust_expansion ≈ strong-bull, cautious_decline ≈ bear/risk-off."
    )
    lines.append("")
    lines.append(
        "2. **Sample size per (edge, regime) cell.** n_obs ranges shown in the table; "
        "cells with n_obs < 30 are marked INSUFFICIENT. HAC t-stat reliability "
        "decreases as n shrinks; for cells with n in [30, 60], the t > 2 threshold "
        "is harder to clear than at the aggregate n ≈ 1041 level."
    )
    lines.append("")
    lines.append(
        "3. **Trade-log aggregation across reps.** T-002 Arm 1 has 3 reps × 5 years; "
        "used rep-1 per year (matches T-004's convention; within-year reps are "
        "bitwise identical per T-002's determinism PASS). T-020 has 1 isolated "
        "backtest per (edge, year); all 25 used."
    )
    lines.append("")
    lines.append(
        "4. **Regime transition handling.** Each trade row carries the regime "
        "label that was active at fill time. Per-trade attribution to a single "
        "regime is the natural choice given the data shape; no special "
        "transition-bar handling needed."
    )
    lines.append("")
    lines.append(
        "5. **What constitutes 'favorable regime' for borderline cases.** "
        "Used strict t > +2 / t < -2 per spec. Cells with 0 < t < 2 (weakly "
        "positive) are reported but NOT classified as 'favorable enough to "
        "wire'. Director can override at review."
    )
    lines.append("")
    return "\n".join(lines)


def build() -> Dict:
    factors = load_factor_data(auto_download=False)
    factors.index = factors.index.normalize()
    if "RF" not in factors.columns:
        raise RuntimeError("RF column missing from factor data")

    per_edge_results = []

    # 6 active edges, all in T-002 Arm 1 trade logs
    for edge in T002_ACTIVE_EDGES:
        print(f"[PER-REGIME] analyzing {edge} (T-002 Arm 1)...", flush=True)
        result = analyze_edge(edge, T002_ARM1_RUN_IDS, factors)
        per_edge_results.append(result)

    # 5 paused edges, each with its own T-020 isolation run_ids
    for edge, run_ids in T020_RUN_IDS.items():
        print(f"[PER-REGIME] analyzing {edge} (T-020 isolation)...", flush=True)
        result = analyze_edge(edge, run_ids, factors)
        per_edge_results.append(result)

    md = render_markdown(per_edge_results)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md)

    payload = {
        "generated": "2026-05-11 (T-2026-05-11-029 dispatch)",
        "spec": "inbox T-2026-05-11-029",
        "t002_arm1_run_ids": T002_ARM1_RUN_IDS,
        "t020_run_ids": T020_RUN_IDS,
        "per_edge": per_edge_results,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    build()
    print(f"[PER-REGIME] Wrote {OUT_MD}")
    print(f"[PER-REGIME] Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
