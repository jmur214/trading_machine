"""high_minus_low_60d — 60d (max-min)/mean range, normalized.

`(max(close[t-59 .. t]) - min(close[t-59 .. t])) / mean(close[t-59 .. t])`.
A range-based volatility primitive distinct from `realized_vol_60d`
(standard deviation of log returns): this captures peak-to-trough
amplitude rather than dispersion of period returns. The Parkinson and
Garman-Klass families show range-based vol estimators are more efficient
than close-to-close stdev for the same horizon. Returns None when fewer
than 60 closes are available before `dt` or the mean is non-positive.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="high_minus_low_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "(60d max - 60d min) / 60d mean. Range-based vol primitive — "
        "peak-to-trough amplitude, distinct from realized_vol_60d "
        "(stdev of log returns). Parkinson/Garman-Klass family."
    ),
)
def high_minus_low_60d(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 60:
        return None
    window = s.iloc[-60:].astype(float)
    mean = float(window.mean())
    if mean <= 0:
        return None
    return (float(window.max()) - float(window.min())) / mean
