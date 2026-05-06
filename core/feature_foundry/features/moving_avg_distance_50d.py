"""moving_avg_distance_50d — log distance of price from 50d simple MA.

`log(close_t / mean(close[t-49 .. t]))`. Trend primitive distinct from
`mom_*` (return over fixed lookback) and `dist_52w_high` (distance from
extreme): a positive value means price is above its 50-day average,
negative means below. The log scale makes the feature symmetric around
zero and roughly equal to the percent deviation for small displacements.
Returns None when fewer than 50 closes are available before `dt` or
any close is non-positive.
"""
from __future__ import annotations

from datetime import date
from math import log
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="moving_avg_distance_50d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "log(close_t / 50-day simple moving average). Trend primitive — "
        "positive above MA, negative below; symmetric around zero. "
        "Distinct from mom_* (fixed-lookback return) and dist_52w_high "
        "(distance from extreme)."
    ),
)
def moving_avg_distance_50d(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 50:
        return None
    window = s.iloc[-50:].astype(float)
    if (window <= 0).any():
        return None
    p_now = float(window.iloc[-1])
    ma = float(window.mean())
    if ma <= 0:
        return None
    return log(p_now / ma)
