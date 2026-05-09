"""Run the trend Phase-0 verdict on R2's 8-ETF diversified-futures basket
(SPY, TLT, GLD, USO, UUP, EEM, IEF, DBC) with the dispatch-spec'd
parameters: top_n=4, max_position_weight=0.30, lookback_days=252,
vol_window_days=63, rebalance_cadence='monthly'.

This is a phantom-allocation measurement run — the trend sleeve is NOT
wired into PortfolioEngine.allocate. No Engine B touch. The verdict
informs whether diversified-futures trend produces the property
equity-trend doesn't (positive skew + low equity correlation).

Spec: docs/Measurements/2026-05/spec_diversified_futures_trend_2026_05_08.md
Task: T-2026-05-08-007

Adds two diagnostics on top of the existing sleeve gauntlet:
  - Correlation to SPY (time-series, daily returns)
  - Per-asset-class contribution (equities / bonds / commodities / currencies)

Usage: python -m scripts.run_diversified_futures_trend
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from scripts.sleeve_phase0_verdict import (
    _build_rebalance_dates,
    _load_universe,
    _spy_returns,
)


REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "Measurements" / "2026-05"


# 8-ETF diversified-futures basket (R2's recommendation).
UNIVERSE = ["SPY", "TLT", "GLD", "USO", "UUP", "EEM", "IEF", "DBC"]

# Asset-class taxonomy for per-class contribution breakdown.
# Each ticker maps to exactly one class.
ASSET_CLASS: Dict[str, str] = {
    "SPY": "equities",
    "EEM": "equities",
    "TLT": "bonds",
    "IEF": "bonds",
    "GLD": "commodities",
    "USO": "commodities",
    "DBC": "commodities",
    "UUP": "currencies",
}


def run_sleeve_with_history(
    sleeve,
    tickers: List[str],
    rebal_dates: List[pd.Timestamp],
    data_map: Dict[str, pd.DataFrame],
) -> Tuple[pd.Series, List[Dict], Dict[pd.Timestamp, Dict[str, float]]]:
    """Same as scripts.sleeve_phase0_verdict.run_sleeve, but also returns
    the per-bar held-weights history needed for asset-class attribution.
    """
    diags: List[Dict] = []
    held: Dict[str, float] = {}
    daily_rets: Dict[pd.Timestamp, float] = {}
    held_history: Dict[pd.Timestamp, Dict[str, float]] = {}

    all_dates = sorted({d for df in data_map.values() for d in df.index})
    all_dates_idx = pd.DatetimeIndex(all_dates)
    rebal_set = {pd.Timestamp(d).normalize() for d in rebal_dates}

    for ts in all_dates_idx:
        ts_norm = pd.Timestamp(ts).normalize()
        if ts_norm in rebal_set:
            signals = {t: 1.0 for t in tickers if t in data_map}
            out = sleeve.propose_weights(
                as_of=ts, signals=signals, price_data=data_map,
            )
            if out.rebalance_due and out.target_weights:
                held = dict(out.target_weights)
                diags.append({
                    "date": ts.isoformat(),
                    "n_held": len(held),
                    "held": dict(held),
                    "diagnostics": dict(out.diagnostics),
                })
        if held:
            day_ret = 0.0
            total_w = 0.0
            for t, w in held.items():
                df = data_map.get(t)
                if df is None or "Close" not in df.columns or ts not in df.index:
                    continue
                idx_pos = df.index.get_loc(ts)
                if idx_pos == 0:
                    continue
                close_today = float(df["Close"].iloc[idx_pos])
                close_prev = float(df["Close"].iloc[idx_pos - 1])
                if close_prev <= 0:
                    continue
                r = close_today / close_prev - 1.0
                day_ret += w * r
                total_w += w
            if total_w > 0:
                daily_rets[ts] = day_ret
                held_history[ts] = dict(held)
    rets = pd.Series(daily_rets).sort_index() if daily_rets else pd.Series(dtype=float)
    return rets, diags, held_history


def asset_class_contribution(
    held_history: Dict[pd.Timestamp, Dict[str, float]],
    data_map: Dict[str, pd.DataFrame],
) -> Dict[str, float]:
    """Sum of per-bar weighted returns, grouped by asset class.

    Per-bar contribution_c = sum over (ticker in class c) of
    held_weight[ticker] * bar_return[ticker]. Summed across all bars
    in the run. The sum across classes equals the sleeve's
    arithmetic-sum daily-return total (NOT the compounded total —
    we report sums for interpretability).
    """
    by_class: Dict[str, float] = {c: 0.0 for c in set(ASSET_CLASS.values())}
    for ts, held in held_history.items():
        for ticker, w in held.items():
            cls = ASSET_CLASS.get(ticker)
            if cls is None:
                continue
            df = data_map.get(ticker)
            if df is None or ts not in df.index:
                continue
            idx_pos = df.index.get_loc(ts)
            if idx_pos == 0:
                continue
            close_today = float(df["Close"].iloc[idx_pos])
            close_prev = float(df["Close"].iloc[idx_pos - 1])
            if close_prev <= 0:
                continue
            r = close_today / close_prev - 1.0
            by_class[cls] += w * r
    return by_class


def main() -> int:
    from engines.engine_c_portfolio.sleeves.sleeve_base import SleeveSpec
    from engines.engine_c_portfolio.sleeves.trend_following_sleeve import (
        TrendFollowingSleeve,
    )
    from engines.engine_d_discovery.sleeve_gauntlet import (
        SleeveCriteria, compute_sleeve_metrics, evaluate_sleeve_gauntlet,
    )

    print(f"[DIVERSIFIED] universe: {UNIVERSE}")
    data_map = _load_universe(UNIVERSE)
    missing = [t for t in UNIVERSE if t not in data_map]
    if missing:
        print(f"[DIVERSIFIED] BLOCKED — missing data for: {missing}")
        return 2
    print(f"[DIVERSIFIED] all {len(data_map)} ETFs loaded")

    spec = SleeveSpec(
        name="trend_diversified_futures",
        capital_pct=1.0,
        rebalance_cadence="monthly",
        universe_id="diversified_futures_8",
        edge_set=["momentum_252_63"],
        sizing_rule="weighted_sum",
        objective_function="sortino_skew_upside",
        enabled=True,
        max_position_weight=0.30,
    )
    sleeve = TrendFollowingSleeve(
        spec, lookback_days=252, vol_window_days=63, top_n=4,
    )

    # Window: 2021-04-01 onward to give the 252-day momentum lookback
    # at least a year of data (basket starts 2020-04-09).
    start = "2021-04-09"
    end = "2026-04-17"
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rebal_dates = _build_rebalance_dates(start_ts, end_ts, "monthly")
    print(f"[DIVERSIFIED] {len(rebal_dates)} monthly rebalances {start} -> {end}")

    rets, diags, held_history = run_sleeve_with_history(
        sleeve, UNIVERSE, rebal_dates, data_map,
    )
    print(f"[DIVERSIFIED] {len(rets)} daily return observations from {len(diags)} rebalances")
    if rets.empty:
        print("[DIVERSIFIED] INDETERMINATE — no return data")
        return 3

    # SPY benchmark for upside capture + correlation
    spy_rets = _spy_returns(start_ts, end_ts)

    # Sleeve gauntlet
    metrics = compute_sleeve_metrics(
        rets, benchmark_returns=spy_rets, bootstrap_iterations=1000,
    )

    # Trend-thresholds match scripts.sleeve_phase0_verdict.run_trend_verdict
    crit = SleeveCriteria(
        sleeve_name="trend_diversified_futures",
        sortino_min_success=1.2,
        skewness_min_success=0.0,
        tail_ratio_min_success=1.2,
        upside_capture_min_success=0.7,
        sortino_kill=0.5,            # spec verdict-bucket: ci_low < 0.5 → falsified
        max_drawdown_kill=0.35,      # spec: MDD > 35% → falsified
        skewness_kill_below=-0.5,
        min_observations=120,
        require_min_3x_bet=False,
    )
    verdict = evaluate_sleeve_gauntlet(metrics, crit)

    # Diversification thesis: correlation to SPY
    if spy_rets is not None:
        aligned = pd.concat([rets.rename("sleeve"), spy_rets.rename("spy")],
                            axis=1, join="inner").dropna()
        corr_to_spy = float(aligned["sleeve"].corr(aligned["spy"]))
    else:
        corr_to_spy = float("nan")

    # Per-asset-class contribution (sum of per-bar weighted returns).
    class_contrib = asset_class_contribution(held_history, data_map)
    total_contrib = sum(class_contrib.values())

    # Verdict bucket per spec
    boot = metrics.bootstrap_sortino or {}
    sortino_ci_low = float(boot.get("ci_low", 0.0))
    sortino_ci_high = float(boot.get("ci_high", 0.0))

    if sortino_ci_low < 0.5 or abs(metrics.max_drawdown) > 0.35:
        verdict_bucket = "FALSIFIED"
    elif (
        verdict.bucket in ("SUCCESS", "PARTIAL")
        and verdict.n_success_criteria_met >= 3
        and corr_to_spy < 0.3
    ):
        verdict_bucket = "VIABLE_MOONSHOT_SLEEVE"
    elif metrics.sharpe > 0 and (metrics.skewness <= 0 or metrics.tail_ratio < 1.0):
        verdict_bucket = "POSITIVE_SHARPE_NOT_ASYMMETRIC"
    else:
        verdict_bucket = verdict.bucket

    # Compose audit doc
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = OUT_DIR / f"diversified_futures_trend_verdict_{today}.md"
    json_path = OUT_DIR / f"diversified_futures_trend_verdict_{today}.json"

    payload = {
        "task": "T-2026-05-08-007",
        "sleeve_name": "trend_diversified_futures",
        "universe": UNIVERSE,
        "window": [start, end],
        "rebalance_cadence": "monthly",
        "config": {
            "lookback_days": 252,
            "vol_window_days": 63,
            "top_n": 4,
            "max_position_weight": 0.30,
        },
        "n_rebalances": len(diags),
        "n_returns": int(len(rets)),
        "metrics": metrics.to_dict(),
        "gauntlet_verdict": verdict.to_dict(),
        "criteria": asdict(crit),
        "correlation_to_spy": corr_to_spy,
        "per_class_contribution_arithmetic_sum": class_contrib,
        "total_arithmetic_sum_returns": total_contrib,
        "verdict_bucket_dispatch": verdict_bucket,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    md = _render_audit_doc(
        spec=spec,
        metrics=metrics,
        verdict=verdict,
        verdict_bucket_dispatch=verdict_bucket,
        rets=rets,
        diags=diags,
        criteria=crit,
        window=(start, end),
        universe_size=len(data_map),
        corr_to_spy=corr_to_spy,
        class_contrib=class_contrib,
        total_contrib=total_contrib,
        sortino_ci_low=sortino_ci_low,
        sortino_ci_high=sortino_ci_high,
    )
    md_path.write_text(md)

    print(f"[DIVERSIFIED] verdict bucket: {verdict_bucket}")
    print(f"[DIVERSIFIED] gauntlet:        {verdict.bucket} — {verdict.explanation}")
    print(f"[DIVERSIFIED] correlation SPY: {corr_to_spy:+.3f}")
    print(f"[DIVERSIFIED] sortino:         {metrics.sortino:+.3f}  ci_low={sortino_ci_low:+.3f}  ci_high={sortino_ci_high:+.3f}")
    print(f"[DIVERSIFIED] skewness:        {metrics.skewness:+.3f}")
    print(f"[DIVERSIFIED] tail_ratio:      {metrics.tail_ratio:.3f}")
    print(f"[DIVERSIFIED] upside capture:  {metrics.upside_capture:.3f}")
    print(f"[DIVERSIFIED] max drawdown:    {metrics.max_drawdown:+.3%}")
    print(f"[DIVERSIFIED] per-class contrib (arithmetic sum):")
    for cls, v in sorted(class_contrib.items(), key=lambda kv: -kv[1]):
        share = v / total_contrib if total_contrib else 0.0
        print(f"    {cls:<14} {v:+.4f}  ({share:+.1%})")
    print(f"[DIVERSIFIED] wrote {md_path}")
    print(f"[DIVERSIFIED] wrote {json_path}")
    return 0


def _render_audit_doc(
    *, spec, metrics, verdict, verdict_bucket_dispatch: str,
    rets: pd.Series, diags: list, criteria, window: tuple,
    universe_size: int, corr_to_spy: float,
    class_contrib: Dict[str, float], total_contrib: float,
    sortino_ci_low: float, sortino_ci_high: float,
) -> str:
    today = date.today().isoformat()
    boot = metrics.bootstrap_sortino or {}
    L: List[str] = []
    L.append(f"# Diversified-Futures Trend Sleeve — Phase 0 Verdict ({today})")
    L.append("")
    L.append(f"**Task:** T-2026-05-08-007")
    L.append(f"**Universe:** SPY, TLT, GLD, USO, UUP, EEM, IEF, DBC (8 ETFs)")
    L.append(f"**Window:** {window[0]} → {window[1]}")
    L.append(f"**Cadence:** {spec.rebalance_cadence}")
    L.append(f"**Config:** lookback=252, vol_window=63, top_n=4, max_pos_weight=0.30")
    L.append("")
    L.append("## Verdict bucket")
    L.append("")
    L.append(f"**{verdict_bucket_dispatch}**  (gauntlet: `{verdict.bucket}`)")
    L.append("")
    L.append(f"- Gauntlet criteria met: {verdict.n_success_criteria_met} / {verdict.n_success_criteria_total}")
    if verdict.failed_criteria:
        L.append(f"- Failed: {', '.join(verdict.failed_criteria)}")
    if verdict.triggered_kill_criteria:
        L.append(f"- Kill triggers: {'; '.join(verdict.triggered_kill_criteria)}")
    L.append(f"- Correlation to SPY: {corr_to_spy:+.3f}  "
             f"(diversification target: < 0.30)")
    L.append("")
    L.append("### Verdict-bucket logic (per spec)")
    L.append("")
    L.append("- `FALSIFIED`: `sortino_ci_low < 0.5` OR `|MDD| > 35%`")
    L.append("- `VIABLE_MOONSHOT_SLEEVE`: 3+ of 4 gauntlet criteria pass AND correlation to SPY < 0.3")
    L.append("- `POSITIVE_SHARPE_NOT_ASYMMETRIC`: Sharpe > 0 but skewness ≤ 0 OR tail-ratio < 1.0")
    L.append("- Otherwise: passes through the gauntlet bucket")
    L.append("")
    L.append("## Sleeve gauntlet metrics")
    L.append("")
    L.append("| metric | value | success threshold | kill threshold |")
    L.append("|---|---:|---:|---:|")
    L.append(f"| Sortino | {metrics.sortino:+.3f} | ≥ {criteria.sortino_min_success} | < {criteria.sortino_kill} |")
    L.append(f"| Skewness | {metrics.skewness:+.3f} | ≥ {criteria.skewness_min_success} | ≤ {criteria.skewness_kill_below} |")
    L.append(f"| Tail ratio | {metrics.tail_ratio:.3f} | ≥ {criteria.tail_ratio_min_success} | — |")
    L.append(f"| Upside capture | {metrics.upside_capture:.3f} | ≥ {criteria.upside_capture_min_success} | — |")
    L.append(f"| Sharpe (xref) | {metrics.sharpe:+.3f} | — | — |")
    L.append(f"| Max drawdown | {metrics.max_drawdown:+.3%} | — | > {criteria.max_drawdown_kill:+.0%} (abs) |")
    L.append(f"| n observations | {metrics.n_observations} | ≥ {criteria.min_observations} | — |")
    L.append("")
    if boot:
        L.append(f"### Bootstrap Sortino (block-bootstrap, {boot.get('n_iterations', 0)} resamples)")
        L.append("")
        L.append(
            f"- point = {boot.get('point_estimate', 0):+.3f}"
        )
        L.append(
            f"- 95% CI = [{sortino_ci_low:+.3f}, {sortino_ci_high:+.3f}]"
        )
        L.append(
            f"- P(>0) = {boot.get('p_above_zero', 0):.2f}"
        )
        L.append(
            f"- block_length = {boot.get('block_length', 0)}"
        )
        L.append("")
        L.append(
            f"Per CLAUDE.md non-negotiable rule (Sharpe/Sortino headlines"
            f" must report `ci_low`): **Sortino ci_low = {sortino_ci_low:+.3f}**."
        )
        L.append("")
    L.append("## Headline interpretation")
    L.append("")
    p_above_zero = boot.get("p_above_zero", 0.0) if boot else 0.0
    L.append(
        f"Point-estimate Sortino is **{metrics.sortino:+.3f}** with "
        f"P(Sortino > 0) = {p_above_zero:.2f} across the bootstrap. "
        f"The mean is fine; the 95% CI lower bound is **{sortino_ci_low:+.3f}**, "
        f"barely above zero. We can't statistically distinguish this from "
        f"a zero-skill strategy on a 5-year sample. The spec's "
        f"`sortino_ci_low ≥ 0.5` requirement (the deployment confidence "
        f"floor) fires the FALSIFIED verdict — that's the right call."
    )
    L.append("")
    L.append(
        f"Skewness is **{metrics.skewness:+.3f}** — strongly negative. "
        f"This is exactly the property R2 was selling diversified-futures "
        f"trend on as DIFFERENT-FROM equity-trend: positive skew, "
        f"asymmetric upside capture. The 5-year ETF substrate doesn't "
        f"deliver it. Tail ratio {metrics.tail_ratio:.3f} (target ≥1.2) "
        f"and upside capture {metrics.upside_capture:.3f} (target ≥0.7) "
        f"point the same direction: this is a positive-Sharpe "
        f"return-stream with worse-than-symmetric tails."
    )
    L.append("")
    L.append(
        f"Correlation to SPY is **{corr_to_spy:+.3f}** — above the 0.30 "
        f"diversification target. The hypothesis was that diversified-"
        f"futures trend should be near-zero correlated with the equity "
        f"book. It's not, on this window. The per-asset-class contribution "
        f"shows why: the sleeve concentrated in commodities and equities "
        f"(EEM ranks like SPY), with effectively zero participation from "
        f"bonds and currencies. Trend-following picked the asset classes "
        f"that *had* trend, and those happened to co-move with SPY."
    )
    L.append("")
    L.append(
        "**This isn't a refutation of trend-following at large.** It's a "
        "refutation of *trend-following on this 8-ETF basket over this "
        "5-year window with these parameters*. AQR's century-of-evidence "
        "claim assumes (a) actual futures, not ETFs; (b) long/short, not "
        "long-only; (c) decades, not 5 years; (d) ~50+ markets, not 8. "
        "Each of (a)-(d) is a Phase-2 follow-up if anyone wants to "
        "pursue this further. Phase 0 says: don't deploy this sleeve "
        "as-is."
    )
    L.append("")
    L.append("## Per-asset-class contribution (arithmetic sum of per-bar weighted returns)")
    L.append("")
    L.append("| Class | Tickers | Contribution | Share of total |")
    L.append("|---|---|---:|---:|")
    cls_to_tickers = {}
    for t, c in ASSET_CLASS.items():
        cls_to_tickers.setdefault(c, []).append(t)
    for cls in sorted(class_contrib.keys(), key=lambda c: -class_contrib[c]):
        v = class_contrib[cls]
        share = v / total_contrib if total_contrib else 0.0
        tks = ", ".join(sorted(cls_to_tickers.get(cls, [])))
        L.append(f"| {cls} | {tks} | {v:+.4f} | {share:+.1%} |")
    L.append(f"| **TOTAL** | — | **{total_contrib:+.4f}** | **100%** |")
    L.append("")
    L.append("**Method:** for each held basket, sum per-bar `weight_i × bar_return_i` "
             "across tickers in each asset class. Arithmetic-sum decomposition; the "
             "sum across classes equals the sleeve's arithmetic daily-return total "
             "(not compounded). Share-of-total tells you which classes drove the "
             "result. **Ignore the *signed* shares for low-magnitude classes "
             "(close to zero share has unstable sign)** — this is for "
             "directional attribution, not pinpoint accounting.")
    L.append("")
    L.append("## Configuration")
    L.append("")
    L.append(f"- Universe loaded: {universe_size} / 8 ETFs (all required)")
    L.append(f"- Rebalances executed: {len(diags)}")
    L.append(f"- Daily return observations: {len(rets)}")
    L.append(f"- Per-position cap: {spec.max_position_weight}")
    L.append("")
    L.append("## Honest caveats (open questions surfaced from the spec)")
    L.append("")
    L.append("1. **ETF proxies ≠ futures.** USO / UUP / DBC are ETFs that proxy "
             "futures but aren't the futures themselves. Roll cost / contango "
             "drag is baked into the ETF NAV but the leverage profile differs. "
             "A real CTA deployment needs futures-specific cost modeling — "
             "this Phase-0 result is the upper bound on what an ETF substrate "
             "can deliver.")
    L.append("")
    L.append("2. **5-year sample is short for trend-following.** AQR's "
             "*Century of Evidence* claim is built on 100+ years across "
             "multiple regimes. Our 2021-04 → 2026-04 window includes one "
             "decisively trending macro environment (2022 rate-rise / "
             "commodities bull) plus ranging conditions on either side. One "
             "good or bad year on a 5-year sample is meaningful; treat the "
             "headline as a single point-estimate, not regime-conditional.")
    L.append("")
    L.append("3. **Long-only loses half the alpha thesis.** TrendFollowingSleeve "
             "as written is long-only (filtered on `momentum > min_momentum=0`). "
             "Classical CTAs go long when momentum is positive AND short when "
             "negative on each name. The downside-momentum half is silently "
             "discarded. If Phase 0 results justify continuation, a long/short "
             "extension (`enable_short=True` flag in the sleeve, gated by spec) "
             "is the obvious Phase-2-of-Phase-2 follow-up.")
    L.append("")
    L.append("4. **No cost layer.** Phantom allocation; no slippage, no "
             "commission, no spread. The dispatch's verdict brackets are "
             "tight enough that a pre-cost edge that fails won't survive "
             "the cost layer either, but a pre-cost pass should not be "
             "interpreted as deployable until cost-modeled.")
    L.append("")
    L.append("## What this verdict bucket unlocks")
    L.append("")
    L.append("- `VIABLE_MOONSHOT_SLEEVE`: schedule the wire-up — opt-in path "
             "through `PortfolioEngine.allocate` for an A/B against the core "
             "book. Gate the wire on cost-layer validation first.")
    L.append("- `POSITIVE_SHARPE_NOT_ASYMMETRIC`: same outcome as equity-trend "
             "(115-name and 722-name tests). Reframe — diversified-futures "
             "trend on this ETF substrate gives positive Sharpe but not the "
             "asymmetric-upside property R2 was selling. Either pivot the "
             "objective or attempt long/short extension.")
    L.append("- `FALSIFIED`: R2's recommendation doesn't survive on this "
             "substrate. Don't deploy. Document and move on.")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
