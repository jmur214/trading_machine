"""
engines/engine_a_alpha/edges/macro_unemployment_momentum_edge.py
================================================================
Macro regime-tilt based on the 3-month change in the headline US
unemployment rate.

Mechanism: same shape as `macro_yield_curve_edge.py`. Emits a uniform
tilt across the universe based on labor-market momentum.

Why 3-month change in UNRATE:
- The level of unemployment is a lagging indicator and tends to mean-
  revert slowly. The 3-month change ("Sahm-rule-like") is much
  closer to a leading signal: a sustained 3m increase has historically
  preceded recessions and equity drawdowns; a sustained 3m decrease
  tracks early-cycle expansion and risk-on conditions.
- 3 months smooths over the noisy single-print whipsaws (one bad NFP
  print does not flip the regime).

Tilt mapping (thresholds derived from the historical stdev of 3m
changes in the cache):
- Rising fast (>= +1 stdev): -0.2 (late-cycle / deteriorating labor)
- Falling fast (<= -1 stdev): +0.2 (early-cycle / improving labor)
- Anywhere between: 0 (no signal)

Cache behavior: reads `UNRATE` via `MacroDataManager.load_cached`.
UNRATE is in the curated FRED registry so the cache is populated by
the standard data pipeline. Empty cache → emit zeros for every
ticker (no exceptions, no NaN).

Magnitude is intentionally small (0.2). This is a regime modulator,
not a per-ticker alpha edge.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("MacroUnemploymentMomentumEdge")


class MacroUnemploymentMomentumEdge(EdgeBase):
    EDGE_ID = "macro_unemployment_momentum_v1"
    CATEGORY = "macro_regime"
    DESCRIPTION = (
        "Unemployment-momentum regime tilt: shifts every ticker's score "
        "based on the 3-month change in UNRATE. Uniform tilt, not per-"
        "ticker alpha."
    )

    DEFAULT_PARAMS = {
        "unrate_series": "UNRATE",
        # Number of months for the change window. UNRATE is monthly, so
        # 3 = quarter-over-quarter change.
        "lookback_months": 3,
        # Number of stdevs of the 3m-change distribution that defines the
        # rising/falling thresholds.
        "stdev_threshold": 1.0,
        "rising_score": -0.2,
        "falling_score": 0.2,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._momentum_cache: pd.Series | None = None
        self._cache_loaded = False
        self._stdev: float | None = None

    @classmethod
    def sample_params(cls):
        return dict(cls.DEFAULT_PARAMS)

    def _ensure_momentum_loaded(self) -> pd.Series | None:
        """Load UNRATE, compute Nm change, store stdev for thresholding."""
        if self._cache_loaded:
            return self._momentum_cache

        self._cache_loaded = True
        try:
            from engines.data_manager import MacroDataManager
        except Exception as exc:
            log.debug(f"MacroDataManager import failed ({exc}); abstaining")
            self._momentum_cache = None
            return None

        try:
            mgr = MacroDataManager()
            df = mgr.load_cached(self.params["unrate_series"])
        except Exception as exc:
            log.debug(f"Cache load failed ({exc}); abstaining")
            self._momentum_cache = None
            return None

        if df is None or df.empty:
            log.debug(
                "FRED cache empty for UNRATE; abstaining. Pre-populate via "
                "MacroDataManager().fetch_series('UNRATE')."
            )
            self._momentum_cache = None
            return None

        if "value" in df.columns:
            series = df["value"].dropna()
        else:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                self._momentum_cache = None
                return None
            series = df[numeric_cols[0]].dropna()

        try:
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                pass

        series = series.sort_index()
        n = int(self.params.get("lookback_months", 3))
        # UNRATE is monthly; .diff(n) on monthly index is the n-month change.
        momentum = series.diff(n).dropna()
        if momentum.empty:
            self._momentum_cache = None
            return None

        self._momentum_cache = momentum
        self._stdev = float(momentum.std(ddof=0))
        return self._momentum_cache

    def _momentum_at(self, as_of: pd.Timestamp) -> float | None:
        series = self._ensure_momentum_loaded()
        if series is None or series.empty:
            return None
        try:
            ts = pd.Timestamp(as_of)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return None
        try:
            val = series.asof(ts)
        except Exception:
            return None
        if pd.isna(val):
            return None
        return float(val)

    def compute_signals(self, data_map, now):
        zero_scores = {ticker: 0.0 for ticker in data_map}

        momentum = self._momentum_at(now)
        if momentum is None or self._stdev is None or self._stdev <= 0:
            return zero_scores

        k = float(self.params.get("stdev_threshold", 1.0))
        rising_threshold = k * self._stdev
        falling_threshold = -k * self._stdev

        if momentum >= rising_threshold:
            tilt = float(self.params.get("rising_score", -0.2))
        elif momentum <= falling_threshold:
            tilt = float(self.params.get("falling_score", 0.2))
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
        edge_id=MacroUnemploymentMomentumEdge.EDGE_ID,
        category=MacroUnemploymentMomentumEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(MacroUnemploymentMomentumEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
