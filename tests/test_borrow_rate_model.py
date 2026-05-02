"""tests/test_borrow_rate_model.py

Tests for ``BorrowRateModel`` — per-day carry cost on short positions.

The model:
  - ADV-bucketed bps/day defaults (5 / 15 / 50)
  - Per-ticker overrides win over bucket classification
  - Post-processor on snapshots + price/volume data
  - Disabled flag returns equity unchanged
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backtester.borrow_rate_model import (
    BorrowRateConfig,
    BorrowRateModel,
    get_borrow_rate_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar_data(n_days: int = 30, close: float = 100.0, daily_volume: float = 1_000_000.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_days)
    return pd.DataFrame(
        {"Close": [close] * n_days, "Volume": [daily_volume] * n_days},
        index=dates,
    )


def _make_snapshots(n_days: int = 30, equity_start: float = 100_000.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_days)
    eq = np.linspace(equity_start, equity_start * 1.05, n_days)
    return pd.DataFrame({"timestamp": dates, "equity": eq})


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def test_mega_cap_bucket_returns_5bps():
    m = BorrowRateModel()
    bps = m.get_bps_per_day("AAPL", adv_usd=1_000_000_000.0)
    assert bps == pytest.approx(5.0)


def test_mid_cap_bucket_returns_15bps():
    m = BorrowRateModel()
    bps = m.get_bps_per_day("MIDCAP", adv_usd=200_000_000.0)
    assert bps == pytest.approx(15.0)


def test_small_cap_bucket_returns_50bps():
    m = BorrowRateModel()
    bps = m.get_bps_per_day("SMALL", adv_usd=10_000_000.0)
    assert bps == pytest.approx(50.0)


def test_per_ticker_override_wins():
    cfg = BorrowRateConfig(per_ticker_bps_per_day={"GME": 200.0})
    m = BorrowRateModel(cfg)
    # Even though ADV would put it in mega-cap bucket, override wins
    bps = m.get_bps_per_day("GME", adv_usd=1_000_000_000.0)
    assert bps == pytest.approx(200.0)


def test_missing_adv_falls_back_to_midcap():
    m = BorrowRateModel()
    bps = m.get_bps_per_day("UNKNOWN", adv_usd=None)
    assert bps == pytest.approx(15.0)


def test_disabled_returns_zero_drag():
    cfg = BorrowRateConfig(enabled=False)
    m = BorrowRateModel(cfg)
    snaps = _make_snapshots(10)
    drag = m.compute_daily_drag(snaps, None, None)
    assert len(drag) == 0


# ---------------------------------------------------------------------------
# Daily drag computation
# ---------------------------------------------------------------------------

def test_long_only_portfolio_has_zero_drag():
    """If positions_by_timestamp is empty / all-long, drag should be 0."""
    m = BorrowRateModel()
    snaps = _make_snapshots(10)
    positions = {pd.Timestamp(snaps["timestamp"].iloc[i]): {"AAPL": 100.0} for i in range(10)}
    drag = m.compute_daily_drag(snaps, {"AAPL": _make_bar_data()}, positions)
    assert (drag == 0).all()


def test_short_position_drag_proportional_to_value_and_rate():
    """Short $100k at 15 bps/day → $150/day drag."""
    m = BorrowRateModel()
    snaps = _make_snapshots(5)
    # -100k notional via signed dollar value (heuristic: |v| > 1e6 not met,
    # so use shares × close lookup). Use 1000 shares short × $100 close.
    bar = _make_bar_data(close=100.0, daily_volume=2_000_000.0)  # ADV $200M → mid-cap
    positions = {
        pd.Timestamp(snaps["timestamp"].iloc[i]): {"MIDCAP": -1000.0}
        for i in range(5)
    }
    drag = m.compute_daily_drag(snaps, {"MIDCAP": bar}, positions)
    # 1000 shares × $100 = $100k short. 15 bps/day → $150/day.
    expected_per_day = 100_000.0 * 15.0 / 10000.0
    assert drag.iloc[0] == pytest.approx(expected_per_day, rel=1e-6)
    assert drag.sum() == pytest.approx(5 * expected_per_day, rel=1e-6)


def test_signed_dollar_value_path():
    """When |value| > 1e6 the heuristic treats it as $-value of short."""
    m = BorrowRateModel()
    snaps = _make_snapshots(3)
    positions = {
        pd.Timestamp(snaps["timestamp"].iloc[i]): {"BIGSHORT": -5_000_000.0}
        for i in range(3)
    }
    bar = _make_bar_data(close=10.0, daily_volume=2_000_000.0)
    drag = m.compute_daily_drag(snaps, {"BIGSHORT": bar}, positions)
    # 15 bps/day on $5M short → $7,500/day
    assert drag.iloc[0] == pytest.approx(5_000_000.0 * 15.0 / 10000.0)


def test_short_value_usd_fallback_path():
    """Without per-ticker positions, use snapshots['short_value_usd']."""
    m = BorrowRateModel()
    snaps = _make_snapshots(3)
    snaps["short_value_usd"] = [50_000.0, 50_000.0, 50_000.0]
    drag = m.compute_daily_drag(snaps, None, None)
    expected = 50_000.0 * 15.0 / 10000.0
    assert drag.iloc[0] == pytest.approx(expected, rel=1e-6)


def test_apply_to_equity_curve_subtracts_cumulative_drag():
    m = BorrowRateModel()
    snaps = _make_snapshots(5)
    equity = pd.Series(snaps["equity"].values, index=pd.to_datetime(snaps["timestamp"]))
    positions = {
        pd.Timestamp(snaps["timestamp"].iloc[i]): {"X": -1000.0}
        for i in range(5)
    }
    bar = _make_bar_data(close=100.0, daily_volume=2_000_000.0)
    adjusted = m.apply_to_equity_curve(equity, snaps, {"X": bar}, positions)
    # cumulative drag at end = 5 × 100k × 15bps = $750
    assert adjusted.iloc[-1] < equity.iloc[-1]
    assert (equity.iloc[-1] - adjusted.iloc[-1]) == pytest.approx(5 * 150.0, rel=1e-3)


def test_disabled_apply_to_equity_curve_is_identity():
    cfg = BorrowRateConfig(enabled=False)
    m = BorrowRateModel(cfg)
    snaps = _make_snapshots(5)
    equity = pd.Series(snaps["equity"].values, index=pd.to_datetime(snaps["timestamp"]))
    adjusted = m.apply_to_equity_curve(equity, snaps, None, None)
    pd.testing.assert_series_equal(equity, adjusted)


def test_factory_honors_overrides():
    m = get_borrow_rate_model({"mega_cap_bps_per_day": 1.0, "small_cap_bps_per_day": 100.0})
    assert m.get_bps_per_day("X", adv_usd=1_000_000_000.0) == pytest.approx(1.0)
    assert m.get_bps_per_day("X", adv_usd=1_000_000.0) == pytest.approx(100.0)
