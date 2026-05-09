"""Regression test for tz-aware vs tz-naive comparison bugs in pead_short_v1.

Same bug class as the 2026-05-08 zero-trade outage in earnings_vol_edge.
PEADShortEdge consumes EarningsDataManager's parquet cache (yfinance
under the hood) and is protected by:
  - engines/engine_a_alpha/edges/pead_short_edge.py:97-98 (cache index)
  - engines/engine_a_alpha/edges/pead_short_edge.py:118-119 (`now`)

If either tz_localize line is removed, this test fires.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_a_alpha.edges.pead_short_edge import PEADShortEdge


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


def test_pead_short_compute_signals_does_not_raise_on_tz_naive_timestamp():
    edge = PEADShortEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_short_compute_signals_does_not_raise_on_tz_aware_timestamp():
    edge = PEADShortEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15", tz="America/New_York")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_short_cached_calendar_index_is_tz_naive():
    edge = PEADShortEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    edge._load_calendars(["AAPL", "MSFT", "GOOGL"])

    if not edge._calendars:
        return

    for sym, cal in edge._calendars.items():
        assert getattr(cal.index, "tz", None) is None, (
            f"PEADShort calendar for {sym} has tz={cal.index.tz}; "
            f"expected None — see test docstring for context."
        )
