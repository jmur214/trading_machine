"""hyg_lqd_spread — credit-stress regime signal as 60d z-score.

Spec called for HYG / LQD ETF closing-price ratio (high-yield ETF over
investment-grade ETF). DATA GAP: HYG_1d.csv and LQD_1d.csv are NOT in
`data/processed/` — only SPY and TLT are. Direct ETF substitute is not
available.

Substitute: FRED's BAML option-adjusted-spread series, which expose the
same credit-risk channel at index level rather than ETF level:

  - BAMLH0A0HYM2 — US High Yield Master II OAS
  - BAMLC0A0CM   — US Corporate (Investment-Grade) Master OAS

We compute the HY-minus-IG spread (in basis-point units) and return its
60-business-day rolling z-score. Spread WIDENS (z > 1) = credit stress;
NARROWS (z < -1) = risk-on / yield reach. Ticker-independent — the same
scalar broadcasts to every name on a given dt.

Hard data caveat: BAML OAS parquets in this project start 2023-04-25.
The 60d z-score is therefore None before ~2023-07-21 (61 business days
after series start). For 2021-2022 backtests this feature returns None
and the meta-learner / cross-asset gate must degrade gracefully.

The HY-minus-IG construction is academically equivalent in sign and
direction to the HYG/LQD ratio — both go UP in stress (HY underperforms
IG). The magnitudes are not comparable to ETF returns, but the z-score
normalization makes that irrelevant for a regime signal.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="hyg_lqd_spread",
    tier="B",
    horizon=20,
    license="public",
    source="fred_macro",
    description=(
        "60-business-day z-score of the HY-minus-IG OAS spread "
        "(BAMLH0A0HYM2 - BAMLC0A0CM). Substitute for the HYG/LQD ETF "
        "ratio, which isn't in the project's data layer. Z > +1 = credit "
        "stress regime; Z < -1 = reach for yield. Ticker-independent. "
        "Returns None before 2023-07 (BAML series start)."
    ),
)
def hyg_lqd_spread(ticker: str, dt: date) -> Optional[float]:
    hy = series("BAMLH0A0HYM2")
    ig = series("BAMLC0A0CM")
    if hy is None or ig is None or hy.empty or ig.empty:
        return None
    hy = hy[hy.index <= dt].astype(float)
    ig = ig[ig.index <= dt].astype(float)
    if len(hy) < 61 or len(ig) < 61:
        return None
    # Align on the intersection of dates and take the spread.
    aligned = hy.to_frame("hy").join(ig.to_frame("ig"), how="inner").dropna()
    if len(aligned) < 61:
        return None
    spread = aligned["hy"] - aligned["ig"]
    window = spread.iloc[-60:].values.astype(float)
    current = float(spread.iloc[-1])
    mean = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    if std <= 1e-9 or not np.isfinite(std):
        return None
    return (current - mean) / std
