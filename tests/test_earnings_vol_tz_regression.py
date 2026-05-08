"""Regression test for the 2026-05-08 zero-trade outage.

Root cause: yfinance returns a tz-aware DatetimeIndex (America/New_York)
from `Ticker.earnings_dates`. `EarningsVolEdge._get_earnings_dates`
cached those dates without stripping tz. Downstream
`_pre_earnings_signal` / `_post_earnings_signal` compared each cached
date against a tz-naive `as_of` timestamp — pandas raises
`TypeError: Cannot compare tz-naive and tz-aware timestamps`.

The exception propagated up through:
  earnings_vol.compute_signals → signal_collector._call_edge →
  signal_collector.collect → AlphaEngine.generate_signals →
  backtest_controller line 388

where it was swallowed by a bare `except Exception` (line 389):
  signals = []

Result: every backtest produced zero trades from 2026-05-07 01:39
onward. Symptom: empty trades.csv, all snapshots at $100k starting
equity, canon md5 = empty-md5 (`d41d8cd98f00b204e9800998ecf8427e`).

This test calls compute_signals on a real ticker against a tz-naive
timestamp and asserts no exception. If yfinance changes its tz handling
again, OR if the strip-tz line is removed, this test fires.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engines.engine_a_alpha.edges.earnings_vol_edge import EarningsVolEdge


def test_earnings_vol_compute_signals_does_not_raise_on_tz_naive_timestamp(tmp_path):
    """The load-bearing invariant: compute_signals must not raise
    a tz-comparison error when called with a tz-naive `now`."""
    edge = EarningsVolEdge()
    edge._earnings_cache = {}  # ensure we re-fetch (simulates first call)

    # Build a synthetic data_map with enough history for the edge's
    # bb_window to compute. AAPL is one of the 12 tickers EarningsVolEdge
    # has yfinance coverage for.
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    import numpy as np
    rng = np.random.default_rng(0)
    close = 100 * (1.0 + rng.normal(0.001, 0.012, 200)).cumprod()
    df = pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": 1_000_000,
    }, index=idx)
    data_map = {"AAPL": df}

    # tz-NAIVE timestamp — the production format. Bug pre-fix: this
    # comparison-against-tz-aware-cached-dates raised TypeError.
    now = pd.Timestamp("2024-09-15")

    # Must not raise. Score may be 0.0 or non-zero; only the no-raise
    # property is being tested.
    scores = edge.compute_signals(data_map, now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_earnings_vol_cached_dates_are_tz_naive(tmp_path):
    """After _get_earnings_dates runs once, the cache must hold tz-naive
    Timestamps. This is the structural invariant that prevents the
    comparison error from ever firing again."""
    edge = EarningsVolEdge()
    edge._earnings_cache = {}

    # Trigger the cache load via a real call
    dates = edge._get_earnings_dates("AAPL")

    # If yfinance returned no data (network or rate-limit), accept that
    # and skip the assertion — the test's purpose is the tz-property,
    # not yfinance availability.
    if not dates:
        pytest.skip("yfinance returned no earnings dates for AAPL "
                    "(network / rate-limit / API change)")

    for d in dates:
        ts = pd.Timestamp(d)
        assert ts.tz is None, (
            f"earnings cache entry has tz={ts.tz}; expected None. "
            f"This is the 2026-05-08 zero-trade-regression invariant — "
            f"any tz-aware entry comparing against a tz-naive `as_of` "
            f"will raise TypeError and silently kill all signals via "
            f"the bare except in backtest_controller:389."
        )


def test_backtest_controller_bare_except_swallows_alpha_errors():
    """Document and verify the bare-except behavior at
    backtest_controller.py:389. We're not removing the catch (changes
    in alpha shouldn't crash a backtest), but we want the existence of
    this swallow path on the record so future debugs know to look here.

    If this test fails, either the line moved or the catch was tightened
    — both are improvements that close this issue more permanently."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "backtester" / "backtest_controller.py").read_text()
    # The catch wraps both compute_signals and generate_signals. If the
    # source no longer has both `signals = []` lines (initial + reset),
    # the structure changed and this test should be updated.
    assert "Alpha signal generation error" in src, (
        "The error-message string in backtest_controller is missing. "
        "Either the bare-except was removed (better!) or the error "
        "message was changed (re-check for tz-comparison bugs in edges)."
    )
