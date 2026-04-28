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

Tilt mapping (computed from a *rolling* 5-year window of the spread,
ending at the current bar — no look-ahead):
- Wide spread (>= rolling_mean + 1 rolling_stdev): -0.3 (stress, defensive)
- Tight spread (<= rolling_mean - 1 rolling_stdev): +0.3 (risk-on)
- Anywhere between: 0 (neutral)

Why rolling instead of full-history mean/stdev: BAA-AAA goes back to
the 1980s including extreme 2008-crisis spikes. Computing mean+stdev
over the full series gives thresholds biased toward old regimes — on
2021-2024 data the spread is structurally low so it almost never
crosses `full_mean ± 1*full_std`, and the edge emits 0 tilt for ~100%
of bars. A trailing 5y window adapts the thresholds to the current
regime: if BAA-AAA has been quiet for 5 years, a smaller widening
counts as a stress signal.

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
        # Number of stdevs from the trailing-window mean that defines wide/tight.
        "stdev_threshold": 1.0,
        # Trailing window for the mean/stdev calculation, in calendar days.
        # 5 years matches typical regime-cycle length while leaving enough
        # samples for stable moments. BAA10Y/AAA10Y are daily series.
        "lookback_days": 1825,
        # Minimum samples required in the trailing window before the edge
        # will fire. Prevents firing on early-history data where the
        # window is mostly empty.
        "min_window_samples": 252,
        # Magnitudes of the tilt. Kept small so this edge modulates rather
        # than dominates per-ticker signals.
        "stress_score": -0.3,
        "riskon_score": 0.3,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._spread_cache: pd.Series | None = None
        self._rolling_mean: pd.Series | None = None
        self._rolling_stdev: pd.Series | None = None
        self._cache_loaded = False

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

        # Rolling stats — uses calendar days (`time-based offset`) so the
        # window is well-defined even when the series has irregular gaps
        # (FRED occasionally has missing days). `min_periods` ensures the
        # window has enough data to be statistically meaningful before any
        # value is emitted; otherwise rolling returns NaN and the edge
        # abstains.
        lookback = int(self.params.get("lookback_days", 1825))
        min_periods = int(self.params.get("min_window_samples", 252))
        window = f"{lookback}D"
        self._rolling_mean = spread.rolling(window, min_periods=min_periods).mean()
        self._rolling_stdev = spread.rolling(window, min_periods=min_periods).std(ddof=0)
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

    def _stats_at(self, as_of: pd.Timestamp) -> tuple[float, float, float] | None:
        """Return (spread_value, rolling_mean, rolling_stdev) at `as_of`,
        all computed from the trailing 5-year window ending at `as_of`.
        Returns None if insufficient data, abstaining via zero tilt."""
        series = self._ensure_spread_loaded()
        if series is None or series.empty:
            return None
        if self._rolling_mean is None or self._rolling_stdev is None:
            return None
        try:
            ts = pd.Timestamp(as_of)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return None
        try:
            spread_val = series.asof(ts)
            mean_val = self._rolling_mean.asof(ts)
            stdev_val = self._rolling_stdev.asof(ts)
        except Exception:
            return None
        if pd.isna(spread_val) or pd.isna(mean_val) or pd.isna(stdev_val):
            return None
        return float(spread_val), float(mean_val), float(stdev_val)

    def compute_signals(self, data_map, now):
        zero_scores = {ticker: 0.0 for ticker in data_map}

        stats = self._stats_at(now)
        if stats is None:
            return zero_scores
        spread, mean_val, stdev_val = stats
        if stdev_val <= 0:
            return zero_scores

        k = float(self.params.get("stdev_threshold", 1.0))
        wide_threshold = mean_val + k * stdev_val
        tight_threshold = mean_val - k * stdev_val

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
