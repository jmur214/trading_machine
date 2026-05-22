"""engines/engine_a_alpha/edges/spinoff_reversion_v1.py
=========================================================
Spin-off reversion edge (T-2026-05-12-041).

Mechanism
---------
When a parent spins off a subsidiary, index funds tracking the parent's
index automatically dump the child (it's not in their index until the
next rebalance). Active managers benchmarked to the parent's index do
the same. The mechanical selling drives the spin-off below fair value
in the immediate post-distribution window. Retail capital can pick up
the discount; institutional capital cannot trade at size in mid/small-
cap spin-offs.

Academic backing: Cusatis-Miles-Woolridge (1993) — spin-offs outperform
industry peers by ~10% annualized for 3 years post-distribution.
Greenblatt (1997, *You Can Be a Stock Market Genius*) popularized the
retail trade.

Signal logic
------------
For each ticker in `data_map`:
  1. Look up whether the ticker is a SPIN-OFF CHILD in the detector's
     event table.
  2. If yes, compute trading-day distance from distribution_date.
  3. Emit BUY signal when distance ∈ [entry_offset, entry_offset +
     holding_period]. Otherwise abstain (0.0).

The signal is BINARY (1.0 when in window, 0.0 otherwise). Position
sizing, max-concurrent, and stop-loss are downstream concerns
(Engine C + Engine B).

Long-only.

Hard constraints
----------------
- No look-ahead: only spin-off events with `distribution_date <= as_of`
  are considered.
- Tickers added to `data_map` AFTER `distribution_date` only — caller
  responsibility (universe resolver wiring is T-041b).

Status on registration
----------------------
`status='paused' tier='feature'` — gauntlet validation required before
activation. Matches the dividend_initiation_drift_v1 + calendar_anomaly_v1
+ cot_positioning_v1 convention.
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase
from ._helpers.spinoff_detector import (
    SpinoffEvent,
    events_by_child,
    get_events,
)

logger = logging.getLogger("SpinoffReversionEdge")


class SpinoffReversionEdge(EdgeBase):
    EDGE_ID = "spinoff_reversion_v1"
    CATEGORY = "event_driven_structural"
    DESCRIPTION = (
        "Long signal on spin-off children in the post-distribution "
        "window. Captures index-fund forced-selling pressure that "
        "drives spin-offs below fair value. Cusatis-Miles-Woolridge "
        "(1993) + Greenblatt (1997). Long-only."
    )

    DEFAULT_PARAMS = {
        # Days after distribution_date before entering. Let initial
        # dumping start; avoid day-of-distribution chaos.
        "entry_offset_days": 3,
        # Hold for this many trading days, then exit.
        "holding_period_days": 90,
        # Score emitted when in-window. Binary signal — there's no
        # "stronger" or "weaker" spin-off in this model.
        "in_window_score": 1.0,
        # If True, scale the score down linearly across the holding
        # window (1.0 at entry → 0.0 at exit). False = constant score
        # throughout the window. Default False (matches Greenblatt
        # "hold for the full period" framing).
        "linear_decay": False,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)
        # Lazy-loaded detector output, cached per-instance.
        self._events_by_child: Dict[str, SpinoffEvent] | None = None

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    def _load_events(self) -> Dict[str, SpinoffEvent]:
        if self._events_by_child is None:
            events = get_events()
            self._events_by_child = events_by_child(events)
        return self._events_by_child

    def _ticker_signal(
        self,
        ticker: str,
        as_of: pd.Timestamp,
        events_by_child_map: Dict[str, SpinoffEvent],
    ) -> float:
        ev = events_by_child_map.get(ticker.upper())
        if ev is None:
            return 0.0

        ts = pd.Timestamp(as_of)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts = ts.normalize()

        # No look-ahead: ignore events that haven't happened yet.
        if ev.distribution_date > ts:
            return 0.0

        # Trading-day distance via np.busday_count (matches the
        # convention used by dividend_initiation_drift_v1 +
        # earnings_vol_edge_v1).
        try:
            days = int(np.busday_count(
                ev.distribution_date.date(), ts.date(),
            ))
        except Exception:
            return 0.0

        entry_offset = int(self.params.get("entry_offset_days", 3))
        holding_period = int(self.params.get("holding_period_days", 90))
        in_window_score = float(self.params.get("in_window_score", 1.0))
        linear_decay = bool(self.params.get("linear_decay", False))

        # Day 0 = distribution_date. Edge fires from entry_offset
        # through entry_offset + holding_period inclusive.
        window_start = entry_offset
        window_end = entry_offset + holding_period

        if days < window_start or days > window_end:
            return 0.0

        if not linear_decay:
            return float(in_window_score)

        # Linear decay from 1.0 at entry to 0.0 at window_end.
        window_size = max(1, window_end - window_start)
        progress = (days - window_start) / window_size
        decay = max(0.0, 1.0 - progress)
        return float(in_window_score * decay)

    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], as_of: pd.Timestamp,
    ) -> Dict[str, float]:
        events_by_child_map = self._load_events()
        if not events_by_child_map:
            return {}
        out: Dict[str, float] = {}
        for ticker in data_map:
            score = self._ticker_signal(ticker, as_of, events_by_child_map)
            if score != 0.0:
                out[ticker] = score
        return out


# ---------------------------------------------------------------------------
# Auto-register on import. status='paused' tier='feature' — gauntlet
# validation required before activation. Matches dividend_initiation_drift_v1
# + calendar_anomaly_v1 convention.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=SpinoffReversionEdge.EDGE_ID,
        category=SpinoffReversionEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(SpinoffReversionEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
