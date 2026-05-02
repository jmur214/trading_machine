"""mom_12_1 — 12-1 momentum (Jegadeesh-Titman 1993).

Return over the prior 12 months (252 trading days) excluding the most
recent month (skip last 21 trading days). The textbook cross-sectional
ranking primitive: long top decile, short bottom decile, monthly
rebalance. The skipped month removes 1-month reversal contamination.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="mom_12_1",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Return over t-252..t-21 trading days. Cross-sectional ranking "
        "primitive (Jegadeesh-Titman 1993)."
    ),
)
def mom_12_1(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 253:
        return None
    p_recent = float(s.iloc[-21])
    p_old = float(s.iloc[-252])
    if p_old <= 0:
        return None
    return p_recent / p_old - 1.0
