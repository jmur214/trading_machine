"""month_of_year_dummy — calendar month as float 1.0..12.0.

Captures seasonality (Sell-in-May, Santa Rally, September weakness,
January effect). Semantically categorical; meta-learner expected to
non-linearly decode month identity rather than treat as continuous.
Pure calendar primitive — ticker-independent.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature


@feature(
    feature_id="month_of_year_dummy",
    tier="B",
    horizon=21,
    license="internal",
    source="calendar",
    description=(
        "Calendar month as float 1.0..12.0. Captures seasonality "
        "(Sell-in-May, Santa Rally, September weakness, January effect). "
        "Meta-learner expected to non-linearly decode the categorical "
        "structure; raw ordering is not monotonically informative."
    ),
)
def month_of_year_dummy(ticker: str, dt: date) -> Optional[float]:
    return float(dt.month)
