"""realized_vol_60d — 60-day annualized realized volatility.

Standard deviation of daily log returns over the trailing 60 trading
days, scaled by sqrt(252) to annualize. Cross-sectional convention:
long the bottom quintile (low-vol anomaly).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="realized_vol_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Annualized stdev of trailing 60 daily log returns. Cross-"
        "sectional ranking primitive for the low-vol anomaly."
    ),
)
def realized_vol_60d(ticker: str, dt: date) -> Optional[float]:
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
    if len(log_ret) < 60:
        return None
    return float(np.std(log_ret, ddof=1) * np.sqrt(252.0))
