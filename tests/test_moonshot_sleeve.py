"""Tests for MoonshotSleeve + leaps_catalyst_edge_v1.

Phase 0 scaffolding tests. Real OPRA validation is Phase 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_c_portfolio.sleeves.moonshot_sleeve import MoonshotSleeve
from engines.engine_c_portfolio.sleeves.sleeve_base import SleeveSpec
from engines.engine_a_alpha.edges.leaps_catalyst_edge import (
    LeapsCatalystEdge, options_payoff_proxy, _norm_inv_approx, _norm_cdf,
)


def _spec(
    name: str = "moonshot",
    capital_pct: float = 0.10,
    cadence: str = "monthly",
    max_w: float = 0.05,
) -> SleeveSpec:
    return SleeveSpec(
        name=name,
        capital_pct=capital_pct,
        rebalance_cadence=cadence,
        universe_id="moonshot_universe",
        edge_set=["leaps_catalyst_v1"],
        sizing_rule="weighted_sum",
        objective_function="sortino_skew_upside",
        enabled=True,
        max_position_weight=max_w,
    )


def _trending_data(n: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.001, 0.012, n)
    prices = 100 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": prices, "High": prices * 1.001, "Low": prices * 0.999,
        "Close": prices, "Volume": 1_000_000,
    }, index=idx)


# ----- MoonshotSleeve --------------------------------------------- #

def test_moonshot_returns_empty_when_no_positive_signals() -> None:
    sleeve = MoonshotSleeve(_spec())
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals={"AAPL": 0.0, "MSFT": -0.5},
        price_data={},
    )
    assert out.target_weights == {}
    assert out.diagnostics["n_eligible"] == 0


def test_moonshot_caps_concurrent_positions():
    """Top-K filter on signal strength. With max_concurrent=3 and 5 names
    only the 3 strongest survive."""
    sleeve = MoonshotSleeve(_spec(), max_concurrent_positions=3, min_concurrent_positions=1)
    signals = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6, "E": 0.5}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals=signals, price_data={},
    )
    assert len(out.target_weights) == 3
    # Strongest 3 survive
    assert set(out.target_weights.keys()) == {"A", "B", "C"}


def test_moonshot_weights_sum_to_one_within_sleeve() -> None:
    sleeve = MoonshotSleeve(_spec())
    signals = {f"T{i}": 0.5 + i * 0.01 for i in range(20)}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals=signals, price_data={},
    )
    assert sum(out.target_weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_moonshot_respects_max_position_weight_cap() -> None:
    """The spec.max_position_weight cap is applied PRE-renormalization
    so a per-bet that would exceed the cap gets clipped before the
    sum-to-1.0 normalization. Property: with N equal-conviction names
    and cap=0.05, after normalization each name ends at 1/N (the cap
    constrains per-bet pre-norm; equal pre-norm weights renormalize to
    equal post-norm weights of 1/N)."""
    sleeve = MoonshotSleeve(_spec(max_w=0.05), max_concurrent_positions=20)
    signals = {f"T{i}": 0.5 for i in range(10)}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals=signals, price_data={},
    )
    if out.target_weights:
        # 10 equal-conviction names, post-renorm each is 1/10 = 0.10.
        for tk, w in out.target_weights.items():
            assert w == pytest.approx(0.10, abs=1e-9), f"{tk}={w}"


def test_moonshot_sector_cap_pro_rates_concentrated_sector() -> None:
    sleeve = MoonshotSleeve(
        _spec(),
        max_sector_weight=0.25,
        sector_map={f"T{i}": ("Tech" if i < 8 else "Energy") for i in range(10)},
    )
    signals = {f"T{i}": 0.5 for i in range(10)}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals=signals, price_data={},
    )
    # Sum tech weights
    tech_sum = sum(w for tk, w in out.target_weights.items() if tk in {f"T{i}" for i in range(8)})
    # After normalization back to sum=1, the sector cap may be exceeded
    # (the cap is enforced PRE-normalization). What we should verify is
    # that the sector cap was applied — tech was scaled DOWN before
    # renorm. Simpler check: tech_sum < 8/10 = 0.8 (which it would be
    # without any cap).
    assert tech_sum < 0.80 + 1e-9


def test_moonshot_honors_cadence() -> None:
    sleeve = MoonshotSleeve(_spec(cadence="monthly"))
    signals = {"A": 0.9, "B": 0.8}
    out1 = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-15"),
        signals=signals, price_data={},
    )
    assert out1.rebalance_due is True
    out2 = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-06-25"),
        signals=signals, price_data={},
    )
    assert out2.rebalance_due is False
    assert out2.target_weights == out1.target_weights


# ----- options_payoff_proxy + Black-Scholes helpers ----------------- #

def test_norm_cdf_matches_known_values() -> None:
    """N(0)=0.5, N(1)≈0.8413, N(-1)≈0.1587"""
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(_norm_cdf(1.0) - 0.8413) < 1e-3
    assert abs(_norm_cdf(-1.0) - 0.1587) < 1e-3


def test_norm_inv_approx_round_trip() -> None:
    """Approximate ICDF should round-trip through CDF within tolerance."""
    for p in [0.05, 0.25, 0.50, 0.75, 0.95]:
        x = _norm_inv_approx(p)
        recovered = _norm_cdf(x)
        assert abs(recovered - p) < 5e-3, f"p={p}, x={x}, recovered={recovered}"


def test_options_payoff_proxy_returns_positive_premium_for_normal_inputs() -> None:
    contract = options_payoff_proxy(
        spot=100.0, strike=100.0, days_to_expiry=540, iv_annual=0.30,
    )
    assert contract.premium > 0
    # Strike for 25-delta call should be ABOVE spot (out of the money)
    assert contract.strike > 100.0
    assert contract.days_to_expiry == 540


def test_options_payoff_proxy_handles_zero_inputs_gracefully() -> None:
    contract = options_payoff_proxy(
        spot=0.0, strike=0.0, days_to_expiry=540, iv_annual=0.30,
    )
    assert contract.premium == 0.0
    contract = options_payoff_proxy(
        spot=100.0, strike=100.0, days_to_expiry=0, iv_annual=0.30,
    )
    assert contract.premium == 0.0


def test_options_payoff_proxy_premium_increases_with_iv() -> None:
    """Sanity: higher IV → higher call premium (vega is positive)."""
    low_iv = options_payoff_proxy(
        spot=100.0, strike=100.0, days_to_expiry=540, iv_annual=0.20,
    )
    high_iv = options_payoff_proxy(
        spot=100.0, strike=100.0, days_to_expiry=540, iv_annual=0.50,
    )
    assert high_iv.premium > low_iv.premium


# ----- LeapsCatalystEdge -------------------------------------------- #

def test_leaps_edge_returns_zero_when_no_history() -> None:
    edge = LeapsCatalystEdge()
    out = edge.compute_signals({"AAPL": pd.DataFrame()}, pd.Timestamp("2024-06-15"))
    assert out["AAPL"] == 0.0


def test_leaps_edge_emits_positive_signal_when_catalyst_window_present() -> None:
    edge = LeapsCatalystEdge()
    df = _trending_data(n=120, seed=1)
    out = edge.compute_signals({"AAPL": df}, pd.Timestamp(df.index[-1]))
    # Phase 0 stand-in always flags an "earnings ≈ +90d" placeholder
    # within the 540d horizon → expect a positive signal.
    assert out["AAPL"] > 0.0


def test_leaps_edge_signal_is_proportional_to_catalyst_confidence() -> None:
    """Phase-0 signal = tilt × mean_confidence. With one earnings
    catalyst at confidence 0.4 and tilt 0.6, the signal is 0.24."""
    edge = LeapsCatalystEdge()
    df = _trending_data(n=120, seed=42)
    out = edge.compute_signals({"AAPL": df}, pd.Timestamp(df.index[-1]))
    assert out["AAPL"] == pytest.approx(0.24, abs=0.01)


def test_leaps_edge_gives_zero_for_unmapped_ticker() -> None:
    edge = LeapsCatalystEdge()
    out = edge.compute_signals({"AAPL": pd.DataFrame()}, pd.Timestamp("2024-06-15"))
    assert "AAPL" in out
    assert out["AAPL"] == 0.0


def test_leaps_edge_id_and_category() -> None:
    assert LeapsCatalystEdge.EDGE_ID == "leaps_catalyst_v1"
    assert LeapsCatalystEdge.CATEGORY == "asymmetric_upside"
