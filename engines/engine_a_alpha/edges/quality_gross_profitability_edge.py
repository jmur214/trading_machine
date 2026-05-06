"""quality_gross_profitability_edge.py — Quality factor: Novy-Marx gross profitability.

Fires LONG when a ticker's TTM_GrossProfit / total_assets is in the top
quintile of the present-data subset.

Why this factor
---------------
Novy-Marx (2013, "The Other Side of Value") identified gross-profitability
(GP/Assets) as a value-orthogonal factor that predicts cross-sectional returns
roughly as strongly as book-to-market. Now standard in factor portfolios
("Profitability" in Fama-French 5-factor, "Quality" in MSCI / Russell variants).
Has held up out-of-sample since publication despite extensive trading.

Mechanism
---------
    gross_profitability = TTM_GrossProfit / total_assets[latest]

Top-quintile names get long_score; everyone else 0.

Universe coverage
-----------------
~80 of 109 prod tickers covered by SimFin FREE. Top quintile = ~16 names.
``min_universe=30`` abstention floor.

Long-only this round.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase
from ._fundamentals_helpers import (
    latest_value,
    top_quintile_long_signals,
    ttm_sum,
)


class QualityGrossProfitabilityEdge(EdgeBase):
    EDGE_ID = "quality_gross_profitability_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Quality factor: cross-sectional top-quintile by Novy-Marx gross "
        "profitability (TTM_GrossProfit / total_assets). Long-only."
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
        # Per-instance basket-transition cache (Bug #4 fix 2026-05-06).
        self._basket_state: dict = {}

    @classmethod
    def sample_params(cls) -> dict:
        return dict(cls.DEFAULT_PARAMS)

    def compute_signals(self, data_map, now):
        def _score(panel: pd.DataFrame, ticker: str, asof_ts: pd.Timestamp,
                   df: Optional[pd.DataFrame]) -> Optional[float]:
            ttm_gp = ttm_sum(panel, ticker, asof_ts, "gross_profit")
            assets = latest_value(panel, ticker, asof_ts, "total_assets")
            if ttm_gp is None or assets is None or assets <= 0:
                return None
            return ttm_gp / assets

        return top_quintile_long_signals(
            data_map, now, _score,
            top_quantile=float(self.params.get("top_quantile", 0.20)),
            long_score=float(self.params.get("long_score", 1.0)),
            min_universe=int(self.params.get("min_universe", 30)),
            state=self._basket_state,
            edge_id=self.EDGE_ID,
        )


# Bug #3 fix 2026-05-06: narrow auto-register exception handling. See
# value_earnings_yield_edge.py for full rationale.
import logging  # noqa: E402

from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

_REG_LOG = logging.getLogger(__name__)

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=QualityGrossProfitabilityEdge.EDGE_ID,
        category=QualityGrossProfitabilityEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(QualityGrossProfitabilityEdge.DEFAULT_PARAMS),
        status="active",
    ))
except (FileNotFoundError, PermissionError, OSError) as _exc:
    _REG_LOG.warning(
        "%s auto-register skipped: %s: %s",
        QualityGrossProfitabilityEdge.EDGE_ID, type(_exc).__name__, _exc,
    )
