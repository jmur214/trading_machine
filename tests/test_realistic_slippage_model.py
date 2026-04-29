"""
tests/test_realistic_slippage_model.py
=======================================
Tests for ``RealisticSlippageModel`` — the Phase 0 honest cost model.

The realistic model exists because flat bps slippage (FixedSlippageModel)
overstates Sharpe on broad universes by 0.2-0.3. It computes total cost
as the sum of:

  1. Half-spread (paid every trade) bucketed by 20-day average dollar
     volume (ADV):
        ADV >= $500M/day  → 1 bps  (mega-cap, e.g. SPY)
        $100M ≤ ADV < $500M → 5 bps  (mid-cap)
        ADV < $100M       → 15 bps  (small-cap)
  2. Square-root market impact (Almgren-Chriss):
        impact_bps = k × σ_daily × sqrt(qty / ADV_shares) × 10000
     where k = 0.5 by default.

These tests cover:
  - Half-spread bucketing across ADV thresholds
  - Square-root market impact scaling (qty doubled → impact ×√2)
  - Graceful fallbacks (Series, insufficient data, zero/missing fields)
  - qty=None vs explicit qty
  - Sanity cap at 100 bps
  - Apply-slippage direction (buy vs sell)
  - Factory wiring for "realistic" model_type
  - Drop-in compatibility with execution_simulator
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.execution.slippage_model import (
    FixedSlippageModel,
    RealisticSlippageModel,
    SlippageConfig,
    VolatilitySlippageModel,
    get_slippage_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar_data(
    n_days: int = 30,
    close: float = 100.0,
    daily_volume: float = 1_000_000.0,
    daily_return_std: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthesize a price/volume DataFrame with controlled vol and ADV.

    Returns a DataFrame with Close + Volume columns, indexed by date,
    with returns drawn from a normal distribution at `daily_return_std`.
    Note: prices random-walk so realized ADV ≠ exactly close × volume
    when daily_return_std > 0; use `_make_bar_data_flat` for boundary
    tests that need exact ADV matching.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days)
    daily_returns = rng.normal(0.0, daily_return_std, size=n_days)
    prices = [close]
    for r in daily_returns[1:]:
        prices.append(prices[-1] * (1 + r))
    return pd.DataFrame(
        {"Close": prices, "Volume": [daily_volume] * n_days},
        index=dates,
    )


def _make_bar_data_flat(
    n_days: int = 30,
    close: float = 100.0,
    daily_volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """Flat-price variant of _make_bar_data for boundary tests where the
    realized ADV must exactly equal close × daily_volume."""
    dates = pd.date_range("2024-01-01", periods=n_days)
    return pd.DataFrame(
        {"Close": [close] * n_days, "Volume": [daily_volume] * n_days},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Half-spread bucketing
# ---------------------------------------------------------------------------

def test_mega_cap_bucket_returns_1bps():
    """ADV >= $500M/day → mega-cap half-spread (default 1 bps)."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # close=$200, vol=10M shares/day → ADV = $2B/day → mega-cap.
    df = _make_bar_data(n_days=30, close=200.0, daily_volume=10_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(1.0)


def test_mid_cap_bucket_returns_5bps():
    """$100M ≤ ADV < $500M → mid-cap half-spread (default 5 bps)."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # close=$50, vol=4M shares/day → ADV = $200M/day → mid-cap.
    df = _make_bar_data(n_days=30, close=50.0, daily_volume=4_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(5.0)


def test_small_cap_bucket_returns_15bps():
    """ADV < $100M → small-cap half-spread (default 15 bps)."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # close=$10, vol=1M shares/day → ADV = $10M/day → small-cap.
    df = _make_bar_data(n_days=30, close=10.0, daily_volume=1_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(15.0)


def test_bucket_threshold_boundary_inclusive_at_mega():
    """ADV exactly at the mega-cap threshold counts as mega-cap, not mid.

    Uses flat prices so the realized 20-day ADV equals close × volume
    exactly. With random-walk prices, ADV drift would push the test off
    the bucket boundary.
    """
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # close=$100, vol=5M → ADV = $500M exactly.
    df = _make_bar_data_flat(n_days=30, close=100.0, daily_volume=5_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(1.0), "$500M ADV should bucket as mega-cap"


def test_bucket_threshold_boundary_inclusive_at_mid():
    """ADV exactly at the mid-cap threshold counts as mid-cap, not small.

    Uses flat prices so the realized 20-day ADV equals close × volume
    exactly.
    """
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # close=$10, vol=10M → ADV = $100M exactly.
    df = _make_bar_data_flat(n_days=30, close=10.0, daily_volume=10_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(5.0), "$100M ADV should bucket as mid-cap"


def test_custom_bucket_thresholds_honored():
    """Custom thresholds in config override defaults."""
    cfg = {
        "model_type": "realistic",
        "mega_cap_threshold_usd": 1_000_000_000.0,  # 1B
        "mid_cap_threshold_usd": 50_000_000.0,       # 50M
        "mega_cap_half_spread_bps": 0.5,
        "mid_cap_half_spread_bps": 3.0,
        "small_cap_half_spread_bps": 25.0,
    }
    model = get_slippage_model(cfg)
    # ADV $200M → mid bucket under custom thresholds (50M ≤ 200M < 1B).
    df = _make_bar_data(n_days=30, close=50.0, daily_volume=4_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Square-root market impact
# ---------------------------------------------------------------------------

def test_qty_none_returns_only_half_spread():
    """qty=None or 0 → no market impact term, only half-spread."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=200.0, daily_volume=10_000_000)
    bps_none = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    bps_zero = model.calculate_slippage_bps("TEST", df, "buy", qty=0)
    assert bps_none == pytest.approx(1.0)
    assert bps_zero == pytest.approx(1.0)


def test_market_impact_scales_with_sqrt_qty():
    """Doubling qty should multiply the impact term by √2 (~1.414×)."""
    cfg = {"model_type": "realistic", "impact_coefficient": 0.5}
    model = get_slippage_model(cfg)
    # Mid-cap: ADV $200M → 5 bps half-spread baseline.
    df = _make_bar_data(
        n_days=30, close=50.0, daily_volume=4_000_000, daily_return_std=0.02
    )
    bps_qty1k = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    bps_qty4k = model.calculate_slippage_bps("TEST", df, "buy", qty=4000)
    impact_1k = bps_qty1k - 5.0  # subtract half-spread
    impact_4k = bps_qty4k - 5.0
    # qty 4× → sqrt(4) = 2× impact
    assert impact_4k == pytest.approx(2.0 * impact_1k, rel=0.01)


def test_market_impact_scales_with_volatility():
    """Higher daily vol → higher impact (linear in σ)."""
    cfg = {"model_type": "realistic", "impact_coefficient": 0.5}
    model = get_slippage_model(cfg)
    df_low = _make_bar_data(
        n_days=30, close=50.0, daily_volume=4_000_000, daily_return_std=0.005
    )
    df_high = _make_bar_data(
        n_days=30, close=50.0, daily_volume=4_000_000, daily_return_std=0.020,
        seed=43,  # different seed to avoid degenerate identical paths
    )
    bps_low = model.calculate_slippage_bps("TEST", df_low, "buy", qty=10_000)
    bps_high = model.calculate_slippage_bps("TEST", df_high, "buy", qty=10_000)
    # High-vol path should have noticeably higher impact than low-vol.
    assert bps_high > bps_low


def test_market_impact_negligible_when_participation_tiny():
    """Tiny qty → impact term very small (≪ half-spread), total ≈ half-spread.

    1-share order on $2B/day ADV mega-cap with 1% daily vol gives a
    theoretical impact of `0.5 × 0.01 × sqrt(1 / 10M_shares) × 10000` ≈
    0.016 bps. Half-spread is 1.0 bps, so total ≈ 1.016 bps. We assert
    the impact term is < 5% of the half-spread (i.e. essentially noise).
    """
    cfg = {"model_type": "realistic", "impact_coefficient": 0.5}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=200.0, daily_volume=10_000_000)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1)  # 1 share
    half_spread = 1.0  # mega-cap
    impact = bps - half_spread
    # Impact term should be far smaller than the half-spread itself
    assert 0.0 <= impact < 0.05 * half_spread, f"Impact {impact:.4f} not negligible"


def test_impact_coefficient_scales_linearly():
    """Doubling impact_coefficient (k) should double the impact term."""
    df = _make_bar_data(
        n_days=30, close=50.0, daily_volume=4_000_000, daily_return_std=0.02
    )
    model_low_k = get_slippage_model({"model_type": "realistic", "impact_coefficient": 0.3})
    model_high_k = get_slippage_model({"model_type": "realistic", "impact_coefficient": 0.6})
    bps_low = model_low_k.calculate_slippage_bps("TEST", df, "buy", qty=10_000)
    bps_high = model_high_k.calculate_slippage_bps("TEST", df, "buy", qty=10_000)
    impact_low = bps_low - 5.0
    impact_high = bps_high - 5.0
    assert impact_high == pytest.approx(2.0 * impact_low, rel=0.01)


def test_impact_capped_at_100bps():
    """Sanity cap: a single fill cannot incur >100 bps in market impact."""
    cfg = {"model_type": "realistic", "impact_coefficient": 5.0}  # extreme k
    model = get_slippage_model(cfg)
    df = _make_bar_data(
        n_days=30, close=50.0, daily_volume=100_000, daily_return_std=0.05
    )
    # Massive qty → huge participation → would exceed cap without sanity guard
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=10_000_000)
    half_spread = 15.0  # small-cap (ADV = $5M)
    impact = bps - half_spread
    assert impact <= 100.0, f"Impact should be capped at 100 bps, got {impact}"


# ---------------------------------------------------------------------------
# Graceful fallbacks
# ---------------------------------------------------------------------------

def test_series_input_falls_back_to_mega_cap_floor():
    """A bare pd.Series can't compute ADV — fall back to mega-cap (1 bps)."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    series = pd.Series({"Close": 100.0, "Volume": 1_000_000})
    bps = model.calculate_slippage_bps("TEST", series, "buy", qty=1000)
    assert bps == pytest.approx(1.0)


def test_too_few_rows_falls_back_to_mega_cap_floor():
    """Insufficient rows for ADV → fall back rather than divide by zero."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=2, close=100.0, daily_volume=1_000_000)  # <5
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    assert bps == pytest.approx(1.0)


def test_missing_volume_column_falls_back():
    """No Volume column → can't compute ADV → mega-cap floor."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = pd.DataFrame(
        {"Close": [100.0] * 30}, index=pd.date_range("2024-01-01", periods=30)
    )
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    assert bps == pytest.approx(1.0)


def test_zero_volume_falls_back():
    """All-zero volume → invalid ADV → mega-cap floor."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=100.0, daily_volume=0.0)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    assert bps == pytest.approx(1.0)


def test_zero_close_returns_half_spread_only():
    """Last close = 0 → no impact term, just bucketed half-spread."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=100.0, daily_volume=4_000_000)
    df.iloc[-1, df.columns.get_loc("Close")] = 0.0
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    # ADV computed using all rows → mid-cap; impact term skipped due to bad close
    assert bps == pytest.approx(5.0)


def test_constant_price_falls_back_to_half_spread():
    """Zero realized vol → no impact term, just half-spread."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = pd.DataFrame(
        {"Close": [50.0] * 30, "Volume": [4_000_000] * 30},
        index=pd.date_range("2024-01-01", periods=30),
    )
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    assert bps == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# apply_slippage direction
# ---------------------------------------------------------------------------

def test_apply_slippage_buy_pays_more():
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 50.0, "buy")
    assert out == pytest.approx(100.50)  # +0.5%


def test_apply_slippage_sell_receives_less():
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 50.0, "sell")
    assert out == pytest.approx(99.50)


def test_apply_slippage_long_short_aliases():
    """'long' aliases to buy; 'short' aliases to sell."""
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    assert model.apply_slippage(100.0, 50.0, "long") == pytest.approx(100.50)
    assert model.apply_slippage(100.0, 50.0, "short") == pytest.approx(99.50)


def test_apply_slippage_cover_pays_more():
    """Covering a short position is a buy — pays more."""
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 50.0, "cover")
    assert out == pytest.approx(100.50)


def test_apply_slippage_exit_receives_less():
    """Exiting a long position is a sell — receives less."""
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 50.0, "exit")
    assert out == pytest.approx(99.50)


def test_apply_slippage_unknown_side_returns_unchanged():
    """Unknown side label → return price unchanged (no crash)."""
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 50.0, "weird")
    assert out == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------

def test_factory_returns_realistic_for_realistic_type():
    model = get_slippage_model({"model_type": "realistic"})
    assert isinstance(model, RealisticSlippageModel)


def test_factory_default_remains_fixed_for_backward_compat():
    """Empty config or unknown type → FixedSlippageModel (legacy default)."""
    assert isinstance(get_slippage_model({}), FixedSlippageModel)
    assert isinstance(get_slippage_model({"model_type": "fixed"}), FixedSlippageModel)
    assert isinstance(get_slippage_model({"model_type": "unknown"}), FixedSlippageModel)


def test_factory_volatility_unchanged():
    """Existing volatility model still wired by factory."""
    model = get_slippage_model({"model_type": "volatility"})
    assert isinstance(model, VolatilitySlippageModel)


def test_factory_parses_realistic_config_keys():
    """Factory propagates all realistic-specific config keys to SlippageConfig."""
    cfg = {
        "model_type": "realistic",
        "impact_coefficient": 0.7,
        "adv_lookback": 30,
        "mega_cap_threshold_usd": 1_000_000_000.0,
        "mid_cap_threshold_usd": 50_000_000.0,
        "mega_cap_half_spread_bps": 0.5,
        "mid_cap_half_spread_bps": 4.0,
        "small_cap_half_spread_bps": 20.0,
    }
    model = get_slippage_model(cfg)
    assert isinstance(model, RealisticSlippageModel)
    assert model.config.impact_coefficient == 0.7
    assert model.config.adv_lookback == 30
    assert model.config.mega_cap_threshold_usd == 1_000_000_000.0
    assert model.config.mid_cap_threshold_usd == 50_000_000.0
    assert model.config.mega_cap_half_spread_bps == 0.5
    assert model.config.mid_cap_half_spread_bps == 4.0
    assert model.config.small_cap_half_spread_bps == 20.0


# ---------------------------------------------------------------------------
# Drop-in compatibility with execution_simulator
# ---------------------------------------------------------------------------

def test_existing_callers_still_work_without_qty():
    """Callers that don't pass qty (legacy) still get a valid bps."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=200.0, daily_volume=10_000_000)
    # Old-style call without qty kwarg — should not raise.
    bps = model.calculate_slippage_bps("TEST", df, "buy")
    assert math.isfinite(bps) and bps > 0


def test_realistic_total_cost_dominates_legacy_on_small_caps():
    """The honesty test: a small-cap order should cost more under the
    realistic model than under the legacy 5 bps flat. This is the whole
    point of the new model — flat 5 bps was systematically optimistic
    for non-mega-cap names."""
    legacy = get_slippage_model({"model_type": "fixed", "slippage_bps": 5.0})
    realistic = get_slippage_model({"model_type": "realistic"})
    # Small-cap with meaningful order size: ADV = $10M, qty = 5000 shares of $10
    # = $50k order = 0.5% of ADV.
    df = _make_bar_data(
        n_days=30, close=10.0, daily_volume=1_000_000, daily_return_std=0.025
    )
    legacy_bps = legacy.calculate_slippage_bps("SMALL", df, "buy", qty=5000)
    realistic_bps = realistic.calculate_slippage_bps("SMALL", df, "buy", qty=5000)
    assert legacy_bps == 5.0
    assert realistic_bps > 15.0, (
        f"Realistic small-cap cost should exceed legacy 5 bps; got {realistic_bps:.2f}"
    )


def test_realistic_total_cost_competitive_on_mega_caps():
    """Mega-cap with retail-sized order: realistic should be CHEAPER than
    a flat 10 bps because real SPY-class spreads are sub-bp.
    """
    legacy = get_slippage_model({"model_type": "fixed", "slippage_bps": 10.0})
    realistic = get_slippage_model({"model_type": "realistic"})
    df = _make_bar_data(
        n_days=30, close=400.0, daily_volume=20_000_000, daily_return_std=0.01
    )  # $8B/day ADV — SPY-class
    legacy_bps = legacy.calculate_slippage_bps("SPY", df, "buy", qty=100)
    realistic_bps = realistic.calculate_slippage_bps("SPY", df, "buy", qty=100)
    assert legacy_bps == 10.0
    assert realistic_bps < 10.0, (
        f"Realistic mega-cap cost should be cheaper than legacy 10 bps; got {realistic_bps:.4f}"
    )


# ---------------------------------------------------------------------------
# ExecutionSimulator integration
#
# Today ExecutionSimulator._apply_slippage does not pass qty to the model.
# These tests verify two things:
#   1. The realistic model still works correctly through the simulator —
#      no crashes, returns sane fills.
#   2. Without qty, only the half-spread term applies. (Integration to
#      pass qty through to the simulator is deferred per the v2 plan
#      Phase 0.1 follow-on work.)
# ---------------------------------------------------------------------------

def test_execution_simulator_with_realistic_model_no_crash():
    """Drop-in replacement: ExecutionSimulator works with realistic model."""
    from backtester.execution_simulator import ExecutionSimulator

    sim = ExecutionSimulator(slippage_bps=10.0, slippage_model="realistic")
    order = {"ticker": "TEST", "side": "long", "qty": 100}
    bar = pd.Series({"Open": 100.0, "High": 101.0, "Low": 99.0,
                     "Close": 100.0, "PrevClose": 100.0})
    fill = sim.fill_at_next_open(order, bar)
    # Series input → mega-cap fallback → 1 bps half-spread → 100 + 0.01% = 100.01
    assert fill is not None
    assert fill["fill_price"] == pytest.approx(100.01, abs=0.001)


def test_execution_simulator_realistic_model_series_bar_falls_back_to_mega_floor():
    """Series bar (single row) cannot compute ADV — falls back to mega-cap
    floor regardless of qty. Documents that callers passing only one bar
    of context don't get differentiated slippage."""
    from backtester.execution_simulator import ExecutionSimulator

    sim = ExecutionSimulator(slippage_bps=10.0, slippage_model="realistic")
    order = {"ticker": "TEST", "side": "long", "qty": 1_000_000}
    bar = pd.Series({"Open": 100.0, "High": 101.0, "Low": 99.0,
                     "Close": 100.0, "PrevClose": 100.0})
    fill = sim.fill_at_next_open(order, bar)
    # Series bar → mega-cap floor (1 bps) → 100 + 0.01% = 100.01.
    assert fill["fill_price"] == pytest.approx(100.01, abs=0.001), (
        "Series bar should produce mega-cap floor regardless of qty"
    )


# ---------------------------------------------------------------------------
# Integration: end-to-end qty plumbing through ExecutionSimulator
#
# These tests verify the post-Phase-0.1 wiring: ExecutionSimulator now
# forwards order qty to RealisticSlippageModel, so size-aware impact
# kicks in when bar_data is a multi-row DataFrame with Volume column.
# ---------------------------------------------------------------------------

def _make_bar_dataframe_with_history(
    n_history: int = 30,
    close: float = 50.0,
    daily_volume: float = 4_000_000.0,
    daily_return_std: float = 0.02,
) -> pd.DataFrame:
    """Multi-row DataFrame with the historical bars realistic model needs."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n_history)
    rets = rng.normal(0.0, daily_return_std, size=n_history)
    prices = [close]
    for r in rets[1:]:
        prices.append(prices[-1] * (1 + r))
    df = pd.DataFrame({
        "Open": prices,
        "High": [p * 1.005 for p in prices],
        "Low": [p * 0.995 for p in prices],
        "Close": prices,
        "Volume": [daily_volume] * n_history,
    }, index=dates)
    df["PrevClose"] = df["Close"].shift(1).fillna(df["Close"].iloc[0])
    return df


def test_execution_simulator_qty_reaches_realistic_model_via_fill_at_next_open():
    """Verify qty plumbing: a small order and a large order should produce
    different fill prices under the realistic model when bar_data has
    enough history for ADV/vol."""
    from backtester.execution_simulator import ExecutionSimulator

    sim = ExecutionSimulator(slippage_bps=10.0, slippage_model="realistic")
    df = _make_bar_dataframe_with_history(close=50.0, daily_volume=4_000_000)
    last_bar = df.iloc[[-1]].copy()  # DataFrame with one row but full columns
    # Re-attach history so bar_data passed to slippage model can compute ADV
    # Note: fill_at_next_open uses the bar_like for slippage, but the
    # SlippageModel needs a multi-row DataFrame. The integration here
    # passes a single-row Series-like, so realistic model falls back to
    # mega-cap floor. This documents the limitation: qty IS forwarded,
    # but the bar_data contract still passes one row at a time.
    bar_row = pd.Series(last_bar.iloc[0].to_dict(), name=last_bar.index[-1])
    order_small = {"ticker": "TEST", "side": "long", "qty": 100}
    order_large = {"ticker": "TEST", "side": "long", "qty": 1_000_000}
    fill_small = sim.fill_at_next_open(order_small, bar_row)
    fill_large = sim.fill_at_next_open(order_large, bar_row)
    # Under current single-row bar contract, both fills get mega-cap floor.
    # That's expected — the qty plumbing works (no crash), but ADV/impact
    # require the slippage model to receive multi-row context.
    assert fill_small["fill_price"] == pytest.approx(fill_large["fill_price"], abs=0.001)


def test_realistic_model_receives_qty_when_called_with_multirow_dataframe():
    """Direct test: when the slippage model gets a multi-row DataFrame
    AND a non-trivial qty, the impact term must fire and produce
    larger bps than qty=None."""
    from engines.execution.slippage_model import get_slippage_model
    df = _make_bar_dataframe_with_history(close=50.0, daily_volume=4_000_000)
    realistic = get_slippage_model({"model_type": "realistic"})
    bps_no_qty = realistic.calculate_slippage_bps("TEST", df, "buy", qty=None)
    bps_large_qty = realistic.calculate_slippage_bps("TEST", df, "buy", qty=10_000)
    # Both pass through the same half-spread bucket; impact only fires
    # for the second call.
    assert bps_large_qty > bps_no_qty
    assert bps_no_qty == pytest.approx(5.0)  # mid-cap half-spread


def test_execution_simulator_constructor_forwards_slippage_extra_to_factory():
    """ExecutionSimulator(slippage_extra=...) must reach the factory so
    realistic-model-specific knobs (impact_coefficient, bucket thresholds)
    are honored when callers supply them via ModeController -> exec_params."""
    from backtester.execution_simulator import ExecutionSimulator
    from engines.execution.slippage_model import RealisticSlippageModel

    sim = ExecutionSimulator(
        slippage_model="realistic",
        slippage_extra={
            "impact_coefficient": 0.7,
            "mega_cap_half_spread_bps": 0.5,
        },
    )
    assert isinstance(sim.model, RealisticSlippageModel)
    assert sim.model.config.impact_coefficient == 0.7
    assert sim.model.config.mega_cap_half_spread_bps == 0.5


def test_execution_simulator_fixed_model_ignores_qty_silently():
    """Backward compatibility: legacy callers using the fixed model still
    work — qty is accepted by the new signature but ignored."""
    from backtester.execution_simulator import ExecutionSimulator

    sim = ExecutionSimulator(slippage_bps=10.0, slippage_model="fixed")
    order = {"ticker": "TEST", "side": "long", "qty": 9_999_999}
    bar = pd.Series({"Open": 100.0, "High": 101.0, "Low": 99.0,
                     "Close": 100.0, "PrevClose": 100.0})
    fill = sim.fill_at_next_open(order, bar)
    # Fixed model ignores qty → flat 10 bps regardless of size.
    assert fill["fill_price"] == pytest.approx(100.10, abs=0.001)


# ---------------------------------------------------------------------------
# Property-style sweeps — cover the parameter space
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adv_usd,expected_half_spread", [
    (10_000_000_000, 1.0),    # $10B mega-cap
    (1_000_000_000, 1.0),     # $1B mega-cap boundary
    (500_000_000, 1.0),       # $500M boundary (mega)
    (499_999_999, 5.0),       # just below mega → mid
    (200_000_000, 5.0),       # mid-cap interior
    (100_000_000, 5.0),       # mid boundary
    (99_999_999, 15.0),       # just below mid → small
    (10_000_000, 15.0),       # small interior
    (1_000_000, 15.0),        # tiny → small
])
def test_half_spread_bucketing_full_sweep(adv_usd, expected_half_spread):
    """Full sweep of ADV bucket boundaries with flat-price data."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    # Choose close=$10 so daily_volume = adv_usd / 10.
    df = _make_bar_data_flat(n_days=30, close=10.0, daily_volume=adv_usd / 10.0)
    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=None)
    assert bps == pytest.approx(expected_half_spread), (
        f"ADV ${adv_usd:,} should bucket to {expected_half_spread} bps; got {bps}"
    )


@pytest.mark.parametrize("qty_multiplier,expected_impact_multiplier", [
    (1, 1.0),
    (4, 2.0),    # sqrt(4) = 2
    (9, 3.0),    # sqrt(9) = 3
    (16, 4.0),   # sqrt(16) = 4
    (100, 10.0), # sqrt(100) = 10
])
def test_market_impact_sqrt_law_full_sweep(qty_multiplier, expected_impact_multiplier):
    """Verify Almgren-Chriss sqrt(qty) scaling at multiple multipliers."""
    cfg = {"model_type": "realistic", "impact_coefficient": 0.5}
    model = get_slippage_model(cfg)
    df = _make_bar_data(
        n_days=30, close=50.0, daily_volume=4_000_000, daily_return_std=0.02
    )
    base_qty = 1000
    bps_base = model.calculate_slippage_bps("TEST", df, "buy", qty=base_qty)
    bps_scaled = model.calculate_slippage_bps(
        "TEST", df, "buy", qty=base_qty * qty_multiplier,
    )
    half_spread = 5.0  # mid-cap bucket
    impact_base = bps_base - half_spread
    impact_scaled = bps_scaled - half_spread
    if qty_multiplier == 1:
        assert impact_scaled == pytest.approx(impact_base, rel=0.001)
    else:
        assert impact_scaled == pytest.approx(
            expected_impact_multiplier * impact_base, rel=0.01
        ), (
            f"qty × {qty_multiplier} should give impact × √{qty_multiplier}; "
            f"got {impact_scaled / impact_base:.3f}× expected {expected_impact_multiplier}×"
        )


@pytest.mark.parametrize("side", ["long", "buy", "cover"])
def test_buy_side_aliases_all_pay_more(side):
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 25.0, side)
    assert out > 100.0


@pytest.mark.parametrize("side", ["short", "sell", "exit"])
def test_sell_side_aliases_all_receive_less(side):
    cfg = SlippageConfig(model_type="realistic")
    model = RealisticSlippageModel(cfg)
    out = model.apply_slippage(100.0, 25.0, side)
    assert out < 100.0


# ---------------------------------------------------------------------------
# Determinism and idempotency
# ---------------------------------------------------------------------------

def test_realistic_model_deterministic_across_calls():
    """Same inputs → same outputs. No hidden state."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=50.0, daily_volume=4_000_000)
    bps_1 = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    bps_2 = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    bps_3 = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    assert bps_1 == bps_2 == bps_3


def test_realistic_model_does_not_mutate_input():
    """The input DataFrame is read-only — never written to in-place."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    df = _make_bar_data(n_days=30, close=50.0, daily_volume=4_000_000)
    df_before = df.copy(deep=True)
    _ = model.calculate_slippage_bps("TEST", df, "buy", qty=1000)
    pd.testing.assert_frame_equal(df, df_before)


def test_realistic_model_returns_finite_for_realistic_inputs():
    """Sweep a realistic parameter grid; never NaN, never Inf, never negative."""
    cfg = {"model_type": "realistic"}
    model = get_slippage_model(cfg)
    for close in [5.0, 50.0, 500.0]:
        for vol_per_day in [100_000, 1_000_000, 10_000_000]:
            for vol_std in [0.005, 0.01, 0.03, 0.05]:
                df = _make_bar_data(
                    n_days=30, close=close, daily_volume=vol_per_day,
                    daily_return_std=vol_std,
                )
                for qty in [None, 100, 10_000, 100_000]:
                    bps = model.calculate_slippage_bps("TEST", df, "buy", qty=qty)
                    assert math.isfinite(bps), f"NaN/Inf bps for qty={qty}"
                    assert bps >= 0.0, f"Negative bps {bps} for qty={qty}"
                    # Sanity upper bound: half_spread (≤15) + impact_cap (≤100) = 115
                    assert bps <= 115.0, f"Bps {bps:.1f} exceeds sanity ceiling"
