"""
tests/test_benchmark.py
========================
Tests for `core/benchmark.py` — the SPY rolling-metrics utility used by
Discovery's Gate 1 and Governance's lifecycle gates. Critical-path code
with zero prior test coverage.

Verifies:
- BenchmarkMetrics dataclass fields and `gate_threshold` arithmetic
- `compute_benchmark_metrics` correctness on synthetic data
- LRU cache returns the same instance for repeated calls
- Empty / insufficient-data windows return safe zero-reference values
- `gate_sharpe_vs_benchmark` correctness for both pass and fail
- Filesystem fallback (raw → processed) behavior

Tests use synthetic price files via tmp_path + monkeypatch so no real
data is required and runs are fully isolated.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import benchmark as bench
from core.benchmark import (
    BenchmarkMetrics,
    compute_benchmark_metrics,
    gate_sharpe_vs_benchmark,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_synthetic_spy(data_dir: Path, ticker: str = "SPY",
                         start: str = "2021-01-01", n: int = 1000,
                         daily_drift: float = 0.0004,
                         daily_vol: float = 0.012,
                         seed: int = 42) -> Path:
    """Write a synthetic <ticker>_1d.csv at data_dir/processed/.
    Returns the file path."""
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(daily_drift, daily_vol, n)
    close = 400 * np.exp(np.cumsum(log_ret))
    dates = pd.bdate_range(start, periods=n)
    df = pd.DataFrame({"Date": dates, "Close": close})
    path = processed / f"{ticker}_1d.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Point benchmark at a tmp data directory with clean cache state."""
    bench.compute_benchmark_metrics.cache_clear()
    monkeypatch.setattr(bench, "DEFAULT_DATA_DIR", tmp_path / "processed")
    yield tmp_path
    bench.compute_benchmark_metrics.cache_clear()


# ---------------------------------------------------------------------------
# BenchmarkMetrics dataclass
# ---------------------------------------------------------------------------

def test_gate_threshold_default_margin():
    bm = BenchmarkMetrics(
        ticker="SPY", start="2021-01-01", end="2024-12-31",
        sharpe=1.0, cagr=0.10, mdd=-0.20, vol=0.15,
        total_return=0.46, n_obs=1000,
    )
    # Default margin 0.2 → threshold = sharpe - 0.2 = 0.8
    assert bm.gate_threshold() == pytest.approx(0.80)


def test_gate_threshold_custom_margin():
    bm = BenchmarkMetrics(
        ticker="SPY", start="x", end="y",
        sharpe=1.5, cagr=0.0, mdd=0.0, vol=0.0,
        total_return=0.0, n_obs=10,
    )
    assert bm.gate_threshold(margin=0.5) == pytest.approx(1.0)
    assert bm.gate_threshold(margin=0.0) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# compute_benchmark_metrics — happy path
# ---------------------------------------------------------------------------

def test_compute_benchmark_metrics_basic_fields(isolated_data):
    _write_synthetic_spy(isolated_data, n=1000)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    assert bm.ticker == "SPY"
    assert bm.start == "2021-01-01"
    assert bm.end == "2024-12-31"
    assert bm.n_obs > 100, f"expected >100 obs, got {bm.n_obs}"
    # Sharpe should be finite (positive or negative depending on rng)
    assert np.isfinite(bm.sharpe)
    # MDD is non-positive
    assert bm.mdd <= 0
    # Vol is non-negative
    assert bm.vol >= 0


def test_synthetic_uptrend_produces_positive_sharpe(isolated_data):
    """Strong positive drift should yield positive Sharpe."""
    _write_synthetic_spy(isolated_data, daily_drift=0.001, daily_vol=0.005, seed=7)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    assert bm.sharpe > 0.5, f"expected clearly positive Sharpe, got {bm.sharpe}"
    assert bm.cagr > 0, f"expected positive CAGR, got {bm.cagr}"


def test_synthetic_downtrend_produces_negative_sharpe(isolated_data):
    """Negative drift should yield negative Sharpe."""
    _write_synthetic_spy(isolated_data, daily_drift=-0.001, daily_vol=0.005, seed=8)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    assert bm.sharpe < 0, f"expected negative Sharpe, got {bm.sharpe}"
    assert bm.cagr < 0


# ---------------------------------------------------------------------------
# Empty / insufficient-data handling
# ---------------------------------------------------------------------------

def test_window_outside_data_returns_zero_reference(isolated_data):
    """Window outside available data → safe zero-reference values
    (so gates don't accidentally pass)."""
    _write_synthetic_spy(isolated_data, start="2021-01-01", n=100)
    bm = compute_benchmark_metrics("2010-01-01", "2010-12-31")
    assert bm.n_obs == 0
    assert bm.sharpe == 0.0
    assert bm.cagr == 0.0
    assert bm.mdd == 0.0


def test_single_day_window_returns_zero_reference(isolated_data):
    """Window with <2 observations can't compute Sharpe → zero-reference."""
    _write_synthetic_spy(isolated_data)
    bm = compute_benchmark_metrics("2021-01-04", "2021-01-04")
    assert bm.n_obs < 2
    assert bm.sharpe == 0.0


def test_missing_benchmark_file_raises(isolated_data):
    """No CSV at all in either processed/ or raw/ → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        compute_benchmark_metrics("2021-01-01", "2024-12-31", ticker="DOES_NOT_EXIST")


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

def test_lru_cache_reuses_result(isolated_data):
    """Same (start, end, ticker) → cached call should return identical
    BenchmarkMetrics instance (same object id under LRU semantics)."""
    _write_synthetic_spy(isolated_data)
    a = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    b = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    # functools.lru_cache returns the SAME object for the same args
    assert a is b


def test_different_windows_recompute(isolated_data):
    """Different args → different cache keys → not the same object."""
    _write_synthetic_spy(isolated_data)
    a = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    b = compute_benchmark_metrics("2022-01-01", "2024-12-31")
    assert a is not b
    # Sharpe values may differ (different windows)


# ---------------------------------------------------------------------------
# gate_sharpe_vs_benchmark
# ---------------------------------------------------------------------------

def test_gate_passes_when_edge_clearly_beats_benchmark(isolated_data):
    """Edge Sharpe well above threshold → passes."""
    _write_synthetic_spy(isolated_data, daily_drift=0.0005, daily_vol=0.012)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    high_sharpe = bm.sharpe + 1.0  # well above
    passed, threshold = gate_sharpe_vs_benchmark(
        high_sharpe, "2021-01-01", "2024-12-31",
    )
    assert passed is True
    assert threshold == pytest.approx(bm.sharpe - 0.2)


def test_gate_fails_when_edge_below_benchmark(isolated_data):
    """Edge Sharpe below threshold → fails."""
    _write_synthetic_spy(isolated_data, daily_drift=0.001, daily_vol=0.005)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    low_sharpe = bm.sharpe - 1.0  # well below threshold
    passed, threshold = gate_sharpe_vs_benchmark(
        low_sharpe, "2021-01-01", "2024-12-31",
    )
    assert passed is False
    assert threshold == pytest.approx(bm.sharpe - 0.2)


def test_gate_with_custom_margin(isolated_data):
    """A larger margin requires the edge to beat benchmark by more."""
    _write_synthetic_spy(isolated_data, daily_drift=0.0005, daily_vol=0.012)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    # Edge Sharpe exactly equals benchmark Sharpe.
    # margin=0.2 → threshold = benchmark - 0.2 → edge passes.
    # margin=-0.5 (tighter) → threshold = benchmark + 0.5 → edge fails.
    p_loose, _ = gate_sharpe_vs_benchmark(bm.sharpe, "2021-01-01", "2024-12-31", margin=0.2)
    p_tight, _ = gate_sharpe_vs_benchmark(bm.sharpe, "2021-01-01", "2024-12-31", margin=-0.5)
    assert p_loose is True
    assert p_tight is False


# ---------------------------------------------------------------------------
# Schema robustness — raw/ format fallback
# ---------------------------------------------------------------------------

def test_falls_back_to_raw_when_processed_missing(tmp_path, monkeypatch):
    """If processed/ is missing the file, the loader falls back to raw/
    with the lowercase-column / 'timestamp' schema. Verifies that the
    rename mapping in `_load_benchmark_prices` works."""
    monkeypatch.setattr(bench, "DEFAULT_DATA_DIR", tmp_path / "processed")
    bench.compute_benchmark_metrics.cache_clear()
    # No processed file
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    n = 500
    log_ret = rng.normal(0.0005, 0.01, n)
    close = 400 * np.exp(np.cumsum(log_ret))
    dates = pd.bdate_range("2022-01-01", periods=n)
    raw_df = pd.DataFrame({
        "timestamp": dates,
        "open": close, "high": close, "low": close,
        "close": close, "volume": [1_000_000] * n,
    })
    # The fallback path uses ROOT/data/raw — patch ROOT_DIR resolution
    # by monkeypatching __file__ logic. Easier: write a stub directly to
    # the parents[1] data/raw path that benchmark.py expects.
    fallback_root = Path(bench.__file__).resolve().parents[1]
    actual_raw = fallback_root / "data" / "raw"
    actual_raw.mkdir(parents=True, exist_ok=True)
    actual_raw_path = actual_raw / "_TEST_FALLBACK_1d.csv"
    raw_df.to_csv(actual_raw_path, index=False)
    try:
        bm = compute_benchmark_metrics("2022-01-01", "2024-12-31",
                                       ticker="_TEST_FALLBACK")
        assert bm.n_obs > 0
        assert np.isfinite(bm.sharpe)
    finally:
        actual_raw_path.unlink(missing_ok=True)
        bench.compute_benchmark_metrics.cache_clear()
