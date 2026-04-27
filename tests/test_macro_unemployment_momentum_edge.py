"""
tests/test_macro_unemployment_momentum_edge.py
==============================================
Tests for the unemployment-momentum regime-tilt edge.

Empty cache → zeros across the universe (no exceptions). Beyond that,
verify the rising/falling/neutral mapping and that the threshold is
derived from the cache's own stdev of 3m changes.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.macro_unemployment_momentum_edge import (
    MacroUnemploymentMomentumEdge,
)


@pytest.fixture
def synthetic_data_map() -> dict:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {"AAPL": df, "MSFT": df, "NVDA": df}


def _seed_edge(edge: MacroUnemploymentMomentumEdge, momentum_values: list[float],
               start: str = "2020-01-01") -> None:
    """Skip cache load — install a known momentum series + stdev."""
    idx = pd.date_range(start, periods=len(momentum_values), freq="MS")
    series = pd.Series(momentum_values, index=idx, dtype=float)
    edge._momentum_cache = series
    edge._cache_loaded = True
    edge._stdev = float(series.std(ddof=0))


# ---------------------------------------------------------------------------
# Empty-cache contract
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    edge._momentum_cache = None
    edge._cache_loaded = True
    edge._stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))

    assert set(scores.keys()) == set(synthetic_data_map.keys())
    assert all(v == 0.0 for v in scores.values())


def test_empty_series_cache_returns_zero(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    edge._momentum_cache = pd.Series([], dtype=float)
    edge._cache_loaded = True
    edge._stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values())


def test_zero_stdev_returns_zero(synthetic_data_map):
    """If the entire history shows zero momentum, no signal."""
    edge = MacroUnemploymentMomentumEdge()
    _seed_edge(edge, [0.0, 0.0, 0.0, 0.0])
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Rising / falling / neutral mapping
# ---------------------------------------------------------------------------

def test_rising_unemployment_emits_late_cycle_tilt(synthetic_data_map):
    """Final 3m change >= +1 stdev → late-cycle bias (-0.2)."""
    edge = MacroUnemploymentMomentumEdge()
    # mean = 0, stdev ≈ 0.5; final value 0.6 > +1 stdev
    _seed_edge(edge, [-0.5, 0.0, 0.5, 0.6])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert all(v == -0.2 for v in scores.values()), scores


def test_falling_unemployment_emits_early_cycle_tilt(synthetic_data_map):
    """Final 3m change <= -1 stdev → early-cycle bias (+0.2)."""
    edge = MacroUnemploymentMomentumEdge()
    _seed_edge(edge, [0.5, 0.0, -0.5, -0.6])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert all(v == 0.2 for v in scores.values()), scores


def test_neutral_change_abstains(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    # Final value at 0 (the mean) → abstain
    _seed_edge(edge, [-0.5, 0.5, -0.3, 0.0])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert all(v == 0.0 for v in scores.values())


def test_uniform_tilt_across_universe(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    _seed_edge(edge, [-0.5, 0.0, 0.5, 0.6])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert len(set(scores.values())) == 1


# ---------------------------------------------------------------------------
# asof + edge cases
# ---------------------------------------------------------------------------

def test_asof_uses_most_recent_value(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    _seed_edge(edge, [-0.5, 0.0, 0.5, 0.6, 0.0],
               start="2024-01-01")
    # Most recent at 2024-06-01 is 2024-05-01's value (0.0) → neutral
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values()), scores


def test_now_before_first_data_point_returns_zero(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    _seed_edge(edge, [-0.5, 0.5, 0.6], start="2024-12-01")

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-01-01"))
    assert all(v == 0.0 for v in scores.values())


def test_overridden_threshold_loosens_signal(synthetic_data_map):
    edge = MacroUnemploymentMomentumEdge()
    edge.params["stdev_threshold"] = 3.0
    _seed_edge(edge, [-0.5, 0.0, 0.5, 0.6])  # +1 stdev, not 3

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-04-01"))
    assert all(v == 0.0 for v in scores.values())
