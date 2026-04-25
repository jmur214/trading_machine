"""
engines/engine_a_alpha/edges/momentum_factor_edge.py
=====================================================
Cross-sectional 12m-1m momentum factor edge.

The 12-month minus 1-month momentum signal (Jegadeesh-Titman 1993, replicated
in dozens of subsequent studies including Asness/Moskowitz/Pedersen 2013) is
the most consistently documented single-factor alpha in equity markets across
geographies and decades. The 1-month exclusion avoids contamination from
short-term mean-reversion (Lehmann 1990).

Mechanism: each bar, rank the universe by 12-1 momentum. Emit a long signal
for tickers in the top quantile (default top 20%). All other tickers emit 0.
Long-only on first iteration — adding the short side requires borrow-cost
modeling that isn't worth complicating a first proof-of-concept with.

Academic-standard parameters (252 / 21 / top quintile) are used as defaults
to avoid in-sample tuning artifacts. Don't tune these to fit a backtest
window — use the standard values, walk-forward verify, accept what you find.

Why this edge is worth adding to a system dominated by classical-technical
edges (SMA crossover, ATR breakout, RSI mean reversion): factor strategies
operate at a different timescale (monthly-stable rather than daily-flap),
search a different signal (cross-sectional rank rather than per-ticker pattern),
and have ~40 years of academic and practitioner validation. They're crowded,
but not as crowded as daily technical patterns.
"""
from __future__ import annotations

import pandas as pd

from ..edge_base import EdgeBase


class MomentumFactorEdge(EdgeBase):
    EDGE_ID = "momentum_factor_v1"
    CATEGORY = "factor"
    DESCRIPTION = (
        "Cross-sectional 12m-1m momentum factor; long top quintile of "
        "universe by trailing 12-month return excluding the most recent month."
    )

    DEFAULT_PARAMS = {
        # Academic-standard params (Jegadeesh-Titman 12-1, top quintile).
        # Don't tune these per backtest — that's overfitting.
        "long_lookback": 252,    # ~12 months in trading days
        "short_lookback": 21,    # ~1 month (the excluded recent window)
        "top_quantile": 0.20,    # long the top 20% of universe by signal
        "long_score": 1.0,       # signal magnitude for top names (0..1)
        "min_universe": 5,       # need at least N tickers to rank meaningfully
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls):
        """Used by Discovery's GA / mutation. Returns the academic defaults
        — this edge is NOT supposed to be hyperparameter-tuned, so the
        sampler returns the canonical values rather than random draws."""
        return dict(cls.DEFAULT_PARAMS)

    def compute_signals(self, data_map, now):
        long_lb = int(self.params.get("long_lookback", 252))
        short_lb = int(self.params.get("short_lookback", 21))
        top_q = float(self.params.get("top_quantile", 0.20))
        long_score = float(self.params.get("long_score", 1.0))
        min_universe = int(self.params.get("min_universe", 5))

        if long_lb <= short_lb:
            # Misconfigured — would compute the wrong signal silently.
            return {t: 0.0 for t in data_map}

        # Compute 12-1 momentum per ticker. Excludes tickers without enough
        # history. We use simple returns (not log) — the difference at this
        # timescale is negligible and simple returns rank-order identically.
        moms: dict[str, float] = {}
        for ticker, df in data_map.items():
            if df is None or "Close" not in df.columns:
                continue
            if len(df) < long_lb + 2:
                continue
            close = df["Close"].astype(float)
            try:
                p_now = float(close.iloc[-1])
                p_long_ago = float(close.iloc[-long_lb])
                p_short_ago = float(close.iloc[-short_lb])
                if p_long_ago <= 0 or p_short_ago <= 0 or p_now <= 0:
                    continue
                ret_long = (p_now / p_long_ago) - 1.0
                ret_short = (p_now / p_short_ago) - 1.0
                mom_12_1 = ret_long - ret_short
                if pd.isna(mom_12_1):
                    continue
                moms[ticker] = float(mom_12_1)
            except Exception:
                continue

        # Universe needs to be large enough for a quantile-based ranking to be
        # meaningful. Below the threshold, abstain (emit zeros for everyone).
        if len(moms) < min_universe:
            return {t: 0.0 for t in data_map}

        # Sort descending — highest momentum first
        sorted_tickers = sorted(moms.keys(), key=lambda t: moms[t], reverse=True)
        n_long = max(1, int(round(len(sorted_tickers) * top_q)))
        top_set = set(sorted_tickers[:n_long])

        # Top quantile gets long signal, everyone else (including tickers
        # without enough data) gets 0. Important: emit a key for every ticker
        # in data_map so the signal_processor's aggregation is well-defined.
        scores: dict[str, float] = {}
        for ticker in data_map:
            scores[ticker] = long_score if ticker in top_set else 0.0
        return scores


# Register on import — same pattern as the other edges
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=MomentumFactorEdge.EDGE_ID,
        category=MomentumFactorEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(MomentumFactorEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    # Best-effort registration; do not break import if registry is unwritable.
    pass
