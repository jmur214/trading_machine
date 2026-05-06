"""weekday_dummy — calendar weekday as float 1.0..5.0 (Mon..Fri).

Captures intraweek seasonality (Monday-effect — historically negative
returns on Mondays; turn-of-week / Friday-effect). Saturday and Sunday
return None since US equities don't trade. Pure calendar primitive —
ticker-independent. Semantically categorical; the meta-learner is
expected to non-linearly decode weekday identity rather than treat the
value as continuous.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature


@feature(
    feature_id="weekday_dummy",
    tier="B",
    horizon=5,
    license="internal",
    source="calendar",
    description=(
        "Weekday as float 1.0..5.0 (Mon..Fri); None on weekends. "
        "Captures intraweek seasonality (Monday-effect, Friday-effect). "
        "Categorical — meta-learner expected to non-linearly decode."
    ),
)
def weekday_dummy(ticker: str, dt: date) -> Optional[float]:
    wd = dt.weekday()  # Mon=0..Sun=6
    if wd >= 5:
        return None
    return float(wd + 1)
