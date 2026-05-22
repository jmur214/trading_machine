"""
engines/data_manager/universe_resolver.py
=========================================

Backtest-time universe resolution.

Bridges ``universe.SP500MembershipLoader`` (the survivorship-bias-aware
membership table) and the orchestration layer's existing static-list
contract. Single entry point: ``resolve_universe(...)``.

The resolver is deliberately small and cache-only: it does not hit the
network. Membership data is expected to be present in
``data/universe/sp500_membership.parquet`` (created by
``scripts/fetch_universe.py``). If it is missing, the resolver falls
back to the static list and logs why — no engine will ever be left
without an input universe.

Why this lives in ``engines/data_manager/`` (not ``orchestration/``)
-------------------------------------------------------------------
The data_manager engine owns "what data is available." Resolving which
tickers a backtest will trade is a data-availability question, not an
orchestration question. Engine boundaries: orchestration calls the
resolver, gets back a list, and proceeds; the resolver does not invoke
ModeController, BacktestController, or any other engine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence

import pandas as pd

from engines.data_manager.universe import (
    SP500MembershipLoader,
    UniverseError,
    union_active_over_window,
)


# Tickers always retained regardless of membership — index ETFs the
# RegimeDetector and macro features depend on. SPY in particular is
# referenced by Engine E for regime context.
DEFAULT_ESSENTIAL_TICKERS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "TLT", "GLD",
)


def _spinoff_children_in_window(
    spinoff_events: Sequence[Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> List[str]:
    """T-041b: from a sequence of `SpinoffEvent`-like records, return
    the unique child tickers whose `distribution_date` falls inside
    [start, end].

    A child whose distribution_date is BEFORE start is excluded: the
    spin-off had already happened before the backtest started, and we
    treat it as part of the prior universe — it should already be
    captured by historical membership or static_tickers if it's still
    tradeable in-window.

    A child whose distribution_date is AFTER end is excluded — no
    look-ahead. The backtest never knew about the spin-off.

    Accepts duck-typed records: anything with `child_ticker` and
    `distribution_date` attributes works, so callers don't have to
    import the SpinoffEvent class from Engine A into the data_manager
    boundary. Engine boundaries: data_manager owns "what's tradeable
    when," not edge-specific event schemas.
    """
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is not None:
        start_ts = start_ts.tz_localize(None)
    if end_ts.tzinfo is not None:
        end_ts = end_ts.tz_localize(None)

    children: set[str] = set()
    for ev in spinoff_events:
        try:
            d = pd.Timestamp(getattr(ev, "distribution_date"))
            if d.tzinfo is not None:
                d = d.tz_localize(None)
            if start_ts <= d <= end_ts:
                children.add(str(getattr(ev, "child_ticker")).upper())
        except (AttributeError, TypeError, ValueError):
            continue
    return sorted(children)


def resolve_universe(
    *,
    static_tickers: Sequence[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    use_historical: bool,
    cache_dir: Path,
    anchor_dates: Optional[Sequence[str]] = None,
    essential_tickers: Sequence[str] = DEFAULT_ESSENTIAL_TICKERS,
    available_filter: Optional[Sequence[str]] = None,
    spinoff_events: Optional[Sequence[Any]] = None,
) -> tuple[list[str], dict]:
    """Return the (tickers, debug_info) tuple for a backtest run.

    Parameters
    ----------
    static_tickers
        The legacy hand-picked list (e.g. ``cfg_bt["tickers"]``).
        Returned verbatim when ``use_historical`` is False, OR when the
        historical-membership cache is missing (graceful degradation).
    start, end
        Backtest window. Used to compute annual anchor dates when
        ``anchor_dates`` is None.
    use_historical
        Master switch. False → pure legacy behavior, no I/O on the
        membership parquet at all.
    cache_dir
        Path to the project's ``data/`` directory. The membership
        parquet is expected at ``cache_dir / "universe" /
        "sp500_membership.parquet"``.
    anchor_dates
        Optional explicit list of as-of dates. Default is one Jan-1
        anchor per calendar year in ``[start, end]``.
    essential_tickers
        Always-on tickers (index ETFs etc.). Default keeps SPY/QQQ/IWM
        /TLT/GLD because Engine E and several macro-aware edges
        reference them by name.
    available_filter
        Optional sequence of tickers to intersect with the resolved
        universe. Use this to drop names whose price CSVs are not on
        disk so the backtest does not waste time fetching empty
        DataFrames. ``None`` = no filter.

    Returns
    -------
    tickers : list[str]
        Sorted, deduplicated list of tickers to feed to
        ``DataManager.ensure_data``.
    info : dict
        Diagnostic payload:
            "mode": "static" | "historical" | "fallback_to_static"
            "n_static", "n_historical_union",
            "n_after_essentials", "n_after_available_filter",
            "anchor_dates": list of ISO dates,
            "missing_from_cache": list of tickers requested but not in
                ``available_filter`` (only populated when filtering),
            "fallback_reason": str or None.
    """
    info: dict = {
        "mode": "static",
        "n_static": len(static_tickers),
        "n_historical_union": 0,
        "n_after_essentials": len(static_tickers),
        "n_after_available_filter": len(static_tickers),
        "n_spinoff_children_added": 0,
        "spinoff_children_added": [],
        "anchor_dates": [],
        "missing_from_cache": [],
        "fallback_reason": None,
    }

    # T-041b: compute the list of spin-off children whose distribution
    # falls inside [start, end]. These get added regardless of the
    # use_historical flag so a hand-picked static run can still pick up
    # spin-offs that occurred during the window.
    spinoff_children: list[str] = []
    if spinoff_events:
        spinoff_children = _spinoff_children_in_window(
            spinoff_events, pd.Timestamp(start), pd.Timestamp(end),
        )
        info["n_spinoff_children_added"] = len(spinoff_children)
        info["spinoff_children_added"] = list(spinoff_children)

    if not use_historical:
        combined_static = sorted(set(static_tickers) | set(spinoff_children))
        info["n_after_essentials"] = len(combined_static)
        if available_filter is not None:
            avail_set = set(available_filter)
            filtered = [t for t in combined_static if t in avail_set]
            info["missing_from_cache"] = [
                t for t in combined_static if t not in avail_set
            ]
            info["n_after_available_filter"] = len(filtered)
            return filtered, info
        info["n_after_available_filter"] = len(combined_static)
        return combined_static, info

    membership_parquet = (
        Path(cache_dir) / "universe" / "sp500_membership.parquet"
    )
    if not membership_parquet.exists():
        info["mode"] = "fallback_to_static"
        info["fallback_reason"] = (
            f"missing membership parquet at {membership_parquet}; run "
            "`python -m scripts.fetch_universe --membership-only` to populate"
        )
        return list(static_tickers), info

    try:
        loader = SP500MembershipLoader(cache_dir=membership_parquet.parent)
        membership_df = loader.load_cached()
        if membership_df.empty:
            raise UniverseError("membership parquet exists but is empty")
        if anchor_dates is None:
            anchors_ts: list[pd.Timestamp] = []
            historical = union_active_over_window(membership_df, start, end)
            # Re-derive the anchor list for diagnostic logging.
            from engines.data_manager.universe import annual_anchor_dates
            anchors_ts = annual_anchor_dates(start, end)
        else:
            anchors_ts = [pd.Timestamp(d) for d in anchor_dates]
            historical = union_active_over_window(
                membership_df, start, end, anchor_dates=list(anchor_dates),
            )
    except (UniverseError, ValueError, OSError) as exc:
        info["mode"] = "fallback_to_static"
        info["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        return list(static_tickers), info

    info["mode"] = "historical"
    info["n_historical_union"] = len(historical)
    info["anchor_dates"] = [a.strftime("%Y-%m-%d") for a in anchors_ts]

    combined = sorted(
        set(historical)
        | set(essential_tickers)
        | set(spinoff_children)
    )
    info["n_after_essentials"] = len(combined)

    if available_filter is not None:
        avail_set = set(available_filter)
        filtered = [t for t in combined if t in avail_set]
        info["missing_from_cache"] = [t for t in combined if t not in avail_set]
        info["n_after_available_filter"] = len(filtered)
        return filtered, info

    info["n_after_available_filter"] = info["n_after_essentials"]
    return combined, info


def discover_cached_tickers(cache_dir: Path, timeframe: str = "1d") -> list[str]:
    """Return the set of tickers with a cached price CSV under ``cache_dir/processed/``.

    Used by the resolver to short-circuit ``ensure_data`` calls on
    tickers that aren't already on disk (avoids triggering Alpaca/yf
    fetches for hundreds of survivorship-aware names during a
    cache-only backtest).
    """
    processed = Path(cache_dir) / "processed"
    if not processed.exists():
        return []
    suffix = f"_{timeframe}.csv"
    out = []
    for f in processed.iterdir():
        if f.is_file() and f.name.endswith(suffix):
            out.append(f.name[: -len(suffix)])
    return sorted(out)
