"""accruals_inv_asset_growth_edge.py — Investment factor: low asset growth.

Fires LONG when a ticker's negated year-over-year asset growth
(-asset_growth) is in the top quintile of the present-data subset — i.e.
firms growing assets the LEAST, which historically deliver higher forward
returns (Cooper-Gulen-Schill 2008; Fama-French 5-factor "CMA" investment leg).

Why this factor
---------------
Cooper-Gulen-Schill (2008, "Asset Growth and the Cross-Section of Stock
Returns") documented that firms with high YoY total-asset growth dramatically
underperform low-growth firms. Mechanisms include over-investment, manager
empire-building, and dilution. Now standardized as the "CMA" (Conservative
Minus Aggressive) investment leg of the Fama-French 5-factor model
(Fama-French 2015).

Importantly, this factor is partly driven by the SHORT leg (high-growth-firm
underperformance), but the LONG leg (low-asset-growth firms) is meaningful
on its own and is what we deploy here.

Mechanism
---------
    asset_growth = (total_assets[t] - total_assets[t-4q]) / total_assets[t-4q]

The SimFin adapter precomputes this at panel build time. We negate so that
LOW asset growth (attractive) sorts to the TOP. Top-quintile of the inverted
score gets long_score; everyone else 0.

Universe coverage
-----------------
Asset growth requires 4 quarters of trailing data, so the first ~12 months
of any ticker's SimFin coverage are unusable. Effective ~80 of 109 prod
tickers; top quintile ~16 names. ``min_universe=30`` abstention floor.

Long-only this round.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase
from ._fundamentals_helpers import (
    latest_value,
    top_quintile_long_signals,
)


class AccrualsInvAssetGrowthEdge(EdgeBase):
    EDGE_ID = "accruals_inv_asset_growth_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Investment factor (Cooper-Gulen-Schill / Fama-French CMA): "
        "cross-sectional top-quintile by -asset_growth (i.e. firms with "
        "the lowest YoY total-asset growth). Long-only."
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
            ag = latest_value(panel, ticker, asof_ts, "asset_growth")
            if ag is None:
                return None
            return -ag

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
        edge_id=AccrualsInvAssetGrowthEdge.EDGE_ID,
        category=AccrualsInvAssetGrowthEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(AccrualsInvAssetGrowthEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
