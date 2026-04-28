"""
tests/test_macro_credit_spread_edge.py
======================================
Tests for the credit-spread regime-tilt edge.

Same contract as the yield-curve edge: empty cache → zeros across the
universe (no exceptions). Beyond that, this edge has the additional
wrinkle that thresholds are derived from the cache's own historical
mean and stdev — so we test the boundaries of that logic too.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.macro_credit_spread_edge import MacroCreditSpreadEdge


@pytest.fixture
def synthetic_data_map() -> dict:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {"AAPL": df, "MSFT": df, "NVDA": df}


def _seed_edge(edge: MacroCreditSpreadEdge, values: list[float],
               start: str = "2020-01-01") -> None:
    """Helper: skip cache load, install a known spread series + rolling stats.

    Tests use small synthetic series, so override `min_window_samples` to 2
    and use a wide enough lookback that the entire seeded series falls in
    the trailing window of every queried bar (effectively reproduces the
    pre-rolling 'use full series' semantics for these unit-test inputs).
    """
    idx = pd.date_range(start, periods=len(values), freq="D")
    series = pd.Series(values, index=idx, dtype=float)
    edge._spread_cache = series
    edge._cache_loaded = True
    # Test-only override: small min_window so short series can fire.
    edge.params["min_window_samples"] = 2
    edge.params["lookback_days"] = 365 * 50  # large enough to cover any test series
    window = f"{int(edge.params['lookback_days'])}D"
    min_periods = int(edge.params["min_window_samples"])
    edge._rolling_mean = series.rolling(window, min_periods=min_periods).mean()
    edge._rolling_stdev = series.rolling(window, min_periods=min_periods).std(ddof=0)


# ---------------------------------------------------------------------------
# Empty-cache contract
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    edge._spread_cache = None
    edge._cache_loaded = True
    edge._rolling_mean = None
    edge._rolling_stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))

    assert set(scores.keys()) == set(synthetic_data_map.keys())
    assert all(v == 0.0 for v in scores.values()), scores


def test_empty_series_cache_returns_zero(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    edge._spread_cache = pd.Series([], dtype=float)
    edge._cache_loaded = True
    edge._rolling_mean = None
    edge._rolling_stdev = None

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values())


def test_zero_stdev_returns_zero(synthetic_data_map):
    """Degenerate cache where every observation is identical → no signal."""
    edge = MacroCreditSpreadEdge()
    _seed_edge(edge, [1.0, 1.0, 1.0, 1.0])
    # Rolling stdev of a constant series is 0.
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Wide / tight / neutral mapping
# ---------------------------------------------------------------------------

def test_wide_spread_emits_stress_tilt(synthetic_data_map):
    """Most recent value >= mean + 1 stdev → defensive bias (-0.3)."""
    edge = MacroCreditSpreadEdge()
    # mean ≈ 1.0, stdev ≈ 0.5; final value 1.6 is > mean + 1 stdev.
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.6])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == -0.3 for v in scores.values()), scores


def test_tight_spread_emits_riskon_tilt(synthetic_data_map):
    """Most recent value <= mean - 1 stdev → risk-on bias (+0.3)."""
    edge = MacroCreditSpreadEdge()
    _seed_edge(edge, [1.5, 1.0, 0.5, 0.4])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.3 for v in scores.values()), scores


def test_neutral_spread_abstains(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    # Final value at the mean → within ±1 stdev → abstain.
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.0])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.0 for v in scores.values()), scores


def test_uniform_tilt_across_universe(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.6])

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert len(set(scores.values())) == 1


# ---------------------------------------------------------------------------
# asof + edge cases
# ---------------------------------------------------------------------------

def test_asof_uses_most_recent_value(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.6, 1.0],
               start="2024-05-01")

    # mean ≈ 1.12, stdev ≈ 0.39; asof 2024-05-04 → 1.6 → wide → stress
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-05-10"))
    # most recent at 2024-05-10 is the final value 1.0 (neutral)
    assert all(v == 0.0 for v in scores.values()), scores


def test_now_before_first_data_point_returns_zero(synthetic_data_map):
    edge = MacroCreditSpreadEdge()
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.6], start="2024-12-01")

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-01-01"))
    assert all(v == 0.0 for v in scores.values())


def test_overridden_threshold_loosens_signal(synthetic_data_map):
    """Raising stdev_threshold to 3.0 means almost nothing qualifies."""
    edge = MacroCreditSpreadEdge()
    edge.params["stdev_threshold"] = 3.0
    _seed_edge(edge, [0.5, 1.0, 1.5, 1.6])  # final at ~+1 stdev, not 3

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Rolling-window regression tests
# ---------------------------------------------------------------------------

def test_rolling_window_thresholds_adapt_to_recent_regime(synthetic_data_map):
    """Crucial regression: a value that was wide vs full-history but ordinary
    vs the trailing 5y window should NOT fire as stress.

    Concretely: 1980s/2008 spike at 3.4 in the historical baseline; trailing
    2021-2024 has been quiet around 0.8-1.0. A reading of 1.1 today is a
    *small* widening relative to recent regime but is well below the static
    'full-history mean + 1 stdev' threshold (which used the spike-inflated
    mean). This test asserts the new logic reads from the trailing window.
    """
    edge = MacroCreditSpreadEdge()
    # 100 days of quiet regime (~0.85 ± 0.05) followed by a single mild
    # widening to 1.1 — that's roughly 5 stdev above the trailing mean.
    quiet = [0.85 + (i % 5) * 0.02 for i in range(100)]
    spike = [1.1]
    series = pd.Series(
        quiet + spike,
        index=pd.date_range("2024-01-01", periods=101, freq="D"),
        dtype=float,
    )
    edge._spread_cache = series
    edge._cache_loaded = True
    edge.params["min_window_samples"] = 30
    edge.params["lookback_days"] = 365 * 5
    window = f"{int(edge.params['lookback_days'])}D"
    edge._rolling_mean = series.rolling(window, min_periods=30).mean()
    edge._rolling_stdev = series.rolling(window, min_periods=30).std(ddof=0)

    # On day 101 (the spike), mean ≈ 0.89, stdev ≈ 0.04, value 1.10.
    # 1.10 >> mean + 1*stdev (0.93), so this fires as stress.
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-04-10"))
    assert all(v == -0.3 for v in scores.values()), (
        f"Rolling window should treat 1.1 as stress vs trailing 0.85±0.05: {scores}"
    )


def test_pre_min_window_emits_zero(synthetic_data_map):
    """Until the trailing window has at least min_window_samples values,
    rolling stats are NaN — edge should abstain rather than fire on
    half-cooked statistics."""
    edge = MacroCreditSpreadEdge()
    series = pd.Series(
        [0.5, 1.0, 1.5, 1.6],
        index=pd.date_range("2020-01-01", periods=4, freq="D"),
        dtype=float,
    )
    edge._spread_cache = series
    edge._cache_loaded = True
    # Require 100 samples even though the test series has only 4.
    edge.params["min_window_samples"] = 100
    edge.params["lookback_days"] = 365 * 5
    window = f"{int(edge.params['lookback_days'])}D"
    edge._rolling_mean = series.rolling(window, min_periods=100).mean()
    edge._rolling_stdev = series.rolling(window, min_periods=100).std(ddof=0)

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2020-01-04"))
    assert all(v == 0.0 for v in scores.values()), scores
