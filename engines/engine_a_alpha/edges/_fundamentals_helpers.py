"""Shared helpers for SimFin V/Q/A fundamentals edges.

These edges all share the same shape:

    1. Iterate active universe.
    2. For each ticker with SimFin coverage at the as_of date, compute a
       per-ticker score (e.g. earnings_yield_market = TTM_NI / market_cap).
    3. Compute the top-quintile threshold cross-sectionally on the present-data
       subset.
    4. Emit long_score for tickers above the threshold; 0 otherwise.

The only thing that varies edge-to-edge is the per-ticker score function. All
the boilerplate (universe iteration, PIT adapter call, quintile selection,
return-keyset) lives here.

Coverage caveat (109-ticker production universe + SimFin FREE):
    109 → ~80 with-data (financials excluded by SimFin FREE) → top-quintile = 16.
    That's the right side of the universe-too-small line documented in
    `project_factor_edge_first_alpha_2026_04_24.md` — but only by a hair.
    Edges with `min_universe=30` will abstain when SimFin coverage drops below
    that on a given as_of (e.g. early in a backtest before enough quarterlies
    have published).

PIT discipline:
    Every score function pulls from the panel via `simfin_adapter.load_panel()`
    + `publish_date <= asof_ts` filter. All TTM-flow items require
    ``≥4 published quarters``; if not enough history, the ticker is dropped.
    Balance-sheet stocks use the most-recent published snapshot.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Panel access — cached per process. The SimFin parquet is ~10MB, loading
# it on every edge invocation would be wasteful; one cached load per process.
# ---------------------------------------------------------------------------

_PANEL_CACHE: Optional[pd.DataFrame] = None
_PANEL_LOAD_FAILED: bool = False


def get_panel() -> Optional[pd.DataFrame]:
    """Return the cached SimFin panel, or None if it can't be loaded.

    The panel is loaded exactly once per process. If the loader raises
    (e.g. SIMFIN_API_KEY missing in a test sandbox), we cache the failure
    so subsequent calls don't keep retrying.
    """
    global _PANEL_CACHE, _PANEL_LOAD_FAILED
    if _PANEL_CACHE is not None:
        return _PANEL_CACHE
    if _PANEL_LOAD_FAILED:
        return None
    try:
        from engines.data_manager.fundamentals.simfin_adapter import load_panel
        _PANEL_CACHE = load_panel()
        return _PANEL_CACHE
    except Exception:
        _PANEL_LOAD_FAILED = True
        return None


def reset_panel_cache() -> None:
    """Test helper: drop the cached panel so a fixture can inject its own."""
    global _PANEL_CACHE, _PANEL_LOAD_FAILED
    _PANEL_CACHE = None
    _PANEL_LOAD_FAILED = False


def set_panel(panel: pd.DataFrame) -> None:
    """Test helper: inject a fixture panel directly."""
    global _PANEL_CACHE, _PANEL_LOAD_FAILED
    _PANEL_CACHE = panel
    _PANEL_LOAD_FAILED = False


# ---------------------------------------------------------------------------
# PIT panel queries — same primitives the path_c compounder uses.
# ---------------------------------------------------------------------------

def latest_value(
    panel: pd.DataFrame,
    ticker: str,
    asof_ts: pd.Timestamp,
    column: str,
) -> Optional[float]:
    """Most recently published value of ``column`` for ``ticker`` as of ``asof_ts``.

    Used for stock items (total_equity, total_assets) AND for adapter-precomputed
    factors (sloan_accruals, asset_growth). Returns None if the ticker has no
    published filings before asof_ts or the column is NaN.
    """
    try:
        ticker_slice = panel.xs(ticker, level="Ticker")
    except KeyError:
        return None

    eligible = ticker_slice[ticker_slice["publish_date"] <= asof_ts]
    if eligible.empty:
        return None

    latest = eligible.sort_values("publish_date").iloc[-1]
    val = latest.get(column)
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def ttm_sum(
    panel: pd.DataFrame,
    ticker: str,
    asof_ts: pd.Timestamp,
    column: str,
    n_quarters: int = 4,
) -> Optional[float]:
    """Trailing N-quarter sum of a flow item, PIT-correct via publish_date.

    SimFin stores quarterly flow values; TTM = sum of most-recent 4 publishes
    that are <= asof_ts. Returns None if fewer than n_quarters of clean data.
    """
    try:
        ticker_slice = panel.xs(ticker, level="Ticker")
    except KeyError:
        return None

    eligible = ticker_slice[ticker_slice["publish_date"] <= asof_ts]
    if len(eligible) < n_quarters:
        return None

    recent = eligible.sort_values("publish_date").tail(n_quarters)
    vals = recent[column]
    if vals.isna().any():
        return None
    return float(vals.sum())


# ---------------------------------------------------------------------------
# Cross-sectional top-quintile selection — the shared edge skeleton.
# ---------------------------------------------------------------------------

def latest_close(df: Optional[pd.DataFrame]) -> Optional[float]:
    """Most-recent close from a per-ticker OHLCV frame, or None if unavailable."""
    if df is None or "Close" not in df.columns or len(df) == 0:
        return None
    try:
        px = float(df["Close"].iloc[-1])
    except (TypeError, ValueError):
        return None
    if not np.isfinite(px) or px <= 0:
        return None
    return px


def top_quintile_long_signals(
    data_map: Dict[str, pd.DataFrame],
    now: pd.Timestamp,
    score_fn: Callable[[pd.DataFrame, str, pd.Timestamp, Optional[pd.DataFrame]], Optional[float]],
    *,
    top_quantile: float,
    long_score: float,
    min_universe: int,
) -> Dict[str, float]:
    """Generic top-quintile cross-sectional long-only edge.

    Parameters
    ----------
    data_map
        ``{ticker: ohlcv_df}`` from the alpha engine.
    now
        As-of timestamp for PIT correctness.
    score_fn
        Callable ``(panel, ticker, asof_ts, ticker_df) -> Optional[float]``.
        Returns the per-ticker raw factor score, or None if data is missing.
        Higher score = more attractive (top of distribution gets the long).
    top_quantile
        Fraction of present-data names that get the long signal (e.g. 0.20).
    long_score
        Magnitude emitted for selected names.
    min_universe
        If fewer than this many tickers have a usable score, abstain entirely.

    Returns
    -------
    ``{ticker: score}`` for every ticker in ``data_map``. Selected names get
    ``long_score``; everyone else (including missing-data names) gets 0.0.
    """
    panel = get_panel()
    asof_ts = pd.Timestamp(now)

    if panel is None:
        # No fundamentals available — abstain. This is the legitimate
        # missing-data path; the edge degrades gracefully.
        return {t: 0.0 for t in data_map}

    raw_scores: Dict[str, float] = {}
    for ticker, df in data_map.items():
        try:
            raw = score_fn(panel, ticker, asof_ts, df)
        except Exception:
            raw = None
        if raw is None:
            continue
        if not np.isfinite(raw):
            continue
        raw_scores[ticker] = float(raw)

    if len(raw_scores) < min_universe:
        return {t: 0.0 for t in data_map}

    # Sort descending — highest score = top of distribution
    sorted_tickers = sorted(raw_scores.keys(), key=lambda t: raw_scores[t], reverse=True)
    n_long = max(1, int(round(len(sorted_tickers) * top_quantile)))
    selected = set(sorted_tickers[:n_long])

    return {t: (long_score if t in selected else 0.0) for t in data_map}
