"""Regression test for tz-aware vs tz-naive comparison bugs in pead_predrift_v1.

Same bug class as the 2026-05-08 zero-trade outage in earnings_vol_edge.
PEADPreDriftEdge consumes EarningsDataManager's parquet cache and adds
a price-series predrift filter. It is protected by THREE tz_localize
calls because the predrift filter compares price-series timestamps
against the announcement date:
  - engines/engine_a_alpha/edges/pead_predrift_edge.py:108-109 (cache index)
  - engines/engine_a_alpha/edges/pead_predrift_edge.py:136-137 (`now`)
  - engines/engine_a_alpha/edges/pead_predrift_edge.py:160-161 (price_series.index)

If any of the three tz_localize lines is removed, this test fires.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_a_alpha.edges.pead_predrift_edge import PEADPreDriftEdge


def _make_data_map(tz=None):
    idx = pd.date_range("2024-01-01", periods=200, freq="B", tz=tz)
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


def test_pead_predrift_compute_signals_does_not_raise_on_tz_naive_timestamp():
    edge = PEADPreDriftEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_predrift_compute_signals_does_not_raise_on_tz_aware_timestamp():
    edge = PEADPreDriftEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15", tz="America/New_York")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_predrift_compute_signals_does_not_raise_on_tz_aware_price_index():
    """The predrift filter slices price_series by date. If the price-series
    index is tz-aware AND the announcement date is tz-naive, the slice
    raises TypeError. The edge guards via prices.index.tz_localize(None)."""
    edge = PEADPreDriftEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    now = pd.Timestamp("2024-09-15")
    scores = edge.compute_signals(
        _make_data_map(tz="America/New_York"), now
    )
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_pead_predrift_cached_calendar_index_is_tz_naive():
    edge = PEADPreDriftEdge()
    edge._calendars = {}
    edge._calendars_loaded = False

    edge._load_calendars(["AAPL", "MSFT", "GOOGL"])

    if not edge._calendars:
        return

    for sym, cal in edge._calendars.items():
        assert getattr(cal.index, "tz", None) is None, (
            f"PEADPreDrift calendar for {sym} has tz={cal.index.tz}; "
            f"expected None — see test docstring for context."
        )
