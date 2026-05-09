"""Regression test for tz-aware vs tz-naive comparison bugs in pead_v1.

Same bug class as the 2026-05-08 zero-trade outage in earnings_vol_edge:
yfinance returns tz-aware DatetimeIndex; comparing tz-aware cache entries
against a tz-naive `now` raises TypeError; the bare-except in
backtest_controller.py:389 swallows it; result is silent zero-signal output.

PEADEdge does NOT call yfinance directly — it consumes the parquet cache
written by EarningsDataManager (which uses yfinance under the hood). The
edge is protected by two defensive tz-localize calls:
  - engines/engine_a_alpha/edges/pead_edge.py:131-132 (cache index)
  - engines/engine_a_alpha/edges/pead_edge.py:163-164 (`now` parameter)

This test asserts compute_signals never raises a tz-comparison error,
regardless of whether `now` is tz-naive or tz-aware. If anyone removes
either tz_localize line, this test fires.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_a_alpha.edges.pead_edge import PEADEdge


def _make_data_map():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    rng = np.random.default_rng(0)
    close = 100 * (1.0 + rng.normal(0.001, 0.012, 200)).cumprod()
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )
    return {"AAPL": df}


def test_pead_compute_signals_does_not_raise_on_tz_naive_timestamp():
    """Load-bearing invariant: compute_signals must not raise a
    tz-comparison error when called with a tz-naive `now`."""
    edge = PEADEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15")  # tz-naive (production format)
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_compute_signals_does_not_raise_on_tz_aware_timestamp():
    """Symmetric robustness: tz-aware input must also not raise. The
    edge normalizes via tz_localize(None) at line 163-164."""
    edge = PEADEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15", tz="America/New_York")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_cached_calendar_index_is_tz_naive():
    """After _load_calendars runs, every cached calendar's index must
    be tz-naive. This is the structural invariant guarding against a
    future earnings-cache schema change reintroducing tz-aware entries.

    If the cache is empty (Finnhub key not set / fresh clone), there's
    nothing to verify — that's a graceful-degradation path, not a bug."""
    edge = PEADEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    edge._load_calendars(["AAPL", "MSFT", "GOOGL"])

    if not edge._calendars:
        return  # earnings cache empty — no calendars to check

    for sym, cal in edge._calendars.items():
        assert getattr(cal.index, "tz", None) is None, (
            f"PEAD calendar for {sym} has tz={cal.index.tz}; expected None. "
            f"This is the 2026-05-08 zero-trade-regression invariant for "
            f"the PEAD-family edges. A tz-aware index here will silently "
            f"kill all PEAD signals via the bare-except in "
            f"backtest_controller:389."
        )
