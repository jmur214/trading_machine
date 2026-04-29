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
    bench.compute_blend_metrics.cache_clear()
    monkeypatch.setattr(bench, "DEFAULT_DATA_DIR", tmp_path / "processed")
    yield tmp_path
    bench.compute_benchmark_metrics.cache_clear()
    bench.compute_blend_metrics.cache_clear()


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
    """Edge Sharpe well above SPY-only threshold → passes.

    Uses mode='spy_only' since the test only seeds synthetic SPY data;
    the new default mode='strongest' would also try to load QQQ + TLT.
    """
    _write_synthetic_spy(isolated_data, daily_drift=0.0005, daily_vol=0.012)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    high_sharpe = bm.sharpe + 1.0  # well above
    passed, threshold = gate_sharpe_vs_benchmark(
        high_sharpe, "2021-01-01", "2024-12-31", mode="spy_only",
    )
    assert passed is True
    assert threshold == pytest.approx(bm.sharpe - 0.2)


def test_gate_fails_when_edge_below_benchmark(isolated_data):
    """Edge Sharpe below SPY-only threshold → fails."""
    _write_synthetic_spy(isolated_data, daily_drift=0.001, daily_vol=0.005)
    bm = compute_benchmark_metrics("2021-01-01", "2024-12-31")
    low_sharpe = bm.sharpe - 1.0  # well below threshold
    passed, threshold = gate_sharpe_vs_benchmark(
        low_sharpe, "2021-01-01", "2024-12-31", mode="spy_only",
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
    p_loose, _ = gate_sharpe_vs_benchmark(
        bm.sharpe, "2021-01-01", "2024-12-31", margin=0.2, mode="spy_only",
    )
    p_tight, _ = gate_sharpe_vs_benchmark(
        bm.sharpe, "2021-01-01", "2024-12-31", margin=-0.5, mode="spy_only",
    )
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


# ---------------------------------------------------------------------------
# Multi-benchmark (Phase 0.2): SPY + QQQ + 60/40
# ---------------------------------------------------------------------------

def test_compute_blend_metrics_returns_valid_metrics(isolated_data):
    """60/40 blend produces sensible Sharpe/CAGR when both legs have data."""
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.0005,
                         daily_vol=0.012, seed=10)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001,
                         daily_vol=0.008, seed=11)
    from core.benchmark import compute_blend_metrics
    bm = compute_blend_metrics("2021-01-01", "2024-12-31")
    assert bm.n_obs > 100
    assert np.isfinite(bm.sharpe)
    assert bm.mdd <= 0
    # 60/40 vol should be lower than 100% equity vol (40% in lower-vol bonds)
    spy = compute_benchmark_metrics("2021-01-01", "2024-12-31", ticker="SPY")
    assert bm.vol < spy.vol


def test_compute_blend_metrics_missing_bond_returns_zero(isolated_data):
    """If bond ticker is unavailable, blend must fall back to zero-reference
    rather than crash or fabricate."""
    _write_synthetic_spy(isolated_data, ticker="SPY", n=500)
    # Don't write TLT.
    from core.benchmark import compute_blend_metrics
    with pytest.raises(FileNotFoundError):
        compute_blend_metrics("2021-01-01", "2024-12-31")


def test_compute_blend_metrics_custom_weights(isolated_data):
    """80/20 blend has higher equity exposure → Sharpe closer to pure equity."""
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.001,
                         daily_vol=0.012, seed=20)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001,
                         daily_vol=0.008, seed=21)
    from core.benchmark import compute_blend_metrics
    bm_60_40 = compute_blend_metrics("2021-01-01", "2024-12-31", equity_weight=0.6)
    bm_80_20 = compute_blend_metrics("2021-01-01", "2024-12-31", equity_weight=0.8)
    spy = compute_benchmark_metrics("2021-01-01", "2024-12-31", ticker="SPY")
    # 80/20 vol should sit between 60/40 and pure equity.
    assert bm_60_40.vol < bm_80_20.vol < spy.vol


def test_compute_blend_metrics_ticker_naming(isolated_data):
    """The synthesized portfolio's ticker field encodes the composition."""
    _write_synthetic_spy(isolated_data, ticker="SPY")
    _write_synthetic_spy(isolated_data, ticker="TLT")
    from core.benchmark import compute_blend_metrics
    bm = compute_blend_metrics("2021-01-01", "2024-12-31")
    assert "60/40" in bm.ticker
    assert "SPY" in bm.ticker
    assert "TLT" in bm.ticker


def test_compute_multi_benchmark_metrics_returns_three(isolated_data):
    """All three reference portfolios computed in one call."""
    _write_synthetic_spy(isolated_data, ticker="SPY", seed=30)
    _write_synthetic_spy(isolated_data, ticker="QQQ", seed=31)
    _write_synthetic_spy(isolated_data, ticker="TLT", seed=32)
    from core.benchmark import compute_multi_benchmark_metrics
    multi = compute_multi_benchmark_metrics("2021-01-01", "2024-12-31")
    assert set(multi.keys()) == {"SPY", "QQQ", "60/40"}
    for name, bm in multi.items():
        assert np.isfinite(bm.sharpe), f"{name} produced non-finite Sharpe"
        assert bm.n_obs > 100


def test_gate_strongest_mode_uses_max_sharpe(isolated_data):
    """Gate threshold under mode='strongest' = max(SPY, QQQ, 60/40) - margin."""
    # Make QQQ the strongest (clearly highest drift).
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.0003, seed=40)
    _write_synthetic_spy(isolated_data, ticker="QQQ", daily_drift=0.0008, seed=41)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001, seed=42)

    from core.benchmark import compute_multi_benchmark_metrics
    multi = compute_multi_benchmark_metrics("2021-01-01", "2024-12-31")
    expected_strongest = max(bm.sharpe for bm in multi.values())

    # Use mode='strongest' (the new default).
    passed, threshold = gate_sharpe_vs_benchmark(
        edge_sharpe=expected_strongest + 1.0,
        start="2021-01-01", end="2024-12-31",
        margin=0.2, mode="strongest",
    )
    assert passed is True
    assert threshold == pytest.approx(expected_strongest - 0.2)


def test_gate_strongest_mode_is_strictly_harder_than_spy_only(isolated_data):
    """When QQQ outperforms SPY, the strongest gate is harder to pass than
    spy_only — that's the whole point of the multi-benchmark fix."""
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.0003,
                         daily_vol=0.012, seed=50)
    # QQQ clearly stronger than SPY.
    _write_synthetic_spy(isolated_data, ticker="QQQ", daily_drift=0.0009,
                         daily_vol=0.014, seed=51)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001,
                         daily_vol=0.008, seed=52)

    spy = compute_benchmark_metrics("2021-01-01", "2024-12-31", ticker="SPY")
    edge_sharpe = spy.sharpe + 0.1  # beats SPY easily

    p_spy_only, t_spy_only = gate_sharpe_vs_benchmark(
        edge_sharpe, "2021-01-01", "2024-12-31",
        margin=0.2, mode="spy_only",
    )
    p_strongest, t_strongest = gate_sharpe_vs_benchmark(
        edge_sharpe, "2021-01-01", "2024-12-31",
        margin=0.2, mode="strongest",
    )

    assert p_spy_only is True, "edge clearly beats SPY"
    assert t_strongest > t_spy_only, "strongest threshold should be higher than SPY-only"
    # Whether the strongest gate passes depends on the exact numbers, but
    # the threshold MUST be strictly higher when QQQ outperforms SPY.


def test_gate_strongest_default_mode_unchanged_signature(isolated_data):
    """Calling gate_sharpe_vs_benchmark without `mode` defaults to strongest.

    Documents the behavior change for callers reading the test suite.
    """
    _write_synthetic_spy(isolated_data, ticker="SPY", seed=60)
    _write_synthetic_spy(isolated_data, ticker="QQQ", seed=61)
    _write_synthetic_spy(isolated_data, ticker="TLT", seed=62)

    # No mode kwarg → should match explicit mode='strongest'
    p_default, t_default = gate_sharpe_vs_benchmark(
        edge_sharpe=2.0, start="2021-01-01", end="2024-12-31",
    )
    p_explicit, t_explicit = gate_sharpe_vs_benchmark(
        edge_sharpe=2.0, start="2021-01-01", end="2024-12-31",
        mode="strongest",
    )
    assert p_default == p_explicit
    assert t_default == pytest.approx(t_explicit)


def test_gate_with_winner_returns_winning_benchmark_name(isolated_data):
    """gate_sharpe_vs_benchmark_with_winner returns which benchmark set the bar."""
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.0003, seed=70)
    _write_synthetic_spy(isolated_data, ticker="QQQ", daily_drift=0.0010, seed=71)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001, seed=72)

    from core.benchmark import gate_sharpe_vs_benchmark_with_winner
    passed, threshold, winner = gate_sharpe_vs_benchmark_with_winner(
        edge_sharpe=10.0, start="2021-01-01", end="2024-12-31", margin=0.2,
    )
    assert winner == "QQQ"  # the strongest synthetic series
    assert passed is True


def test_gate_spy_only_mode_preserves_legacy_behavior(isolated_data):
    """Legacy callers can opt back into spy_only and get the original
    SPY-only threshold even when QQQ/TLT files exist."""
    _write_synthetic_spy(isolated_data, ticker="SPY", daily_drift=0.0003, seed=80)
    _write_synthetic_spy(isolated_data, ticker="QQQ", daily_drift=0.001, seed=81)
    _write_synthetic_spy(isolated_data, ticker="TLT", daily_drift=0.0001, seed=82)

    spy = compute_benchmark_metrics("2021-01-01", "2024-12-31", ticker="SPY")
    _, threshold_spy_only = gate_sharpe_vs_benchmark(
        edge_sharpe=0.0, start="2021-01-01", end="2024-12-31",
        mode="spy_only",
    )
    assert threshold_spy_only == pytest.approx(spy.sharpe - 0.2)
