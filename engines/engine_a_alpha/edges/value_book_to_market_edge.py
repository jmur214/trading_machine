"""value_book_to_market_edge.py — Value factor: book-to-market.

Fires LONG when a ticker's total_equity / market_cap is in the top quintile
of the present-data subset of the active universe.

Why this factor
---------------
Book-to-market (B/P) is the canonical Fama-French value factor, the second leg
of the original 3-factor model (Fama-French 1992). Used by every major systematic
value fund. Robust across geographies and decades despite well-documented secular
underperformance during the 2010s growth regime.

Mechanism
---------
    book_to_market = total_equity / market_cap

where ``market_cap = price[as_of] * shares_diluted[latest]``. PIT enforced
via SimFin ``publish_date``. Negative-equity tickers are dropped (B/P sign
flip would mislead the rank).

Top-quintile names get long_score; everyone else 0.

Universe coverage
-----------------
Same as `value_earnings_yield_edge`: ~80 of 109 prod tickers covered by
SimFin FREE; top quintile = ~16 names. ``min_universe=30`` abstention floor.

Long-only this round.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase
from ._fundamentals_helpers import (
    latest_close,
    latest_value,
    top_quintile_long_signals,
)


class ValueBookToMarketEdge(EdgeBase):
    EDGE_ID = "value_book_to_market_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Value factor: cross-sectional top-quintile by total_equity / market_cap. "
        "Long-only, negative-equity dropped. PIT-correct via SimFin publish_date."
    )

    DEFAULT_PARAMS = {
        "top_quantile": 0.20,
        "long_score": 1.0,
        "min_universe": 30,
    }

    def __init__(self, params: Optional[dict] = None):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)

    @classmethod
    def sample_params(cls) -> dict:
        return dict(cls.DEFAULT_PARAMS)

    def compute_signals(self, data_map, now):
        def _score(panel: pd.DataFrame, ticker: str, asof_ts: pd.Timestamp,
                   df: Optional[pd.DataFrame]) -> Optional[float]:
            equity = latest_value(panel, ticker, asof_ts, "total_equity")
            shares = latest_value(panel, ticker, asof_ts, "shares_diluted")
            px = latest_close(df)
            if equity is None or shares is None or px is None:
                return None
            if equity <= 0 or shares <= 0:
                # Negative-equity firms produce misleading signs for B/P
                return None
            market_cap = px * shares
            if market_cap <= 0:
                return None
            return equity / market_cap

        return top_quintile_long_signals(
            data_map, now, _score,
            top_quantile=float(self.params.get("top_quantile", 0.20)),
            long_score=float(self.params.get("long_score", 1.0)),
            min_universe=int(self.params.get("min_universe", 30)),
        )


from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=ValueBookToMarketEdge.EDGE_ID,
        category=ValueBookToMarketEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(ValueBookToMarketEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
