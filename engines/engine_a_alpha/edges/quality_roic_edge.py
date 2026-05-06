"""quality_roic_edge.py — Quality factor: Return On Invested Capital proxy.

Fires LONG when a ticker's ROIC proxy is in the top quintile of the
present-data subset.

Why this factor
---------------
ROIC (after-tax operating profit / invested capital) is the cleanest single
measure of how well a business converts deployed capital into earnings. Buffett's
operational test in ten words. Empirically robust as a quality factor across
the academic literature (Asness-Frazzini-Pedersen "Quality Minus Junk" 2019).

Mechanism
---------
    NOPAT       = TTM_OperatingIncome * (1 - tax_rate)        [tax_rate = 0.21]
    invested_cap = total_equity[latest] + long_term_debt[latest]
    roic        = NOPAT / invested_cap                         [if invested_cap > 0]

Same parameter convention used by the path_c compounder. Long-term debt may be
None for debt-free firms; we treat None as 0 (academic-standard for quality
work — debt-free firms aren't penalized).

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


# US corporate effective tax rate ≈ 21%. Same constant as path_c_synthetic_compounder.
_ROIC_TAX_RATE = 0.21


class QualityROICEdge(EdgeBase):
    EDGE_ID = "quality_roic_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Quality factor: cross-sectional top-quintile by ROIC proxy "
        "(NOPAT / (equity + LT_debt)). Long-only. PIT-correct."
    )

    DEFAULT_PARAMS = {
        "top_quantile": 0.20,
        "long_score": 1.0,
        "min_universe": 30,
        "tax_rate": _ROIC_TAX_RATE,
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
        tax_rate = float(self.params.get("tax_rate", _ROIC_TAX_RATE))

        def _score(panel: pd.DataFrame, ticker: str, asof_ts: pd.Timestamp,
                   df: Optional[pd.DataFrame]) -> Optional[float]:
            ttm_oi = ttm_sum(panel, ticker, asof_ts, "operating_income")
            equity = latest_value(panel, ticker, asof_ts, "total_equity")
            lt_debt = latest_value(panel, ticker, asof_ts, "long_term_debt")
            if ttm_oi is None or equity is None:
                return None

            # Drop distressed firms (non-positive equity). Without this guard,
            # the silent zero-equity fallback would compute ROIC = NOPAT /
            # lt_debt — which can score a bankrupt-leverage firm into the top
            # quintile, the OPPOSITE of the academic Quality factor
            # (Asness-Frazzini-Pedersen "Quality Minus Junk" 2019). Mirrors
            # the explicit drop in value_book_to_market_edge.py:76-78.
            if equity <= 0:
                return None

            invested_capital = equity + \
                               (lt_debt if (lt_debt is not None and lt_debt > 0) else 0.0)
            if invested_capital <= 0:
                return None

            nopat = ttm_oi * (1.0 - tax_rate)
            return nopat / invested_capital

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
        edge_id=QualityROICEdge.EDGE_ID,
        category=QualityROICEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(QualityROICEdge.DEFAULT_PARAMS),
        status="active",
    ))
except (FileNotFoundError, PermissionError, OSError) as _exc:
    _REG_LOG.warning(
        "%s auto-register skipped: %s: %s",
        QualityROICEdge.EDGE_ID, type(_exc).__name__, _exc,
    )
