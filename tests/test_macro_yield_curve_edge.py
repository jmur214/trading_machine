"""
tests/test_macro_yield_curve_edge.py
=====================================
Tests for the FRED-consuming macro yield-curve edge.

The most important contract: when the FRED cache is empty (no
FINNHUB_API_KEY/FRED_API_KEY configured, or fresh clone, or a network
failure that left the cache stale), the edge MUST emit zeros for every
ticker — no exceptions, no NaN, no partial signals. Otherwise the edge
breaks any backtest that runs without macro data populated.

Other tests verify the curve-state → tilt mapping is correct (normal /
neutral / inverted) and that the threshold parameters apply.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.macro_yield_curve_edge import MacroYieldCurveEdge


@pytest.fixture
def synthetic_data_map() -> dict:
    """Minimal data_map — content doesn't matter; this edge ignores price."""
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {"AAPL": df, "MSFT": df, "NVDA": df}


# ---------------------------------------------------------------------------
# Empty-cache contract: ABSTAIN entirely.
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers(synthetic_data_map):
    """Without FRED data, the edge must emit zero for every ticker.

    This is the contract that lets the edge ship as `active` in
    `alpha_settings.prod.json` without breaking backtests that don't
    have FRED_API_KEY set.
    """
    edge = MacroYieldCurveEdge()
    # Force cache to "empty" state without touching disk
    edge._spread_cache = None
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))

    assert set(scores.keys()) == set(synthetic_data_map.keys())
    assert all(v == 0.0 for v in scores.values()), (
        f"Empty cache should produce all zeros, got {scores}"
    )


def test_empty_dataframe_cache_returns_zero(synthetic_data_map):
    """Even an empty DataFrame (parquet file with no rows) abstains."""
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series([], dtype=float)
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values())


# ---------------------------------------------------------------------------
# Curve-state → tilt mapping
# ---------------------------------------------------------------------------

def test_normal_curve_emits_bullish_tilt(synthetic_data_map):
    edge = MacroYieldCurveEdge()
    # Spread of 0.80% — well above the 0.50 normal threshold
    edge._spread_cache = pd.Series([0.80],
                                   index=pd.DatetimeIndex(["2024-05-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.3 for v in scores.values()), scores


def test_inverted_curve_emits_bearish_tilt(synthetic_data_map):
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series([-0.30],
                                   index=pd.DatetimeIndex(["2024-05-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == -0.3 for v in scores.values()), scores


def test_neutral_curve_abstains(synthetic_data_map):
    """Spread between 0 and +0.50% (the inversion and normal thresholds)
    is "neutral" — no signal. The edge is opinionated about extremes only."""
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series([0.25],  # neutral zone
                                   index=pd.DatetimeIndex(["2024-05-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values()), scores


def test_uniform_tilt_across_universe(synthetic_data_map):
    """Verify the regime-tilt semantic: every ticker receives the SAME
    score on a given bar (this is a market-timing signal, not per-ticker
    alpha). Different from cross-sectional edges."""
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series([0.80],
                                   index=pd.DatetimeIndex(["2024-05-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    unique_values = set(scores.values())
    assert len(unique_values) == 1, (
        f"Yield-curve tilt should be uniform across universe, got {scores}"
    )


# ---------------------------------------------------------------------------
# Time-series asof: edge uses most-recent value at-or-before `now`
# ---------------------------------------------------------------------------

def test_asof_uses_most_recent_value_before_now(synthetic_data_map):
    """When asked about 2024-06-15, edge should use the 2024-06-01 spread
    value (most recent at or before), not 2024-07-15."""
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series(
        [0.80, -0.30, 0.80],  # normal, inverted, normal
        index=pd.DatetimeIndex(["2024-05-01", "2024-06-01", "2024-07-01"]),
    )
    edge._cache_loaded = True

    # Mid-June: should see the 2024-06-01 inversion
    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-15"))
    assert all(v == -0.3 for v in scores.values()), (
        f"Expected bearish tilt from June 1 inversion, got {scores}"
    )


# ---------------------------------------------------------------------------
# Misconfiguration guards
# ---------------------------------------------------------------------------

def test_now_before_first_data_point_returns_zero(synthetic_data_map):
    """If `now` is before any cached data point, asof returns NaN — abstain."""
    edge = MacroYieldCurveEdge()
    edge._spread_cache = pd.Series([0.80],
                                   index=pd.DatetimeIndex(["2024-12-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-01-01"))
    assert all(v == 0.0 for v in scores.values())


def test_overridden_thresholds_are_honored(synthetic_data_map):
    """If params are tightened/loosened, the gates should respect them."""
    edge = MacroYieldCurveEdge()
    edge.params["normal_threshold"] = 1.5  # require very steep curve to call "normal"
    edge.params["inversion_threshold"] = 0.0
    edge._spread_cache = pd.Series([0.80],  # normally bullish, but threshold raised
                                   index=pd.DatetimeIndex(["2024-05-01"]))
    edge._cache_loaded = True

    scores = edge.compute_signals(synthetic_data_map, pd.Timestamp("2024-06-01"))
    assert all(v == 0.0 for v in scores.values()), (
        "0.80 spread no longer normal under threshold=1.5; should abstain"
    )
