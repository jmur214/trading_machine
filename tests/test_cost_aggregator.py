"""tests/test_cost_aggregator.py

Tests for ``CostAggregator`` — the post-processor that produces A/B/C
equity curves from a backtest's snapshot history + trade log.

Coverage:
  - Disabled-by-default modules → A == B == C
  - Enabling alpaca_fees alone reduces final equity by ~total fees
  - Enabling borrow alone subtracts daily drag on shorts
  - Enabling tax alone applies year-end synthetic withdrawals
  - Sharpe of A > B > C when costs accumulate (or equal if no trades)
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backtester.cost_aggregator import CostAggregator


def _make_snapshots(n_days: int = 60, equity_start: float = 100_000.0, daily_ret: float = 0.001) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_days)
    eq = equity_start * (1 + daily_ret) ** np.arange(n_days)
    return pd.DataFrame({"timestamp": dates, "equity": eq})


def _make_bar_data(close: float = 100.0, volume: float = 2_000_000.0, n_days: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n_days)
    return pd.DataFrame({"Close": [close] * n_days, "Volume": [volume] * n_days}, index=dates)


def test_all_disabled_yields_identical_curves():
    snaps = _make_snapshots()
    trades = pd.DataFrame(
        [{"timestamp": "2024-01-15", "ticker": "X", "side": "long", "qty": 100, "fill_price": 100.0, "commission": 0.0}],
    )
    cfg = {
        "alpaca_fees": {"enabled": False},
        "borrow_rate_model": {"enabled": False},
        "tax_drag_model": {"enabled": False},
    }
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, {"X": _make_bar_data()})
    assert result.equity_A.iloc[-1] == result.equity_B.iloc[-1]
    assert result.equity_B.iloc[-1] == result.equity_C.iloc[-1]


def test_alpaca_fees_show_up_in_total_when_commission_present():
    snaps = _make_snapshots()
    trades = pd.DataFrame([
        {"timestamp": "2024-01-15", "ticker": "X", "side": "long", "qty": 100, "fill_price": 100.0, "commission": 1.50},
        {"timestamp": "2024-02-15", "ticker": "X", "side": "exit", "qty": 100, "fill_price": 110.0, "commission": 2.10},
    ])
    cfg = {"alpaca_fees": {"enabled": True}, "borrow_rate_model": {"enabled": False}, "tax_drag_model": {"enabled": False}}
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, None)
    # Total fees = sum of commission column = $3.60
    assert result.total_alpaca_fees == pytest.approx(3.60, rel=1e-6)


def test_borrow_drag_reduces_final_equity_when_short_position_exists():
    snaps = _make_snapshots()
    trades = pd.DataFrame([
        # Open short on day 5 of 60-day window, never close
        {"timestamp": str(snaps["timestamp"].iloc[5].date()), "ticker": "X", "side": "short",
         "qty": 1000, "fill_price": 100.0, "commission": 0.0},
    ])
    cfg = {"alpaca_fees": {"enabled": False}, "borrow_rate_model": {"enabled": True}, "tax_drag_model": {"enabled": False}}
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, {"X": _make_bar_data()})
    assert result.equity_B.iloc[-1] < result.equity_A.iloc[-1]
    assert result.total_borrow_drag > 0


def test_tax_drag_reduces_final_equity_when_realized_gains_present():
    snaps = _make_snapshots(n_days=400)  # span past year-end
    trades = pd.DataFrame([
        {"timestamp": "2024-01-15", "ticker": "X", "side": "long", "qty": 100, "fill_price": 100.0, "commission": 0.0},
        {"timestamp": "2024-06-15", "ticker": "X", "side": "exit", "qty": 100, "fill_price": 120.0, "commission": 0.0},
    ])
    cfg = {"alpaca_fees": {"enabled": False}, "borrow_rate_model": {"enabled": False}, "tax_drag_model": {"enabled": True}}
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, None)
    assert result.equity_C.iloc[-1] < result.equity_B.iloc[-1]
    # +$2000 ST gain × 30% = $600 owed
    assert result.total_tax_drag == pytest.approx(600.0, rel=1e-3)


def test_sharpe_strictly_decreases_when_borrow_active():
    snaps = _make_snapshots(daily_ret=0.001)
    trades = pd.DataFrame([
        {"timestamp": str(snaps["timestamp"].iloc[2].date()), "ticker": "X", "side": "short",
         "qty": 1000, "fill_price": 100.0, "commission": 0.0},
    ])
    cfg = {"alpaca_fees": {"enabled": False}, "borrow_rate_model": {"enabled": True}, "tax_drag_model": {"enabled": False}}
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, {"X": _make_bar_data()})
    assert result.sharpe_B < result.sharpe_A


def test_summary_dict_has_expected_keys():
    snaps = _make_snapshots()
    trades = pd.DataFrame([
        {"timestamp": "2024-01-15", "ticker": "X", "side": "long", "qty": 100, "fill_price": 100.0, "commission": 0.0},
    ])
    agg = CostAggregator()
    result = agg.compute(snaps, trades, None)
    summary = CostAggregator.result_to_summary_dict(result)
    block = summary["cost_completeness_layer_v1"]
    for k in ("sharpe_A_baseline", "sharpe_B_after_borrow_alpaca", "sharpe_C_after_tax",
              "delta_A_to_B_sharpe", "delta_B_to_C_sharpe",
              "total_alpaca_fees_usd", "total_borrow_drag_usd", "total_tax_drag_usd"):
        assert k in block


def test_empty_trade_log_does_not_crash():
    snaps = _make_snapshots()
    trades = pd.DataFrame(columns=["timestamp", "ticker", "side", "qty", "fill_price", "commission"])
    cfg = {"alpaca_fees": {"enabled": True}, "borrow_rate_model": {"enabled": True}, "tax_drag_model": {"enabled": True}}
    agg = CostAggregator(cfg)
    result = agg.compute(snaps, trades, None)
    assert result.equity_A.iloc[-1] == result.equity_B.iloc[-1] == result.equity_C.iloc[-1]
