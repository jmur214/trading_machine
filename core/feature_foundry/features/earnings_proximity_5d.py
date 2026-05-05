"""earnings_proximity_5d — graded 0..1 score = max(0, 1 - bdays/5).

1.0 on announcement day, 0.8 one trading day prior, 0.0 once the next
announcement is more than 5 trading days away. Captures pre-announcement
run-up + Post-Earnings Announcement Drift. Reads ONLY scheduled dates,
never EPS / surprise — point-in-time safe. Returns None for tickers
without cached earnings or once all cached announcements are past.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from ..feature import feature
from ..sources.earnings_calendar import announcement_dates


@feature(
    feature_id="earnings_proximity_5d",
    tier="B",
    horizon=5,
    license="internal",
    source="earnings_calendar",
    description=(
        "Graded score 0..1 = max(0, 1 - business_days_to_next_earnings/5). "
        "Captures pre-announcement run-up + PEAD windows. Uses only "
        "scheduled announcement DATES (point-in-time safe); the surprise "
        "/ actuals are not consumed."
    ),
)
def earnings_proximity_5d(ticker: str, dt: date) -> Optional[float]:
    idx = announcement_dates(ticker)
    if idx is None or len(idx) == 0:
        return None
    dt_ts = pd.Timestamp(dt)
    future = idx[idx >= dt_ts]
    if len(future) == 0:
        return None
    # numpy.busday_count is exclusive of end date — symmetric:
    # busday_count(dt, dt) == 0; same trading day → score 1.0.
    days = float(np.busday_count(dt, future[0].date()))
    return max(0.0, 1.0 - days / 5.0)
