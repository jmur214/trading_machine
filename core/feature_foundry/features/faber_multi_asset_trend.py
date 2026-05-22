"""faber_multi_asset_trend_above_10mo_sma — Faber GTAA price-regime
filter, 5-asset version.

For date `dt`, compute for each of {SPY, EFA, AGG, GLD, VNQ}:
    binary 1 if `close > SMA(close, 10-month=210 trading days)` else 0.
Return the SUM of those 5 binaries → integer score in {0, 1, 2, 3, 4, 5}.

Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"
proposed the 10-month SMA rule across 5 asset classes as the canonical
price-regime filter. Multi-asset breadth above the trend filter
correlates strongly with subsequent low-risk equity environments;
breadth ≤ 1 historically precedes most 10 %+ drawdowns.

Per T-2026-05-12-052 research convergence: this is the canonical
slow-regime filter — monthly evaluation cadence is sufficient (carry-
forward to daily bars). All 4 research dives flagged it as the
price-component of a 4-signal regime ensemble.

Data sources (per Faber's original):
- SPY (US large-cap equity)
- EFA (developed international equity)
- AGG (US aggregate bonds)
- GLD (gold)
- VNQ (US REITs)

**Partial-coverage caveat**: if any of EFA, AGG, VNQ aren't in
`data/processed/*_1d.csv` cache (current T-052 state lacks them),
the feature returns the score over whatever ETFs ARE available, with
range = number-of-available-ETFs. Run `scripts/backfill_t052_macro_data.py`
to populate the missing tickers from yfinance.

Returns None when fewer than 2 of the 5 ETFs are available or when
fewer than 210 days of price history exist before `dt`.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..feature import feature
from ..sources.local_ohlcv import close_series

logger = logging.getLogger(__name__)


# Faber GTAA canonical 5-asset basket. ORDER PRESERVED for
# reproducibility.
_FABER_TICKERS = ("SPY", "EFA", "AGG", "GLD", "VNQ")

# 10-month SMA ≈ 210 trading days (12 mo × ~21 trading days = 252;
# Faber paper uses 10 mo of monthly closes = 200 trading days
# approximate). 210 is the conventional retail value.
_SMA_WINDOW_DAYS = 210


_MISSING_LOGGED = False


def _log_missing_once(missing: list) -> None:
    global _MISSING_LOGGED
    if _MISSING_LOGGED:
        return
    _MISSING_LOGGED = True
    logger.warning(
        "[FOUNDRY] faber_multi_asset_trend: missing OHLCV for %s — "
        "feature returns partial-coverage score. Run scripts/backfill_t052_macro_data.py "
        "to populate from yfinance.",
        ", ".join(missing),
    )


@feature(
    feature_id="faber_multi_asset_trend_above_10mo_sma",
    tier="A",
    horizon=21,
    license="public",
    source="local_ohlcv",
    description=(
        "Sum of 5-asset breadth above 10-month SMA: SPY+EFA+AGG+GLD+VNQ. "
        "Faber GTAA price-regime filter, canonical multi-asset breadth "
        "signal. T-052 ensemble."
    ),
)
def faber_multi_asset_trend_above_10mo_sma(
    ticker: str, dt: date,
) -> Optional[float]:
    available: Dict[str, pd.Series] = {}
    missing = []
    for t in _FABER_TICKERS:
        s = close_series(t)
        if s is None or s.empty:
            missing.append(t)
            continue
        s = s[s.index <= dt]
        if len(s) < _SMA_WINDOW_DAYS + 1:
            missing.append(t)
            continue
        available[t] = s
    if missing:
        _log_missing_once(missing)
    if len(available) < 2:
        return None
    score = 0
    for t, s in available.items():
        window = s.iloc[-_SMA_WINDOW_DAYS:].astype(float).values
        sma = float(np.mean(window))
        v_now = float(s.iloc[-1])
        if v_now > sma:
            score += 1
    return float(score)
