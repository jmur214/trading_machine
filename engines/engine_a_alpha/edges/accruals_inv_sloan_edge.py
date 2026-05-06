"""accruals_inv_sloan_edge.py — Earnings-quality factor: low Sloan accruals.

Fires LONG when a ticker's negated Sloan accruals (-sloan_accruals) is in the
top quintile of the present-data subset — i.e. firms with the LOWEST accruals,
which historically deliver higher forward returns (Sloan 1996).

Why this factor
---------------
Sloan (1996, "Do Stock Prices Fully Reflect Information in Accruals and Cash
Flows About Future Earnings?") documented that the cash-flow component of
earnings is more persistent than the accrual component. Firms with high
accruals (NI > OCF) tend to underperform; firms with low accruals
(NI ≈ OCF, i.e. "high earnings quality") tend to outperform. 30+ years of
out-of-sample replication, including post-publication.

Mechanism
---------
    sloan_accruals = (net_income - operating_cash_flow) / total_assets

We take the NEGATED value so that LOW raw accruals (= high earnings quality
= attractive) sort to the TOP of the cross-section. Top-quintile of the
inverted score gets long_score; everyone else 0.

The SimFin adapter precomputes ``sloan_accruals`` at panel build time, so this
edge is a thin wrapper that just inverts and ranks.

Universe coverage
-----------------
~80 of 109 prod tickers covered by SimFin FREE; top quintile = ~16 names.
``min_universe=30`` abstention floor.

PIT caveat
----------
Accruals are sensitive to restatements. SimFin's `Restated Date` field is
later than `Publish Date` for some filings; the panel adapter joins on
Publish Date for PIT correctness, but the underlying figures themselves are
"latest restated" (per SimFin docs). This is a small but real PIT-bias.
Documented in `docs/Core/Ideas_Pipeline/ws_f_fundamentals_data_scoping.md`.

Long-only this round. Note: the SHORT side of Sloan (high-accruals firms)
is the more profitable leg historically — adding it later is high-priority
once a borrow-cost model exists.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase
from ._fundamentals_helpers import (
    latest_value,
    top_quintile_long_signals,
)


class AccrualsInvSloanEdge(EdgeBase):
    EDGE_ID = "accruals_inv_sloan_v1"
    CATEGORY = "fundamental"
    DESCRIPTION = (
        "Earnings-quality factor: cross-sectional top-quintile by "
        "-sloan_accruals (i.e. lowest accrual firms). Long-only."
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
            sloan = latest_value(panel, ticker, asof_ts, "sloan_accruals")
            if sloan is None:
                return None
            # Negate so low-accruals firms (the attractive ones) sort to the top
            return -sloan

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
        edge_id=AccrualsInvSloanEdge.EDGE_ID,
        category=AccrualsInvSloanEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(AccrualsInvSloanEdge.DEFAULT_PARAMS),
        status="active",
    ))
except (FileNotFoundError, PermissionError, OSError) as _exc:
    _REG_LOG.warning(
        "%s auto-register skipped: %s: %s",
        AccrualsInvSloanEdge.EDGE_ID, type(_exc).__name__, _exc,
    )
