"""Tests for the cross-section bootstrap and attribution-stream PBO
in robustness.py — both added in the 2026-05-02 architectural fix.

Pin two correctness properties:
1. `generate_cross_section_bootstrap` picks SYNCHRONIZED block-starts
   across tickers (not independent per-ticker) so cross-sectional
   correlation is preserved.
2. `bootstrap_returns_stream` + `calculate_pbo_returns_stream` operate
   on the 1-D attribution stream and return sane survival rates on
   pathological inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_d_discovery.robustness import RobustnessTester


def _make_data_map(n_tickers: int = 3, n_days: int = 250, seed: int = 0):
    """Build a `data_map` of `n_tickers` correlated tickers."""
    rng = np.random.RandomState(seed)
    days = pd.bdate_range("2024-01-02", periods=n_days)
    common_factor = rng.normal(0, 0.01, size=n_days)
    out = {}
    for i in range(n_tickers):
        # Each ticker = common factor + idiosyncratic noise
        idio = rng.normal(0, 0.005, size=n_days)
        ret = common_factor + idio
        price = 100.0 * np.cumprod(1 + ret)
        out[f"T{i}"] = pd.DataFrame({
            "Open": price, "High": price * 1.01,
            "Low": price * 0.99, "Close": price,
            "Volume": np.full(n_days, 1_000_000.0),
        }, index=days)
    return out


def test_cross_section_bootstrap_returns_correct_shape():
    tester = RobustnessTester()
    data_map = _make_data_map(n_tickers=3, n_days=200)
    paths = tester.generate_cross_section_bootstrap(
        data_map, n_paths=5, block_size=10, seed=42,
    )
    assert len(paths) == 5
    for p in paths:
        # Each path is a dict of {ticker: DataFrame}
        assert set(p.keys()) == {"T0", "T1", "T2"}
        # Each ticker has the expected length
        for t, df in p.items():
            assert len(df) > 0
            assert "Close" in df.columns


def test_cross_section_bootstrap_preserves_correlation():
    """The synchronized block-pick should yield bootstrap paths whose
    pairwise correlation is similar to the original data's pairwise
    correlation. Independent per-ticker bootstrap would destroy that.
    """
    tester = RobustnessTester()
    data_map = _make_data_map(n_tickers=3, n_days=300)

    # Original returns correlation
    orig_returns = pd.DataFrame({
        t: df["Close"].pct_change().dropna() for t, df in data_map.items()
    })
    orig_corr = orig_returns.corr().values
    orig_mean_offdiag = (orig_corr.sum() - np.trace(orig_corr)) / (3 * 3 - 3)

    paths = tester.generate_cross_section_bootstrap(
        data_map, n_paths=10, block_size=20, seed=42,
    )
    # Bootstrap paths should still have substantial mean off-diagonal corr.
    boot_offdiag = []
    for p in paths:
        boot_returns = pd.DataFrame({
            t: df["Close"].pct_change().dropna() for t, df in p.items()
        })
        c = boot_returns.corr().values
        boot_offdiag.append(
            (c.sum() - np.trace(c)) / (3 * 3 - 3)
        )
    mean_boot = float(np.mean(boot_offdiag))
    # If synchronized, the cross-correlation is preserved (within sampling
    # noise). Allow a generous tolerance — the assertion is "close to the
    # original," not "exactly equal."
    assert abs(mean_boot - orig_mean_offdiag) < 0.2, (
        f"Cross-section bootstrap should preserve correlation: "
        f"orig {orig_mean_offdiag:.3f}, boot {mean_boot:.3f}"
    )


def test_cross_section_bootstrap_reproducible():
    tester = RobustnessTester()
    data_map = _make_data_map(n_tickers=2, n_days=200)
    p1 = tester.generate_cross_section_bootstrap(
        data_map, n_paths=3, block_size=10, seed=42,
    )
    p2 = tester.generate_cross_section_bootstrap(
        data_map, n_paths=3, block_size=10, seed=42,
    )
    for path_a, path_b in zip(p1, p2):
        for ticker in path_a:
            np.testing.assert_array_equal(
                path_a[ticker]["Close"].values, path_b[ticker]["Close"].values,
            )


def test_bootstrap_returns_stream_basic():
    tester = RobustnessTester()
    rng = np.random.RandomState(0)
    stream = pd.Series(rng.normal(0, 0.01, size=500))
    out = tester.bootstrap_returns_stream(stream, n_paths=20, block_size=20)
    assert len(out) == 20
    for s in out:
        assert len(s) == len(stream)


def test_calculate_pbo_returns_stream_positive_mean():
    """Strongly positive-mean stream → high survival rate."""
    tester = RobustnessTester()
    rng = np.random.RandomState(0)
    # mean 0.001, std 0.002 → annualized Sharpe ≈ 0.5/0.002 × sqrt(252) > 0
    stream = pd.Series(rng.normal(0.001, 0.002, size=500))
    pbo = tester.calculate_pbo_returns_stream(
        stream, n_paths=100, block_size=20, seed=42,
    )
    assert pbo["n_paths"] == 100
    # With high SNR, most bootstrap paths should also have positive Sharpe
    assert pbo["survival_rate"] > 0.7


def test_calculate_pbo_returns_stream_negative_mean():
    """Strongly negative-mean stream → low survival rate."""
    tester = RobustnessTester()
    rng = np.random.RandomState(0)
    stream = pd.Series(rng.normal(-0.001, 0.002, size=500))
    pbo = tester.calculate_pbo_returns_stream(
        stream, n_paths=100, block_size=20, seed=42,
    )
    assert pbo["survival_rate"] < 0.3


def test_calculate_pbo_returns_stream_short_input():
    """Streams shorter than block_size should not crash; return n_paths=0."""
    tester = RobustnessTester()
    short = pd.Series([0.01, -0.01, 0.005])
    pbo = tester.calculate_pbo_returns_stream(
        short, n_paths=10, block_size=20,
    )
    assert pbo["n_paths"] == 0
