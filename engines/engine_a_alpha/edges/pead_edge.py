"""
engines/engine_a_alpha/edges/pead_edge.py
==========================================
Post-Earnings Announcement Drift (PEAD) edge.

PEAD is the most-replicated single-factor alpha in the academic equity
literature. After a positive earnings surprise, stocks tend to drift
upward over the following 2-3 months — the market underreacts to new
fundamental information and the price adjustment is gradual. The drift
is largest when the surprise itself is large (>5% standardized
unexpected earnings).

Original references: Bernard & Thomas (1989), Foster/Olsen/Shevlin
(1984). Replicated dozens of times across geographies and decades. The
factor has decayed somewhat as quant funds have professionalized but
remains net-positive in most studies.

Mechanism: per ticker, per bar, check whether an earnings announcement
has happened in the trailing window (default 84 calendar days ≈ 60
trading days). If yes, emit a signal proportional to the surprise size,
decaying linearly from full strength at announcement day to zero at
window end.

Long-only initially. The short side requires borrow-cost modeling that
isn't worth complicating a first proof-of-concept with — and the
academic literature shows the long side captures most of the alpha
anyway (Bernard-Thomas decile-1 vs decile-10 spreads are heavily
asymmetric in favor of the long side).

Cache behavior: reads earnings data via `EarningsDataManager.load_cached`.
If the cache is empty (no FINNHUB_API_KEY configured, or fresh clone),
the edge emits zeros for every ticker — graceful degradation, no crash.
This lets the edge ship and be active in code without requiring the
Finnhub key to be configured for backtests to run.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("PEADEdge")


class PEADEdge(EdgeBase):
    EDGE_ID = "pead_v1"
    CATEGORY = "event_driven"
    DESCRIPTION = (
        "Post-Earnings Announcement Drift: long signal proportional to "
        "EPS surprise %, held with linear decay over ~60 trading days "
        "post-announcement. Long-only."
    )

    DEFAULT_PARAMS = {
        # ~60 trading days expressed as calendar days (60 * 7/5 = 84).
        "hold_calendar_days": 84,
        # Minimum surprise magnitude (absolute %) to act on. Below this,
        # surprise data is too noisy. Academic standard is in the 2-5% range;
        # 5% is conservative and avoids most data-quality artifacts.
        "min_surprise_pct": 0.05,
        # Cap surprise magnitude at this value to avoid letting one
        # extreme print dominate (e.g., NVDA's 600% Q4 2023 surprises
        # would overwhelm the rest of the universe). 0.30 = 30% surprise
        # mapped to full signal magnitude; anything beyond is clipped.
        "surprise_clip_pct": 0.30,
        # Maximum signal magnitude. Bounded so PEAD doesn't dominate
        # per-ticker technical signals.
        "long_score_max": 0.4,
        # Decay shape: linear from 1.0 at announcement to 0.0 at end.
        # Could swap to exponential or step in v2 if walk-forward suggests.
        "decay_mode": "linear",
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._calendars: dict[str, pd.DataFrame] = {}
        self._calendars_loaded = False

    @classmethod
    def sample_params(cls):
        """Used by Engine D's GA / mutation. Returns the canonical defaults
        — this edge is not supposed to be hyperparameter-tuned (academic
        signal with established parameters). Tuning the threshold or
        window to fit a backtest is the textbook overfitting trap."""
        return dict(cls.DEFAULT_PARAMS)

    def _load_calendars(self, symbols: list[str]) -> None:
        """Lazy-load each ticker's earnings calendar from the parquet cache.
        Called once per edge instance (per backtest run). Tickers with no
        cached data are simply absent from `self._calendars` — they'll
        score 0 in compute_signals."""
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
            # Ensure index is timezone-naive Timestamp for deterministic
            # comparison against the bar's `now` parameter.
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

        if not self._calendars:
            log.debug(
                "earnings cache is empty for all tickers in universe; "
                "PEAD edge abstaining. Populate cache via "
                "`EarningsDataManager().fetch_universe(<tickers>)` after "
                "FINNHUB_API_KEY is set in .env."
            )

    def _compute_one_signal(self, sym: str, now: pd.Timestamp) -> float:
        """Return signal magnitude for one ticker at one timestamp.
        Zero if no recent qualifying announcement."""
        cal = self._calendars.get(sym)
        if cal is None or cal.empty:
            return 0.0

        hold_days = int(self.params.get("hold_calendar_days", 84))
        min_surprise = float(self.params.get("min_surprise_pct", 0.05))
        clip_surprise = float(self.params.get("surprise_clip_pct", 0.30))
        long_score_max = float(self.params.get("long_score_max", 0.4))

        # Most recent announcement at or before `now`
        try:
            ts = pd.Timestamp(now)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return 0.0

        # Look at announcements within the trailing hold-window
        window_start = ts - pd.Timedelta(days=hold_days)
        recent = cal.loc[(cal.index >= window_start) & (cal.index <= ts)]
        if recent.empty:
            return 0.0

        # Use the most recent announcement in the window
        last = recent.iloc[-1]
        last_date = recent.index[-1]
        surprise = last.get("eps_surprise_pct", np.nan)
        if pd.isna(surprise):
            return 0.0
        surprise = float(surprise)

        # Threshold check — too small means noise
        if abs(surprise) < min_surprise:
            return 0.0

        # Long-only: ignore negative surprises in v1
        if surprise <= 0:
            return 0.0

        # Clip extreme surprises so one print doesn't overwhelm the universe
        capped = min(surprise, clip_surprise)
        # Map capped surprise [min_surprise, clip_surprise] → [0, 1]
        denom = max(1e-9, clip_surprise - min_surprise)
        magnitude_factor = (capped - min_surprise) / denom
        magnitude_factor = max(0.0, min(1.0, magnitude_factor))

        # Time decay: linear from 1.0 at announcement to 0.0 at window end
        days_since = (ts - last_date).days
        time_factor = max(0.0, 1.0 - (days_since / max(1, hold_days)))

        return long_score_max * magnitude_factor * time_factor

    def compute_signals(self, data_map, now):
        symbols = list(data_map.keys())
        self._load_calendars(symbols)

        if not self._calendars:
            # Cache empty for the entire universe — abstain
            return {sym: 0.0 for sym in symbols}

        return {sym: self._compute_one_signal(sym, now) for sym in symbols}


# ---------------------------------------------------------------------------
# Auto-register on import. Safe post-2026-04-25 registry fix —
# `EdgeRegistry.ensure()` write-protects status on existing specs.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=PEADEdge.EDGE_ID,
        category=PEADEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(PEADEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
