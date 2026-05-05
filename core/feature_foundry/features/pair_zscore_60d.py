"""pair_zscore_60d — 60-day rolling z-score of price ratio for hand-picked pairs.

For each ticker mapped to a sector pair (JPM/BAC, XOM/CVX, KO/PEP,
HD/LOW, V/MA), compute the log price ratio `log(self / partner)` and
return the 60-day rolling z-score of that ratio. Positive z = self
expensive vs partner (mean-revert short candidate); negative z = self
cheap vs partner (mean-revert long candidate). Sign convention matches
the long-the-cheap leg convention in stat-arb.

Tickers not in the pair map return None — keeps the feature defined
only where it has a partner, rather than emitting noise. Returns None
when fewer than 60 aligned trading days exist.

Hand-picked pairs are documented in the model card; expansion to
data-driven cointegrating pairs is a Discovery-engine follow-up.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


# Each ticker maps to its partner. Pairs are bidirectional — JPM has
# partner BAC and BAC has partner JPM.
_PAIRS = {
    "JPM": "BAC", "BAC": "JPM",
    "XOM": "CVX", "CVX": "XOM",
    "KO":  "PEP", "PEP": "KO",
    "HD":  "LOW", "LOW": "HD",
    "V":   "MA",  "MA":  "V",
}


@feature(
    feature_id="pair_zscore_60d",
    tier="B",
    horizon=10,
    license="internal",
    source="local_ohlcv",
    description=(
        "60-day rolling z-score of log(self/partner) price ratio for 5 "
        "hand-picked sector pairs (JPM/BAC, XOM/CVX, KO/PEP, HD/LOW, "
        "V/MA). Mean-reversion stat-arb primitive. Defined only for "
        "tickers in the pair map; others return None."
    ),
)
def pair_zscore_60d(ticker: str, dt: date) -> Optional[float]:
    partner = _PAIRS.get(ticker)
    if partner is None:
        return None
    s_self = close_series(ticker)
    s_pair = close_series(partner)
    if s_self is None or s_pair is None:
        return None
    s_self = s_self[s_self.index <= dt]
    s_pair = s_pair[s_pair.index <= dt]
    idx = sorted(s_self.index.intersection(s_pair.index))[-60:]
    if len(idx) < 60:
        return None
    a = s_self.loc[idx].astype(float).values
    b = s_pair.loc[idx].astype(float).values
    if (a <= 0).any() or (b <= 0).any():
        return None
    ratio = np.log(a) - np.log(b)
    mu = float(ratio.mean())
    sd = float(ratio.std(ddof=1))
    if sd <= 0:
        return None
    return (float(ratio[-1]) - mu) / sd
