"""dispersion_60d — cross-sectional std of trailing 60-day returns.

For date `dt`, compute each ticker's 60-day total return
`close_t / close_{t-60} - 1`, then return the standard deviation across
the universe. Captures factor-rotation regimes — high dispersion means
big winners and big losers (factor pickers' market); low dispersion
means everything moves together (macro-driven, factor-hostile).

Universe is whatever's discoverable from the registered LocalOHLCV
source — substrate-independent. Value is ticker-independent (same for
every ticker on a given date); the parameter is kept for substrate
uniformity. Per-date results are cached in-process to avoid re-scanning
the universe on every call. Returns None when fewer than 5 tickers
have ≥61 closes ending at-or-before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series, list_tickers


_DISPERSION_CACHE: Dict[date, Optional[float]] = {}


def _compute_dispersion(dt: date) -> Optional[float]:
    rets = []
    for t in list_tickers():
        s = close_series(t)
        if s is None or s.empty:
            continue
        s = s[s.index <= dt]
        if len(s) < 61:
            continue
        p_now = float(s.iloc[-1])
        p_then = float(s.iloc[-61])
        if p_then <= 0:
            continue
        rets.append(p_now / p_then - 1.0)
    if len(rets) < 5:
        return None
    return float(np.std(np.asarray(rets, dtype=float), ddof=1))


@feature(
    feature_id="dispersion_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Cross-sectional standard deviation of trailing 60-day returns "
        "across the universe. Factor-rotation regime primitive — high "
        "dispersion = factor-friendly market, low = macro-driven."
    ),
)
def dispersion_60d(ticker: str, dt: date) -> Optional[float]:
    if dt in _DISPERSION_CACHE:
        return _DISPERSION_CACHE[dt]
    val = _compute_dispersion(dt)
    _DISPERSION_CACHE[dt] = val
    return val


def clear_dispersion_cache() -> None:
    """Test helper — drop the in-process per-date cache."""
    _DISPERSION_CACHE.clear()
