"""
engines/engine_a_alpha/edges/short_term_reversal_v1.py
=======================================================

1-month cross-sectional reversal.

Mechanism (Lehmann 1990, Lo-MacKinlay 1990, Jegadeesh 1990):
- Tickers that outperformed the universe over the most recent ~21
  trading days (1 calendar month) tend to underperform in the
  subsequent month, and vice versa. Microstructure / overreaction /
  short-term inventory imbalances rebalance.
- Cross-sectional rank by trailing 21-day return; **short** the top
  decile (recent winners — predicted to mean-revert lower); **long**
  the bottom decile (recent losers — predicted to mean-revert higher).

Direction choice (per spec open question 3):
- The Lehmann original studies the LONG-LOSER direction more cleanly
  (absent borrow-cost / short-availability concerns). The short-winner
  side requires shortable-borrow modeling that doesn't ship in this
  edge. Both directions are returned here so the meta-learner can
  decide which to weight; the short side at production deploy time
  may need an additional shortable-name filter.

Why short-term reversal alongside 12-1 / 6-1 momentum:
- Counterweight by construction. 1-month reversal is anti-momentum on
  short horizons; pairing it with the 6-1 / 12-1 momentum edges
  produces a composite ensemble whose factor exposures partially
  cancel (the inverse of the value-cluster problem T-002 surfaced).
- The 1-month skip in 12-1 / 6-1 is not coincidental — it's there
  precisely BECAUSE 1-month reversal contaminates raw 12-month or
  6-month momentum. This edge surfaces the contamination as its own
  signal.

Status on registration: paused / feature.
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("ShortTermReversalEdge")


class ShortTermReversalEdge(EdgeBase):
    EDGE_ID = "short_term_reversal_v1"
    CATEGORY = "cross_sectional_reversal"
    DESCRIPTION = (
        "1-month cross-sectional reversal (Lehmann 1990 / Lo-MacKinlay). "
        "Short top decile of trailing-21-day return (recent winners "
        "predicted to mean-revert); long bottom decile (recent losers). "
        "Counterweight to 12-1 / 6-1 momentum edges by construction."
    )

    DEFAULT_PARAMS = {
        "lookback_days": 21,            # ~1 trading month
        "long_quantile": 0.10,          # bottom decile <= 0.10 → long losers
        "short_quantile": 0.90,         # top decile >= 0.90 → short winners
        "min_universe_size": 50,
        "long_score": 1.0,
        "short_score": -1.0,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    def _ticker_return(self, df: pd.DataFrame, lookback: int) -> float:
        """Trailing lookback-day cumulative return (no skip)."""
        if df is None or "Close" not in df.columns:
            return float("nan")
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(close) < lookback + 1:
            return float("nan")
        end = close.iloc[-1]
        start = close.iloc[-(lookback + 1)]
        if not (np.isfinite(start) and np.isfinite(end)) or start <= 0:
            return float("nan")
        return float(end / start - 1.0)

    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp
    ) -> Dict[str, float]:
        lookback = int(self.params.get("lookback_days", 21))
        long_q = float(self.params.get("long_quantile", 0.10))
        short_q = float(self.params.get("short_quantile", 0.90))
        min_uni = int(self.params.get("min_universe_size", 50))
        long_score = float(self.params.get("long_score", 1.0))
        short_score = float(self.params.get("short_score", -1.0))

        rets: Dict[str, float] = {}
        for ticker, df in data_map.items():
            r = self._ticker_return(df, lookback)
            if np.isfinite(r):
                rets[ticker] = r

        if len(rets) < min_uni:
            return {ticker: 0.0 for ticker in data_map}

        ret_series = pd.Series(rets)
        long_threshold = float(ret_series.quantile(long_q))
        short_threshold = float(ret_series.quantile(short_q))

        out: Dict[str, float] = {}
        for ticker in data_map:
            r = rets.get(ticker)
            if r is None:
                out[ticker] = 0.0
                continue
            if r <= long_threshold:
                out[ticker] = long_score
            elif r >= short_threshold:
                out[ticker] = short_score
            else:
                out[ticker] = 0.0
        return out


from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=ShortTermReversalEdge.EDGE_ID,
        category=ShortTermReversalEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(ShortTermReversalEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
