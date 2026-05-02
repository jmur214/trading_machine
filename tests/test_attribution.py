"""Unit tests for engines.engine_d_discovery.attribution.

The attribution stream is the load-bearing input for gates 2-6 after the
2026-05-02 architectural fix. These tests pin the math so future changes
(e.g. switching to a per-fill attribution scheme) surface as failures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_d_discovery.attribution import (
    treatment_effect_returns,
    per_edge_realized_pnl_returns,
    stream_sharpe,
    attribution_diagnostics,
)


def _daily_index(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-02", periods=n)


def test_treatment_effect_returns_basic_diff():
    """Canonical case: with - baseline returns the elementwise difference."""
    idx = _daily_index(10)
    with_r = pd.Series(np.linspace(0.01, 0.005, 10), index=idx)
    base_r = pd.Series(np.linspace(0.005, 0.0025, 10), index=idx)
    out = treatment_effect_returns(with_r, base_r)
    assert len(out) == 10
    np.testing.assert_allclose(out.values, with_r.values - base_r.values)


def test_treatment_effect_returns_aligns_on_index_intersection():
    """Mismatched-but-overlapping indices should align on the intersection."""
    idx_a = _daily_index(10)
    idx_b = _daily_index(12)[2:]  # last 10 days, shifted by 2
    with_r = pd.Series(np.full(10, 0.01), index=idx_a)
    base_r = pd.Series(np.full(10, 0.005), index=idx_b)
    out = treatment_effect_returns(with_r, base_r)
    common = idx_a.intersection(idx_b)
    assert len(out) == len(common)


def test_treatment_effect_empty_inputs_return_empty():
    empty = pd.Series(dtype=float)
    populated = pd.Series([0.01, 0.02], index=_daily_index(2))
    assert treatment_effect_returns(empty, populated).empty
    assert treatment_effect_returns(populated, empty).empty


def test_treatment_effect_dedupes_intra_day_snapshots():
    """When the input has duplicate dates (e.g. multi-snapshot per day),
    the diff should be computed on end-of-day values, not summed returns.
    """
    # Two same-day timestamps with different values; we want the LAST.
    timestamps = [
        pd.Timestamp("2024-01-02 09:30"),
        pd.Timestamp("2024-01-02 16:00"),
        pd.Timestamp("2024-01-03 16:00"),
    ]
    with_r = pd.Series([0.01, 0.02, 0.03], index=timestamps)
    base_r = pd.Series([0.005, 0.01, 0.015], index=timestamps)
    out = treatment_effect_returns(with_r, base_r)
    # Two unique days expected
    assert len(out) == 2
    # 0.02 - 0.01 = 0.01 (Jan 2 EOD), 0.03 - 0.015 = 0.015 (Jan 3 EOD)
    np.testing.assert_allclose(out.values, [0.01, 0.015])


def test_stream_sharpe_handles_zero_std():
    """Constant return series → Sharpe must be 0, not inf or NaN."""
    constant = pd.Series([0.01] * 50)
    assert stream_sharpe(constant) == 0.0


def test_stream_sharpe_known_sharpe():
    """Daily mean 0.001, std 0.005 → annualized ≈ 0.001/0.005 × sqrt(252)."""
    rng = np.random.RandomState(42)
    # Build a series whose realized mean/std hit a known target.
    arr = rng.normal(loc=0.001, scale=0.005, size=2520)
    s = pd.Series(arr)
    # Match formula
    expected = (s.mean() / s.std()) * np.sqrt(252)
    np.testing.assert_allclose(stream_sharpe(s), float(expected), rtol=1e-6)


def test_per_edge_realized_pnl_returns_groups_by_day():
    """Multiple fills same day → summed and divided by capital."""
    trade_log = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2024-01-02 09:30"),
            pd.Timestamp("2024-01-02 11:00"),
            pd.Timestamp("2024-01-03 09:30"),
        ],
        "edge": ["foo_v1", "foo_v1", "foo_v1"],
        "pnl": [50.0, 75.0, 200.0],
    })
    out = per_edge_realized_pnl_returns(trade_log, "foo_v1", capital=100_000.0)
    assert len(out) == 2
    # Day 1: (50 + 75) / 100_000 = 0.00125
    # Day 2: 200 / 100_000 = 0.002
    np.testing.assert_allclose(out.values, [0.00125, 0.002])


def test_per_edge_realized_pnl_returns_filters_to_edge():
    """Other edges' fills must NOT contribute."""
    trade_log = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2024-01-02 09:30"),
            pd.Timestamp("2024-01-02 11:00"),
        ],
        "edge": ["foo_v1", "bar_v1"],
        "pnl": [100.0, 999.0],
    })
    out = per_edge_realized_pnl_returns(trade_log, "foo_v1", capital=100_000.0)
    # Bar's $999 must NOT show up
    assert len(out) == 1
    np.testing.assert_allclose(out.values, [0.001])


def test_per_edge_realized_pnl_returns_empty_for_unknown_edge():
    trade_log = pd.DataFrame({
        "timestamp": [pd.Timestamp("2024-01-02")],
        "edge": ["foo_v1"],
        "pnl": [100.0],
    })
    out = per_edge_realized_pnl_returns(trade_log, "missing_edge", capital=100_000.0)
    assert out.empty


def test_per_edge_realized_pnl_returns_capital_validation():
    trade_log = pd.DataFrame({
        "timestamp": [pd.Timestamp("2024-01-02")],
        "edge": ["foo_v1"],
        "pnl": [100.0],
    })
    import pytest
    with pytest.raises(ValueError):
        per_edge_realized_pnl_returns(trade_log, "foo_v1", capital=0)
    with pytest.raises(ValueError):
        per_edge_realized_pnl_returns(trade_log, "foo_v1", capital=-1)


def test_attribution_diagnostics_shape_and_signs():
    """Sanity-check the diagnostics output for a known stream."""
    # Mostly-positive stream
    pos = pd.Series([0.001, 0.002, 0.003, -0.001, 0.005])
    diag = attribution_diagnostics(pos, capital=100_000.0)
    assert diag["n_obs"] == 5
    assert diag["mean_daily_return"] > 0
    assert diag["std_daily_return"] > 0
    assert diag["total_return"] > 0
    # max_dd should be 0 or negative
    assert diag["max_dd"] <= 0


def test_attribution_diagnostics_empty():
    diag = attribution_diagnostics(pd.Series(dtype=float), capital=100_000.0)
    assert diag["n_obs"] == 0
    assert diag["sharpe"] == 0.0
