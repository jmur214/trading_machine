"""
tests/test_low_vol_factor_edge.py
==================================
Tests for the cross-sectional low-volatility factor edge.

Unlike `macro_yield_curve_edge` and `pead_edge`, this edge has no
external data dependency — it computes realized vol from OHLCV that's
already cached. So the "empty cache" failure mode doesn't apply.
Instead the contracts to verify are:

- Bottom-quintile selection by realized vol is correct (lowest-vol wins)
- Universe-size threshold (`min_universe`) blocks tiny-sample ranking
- Insufficient history per ticker is handled gracefully
- Bottom-quintile sizing scales correctly with universe size
- Tickers with degenerate price series (constant, NaN, etc.) don't crash
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.low_vol_factor_edge import LowVolFactorEdge


def _synth_close(start_price: float, ann_vol: float, n: int = 200,
                 seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic OHLCV-style frame with a target annualized vol."""
    rng = np.random.default_rng(seed)
    daily_ret = rng.normal(0, ann_vol / np.sqrt(252), n)
    prices = start_price * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(
        {"Close": prices},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


# ---------------------------------------------------------------------------
# Bottom-quintile selection
# ---------------------------------------------------------------------------

def test_lowest_vol_ticker_selected_in_5_universe():
    """5 tickers stratified by vol — bottom-quintile of 5 = 1 name (the
    lowest). Need to lower min_universe since default is 10."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    data_map = {
        "STABLE": _synth_close(100, 0.10),
        "CALM":   _synth_close(100, 0.15),
        "NORMAL": _synth_close(100, 0.25),
        "WILD":   _synth_close(100, 0.40),
        "CRAZY":  _synth_close(100, 0.60),
    }

    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    # Bottom 20% of 5 = 1 → only STABLE wins
    assert scores["STABLE"] == 1.0
    assert all(scores[t] == 0.0 for t in ("CALM", "NORMAL", "WILD", "CRAZY"))


def test_bottom_quintile_size_scales_with_universe():
    """Universe of 11 → bottom quintile = round(11 * 0.20) = 2."""
    edge = LowVolFactorEdge()
    data_map = {
        f"T{i}": _synth_close(100, 0.05 + i * 0.05, seed=42 + i)
        for i in range(11)
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    selected = sorted([t for t, v in scores.items() if v == 1.0])
    assert len(selected) == 2, f"expected 2 selected, got {selected}"


def test_universe_of_50_selects_10():
    """Universe of 50 → bottom 20% = 10 names."""
    edge = LowVolFactorEdge()
    data_map = {
        f"T{i:02d}": _synth_close(100, 0.05 + i * 0.01, seed=42 + i)
        for i in range(50)
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    n_selected = sum(1 for v in scores.values() if v == 1.0)
    assert n_selected == 10, f"expected 10 selected of 50 (20%), got {n_selected}"


# ---------------------------------------------------------------------------
# Universe-size threshold
# ---------------------------------------------------------------------------

def test_below_min_universe_abstains():
    """Default min_universe=10. With 5 tickers, edge should abstain."""
    edge = LowVolFactorEdge()
    data_map = {f"T{i}": _synth_close(100, 0.10 + i * 0.05) for i in range(5)}
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    assert all(v == 0.0 for v in scores.values()), (
        "Universe of 5 below default min=10; should abstain entirely"
    )


def test_at_min_universe_threshold_active():
    """At exactly min_universe, edge fires."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 10
    data_map = {f"T{i}": _synth_close(100, 0.05 + i * 0.05, seed=42 + i)
                for i in range(10)}
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    n_selected = sum(1 for v in scores.values() if v == 1.0)
    assert n_selected >= 1, "should select at least 1 at threshold"


# ---------------------------------------------------------------------------
# Insufficient history per ticker
# ---------------------------------------------------------------------------

def test_short_history_ticker_excluded_from_ranking():
    """Tickers with len(df) < lookback + 2 should be excluded but should
    not crash the ranking. They emit 0 (not in selected set)."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    data_map = {
        "FULL_LOW":  _synth_close(100, 0.10, n=200, seed=1),
        "FULL_MID":  _synth_close(100, 0.30, n=200, seed=2),
        "FULL_HIGH": _synth_close(100, 0.50, n=200, seed=3),
        "SHORT":     _synth_close(100, 0.05, n=10, seed=4),  # too short
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    # SHORT has the lowest vol BY CONSTRUCTION but has only 10 rows < lookback=30
    # → excluded from ranking → score 0
    assert scores["SHORT"] == 0.0, "short-history ticker should not be selected"
    # FULL_LOW (the actual lowest among full-history tickers) should win
    assert scores["FULL_LOW"] == 1.0


def test_missing_close_column_handled():
    """Some malformed frames may not have Close. Must not crash."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 2
    data_map = {
        "OK":  _synth_close(100, 0.10, n=100),
        "BAD": pd.DataFrame({"Volume": [1, 2, 3]}),  # no Close
    }
    # Should not raise; BAD just gets 0
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    assert scores["BAD"] == 0.0


# ---------------------------------------------------------------------------
# Edge cases — degenerate price series
# ---------------------------------------------------------------------------

def test_constant_price_ticker_excluded():
    """A ticker with zero realized vol (constant price) → std=0 → excluded
    (can't rank it without a vol value)."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    data_map = {
        "VARYING_LOW":  _synth_close(100, 0.10, n=100, seed=1),
        "VARYING_MID":  _synth_close(100, 0.30, n=100, seed=2),
        "VARYING_HIGH": _synth_close(100, 0.50, n=100, seed=3),
        "FLAT": pd.DataFrame(
            {"Close": [100.0] * 100},
            index=pd.date_range("2024-01-01", periods=100, freq="D"),
        ),
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-04-10"))
    # FLAT has zero vol → would be the lowest, but std=0 means we can't
    # compute a finite Sharpe-like rank. Edge skips it.
    assert scores["FLAT"] == 0.0
    # The actual lowest of varying tickers wins
    assert scores["VARYING_LOW"] == 1.0


# ---------------------------------------------------------------------------
# Determinism — same data + same now → same result
# ---------------------------------------------------------------------------

def test_deterministic_repeat():
    """Same inputs must produce same scores. Edge has no internal state
    that would diverge between calls."""
    edge1 = LowVolFactorEdge()
    edge1.params["min_universe"] = 3
    edge2 = LowVolFactorEdge()
    edge2.params["min_universe"] = 3
    data_map = {
        f"T{i}": _synth_close(100, 0.05 + i * 0.05, seed=42 + i)
        for i in range(8)
    }
    s1 = edge1.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    s2 = edge2.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    assert s1 == s2


# ---------------------------------------------------------------------------
# Custom params honored
# ---------------------------------------------------------------------------

def test_long_score_param_honored():
    """If long_score is changed, selected tickers emit that value."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    edge.params["long_score"] = 0.7
    data_map = {
        f"T{i}": _synth_close(100, 0.05 + i * 0.05, seed=42 + i)
        for i in range(10)
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    selected = [v for v in scores.values() if v != 0.0]
    assert all(v == 0.7 for v in selected), f"expected 0.7, got {selected}"


def test_bottom_quantile_param_honored():
    """Setting bottom_quantile=0.5 selects half the universe."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    edge.params["bottom_quantile"] = 0.50
    data_map = {
        f"T{i}": _synth_close(100, 0.05 + i * 0.05, seed=42 + i)
        for i in range(10)
    }
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-07-01"))
    n_selected = sum(1 for v in scores.values() if v != 0.0)
    assert n_selected == 5  # round(10 * 0.50) = 5


# ---------------------------------------------------------------------------
# Lowest-vol identification: across different vol regimes the winner is
# always the one with the LOWEST realized vol, not the lowest target vol.
# ---------------------------------------------------------------------------

def test_lowest_realized_vol_wins_not_lowest_target():
    """The edge ranks REALIZED vol from the price series, not any target
    parameter. Two tickers with the same target vol but different paths
    could have different realized vols; the one with lower REALIZED vol
    should be selected."""
    edge = LowVolFactorEdge()
    edge.params["min_universe"] = 3
    # Two paths with same target ann_vol=0.20 but different rng seeds
    # producing different realized values
    data_map = {
        "A": _synth_close(100, 0.20, n=100, seed=1),
        "B": _synth_close(100, 0.20, n=100, seed=2),
        "C": _synth_close(100, 0.20, n=100, seed=3),
        "D": _synth_close(100, 0.20, n=100, seed=4),
        "E": _synth_close(100, 0.20, n=100, seed=5),
    }
    # Compute realized vol manually to find the empirical lowest
    realized_vols = {}
    for k, df in data_map.items():
        log_ret = np.log(df["Close"]).diff().dropna().iloc[-30:]
        realized_vols[k] = log_ret.std() * np.sqrt(252)
    expected_winner = min(realized_vols, key=lambda k: realized_vols[k])

    scores = edge.compute_signals(data_map, pd.Timestamp("2024-04-10"))
    selected = [k for k, v in scores.items() if v != 0.0]
    assert expected_winner in selected, (
        f"expected lowest-realized-vol ({expected_winner}) to win, got {selected}"
    )
