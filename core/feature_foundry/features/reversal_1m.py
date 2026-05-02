"""reversal_1m — short-term (1-month) reversal.

Last-21-trading-day return. The classic short-term reversal anomaly:
recent winners underperform recent losers over the following month.
Cross-sectional convention: long the bottom decile (most negative
recent return), short the top decile.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="reversal_1m",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Trailing 21-trading-day return. Cross-sectional ranking "
        "primitive for short-term mean reversion."
    ),
)
def reversal_1m(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 22:
        return None
    p_now = float(s.iloc[-1])
    p_then = float(s.iloc[-22])
    if p_then <= 0:
        return None
    return p_now / p_then - 1.0
