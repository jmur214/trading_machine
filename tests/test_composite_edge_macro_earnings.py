"""
tests/test_composite_edge_macro_earnings.py
============================================
Tests for macro and earnings gene types added to CompositeEdge (Step 4 of
Engine D vocabulary expansion).

Covers:
  1. _calc_macro_val returns a float from real cached FRED series.
  2. _calc_macro_val returns None gracefully for unknown indicator.
  3. _calc_macro_val returns None when as_of predates series start.
  4. unemployment_delta returns month-over-month change (float).
  5. _calc_earnings_val returns a float from real cached earnings data.
  6. _calc_earnings_val returns None when no event within lookback_days.
  7. _calc_earnings_val returns None for unknown ticker (no cache).
  8. _create_random_gene produces "macro" and "earnings" types.
  9. Gene vocabulary distribution roughly matches declared weights.
  10. CompositeEdge.compute_signals does not crash with macro/earnings genes.
"""
from __future__ import annotations

import random
import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.composite_edge import CompositeEdge
from engines.engine_d_discovery.discovery import DiscoveryEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def edge():
    return CompositeEdge(params={"genes": [], "direction": "long"})


@pytest.fixture()
def price_df():
    dates = pd.date_range("2021-01-04", "2023-12-31", freq="B")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 102.0,
            "Low": 98.0,
            "Close": 100.0 + rng.standard_normal(len(dates)).cumsum(),
            "Volume": 1_000_000,
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Macro gene tests
# ---------------------------------------------------------------------------

def test_calc_macro_yield_curve_returns_float(edge):
    val = edge._calc_macro_val(
        pd.Timestamp("2022-06-01"),
        {"type": "macro", "indicator": "yield_curve", "operator": "less", "threshold": 2.0},
    )
    assert isinstance(val, float)


def test_calc_macro_vix_returns_positive(edge):
    val = edge._calc_macro_val(
        pd.Timestamp("2022-01-15"),
        {"type": "macro", "indicator": "vix_level", "operator": "greater", "threshold": 20},
    )
    assert isinstance(val, float)
    assert val > 0


def test_calc_macro_unemployment_delta_returns_float(edge):
    val = edge._calc_macro_val(
        pd.Timestamp("2022-01-01"),
        {"type": "macro", "indicator": "unemployment_delta", "operator": "less", "threshold": 0.1},
    )
    assert isinstance(val, float)


def test_calc_macro_unknown_indicator_returns_none(edge):
    val = edge._calc_macro_val(
        pd.Timestamp("2022-01-01"),
        {"type": "macro", "indicator": "does_not_exist", "operator": "less", "threshold": 0},
    )
    assert val is None


def test_calc_macro_date_before_series_returns_none(edge):
    # T10Y2Y starts ~2000-01-03; ask for 1990 — should return None
    val = edge._calc_macro_val(
        pd.Timestamp("1985-01-01"),
        {"type": "macro", "indicator": "yield_curve", "operator": "less", "threshold": 2.0},
    )
    assert val is None


def test_calc_macro_cached_after_first_call(edge):
    gene = {"type": "macro", "indicator": "yield_curve", "operator": "less", "threshold": 2.0}
    edge._calc_macro_val(pd.Timestamp("2022-01-01"), gene)
    assert hasattr(edge, "_macro_cache")
    assert "T10Y2Y" in edge._macro_cache


# ---------------------------------------------------------------------------
# Earnings gene tests
# ---------------------------------------------------------------------------

def test_calc_earnings_aapl_returns_float(edge):
    val = edge._calc_earnings_val(
        "AAPL",
        pd.Timestamp("2022-05-15"),
        {"type": "earnings", "indicator": "eps_surprise_pct", "lookback_days": 90, "operator": "greater", "threshold": 0.05},
    )
    assert isinstance(val, float)


def test_calc_earnings_no_event_in_window_returns_none(edge):
    # Use a very short lookback (2 days) — almost certainly no event
    val = edge._calc_earnings_val(
        "AAPL",
        pd.Timestamp("2022-01-03"),
        {"type": "earnings", "indicator": "eps_surprise_pct", "lookback_days": 2, "operator": "greater", "threshold": 0.0},
    )
    assert val is None


def test_calc_earnings_unknown_ticker_returns_none(edge):
    val = edge._calc_earnings_val(
        "FAKE_TICKER_XYZ_9999",
        pd.Timestamp("2022-06-01"),
        {"type": "earnings", "indicator": "eps_surprise_pct", "lookback_days": 60, "operator": "greater", "threshold": 0.0},
    )
    assert val is None


def test_calc_earnings_cached_after_first_call(edge):
    edge._calc_earnings_val(
        "AAPL",
        pd.Timestamp("2022-05-15"),
        {"type": "earnings", "indicator": "eps_surprise_pct", "lookback_days": 90, "operator": "greater", "threshold": 0.0},
    )
    assert hasattr(edge, "_earnings_cache")
    assert "AAPL" in edge._earnings_cache


# ---------------------------------------------------------------------------
# Gene vocabulary tests
# ---------------------------------------------------------------------------

def test_create_random_gene_produces_macro():
    de = DiscoveryEngine.__new__(DiscoveryEngine)
    random.seed(0)
    types_seen = set()
    for _ in range(2000):
        types_seen.add(de._create_random_gene()["type"])
    assert "macro" in types_seen


def test_create_random_gene_produces_earnings():
    de = DiscoveryEngine.__new__(DiscoveryEngine)
    random.seed(0)
    types_seen = set()
    for _ in range(2000):
        types_seen.add(de._create_random_gene()["type"])
    assert "earnings" in types_seen


def test_gene_vocabulary_distribution():
    de = DiscoveryEngine.__new__(DiscoveryEngine)
    random.seed(123)
    counts: dict = {}
    for _ in range(5000):
        t = de._create_random_gene()["type"]
        counts[t] = counts.get(t, 0) + 1
    total = sum(counts.values())
    macro_pct = counts.get("macro", 0) / total
    earnings_pct = counts.get("earnings", 0) / total
    technical_pct = counts.get("technical", 0) / total
    # Macro should be ~10%, earnings ~5%, technical ~35%
    assert 0.07 < macro_pct < 0.13, f"macro={macro_pct:.1%}"
    assert 0.03 < earnings_pct < 0.09, f"earnings={earnings_pct:.1%}"
    assert 0.28 < technical_pct < 0.42, f"technical={technical_pct:.1%}"


# ---------------------------------------------------------------------------
# Integration: compute_signals does not crash with macro/earnings genes
# ---------------------------------------------------------------------------

def test_compute_signals_with_macro_gene_no_crash(edge, price_df):
    edge.genes = [
        {"type": "macro", "indicator": "yield_curve", "operator": "less", "threshold": 2.0}
    ]
    edge._current_data_map = {"AAPL": price_df}
    edge.regime_meta = {"trend": "bull", "volatility": "low"}
    scores = edge.compute_signals({"AAPL": price_df}, as_of=pd.Timestamp("2022-06-01"))
    assert "AAPL" in scores
    assert scores["AAPL"] in (0.0, 1.0)


def test_compute_signals_with_earnings_gene_no_crash(edge, price_df):
    edge.genes = [
        {"type": "earnings", "indicator": "eps_surprise_pct", "lookback_days": 90,
         "operator": "greater", "threshold": 0.0}
    ]
    edge._current_data_map = {"AAPL": price_df}
    edge.regime_meta = {"trend": "bull", "volatility": "low"}
    scores = edge.compute_signals({"AAPL": price_df}, as_of=pd.Timestamp("2022-06-01"))
    assert "AAPL" in scores
    assert scores["AAPL"] in (0.0, 1.0)
