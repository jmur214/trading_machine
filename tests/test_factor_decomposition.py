"""
tests/test_factor_decomposition.py
===================================
Tests for ``core/factor_decomposition.py`` — the FF5 + Momentum factor
regression module used by:
  - ``scripts/factor_decomposition_baseline.py`` (diagnostic)
  - ``engines/engine_d_discovery/discovery.py::validate_candidate`` Gate 6

Coverage:
  - regress_returns_on_factors: correctness on synthetic returns + factors
  - gate_factor_alpha: pass/fail logic at the t-stat and alpha boundaries
  - graceful handling of insufficient observations
  - graceful handling of zero-vol residuals
  - column-name and missing-RF guards
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.factor_decomposition import (
    DEFAULT_ALPHA_ANNUAL_MIN,
    DEFAULT_ALPHA_TSTAT_MIN,
    DEFAULT_FACTOR_COLS,
    FactorDecomp,
    gate_factor_alpha,
    regress_returns_on_factors,
)


# ---------------------------------------------------------------------------
# Synthetic factor + return helpers
# ---------------------------------------------------------------------------

def _synthetic_factor_panel(n: int = 252, seed: int = 0) -> pd.DataFrame:
    """Create a synthetic FF5+Mom factor panel with realistic-ish stats."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "MktRF": rng.normal(0.0003, 0.012, n),
            "SMB":   rng.normal(0.0,    0.005, n),
            "HML":   rng.normal(0.0,    0.005, n),
            "RMW":   rng.normal(0.0001, 0.004, n),
            "CMA":   rng.normal(0.0,    0.004, n),
            "Mom":   rng.normal(0.0002, 0.008, n),
            "RF":    np.full(n, 0.00005),  # ~1.25% annualized risk-free
        },
        index=dates,
    )


def _returns_with_pure_alpha(
    factors: pd.DataFrame,
    daily_alpha: float = 0.0008,    # ~20% annualized
    seed: int = 1,
) -> pd.Series:
    """Synthesize a return stream with constant alpha + zero factor exposure +
    small idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.003, len(factors))
    return pd.Series(
        factors["RF"].values + daily_alpha + noise,
        index=factors.index,
        name="alpha_only",
    )


def _returns_with_pure_factor_beta(
    factors: pd.DataFrame,
    mom_beta: float = 1.0,
    seed: int = 2,
) -> pd.Series:
    """Return stream that is purely momentum-factor exposure with a small
    alpha set to zero. Should regress to alpha ≈ 0 and Mom-beta ≈ 1."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.003, len(factors))
    return pd.Series(
        factors["RF"].values + mom_beta * factors["Mom"].values + noise,
        index=factors.index,
        name="mom_beta_only",
    )


# ---------------------------------------------------------------------------
# regress_returns_on_factors — correctness
# ---------------------------------------------------------------------------

def test_pure_alpha_recovers_intercept_and_zero_betas():
    factors = _synthetic_factor_panel(n=252)
    returns = _returns_with_pure_alpha(factors, daily_alpha=0.0008)
    decomp = regress_returns_on_factors(returns, factors, edge_name="alpha_only")

    assert decomp is not None
    # Intercept should be close to 0.0008 daily. Tolerance reflects the
    # 0.003 noise level: with 252 obs, intercept SE ≈ 0.003/√252 ≈ 1.9e-4.
    # Allow ±2σ → 4e-4. annualized = daily × 252 is purely arithmetic so
    # we don't double-test it.
    assert decomp.alpha_daily == pytest.approx(0.0008, abs=4e-4)
    assert decomp.alpha_annualized == decomp.alpha_daily * 252
    # Factor betas should all be near zero.
    for f in DEFAULT_FACTOR_COLS:
        if f in decomp.betas:
            assert abs(decomp.betas[f]) < 0.5, f"unexpected loading on {f}: {decomp.betas[f]}"
    # t-stat should be highly significant given 252 obs of clear alpha.
    assert decomp.alpha_tstat > 2.0


def test_pure_factor_beta_recovers_zero_alpha():
    factors = _synthetic_factor_panel(n=400)
    returns = _returns_with_pure_factor_beta(factors, mom_beta=1.0)
    decomp = regress_returns_on_factors(returns, factors, edge_name="mom_only")

    assert decomp is not None
    # Alpha should be near zero (no real edge — just factor exposure).
    assert abs(decomp.alpha_annualized) < 0.05  # |alpha| < 5% annualized
    # Mom beta should be near 1.0.
    assert decomp.betas["Mom"] == pytest.approx(1.0, abs=0.15)
    # R² should be moderate-to-high (returns ARE explainable by Mom).
    assert decomp.r_squared > 0.3


def test_n_obs_below_minimum_returns_none():
    factors = _synthetic_factor_panel(n=20)
    returns = _returns_with_pure_alpha(factors)
    # Default min is 30; we pass 20.
    decomp = regress_returns_on_factors(returns, factors, edge_name="too_short")
    assert decomp is None


def test_custom_minimum_observations_threshold_honored():
    factors = _synthetic_factor_panel(n=50)
    returns = _returns_with_pure_alpha(factors)
    # Lower min_observations to 30 — should produce a decomp.
    decomp = regress_returns_on_factors(
        returns, factors, edge_name="ok", min_observations=30,
    )
    assert decomp is not None
    # Higher min_observations than n_obs — should return None.
    decomp_strict = regress_returns_on_factors(
        returns, factors, edge_name="too_short", min_observations=100,
    )
    assert decomp_strict is None


def test_missing_rf_column_raises():
    factors = _synthetic_factor_panel().drop(columns=["RF"])
    returns = pd.Series([0.001] * len(factors), index=factors.index)
    with pytest.raises(ValueError, match="RF"):
        regress_returns_on_factors(returns, factors, edge_name="x")


def test_no_factor_cols_raises():
    factors = pd.DataFrame({"RF": [0.0001] * 50},
                           index=pd.date_range("2024-01-01", periods=50, freq="D"))
    returns = pd.Series([0.001] * 50, index=factors.index)
    with pytest.raises(ValueError, match="No factor columns"):
        regress_returns_on_factors(returns, factors, edge_name="x")


def test_explicit_factor_cols_subset():
    """Caller can request a subset of factor columns explicitly."""
    factors = _synthetic_factor_panel(n=300)
    returns = _returns_with_pure_alpha(factors)
    # Restrict to just MktRF + Mom.
    decomp = regress_returns_on_factors(
        returns, factors,
        factor_cols=["MktRF", "Mom"],
        edge_name="subset",
    )
    assert decomp is not None
    assert set(decomp.betas.keys()) == {"MktRF", "Mom"}


def test_misaligned_dates_use_inner_join():
    """If returns and factors have only partial overlap, the regression
    runs on the intersection and the rest is dropped."""
    factors = _synthetic_factor_panel(n=200)
    # Returns covering only the second half of factors.
    half = factors.iloc[100:].copy()
    returns = _returns_with_pure_alpha(half).rename("partial_overlap")
    decomp = regress_returns_on_factors(returns, factors, edge_name="partial")
    assert decomp is not None
    assert decomp.n_obs == 100


def test_regression_does_not_mutate_inputs():
    factors = _synthetic_factor_panel(n=100)
    returns = _returns_with_pure_alpha(factors)
    factors_before = factors.copy(deep=True)
    returns_before = returns.copy()
    _ = regress_returns_on_factors(returns, factors, edge_name="immut")
    pd.testing.assert_frame_equal(factors, factors_before)
    pd.testing.assert_series_equal(returns, returns_before)


# ---------------------------------------------------------------------------
# gate_factor_alpha — pass/fail decisions
# ---------------------------------------------------------------------------

def _make_decomp(alpha_ann: float, t: float) -> FactorDecomp:
    """Build a minimal FactorDecomp for gate-logic testing."""
    return FactorDecomp(
        edge="test", n_obs=200, raw_sharpe=1.0,
        alpha_daily=alpha_ann / 252,
        alpha_annualized=alpha_ann,
        alpha_tstat=t,
        r_squared=0.1,
        betas={f: 0.0 for f in DEFAULT_FACTOR_COLS},
    )


def test_gate_passes_with_strong_alpha():
    decomp = _make_decomp(alpha_ann=0.10, t=3.0)  # +10%/yr, t=3
    passed, reason = gate_factor_alpha(decomp)
    assert passed is True
    assert "alpha" in reason


def test_gate_fails_when_tstat_below_threshold():
    decomp = _make_decomp(alpha_ann=0.10, t=1.5)  # economically big but not significant
    passed, reason = gate_factor_alpha(decomp)
    assert passed is False
    assert "t-stat" in reason


def test_gate_fails_when_alpha_below_economic_threshold():
    decomp = _make_decomp(alpha_ann=0.01, t=10.0)  # very significant but tiny (1%)
    passed, reason = gate_factor_alpha(decomp)
    assert passed is False
    # Reason should reference the economic threshold.
    assert "%" in reason


def test_gate_fails_at_exact_tstat_threshold():
    """t-stat exactly at the threshold should fail (gate is strict >, not ≥)."""
    decomp = _make_decomp(alpha_ann=0.10, t=DEFAULT_ALPHA_TSTAT_MIN)
    passed, _ = gate_factor_alpha(decomp)
    assert passed is False


def test_gate_passes_just_above_thresholds():
    decomp = _make_decomp(
        alpha_ann=DEFAULT_ALPHA_ANNUAL_MIN + 0.001,
        t=DEFAULT_ALPHA_TSTAT_MIN + 0.01,
    )
    passed, _ = gate_factor_alpha(decomp)
    assert passed is True


def test_gate_skip_on_none_decomp_returns_pass():
    """When the regression couldn't run (insufficient data), gate is
    'skipped' and passes — don't punish candidates for diagnostic gaps."""
    passed, reason = gate_factor_alpha(None)
    assert passed is True
    assert "skipped" in reason


def test_gate_negative_alpha_fails():
    """A significantly NEGATIVE alpha must fail the gate (we don't want
    edges that are reliably destroying value)."""
    decomp = _make_decomp(alpha_ann=-0.05, t=-3.0)
    passed, reason = gate_factor_alpha(decomp)
    assert passed is False


def test_gate_custom_thresholds_honored():
    decomp = _make_decomp(alpha_ann=0.015, t=1.8)
    # Default would fail (t<2 AND alpha<2%). Loosen both → passes.
    passed_custom, _ = gate_factor_alpha(
        decomp, alpha_tstat_min=1.5, alpha_annual_min=0.01,
    )
    assert passed_custom is True
    # Tighten the t-stat threshold → fails.
    passed_strict, _ = gate_factor_alpha(decomp, alpha_tstat_min=3.0)
    assert passed_strict is False


# ---------------------------------------------------------------------------
# Real-data smoke (uses the cached FF files if present)
# ---------------------------------------------------------------------------

def test_load_factor_data_uses_cache_when_present():
    """If the FF cache files exist (from running the diagnostic), the
    no-auto-download path returns a non-empty factor panel."""
    from pathlib import Path
    from core.factor_decomposition import FF5_CACHE, MOM_CACHE, load_factor_data
    if not FF5_CACHE.exists() or not MOM_CACHE.exists():
        pytest.skip("FF cache not primed; run scripts/factor_decomposition_baseline.py first")
    factors = load_factor_data(auto_download=False)
    assert "MktRF" in factors.columns
    assert "RF" in factors.columns
    assert "Mom" in factors.columns
    assert len(factors) > 100


def test_load_factor_data_no_download_raises_when_missing(tmp_path):
    """When auto_download=False and the cache file is missing, raise
    rather than silently returning empty."""
    from core.factor_decomposition import load_factor_data
    missing = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError):
        load_factor_data(auto_download=False, ff5_cache=missing, mom_cache=missing)
