"""Unit + integration tests for the ADV-floor precondition primitive.

The primitive lives in EdgeBase._below_adv_floor and is consumed by the
five ADV-fragile edges (atr_breakout_v1, momentum_edge_v1,
volume_anomaly_v1, herding_v1, gap_fill_v1) per the Path-2 audit
(docs/Audit/path2_adv_floors_2026_05.md).

These tests verify:
  1. Primitive is a no-op when min_adv_usd is None / 0 / NaN.
  2. Floor at $200M skips a $100M-ADV ticker.
  3. Floor at $200M allows a $500M-ADV ticker.
  4. Edge-case correctness on missing-Volume / short-history / 0-volume bars.
  5. Counter increments correctly across calls.
  6. Per-edge integration: synthetic 2-ticker run skips below-floor name
     and fires on above-floor name (atr_breakout, momentum, volume_anomaly,
     gap_fill).
  7. Cross-sectional integration: herding excludes below-floor tickers
     from the breadth/contrarian universe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edges.atr_breakout import ATRBreakoutEdge
from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge
from engines.engine_a_alpha.edges.volume_anomaly_edge import VolumeAnomalyEdge
from engines.engine_a_alpha.edges.herding_edge import HerdingEdge
from engines.engine_a_alpha.edges.gap_edge import GapEdge


def _make_df(price: float, volume: float, n: int = 60) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with constant price/volume."""
    rng = np.random.default_rng(42)
    closes = price + rng.normal(0, price * 0.005, n)
    opens = closes + rng.normal(0, price * 0.002, n)
    highs = np.maximum(opens, closes) + abs(rng.normal(0, price * 0.003, n))
    lows = np.minimum(opens, closes) - abs(rng.normal(0, price * 0.003, n))
    volumes = np.full(n, volume, dtype=float) + rng.normal(0, volume * 0.05, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


# -------------------- 1. EdgeBase primitive -------------------- #

def test_floor_none_is_no_op():
    """min_adv_usd=None must always return False, regardless of volume."""
    eb = EdgeBase()
    df_low = _make_df(price=10.0, volume=1_000_000)  # $10M/day
    assert eb._below_adv_floor(df_low, None, ticker="LOW") is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_zero_or_negative_is_no_op():
    eb = EdgeBase()
    df = _make_df(price=10.0, volume=1_000_000)
    assert eb._below_adv_floor(df, 0, ticker="X") is False
    assert eb._below_adv_floor(df, -100_000_000, ticker="X") is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_nan_is_no_op():
    eb = EdgeBase()
    df = _make_df(price=10.0, volume=1_000_000)
    assert eb._below_adv_floor(df, float("nan"), ticker="X") is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_skips_below_threshold():
    """$200M floor must skip a ~$100M-ADV ticker."""
    eb = EdgeBase()
    # $100/share × 1M shares/day = $100M/day
    df_below = _make_df(price=100.0, volume=1_000_000)
    assert eb._below_adv_floor(df_below, 200_000_000, ticker="LOW") is True
    assert eb.get_adv_skip_summary() == {"LOW": 1}


def test_floor_allows_above_threshold():
    """$200M floor must allow a ~$500M-ADV ticker."""
    eb = EdgeBase()
    # $50/share × 10M shares/day = $500M/day
    df_above = _make_df(price=50.0, volume=10_000_000)
    assert eb._below_adv_floor(df_above, 200_000_000, ticker="HIGH") is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_handles_missing_volume_column():
    eb = EdgeBase()
    df = _make_df(price=10.0, volume=1_000_000).drop(columns=["Volume"])
    # No Volume column → cannot evaluate, return False (no-op)
    assert eb._below_adv_floor(df, 200_000_000, ticker="X") is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_handles_short_history():
    eb = EdgeBase()
    df = _make_df(price=100.0, volume=1_000_000, n=10)  # < 20 bars
    # With < window bars, no-op
    assert eb._below_adv_floor(df, 200_000_000, ticker="SHORT", window=20) is False
    assert eb.get_adv_skip_summary() == {}


def test_floor_handles_zero_volume_bars():
    """A ticker with zero volume across the window must skip (median dv = 0 < floor)."""
    eb = EdgeBase()
    df = _make_df(price=100.0, volume=1_000_000)
    df["Volume"] = 0  # Zero out all volume
    assert eb._below_adv_floor(df, 200_000_000, ticker="DEAD") is True
    assert eb.get_adv_skip_summary() == {"DEAD": 1}


def test_counter_increments_across_calls():
    eb = EdgeBase()
    df_below = _make_df(price=100.0, volume=1_000_000)  # $100M/day
    eb._below_adv_floor(df_below, 200_000_000, ticker="A")
    eb._below_adv_floor(df_below, 200_000_000, ticker="A")
    eb._below_adv_floor(df_below, 200_000_000, ticker="B")
    summary = eb.get_adv_skip_summary()
    assert summary == {"A": 2, "B": 1}
    eb.reset_adv_skip_summary()
    assert eb.get_adv_skip_summary() == {}


# -------------------- 2. Per-edge integration -------------------- #

def _two_ticker_data_map():
    """One above the smallest floor ($150M), one below all floors ($50M)."""
    return {
        "ABOVE": _make_df(price=100.0, volume=10_000_000),  # $1B/day — clears all floors
        "BELOW": _make_df(price=10.0, volume=5_000_000),    # $50M/day — sub-floor for all
    }


def test_atr_breakout_skips_below_floor():
    edge = ATRBreakoutEdge()
    edge.set_params({"min_score": 0.0})  # Disable dead-zone so signals always emit
    data_map = _two_ticker_data_map()
    scores = edge.compute_signals(data_map, as_of=None)
    assert "BELOW" not in scores or scores.get("BELOW", 0.0) == 0.0
    assert "ABOVE" in scores
    skips = edge.get_adv_skip_summary()
    assert "BELOW" in skips and skips["BELOW"] == 1


def test_momentum_skips_below_floor():
    edge = MomentumEdge()
    data_map = _two_ticker_data_map()
    scores = edge.compute_signals(data_map, now=None)
    assert "BELOW" not in scores
    assert "ABOVE" in scores
    skips = edge.get_adv_skip_summary()
    assert skips.get("BELOW") == 1


def test_volume_anomaly_skips_below_floor():
    edge = VolumeAnomalyEdge()
    data_map = _two_ticker_data_map()
    scores = edge.compute_signals(data_map, as_of=None)
    assert "BELOW" not in scores
    skips = edge.get_adv_skip_summary()
    assert skips.get("BELOW") == 1


def test_gap_fill_skips_below_floor():
    edge = GapEdge()
    data_map = _two_ticker_data_map()
    scores = edge.compute_signals(data_map, as_of=None)
    assert "BELOW" not in scores
    skips = edge.get_adv_skip_summary()
    assert skips.get("BELOW") == 1


def test_herding_excludes_below_floor_from_universe():
    """Cross-sectional edge: sub-floor tickers must not contribute to breadth."""
    # 12 above-floor tickers (one extreme mover) + 12 below-floor (all moving up)
    # Without floor: 24-ticker universe, 100% up → herding fires contrarian on extremes.
    # With floor: 12-ticker universe, some up some down → may or may not fire.
    # Key invariant: below-floor names get score 0 regardless.
    rng = np.random.default_rng(0)

    def make_ticker(price, volume, last_ret):
        n = 30
        closes = np.full(n, price, dtype=float) + rng.normal(0, price * 0.001, n)
        # Set last bar to specific return
        closes[-1] = closes[-2] * (1 + last_ret)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        return pd.DataFrame({
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": np.full(n, volume, dtype=float),
        }, index=idx)

    data_map = {}
    # 12 above-floor tickers — mixed returns
    for i in range(12):
        data_map[f"BIG{i}"] = make_ticker(price=100.0, volume=10_000_000, last_ret=0.02 if i < 6 else -0.01)
    # 12 below-floor tickers — all same direction (extreme)
    for i in range(12):
        data_map[f"SMALL{i}"] = make_ticker(price=5.0, volume=2_000_000, last_ret=0.05)

    edge = HerdingEdge()
    edge.set_params({"min_universe_size": 10})
    scores = edge.compute_signals(data_map, as_of=None)
    # Below-floor tickers must get 0 (or be absent)
    for i in range(12):
        assert scores.get(f"SMALL{i}", 0.0) == 0.0
    skips = edge.get_adv_skip_summary()
    for i in range(12):
        assert skips.get(f"SMALL{i}") == 1


def test_floor_explicit_param_override():
    """Setting min_adv_usd=0 via params disables the floor for that edge."""
    edge = ATRBreakoutEdge()
    edge.set_params({"min_score": 0.0, "min_adv_usd": 0})
    data_map = _two_ticker_data_map()
    scores = edge.compute_signals(data_map, as_of=None)
    # Both tickers should be eligible
    assert "ABOVE" in scores
    assert "BELOW" in scores
    assert edge.get_adv_skip_summary() == {}
