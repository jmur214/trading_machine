"""
engines/engine_a_alpha/edges/cot_positioning_edge.py
====================================================

COT positioning edge — contrarian signal off CFTC commercial-trader
extremes.

Mechanism (Cohen-Malloy-Pomorski 2014, Sanders-Boris-Manfredo 2004):
- "Commercial" futures traders are the producers/end-users who hedge
  underlying business exposure. When they're heavily SHORT, they're
  hedging an expected price decline (price often peaks/declines from
  here). When they're heavily LONG, they're hedging an expected price
  increase (price often bottoms/rises).
- Common-knowledge in commodities: "follow the smart money inversely."
  Effect is documented in CL/GLD/SI; weaker but present in soft
  commodities.

Signal:
- compute z-score of `cot_commercial_net_long` over rolling 52-week window
- z > +1.5 (commercials extreme long, hedging rally) → short tilt -0.5
- z < -1.5 (commercials extreme short, hedging selloff) → long tilt +0.5
- otherwise → 0 (abstain)

Universe:
- Restricted to the 12 ETFs in `core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET`
  (USO, UCO, GLD, IAU, SLV, UNG, TLT, IEF, DBA, CORN, SOYB, UUP). Other
  tickers receive 0.0 (no signal).

Data dependency:
- `core/feature_foundry/sources/cftc_cot.py` must have a fetcher
  configured (production: `scripts/refresh_foundry_sources.py`; tests:
  fixture fetcher). Without a fetcher, the feature returns None and
  this edge emits zero — no exceptions, no NaN.

Why this exists:
- The Foundry already ships `cftc_cot.py` source + `cot_commercial_net_long`
  feature. No edge consumed them. Orphaned data per the 2026-05-07 audit.
  This edge closes that loop.

Status on registration: starts paused, tier=feature so the lifecycle
gauntlet evaluates the edge before deploying real capital.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("CotPositioningEdge")


class CotPositioningEdge(EdgeBase):
    EDGE_ID = "cot_positioning_v1"
    CATEGORY = "macro_positioning"
    DESCRIPTION = (
        "Contrarian commercial-trader positioning signal from CFTC COT "
        "reports. Short when commercials are extreme long (heavy hedging "
        "of expected rally), long when commercials are extreme short. "
        "Restricted to the 12 ETFs with a futures-correlated mapping."
    )

    DEFAULT_PARAMS = {
        # Z-score window for normalizing commercial net-long ratio.
        "zscore_window_weeks": 52,
        # Z-score thresholds for entry. Wider → fewer, more confident bets.
        "z_long_threshold": -1.5,
        "z_short_threshold": 1.5,
        # Tilt magnitude — small enough that this edge is a tilter, not
        # a generator. Composes with the rest of the ensemble.
        "long_tilt": 0.5,
        "short_tilt": -0.5,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)
        # Per-ticker cached pandas Series of weekly commercial-net-long
        # ratios. Filled lazily on first compute_signals call so unit
        # tests that don't touch the COT path pay no I/O cost.
        self._cot_cache: Dict[str, Optional[pd.Series]] = {}

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    # ------------------------------------------------------------------
    def _load_cot_series_for_ticker(self, ticker: str, as_of: pd.Timestamp) -> Optional[pd.Series]:
        """Return the historical commercial-net-long series for `ticker`
        up to `as_of`, or None if data unavailable / ticker unmapped."""
        if ticker in self._cot_cache:
            return self._cot_cache[ticker]

        try:
            from core.feature_foundry.sources.cftc_cot import (
                TICKER_TO_MARKET, CFTCCommitmentsOfTraders,
            )
            from core.feature_foundry.data_source import get_source_registry
        except Exception as exc:
            log.debug(f"Foundry COT imports failed ({exc}); abstaining for {ticker}")
            self._cot_cache[ticker] = None
            return None

        market = TICKER_TO_MARKET.get(ticker)
        if market is None:
            self._cot_cache[ticker] = None
            return None

        src = get_source_registry().get("cftc_cot")
        if src is None or not isinstance(src, CFTCCommitmentsOfTraders):
            self._cot_cache[ticker] = None
            return None

        # Fetch enough history for the rolling z-score window plus one
        # buffer year. fetch_cached returns the cached parquet (no
        # network) when production refresh has run, NotImplementedError
        # when no fetcher is configured.
        weeks = int(self.params.get("zscore_window_weeks", 52))
        start_date = (as_of - pd.DateOffset(weeks=weeks + 4)).date()
        try:
            df = src.fetch_cached(start_date, as_of.date())
        except (NotImplementedError, ValueError, FileNotFoundError):
            self._cot_cache[ticker] = None
            return None

        if df is None or df.empty:
            self._cot_cache[ticker] = None
            return None

        sub = df[df["Market_and_Exchange_Names"] == market]
        if sub.empty:
            self._cot_cache[ticker] = None
            return None

        # Compute the (long - short) / OI ratio per report row, indexed
        # by report date. We keep all rows (no dedupe) — CFTC publishes
        # weekly so duplicates are rare.
        rep_dates = pd.to_datetime(sub["Report_Date_as_YYYY-MM-DD"])
        oi = sub["Open_Interest_All"].astype(float)
        long_p = sub["Comm_Positions_Long_All"].astype(float)
        short_p = sub["Comm_Positions_Short_All"].astype(float)
        # Avoid divide-by-zero — zero OI rows are dropped.
        valid = oi > 0
        ratio = pd.Series(
            ((long_p[valid] - short_p[valid]) / oi[valid]).values,
            index=rep_dates[valid],
        ).sort_index()
        self._cot_cache[ticker] = ratio
        return ratio

    # ------------------------------------------------------------------
    def _zscore_of_latest(self, series: pd.Series, as_of: pd.Timestamp) -> Optional[float]:
        """Z-score of the most-recent (≤ as_of) value within the rolling
        z-window, or None if insufficient history."""
        if series is None or series.empty:
            return None
        # Defensive normalization: index must be tz-naive Timestamps for
        # comparison with as_of.
        try:
            series = series.copy()
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                return None

        weeks = int(self.params.get("zscore_window_weeks", 52))
        cutoff_low = as_of - pd.DateOffset(weeks=weeks)
        window = series[(series.index >= cutoff_low) & (series.index <= as_of)]
        if len(window) < 12:  # need at least ~3 months of weekly reports
            return None
        latest = window.iloc[-1]
        mu = window.mean()
        sigma = window.std(ddof=0)
        if sigma <= 0 or not np.isfinite(sigma):
            return None
        return float((latest - mu) / sigma)

    # ------------------------------------------------------------------
    def compute_signals(self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
        out: Dict[str, float] = {}
        as_of = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tz else pd.Timestamp(now)
        z_long = float(self.params.get("z_long_threshold", -1.5))
        z_short = float(self.params.get("z_short_threshold", 1.5))
        long_tilt = float(self.params.get("long_tilt", 0.5))
        short_tilt = float(self.params.get("short_tilt", -0.5))

        for ticker in data_map:
            series = self._load_cot_series_for_ticker(ticker, as_of)
            if series is None or series.empty:
                out[ticker] = 0.0
                continue
            z = self._zscore_of_latest(series, as_of)
            if z is None:
                out[ticker] = 0.0
                continue
            # Contrarian: extreme long → short tilt; extreme short → long tilt
            if z >= z_short:
                out[ticker] = short_tilt
            elif z <= z_long:
                out[ticker] = long_tilt
            else:
                out[ticker] = 0.0
        return out


# ---------------------------------------------------------------------------
# Auto-register on import. Starts paused so the lifecycle gauntlet
# evaluates the edge before it deploys real capital. tier='feature' so
# the meta-learner consumes the signal rather than letting it trade
# directly until factor-decomposition diagnostics promote it.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=CotPositioningEdge.EDGE_ID,
        category=CotPositioningEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(CotPositioningEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
