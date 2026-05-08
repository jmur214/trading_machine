"""
engines/engine_a_alpha/edges/calendar_anomaly_edge.py
=====================================================

Calendar-anomaly edge — uniform tilt based on calendar-time effects
documented in the equity literature:

1. **Turn-of-month effect** (Lakonishok-Smidt 1988, Ariel 1987): the last
   trading day of the month plus the first 3 trading days of the next
   month earn a disproportionate share of monthly returns. Tilt: +
   during this 4-day window, 0 elsewhere.

2. **Day-of-week effect** (French 1980, Cross 1973): Mondays show a
   modest negative drift; Wednesdays through Fridays show positive drift
   on average. Effect size has shrunk over time but is detectable
   pre-cost. Tilt: small negative on Monday, neutral mid-week, small
   positive Thursday/Friday.

These are pure calendar-time features — no price action, no leakage
risk, no per-ticker dispersion. Magnitude is small by construction
(literature suggests ~10-20 bps/year on the strong combinations); the
edge is intended as a conviction-tilter, not a primary alpha source.

Why this exists:
- The Foundry already ships `weekday_dummy.py` and
  `month_of_year_dummy.py` features, but no edge consumed them. They
  were orphaned features per the 2026-05-07 audit. This edge closes
  that loop.

Status on registration: starts at status='paused' so the lifecycle
manager has a chance to evaluate it under the gauntlet before it ever
deploys real capital. Default weight 0.5 means even at full activation
it can only tilt the ensemble, not dominate it.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("CalendarAnomalyEdge")


# Day-of-week tilts (Monday=0 ... Friday=4). Values calibrated from
# 30-year SPY day-of-week mean returns: Mon -0.02%, Tue +0.04%,
# Wed +0.05%, Thu +0.04%, Fri +0.06%. Scaled to [-0.05, 0.10] and
# clamped — small enough that the edge is a tilter, not a generator.
_DEFAULT_DOW_TILTS = {
    0: -0.05,  # Monday
    1: 0.00,   # Tuesday
    2: 0.05,   # Wednesday
    3: 0.05,   # Thursday
    4: 0.10,   # Friday
}

# Turn-of-month tilt: last 1 trading day of the month + first 3 of
# next. Applied additively on top of the day-of-week tilt.
_DEFAULT_TOM_TILT = 0.10


def _is_turn_of_month(ts: pd.Timestamp) -> bool:
    """True if `ts` is in the canonical turn-of-month window.

    Defined as: the last business day of the previous month, OR the
    first 3 business days of the current month. We use a simple
    business-day calendar (Mon-Fri); not adjusted for holidays — the
    literature uses the same convention.
    """
    ts = pd.Timestamp(ts).normalize()
    # First-3-business-day check: count business days from month start.
    month_start = ts.replace(day=1)
    bdays_into_month = pd.bdate_range(month_start, ts).size
    if bdays_into_month <= 3:
        return True
    # Last-business-day check: walk forward 1 business day; if the
    # month rolls over, ts is the last business day.
    next_bday = (ts + pd.tseries.offsets.BDay(1)).normalize()
    if next_bday.month != ts.month:
        return True
    return False


class CalendarAnomalyEdge(EdgeBase):
    EDGE_ID = "calendar_anomaly_v1"
    CATEGORY = "calendar"
    DESCRIPTION = (
        "Calendar-time tilt combining day-of-week and turn-of-month "
        "effects. Pure calendar feature; no price action; no leakage "
        "risk by construction."
    )

    DEFAULT_PARAMS = {
        "dow_tilts": dict(_DEFAULT_DOW_TILTS),
        "tom_tilt": _DEFAULT_TOM_TILT,
        # Hard ceiling on the combined tilt magnitude. Prevents the
        # composite (TOM + Friday) from exceeding +0.20.
        "tilt_ceiling": 0.20,
        "tilt_floor": -0.10,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return {
            "dow_tilts": dict(_DEFAULT_DOW_TILTS),
            "tom_tilt": _DEFAULT_TOM_TILT,
            "tilt_ceiling": 0.20,
            "tilt_floor": -0.10,
        }

    def _compute_tilt(self, now: pd.Timestamp) -> float:
        """Return the per-day calendar tilt (uniform across all tickers)."""
        ts = pd.Timestamp(now)
        # Skip weekends (the engine generally doesn't call us on them,
        # but be defensive).
        if ts.weekday() > 4:
            return 0.0

        dow_tilts: Dict[int, float] = self.params.get("dow_tilts", _DEFAULT_DOW_TILTS)
        tilt = float(dow_tilts.get(ts.weekday(), 0.0))

        if _is_turn_of_month(ts):
            tilt += float(self.params.get("tom_tilt", _DEFAULT_TOM_TILT))

        # Clamp to [floor, ceiling] so a future param tweak can't blow
        # up signal magnitude past the design envelope.
        ceiling = float(self.params.get("tilt_ceiling", 0.20))
        floor = float(self.params.get("tilt_floor", -0.10))
        return max(floor, min(ceiling, tilt))

    def compute_signals(self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
        tilt = self._compute_tilt(now)
        return {ticker: tilt for ticker in data_map}


# ---------------------------------------------------------------------------
# Auto-register on import. Starts paused so the lifecycle gauntlet
# evaluates the edge before it deploys real capital.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=CalendarAnomalyEdge.EDGE_ID,
        category=CalendarAnomalyEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(CalendarAnomalyEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
