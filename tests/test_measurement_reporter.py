"""
tests/test_measurement_reporter.py
==================================
Tests for `core.measurement_reporter` — loads a run's portfolio snapshots
and computes the extended-metric ladder (PSR, IR, Calmar, Sortino, etc.).

Added 2026-05-09 evening per the metric-framework upgrade.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import measurement_reporter as mr


@pytest.fixture
def synthetic_snapshot_csv(tmp_path: Path) -> str:
    """Build a synthetic portfolio_snapshots.csv in a tmp trade-log dir.

    Returns the synthetic run_id; monkey-patches `mr.TRADE_LOGS_DIR` to point
    at the temp directory for the duration of the fixture.
    """
    run_id = "test-run-abc123"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    n = 100
    rng = np.random.default_rng(42)
    # Simulate a noisy upward equity curve from 100k
    rets = rng.normal(0.001, 0.012, n)
    equity = (1.0 + pd.Series(rets)).cumprod() * 100_000
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-02", periods=n, freq="B").strftime("%Y-%m-%d"),
        "cash": [100_000.0] * n,
        "market_value": [0.0] * n,
        "realized_pnl": [0.0] * n,
        "unrealized_pnl": [0.0] * n,
        "equity": equity.values,
        "positions": [0] * n,
        "open_pos_by_edge": ["{}"] * n,
        "run_id": [run_id] * n,
    })
    df.to_csv(run_dir / "portfolio_snapshots.csv", index=False)
    original_dir = mr.TRADE_LOGS_DIR
    mr.TRADE_LOGS_DIR = tmp_path
    yield run_id
    mr.TRADE_LOGS_DIR = original_dir


def test_load_equity_curve_returns_dated_series(synthetic_snapshot_csv):
    eq = mr.load_equity_curve(synthetic_snapshot_csv)
    assert isinstance(eq, pd.Series)
    assert isinstance(eq.index, pd.DatetimeIndex)
    assert len(eq) == 100
    assert eq.iloc[0] > 0


def test_load_equity_curve_raises_for_missing_run(tmp_path: Path):
    """Missing portfolio_snapshots.csv should fail loud, not silent."""
    original_dir = mr.TRADE_LOGS_DIR
    mr.TRADE_LOGS_DIR = tmp_path
    try:
        with pytest.raises(FileNotFoundError):
            mr.load_equity_curve("does-not-exist")
    finally:
        mr.TRADE_LOGS_DIR = original_dir


def test_compute_extended_metrics_returns_full_ladder(synthetic_snapshot_csv):
    """Output dict must contain all the new headline metrics."""
    metrics = mr.compute_extended_metrics(synthetic_snapshot_csv)
    expected_new_keys = {
        "PSR", "DSR", "Calmar", "Ulcer Index",
        "Skewness", "Excess Kurtosis", "Tail Ratio",
        "Information Ratio",
    }
    expected_existing_keys = {"Sharpe", "Sortino", "Max Drawdown %", "CAGR %"}
    keys = set(metrics.keys())
    assert expected_new_keys.issubset(keys)
    assert expected_existing_keys.issubset(keys)


def test_compute_extended_metrics_dsr_below_psr_with_high_n_trials(synthetic_snapshot_csv):
    """DSR with many trials must produce a smaller probability than PSR(SR>0)."""
    psr_only = mr.compute_extended_metrics(synthetic_snapshot_csv, n_trials_for_dsr=1)
    dsr_high = mr.compute_extended_metrics(synthetic_snapshot_csv, n_trials_for_dsr=100)
    assert dsr_high["DSR"] < psr_only["DSR"] + 1e-9
    assert psr_only["DSR"] == pytest.approx(psr_only["PSR"], abs=1e-9)


def test_render_extended_metric_summary_returns_lines(synthetic_snapshot_csv):
    metrics = mr.compute_extended_metrics(synthetic_snapshot_csv)
    lines = mr.render_extended_metric_summary(metrics)
    assert isinstance(lines, list)
    assert any("PSR" in line for line in lines)
    assert any("Information Ratio" in line for line in lines)
    assert any("Calmar" in line for line in lines)
    assert any("Tail Ratio" in line for line in lines)


def test_load_benchmark_curve_returns_none_when_csv_missing(tmp_path: Path):
    """Graceful fallback when benchmark CSV is absent — caller falls back to no-IR metrics."""
    original = mr.PROCESSED_DIR
    mr.PROCESSED_DIR = tmp_path
    try:
        result = mr.load_benchmark_curve(
            pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31"),
        )
        assert result is None
    finally:
        mr.PROCESSED_DIR = original


def test_load_benchmark_curve_scales_to_100k_starting_equity(tmp_path: Path):
    """Benchmark series must start at 100,000 for like-for-like IR vs strategy."""
    csv_path = tmp_path / "SPY_1d.csv"
    pd.DataFrame({
        "timestamp": pd.date_range("2024-01-02", periods=20, freq="B"),
        "close": np.linspace(400, 500, 20),
    }).to_csv(csv_path, index=False)
    original = mr.PROCESSED_DIR
    mr.PROCESSED_DIR = tmp_path
    try:
        bench = mr.load_benchmark_curve(
            pd.Timestamp("2024-01-02"), pd.Timestamp("2024-12-31"),
        )
        assert bench is not None
        assert bench.iloc[0] == pytest.approx(100_000.0, abs=1e-3)
        # Final value is (500/400)*100k = 125k
        assert bench.iloc[-1] == pytest.approx(125_000.0, abs=1.0)
    finally:
        mr.PROCESSED_DIR = original
