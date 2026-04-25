"""
engines/engine_a_alpha/edges/macro_yield_curve_edge.py
======================================================
First FRED-consuming edge. Macro regime-tilt based on the Treasury yield
curve.

The yield-curve-inversion signal is one of the most well-documented
recession leading indicators in macroeconomics — has correctly preceded
every US recession since 1970, with a 6-18 month lead. The 10Y-2Y spread
is the popular version; the 10Y-3M is the NY Fed's preferred indicator.
Either is valid; both are free on FRED.

Mechanism: this edge does NOT generate per-ticker signals. It emits a
uniform tilt score across the universe based on the current curve state.
- Curve clearly normal (spread > +0.50%): +0.3 (mild bullish bias)
- Curve neutral (0 < spread < +0.50%): 0 (abstain)
- Curve inverted (spread < 0): -0.3 (defensive bias)

The signal_processor's weighted aggregation adds this tilt to each
per-ticker score. Net effect: when the curve is inverted, every ticker's
aggregate score shifts down, making long entries less likely to clear
the entry threshold and more likely to be cut by exits. That's the right
semantic for a regime-modulator — it doesn't pick stocks, it conditions
the system's gross-long bias on macro state.

The signal magnitude (0.3) is intentionally modest. This is a tilt, not
a per-ticker alpha edge. If the magnitude were larger, this edge would
dominate per-ticker signals.

Cache behavior: reads FRED data via `MacroDataManager.load_cached`.
If the cache is empty (no FRED_API_KEY configured, or fresh clone),
the edge emits zeros for every ticker (abstains entirely). No crash.
This lets the edge ship and be active in code without requiring the
FRED key to be configured for backtests to run.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("MacroYieldCurveEdge")


class MacroYieldCurveEdge(EdgeBase):
    EDGE_ID = "macro_yield_curve_v1"
    CATEGORY = "macro"
    DESCRIPTION = (
        "Yield-curve regime tilt: shifts every ticker's aggregate score "
        "based on the 10Y-2Y (or 10Y-3M) Treasury spread. Uniform tilt, "
        "not per-ticker alpha."
    )

    DEFAULT_PARAMS = {
        # Which FRED series provides the spread. Two options ship with the
        # macro_data registry: T10Y2Y (popular) or T10Y3M (NY Fed preferred).
        "spread_series": "T10Y2Y",
        # Threshold above which the curve is "clearly normal" — bullish tilt.
        # In percent (FRED publishes spreads as percentage points).
        "normal_threshold": 0.50,
        # Inversion threshold — defensive tilt.
        "inversion_threshold": 0.0,
        # Magnitudes of the tilt. Kept small so this edge modulates rather
        # than dominates per-ticker signals.
        "bullish_score": 0.3,
        "bearish_score": -0.3,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._spread_cache: pd.Series | None = None
        self._cache_loaded = False

    @classmethod
    def sample_params(cls):
        """Used by Engine D's GA / mutation. Returns the canonical defaults
        — this edge is not supposed to be hyperparameter-tuned."""
        return dict(cls.DEFAULT_PARAMS)

    def _ensure_spread_loaded(self) -> pd.Series | None:
        """Lazy-load the FRED spread series from cache. Returns None if
        cache is empty or unreadable. Logs but does not raise."""
        if self._cache_loaded:
            return self._spread_cache

        self._cache_loaded = True
        try:
            from engines.data_manager import MacroDataManager
        except Exception as exc:
            log.debug(f"MacroDataManager import failed ({exc}); abstaining")
            self._spread_cache = None
            return None

        try:
            mgr = MacroDataManager()
            df = mgr.load_cached(self.params["spread_series"])
        except Exception as exc:
            log.debug(f"Cache load failed ({exc}); abstaining")
            self._spread_cache = None
            return None

        if df is None or df.empty:
            log.debug(
                f"FRED cache empty for {self.params['spread_series']}; "
                "abstaining. Populate cache with `python -c \"from "
                "engines.data_manager.macro_data import MacroDataManager; "
                "MacroDataManager().fetch_panel()\"` after FRED_API_KEY is set."
            )
            self._spread_cache = None
            return None

        # Standardize: cache writes a frame with column "value", index "date"
        if "value" in df.columns:
            series = df["value"].dropna()
        else:
            # Fallback if schema differs — take the first numeric column
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                self._spread_cache = None
                return None
            series = df[numeric_cols[0]].dropna()

        # Ensure index is DatetimeIndex naive
        try:
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                pass

        self._spread_cache = series.sort_index()
        return self._spread_cache

    def _spread_at(self, as_of: pd.Timestamp) -> float | None:
        """Return the most recent spread value at or before `as_of`.
        None if no data available at that point in time."""
        series = self._ensure_spread_loaded()
        if series is None or series.empty:
            return None
        try:
            ts = pd.Timestamp(as_of)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return None
        # asof returns the most recent index <= ts
        try:
            val = series.asof(ts)
        except Exception:
            return None
        if pd.isna(val):
            return None
        return float(val)

    def compute_signals(self, data_map, now):
        # Default: zeros for everyone (abstain).
        zero_scores = {ticker: 0.0 for ticker in data_map}

        spread = self._spread_at(now)
        if spread is None:
            return zero_scores

        normal = float(self.params.get("normal_threshold", 0.50))
        inverted = float(self.params.get("inversion_threshold", 0.0))
        bullish = float(self.params.get("bullish_score", 0.3))
        bearish = float(self.params.get("bearish_score", -0.3))

        if spread > normal:
            tilt = bullish
        elif spread < inverted:
            tilt = bearish
        else:
            tilt = 0.0

        return {ticker: tilt for ticker in data_map}


# ---------------------------------------------------------------------------
# Auto-register on import — same pattern as other edges. Now SAFE: post-fix
# (2026-04-25), `EdgeRegistry.ensure()` write-protects the status field on
# existing specs, so re-registration on import won't revert lifecycle decisions.
# See `tests/test_edge_registry.py::test_ensure_does_not_overwrite_paused_status`.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=MacroYieldCurveEdge.EDGE_ID,
        category=MacroYieldCurveEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(MacroYieldCurveEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
