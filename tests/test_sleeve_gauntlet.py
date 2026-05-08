"""Tests for engines.engine_d_discovery.sleeve_gauntlet.

The sleeve gauntlet evaluates a sleeve's PnL stream against pre-committed
Sortino + skewness + tail-ratio + upside-capture thresholds, plus kill
criteria (large MDD, flat skew, weak hit-rate × winner combo).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_d_discovery.sleeve_gauntlet import (
    SleeveCriteria, SleeveMetrics, SleeveVerdict,
    compute_sleeve_metrics, evaluate_sleeve_gauntlet,
    upside_capture, per_trade_stats,
)


# ----- Synthetic series helpers ----------------------------------- #

def _strong_positive_series(n: int = 250, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(0.002, 0.012, n), index=idx)


def _flat_series(n: int = 250, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(0.0, 0.012, n), index=idx)


def _negative_series(n: int = 250, seed: int = 2) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rng.normal(-0.003, 0.012, n), index=idx)


def _heavy_drawdown_series(n: int = 250, seed: int = 3) -> pd.Series:
    """Sequence with a single deep drawdown."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.001, 0.005, n)
    # Inject -50% over 20 days mid-series
    mid = n // 2
    rets[mid:mid + 20] = -0.035
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(rets, index=idx)


# ----- compute_sleeve_metrics ------------------------------------- #

def test_metrics_returns_zero_metrics_on_empty_series() -> None:
    m = compute_sleeve_metrics(pd.Series(dtype=float))
    assert m.n_observations == 0
    assert m.sortino == 0.0


def test_metrics_computes_sortino_for_positive_series() -> None:
    rets = _strong_positive_series()
    m = compute_sleeve_metrics(rets)
    assert m.n_observations == 250
    assert m.sortino > 1.0  # strong positive should clear 1.0


def test_metrics_negative_series_has_negative_sortino() -> None:
    rets = _negative_series()
    m = compute_sleeve_metrics(rets)
    assert m.sortino < 0.0


def test_metrics_includes_skewness_and_tail_ratio() -> None:
    rets = _strong_positive_series()
    m = compute_sleeve_metrics(rets)
    assert np.isfinite(m.skewness)
    assert m.tail_ratio >= 0


def test_metrics_upside_capture_with_benchmark() -> None:
    strat = _strong_positive_series(seed=0)
    bench = _strong_positive_series(seed=1)
    m = compute_sleeve_metrics(strat, benchmark_returns=bench)
    assert m.upside_capture > 0.0


def test_metrics_max_drawdown_is_negative() -> None:
    rets = _heavy_drawdown_series()
    m = compute_sleeve_metrics(rets)
    assert m.max_drawdown < 0.0  # signed negative


def test_metrics_per_trade_stats_populated_when_provided() -> None:
    trade_pnls = [0.5, 1.2, 3.0, -0.4, -0.6, 2.5]  # one is ≥3x (3.0 ≥ 2.0)
    m = compute_sleeve_metrics(_strong_positive_series(), trade_returns=trade_pnls)
    assert m.hit_rate == pytest.approx(4 / 6)  # 4 winners
    assert m.has_3x_bet is True


def test_metrics_bootstrap_optional() -> None:
    rets = _strong_positive_series(n=300)
    m_no_boot = compute_sleeve_metrics(rets, bootstrap_iterations=0)
    assert m_no_boot.bootstrap_sortino is None
    m_boot = compute_sleeve_metrics(rets, bootstrap_iterations=200)
    assert m_boot.bootstrap_sortino is not None
    assert "ci_low" in m_boot.bootstrap_sortino


# ----- per_trade_stats unit ------------------------------------- #

def test_per_trade_stats_handles_empty() -> None:
    out = per_trade_stats([])
    assert out["hit_rate"] is None
    assert out["has_3x_bet"] is None


def test_per_trade_stats_3x_threshold_at_2_returns_or_more() -> None:
    out = per_trade_stats([1.99])
    assert out["has_3x_bet"] is False
    out = per_trade_stats([2.0])
    assert out["has_3x_bet"] is True


def test_per_trade_stats_filters_non_finite() -> None:
    out = per_trade_stats([1.0, float("nan"), -0.5, float("inf")])
    # Only 1.0 and -0.5 counted; finite winners=1, losers=1
    assert out["hit_rate"] == pytest.approx(0.5)


# ----- upside_capture ------------------------------------------- #

def test_upside_capture_returns_zero_on_empty() -> None:
    assert upside_capture(pd.Series(dtype=float), pd.Series(dtype=float)) == 0.0


def test_upside_capture_zero_when_too_few_up_days() -> None:
    """Need ≥5 up-days in benchmark to compute meaningfully."""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    s = pd.Series([0.01] * 10, index=idx)
    b = pd.Series([0.01, 0.01, -0.01, -0.01, -0.01, -0.01, -0.01, -0.01, -0.01, -0.01], index=idx)
    # Only 2 up-days in b → returns 0
    assert upside_capture(s, b) == 0.0


def test_upside_capture_above_one_means_outperforms() -> None:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    b = pd.Series(rng.normal(0.0, 0.01, 100), index=idx)
    # Strategy is 2x benchmark
    s = b * 2.0
    cap = upside_capture(s, b)
    assert cap == pytest.approx(2.0, rel=0.05)


# ----- evaluate_sleeve_gauntlet --------------------------------- #

def _strict_criteria(name: str = "test") -> SleeveCriteria:
    return SleeveCriteria(sleeve_name=name, min_observations=10)


def test_verdict_indeterminate_for_too_few_observations() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.0,
        max_drawdown=-0.05, sharpe=1.5, n_observations=5,
    )
    crit = SleeveCriteria(sleeve_name="test", min_observations=60)
    v = evaluate_sleeve_gauntlet(metrics, crit)
    assert v.bucket == "INDETERMINATE"


def test_verdict_success_when_all_criteria_clear() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "SUCCESS"
    assert v.n_success_criteria_met == v.n_success_criteria_total
    assert v.failed_criteria == []


def test_verdict_partial_when_one_short_of_full() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=0.5,  # below 0.7 threshold
        max_drawdown=-0.10, sharpe=1.5, n_observations=120,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "PARTIAL"
    assert "upside_capture" in v.failed_criteria


def test_verdict_fail_when_kill_triggered_even_if_success_met() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.50,  # 50% MDD triggers kill > 35%
        sharpe=1.5, n_observations=120,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "FAIL"
    assert any("MDD" in k for k in v.triggered_kill_criteria)


def test_verdict_kill_on_flat_skewness() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=-0.1, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "FAIL"
    assert any("skewness" in k for k in v.triggered_kill_criteria)


def test_verdict_kill_on_low_hitrate_AND_low_winner() -> None:
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120,
        hit_rate=0.20, avg_winner=1.5,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "FAIL"
    assert any("hit_rate" in k for k in v.triggered_kill_criteria)


def test_verdict_low_hitrate_alone_does_not_kill_if_winners_big() -> None:
    """Low hit-rate + BIG winners is the moonshot pattern — should
    NOT be killed by the combined-trigger gate."""
    metrics = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120,
        hit_rate=0.20, avg_winner=5.0,  # big winners save the gate
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert v.bucket == "SUCCESS"


def test_verdict_require_3x_bet_when_specified() -> None:
    crit = SleeveCriteria(
        sleeve_name="moonshot", min_observations=10, require_min_3x_bet=True,
    )
    metrics_no_3x = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120, has_3x_bet=False,
    )
    v = evaluate_sleeve_gauntlet(metrics_no_3x, crit)
    # Now there are 5 success criteria; 4 met, 1 missed → PARTIAL
    assert v.bucket == "PARTIAL"
    assert "has_3x_bet" in v.failed_criteria

    metrics_3x = SleeveMetrics(
        sortino=2.0, skewness=1.0, tail_ratio=2.0, upside_capture=1.2,
        max_drawdown=-0.10, sharpe=1.5, n_observations=120, has_3x_bet=True,
    )
    v2 = evaluate_sleeve_gauntlet(metrics_3x, crit)
    assert v2.bucket == "SUCCESS"


def test_verdict_explanation_includes_failed_and_killed() -> None:
    metrics = SleeveMetrics(
        sortino=0.1, skewness=-0.5, tail_ratio=0.5, upside_capture=0.2,
        max_drawdown=-0.50, sharpe=0.0, n_observations=120,
    )
    v = evaluate_sleeve_gauntlet(metrics, _strict_criteria())
    assert "kills:" in v.explanation
    # Multiple kill criteria fired (sortino, MDD, skewness)
    assert len(v.triggered_kill_criteria) >= 2
