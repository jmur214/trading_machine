"""dxy_change_20d — USD index 20-business-day percent change.

Risk-off / risk-on regime confirmation. USD strength historically
correlates with risk-off episodes (flight to dollar safety, EM stress,
commodity weakness). A rapid 20d rally in the dollar is one of the
classic 'crash signature' indicators alongside HY-spread widening and
vol-of-vol spikes.

Source: FRED `DTWEXBGS` — Trade-Weighted U.S. Dollar Index against a
broad basket of currencies. Daily frequency, 2006-present in the local
cache. Ticker-independent — broadcasts the same scalar to every name on
a given dt.

Hard caveat: DTWEXBGS publishes with ~1 business-day lag (FRED's typical
exchange-rate cadence). The local cache reflects whatever the macro data
manager last pulled — features should call `s[s.index <= dt]` (which
this does) to enforce no-leakage at the (ticker, dt) cell.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="dxy_change_20d",
    tier="B",
    horizon=20,
    license="public",
    source="fred_macro",
    description=(
        "20-business-day percent change in the trade-weighted USD index "
        "(FRED DTWEXBGS). Risk-off proxy: a rapid USD rally is part of "
        "the classic crash-signature trio (with HY-spread widening and "
        "vol-of-vol spikes). Ticker-independent."
    ),
)
def dxy_change_20d(ticker: str, dt: date) -> Optional[float]:
    s = series("DTWEXBGS")
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 21:
        return None
    window = s.iloc[-21:].astype(float).values
    v_now = float(window[-1])
    v_then = float(window[0])
    if v_then <= 0:
        return None
    return v_now / v_then - 1.0
