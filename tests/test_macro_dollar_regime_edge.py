"""
tests/test_macro_dollar_regime_edge.py
======================================
Tests for the dollar-regime tilt edge.

Empty cache → zeros across the universe. The two-condition gate
(momentum sign AND level vs 1y mean) means there are several
"abstain" cases beyond pure neutrality — those are tested explicitly.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.macro_dollar_regime_edge import MacroDollarRegimeEdge


@pytest.fixture
def synthetic_data_map() -> dict:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {"AAPL": df, "MSFT": df, "NVDA": df}


def _seed_edge(edge: MacroDollarRegimeEdge, values: np.ndarray,
               start: str = "2020-01-01") -> None:
    idx = pd.date_range(start, periods=len(values), freq="D")
    edge._series_cache = pd.Series(values, index=idx, dtype=float)
    edge._cache_loaded = True


def _short_window_edge() -> MacroDollarRegimeEdge:
    """Edge with shrunk windows so unit tests don't need 252+63 data points."""
    edge = MacroDollarRegimeEdge()
    edge.params["level_window_days"] = 20
    edge.params["momentum_window_days"] = 5
    return edge


# ---------------------------------------------------------------------------
# Empty-cache contract
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers(synthetic_data_map):
    edge = MacroDollarRegimeEdge()
    edge._series_cache = None
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))

    assert set(scores.keys()) == set(synthetic_data_map.keys())
    assert all(v == 0.0 for v in scores.values())


def test_empty_series_cache_returns_zero(synthetic_data_map):
    edge = MacroDollarRegimeEdge()
    edge._series_cache = pd.Series([], dtype=float)
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values())


def test_insufficient_history_returns_zero(synthetic_data_map):
    """Not enough data for level + momentum windows → abstain."""
    edge = MacroDollarRegimeEdge()  # default windows: 252 + 63
    _seed_edge(edge, np.linspace(100, 110, 30))  # only 30 points

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2030-06-01"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Strong / weak / mixed regimes
# ---------------------------------------------------------------------------

def test_strong_dollar_regime_emits_negative_tilt(synthetic_data_map):
    """Sustained uptrend: momentum > 0 AND current > 1y mean → -0.2."""
    edge = _short_window_edge()
    # 30-day monotonic uptrend; final value is well above 20d mean and above
    # the 5d-prior value.
    values = np.linspace(100.0, 130.0, 30)
    _seed_edge(edge, values)

    last_idx = pd.Timestamp("2020-01-01") + pd.Timedelta(days=29)
    scores = edge.compute_signals(synthetic_data_map, last_idx)
    assert all(v == -0.2 for v in scores.values()), scores


def test_weak_dollar_regime_emits_positive_tilt(synthetic_data_map):
    """Sustained downtrend: momentum < 0 AND current < 1y mean → +0.2."""
    edge = _short_window_edge()
    values = np.linspace(130.0, 100.0, 30)
    _seed_edge(edge, values)

    last_idx = pd.Timestamp("2020-01-01") + pd.Timedelta(days=29)
    scores = edge.compute_signals(synthetic_data_map, last_idx)
    assert all(v == 0.2 for v in scores.values()), scores


def test_mixed_regime_abstains(synthetic_data_map):
    """Momentum positive but level below mean → no clear regime → abstain."""
    edge = _short_window_edge()
    # First 20 high, last 10 low but turning back up at the very end.
    values = np.concatenate([
        np.full(20, 130.0),
        np.full(5, 100.0),
        np.linspace(100.0, 105.0, 5),  # recent uptick
    ])
    _seed_edge(edge, values)

    last_idx = pd.Timestamp("2020-01-01") + pd.Timedelta(days=len(values) - 1)
    scores = edge.compute_signals(synthetic_data_map, last_idx)
    # Most-recent 5d momentum is +5, but current (105) is well below 20d mean
    # → mixed → abstain.
    assert all(v == 0.0 for v in scores.values()), scores


def test_uniform_tilt_across_universe(synthetic_data_map):
    edge = _short_window_edge()
    values = np.linspace(100.0, 130.0, 30)
    _seed_edge(edge, values)

    last_idx = pd.Timestamp("2020-01-01") + pd.Timedelta(days=29)
    scores = edge.compute_signals(synthetic_data_map, last_idx)
    assert len(set(scores.values())) == 1


# ---------------------------------------------------------------------------
# asof + edge cases
# ---------------------------------------------------------------------------

def test_now_before_first_data_point_returns_zero(synthetic_data_map):
    edge = _short_window_edge()
    values = np.linspace(100.0, 130.0, 30)
    _seed_edge(edge, values, start="2024-12-01")

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-01"))
    assert all(v == 0.0 for v in scores.values())


def test_no_lookahead_uses_only_past_data(synthetic_data_map):
    """Verify the edge only uses data at-or-before `now`, not the full series."""
    edge = _short_window_edge()
    # First 30 days flat-low, then a sudden surge — but we ask about a date
    # before the surge.
    values = np.concatenate([
        np.full(30, 100.0),  # flat
        np.full(30, 200.0),  # surge
    ])
    _seed_edge(edge, values, start="2020-01-01")

    # Ask about day 25 — only the flat history is visible.
    asof = pd.Timestamp("2020-01-01") + pd.Timedelta(days=25)
    scores = edge.compute_signals(synthetic_data_map, asof)
    # Flat → momentum 0, current == mean → no regime.
    assert all(v == 0.0 for v in scores.values()), scores
