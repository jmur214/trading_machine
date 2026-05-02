"""ma_cross_50_200 — long-term trend strength via SMA crossover.

`(SMA_50 - SMA_200) / SMA_200`. Positive when the 50-day SMA is above
the 200-day SMA ("golden cross" regime); negative below ("death cross").
Magnitude expresses gap size in fractional terms — a normalized
continuous version of the binary cross signal. Returns None when fewer
than 200 trading-day closes are available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="ma_cross_50_200",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "(SMA_50 - SMA_200) / SMA_200. Cross-sectional ranking primitive "
        "— normalized long-term trend strength."
    ),
)
def ma_cross_50_200(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 200:
        return None
    closes = s.iloc[-200:].astype(float)
    sma_50 = float(closes.iloc[-50:].mean())
    sma_200 = float(closes.mean())
    if sma_200 <= 0:
        return None
    return (sma_50 - sma_200) / sma_200
