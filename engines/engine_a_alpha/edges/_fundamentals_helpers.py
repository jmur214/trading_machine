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

import logging
from typing import Any, Callable, Dict, Optional, Set

import numpy as np
import pandas as pd

_LOG = logging.getLogger(__name__)


# Programmer-error exceptions that MUST propagate from inside score functions.
# Per memory `project_gauntlet_consolidated_fix_2026_05_01`, swallowing these
# behind a bare-except masks bugs as "missing data". The score_fn callable's
# legitimate "data missing" channel is `return None`, not raising.
_PROGRAMMER_ERRORS: tuple = (
    AttributeError,   # method on None, missing attr
    NameError,        # missing import
    ImportError,      # broken import
    SyntaxError,      # build-time programmer error reaching runtime
    AssertionError,   # explicit guard rail violation
)

# Legitimate runtime exceptions that score_fn might raise on a sparse SimFin
# slice or odd panel shape. These are still suppressed (treated as
# "ticker has no signal") but logged at DEBUG so they surface during audits.
_DATA_MISSING_ERRORS: tuple = (
    KeyError,
    IndexError,
    ValueError,
    ZeroDivisionError,
    TypeError,        # e.g. None * float in arithmetic on missing columns
)


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
    state: Optional[Dict[str, Any]] = None,
    edge_id: str = "",
    sustained_score: float = 0.3,
) -> Dict[str, float]:
    """Generic top-quintile cross-sectional long-only edge with state-transition emission.

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
        ``return None`` is the contract for missing data; raising
        AttributeError / NameError / ImportError will propagate (programmer
        errors must surface, not silently degrade).
    top_quantile
        Fraction of present-data names that get the long signal (e.g. 0.20).
    long_score
        Magnitude emitted for selected names ON ENTRY.
    min_universe
        If fewer than this many tickers have a usable score, abstain entirely.
    state
        Optional mutable dict for caching the prior basket across calls.
        If provided, the helper emits ``long_score`` ONLY for tickers that
        CROSSED INTO the top quintile since the last call (state-transition
        pattern). Sustained members emit ``sustained_score`` (the
        position-defending vote) so other edges' transient negative signals
        don't silently exit fundamentals-driven positions. Eliminates the
        daily over-trading produced when long_score=1.0 fires every bar
        against quarterly-cadence fundamentals data. ``None`` reverts to
        legacy steady-state emission (every basket member gets long_score
        every call) — kept as a fallback for tests that don't want
        to thread state through.
    edge_id
        Optional label used in DEBUG logs identifying which edge swallowed
        a data-missing exception or applied a state transition.
    sustained_score
        Magnitude emitted for tickers that REMAIN in the top quintile across
        consecutive calls. Default 0.3 — a position-defending vote: strong
        enough to counter mildly negative signals from other edges (so a
        slow-moving factor edge doesn't silently consent to a quarterly-
        held position being exited on a daily reversal blip), weak enough
        not to block exits when other edges fire strongly negative.
        Set to 0.0 to recover the prior pure entry-only / exit-only
        emission shape.

    Returns
    -------
    ``{ticker: score}`` for every ticker in ``data_map``.

    State-transition semantics (when ``state`` is provided):
      - Tickers crossing INTO the top quintile this call: ``long_score``
      - Tickers crossing OUT of the top quintile this call: 0.0
      - Sustained members (in basket this call AND last call): ``sustained_score``
      - Non-members (never in basket): 0.0
      The state dict is mutated in place: ``state["last_basket"]`` is
      replaced with the new basket frozenset.

    Legacy semantics (when ``state`` is None):
      - Every member of the current top quintile: ``long_score``
      - Everyone else: 0.0

    Exception handling (per Bug #2 fix 2026-05-06):
      - Programmer errors (AttributeError, NameError, ImportError, etc.)
        from inside score_fn propagate.
      - Data-missing errors (KeyError, ValueError, TypeError, etc.) are
        suppressed and logged at DEBUG so future bugs surface.
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
        except _PROGRAMMER_ERRORS:
            # Programmer error — let it propagate so the bug surfaces.
            # Same lesson as the gauntlet-consolidated-fix 2026-05-02
            # (memory project_gauntlet_consolidated_fix_2026_05_01).
            raise
        except _DATA_MISSING_ERRORS as exc:
            # Legitimate runtime data-shape exception — log so audits can
            # surface unexpected swallowing, then treat as missing data.
            _LOG.debug(
                "[%s] score_fn dropped %s @ %s: %s: %s",
                edge_id or "fundamentals_helpers",
                ticker,
                asof_ts.date() if hasattr(asof_ts, "date") else asof_ts,
                type(exc).__name__,
                exc,
            )
            raw = None
        if raw is None:
            continue
        if not np.isfinite(raw):
            continue
        raw_scores[ticker] = float(raw)

    if len(raw_scores) < min_universe:
        # Below abstention floor — also clear the state cache so a recovery
        # of coverage doesn't immediately re-emit the entire basket as
        # "transitions". Without this, a temporary panel-coverage gap would
        # produce a spurious entry burst on the recovery bar.
        if state is not None:
            state["last_basket"] = frozenset()
        return {t: 0.0 for t in data_map}

    # Sort descending — highest score = top of distribution
    sorted_tickers = sorted(raw_scores.keys(), key=lambda t: raw_scores[t], reverse=True)
    n_long = max(1, int(round(len(sorted_tickers) * top_quantile)))
    new_basket: Set[str] = set(sorted_tickers[:n_long])

    if state is None:
        # Legacy steady-state emission. Reserved for tests / callers that
        # don't thread state. Reproduces the pre-fix daily over-trading
        # behavior — do not use in production edges.
        return {t: (long_score if t in new_basket else 0.0) for t in data_map}

    # State-transition pattern (Bug #4 fix 2026-05-06).
    # Quarterly-cadence fundamentals data with daily-cadence bar invocation
    # would emit long_score=1.0 on the same 16 names every day under the
    # legacy semantics, and the per-ticker aggregator + Engine B
    # rebalance_within_tolerance check do not fully suppress the resulting
    # daily entry-rebalances (847 trades/yr observed on 16-name baskets in
    # 2021 single-year smoke). Emit signals only on basket transitions.
    prev_basket: Set[str] = set(state.get("last_basket", frozenset()))
    state["last_basket"] = frozenset(new_basket)

    entries = new_basket - prev_basket
    exits = prev_basket - new_basket

    sustained = new_basket & prev_basket

    out: Dict[str, float] = {}
    for ticker in data_map:
        if ticker in entries:
            out[ticker] = long_score
        elif ticker in exits:
            # Explicit exit signal — fade to zero so the per-ticker
            # aggregator stops boosting a no-longer-quintile ticker.
            out[ticker] = 0.0
        elif ticker in sustained:
            # Position-defending vote on held basket members. Slow-moving
            # factor edges should keep saying "I still want this position"
            # while a ticker is in the basket, otherwise transient daily
            # negative signals from faster edges (e.g. momentum reversal)
            # silently exit fundamentals-driven holds. ``sustained_score``
            # is calibrated weak enough not to block strongly-negative
            # exits but strong enough to defend mildly-negative ones.
            out[ticker] = sustained_score
        else:
            # Non-members — never in basket — emit 0.0.
            out[ticker] = 0.0

    if entries or exits:
        _LOG.debug(
            "[%s] basket transition @ %s: +%d entries, -%d exits, %d sustained",
            edge_id or "fundamentals_helpers",
            asof_ts.date() if hasattr(asof_ts, "date") else asof_ts,
            len(entries),
            len(exits),
            len(sustained),
        )

    return out
