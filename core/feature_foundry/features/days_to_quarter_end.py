"""days_to_quarter_end — calendar days to next Mar/Jun/Sep/Dec end.

Integer 0..92 returned as float; 0 on quarter-end day. Captures
quarter-end portfolio rebalancing flow / window-dressing pressure.
Pure calendar primitive — ticker-independent, kept in signature for
substrate compatibility.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature


def _next_quarter_end(dt: date) -> date:
    """The first calendar quarter-end ≥ dt."""
    q_ends = [
        date(dt.year, 3, 31),
        date(dt.year, 6, 30),
        date(dt.year, 9, 30),
        date(dt.year, 12, 31),
    ]
    for q in q_ends:
        if dt <= q:
            return q
    return date(dt.year + 1, 3, 31)


@feature(
    feature_id="days_to_quarter_end",
    tier="B",
    horizon=10,
    license="internal",
    source="calendar",
    description=(
        "Calendar days until next quarter-end (Mar/Jun/Sep/Dec 31 or 30). "
        "Captures quarter-end rebalancing flow / window-dressing pressure. "
        "Pure calendar — ticker-independent."
    ),
)
def days_to_quarter_end(ticker: str, dt: date) -> Optional[float]:
    return float((_next_quarter_end(dt) - dt).days)
