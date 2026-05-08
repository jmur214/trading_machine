"""Sleeve Phase-0 verdict harness — drives a Sleeve through a measurement-
only backtest against real OHLCV, then runs the sleeve gauntlet to
produce a SUCCESS / PARTIAL / FAIL / INDETERMINATE verdict.

Usage:
    python -m scripts.sleeve_phase0_verdict --sleeve trend
    python -m scripts.sleeve_phase0_verdict --sleeve moonshot

Phase 0 = phantom allocation. The sleeve runs in measurement mode against
real price data; the verdict feeds the gauntlet, but no capital is
deployed. This is the dispatch-spec'd path before the sleeve is wired
into PortfolioEngine.allocate.

What this is NOT:
- Not a full multi-engine backtest with cost layer. The harness uses
  next-period close-to-close returns weighted by sleeve target weights.
  No slippage, no commission, no advisory caps. The dispatch's verdict
  brackets are deliberately tight enough that any pre-cost edge that
  passes is unlikely to fail at the cost layer; an edge that fails
  pre-cost is dead at any layer.
- Not a multi-cycle / Engine-D / lifecycle integration. The sleeve is
  evaluated as a standalone strategy stream.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DATA_PROCESSED = REPO / "data" / "processed"
DOCS_OUT = REPO / "docs" / "Measurements" / "2026-05"


# ---------------------------------------------------------------------- #
# Data plumbing — local CSV reader (no network, deterministic)

def _load_close(ticker: str) -> Optional[pd.Series]:
    p = DATA_PROCESSED / f"{ticker}_1d.csv"
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["Date"]).set_index("Date")
    except Exception:
        return None
    if "Close" not in df.columns:
        return None
    return df["Close"].astype(float).sort_index()


def _load_universe(tickers: List[str]) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        p = DATA_PROCESSED / f"{t}_1d.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, parse_dates=["Date"]).set_index("Date").sort_index()
        except Exception:
            continue
        if df.empty or "Close" not in df.columns:
            continue
        out[t] = df
    return out


# ---------------------------------------------------------------------- #
# Sleeve harness

def run_sleeve(
    sleeve,
    tickers: List[str],
    rebal_dates: List[pd.Timestamp],
    data_map: Dict[str, pd.DataFrame],
) -> Tuple[pd.Series, List[Dict]]:
    """Run the sleeve through a sequence of rebalance dates. Returns
    (daily_returns Series, list of per-rebalance diagnostics)."""
    diags: List[Dict] = []
    held: Dict[str, float] = {}
    last_rebal: Optional[pd.Timestamp] = None
    daily_rets: Dict[pd.Timestamp, float] = {}

    # Build a sorted list of all trading days from the data
    all_dates = sorted({d for df in data_map.values() for d in df.index})
    all_dates_idx = pd.DatetimeIndex(all_dates)
    rebal_set = set(pd.Timestamp(d).normalize() for d in rebal_dates)

    for ts in all_dates_idx:
        ts_norm = pd.Timestamp(ts).normalize()
        if ts_norm in rebal_set:
            # Build inputs at this date
            signals = {t: 1.0 for t in tickers if t in data_map}
            out = sleeve.propose_weights(
                as_of=ts, signals=signals, price_data=data_map,
            )
            if out.rebalance_due and out.target_weights:
                held = dict(out.target_weights)
                last_rebal = ts
                diags.append({
                    "date": ts.isoformat(),
                    "n_held": len(held),
                    "diagnostics": dict(out.diagnostics),
                })

        # Compute return for this bar from held positions
        # Return = sum(weight_i * close_today/close_prev - weight_i)
        if held:
            day_ret = 0.0
            total_weight = 0.0
            for t, w in held.items():
                df = data_map.get(t)
                if df is None or "Close" not in df.columns:
                    continue
                # find this day's close and previous trading day's close
                if ts not in df.index:
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
                total_weight += w
            if total_weight > 0:
                daily_rets[ts] = day_ret

    if not daily_rets:
        return pd.Series(dtype=float), diags
    rets = pd.Series(daily_rets).sort_index()
    return rets, diags


def _build_rebalance_dates(start: pd.Timestamp, end: pd.Timestamp,
                           cadence: str) -> List[pd.Timestamp]:
    if cadence == "monthly":
        d = start
        out = []
        while d <= end:
            out.append(d)
            d = (d + pd.DateOffset(months=1)).normalize()
        return out
    if cadence == "quarterly":
        d = start
        out = []
        while d <= end:
            out.append(d)
            d = (d + pd.DateOffset(months=3)).normalize()
        return out
    if cadence == "weekly":
        return list(pd.date_range(start, end, freq="W-MON"))
    raise ValueError(f"unknown cadence {cadence!r}")


# ---------------------------------------------------------------------- #
# SPY benchmark loading

def _spy_returns(start: pd.Timestamp, end: pd.Timestamp) -> Optional[pd.Series]:
    s = _load_close("SPY")
    if s is None:
        return None
    s = s[(s.index >= start) & (s.index <= end)]
    return s.pct_change().dropna()


# ---------------------------------------------------------------------- #
# Per-sleeve verdict drivers

def run_trend_verdict(
    out_dir: Path,
    universe_tickers: List[str],
    start: str = "2021-01-01",
    end: str = "2025-12-31",
) -> dict:
    from engines.engine_c_portfolio.sleeves.sleeve_base import SleeveSpec
    from engines.engine_c_portfolio.sleeves.trend_following_sleeve import (
        TrendFollowingSleeve,
    )
    from engines.engine_d_discovery.sleeve_gauntlet import (
        SleeveCriteria, compute_sleeve_metrics, evaluate_sleeve_gauntlet,
    )

    print(f"[TREND] loading {len(universe_tickers)} tickers from {DATA_PROCESSED}")
    data_map = _load_universe(universe_tickers)
    print(f"[TREND] {len(data_map)} have OHLCV data on disk")

    spec = SleeveSpec(
        name="trend",
        capital_pct=1.0,            # phantom: full sleeve allocation
        rebalance_cadence="monthly",
        universe_id="universe_115",
        edge_set=["momentum_252_63"],
        sizing_rule="weighted_sum",
        objective_function="sortino_skew_upside",
        enabled=True,
        max_position_weight=0.20,
    )
    sleeve = TrendFollowingSleeve(
        spec, lookback_days=252, vol_window_days=63, top_n=10,
    )

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rebal_dates = _build_rebalance_dates(start_ts, end_ts, "monthly")
    print(f"[TREND] {len(rebal_dates)} rebalance dates from {start} to {end}")

    rets, diags = run_sleeve(sleeve, universe_tickers, rebal_dates, data_map)
    print(f"[TREND] generated {len(rets)} daily return observations")
    if rets.empty:
        verdict = {"bucket": "INDETERMINATE", "reason": "no return data generated"}
        return verdict

    spy_rets = _spy_returns(start_ts, end_ts)

    metrics = compute_sleeve_metrics(
        rets, benchmark_returns=spy_rets, bootstrap_iterations=300,
    )
    # Trend-following uses TIGHTER thresholds than moonshot — proven
    # strategy class so the bar is higher.
    crit = SleeveCriteria(
        sleeve_name="trend",
        sortino_min_success=1.2,
        skewness_min_success=0.0,           # trend doesn't need positive skew
        tail_ratio_min_success=1.2,
        upside_capture_min_success=0.7,
        sortino_kill=0.3,
        max_drawdown_kill=0.25,             # tighter MDD kill (25% not 35%)
        skewness_kill_below=-0.5,           # only kill on strong negative skew
        min_observations=120,
        require_min_3x_bet=False,
    )
    verdict = evaluate_sleeve_gauntlet(metrics, crit)

    # ---- write audit doc + JSON ----
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = out_dir / f"trend_phase0_verdict_{today}.md"
    json_path = out_dir / f"trend_phase0_verdict_{today}.json"

    md = _render_audit_doc(
        sleeve_name="Trend-Following",
        spec=spec,
        metrics=metrics,
        verdict=verdict,
        rets=rets,
        diags=diags,
        criteria=crit,
        window=(start, end),
        universe_size=len(data_map),
        is_synthetic=False,
        synthetic_note=None,
    )
    md_path.write_text(md)

    payload = {
        "sleeve_name": "trend-following",
        "window": [start, end],
        "rebalance_cadence": "monthly",
        "universe_size": len(data_map),
        "n_rebalances": len(diags),
        "n_returns": int(len(rets)),
        "metrics": metrics.to_dict(),
        "verdict": verdict.to_dict(),
        "criteria": asdict(crit),
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[TREND] verdict: {verdict.bucket} — {verdict.explanation}")
    print(f"[TREND] wrote {md_path}")
    print(f"[TREND] wrote {json_path}")
    return payload


def run_moonshot_verdict(
    out_dir: Path,
    universe_tickers: List[str],
    start: str = "2021-01-01",
    end: str = "2025-12-31",
) -> dict:
    from engines.engine_c_portfolio.sleeves.sleeve_base import SleeveSpec
    from engines.engine_c_portfolio.sleeves.moonshot_sleeve import MoonshotSleeve
    from engines.engine_a_alpha.edges.leaps_catalyst_edge import LeapsCatalystEdge
    from engines.engine_d_discovery.sleeve_gauntlet import (
        SleeveCriteria, compute_sleeve_metrics, evaluate_sleeve_gauntlet,
    )

    print(f"[MOONSHOT] loading {len(universe_tickers)} tickers")
    data_map = _load_universe(universe_tickers)
    print(f"[MOONSHOT] {len(data_map)} have data")

    edge = LeapsCatalystEdge()
    spec = SleeveSpec(
        name="moonshot",
        capital_pct=1.0,
        rebalance_cadence="monthly",
        universe_id="universe_115",
        edge_set=["leaps_catalyst_v1"],
        sizing_rule="weighted_sum",
        objective_function="sortino_skew_upside",
        enabled=True,
        max_position_weight=0.05,
    )
    sleeve = MoonshotSleeve(
        spec, max_concurrent_positions=30, min_concurrent_positions=10,
    )

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rebal_dates = _build_rebalance_dates(start_ts, end_ts, "monthly")
    print(f"[MOONSHOT] {len(rebal_dates)} rebalance dates")

    # Drive moonshot via real LEAPS edge signals (Phase 0 stand-in)
    diags: List[Dict] = []
    held: Dict[str, float] = {}
    daily_rets: Dict[pd.Timestamp, float] = {}
    all_dates = sorted({d for df in data_map.values() for d in df.index})
    rebal_set = set(pd.Timestamp(d).normalize() for d in rebal_dates)

    for ts in pd.DatetimeIndex(all_dates):
        ts_norm = pd.Timestamp(ts).normalize()
        if ts_norm in rebal_set:
            signals = edge.compute_signals(data_map, ts)
            out = sleeve.propose_weights(
                as_of=ts, signals=signals, price_data=data_map,
            )
            if out.rebalance_due and out.target_weights:
                held = dict(out.target_weights)
                diags.append({
                    "date": ts.isoformat(),
                    "n_held": len(held),
                    "diagnostics": dict(out.diagnostics),
                })

        if held:
            day_ret = 0.0
            total_w = 0.0
            for t, w in held.items():
                df = data_map.get(t)
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
                day_ret += w * r
                total_w += w
            if total_w > 0:
                daily_rets[ts] = day_ret

    if not daily_rets:
        verdict = {"bucket": "INDETERMINATE", "reason": "no return data"}
        return verdict
    rets = pd.Series(daily_rets).sort_index()
    spy_rets = _spy_returns(start_ts, end_ts)

    metrics = compute_sleeve_metrics(
        rets, benchmark_returns=spy_rets, bootstrap_iterations=300,
    )
    crit = SleeveCriteria(
        sleeve_name="moonshot",
        sortino_min_success=1.5,
        skewness_min_success=0.5,
        tail_ratio_min_success=1.5,
        upside_capture_min_success=0.7,
        sortino_kill=0.3,
        max_drawdown_kill=0.35,
        skewness_kill_below=0.0,
        hit_rate_kill_below=0.25,
        avg_winner_kill_below=2.0,
        min_observations=120,
        require_min_3x_bet=False,           # trade returns not measured here
    )
    verdict = evaluate_sleeve_gauntlet(metrics, crit)

    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = out_dir / f"moonshot_phase0_verdict_{today}.md"
    json_path = out_dir / f"moonshot_phase0_verdict_{today}.json"

    md = _render_audit_doc(
        sleeve_name="Moonshot",
        spec=spec,
        metrics=metrics,
        verdict=verdict,
        rets=rets,
        diags=diags,
        criteria=crit,
        window=(start, end),
        universe_size=len(data_map),
        is_synthetic=True,
        synthetic_note=(
            "PHASE 0 SYNTHETIC OPTIONS STAND-IN. The leaps_catalyst_edge_v1 "
            "uses Black-Scholes pricing on the underlying close + IV proxy "
            "from realized vol. This is good enough to validate sleeve "
            "plumbing but is NOT a substitute for real OPRA options PnL. "
            "Real OPRA via Schwab is Phase 1 work. Treat the verdict bucket "
            "as a SLEEVE-PLUMBING signal, not a real strategy verdict."
        ),
    )
    md_path.write_text(md)

    payload = {
        "sleeve_name": "moonshot",
        "window": [start, end],
        "rebalance_cadence": "monthly",
        "universe_size": len(data_map),
        "n_rebalances": len(diags),
        "n_returns": int(len(rets)),
        "metrics": metrics.to_dict(),
        "verdict": verdict.to_dict(),
        "criteria": asdict(crit),
        "phase_0_caveat": "synthetic Black-Scholes; not real OPRA",
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[MOONSHOT] verdict: {verdict.bucket} — {verdict.explanation}")
    return payload


# ---------------------------------------------------------------------- #
# Audit-doc renderer

def _render_audit_doc(
    *, sleeve_name: str, spec, metrics, verdict, rets: pd.Series,
    diags: list, criteria, window, universe_size: int,
    is_synthetic: bool, synthetic_note: Optional[str],
) -> str:
    lines: list = []
    today = date.today().isoformat()
    lines.append(f"# {sleeve_name} Sleeve Phase 0 Verdict — {today}")
    lines.append("")
    if is_synthetic and synthetic_note:
        lines.append("## ⚠️ Phase 0 caveat")
        lines.append("")
        lines.append(f"_{synthetic_note}_")
        lines.append("")
    lines.append("## Verdict bucket")
    lines.append("")
    lines.append(f"**{verdict.bucket}** — {verdict.explanation}")
    lines.append("")
    lines.append(f"- Success criteria met: {verdict.n_success_criteria_met} / {verdict.n_success_criteria_total}")
    if verdict.failed_criteria:
        lines.append(f"- Failed: {', '.join(verdict.failed_criteria)}")
    if verdict.triggered_kill_criteria:
        lines.append(f"- Kill triggers: {'; '.join(verdict.triggered_kill_criteria)}")
    lines.append("")
    lines.append("## Sleeve metrics")
    lines.append("")
    lines.append(f"| metric | value | success threshold | kill threshold |")
    lines.append(f"|---|---:|---:|---:|")
    lines.append(f"| Sortino | {metrics.sortino:+.3f} | ≥ {criteria.sortino_min_success} | < {criteria.sortino_kill} |")
    lines.append(f"| Skewness | {metrics.skewness:+.3f} | ≥ {criteria.skewness_min_success} | ≤ {criteria.skewness_kill_below} |")
    lines.append(f"| Tail ratio | {metrics.tail_ratio:.3f} | ≥ {criteria.tail_ratio_min_success} | — |")
    lines.append(f"| Upside capture | {metrics.upside_capture:.3f} | ≥ {criteria.upside_capture_min_success} | — |")
    lines.append(f"| Sharpe (xref) | {metrics.sharpe:+.3f} | — | — |")
    lines.append(f"| Max drawdown | {metrics.max_drawdown:+.3%} | — | > {criteria.max_drawdown_kill:+.0%} (abs) |")
    lines.append(f"| n observations | {metrics.n_observations} | ≥ {criteria.min_observations} | — |")
    lines.append("")
    if metrics.bootstrap_sortino:
        b = metrics.bootstrap_sortino
        lines.append(f"### Bootstrap Sortino (block-bootstrap, {b.get('n_iterations', 0)} resamples)")
        lines.append("")
        lines.append(
            f"point={b.get('point_estimate', 0):+.3f} "
            f"95%CI=[{b.get('ci_low', 0):+.3f}, {b.get('ci_high', 0):+.3f}] "
            f"P(>0)={b.get('p_above_zero', 0):.2f} "
            f"block_length={b.get('block_length', 0)}"
        )
        lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Window: {window[0]} → {window[1]}")
    lines.append(f"- Cadence: {spec.rebalance_cadence}")
    lines.append(f"- Universe loaded: {universe_size} tickers")
    lines.append(f"- Rebalances executed: {len(diags)}")
    lines.append(f"- Daily return observations: {len(rets)}")
    lines.append(f"- Per-position cap: {spec.max_position_weight}")
    lines.append("")
    lines.append("## Honest caveats")
    lines.append("")
    lines.append("- This harness drives the sleeve in PHANTOM ALLOCATION mode against real OHLCV. No cost layer applied (no slippage, no commission, no advisory cap). Edges that fail pre-cost are dead at any layer; edges that pass pre-cost still need the cost layer to clear before any capital deployment.")
    lines.append("- The sleeve is NOT YET wired into PortfolioEngine.allocate. Verdict here informs whether to invest engineering time in the wire-up — not whether to deploy capital.")
    lines.append("- Returns are next-bar close-to-close on the held weights; rebalancing happens at month boundary at the close. Real production would have execution lag; this measurement does not.")
    lines.append("")
    lines.append("## What success unlocks")
    lines.append("")
    lines.append("- **SUCCESS**: schedule the wire-up dispatch — add the opt-in path through `PortfolioEngine.allocate` so the sleeve can be A/B'd against the core book.")
    lines.append("- **PARTIAL**: the sleeve has signal but doesn't clear all gates. Tweak parameters (top_n, max_position_weight, lookback) and re-run before considering the wire.")
    lines.append("- **FAIL**: don't wire. Either the sleeve concept is wrong for this substrate, or the sleeve's parameters need a fundamental rework.")
    lines.append("- **INDETERMINATE**: insufficient data. Extend window or universe.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------- #

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sleeve", required=True, choices=["trend", "moonshot"])
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--out-dir", default=str(DOCS_OUT))
    args = p.parse_args()

    universe_path = REPO / "config" / "universe.json"
    with universe_path.open() as f:
        tickers = json.load(f)
    if not isinstance(tickers, list):
        print(f"[error] universe.json schema unexpected: {type(tickers).__name__}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)

    if args.sleeve == "trend":
        run_trend_verdict(out_dir, tickers, start=args.start, end=args.end)
    elif args.sleeve == "moonshot":
        run_moonshot_verdict(out_dir, tickers, start=args.start, end=args.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
