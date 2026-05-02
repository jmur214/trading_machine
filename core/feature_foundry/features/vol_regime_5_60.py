"""vol_regime_5_60 — short-vs-long realized vol ratio.

`stdev(log_ret[t-4 .. t]) / stdev(log_ret[t-59 .. t])`. Captures
volatility expansion (>1) vs contraction (<1). Useful both as a
cross-sectional feature (high values = recent shock) and as input to
regime-conditional sizing. Returns None when fewer than 61 closes are
available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="vol_regime_5_60",
    tier="B",
    horizon=5,
    license="internal",
    source="local_ohlcv",
    description=(
        "5-day realized vol divided by 60-day realized vol. Cross-"
        "sectional ranking primitive — vol expansion/contraction ratio."
    ),
)
def vol_regime_5_60(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 61:
        return None
    closes = s.iloc[-61:].astype(float).values
    if (closes <= 0).any():
        return None
    log_ret = np.diff(np.log(closes))
    short = float(np.std(log_ret[-5:], ddof=1))
    long_ = float(np.std(log_ret, ddof=1))
    if long_ <= 0:
        return None
    return short / long_
