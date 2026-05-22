"""hy_oas_change_20d — 20-business-day change in HY OAS (basis points).

For date `dt`, compute `HY_OAS(t) - HY_OAS(t-20)` in basis points.
Credit-spread velocity. HY OAS widening before equity declines is a
leading recession / risk-off indicator with 6-12 month lag per Gilchrist-
Zakrajšek (2012) and the FRB's EBP literature. Faster than equity vol
(which is coincident); slower than yield curve (which is forecasting
multi-year). The 20-day delta captures the meaningful 1-month credit
regime shift.

Data source: FRED daily series BAMLH0A0HYM2 (ICE BofA US High Yield
Index Option-Adjusted Spread). Already on the project's macro pipeline.
Daily close, ~1-day publication lag → usable at T+1 EOD safely. Ticker-
independent.

Per T-2026-05-12-052 research convergence: the Δ (change) signal
matters more than the LEVEL for regime classification — a "high but
stable" spread is less informative than a "moderate but spiking"
spread.

Returns None when fewer than 21 days of history are available before
`dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="hy_oas_change_20d",
    tier="A",
    horizon=21,
    license="public",
    source="fred_macro",
    description=(
        "20-business-day change in BAMLH0A0HYM2 (HY OAS), in basis "
        "points. Credit-stress velocity — leading 6-12mo equity decline "
        "signal per Gilchrist-Zakrajšek. T-052 minimum regime ensemble."
    ),
)
def hy_oas_change_20d(ticker: str, dt: date) -> Optional[float]:
    s = series("BAMLH0A0HYM2")
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 21:
        return None
    # FRED publishes BAMLH0A0HYM2 as a percentage (e.g., 3.50 = 350 bps).
    # Multiply the delta by 100 to express in basis points.
    v_now = float(s.iloc[-1])
    v_then = float(s.iloc[-21])
    return (v_now - v_then) * 100.0
