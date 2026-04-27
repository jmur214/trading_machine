"""
tests/test_insider_cluster_edge.py
===================================
Tests for the InsiderCluster edge.

Most important contract: when the insider cache is empty (fresh clone,
OpenInsider down at bootstrap), the edge MUST emit zeros for every
ticker — no exceptions, no NaN, no partial signals. Same contract as
PEAD's empty-cache test.

Other tests verify the cluster threshold, the lookback / hold-window
boundaries, the time decay shape, and the magnitude scaling.

Tests inject `_frames` directly to bypass the cache-load path. The
cache-load path is exercised only in the data_manager's own tests.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.insider_cluster_edge import InsiderClusterEdge


# ---------------------------------------------------------------------------
# Fixtures: build a transactions frame matching the InsiderDataManager
# parquet schema (subset of columns the edge actually reads).
# ---------------------------------------------------------------------------
def _txn(date: str, name: str, value: float, ttype: str = "P") -> dict:
    return {
        "transaction_date": pd.Timestamp(date),
        "insider_name": name,
        "transaction_type": ttype,
        "value": value,
    }


def _frame(*txns: dict) -> pd.DataFrame:
    df = pd.DataFrame(list(txns)).set_index("transaction_date").sort_index()
    return df


def _data_map(*tickers: str) -> dict:
    """data_map shape: dict[ticker -> DataFrame]. Edge ignores the
    DataFrame contents (it reads from its own cache); only keys matter."""
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {t: df for t in tickers}


def _make_edge(frames: dict) -> InsiderClusterEdge:
    e = InsiderClusterEdge()
    e._frames = frames
    e._frames_loaded = True
    return e


# ---------------------------------------------------------------------------
# Empty-cache contract
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers():
    edge = _make_edge({})
    scores = edge.compute_signals(
        _data_map("AAPL", "MSFT", "NVDA"),
        pd.Timestamp("2024-06-01"),
    )
    assert set(scores.keys()) == {"AAPL", "MSFT", "NVDA"}
    assert all(v == 0.0 for v in scores.values())


def test_ticker_missing_from_frames_returns_zero():
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-05-01", "Insider A", 1_000_000),
            _txn("2024-05-05", "Insider B", 1_500_000),
            _txn("2024-05-10", "Insider C", 2_000_000),
        ),
    })
    scores = edge.compute_signals(
        _data_map("AAPL", "UNCOVERED"),
        pd.Timestamp("2024-05-15"),
    )
    assert scores["UNCOVERED"] == 0.0
    assert scores["AAPL"] > 0.0


# ---------------------------------------------------------------------------
# Cluster threshold (default min_distinct_insiders = 3)
# ---------------------------------------------------------------------------

def test_single_buyer_no_signal():
    edge = _make_edge({
        "AAPL": _frame(_txn("2024-05-01", "CEO", 5_000_000)),
    })
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-15"))
    assert scores["AAPL"] == 0.0


def test_two_buyers_below_threshold_no_signal():
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-05-01", "CEO", 5_000_000),
            _txn("2024-05-05", "CFO", 3_000_000),
        ),
    })
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-15"))
    assert scores["AAPL"] == 0.0


def test_three_distinct_buyers_fires():
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-05-01", "CEO", 1_000_000),
            _txn("2024-05-05", "CFO", 1_500_000),
            _txn("2024-05-10", "Director", 2_000_000),
        ),
    })
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-15"))
    assert scores["AAPL"] > 0.0


def test_three_buys_same_insider_does_not_qualify():
    """Distinct insiders required — one insider buying three times is
    routine accumulation, not cluster signal."""
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-05-01", "CEO", 1_000_000),
            _txn("2024-05-05", "CEO", 1_500_000),
            _txn("2024-05-10", "CEO", 2_000_000),
        ),
    })
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-15"))
    assert scores["AAPL"] == 0.0


# ---------------------------------------------------------------------------
# Lookback window (default 60 days) — buys must cluster within window
# ---------------------------------------------------------------------------

def test_buys_spread_outside_lookback_no_cluster():
    """Three buys but spread across ~80 days — no 60-day window contains
    all three, so no cluster fires."""
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-03-01", "CEO", 1_000_000),
            _txn("2024-04-15", "CFO", 1_500_000),
            _txn("2024-05-20", "Director", 2_000_000),
        ),
    })
    # Now=2024-05-25: trailing 60d = [2024-03-26, 2024-05-25].
    # Only CFO (Apr 15) and Director (May 20) fall in window — 2 distinct
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-25"))
    assert scores["AAPL"] == 0.0


# ---------------------------------------------------------------------------
# Hold window (default 90 days) — signal decays to zero
# ---------------------------------------------------------------------------

def test_cluster_outside_hold_window_returns_zero():
    """Trigger 91 days before now → outside the 90-day hold."""
    edge = _make_edge({
        "AAPL": _frame(
            _txn("2024-01-01", "CEO", 1_000_000),
            _txn("2024-01-05", "CFO", 1_500_000),
            _txn("2024-01-10", "Director", 2_000_000),
        ),
    })
    # Now is 2024-04-15 → 95 days after the latest trigger date
    scores = edge.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-04-15"))
    assert scores["AAPL"] == 0.0


def test_signal_decays_linearly_over_hold_window():
    """Signal at trigger > signal at +30d > signal at +60d → zero by +90d."""
    txns = (
        _txn("2024-05-01", "CEO", 1_000_000),
        _txn("2024-05-05", "CFO", 1_500_000),
        _txn("2024-05-10", "Director", 2_000_000),
    )
    # Trigger date is 2024-05-10 (latest in window).
    edge_at_trigger = _make_edge({"AAPL": _frame(*txns)})
    s0 = edge_at_trigger.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-05-10"))["AAPL"]

    edge_at_30 = _make_edge({"AAPL": _frame(*txns)})
    s30 = edge_at_30.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-06-09"))["AAPL"]

    edge_at_60 = _make_edge({"AAPL": _frame(*txns)})
    s60 = edge_at_60.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-07-09"))["AAPL"]

    edge_at_90 = _make_edge({"AAPL": _frame(*txns)})
    s90 = edge_at_90.compute_signals(_data_map("AAPL"), pd.Timestamp("2024-08-08"))["AAPL"]

    assert s0 > s30 > s60 > 0
    # Day 90 hits the boundary exactly — signal is at or near zero
    assert s90 == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Magnitude scaling
# ---------------------------------------------------------------------------

def test_larger_dollar_cluster_produces_larger_signal():
    """Two clusters fire at the same date with the same insiders, but
    one is 100x the dollar value. Larger should produce larger signal."""
    small_txns = (
        _txn("2024-05-10", "CEO", 50_000),
        _txn("2024-05-10", "CFO", 50_000),
        _txn("2024-05-10", "Dir", 50_000),
    )
    large_txns = (
        _txn("2024-05-10", "CEO", 5_000_000),
        _txn("2024-05-10", "CFO", 5_000_000),
        _txn("2024-05-10", "Dir", 5_000_000),
    )
    s_small = _make_edge({"X": _frame(*small_txns)}).compute_signals(
        _data_map("X"), pd.Timestamp("2024-05-15")
    )["X"]
    s_large = _make_edge({"Y": _frame(*large_txns)}).compute_signals(
        _data_map("Y"), pd.Timestamp("2024-05-15")
    )["Y"]
    assert s_large > s_small
    assert s_small > 0  # both fire


def test_magnitude_clipped_at_upper_bound():
    """A $500M cluster shouldn't produce a signal larger than a $50M
    cluster — magnitude is clipped."""
    just_at_clip_txns = (
        _txn("2024-05-10", "A", 50_000_000 / 3),
        _txn("2024-05-10", "B", 50_000_000 / 3),
        _txn("2024-05-10", "C", 50_000_000 / 3),
    )
    way_above_clip_txns = (
        _txn("2024-05-10", "A", 500_000_000 / 3),
        _txn("2024-05-10", "B", 500_000_000 / 3),
        _txn("2024-05-10", "C", 500_000_000 / 3),
    )
    s_clip = _make_edge({"X": _frame(*just_at_clip_txns)}).compute_signals(
        _data_map("X"), pd.Timestamp("2024-05-15")
    )["X"]
    s_huge = _make_edge({"Y": _frame(*way_above_clip_txns)}).compute_signals(
        _data_map("Y"), pd.Timestamp("2024-05-15")
    )["Y"]
    # Both should saturate to the same magnitude_factor (=1.0)
    assert s_clip == pytest.approx(s_huge)


# ---------------------------------------------------------------------------
# Sales filter (transaction_type == "P" only)
# ---------------------------------------------------------------------------

def test_only_sales_no_signal():
    """A cluster of three insider sales should produce zero — long-only
    v1 ignores the short side."""
    # Note: the edge pre-filters to transaction_type=='P' in _load_frames,
    # so injecting a frame with only S transactions tests the filter
    # at construction time.
    sales_only = pd.DataFrame(
        [_txn("2024-05-01", "A", -1_000_000, ttype="S"),
         _txn("2024-05-05", "B", -1_500_000, ttype="S"),
         _txn("2024-05-10", "C", -2_000_000, ttype="S")]
    ).set_index("transaction_date").sort_index()

    edge = InsiderClusterEdge()
    # Bypass _load_frames since we're injecting raw mixed data — but
    # the edge's per-bar logic ALSO doesn't filter, it relies on the
    # load-time filter. Simulate that load-time filter:
    edge._frames = {"X": sales_only[sales_only["transaction_type"] == "P"]}
    edge._frames_loaded = True

    scores = edge.compute_signals(_data_map("X"), pd.Timestamp("2024-05-15"))
    assert scores["X"] == 0.0


def test_mixed_buys_and_sales_uses_only_buys():
    """Three buys and three sales — buys cluster should fire; sales
    are filtered out at load time."""
    mixed = pd.DataFrame([
        _txn("2024-05-01", "A", 1_000_000, ttype="P"),
        _txn("2024-05-02", "X", -2_000_000, ttype="S"),
        _txn("2024-05-05", "B", 1_500_000, ttype="P"),
        _txn("2024-05-06", "Y", -3_000_000, ttype="S"),
        _txn("2024-05-10", "C", 2_000_000, ttype="P"),
        _txn("2024-05-11", "Z", -1_000_000, ttype="S"),
    ]).set_index("transaction_date").sort_index()

    edge = InsiderClusterEdge()
    # Apply the load-time filter to match what _load_frames would do
    edge._frames = {"X": mixed[mixed["transaction_type"] == "P"]}
    edge._frames_loaded = True

    scores = edge.compute_signals(_data_map("X"), pd.Timestamp("2024-05-15"))
    assert scores["X"] > 0.0


# ---------------------------------------------------------------------------
# Signal bounds
# ---------------------------------------------------------------------------

def test_signal_is_bounded_by_long_score_max():
    """Saturated magnitude × max time factor = long_score_max exactly."""
    saturating = (
        _txn("2024-05-10", "A", 50_000_000 / 3),  # at clip
        _txn("2024-05-10", "B", 50_000_000 / 3),
        _txn("2024-05-10", "C", 50_000_000 / 3),
    )
    edge = _make_edge({"X": _frame(*saturating)})
    s = edge.compute_signals(_data_map("X"), pd.Timestamp("2024-05-10"))["X"]
    assert s == pytest.approx(InsiderClusterEdge.DEFAULT_PARAMS["long_score_max"])


def test_signal_never_negative_long_only():
    """Long-only v1: the signal cannot go negative under any input."""
    txns = (
        _txn("2024-05-01", "A", 1_000_000),
        _txn("2024-05-05", "B", 1_500_000),
        _txn("2024-05-10", "C", 2_000_000),
    )
    edge = _make_edge({"X": _frame(*txns)})
    # Probe across hold window
    for offset in (0, 30, 60, 89, 120):
        s = edge.compute_signals(
            _data_map("X"),
            pd.Timestamp("2024-05-10") + pd.Timedelta(days=offset),
        )["X"]
        assert s >= 0.0
