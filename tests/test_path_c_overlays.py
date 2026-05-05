"""Tests for the Path C vol-target overlay helper (2026-05-06).

Verifies the behavior of the standalone vol-overlay math in
``scripts/path_c_overlays.py``:

  1. test_high_vol_de_levers       — port_vol > target → applied_scalar < 1
  2. test_low_vol_levers_up        — port_vol < target → applied_scalar > 1
  3. test_neutral_vol_no_op        — port_vol == target → applied_scalar ≈ 1
  4. test_clip_high_capped_at_2    — extreme low-vol stops at 2.0
  5. test_clip_low_floored_at_0_3  — extreme high-vol stops at 0.3
  6. test_diagnostics_classify     — clip_state field categorizes correctly
  7. test_empty_weights_handled    — degenerate input returns gracefully
  8. test_summarize_aggregates     — summary dict has required keys
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.path_c_overlays import (
    DEFAULT_TARGET_VOL,
    SCALAR_CLIP_HIGH,
    SCALAR_CLIP_LOW,
    VolOverlayDiagnostics,
    apply_exposure_cap,
    apply_vol_target,
    estimate_portfolio_vol,
    summarize_overlay_diagnostics,
)


# ---------------------------------------------------------------------------
# Synthetic price-panel builders — control realized vol explicitly
# ---------------------------------------------------------------------------

def make_constant_vol_panel(
    tickers: list[str],
    daily_vol: float,
    n_days: int = 200,
    seed: int = 42,
    correlation: float = 0.0,
) -> pd.DataFrame:
    """Build a wide price panel with controlled per-asset daily vol.

    Each ticker's log returns ~ Normal(0, daily_vol). Annualized vol of
    each asset ≈ daily_vol * sqrt(252).

    correlation = 0  → diversified (port vol < single-asset vol)
    correlation = 1  → fully correlated (port vol == single-asset vol)
    """
    rng = np.random.default_rng(seed)
    n_tickers = len(tickers)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")

    # Common factor + idiosyncratic
    common = rng.normal(0, daily_vol, n_days)
    if correlation == 1.0:
        rets = np.tile(common[:, None], (1, n_tickers))
    elif correlation == 0.0:
        rets = rng.normal(0, daily_vol, (n_days, n_tickers))
    else:
        idio = rng.normal(0, daily_vol * np.sqrt(1 - correlation**2),
                          (n_days, n_tickers))
        rets = correlation * common[:, None] + idio

    # Convert returns to prices (start at 100)
    log_rets = pd.DataFrame(rets, index=dates, columns=tickers)
    prices = 100 * np.exp(log_rets.cumsum())
    return prices


# ---------------------------------------------------------------------------
# 1. High realized vol → de-lever
# ---------------------------------------------------------------------------

def test_high_vol_de_levers():
    """When realized port vol > target, apply_vol_target must scale weights DOWN.

    The most important diagnostic: this is the MDD-rescue mechanism.
    """
    tickers = [f"T{i}" for i in range(10)]
    # Daily vol 0.025 → annualized ~0.40, well above target 0.15
    prices = make_constant_vol_panel(tickers, daily_vol=0.025,
                                     correlation=1.0)  # fully correlated → port vol = single-asset vol
    asof = prices.index[-1]
    weights = {t: 0.1 for t in tickers}  # equal-weight, gross=1.0
    gross_before = sum(abs(w) for w in weights.values())

    new_weights, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=asof,
        target_vol=0.15,
        lookback=60,
    )
    gross_after = sum(abs(w) for w in new_weights.values())

    assert diag.estimated_port_vol > 0.15, (
        f"Test setup failed: estimated port vol {diag.estimated_port_vol:.3f} "
        f"not above target 0.15"
    )
    assert diag.applied_scalar < 1.0, (
        f"Expected de-lever (scalar<1) when port vol > target. "
        f"Got applied_scalar={diag.applied_scalar:.3f}, "
        f"port_vol={diag.estimated_port_vol:.3f}"
    )
    assert gross_after < gross_before, (
        f"Gross exposure should decrease: {gross_before:.3f} → {gross_after:.3f}"
    )


# ---------------------------------------------------------------------------
# 2. Low realized vol → lever up
# ---------------------------------------------------------------------------

def test_low_vol_levers_up():
    """When port vol < target, scalar > 1 (within clip range)."""
    tickers = [f"T{i}" for i in range(10)]
    # Daily vol 0.003 → annualized ~0.05, well below target 0.15
    prices = make_constant_vol_panel(tickers, daily_vol=0.003,
                                     correlation=1.0)
    asof = prices.index[-1]
    weights = {t: 0.1 for t in tickers}

    new_weights, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=asof,
        target_vol=0.15,
        lookback=60,
    )

    assert diag.estimated_port_vol < 0.15, (
        f"Test setup failed: estimated port vol {diag.estimated_port_vol:.3f} "
        f"not below target 0.15"
    )
    assert diag.applied_scalar > 1.0, (
        f"Expected lever-up (scalar>1) when port vol < target. "
        f"Got applied_scalar={diag.applied_scalar:.3f}, "
        f"port_vol={diag.estimated_port_vol:.3f}"
    )


# ---------------------------------------------------------------------------
# 3. Neutral vol → no-op
# ---------------------------------------------------------------------------

def test_neutral_vol_no_op():
    """When realized port vol ≈ target, scalar ≈ 1, weights unchanged."""
    # daily_vol such that annualized ~= 0.15 → daily ~ 0.15 / sqrt(252) ~ 0.00945
    tickers = [f"T{i}" for i in range(10)]
    prices = make_constant_vol_panel(tickers, daily_vol=0.00945,
                                     correlation=1.0, seed=7)
    asof = prices.index[-1]
    weights = {t: 0.1 for t in tickers}

    new_weights, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=asof,
        target_vol=0.15,
        lookback=60,
    )

    # Allow some sample noise — within ~30% of 1.0
    assert 0.7 < diag.applied_scalar < 1.4, (
        f"Expected scalar ~1.0 when port vol ~ target 0.15. "
        f"Got applied_scalar={diag.applied_scalar:.3f}, "
        f"port_vol={diag.estimated_port_vol:.3f}"
    )


# ---------------------------------------------------------------------------
# 4. Clip ceiling
# ---------------------------------------------------------------------------

def test_clip_high_capped_at_2():
    """Extreme low-vol regime: applied scalar must be capped at SCALAR_CLIP_HIGH (2.0)."""
    tickers = [f"T{i}" for i in range(10)]
    # Pathologically low vol → raw scalar would be huge
    prices = make_constant_vol_panel(tickers, daily_vol=0.0001,
                                     correlation=1.0)
    asof = prices.index[-1]
    weights = {t: 0.1 for t in tickers}

    _, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=asof,
        target_vol=0.15,
        lookback=60,
    )

    assert diag.raw_scalar > SCALAR_CLIP_HIGH, (
        f"Test setup failed: raw scalar {diag.raw_scalar:.2f} "
        f"not above clip ceiling {SCALAR_CLIP_HIGH}"
    )
    assert diag.applied_scalar == pytest.approx(SCALAR_CLIP_HIGH), (
        f"Applied scalar must equal clip ceiling. "
        f"Got {diag.applied_scalar:.3f}"
    )
    assert diag.clip_state == "upper_clip"


# ---------------------------------------------------------------------------
# 5. Clip floor
# ---------------------------------------------------------------------------

def test_clip_low_floored_at_0_3():
    """Extreme high-vol regime: applied scalar must be floored at SCALAR_CLIP_LOW (0.3)."""
    tickers = [f"T{i}" for i in range(10)]
    # Pathologically high vol → raw scalar very small
    prices = make_constant_vol_panel(tickers, daily_vol=0.10,
                                     correlation=1.0)
    asof = prices.index[-1]
    weights = {t: 0.1 for t in tickers}

    _, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=asof,
        target_vol=0.15,
        lookback=60,
    )

    assert diag.raw_scalar < SCALAR_CLIP_LOW, (
        f"Test setup failed: raw scalar {diag.raw_scalar:.3f} "
        f"not below clip floor {SCALAR_CLIP_LOW}"
    )
    assert diag.applied_scalar == pytest.approx(SCALAR_CLIP_LOW), (
        f"Applied scalar must equal clip floor. "
        f"Got {diag.applied_scalar:.3f}"
    )
    assert diag.clip_state == "lower_clip"


# ---------------------------------------------------------------------------
# 6. Clip-state classification
# ---------------------------------------------------------------------------

def test_diagnostics_clip_state_categorizes_correctly():
    """VolOverlayDiagnostics.clip_state must categorize each region."""
    base = dict(
        asof=pd.Timestamp("2024-01-01"),
        n_holdings=10,
        estimated_port_vol=0.15,
        target_vol=0.15,
        gross_before=1.0,
        gross_after=1.0,
    )

    cases = [
        (1.0,    1.0,    "neutral"),
        (1.5,    1.5,    "levered_up"),
        (0.7,    0.7,    "de_levered"),
        (3.0,    SCALAR_CLIP_HIGH, "upper_clip"),
        (0.1,    SCALAR_CLIP_LOW,  "lower_clip"),
        (1.005,  1.005,  "neutral"),  # within 1% band
    ]
    for raw, applied, expected in cases:
        d = VolOverlayDiagnostics(raw_scalar=raw, applied_scalar=applied, **base)
        assert d.clip_state == expected, (
            f"raw={raw}, applied={applied}: expected {expected}, got {d.clip_state}"
        )


# ---------------------------------------------------------------------------
# 7. Empty / degenerate inputs
# ---------------------------------------------------------------------------

def test_empty_weights_handled():
    """Empty weights dict should round-trip without raising."""
    prices = make_constant_vol_panel(["T0", "T1"], daily_vol=0.01)
    new_weights, diag = apply_vol_target(
        weights={},
        prices=prices,
        asof=prices.index[-1],
    )
    assert new_weights == {}
    assert diag.n_holdings == 0


def test_single_ticker_falls_back():
    """One ticker falls back to that asset's vol (>=2 needed for cov)."""
    prices = make_constant_vol_panel(["T0"], daily_vol=0.025, correlation=1.0)
    weights = {"T0": 1.0}
    new_weights, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=prices.index[-1],
        target_vol=0.15,
    )
    # T0's annualized vol ~0.40, so applied_scalar should be < 1
    assert diag.estimated_port_vol > 0.15
    assert diag.applied_scalar < 1.0
    assert new_weights["T0"] < 1.0


def test_tickers_missing_from_panel_skipped():
    """Tickers in `weights` but missing from `prices.columns` ignored."""
    prices = make_constant_vol_panel(["A", "B"], daily_vol=0.01)
    weights = {"A": 0.5, "B": 0.5, "GHOST": 0.5}  # GHOST not in prices
    new_weights, diag = apply_vol_target(
        weights=weights,
        prices=prices,
        asof=prices.index[-1],
    )
    # GHOST stays in output (we just don't include it in vol estimation)
    # but the function does not raise.
    assert "A" in new_weights
    assert "B" in new_weights


# ---------------------------------------------------------------------------
# 8. Diagnostics summary
# ---------------------------------------------------------------------------

def test_summarize_overlay_diagnostics_aggregates():
    """summarize_overlay_diagnostics produces required summary keys."""
    base = dict(
        asof=pd.Timestamp("2024-01-01"),
        n_holdings=10,
        estimated_port_vol=0.20,
        target_vol=0.15,
        gross_before=1.0,
    )
    diags = [
        VolOverlayDiagnostics(raw_scalar=0.75, applied_scalar=0.75,
                              gross_after=0.75, **base),
        VolOverlayDiagnostics(raw_scalar=1.0, applied_scalar=1.0,
                              gross_after=1.0, **base),
        VolOverlayDiagnostics(raw_scalar=2.5, applied_scalar=SCALAR_CLIP_HIGH,
                              gross_after=2.0, **base),
    ]
    summary = summarize_overlay_diagnostics(diags)

    required_keys = {
        "n_rebalances", "clip_state_counts", "clip_state_fractions",
        "raw_scalar_mean", "raw_scalar_min", "raw_scalar_max",
        "applied_scalar_mean", "applied_scalar_min", "applied_scalar_max",
        "estimated_port_vol_mean", "estimated_port_vol_min", "estimated_port_vol_max",
        "gross_after_mean", "gross_after_min", "gross_after_max",
    }
    assert required_keys.issubset(summary.keys())
    assert summary["n_rebalances"] == 3
    assert summary["clip_state_counts"]["de_levered"] == 1
    assert summary["clip_state_counts"]["neutral"] == 1
    assert summary["clip_state_counts"]["upper_clip"] == 1


def test_summarize_empty_returns_empty_dict():
    summary = summarize_overlay_diagnostics([])
    assert summary == {}


# ---------------------------------------------------------------------------
# 9. Exposure cap (regime-free)
# ---------------------------------------------------------------------------

def test_exposure_cap_no_op_when_under_cap():
    weights = {"A": 0.3, "B": 0.3}
    capped = apply_exposure_cap(weights, cap=1.0)
    assert capped == weights


def test_exposure_cap_scales_when_over():
    weights = {"A": 0.8, "B": 0.8}  # gross 1.6
    capped = apply_exposure_cap(weights, cap=1.0)
    assert sum(abs(w) for w in capped.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 10. estimate_portfolio_vol direct
# ---------------------------------------------------------------------------

def test_estimate_vol_consistent_with_single_asset_when_correlated():
    """Fully correlated equal-weight portfolio of N assets has port vol == single-asset vol."""
    tickers = [f"T{i}" for i in range(5)]
    prices = make_constant_vol_panel(tickers, daily_vol=0.02, correlation=1.0)
    weights = {t: 0.2 for t in tickers}
    pv = estimate_portfolio_vol(weights, prices, prices.index[-1], lookback=60)

    # Single-asset annualized vol: 0.02 * sqrt(252) ≈ 0.317
    expected = 0.02 * np.sqrt(252)
    # Allow 30% tolerance for sample noise on 60-day window
    assert pv == pytest.approx(expected, rel=0.30)


def test_estimate_vol_diversifies_when_uncorrelated():
    """Diversified port vol < single-asset vol when correlation = 0."""
    tickers = [f"T{i}" for i in range(20)]
    prices = make_constant_vol_panel(tickers, daily_vol=0.02, correlation=0.0)
    weights = {t: 1.0 / 20 for t in tickers}
    pv = estimate_portfolio_vol(weights, prices, prices.index[-1], lookback=60)

    single_asset = 0.02 * np.sqrt(252)
    # 20 uncorrelated assets equally weighted → port vol ~= single / sqrt(20)
    expected_diversified = single_asset / np.sqrt(20)
    # Allow generous tolerance (small-sample noise)
    assert pv < single_asset * 0.5, (
        f"Diversified port vol {pv:.3f} not materially below single-asset {single_asset:.3f}"
    )
