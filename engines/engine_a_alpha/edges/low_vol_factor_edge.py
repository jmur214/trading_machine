"""
engines/engine_a_alpha/edges/low_vol_factor_edge.py
====================================================
Low-volatility factor edge (cross-sectional).

The low-volatility anomaly — that low-volatility stocks have historically
delivered higher risk-adjusted returns than high-volatility stocks,
despite CAPM predicting the opposite — is one of the most-replicated
factor anomalies in the academic literature. References include:

- Frazzini & Pedersen, "Betting Against Beta" (2014, JFE)
- Baker, Bradley, Wurgler, "Benchmarks as Limits to Arbitrage" (2011, FAJ)
- Blitz & van Vliet, "The Volatility Effect" (2007, JPM)

The factor's mechanism is debated (leverage constraints, lottery
preferences, asymmetric attention) but the empirical record is robust
across decades and geographies. Retail-accessible ETFs (USMV, SPLV)
deliver Sharpe ratios in the 0.7-1.0 range net of fees.

Mechanism: each bar, rank the universe by trailing 30-day realized
volatility (annualized). Emit a long signal for tickers in the bottom
quintile (lowest vol). Long-only.

Why low-vol pairs well with the existing edge stack here:
- The system's existing edges have implicit beta tilt (mega-cap tech,
  trending names → high-beta exposure). Low-vol is mechanically
  anti-correlated with that, providing genuine diversification.
- Low-vol is most additive during drawdowns — exactly when the system's
  current MDD is lowest (-9% on 109-ticker universe vs SPY -25%). Adding
  more drawdown protection to a system already winning on MDD compounds
  the relative-MDD advantage.
- Bottom-quintile of 109 tickers = ~22 names — wider than the failed
  `momentum_factor_v1`'s 8-name top-quintile, more statistically credible.

Long-only initially. Short side requires borrow-cost modeling that's
not worth complicating a first version with.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("LowVolFactorEdge")


class LowVolFactorEdge(EdgeBase):
    EDGE_ID = "low_vol_factor_v1"
    CATEGORY = "factor"
    DESCRIPTION = (
        "Cross-sectional low-volatility factor; long bottom-quintile of "
        "universe by trailing 30-day realized volatility."
    )

    DEFAULT_PARAMS = {
        # Trailing window for realized vol calc, in trading days.
        # 30 is the academic standard; shorter windows are noisier,
        # longer windows lag too much during regime transitions.
        "vol_lookback": 30,
        # Bottom quantile selected as long. 0.20 = bottom 20% (~22 of 109).
        # Don't tune this per backtest — academic-standard quintile.
        "bottom_quantile": 0.20,
        # Signal magnitude for selected names. Modest by design (regime tilt
        # blended with per-ticker technical signals via signal_processor's
        # weighted aggregation).
        "long_score": 1.0,
        # Need at least this many tickers with valid vol estimates for the
        # ranking to be meaningful. Below this, abstain.
        "min_universe": 10,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls):
        """Used by Engine D's GA / mutation. Returns canonical defaults —
        this edge is not supposed to be hyperparameter-tuned."""
        return dict(cls.DEFAULT_PARAMS)

    def compute_signals(self, data_map, now):
        lookback = int(self.params.get("vol_lookback", 30))
        bottom_q = float(self.params.get("bottom_quantile", 0.20))
        long_score = float(self.params.get("long_score", 1.0))
        min_universe = int(self.params.get("min_universe", 10))

        # Compute realized vol per ticker (annualized). Skip tickers without
        # enough history — the edges base contract is per-ticker scoring,
        # so missing tickers just don't enter the cross-sectional ranking.
        vols: dict[str, float] = {}
        for ticker, df in data_map.items():
            if df is None or "Close" not in df.columns:
                continue
            if len(df) < lookback + 2:
                continue
            close = df["Close"].astype(float).iloc[-(lookback + 1):]
            # Use log returns to handle big moves cleanly
            log_ret = np.log(close).diff().dropna()
            if len(log_ret) < 2 or log_ret.std() == 0:
                continue
            ann_vol = float(log_ret.std() * np.sqrt(252))
            if not np.isfinite(ann_vol):
                continue
            vols[ticker] = ann_vol

        if len(vols) < min_universe:
            # Universe too thin — abstain rather than rank a tiny set
            return {ticker: 0.0 for ticker in data_map}

        # Sort ascending — lowest vol first. Bottom-quintile (lowest-vol)
        # gets the long signal.
        sorted_tickers = sorted(vols.keys(), key=lambda t: vols[t])
        n_long = max(1, int(round(len(sorted_tickers) * bottom_q)))
        selected = set(sorted_tickers[:n_long])

        scores: dict[str, float] = {}
        for ticker in data_map:
            scores[ticker] = long_score if ticker in selected else 0.0
        return scores


# ---------------------------------------------------------------------------
# Auto-register on import. Safe post-2026-04-25 registry fix —
# `EdgeRegistry.ensure()` write-protects status on existing specs.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=LowVolFactorEdge.EDGE_ID,
        category=LowVolFactorEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(LowVolFactorEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
