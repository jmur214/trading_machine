"""mom_6_1 — 6-1 momentum.

Return over the prior 6 months (126 trading days) excluding the most
recent month (skip last 21 trading days). Higher-frequency cousin of
mom_12_1 — captures intermediate-horizon trend persistence with the
same 1-month reversal skip.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="mom_6_1",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Return over t-126..t-21 trading days. Cross-sectional ranking "
        "primitive — 6-month horizon variant of Jegadeesh-Titman."
    ),
)
def mom_6_1(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 127:
        return None
    p_recent = float(s.iloc[-21])
    p_old = float(s.iloc[-126])
    if p_old <= 0:
        return None
    return p_recent / p_old - 1.0
