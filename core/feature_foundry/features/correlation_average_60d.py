"""correlation_average_60d — average pairwise return correlation.

For date `dt`, compute the daily-log-return correlation matrix across
the universe over the trailing 60 trading days, then return the mean
of all upper-triangular off-diagonal entries. Spikes precede
coordinated drawdowns — when everything correlates to 1, idiosyncratic
risk vanishes and de-grossing is required to retain Sharpe.

Substrate-independent: universe is whatever's discoverable from the
registered LocalOHLCV source. Value is ticker-independent; the
parameter is kept for substrate uniformity. Per-date results are
cached in-process to amortize universe scans. Returns None when fewer
than 3 tickers have ≥61 aligned closes ending at-or-before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..feature import feature
from ..sources.local_ohlcv import close_series, list_tickers


_CORR_CACHE: Dict[date, Optional[float]] = {}


def _compute_avg_correlation(dt: date) -> Optional[float]:
    log_returns: Dict[str, pd.Series] = {}
    for t in list_tickers():
        s = close_series(t)
        if s is None or s.empty:
            continue
        s = s[s.index <= dt]
        if len(s) < 61:
            continue
        closes = s.iloc[-61:].astype(float)
        if (closes <= 0).any():
            continue
        log_returns[t] = pd.Series(
            np.diff(np.log(closes.values)), index=closes.index[1:]
        )
    if len(log_returns) < 3:
        return None
    df = pd.DataFrame(log_returns).dropna()
    if df.shape[0] < 30 or df.shape[1] < 3:
        return None
    corr = df.corr().to_numpy()
    iu = np.triu_indices_from(corr, k=1)
    pairs = corr[iu]
    pairs = pairs[~np.isnan(pairs)]
    if pairs.size == 0:
        return None
    return float(pairs.mean())


@feature(
    feature_id="correlation_average_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Mean of upper-triangular pairwise correlations of trailing-60d "
        "log returns across the universe. Coordinated-drawdown primitive "
        "— spikes precede de-grossing regimes."
    ),
)
def correlation_average_60d(ticker: str, dt: date) -> Optional[float]:
    if dt in _CORR_CACHE:
        return _CORR_CACHE[dt]
    val = _compute_avg_correlation(dt)
    _CORR_CACHE[dt] = val
    return val


def clear_correlation_cache() -> None:
    """Test helper — drop the in-process per-date cache."""
    _CORR_CACHE.clear()
