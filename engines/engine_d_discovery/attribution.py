"""
engines/engine_d_discovery/attribution.py
=========================================
Per-candidate contribution stream computation for the gauntlet.

The architectural fix (project_gauntlet_consolidated_fix_2026_05_01.md):
gates 2-6 should consume the candidate's *attribution stream* — the
difference between the production-equivalent ensemble's returns with
the candidate included vs without — rather than a standalone single-edge
equity curve. Production-equivalent geometry by construction.

Two attribution methodologies are exposed:

1. ``treatment_effect_returns(with_candidate, baseline)``
   The cleanest measure of the candidate's contribution. Daily returns
   of the with-candidate ensemble minus daily returns of the baseline
   ensemble. Captures both the candidate's own fills AND any
   ensemble-spillover effects (capital rivalry, regime interaction,
   meta-learner reweighting). This is what gates 2/3/4/6 should consume.

2. ``per_edge_realized_pnl_returns(trade_log, candidate_id, capital)``
   A narrower measure: the candidate's own realized fills, summed per
   day, divided by capital. Useful as a sanity check and for
   per-fill attribution dashboards. Not the primary gate input.

Both return per-day series indexed by trading day.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


def treatment_effect_returns(
    with_candidate_daily_returns: pd.Series,
    baseline_daily_returns: pd.Series,
) -> pd.Series:
    """Daily attribution stream = with_candidate - baseline.

    Aligns the two series on their intersection. If either is empty,
    returns an empty series.

    Both inputs should be daily-frequency `pd.Series` with datetime-like
    index. The returned series has the same dtype as the inputs (float),
    indexed by the intersection of dates.
    """
    if with_candidate_daily_returns.empty or baseline_daily_returns.empty:
        return pd.Series(dtype=float)

    a = pd.Series(with_candidate_daily_returns).copy()
    b = pd.Series(baseline_daily_returns).copy()
    a.index = pd.to_datetime(a.index).normalize()
    b.index = pd.to_datetime(b.index).normalize()
    # If duplicate dates exist (multi-snapshot per day), aggregate by sum
    # of returns is wrong; take the last per day instead, since equity
    # at end-of-day determines the daily return shape.
    a = a.groupby(a.index).last()
    b = b.groupby(b.index).last()
    df = pd.concat({"with": a, "base": b}, axis=1, join="inner").dropna()
    return df["with"] - df["base"]


def per_edge_realized_pnl_returns(
    trade_log: pd.DataFrame,
    edge_id: str,
    capital: float,
) -> pd.Series:
    """Daily realized PnL for one edge, normalized to per-day return.

    Returns a series of (sum_pnl_for_edge_on_day) / capital, indexed
    by date (midnight-normalized). Trading days with no realized PnL
    for this edge get filled with 0 across the date range observed in
    the trade log.

    Useful for:
    - Sanity-checking that the treatment-effect stream isn't dominated
      by spillover (compare magnitudes).
    - Per-fill diagnostics (which day did the candidate trade?).
    """
    if trade_log.empty:
        return pd.Series(dtype=float)
    if capital <= 0:
        raise ValueError(f"capital must be positive, got {capital}")

    df = trade_log.copy()
    df = df.dropna(subset=["pnl"])
    if df.empty:
        return pd.Series(dtype=float)

    df["edge"] = df["edge"].fillna("Unknown")
    sub = df[df["edge"] == edge_id]
    if sub.empty:
        return pd.Series(dtype=float)

    sub = sub.copy()
    sub["date"] = pd.to_datetime(sub["timestamp"]).dt.normalize()
    daily = sub.groupby("date")["pnl"].sum() / float(capital)
    daily.name = edge_id
    return daily


def stream_sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe of a per-day return stream.

    Returns 0.0 when std == 0 or len < 2 (degenerate inputs). Used by
    Gates 2-4 to compute Sharpe-of-attribution.
    """
    r = pd.Series(returns).dropna()
    if len(r) < 2:
        return 0.0
    s = float(r.std())
    if s == 0.0:
        return 0.0
    return float((r.mean() / s) * np.sqrt(periods_per_year))


def attribution_diagnostics(
    treatment_stream: pd.Series,
    capital: float,
) -> Dict[str, float]:
    """Summary stats for the attribution stream — for audit logging.

    Returns
    -------
    Dict with:
      - n_obs: int (number of days in stream)
      - mean_daily_return: float
      - std_daily_return: float
      - sharpe: float (annualized)
      - total_return: float (cumulative)
      - max_dd: float (peak-to-trough)
    """
    r = pd.Series(treatment_stream).dropna()
    if len(r) == 0:
        return {
            "n_obs": 0, "mean_daily_return": 0.0,
            "std_daily_return": 0.0, "sharpe": 0.0,
            "total_return": 0.0, "max_dd": 0.0,
        }

    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return {
        "n_obs": int(len(r)),
        "mean_daily_return": float(r.mean()),
        "std_daily_return": float(r.std()) if len(r) > 1 else 0.0,
        "sharpe": stream_sharpe(r),
        "total_return": float(cum.iloc[-1] - 1.0),
        "max_dd": float(dd.min()),
    }


__all__ = [
    "treatment_effect_returns",
    "per_edge_realized_pnl_returns",
    "stream_sharpe",
    "attribution_diagnostics",
]
