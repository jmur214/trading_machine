"""
engines/engine_a_alpha/edges/momentum_6_1_v1.py
================================================

6-month-minus-1-month cross-sectional momentum.

Mechanism: same shape as `momentum_12_1_v1` (Jegadeesh-Titman) but on a
shorter horizon. Computes cumulative return over the trailing ~126
trading days, excluding the most recent ~21 days (1-month skip to
remove short-term reversal contamination). Cross-sectionally ranks the
universe; long top quintile.

Why a 6-1 variant alongside 12-1:
- The short-medium horizon momentum factor is partially independent of
  the 12-1 factor — correlation typically 0.4-0.6 across literature
  samples, NOT 1.0. A 6-1 edge captures a faster regime-shift signal
  the 12-1 misses, and vice versa.
- Per dev-review-mandated edge-expansion track: avoid the value/accruals
  cluster's 0.6+ collinearity problem by deliberately picking edges
  whose factor exposures don't fully overlap.

Status on registration: paused / feature, lifecycle-gauntlet-validated
before deployment. Same soft-pause behavior as `momentum_12_1_v1`.
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("Momentum6_1Edge")


class Momentum6_1Edge(EdgeBase):
    EDGE_ID = "momentum_6_1_v1"
    CATEGORY = "cross_sectional_momentum"
    DESCRIPTION = (
        "6-month-minus-1-month cross-sectional momentum (Jegadeesh-Titman "
        "shorter-horizon variant). Long top quintile of universe by "
        "126-day-skip-21 return; abstain otherwise. Long-only first cut."
    )

    DEFAULT_PARAMS = {
        "lookback_days": 126,
        "skip_days": 21,
        "long_quantile": 0.80,
        "min_universe_size": 50,
        "long_score": 1.0,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    def _ticker_return(self, df: pd.DataFrame, lookback: int, skip: int) -> float:
        if df is None or "Close" not in df.columns:
            return float("nan")
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(close) < lookback + skip + 1:
            return float("nan")
        end = close.iloc[-(skip + 1)]
        start = close.iloc[-(lookback + skip + 1)]
        if not (np.isfinite(start) and np.isfinite(end)) or start <= 0:
            return float("nan")
        return float(end / start - 1.0)

    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp
    ) -> Dict[str, float]:
        lookback = int(self.params.get("lookback_days", 126))
        skip = int(self.params.get("skip_days", 21))
        long_q = float(self.params.get("long_quantile", 0.80))
        min_uni = int(self.params.get("min_universe_size", 50))
        long_score = float(self.params.get("long_score", 1.0))

        rets: Dict[str, float] = {}
        for ticker, df in data_map.items():
            r = self._ticker_return(df, lookback, skip)
            if np.isfinite(r):
                rets[ticker] = r

        if len(rets) < min_uni:
            return {ticker: 0.0 for ticker in data_map}

        ret_series = pd.Series(rets)
        threshold = float(ret_series.quantile(long_q))

        out: Dict[str, float] = {}
        for ticker in data_map:
            r = rets.get(ticker)
            if r is None:
                out[ticker] = 0.0
                continue
            out[ticker] = long_score if r >= threshold else 0.0
        return out


from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=Momentum6_1Edge.EDGE_ID,
        category=Momentum6_1Edge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(Momentum6_1Edge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
