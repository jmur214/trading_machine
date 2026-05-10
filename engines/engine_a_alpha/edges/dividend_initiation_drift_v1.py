"""
engines/engine_a_alpha/edges/dividend_initiation_drift_v1.py
=============================================================

Dividend-initiation drift edge.

Mechanism (Asem 2009; Michaely-Thaler-Womack 1995 for the broader
initiation literature):
- A company that INITIATES a dividend (i.e., pays its first dividend
  after a long gap or ever) is sending a strong management-confidence
  signal: stable cash flow, predictable earnings, willingness to commit
  to a recurring obligation. The market underreacts; post-announcement
  drift over ~60 trading days is documented.
- Cleanest sub-event in the corporate-action literature. Increases /
  decreases / consistent payouts have weaker / noisier drift; only
  INITIATIONS qualify here.

Mechanics:
1. For each ticker, fetch full dividend history via yfinance (cached
   in-process per-ticker for the run).
2. Identify INITIATION events: a dividend payment that is either the
   ticker's FIRST EVER dividend OR follows a gap of ≥ `gap_years`
   without any prior dividend (default 3 years).
3. At each bar `t`, find the most recent initiation event ≤ `t`.
4. If the event is in the [1, drift_window_days] window prior to `t`,
   emit a long signal with confidence linearly decaying from 1.0 at
   day 1 to 0.0 at day drift_window_days. Skip day 0 (announcement-day
   volatility cluster).
5. Else: abstain (0.0).

Status on registration: paused / feature, lifecycle-gauntlet validates
before deployment. Soft-pause 0.25× weighting applies.

T-001 tz-regression discipline: yfinance returns tz-aware datetime
indexes. We strip tz at the cache-write boundary so all downstream
comparisons against tz-naive `as_of` timestamps work. Bug class
surfaced 2026-05-08; do not remove the tz_localize(None) calls.

DATA-COVERAGE NOTE:
- yfinance dividends are reasonably complete for US large-caps from
  ~1985 onward. Coverage is thinner for international / micro-caps.
- yfinance does NOT expose buyback announcements; sibling edge
  `buyback_drift_v1` is therefore SCOPED OUT of T-018 — see audit doc
  `docs/Audit/buyback_dividend_drift_edges_2026_05_09.md`.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

logger = logging.getLogger("DividendInitiationDriftEdge")


class DividendInitiationDriftEdge(EdgeBase):
    EDGE_ID = "dividend_initiation_drift_v1"
    CATEGORY = "event_driven_drift"
    DESCRIPTION = (
        "Long signal in the 60-day post-announcement window after a "
        "dividend INITIATION (first dividend ever, or first after "
        "≥3-year gap). Asem 2009 + initiation-drift literature. "
        "Linear confidence decay from 1.0 at day 1 to 0.0 at day 60. "
        "Long-only."
    )

    DEFAULT_PARAMS = {
        # Gap (in years) defining "initiation" vs "ongoing dividend".
        # 3 years matches the cleanest sub-event definition in Asem 2009.
        "initiation_gap_years": 3,
        # Drift window: trading-day count from announcement.
        "drift_window_days": 60,
        # Skip the announcement day itself (vol cluster).
        "skip_first_day": True,
        # Maximum signal magnitude. Bounded so this edge is a contributor,
        # not a dominator.
        "long_score_max": 0.5,
    }

    # Class-level cache keyed by ticker. Per the earnings_vol_edge_v1
    # convention — lazy-fetch + in-process cache. Exposed for testing
    # so tests can inject synthetic dividend series without hitting
    # yfinance.
    _dividends_cache: Dict[str, pd.Series] = {}

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    def _get_dividends(self, ticker: str) -> Optional[pd.Series]:
        """Return tz-naive Timestamp index of historical ex-dividend dates
        for `ticker`, OR None if data unavailable.

        Lazy yfinance fetch with class-level cache. Cache miss + network
        failure returns None; the edge then abstains for that ticker.
        T-001 invariant: any tz-aware index returned by yfinance is
        coerced to tz-naive at the cache-write boundary.
        """
        if ticker in self._dividends_cache:
            cached = self._dividends_cache[ticker]
            return cached if not cached.empty else None

        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            divs = tk.dividends  # Series indexed by date, values = dividend amounts
            if divs is None or divs.empty:
                self._dividends_cache[ticker] = pd.Series(dtype=float)
                return None
            idx = divs.index
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            divs = pd.Series(divs.values, index=pd.DatetimeIndex(idx).normalize())
            divs = divs.sort_index()
            divs = divs[~divs.index.duplicated(keep="first")]
            self._dividends_cache[ticker] = divs
            return divs
        except Exception as e:
            logger.debug(f"Could not fetch dividends for {ticker}: {e}")
            self._dividends_cache[ticker] = pd.Series(dtype=float)
            return None

    def _initiation_dates(self, divs: pd.Series, gap_years: int) -> List[pd.Timestamp]:
        """Identify INITIATION events in a dividend history.

        An initiation is:
          (a) The very first dividend in `divs`, OR
          (b) Any dividend that occurs ≥ `gap_years` years after the
              prior dividend in the series.

        Returns the list of initiation Timestamps (tz-naive, sorted).
        """
        if divs is None or divs.empty:
            return []
        idx = pd.DatetimeIndex(divs.index).sort_values()
        if len(idx) == 0:
            return []
        out = [idx[0]]  # first dividend is always an initiation
        gap_days = gap_years * 365
        for i in range(1, len(idx)):
            if (idx[i] - idx[i - 1]).days >= gap_days:
                out.append(idx[i])
        return out

    def _ticker_signal(
        self,
        ticker: str,
        as_of: pd.Timestamp,
        gap_years: int,
        drift_window_days: int,
        skip_first_day: bool,
        long_score_max: float,
    ) -> float:
        divs = self._get_dividends(ticker)
        if divs is None or divs.empty:
            return 0.0

        ts = pd.Timestamp(as_of)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)

        initiations = self._initiation_dates(divs, gap_years)
        if not initiations:
            return 0.0

        # Find the most recent initiation ≤ ts
        past = [d for d in initiations if d <= ts]
        if not past:
            return 0.0
        last_init = past[-1]

        # Trading-day distance — use np.busday_count for trading days
        # (Mon-Fri); not holiday-adjusted but matches earnings_vol_edge
        # convention.
        try:
            days = int(np.busday_count(last_init.date(), ts.date()))
        except Exception:
            return 0.0

        if skip_first_day and days < 1:
            return 0.0
        if days < 1 or days > drift_window_days:
            return 0.0

        # Linear decay: 1.0 at day 1 → 0.0 at day drift_window_days
        decay = max(0.0, 1.0 - (days - 1) / max(1, drift_window_days - 1))
        return float(long_score_max * decay)

    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> Dict[str, float]:
        gap_years = int(self.params.get("initiation_gap_years", 3))
        drift_window_days = int(self.params.get("drift_window_days", 60))
        skip_first_day = bool(self.params.get("skip_first_day", True))
        long_score_max = float(self.params.get("long_score_max", 0.5))

        out: Dict[str, float] = {}
        for ticker in data_map:
            out[ticker] = self._ticker_signal(
                ticker, as_of, gap_years, drift_window_days,
                skip_first_day, long_score_max,
            )
        return out


# ---------------------------------------------------------------------------
# Auto-register on import. status='paused' tier='feature' — same as
# T-016 and the calendar_anomaly_v1 / cot_positioning_v1 precedent.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=DividendInitiationDriftEdge.EDGE_ID,
        category=DividendInitiationDriftEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(DividendInitiationDriftEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
