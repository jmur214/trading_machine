"""skew_60d — 60-day rolling skewness of daily log returns.

Sample skewness (Fisher-Pearson, ddof=1) of the trailing 60 daily log
returns. Negative skew = fat left tail (crash risk). Cross-sectional
ranking primitive: low-skew stocks have historically earned a return
premium (Bali et al. 2011 on idiosyncratic skewness). Returns None when
fewer than 61 closes are available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


@feature(
    feature_id="skew_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Sample skewness of trailing 60 daily log returns. Cross-"
        "sectional ranking primitive — low-skew premium (Bali 2011)."
    ),
)
def skew_60d(ticker: str, dt: date) -> Optional[float]:
    s = close_series(ticker)
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 61:
        return None
    closes = s.iloc[-61:].astype(float).values
    if (closes <= 0).any():
        return None
    r = np.diff(np.log(closes))
    mu = float(r.mean())
    m2 = float(np.mean((r - mu) ** 2))
    if m2 <= 0:
        return None
    m3 = float(np.mean((r - mu) ** 3))
    n = len(r)
    return (m3 / m2 ** 1.5) * (n * (n - 1)) ** 0.5 / (n - 2)
