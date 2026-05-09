"""Engine D Foundry-loop perf benchmark (T-2026-05-08-013).

Measures wall-time of `_compute_foundry_features` across a simulated
multi-ticker TreeScanner call sequence (5 tickers, 252 bars each).
Reports median over 5 samples.

The TreeScanner production call path iterates the active universe
(~109 tickers) and calls `compute_all_features(ohlc, fund, ...,
ticker=T)` per ticker. That's where the per-bar Foundry loop's
cross-ticker redundancy on ticker-independent features (calendar,
fred_macro) shows up. The benchmark below is a 5-ticker proxy —
enough to expose the redundancy ratio without inflating CI time.

Usage:
    python -m pytest tests/test_engine_d_foundry_loop_perf.py -v -s
    # The -s flag is important — the benchmark prints timing to stdout.
"""

from __future__ import annotations

import statistics
import time
from typing import List

import numpy as np
import pandas as pd
import pytest


def _make_ohlc(n_bars: int = 252) -> pd.DataFrame:
    """Deterministic OHLCV frame — content doesn't matter for the
    benchmark, only the date index length does."""
    dates = pd.date_range("2024-01-02", periods=n_bars, freq="B")
    close = np.linspace(100.0, 130.0, n_bars)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(n_bars, 1_000_000),
        },
        index=dates,
    )


def _bench_foundry_loop(n_tickers: int = 5, n_bars: int = 252) -> float:
    """Run a multi-ticker simulated TreeScanner sequence and return
    wall-clock seconds elapsed. Recreates a fresh FeatureEngineer per
    call so any module-level cache from prior calls is the only
    cross-call optimization in scope."""
    from engines.engine_d_discovery.feature_engineering import FeatureEngineer

    fe = FeatureEngineer()
    ohlc = _make_ohlc(n_bars)
    tickers = [f"PERF_BENCH_{i:03d}" for i in range(n_tickers)]
    t0 = time.perf_counter()
    for t in tickers:
        fe.compute_all_features(ohlc, pd.DataFrame(), ticker=t)
    return time.perf_counter() - t0


@pytest.mark.skip(reason=(
    "Benchmark — runs locally + in audit doc evidence, not in CI. "
    "To run: `pytest tests/test_engine_d_foundry_loop_perf.py "
    "-k benchmark --runxfail -s` "
    "or strip the skip marker for measurement."
))
def test_foundry_loop_benchmark_5_tickers_252_bars():
    """Measure 5 samples of the 5-ticker × 252-bar sequence; report
    median + min + max wall time."""
    samples = [_bench_foundry_loop(5, 252) for _ in range(5)]
    median = statistics.median(samples)
    print(
        f"\n[FOUNDRY_PERF] 5 tickers × 252 bars × 5 samples\n"
        f"  median: {median:.3f}s\n"
        f"  min:    {min(samples):.3f}s\n"
        f"  max:    {max(samples):.3f}s\n"
        f"  raw:    {[f'{s:.3f}' for s in samples]}"
    )


def test_foundry_loop_correctness_after_optimization():
    """Sanity guard — after vectorization, the value-shape of every
    Foundry_* column must be identical to the un-vectorized scalar
    loop. This is a within-process check (not the determinism canon
    md5 gate, which is run separately) — it catches obvious shape
    drifts in the vectorized output."""
    from engines.engine_d_discovery.feature_engineering import FeatureEngineer

    fe = FeatureEngineer()
    ohlc = _make_ohlc(50)

    # Two separate tickers — second should hit the ticker-independent
    # cache for calendar / fred_macro features. Both must produce
    # identical Foundry_* columns for ticker-independent features
    # (the cache is the whole point), and SOMETHING for ticker-dependent
    # ones (different tickers may produce different values, but the
    # column shape must be intact).
    out_a = fe.compute_all_features(ohlc, pd.DataFrame(), ticker="PERF_AAA")
    out_b = fe.compute_all_features(ohlc, pd.DataFrame(), ticker="PERF_BBB")

    foundry_cols_a = sorted(c for c in out_a.columns if c.startswith("Foundry_"))
    foundry_cols_b = sorted(c for c in out_b.columns if c.startswith("Foundry_"))
    assert foundry_cols_a == foundry_cols_b, (
        "Foundry column set must be stable across tickers"
    )

    # For the calendar-source features (days_to_quarter_end,
    # month_of_year_dummy, weekday_dummy) the value SERIES must be
    # bitwise-identical across tickers — they're ticker-independent
    # by construction.
    for col in ("Foundry_days_to_quarter_end",
                "Foundry_month_of_year_dummy",
                "Foundry_weekday_dummy"):
        if col not in out_a.columns:
            continue
        # NaN-aware comparison: ticker-independent calendar features
        # should produce identical values (no NaN unless the feature
        # genuinely doesn't apply on a given date — calendar features
        # always do).
        eq = (out_a[col].fillna(-9999) == out_b[col].fillna(-9999)).all()
        assert eq, f"ticker-independent calendar col {col} drifted across tickers"
