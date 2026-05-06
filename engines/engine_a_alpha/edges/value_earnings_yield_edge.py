"""value_earnings_yield_edge.py — Value factor: market-cap earnings yield.

Fires LONG when a ticker's TTM-net-income / market_cap is in the top quintile
of the present-data subset of the active universe.

Why this factor
---------------
Earnings yield (E/P) is the inverse of P/E and is one of the original Fama-French
value primitives. Among large-cap-equity factors it has the longest paper trail
— Basu (1977), Fama-French (1992), Lakonishok-Shleifer-Vishny (1994). It pairs
naturally with the cross-sectional Path C composite where it is one of the six
V/Q/A primitives.

Mechanism
---------
For each ticker:
    earnings_yield_market = TTM_NetIncome / market_cap

where ``market_cap = price[as_of] * shares_diluted[latest]``. PIT enforced by
filtering the SimFin panel on ``publish_date <= as_of``.

Top-quintile names get long_score; everyone else 0.

Universe coverage
-----------------
SimFin FREE excludes ~25 of the 109-ticker prod universe (mostly financials).
Effective active universe ~80; top quintile ~16 names. ``min_universe=30`` is
the abstention floor — a 22-name post-financial-exclude universe in 2021-Q1
(early SimFin coverage gaps) won't fire signals.

Long-only this round; the short side requires borrow modeling not in scope.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase
from ._fundamentals_helpers import (
    latest_close,
    latest_value,
    top_quintile_long_signals,
    ttm_sum,
)


class ValueEarningsYieldEdge(EdgeBase):
    EDGE_ID = "value_earnings_yield_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Value factor: cross-sectional top-quintile by TTM_NetIncome / market_cap. "
        "Long-only. PIT-correct via SimFin publish_date."
    )

    DEFAULT_PARAMS = {
        "top_quantile": 0.20,    # academic-standard top quintile
        "long_score": 1.0,
        "min_universe": 30,      # abstain when fundamentals coverage drops below this
    }

    def __init__(self, params: Optional[dict] = None):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        # Per-instance basket-transition cache (Bug #4 fix 2026-05-06).
        # Threaded into top_quintile_long_signals so signals fire only
        # when a ticker crosses into / out of the top quintile, not every
        # day a sustained member sits in the basket.
        self._basket_state: dict = {}

    @classmethod
    def sample_params(cls) -> dict:
        return dict(cls.DEFAULT_PARAMS)

    def compute_signals(self, data_map, now):
        def _score(panel: pd.DataFrame, ticker: str, asof_ts: pd.Timestamp,
                   df: Optional[pd.DataFrame]) -> Optional[float]:
            ttm_ni = ttm_sum(panel, ticker, asof_ts, "net_income")
            shares = latest_value(panel, ticker, asof_ts, "shares_diluted")
            px = latest_close(df)
            if ttm_ni is None or shares is None or px is None:
                return None
            if shares <= 0:
                return None
            market_cap = px * shares
            if market_cap <= 0:
                return None
            return ttm_ni / market_cap

        return top_quintile_long_signals(
            data_map, now, _score,
            top_quantile=float(self.params.get("top_quantile", 0.20)),
            long_score=float(self.params.get("long_score", 1.0)),
            min_universe=int(self.params.get("min_universe", 30)),
            state=self._basket_state,
            edge_id=self.EDGE_ID,
        )


# ---------------------------------------------------------------------------
# Auto-register on import. Safe post-2026-04-25 — `EdgeRegistry.ensure()`
# write-protects status, so this won't stomp lifecycle decisions.
#
# Bug #3 fix 2026-05-06: narrowed from `except Exception: pass` to specific
# I/O errors. Programmer errors (AttributeError, NameError, ImportError,
# TypeError on a future EdgeSpec schema change) now propagate so the
# AlphaEngine never loads an edge whose registry spec failed to install.
# ---------------------------------------------------------------------------
import logging  # noqa: E402

from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

_REG_LOG = logging.getLogger(__name__)

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=ValueEarningsYieldEdge.EDGE_ID,
        category=ValueEarningsYieldEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(ValueEarningsYieldEdge.DEFAULT_PARAMS),
        status="active",
    ))
except (FileNotFoundError, PermissionError, OSError) as _exc:
    # Filesystem-level registry unavailable (e.g. test sandbox without
    # data/governor/). Degrade gracefully — the edge class is still
    # importable for unit tests that mock the registry.
    _REG_LOG.warning(
        "%s auto-register skipped: %s: %s",
        ValueEarningsYieldEdge.EDGE_ID, type(_exc).__name__, _exc,
    )
