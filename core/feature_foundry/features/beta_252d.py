"""beta_252d — 252-day beta vs SPY.

OLS beta of daily log returns vs SPY daily log returns over the
trailing 252 trading days (cov / var). Cross-sectional convention:
long the bottom quintile (low-beta anomaly).

Returns None for SPY itself and when the SPY series is missing or
shorter than the lookback.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


def _aligned_log_returns(ticker_close, spy_close, n: int):
    idx = ticker_close.index.intersection(spy_close.index)
    idx = sorted(idx)[-(n + 1):]
    if len(idx) < n + 1:
        return None, None
    a = np.log(ticker_close.loc[idx].astype(float).values)
    b = np.log(spy_close.loc[idx].astype(float).values)
    return np.diff(a), np.diff(b)


@feature(
    feature_id="beta_252d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "OLS beta of daily log returns vs SPY over trailing 252 days. "
        "Cross-sectional ranking primitive for the low-beta anomaly."
    ),
)
def beta_252d(ticker: str, dt: date) -> Optional[float]:
    if ticker == "SPY":
        return None
    s_t = close_series(ticker)
    s_b = close_series("SPY")
    if s_t is None or s_b is None or s_t.empty or s_b.empty:
        return None
    s_t = s_t[s_t.index <= dt]
    s_b = s_b[s_b.index <= dt]
    r_t, r_b = _aligned_log_returns(s_t, s_b, n=252)
    if r_t is None or r_b is None:
        return None
    var_b = float(np.var(r_b, ddof=1))
    if var_b <= 0:
        return None
    cov_tb = float(np.cov(r_t, r_b, ddof=1)[0, 1])
    return cov_tb / var_b
