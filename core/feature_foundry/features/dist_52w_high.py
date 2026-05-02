"""dist_52w_high — distance from the 52-week (252-trading-day) high.

`(close_t / max(close[t-251 .. t])) - 1`. Float in (-1, 0]; equals 0 on
a fresh 52-week high. CAN-SLIM-flavored momentum primitive: stocks
within a few percent of their 52w high have historically continued
trending (George & Hwang, 2004). Returns None when fewer than 252
trading-day closes are available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="dist_52w_high",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "(close_t / 252-day rolling max) - 1. Cross-sectional ranking "
        "primitive — distance from the 52-week high (George-Hwang 2004)."
    ),
)
def dist_52w_high(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 252:
        return None
    window = s.iloc[-252:].astype(float)
    p_now = float(window.iloc[-1])
    p_max = float(window.max())
    if p_max <= 0:
        return None
    return p_now / p_max - 1.0
