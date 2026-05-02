"""
engines/engine_a_alpha/edges/macro_dollar_regime_edge.py
========================================================

DEPRECATED 2026-05-02 — RECLASSIFIED AS REGIME INPUT.
DTWEXBGS broad dollar index now feeds Engine E's HMM regime classifier
as the dollar_ret_63d feature (engines.engine_e_regime.macro_features)
rather than generating per-ticker tilts. Code retained for historical
reference; auto-register writes status='retired'.

Macro regime-tilt based on the broad trade-weighted US dollar index
(FRED ``DTWEXBGS``).

Mechanism: same shape as `macro_yield_curve_edge.py`. Emits a uniform
tilt across the universe based on dollar trend state.

Why dollar trend matters:
- A strong, rising dollar is a headwind for the S&P 500 because
  multinational earnings translate to fewer USD; commodity producers
  also struggle (commodities priced in USD become more expensive
  internationally → weaker demand). The reverse is true for a falling
  dollar.
- Combining "level above 1y mean" AND "3m momentum positive" filters
  out short-term wobbles and isolates the sustained-trend regime.

Tilt mapping:
- Strong-dollar regime (3m momentum > 0 AND level > 1y mean): -0.2
- Weak-dollar regime (3m momentum < 0 AND level < 1y mean): +0.2
- Anywhere else (mixed signals or neutral): 0

Cache behavior: reads `DTWEXBGS` via `MacroDataManager.load_cached`.
DTWEXBGS is in the curated FRED registry. Empty cache → emit zeros for
every ticker (no exceptions, no NaN).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("MacroDollarRegimeEdge")


class MacroDollarRegimeEdge(EdgeBase):
    EDGE_ID = "macro_dollar_regime_v1"
    CATEGORY = "macro_regime"
    DESCRIPTION = (
        "Dollar-regime tilt: shifts every ticker's score based on the "
        "broad trade-weighted USD index trend (level vs 1y mean and "
        "3m momentum). Uniform tilt, not per-ticker alpha."
    )

    DEFAULT_PARAMS = {
        "dollar_series": "DTWEXBGS",
        # Days for the level reference (rolling window mean).
        "level_window_days": 252,
        # Days for the momentum lookback.
        "momentum_window_days": 63,
        "strong_score": -0.2,
        "weak_score": 0.2,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._series_cache: pd.Series | None = None
        self._cache_loaded = False

    @classmethod
    def sample_params(cls):
        return dict(cls.DEFAULT_PARAMS)

    def _ensure_series_loaded(self) -> pd.Series | None:
        if self._cache_loaded:
            return self._series_cache

        self._cache_loaded = True
        try:
            from engines.data_manager import MacroDataManager
        except Exception as exc:
            log.debug(f"MacroDataManager import failed ({exc}); abstaining")
            self._series_cache = None
            return None

        try:
            mgr = MacroDataManager()
            df = mgr.load_cached(self.params["dollar_series"])
        except Exception as exc:
            log.debug(f"Cache load failed ({exc}); abstaining")
            self._series_cache = None
            return None

        if df is None or df.empty:
            log.debug(
                "FRED cache empty for DTWEXBGS; abstaining. Pre-populate via "
                "MacroDataManager().fetch_series('DTWEXBGS')."
            )
            self._series_cache = None
            return None

        if "value" in df.columns:
            series = df["value"].dropna()
        else:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                self._series_cache = None
                return None
            series = df[numeric_cols[0]].dropna()

        try:
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                pass

        self._series_cache = series.sort_index()
        return self._series_cache

    def _compute_state(self, as_of: pd.Timestamp) -> tuple[float, float, float] | None:
        """Return (current_value, level_mean, momentum) or None."""
        series = self._ensure_series_loaded()
        if series is None or series.empty:
            return None
        try:
            ts = pd.Timestamp(as_of)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return None

        # Restrict the series to history at-or-before `now` so the edge
        # is point-in-time correct (no look-ahead).
        history = series.loc[series.index <= ts]
        if history.empty:
            return None

        level_window = int(self.params.get("level_window_days", 252))
        momentum_window = int(self.params.get("momentum_window_days", 63))
        # Need enough history for both windows.
        if len(history) < max(level_window, momentum_window) + 1:
            return None

        current = float(history.iloc[-1])
        level_slice = history.tail(level_window)
        level_mean = float(level_slice.mean())
        # Momentum = current minus value momentum_window days ago.
        prior = float(history.iloc[-(momentum_window + 1)])
        momentum = current - prior
        return (current, level_mean, momentum)

    def compute_signals(self, data_map, now):
        zero_scores = {ticker: 0.0 for ticker in data_map}

        state = self._compute_state(now)
        if state is None:
            return zero_scores
        current, level_mean, momentum = state

        if momentum > 0 and current > level_mean:
            tilt = float(self.params.get("strong_score", -0.2))
        elif momentum < 0 and current < level_mean:
            tilt = float(self.params.get("weak_score", 0.2))
        else:
            tilt = 0.0

        return {ticker: tilt for ticker in data_map}


# ---------------------------------------------------------------------------
# Auto-register on import.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=MacroDollarRegimeEdge.EDGE_ID,
        category=MacroDollarRegimeEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(MacroDollarRegimeEdge.DEFAULT_PARAMS),
        status="retired",  # 2026-05-02: reclassified to regime_input
    ))
except Exception:
    pass
