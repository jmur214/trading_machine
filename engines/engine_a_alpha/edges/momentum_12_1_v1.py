"""
engines/engine_a_alpha/edges/momentum_12_1_v1.py
=================================================

Classical Jegadeesh-Titman 12-month-minus-1-month cross-sectional
momentum edge.

Mechanism (Jegadeesh-Titman 1993, Asness-Moskowitz-Pedersen 2013):
- For each ticker in the universe, compute cumulative return over the
  trailing ~252 trading days BUT EXCLUDING the most recent ~21 trading
  days (the 1-month skip removes microstructure / 1-month-reversal
  contamination — see `short_term_reversal_v1.py` for the counterweight).
- Cross-sectionally rank tickers at each date.
- Long top quintile (highest 12-1 momentum); abstain otherwise.
- The classical literature also shorts bottom quintile, but the
  long-side captures the bulk of the alpha empirically and avoids
  borrow-cost modeling for a first-pass edge. Short-side is left to
  Discovery / a later short-momentum-v1 ticket if warranted.

Why this edge exists:
- The Foundry already exposes `mom_12_1` as a Foundry feature
  (per T-006 vocabulary expansion), but no edge consumed it. This
  edge closes that loop. Vocabulary becomes a tradable signal.
- Connects to the existing `momentum_edge_v1` (10/40 MA crossover,
  per-ticker, no cross-sectional ranking) by adding the cross-sectional
  formulation that Jegadeesh-Titman is the canonical citation for.

Status on registration: starts at status='paused' tier='feature'. The
lifecycle gauntlet evaluates the edge before it deploys real capital.
Soft-pause weighting (0.25× per project_soft_pause_win_2026_04_24)
applies at runtime — paused edges trade at reduced size, not zero,
to preserve revival-gate evidence.
"""
from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("Momentum12_1Edge")


class Momentum12_1Edge(EdgeBase):
    EDGE_ID = "momentum_12_1_v1"
    CATEGORY = "cross_sectional_momentum"
    DESCRIPTION = (
        "Jegadeesh-Titman 12-month-minus-1-month cross-sectional momentum. "
        "Long top quintile of universe by 252-day-skip-21 return; "
        "abstain otherwise. Long-only first cut."
    )

    DEFAULT_PARAMS = {
        "lookback_days": 252,         # ~12 trading months
        "skip_days": 21,              # ~1 trading month skip
        "long_quantile": 0.80,        # top quintile (>=0.80)
        "min_universe_size": 50,      # below this, top-quintile = <10 names → skip
        "long_score": 1.0,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    def _ticker_return(self, df: pd.DataFrame, lookback: int, skip: int) -> float:
        """Cumulative return over [-(lookback+skip), -skip] window."""
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
        lookback = int(self.params.get("lookback_days", 252))
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
            # Below universe-size gate — abstain on every ticker rather
            # than concentrate. Avoids a 5-name bet on a 25-ticker universe.
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


# ---------------------------------------------------------------------------
# Auto-register on import. status='paused' tier='feature' — won't trade
# in production until lifecycle gauntlet validates. Same pattern as
# calendar_anomaly_v1, cot_positioning_v1.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=Momentum12_1Edge.EDGE_ID,
        category=Momentum12_1Edge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(Momentum12_1Edge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
