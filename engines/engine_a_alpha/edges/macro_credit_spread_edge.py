"""
engines/engine_a_alpha/edges/macro_credit_spread_edge.py
========================================================
Macro regime-tilt based on the BAA-AAA corporate credit spread.

Mechanism: same shape as `macro_yield_curve_edge.py`. This is NOT a
per-ticker alpha edge — it emits a uniform tilt across the universe
based on current credit-stress state.

Why credit spreads:
- The investment-grade credit-quality slope (Baa over Aaa) widens
  before equity drawdowns. Stress in the bond market typically
  precedes stress in equities by weeks-to-months because credit
  investors are first to demand a risk premium when default
  expectations rise.
- FRED publishes ``BAA10Y`` (Moody's Seasoned Baa Corporate Bond
  Yield Relative to 10Y Treasury) and ``AAA10Y`` (Aaa version).
  Subtracting cancels the common 10Y leg, leaving Baa-Aaa — the
  pure credit-quality slope.

Tilt mapping (computed from the cache's full historical mean and
stdev):
- Wide spread (>= mean + 1 stdev): -0.3 (stress regime, defensive bias)
- Tight spread (<= mean - 1 stdev): +0.3 (risk-on regime)
- Anywhere between: 0 (neutral)

Cache behavior: reads `BAA10Y` and `AAA10Y` via `MacroDataManager.
load_cached`. Neither is in the curated registry yet, so on a fresh
clone the parquet files do not exist and `load_cached` returns an
empty frame — the edge then emits zeros for every ticker (abstains).
This lets the edge ship as `active` without breaking backtests that
have not pre-populated the cache.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("MacroCreditSpreadEdge")


class MacroCreditSpreadEdge(EdgeBase):
    EDGE_ID = "macro_credit_spread_v1"
    CATEGORY = "macro_regime"
    DESCRIPTION = (
        "Credit-spread regime tilt: shifts every ticker's aggregate score "
        "based on the Baa-Aaa corporate credit spread (BAA10Y - AAA10Y). "
        "Uniform tilt, not per-ticker alpha."
    )

    DEFAULT_PARAMS = {
        "baa_series": "BAA10Y",
        "aaa_series": "AAA10Y",
        # Number of stdevs from the historical mean that defines wide/tight.
        "stdev_threshold": 1.0,
        # Magnitudes of the tilt. Kept small so this edge modulates rather
        # than dominates per-ticker signals.
        "stress_score": -0.3,
        "riskon_score": 0.3,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._spread_cache: pd.Series | None = None
        self._cache_loaded = False
        self._mean: float | None = None
        self._stdev: float | None = None

    @classmethod
    def sample_params(cls):
        return dict(cls.DEFAULT_PARAMS)

    def _ensure_spread_loaded(self) -> pd.Series | None:
        """Lazy-load BAA10Y and AAA10Y from cache, return BAA-AAA series.
        Returns None if either side is missing. Logs but does not raise."""
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
            baa = mgr.load_cached(self.params["baa_series"])
            aaa = mgr.load_cached(self.params["aaa_series"])
        except Exception as exc:
            log.debug(f"Cache load failed ({exc}); abstaining")
            self._spread_cache = None
            return None

        if baa is None or baa.empty or aaa is None or aaa.empty:
            log.debug(
                "FRED cache empty for BAA10Y or AAA10Y; abstaining. "
                "Pre-populate via MacroDataManager().fetch_series('BAA10Y') "
                "and ('AAA10Y') after FRED_API_KEY is set."
            )
            self._spread_cache = None
            return None

        baa_s = self._extract_series(baa)
        aaa_s = self._extract_series(aaa)
        if baa_s is None or aaa_s is None:
            self._spread_cache = None
            return None

        # Align on common dates and subtract.
        joined = pd.concat([baa_s.rename("baa"), aaa_s.rename("aaa")],
                           axis=1, join="inner").dropna()
        if joined.empty:
            self._spread_cache = None
            return None
        spread = (joined["baa"] - joined["aaa"]).sort_index()

        self._spread_cache = spread
        self._mean = float(spread.mean())
        self._stdev = float(spread.std(ddof=0))
        return self._spread_cache

    @staticmethod
    def _extract_series(df: pd.DataFrame) -> pd.Series | None:
        """Extract the value column and normalize the index to naive dates."""
        if "value" in df.columns:
            series = df["value"].dropna()
        else:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) == 0:
                return None
            series = df[numeric_cols[0]].dropna()
        try:
            series.index = pd.to_datetime(series.index).tz_localize(None)
        except (TypeError, AttributeError):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                pass
        return series.sort_index()

    def _spread_at(self, as_of: pd.Timestamp) -> float | None:
        series = self._ensure_spread_loaded()
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

        spread = self._spread_at(now)
        if spread is None or self._mean is None or self._stdev is None:
            return zero_scores
        if self._stdev <= 0:
            return zero_scores

        k = float(self.params.get("stdev_threshold", 1.0))
        wide_threshold = self._mean + k * self._stdev
        tight_threshold = self._mean - k * self._stdev

        if spread >= wide_threshold:
            tilt = float(self.params.get("stress_score", -0.3))
        elif spread <= tight_threshold:
            tilt = float(self.params.get("riskon_score", 0.3))
        else:
            tilt = 0.0

        return {ticker: tilt for ticker in data_map}


# ---------------------------------------------------------------------------
# Auto-register on import — same pattern as macro_yield_curve_edge.
# Safe post-2026-04-25 fix: EdgeRegistry.ensure() write-protects status.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=MacroCreditSpreadEdge.EDGE_ID,
        category=MacroCreditSpreadEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(MacroCreditSpreadEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception:
    pass
