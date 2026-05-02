"""drawdown_60d — distance from the 60-day rolling max.

`(close_t / max(close[t-59 .. t])) - 1`. Float in (-1, 0]. Shorter
horizon cousin of `dist_52w_high` — captures intermediate-term
drawdown depth used by mean-reversion overlays and stop-management
heuristics. Returns None when fewer than 60 trading-day closes are
available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="drawdown_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "(close_t / 60-day rolling max) - 1. Cross-sectional ranking "
        "primitive — intermediate-term drawdown depth."
    ),
)
def drawdown_60d(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 60:
        return None
    window = s.iloc[-60:].astype(float)
    p_now = float(window.iloc[-1])
    p_max = float(window.max())
    if p_max <= 0:
        return None
    return p_now / p_max - 1.0
