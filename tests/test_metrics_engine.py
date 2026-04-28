"""
tests/test_metrics_engine.py
=============================
Tests for ``core.metrics_engine.MetricsEngine`` — the centralized
performance-metric calculator used by Research, Backtesting, and the
Discovery validation gauntlet.

Critical because:
- ``calculate_all`` is called inside Gate 1 of `validate_candidate` for
  every discovery candidate, and inside `MetricsEngine.cagr` is the
  ``(end - start).days`` operation that previously crashed silently when
  callers built equity curves without datetime indices (commit dda474c).
- Several Sharpe/CAGR computations have known-pathological edge cases
  (constant series, single-bar curves, negative-return paths). These
  tests lock in the current behavior so future refactors don't regress
  the validation gauntlet's pass/fail decisions.
- No prior test file existed despite the module being foundational.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.metrics_engine import MetricsEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_range(n_days: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n_days, freq="D")


def _flat_curve(n_days: int = 252, value: float = 100.0) -> pd.Series:
    return pd.Series([value] * n_days, index=_date_range(n_days))


def _linear_growth_curve(
    n_days: int = 252,
    start: float = 100.0,
    daily_return: float = 0.001,
) -> pd.Series:
    """Geometric daily growth — returns are exactly daily_return every day."""
    prices = [start]
    for _ in range(n_days - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return pd.Series(prices, index=_date_range(n_days))


def _random_walk_curve(
    n_days: int = 252,
    start: float = 100.0,
    daily_return_mean: float = 0.0005,
    daily_return_std: float = 0.01,
    seed: int = 42,
) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(daily_return_mean, daily_return_std, size=n_days)
    prices = [start]
    for r in rets[1:]:
        prices.append(prices[-1] * (1 + r))
    return pd.Series(prices, index=_date_range(n_days))


# ---------------------------------------------------------------------------
# calculate_all — top-level orchestrator
# ---------------------------------------------------------------------------

def test_calculate_all_empty_series_returns_empty_metrics():
    metrics = MetricsEngine.calculate_all(pd.Series([], dtype=float))
    assert all(v == 0.0 for v in metrics.values())


def test_calculate_all_single_bar_returns_empty_metrics():
    """One bar → can't compute returns → empty metrics."""
    s = pd.Series([100.0], index=_date_range(1))
    metrics = MetricsEngine.calculate_all(s)
    assert all(v == 0.0 for v in metrics.values())


def test_calculate_all_constant_curve_returns_empty_metrics():
    """Zero variance → empty metrics (avoids divide-by-zero)."""
    metrics = MetricsEngine.calculate_all(_flat_curve(50))
    assert all(v == 0.0 for v in metrics.values())


def test_calculate_all_perfectly_constant_growth_returns_empty():
    """Geometric constant growth produces returns whose std is mathematically
    zero. calculate_all's `returns.std() == 0` guard fires (despite tiny
    floating-point noise) and short-circuits to empty_metrics. This is the
    expected behavior — the guard exists to avoid divide-by-zero
    downstream — even though "the curve grew 29%" is true.
    """
    curve = _linear_growth_curve(252, 100.0, 0.001)
    metrics = MetricsEngine.calculate_all(curve)
    # The guard fires because returns are bit-identical floats (std == 0).
    assert metrics["Total Return %"] == 0.0


def test_calculate_all_noisy_growth_produces_finite_metrics():
    """A realistic noisy upward-trending curve produces finite metrics."""
    curve = _random_walk_curve(252, 100.0, daily_return_mean=0.001, daily_return_std=0.005)
    metrics = MetricsEngine.calculate_all(curve)
    for k, v in metrics.items():
        assert math.isfinite(v), f"Metric {k} = {v} is not finite"
    assert metrics["Total Return %"] > 0
    assert metrics["Sharpe"] > 0


def test_calculate_all_returns_expected_keys():
    """Output schema is stable — downstream callers depend on these keys."""
    curve = _random_walk_curve()
    metrics = MetricsEngine.calculate_all(curve)
    expected_keys = {
        "Total Return %", "CAGR %", "Sharpe", "Sortino",
        "Max Drawdown %", "Calmar", "Volatility %", "VaR 95%",
        "Beta", "Alpha",
    }
    assert set(metrics.keys()) == expected_keys


def test_calculate_all_with_benchmark_computes_beta_alpha():
    """When benchmark provided, beta and alpha should be non-trivial."""
    strategy = _random_walk_curve(252, daily_return_std=0.012, seed=1)
    benchmark = _random_walk_curve(252, daily_return_std=0.010, seed=2)
    metrics = MetricsEngine.calculate_all(strategy, benchmark)
    assert math.isfinite(metrics["Beta"])
    assert math.isfinite(metrics["Alpha"])


def test_calculate_all_without_benchmark_zero_beta_alpha():
    metrics = MetricsEngine.calculate_all(_random_walk_curve(50))
    assert metrics["Beta"] == 0.0
    assert metrics["Alpha"] == 0.0


def test_calculate_all_int_index_raises_or_handles():
    """Regression: equity curve with RangeIndex (int) used to crash inside
    cagr() with `'int' object has no attribute 'days'`. The current
    behavior is to raise that AttributeError — we lock it in here so that
    if someone wraps cagr in try/except in the future, the test fails
    and forces them to think about whether silent-default is right.

    The proper fix is for callers to provide a datetime index (the bug
    fix in dda474c added that to discovery.py:651 and again at line 806).
    """
    s = pd.Series([100.0, 101.0, 102.0, 99.0, 100.5])  # RangeIndex (int)
    with pytest.raises(AttributeError, match="'int' object has no attribute 'days'"):
        MetricsEngine.calculate_all(s)


# ---------------------------------------------------------------------------
# sharpe_ratio
# ---------------------------------------------------------------------------

def test_sharpe_zero_for_exactly_zero_returns():
    """All-zero returns → std exactly 0 → guard fires → 0.0."""
    rets = pd.Series([0.0] * 100)
    assert MetricsEngine.sharpe_ratio(rets) == 0.0


def test_sharpe_known_floating_point_edge_case_for_constant_positive_returns():
    """Constant positive returns produce a non-zero std due to float
    representation (e.g. ~1e-19) so the `returns.std() == 0` guard does
    NOT fire. Result: huge / unstable Sharpe.

    This is documented as a known degenerate edge case rather than a
    fix — production data never produces exactly-constant returns. If
    we ever want to harden the guard, change `== 0` to `< 1e-10` or
    similar; that's a behavior change requiring user approval.
    """
    rets = pd.Series([0.001] * 100)
    sharpe = MetricsEngine.sharpe_ratio(rets)
    # Either the guard fires (returns 0) or we get a huge unstable number.
    # Both are "wrong" in different ways; lock in current behavior.
    assert sharpe == 0.0 or abs(sharpe) > 1e10


def test_sharpe_positive_for_positive_drift():
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.001, 0.01, size=252))
    sharpe = MetricsEngine.sharpe_ratio(rets)
    assert sharpe > 0


def test_sharpe_negative_for_negative_drift():
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(-0.001, 0.01, size=252))
    sharpe = MetricsEngine.sharpe_ratio(rets)
    assert sharpe < 0


def test_sharpe_annualization_period_factor():
    """Sharpe with periods=252 should be sqrt(252) × Sharpe with periods=1."""
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.001, 0.01, size=252))
    daily_sharpe = MetricsEngine.sharpe_ratio(rets, periods=1)
    annualized = MetricsEngine.sharpe_ratio(rets, periods=252)
    assert annualized == pytest.approx(daily_sharpe * np.sqrt(252), rel=1e-6)


def test_sharpe_risk_free_rate_lowers_score():
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.001, 0.01, size=252))
    sharpe_no_rf = MetricsEngine.sharpe_ratio(rets, risk_free_rate=0.0)
    sharpe_with_rf = MetricsEngine.sharpe_ratio(rets, risk_free_rate=0.0005)
    assert sharpe_with_rf < sharpe_no_rf


# ---------------------------------------------------------------------------
# sortino_ratio
# ---------------------------------------------------------------------------

def test_sortino_caps_at_10_when_no_downside():
    """All-positive returns → no downside variance → cap at 10.0."""
    rets = pd.Series([0.01, 0.02, 0.03, 0.005, 0.015])
    s = MetricsEngine.sortino_ratio(rets)
    assert s == 10.0


def test_sortino_caps_at_10_when_downside_zero_variance():
    """If downside returns are all zero (no variance), cap at 10.0."""
    rets = pd.Series([0.01, 0.02, 0.0, 0.0, 0.005])
    s = MetricsEngine.sortino_ratio(rets)
    assert s == 10.0


def test_sortino_distinguishes_from_sharpe_on_asymmetric_returns():
    """Skewed-positive distribution: Sortino should exceed Sharpe."""
    # Mostly small positives, with occasional small negatives
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0.002, 0.005, size=252))
    rets[rets < -0.005] = -0.005  # cap downside
    sharpe = MetricsEngine.sharpe_ratio(rets)
    sortino = MetricsEngine.sortino_ratio(rets)
    assert sortino >= sharpe


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

def test_max_drawdown_zero_for_monotone_uptrend():
    curve = pd.Series([100, 101, 102, 103, 105])
    assert MetricsEngine.max_drawdown(curve) == 0.0


def test_max_drawdown_negative_for_decline():
    """Drawdown convention: negative number (e.g. -0.15 = -15%)."""
    curve = pd.Series([100, 110, 120, 100, 90])  # peak 120 → trough 90 = -25%
    dd = MetricsEngine.max_drawdown(curve)
    assert dd == pytest.approx(-0.25)


def test_max_drawdown_recovery_uses_max_low():
    """Drawdown is from running max, so a lower trough later is the answer
    even if there's a prior smaller trough."""
    curve = pd.Series([100, 105, 95, 110, 80, 115])
    # Running max: 100, 105, 105, 110, 110, 115
    # DD at each: 0, 0, -9.5%, 0, -27.3%, 0
    dd = MetricsEngine.max_drawdown(curve)
    assert dd == pytest.approx(-30 / 110)


# ---------------------------------------------------------------------------
# cagr
# ---------------------------------------------------------------------------

def test_cagr_zero_for_too_short_series():
    """Less than 36 days (~0.1 year) → CAGR is 0 (avoids ridiculous values)."""
    curve = pd.Series([100, 110], index=_date_range(2))
    assert MetricsEngine.cagr(curve) == 0.0


def test_cagr_negative_one_for_total_loss():
    """If equity goes to zero (or below) over a >0.1-year span, CAGR
    returns -1 as a sentinel for total loss."""
    curve = pd.Series(
        [100.0, 0.0],
        index=pd.DatetimeIndex(["2020-01-01", "2022-12-31"]),
    )
    assert MetricsEngine.cagr(curve) == -1.0


def test_cagr_for_simple_doubling_over_one_year():
    """Equity doubled over 365 days → CAGR ≈ 100%."""
    idx = pd.DatetimeIndex(["2024-01-01", "2025-01-01"])
    curve = pd.Series([100.0, 200.0], index=idx)
    cagr = MetricsEngine.cagr(curve)
    assert cagr == pytest.approx(1.0, rel=0.01)  # ~100%


def test_cagr_handles_one_day_more_than_year():
    """365.25-day basis → just over a year produces just under doubling-rate
    when equity exactly doubles."""
    idx = pd.DatetimeIndex(["2024-01-01", "2025-01-15"])  # 380 days
    curve = pd.Series([100.0, 200.0], index=idx)
    cagr = MetricsEngine.cagr(curve)
    # 380 / 365.25 ≈ 1.040 years; total_ret = 2; cagr = 2^(1/1.04) - 1 ≈ 0.951
    assert cagr == pytest.approx(0.951, rel=0.01)


def test_cagr_raises_on_int_index():
    """Locked-in: cagr with RangeIndex raises AttributeError on .days.

    This is the bug discovery.py:651 / 806 had to fix by adding
    ``index=pd.to_datetime([h["timestamp"] for h in history])``.
    """
    curve = pd.Series([100.0, 200.0])  # default RangeIndex
    with pytest.raises(AttributeError, match="'int' object has no attribute 'days'"):
        MetricsEngine.cagr(curve)


# ---------------------------------------------------------------------------
# beta
# ---------------------------------------------------------------------------

def test_beta_one_for_identical_streams():
    rng = np.random.default_rng(42)
    s = pd.Series(rng.normal(0, 0.01, 252))
    assert MetricsEngine.beta(s, s) == pytest.approx(1.0)


def test_beta_zero_for_uncorrelated():
    rng = np.random.default_rng(42)
    s1 = pd.Series(rng.normal(0, 0.01, 1000))
    s2 = pd.Series(rng.normal(0, 0.01, 1000))
    # Independent random walks — beta should be near zero (large N)
    assert abs(MetricsEngine.beta(s1, s2)) < 0.1


def test_beta_zero_when_benchmark_constant():
    """Zero variance in benchmark → guard against divide-by-zero → 0.0."""
    s = pd.Series([0.01, 0.02, -0.01, 0.005])
    bench = pd.Series([0.005, 0.005, 0.005, 0.005])
    assert MetricsEngine.beta(s, bench) == 0.0


def test_beta_negative_for_inverse_correlation():
    rng = np.random.default_rng(42)
    s = pd.Series(rng.normal(0, 0.01, 252))
    inverse = -s
    assert MetricsEngine.beta(s, inverse) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# value_at_risk
# ---------------------------------------------------------------------------

def test_var_returns_negative_quantile_for_loss_distribution():
    """5%-VaR on N(0, 0.01) should be roughly -1.645 × 0.01 = -0.0165."""
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0, 0.01, size=10_000))
    var = MetricsEngine.value_at_risk(rets, confidence=0.95)
    # Empirical 5% quantile of standard normal × 0.01 ≈ -0.0165
    assert var == pytest.approx(-0.0165, abs=0.002)


def test_var_99_more_extreme_than_var_95():
    rng = np.random.default_rng(42)
    rets = pd.Series(rng.normal(0, 0.01, size=10_000))
    var_95 = MetricsEngine.value_at_risk(rets, 0.95)
    var_99 = MetricsEngine.value_at_risk(rets, 0.99)
    assert var_99 < var_95  # more extreme = more negative


# ---------------------------------------------------------------------------
# sqn (System Quality Number)
# ---------------------------------------------------------------------------

def test_sqn_zero_for_short_series():
    assert MetricsEngine.sqn(pd.Series([])) == 0.0
    assert MetricsEngine.sqn(pd.Series([100.0])) == 0.0


def test_sqn_zero_for_constant_pnl():
    pnl = pd.Series([100.0, 100.0, 100.0])
    assert MetricsEngine.sqn(pnl) == 0.0


def test_sqn_scales_with_sample_size():
    """SQN includes √N — same expectancy/std with more trades → higher SQN."""
    pnl_short = pd.Series([100.0, -50.0] * 10)   # N=20
    pnl_long = pd.Series([100.0, -50.0] * 100)  # N=200
    sqn_short = MetricsEngine.sqn(pnl_short)
    sqn_long = MetricsEngine.sqn(pnl_long)
    # ratio should be approximately sqrt(200/20) = sqrt(10)
    assert sqn_long == pytest.approx(sqn_short * np.sqrt(10), rel=0.05)


# ---------------------------------------------------------------------------
# kelly_fraction
# ---------------------------------------------------------------------------

def test_kelly_zero_for_zero_win_loss_ratio():
    """Defensive: don't divide by zero when win_loss_ratio = 0."""
    assert MetricsEngine.kelly_fraction(0.6, 0.0) == 0.0


def test_kelly_break_even_for_50_pct_win_rate_1to1_ratio():
    """W=0.5, R=1 → Kelly = 0.5 - 0.5/1 = 0.0 (no edge)."""
    assert MetricsEngine.kelly_fraction(0.5, 1.0) == 0.0


def test_kelly_positive_when_edge_exists():
    """W=0.6, R=1.5 → Kelly = 0.6 - 0.4/1.5 ≈ 0.333"""
    k = MetricsEngine.kelly_fraction(0.6, 1.5)
    assert k == pytest.approx(0.6 - 0.4 / 1.5, rel=1e-6)


def test_kelly_negative_when_edge_disadvantage():
    """W=0.4, R=1 → Kelly = 0.4 - 0.6/1 = -0.2 (negative — don't bet)."""
    k = MetricsEngine.kelly_fraction(0.4, 1.0)
    assert k == pytest.approx(-0.2)


# ---------------------------------------------------------------------------
# Integration: regression against the dda474c bug
# ---------------------------------------------------------------------------

def test_history_to_metrics_pipeline_with_datetime_index():
    """Mirrors what `discovery.validate_candidate` now does after the
    dda474c fix: build equity curve with datetime index, call
    calculate_all, expect finite metrics."""
    history = [
        {"timestamp": pd.Timestamp(f"2024-01-{(i % 28) + 1:02d}"), "equity": 100.0 + i}
        for i in range(60)
    ]
    equity_curve = pd.Series(
        [h["equity"] for h in history],
        index=pd.to_datetime([h["timestamp"] for h in history]),
    )
    metrics = MetricsEngine.calculate_all(equity_curve)
    for k, v in metrics.items():
        assert math.isfinite(v), f"Metric {k} = {v} is not finite"
    # Total return: 159/100 - 1 = 0.59 → 59%
    assert metrics["Total Return %"] == pytest.approx(59.0, abs=0.01)


def test_history_to_metrics_pipeline_without_datetime_index_raises():
    """The pre-dda474c shape (no datetime index) MUST raise to surface the bug
    instead of silently returning Sharpe=0.00 from an exception swallow."""
    history = [{"equity": 100.0 + i} for i in range(60)]
    bad_equity_curve = pd.Series([h["equity"] for h in history])  # int index
    with pytest.raises(AttributeError, match="'int' object has no attribute 'days'"):
        MetricsEngine.calculate_all(bad_equity_curve)
