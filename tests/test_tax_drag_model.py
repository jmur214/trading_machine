"""tests/test_tax_drag_model.py

Tests for ``TaxDragModel`` — short/long-term capital gains accounting.

Coverage:
  - FIFO trade reconstruction (long + short)
  - Holding-period classification (short_term vs long_term)
  - Wash-sale rule flagging
  - Yearly aggregation + carry-forward losses
  - Year-end synthetic withdrawal on equity curve
  - Disabled-mode is identity on equity
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backtester.tax_drag_model import (
    TaxDragConfig,
    TaxDragModel,
    get_tax_drag_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fill(ts: str, ticker: str, side: str, qty: int, price: float) -> dict:
    return {"timestamp": ts, "ticker": ticker, "side": side, "qty": qty, "fill_price": price}


def _fill_log(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------------------
# FIFO reconstruction
# ---------------------------------------------------------------------------

def test_simple_long_round_trip_short_term():
    log = _fill_log(
        _fill("2024-01-15", "AAPL", "long", 100, 100.0),
        _fill("2024-06-15", "AAPL", "exit", 100, 110.0),
    )
    m = TaxDragModel()
    trades = m.reconstruct_trades(log)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "long"
    assert t.qty == 100
    assert t.pnl == pytest.approx(1000.0)
    assert t.classification == "short_term"
    assert t.holding_days < 365


def test_long_round_trip_long_term():
    log = _fill_log(
        _fill("2023-01-01", "AAPL", "long", 100, 100.0),
        _fill("2024-06-01", "AAPL", "exit", 100, 120.0),
    )
    m = TaxDragModel()
    trades = m.reconstruct_trades(log)
    assert trades[0].classification == "long_term"
    assert trades[0].holding_days >= 365


def test_short_round_trip_correct_pnl_sign():
    """Short at $100, cover at $90 → +$1000 PnL on 100 shares."""
    log = _fill_log(
        _fill("2024-01-15", "TSLA", "short", 100, 100.0),
        _fill("2024-03-15", "TSLA", "cover", 100, 90.0),
    )
    m = TaxDragModel()
    trades = m.reconstruct_trades(log)
    assert len(trades) == 1
    assert trades[0].side == "short"
    assert trades[0].pnl == pytest.approx(1000.0)


def test_fifo_partial_close():
    """FIFO matches earliest lot first."""
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 50.0),
        _fill("2024-02-01", "X", "long", 100, 60.0),
        _fill("2024-03-01", "X", "exit", 150, 70.0),
    )
    m = TaxDragModel()
    trades = m.reconstruct_trades(log)
    # Should produce 2 closed trades: 100 from first lot @ $50, 50 from second @ $60
    assert len(trades) == 2
    pnl_total = sum(t.pnl for t in trades)
    assert pnl_total == pytest.approx(100 * 20.0 + 50 * 10.0)


# ---------------------------------------------------------------------------
# Wash-sale rule
# ---------------------------------------------------------------------------

def test_wash_sale_flags_loss_with_repurchase_within_30_days():
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-02-01", "X", "exit", 100, 90.0),    # loss
        _fill("2024-02-15", "X", "long", 100, 91.0),    # repurchase within 30 days
        _fill("2024-04-01", "X", "exit", 100, 95.0),
    )
    m = TaxDragModel()
    trades = m.reconstruct_trades(log)
    trades = m.apply_wash_sale_rule(trades)
    # First trade: loss with repurchase 14d later → wash-sale disallowed
    assert trades[0].pnl < 0
    assert trades[0].wash_sale_disallowed is True


def test_wash_sale_does_not_flag_gains():
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-02-01", "X", "exit", 100, 110.0),  # gain
        _fill("2024-02-15", "X", "long", 100, 111.0),
    )
    m = TaxDragModel()
    trades = m.apply_wash_sale_rule(m.reconstruct_trades(log))
    assert trades[0].wash_sale_disallowed is False


def test_wash_sale_does_not_flag_losses_outside_window():
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-02-01", "X", "exit", 100, 90.0),
        _fill("2024-04-01", "X", "long", 100, 91.0),  # >30 days later
    )
    m = TaxDragModel()
    trades = m.apply_wash_sale_rule(m.reconstruct_trades(log))
    assert trades[0].wash_sale_disallowed is False


# ---------------------------------------------------------------------------
# Yearly tax computation
# ---------------------------------------------------------------------------

def test_short_term_gain_taxed_at_30_percent():
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-03-01", "X", "exit", 100, 120.0),  # +$2000 ST gain
    )
    m = TaxDragModel(TaxDragConfig(enabled=True))
    yearly = m.compute_yearly_tax(m.reconstruct_trades(log))
    assert 2024 in yearly
    assert yearly[2024]["taxable_st"] == pytest.approx(2000.0)
    assert yearly[2024]["tax_owed"] == pytest.approx(600.0)  # 2000 × 0.30


def test_long_term_gain_taxed_at_15_percent():
    log = _fill_log(
        _fill("2023-01-01", "X", "long", 100, 100.0),
        _fill("2024-06-01", "X", "exit", 100, 120.0),  # +$2000 LT gain
    )
    m = TaxDragModel(TaxDragConfig(enabled=True))
    yearly = m.compute_yearly_tax(m.reconstruct_trades(log))
    assert yearly[2024]["taxable_lt"] == pytest.approx(2000.0)
    assert yearly[2024]["tax_owed"] == pytest.approx(300.0)  # 2000 × 0.15


def test_st_loss_offsets_st_gain_within_year():
    log = _fill_log(
        _fill("2024-01-01", "A", "long", 100, 100.0),
        _fill("2024-03-01", "A", "exit", 100, 120.0),  # +$2000 ST
        _fill("2024-04-01", "B", "long", 100, 100.0),
        _fill("2024-06-01", "B", "exit", 100, 90.0),   # -$1000 ST
    )
    m = TaxDragModel(TaxDragConfig(enabled=True))
    yearly = m.compute_yearly_tax(m.reconstruct_trades(log))
    # net ST = 2000 - 1000 = 1000; tax = 300
    assert yearly[2024]["taxable_st"] == pytest.approx(1000.0)
    assert yearly[2024]["tax_owed"] == pytest.approx(300.0)


def test_loss_carries_forward_to_next_year():
    log = _fill_log(
        # 2024: net loss
        _fill("2024-01-01", "A", "long", 100, 100.0),
        _fill("2024-06-01", "A", "exit", 100, 80.0),   # -$2000 ST
        # 2025: gain that should be partially offset by 2024's loss
        _fill("2025-01-01", "B", "long", 100, 100.0),
        _fill("2025-06-01", "B", "exit", 100, 130.0),  # +$3000 ST
    )
    m = TaxDragModel(TaxDragConfig(enabled=True))
    yearly = m.compute_yearly_tax(m.reconstruct_trades(log))
    assert yearly[2024]["tax_owed"] == 0.0  # net loss → no tax
    # 2025: 3000 gross - 2000 carry = 1000 taxable → 300 owed
    assert yearly[2025]["carry_in_st"] == pytest.approx(2000.0)
    assert yearly[2025]["taxable_st"] == pytest.approx(1000.0)
    assert yearly[2025]["tax_owed"] == pytest.approx(300.0)


def test_apply_to_equity_curve_subtracts_at_year_end():
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-06-01", "X", "exit", 100, 120.0),  # +$2000 ST
    )
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    equity = pd.Series(100_000.0, index=dates)
    m = TaxDragModel(TaxDragConfig(enabled=True))
    trades = m.reconstruct_trades(log)
    adjusted = m.apply_to_equity_curve(equity, trades)
    # before year-end: equity unchanged
    assert adjusted.loc["2024-06-15"] == pytest.approx(100_000.0)
    # after year-end: $600 tax debited
    assert adjusted.loc["2025-01-15"] == pytest.approx(99_400.0)


def test_disabled_apply_to_equity_curve_is_identity():
    cfg = TaxDragConfig(enabled=False)
    m = TaxDragModel(cfg)
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-06-01", "X", "exit", 100, 120.0),
    )
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    equity = pd.Series(100_000.0, index=dates)
    trades = m.reconstruct_trades(log)
    adjusted = m.apply_to_equity_curve(equity, trades)
    pd.testing.assert_series_equal(adjusted, equity)


def test_factory_honors_overrides():
    m = get_tax_drag_model({"enabled": True, "short_term_rate": 0.50})
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-03-01", "X", "exit", 100, 110.0),
    )
    yearly = m.compute_yearly_tax(m.reconstruct_trades(log))
    # +$1000 ST × 50% = $500
    assert yearly[2024]["tax_owed"] == pytest.approx(500.0)


def test_compute_end_to_end_returns_full_artifacts():
    m = TaxDragModel(TaxDragConfig(enabled=True))
    log = _fill_log(
        _fill("2024-01-01", "X", "long", 100, 100.0),
        _fill("2024-06-01", "X", "exit", 100, 120.0),
    )
    dates = pd.date_range("2024-01-01", "2025-06-30", freq="D")
    equity = pd.Series(100_000.0, index=dates)
    out = m.compute(log, equity)
    assert "trades" in out and len(out["trades"]) == 1
    assert out["total_tax"] == pytest.approx(600.0)
    assert "after_tax_equity" in out
