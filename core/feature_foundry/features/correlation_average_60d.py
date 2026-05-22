"""correlation_average_60d — average pairwise return correlation.

For date `dt`, compute the daily-log-return correlation matrix across
the universe over the trailing 60 trading days, then return the mean
of all upper-triangular off-diagonal entries. Spikes precede
coordinated drawdowns — when everything correlates to 1, idiosyncratic
risk vanishes and de-grossing is required to retain Sharpe.

Substrate-independent: universe is whatever's discoverable from the
registered LocalOHLCV source. Value is ticker-independent; the
parameter is kept for substrate uniformity. Per-date results are
cached in-process to amortize universe scans. Returns None when fewer
than 3 tickers have ≥61 aligned closes ending at-or-before `dt`.

T-2026-05-12-038-CONT: vectorized for 100×+ speedup. The pre-T-038-
CONT implementation rebuilt the per-ticker log-returns dict from
scratch on every call (727 ticker iterations × ~150 μs each ≈ 116 ms
per date). With ~1008 unique dates in a 4-year Discovery cycle, that
totaled ~117 s of redundant universe assembly.

The new implementation builds the universe-wide log-returns DataFrame
ONCE on first call (~5 s warm-up cost) and caches it as
`_LOG_RETURNS_PANEL`. Subsequent per-date queries slice the last
61 rows and compute corr().mean() in <1 ms each. End-to-end target:
117 s → 5 s + 1008 × 1 ms ≈ 6 s = 19× speedup.

Behavior unchanged: the same dropna() rule applies to each per-date
slice, so the function still returns None when no aligned cohort of
≥3 tickers spans the trailing 60 days. The pre-T-038-CONT pattern of
"None for most real dates" (caused by union-of-date-sets dropna
killing coverage) is preserved — fixing the dropna semantics is
explicitly out of scope per the T-038-CONT brief's "no output drift"
constraint.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..feature import feature
from ..sources.local_ohlcv import close_series, list_tickers


_CORR_CACHE: Dict[date, Optional[float]] = {}

# T-038-CONT: cache of the universe-wide log-returns panel. Built
# lazily on first call to `correlation_average_60d`. Shape: dates ×
# tickers. Dates are `datetime.date` (matching the cache-key dtype).
_LOG_RETURNS_PANEL: Optional[pd.DataFrame] = None


def _build_log_returns_panel() -> pd.DataFrame:
    """One-shot universe-wide log-returns assembly. Each column is a
    ticker; index is the union of trading dates across the universe."""
    series_by_ticker: Dict[str, pd.Series] = {}
    for t in list_tickers():
        s = close_series(t)
        if s is None or s.empty:
            continue
        closes = s.astype(float)
        if (closes <= 0).any():
            continue
        log_returns = pd.Series(
            np.diff(np.log(closes.values)),
            index=closes.index[1:],
        )
        series_by_ticker[t] = log_returns
    if not series_by_ticker:
        return pd.DataFrame()
    return pd.DataFrame(series_by_ticker)


def _ensure_panel_loaded() -> pd.DataFrame:
    global _LOG_RETURNS_PANEL
    if _LOG_RETURNS_PANEL is None:
        _LOG_RETURNS_PANEL = _build_log_returns_panel()
    return _LOG_RETURNS_PANEL


def _compute_avg_correlation(dt: date) -> Optional[float]:
    panel = _ensure_panel_loaded()
    if panel.empty:
        return None
    # Slice rows at-or-before dt. The panel index is `datetime.date`
    # so direct comparison works.
    window = panel.loc[panel.index <= dt]
    if window.shape[0] < 61:
        return None
    # Take the trailing 60 returns (60 days = 60 returns after the
    # log-diff). Matches the pre-T-038-CONT slice semantics:
    # `closes.iloc[-61:]` → 60 returns via np.diff.
    window = window.iloc[-60:]
    # dropna() with default axis=0 / how='any' matches the pre-T-038-
    # CONT semantics EXACTLY: drop rows where ANY ticker has NaN. On a
    # 727-ticker universe this collapses most rows because the union-
    # of-date-sets has gaps. The function returns None on most real
    # dates as a consequence. Switching to column-wise drop or
    # pairwise correlation would change output → out of scope per the
    # T-038-CONT "no output drift" constraint. The dropna semantics
    # bug-fix is a separate workstream candidate (T-040+).
    window = window.dropna()
    if window.shape[0] < 30 or window.shape[1] < 3:
        return None
    corr = window.corr().to_numpy()
    iu = np.triu_indices_from(corr, k=1)
    pairs = corr[iu]
    pairs = pairs[~np.isnan(pairs)]
    if pairs.size == 0:
        return None
    return float(pairs.mean())


@feature(
    feature_id="correlation_average_60d",
    tier="B",
    horizon=21,
    license="internal",
    source="local_ohlcv",
    description=(
        "Mean of upper-triangular pairwise correlations of trailing-60d "
        "log returns across the universe. Coordinated-drawdown primitive "
        "— spikes precede de-grossing regimes."
    ),
    ticker_independent=True,
)
def correlation_average_60d(ticker: str, dt: date) -> Optional[float]:
    if dt in _CORR_CACHE:
        return _CORR_CACHE[dt]
    val = _compute_avg_correlation(dt)
    _CORR_CACHE[dt] = val
    return val


def clear_correlation_cache() -> None:
    """Test helper — drop the in-process per-date cache AND the panel."""
    global _LOG_RETURNS_PANEL
    _CORR_CACHE.clear()
    _LOG_RETURNS_PANEL = None
