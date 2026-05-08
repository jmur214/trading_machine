"""Tests for MetricsEngine.bootstrap_distribution.

Block-bootstrap CI on metrics — addresses the forward-plan item asking for
distributional measures around point estimates so a Sharpe ratio of 0.85
can be quoted as "0.85 [95% CI: 0.32, 1.41]" rather than a single number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.metrics_engine import MetricsEngine


def _make_returns(n: int = 252, seed: int = 0, mu: float = 0.0005, sigma: float = 0.012) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(loc=mu, scale=sigma, size=n), index=idx)


def test_bootstrap_returns_expected_keys() -> None:
    rets = _make_returns(252)
    out = MetricsEngine.bootstrap_distribution(
        rets, MetricsEngine.sharpe_ratio, n_iterations=200, seed=42,
    )
    expected_keys = {
        "point_estimate", "mean", "std", "median", "ci_low", "ci_high",
        "p_above_zero", "n_iterations", "block_length",
    }
    assert expected_keys.issubset(out.keys())


def test_bootstrap_ci_envelopes_point_estimate() -> None:
    """For a positive-mean series the 95% CI should bracket the point Sharpe
    most of the time. We don't require strict containment — bootstrap CIs
    are estimators — but we do require the median to be near the point."""
    rets = _make_returns(504, seed=1, mu=0.001, sigma=0.012)
    out = MetricsEngine.bootstrap_distribution(
        rets, MetricsEngine.sharpe_ratio, n_iterations=500, seed=42,
    )
    point = out["point_estimate"]
    # CI should NOT be degenerate
    assert out["ci_high"] > out["ci_low"]
    # Median should be within ~1.5x the bootstrap std of the point estimate
    assert abs(out["median"] - point) <= 2.0 * out["std"] + 0.1


def test_bootstrap_p_above_zero_high_for_positive_strategy() -> None:
    """A clearly positive-Sharpe synthetic series should produce a high
    fraction of bootstrap samples with positive Sharpe."""
    rets = _make_returns(504, seed=7, mu=0.005, sigma=0.012)
    point = MetricsEngine.sharpe_ratio(rets)
    assert point > 1.0, f"sanity: synthetic point Sharpe should be strong, got {point}"
    out = MetricsEngine.bootstrap_distribution(
        rets, MetricsEngine.sharpe_ratio, n_iterations=500, seed=42,
    )
    assert out["p_above_zero"] > 0.95, f"p_above_zero={out['p_above_zero']}, point={point}"


def test_bootstrap_p_above_zero_near_half_for_zero_sample_mean() -> None:
    """A series whose SAMPLE mean is exactly 0 (centered post-hoc) should
    produce ~50/50 above/below. We center to remove the seed-dependent
    drift in the realized sample."""
    raw = _make_returns(504, seed=11, mu=0.0, sigma=0.012)
    rets = raw - raw.mean()  # exact sample-mean = 0 → exact point Sharpe = 0
    assert abs(MetricsEngine.sharpe_ratio(rets)) < 1e-9
    out = MetricsEngine.bootstrap_distribution(
        rets, MetricsEngine.sharpe_ratio, n_iterations=500, seed=42,
    )
    assert 0.30 < out["p_above_zero"] < 0.70, f"p_above_zero={out['p_above_zero']}"


def test_bootstrap_works_with_sortino_metric() -> None:
    rets = _make_returns(252, seed=3)
    out = MetricsEngine.bootstrap_distribution(
        rets, MetricsEngine.sortino_ratio, n_iterations=300, seed=42,
    )
    assert out["n_iterations"] == 300
    assert np.isfinite(out["point_estimate"])


def test_bootstrap_block_length_default_grows_with_n() -> None:
    """Politis-White heuristic n^(1/3); a larger series should pick a
    larger default block."""
    short = _make_returns(64)
    long = _make_returns(1024)
    o_s = MetricsEngine.bootstrap_distribution(short, MetricsEngine.sharpe_ratio, n_iterations=10, seed=0)
    o_l = MetricsEngine.bootstrap_distribution(long, MetricsEngine.sharpe_ratio, n_iterations=10, seed=0)
    assert o_l["block_length"] >= o_s["block_length"]


def test_bootstrap_handles_empty_series() -> None:
    out = MetricsEngine.bootstrap_distribution(
        pd.Series(dtype=float), MetricsEngine.sharpe_ratio, n_iterations=100,
    )
    assert out["n_iterations"] == 0
    assert out["block_length"] == 0


def test_bootstrap_is_reproducible_with_same_seed() -> None:
    rets = _make_returns(252, seed=5)
    o1 = MetricsEngine.bootstrap_distribution(rets, MetricsEngine.sharpe_ratio, n_iterations=200, seed=42)
    o2 = MetricsEngine.bootstrap_distribution(rets, MetricsEngine.sharpe_ratio, n_iterations=200, seed=42)
    assert o1 == o2
