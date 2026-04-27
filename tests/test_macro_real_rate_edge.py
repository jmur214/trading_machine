"""
tests/test_macro_real_rate_edge.py
==================================
Tests for the real-rate regime-tilt edge.

Empty cache → zeros (no exceptions). Continuous tilt: sign and
magnitude track the deviation from the long-run mean, clipped to
±max_tilt.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.macro_real_rate_edge import MacroRealRateEdge


@pytest.fixture
def synthetic_data_map() -> dict:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {"AAPL": df, "MSFT": df, "NVDA": df}


def _seed_edge(edge: MacroRealRateEdge, values: list[float],
               start: str = "2020-01-01") -> None:
    idx = pd.date_range(start, periods=len(values), freq="D")
    series = pd.Series(values, index=idx, dtype=float)
    edge._series_cache = series
    edge._cache_loaded = True
    edge._mean = float(series.mean())
    edge._stdev = float(series.std(ddof=0))


# ---------------------------------------------------------------------------
# Empty-cache contract
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers(synthetic_data_map):
    edge = MacroRealRateEdge()
    edge._series_cache = None
    edge._cache_loaded = True
    edge._mean = None
    edge._stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))

    assert set(scores.keys()) == set(synthetic_data_map.keys())
    assert all(v == 0.0 for v in scores.values())


def test_empty_series_cache_returns_zero(synthetic_data_map):
    edge = MacroRealRateEdge()
    edge._series_cache = pd.Series([], dtype=float)
    edge._cache_loaded = True
    edge._mean = None
    edge._stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values())


def test_zero_stdev_returns_zero(synthetic_data_map):
    edge = MacroRealRateEdge()
    _seed_edge(edge, [1.0, 1.0, 1.0, 1.0])
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Continuous tilt: sign and magnitude
# ---------------------------------------------------------------------------

def test_value_at_mean_emits_zero(synthetic_data_map):
    edge = MacroRealRateEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.0])  # mean=1.0, final=1.0
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(abs(v) < 1e-9 for v in scores.values()), scores


def test_high_real_rate_emits_negative_tilt(synthetic_data_map):
    """Value above mean → negative tilt (headwind)."""
    edge = MacroRealRateEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 2.0])  # mean=1.25, stdev≈0.56, final=2.0
    # z = (2.0 - 1.25) / 0.56 ≈ 1.34 → raw ≈ -0.20 → not clipped
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    vals = list(scores.values())
    assert all(v < 0 for v in vals)
    assert all(v == vals[0] for v in vals)
    assert all(v >= -0.3 for v in vals)  # not yet saturated


def test_low_real_rate_emits_positive_tilt(synthetic_data_map):
    edge = MacroRealRateEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 0.0])  # mean=0.75, final below
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    vals = list(scores.values())
    assert all(v > 0 for v in vals)
    assert all(v <= 0.3 for v in vals)


def test_extreme_high_clips_to_max_negative(synthetic_data_map):
    """Far above the mean (z >> 2) → tilt saturates at -max_tilt.

    Manually fix mean=0, stdev=1, final value=10 → z=10 → raw=-1.5 → clip to -0.3.
    """
    edge = MacroRealRateEdge()
    idx = pd.date_range("2020-01-01", periods=2, freq="D")
    edge._series_cache = pd.Series([0.0, 10.0], index=idx, dtype=float)
    edge._cache_loaded = True
    edge._mean = 0.0
    edge._stdev = 1.0

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-02"))
    assert all(v == -0.3 for v in scores.values()), scores


def test_extreme_low_clips_to_max_positive(synthetic_data_map):
    edge = MacroRealRateEdge()
    idx = pd.date_range("2020-01-01", periods=2, freq="D")
    edge._series_cache = pd.Series([0.0, -10.0], index=idx, dtype=float)
    edge._cache_loaded = True
    edge._mean = 0.0
    edge._stdev = 1.0

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-02"))
    assert all(v == 0.3 for v in scores.values()), scores


def test_uniform_tilt_across_universe(synthetic_data_map):
    edge = MacroRealRateEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 2.0])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert len(set(scores.values())) == 1


# ---------------------------------------------------------------------------
# asof + edge cases
# ---------------------------------------------------------------------------

def test_now_before_first_data_point_returns_zero(synthetic_data_map):
    edge = MacroRealRateEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 2.0], start="2024-12-01")

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-01-01"))
    assert all(v == 0.0 for v in scores.values())


def test_overridden_scale_amplifies_tilt(synthetic_data_map):
    """Doubling scale doubles the unclipped tilt magnitude."""
    edge = MacroRealRateEdge()
    edge.params["scale"] = 0.30
    edge.params["max_tilt"] = 1.0  # disable clipping for the test
    _seed_edge(edge, [0.5, 1.0, 1.5, 2.0])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    # Expect roughly 2x the magnitude of the default-scale case.
    vals = list(scores.values())
    assert all(v < -0.3 for v in vals), (
        f"With scale=0.3 and max_tilt=1.0, expected unclipped magnitude > 0.3, got {vals}"
    )
