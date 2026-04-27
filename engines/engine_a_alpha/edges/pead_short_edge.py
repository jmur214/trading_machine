"""
engines/engine_a_alpha/edges/pead_short_edge.py
================================================
Post-Earnings Announcement Drift — short side.

The same academic mechanism as pead_v1 but on negative surprises: after a
negative EPS surprise, stocks continue drifting downward as the market
gradually processes the bad news. The short-side effect is real but has a
somewhat faster reversal dynamic than the long side (~45–60 trading days
vs 60–90) — institutional covering tends to cap the drift sooner.

References: Bernard & Thomas (1989) both sides; Livnat & Mendenhall (2006)
for the short-side decay asymmetry; Hirshleifer, Lim & Teoh (2009) for
short-side PEAD persistence.

Signal convention: emits negative scores (short signal). Compatible with
the signed aggregation in SignalProcessor — these subtract from long-only
edges in the weighted mean.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("PEADShortEdge")


class PEADShortEdge(EdgeBase):
    EDGE_ID = "pead_short_v1"
    CATEGORY = "event_driven"
    DESCRIPTION = (
        "Post-Earnings Announcement Drift (short side): short signal "
        "proportional to negative EPS surprise %, held with linear decay "
        "over ~45 trading days post-announcement."
    )

    DEFAULT_PARAMS = {
        # Shorter hold window than long side — short PEAD reverts faster
        # as institutional short-covering kicks in (~45 trading days).
        "hold_calendar_days": 63,
        "min_surprise_pct": 0.05,
        "surprise_clip_pct": 0.30,
        # Max short-signal magnitude. Slightly smaller than long side —
        # short-side PEAD has smaller effect size in most studies.
        "short_score_max": 0.30,
        "decay_mode": "linear",
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._calendars: dict[str, pd.DataFrame] = {}
        self._calendars_loaded = False

    @classmethod
    def sample_params(cls):
        return dict(cls.DEFAULT_PARAMS)

    def _load_calendars(self, symbols: list[str]) -> None:
        if self._calendars_loaded:
            return
        self._calendars_loaded = True

        try:
            from engines.data_manager import EarningsDataManager
        except ImportError:
            try:
                from engines.data_manager.earnings_data import EarningsDataManager
            except Exception as exc:
                log.debug(f"EarningsDataManager import failed ({exc}); abstaining")
                return
        except Exception as exc:
            log.debug(f"EarningsDataManager import failed ({exc}); abstaining")
            return

        try:
            mgr = EarningsDataManager()
        except Exception as exc:
            log.debug(f"EarningsDataManager init failed ({exc}); abstaining")
            return

        for sym in symbols:
            try:
                df = mgr.load_cached(sym)
            except Exception as exc:
                log.debug(f"earnings cache load failed for {sym} ({exc})")
                continue
            if df is None or df.empty:
                continue
            try:
                idx = pd.to_datetime(df.index)
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                df = df.copy()
                df.index = idx
                df = df.sort_index()
            except Exception:
                continue
            self._calendars[sym] = df

    def _compute_one_signal(self, sym: str, now: pd.Timestamp) -> float:
        cal = self._calendars.get(sym)
        if cal is None or cal.empty:
            return 0.0

        hold_days = int(self.params.get("hold_calendar_days", 63))
        min_surprise = float(self.params.get("min_surprise_pct", 0.05))
        clip_surprise = float(self.params.get("surprise_clip_pct", 0.30))
        short_score_max = float(self.params.get("short_score_max", 0.30))

        try:
            ts = pd.Timestamp(now)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return 0.0

        window_start = ts - pd.Timedelta(days=hold_days)
        recent = cal.loc[(cal.index >= window_start) & (cal.index <= ts)]
        if recent.empty:
            return 0.0

        last = recent.iloc[-1]
        last_date = recent.index[-1]
        surprise = last.get("eps_surprise_pct", np.nan)
        if pd.isna(surprise):
            return 0.0
        surprise = float(surprise)

        # Short side: only fire on negative surprises
        if surprise >= 0:
            return 0.0
        if abs(surprise) < min_surprise:
            return 0.0

        capped = min(abs(surprise), clip_surprise)
        denom = max(1e-9, clip_surprise - min_surprise)
        magnitude_factor = (capped - min_surprise) / denom
        magnitude_factor = max(0.0, min(1.0, magnitude_factor))

        days_since = (ts - last_date).days
        time_factor = max(0.0, 1.0 - (days_since / max(1, hold_days)))

        # Negative signal (short direction)
        return -short_score_max * magnitude_factor * time_factor

    def compute_signals(self, data_map, now):
        symbols = list(data_map.keys())
        self._load_calendars(symbols)

        if not self._calendars:
            return {sym: 0.0 for sym in symbols}

        return {sym: self._compute_one_signal(sym, now) for sym in symbols}


from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=PEADShortEdge.EDGE_ID,
        category=PEADShortEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(PEADShortEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
