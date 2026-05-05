"""vvix_or_proxy — vol-of-vol stress signal (VVIX substitute).

Spec called for CBOE's VVIX (VIX of VIX). DATA GAP: VVIX is NOT in the
project's macro cache — only VIXCLS. Practical substitute: 30-business-
day realized volatility of VIX itself, computed from daily VIX log
returns and annualized.

When VIX is stable (regardless of its level), the realized vol of VIX is
low — markets are pricing a coherent vol path. When VIX itself becomes
volatile, the realized vol of VIX spikes — the market is uncertain even
about the level of fear, which is the classic vol-of-vol stress signature
that VVIX is designed to capture.

This is a substitute, not a clone. Real VVIX is implied (option-derived,
forward-looking ~30d). Ours is realized (backward-looking 30d, equity-
style). The two correlate strongly empirically (~0.7 in published
studies) but our version lags VVIX during fast regime turns — this is
the standard tradeoff of any realized-vol substitute for an implied
measure.

Ticker-independent — same scalar for every name on a given dt.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="vvix_or_proxy",
    tier="B",
    horizon=20,
    license="public",
    source="fred_macro",
    description=(
        "30-business-day annualized realized volatility of VIX log "
        "returns (from FRED VIXCLS). Substitute for CBOE VVIX, which "
        "isn't in the data layer. Vol-of-vol stress signal — high values "
        "indicate market is uncertain about the level of fear itself. "
        "Ticker-independent."
    ),
)
def vvix_or_proxy(ticker: str, dt: date) -> Optional[float]:
    s = series("VIXCLS")
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    # FRED VIXCLS occasionally has NaN holes (federal/trading-day holidays
    # like Christmas Day). Drop them — std-of-log-returns must operate on
    # a clean numeric series, otherwise NaN poisons the whole window.
    s = s.dropna()
    if len(s) < 31:
        return None
    closes = s.iloc[-31:].astype(float).values
    if (closes <= 0).any():
        return None
    log_ret = np.diff(np.log(closes))
    if len(log_ret) < 30:
        return None
    val = float(np.std(log_ret, ddof=1) * np.sqrt(252.0))
    if not np.isfinite(val):
        return None
    return val
