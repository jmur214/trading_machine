"""Tests for the regime-aware asymmetric vol-target clamp (R1 punch-list).

The vol-target overlay used to clamp `vol_scalar = target / realized_vol` to
[0.3, 2.0] symmetrically — meaning whenever realized vol fell below target
the portfolio leveraged up to 2× regardless of the macro regime. R1's audit
called this "the Minsky setup": leverage rises into calm periods that often
precede stress events.

The fix caps the upside ceiling at 1.0 in adverse regimes, 1.4 in
transitional, and the legacy 2.0 only in benign / unknown regimes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_c_portfolio.policy import PortfolioPolicy, PortfolioPolicyConfig


def _calm_price_data() -> dict[str, pd.DataFrame]:
    rng = pd.date_range("2024-01-01", periods=120, freq="B")
    base = np.linspace(100, 105, len(rng))
    df = pd.DataFrame({"Open": base, "High": base * 1.001, "Low": base * 0.999, "Close": base, "Volume": 1_000_000}, index=rng)
    return {"AAPL": df, "MSFT": df.copy()}


def _starting_weights() -> dict[str, float]:
    return {"AAPL": 0.05, "MSFT": 0.05}


def _make_policy() -> PortfolioPolicy:
    cfg = PortfolioPolicyConfig(
        target_volatility=0.15,
        min_weight=-0.20,
        max_weight=0.20,
        vol_target_enabled=True,
        debug=False,
    )
    return PortfolioPolicy(cfg)


def test_benign_regime_allows_legacy_2x_ceiling() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta={"macro_regime": {"label": "robust_expansion"}},
    )
    gross = sum(abs(w) for w in out.values())
    # In a calm bull (vol << target), legacy ceiling 2× lets gross approach 2×
    # the input gross of 0.10 = 0.20.
    assert gross > 0.10  # leverage IS applied
    assert gross <= 0.20 + 1e-6  # ceiling honored (max_weight clamp)


def test_market_turmoil_regime_clamps_to_no_leverage() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta={"macro_regime": {"label": "market_turmoil"}},
    )
    gross = sum(abs(w) for w in out.values())
    # vol_scalar capped at 1.0 → output gross == input gross == 0.10
    assert abs(gross - 0.10) < 1e-6, f"expected 0.10, got {gross}"


def test_cautious_decline_regime_clamps_to_no_leverage() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta={"macro_regime": {"label": "cautious_decline"}},
    )
    gross = sum(abs(w) for w in out.values())
    assert abs(gross - 0.10) < 1e-6


def test_transitional_regime_uses_half_step_ceiling() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta={"macro_regime": {"label": "transitional"}},
    )
    gross = sum(abs(w) for w in out.values())
    # Ceiling 1.4 → output gross at most 1.4 × 0.10 = 0.14
    assert gross <= 0.14 + 1e-6
    # And strictly more than no-leverage when vol is below target
    assert gross > 0.10


def test_no_regime_meta_preserves_legacy_behavior() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta=None,
    )
    gross = sum(abs(w) for w in out.values())
    # Without regime context, ceiling is the legacy 2.0 — same as benign.
    assert gross > 0.10
    assert gross <= 0.20 + 1e-6


def test_forward_stress_regime_label_is_consulted_when_macro_absent() -> None:
    policy = _make_policy()
    out = policy._apply_vol_target(
        _starting_weights(), _calm_price_data(),
        regime_meta={"forward_stress_regime": {"state": "stressed"}},
    )
    gross = sum(abs(w) for w in out.values())
    assert abs(gross - 0.10) < 1e-6
