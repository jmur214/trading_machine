"""tests/test_alpaca_fees.py

Tests for ``AlpacaFees`` — the per-fill regulatory pass-through model.

Alpaca offers commission-free stock trading but passes through:
  - SEC Section 31 fee on sells: $27.80 per $1M of principal
  - FINRA TAF on sells: $0.000166/share, capped at $8.30/trade

Buys are free. The only ambiguity is what "sell" includes — by convention
in this repo, the sell-side is ``sell``, ``exit``, ``short``, ``cover``.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backtester.alpaca_fees import (
    AlpacaFees,
    AlpacaFeesConfig,
    get_alpaca_fees,
)


def test_buy_pays_zero_when_disabled_buy_side_fees():
    fees = AlpacaFees()
    fee = fees.compute_fee(side="long", qty=100, fill_price=150.0)
    assert fee == 0.0


def test_sell_long_pays_sec_plus_taf():
    fees = AlpacaFees()
    qty, price = 100, 150.0  # notional $15,000
    fee = fees.compute_fee(side="exit", qty=qty, fill_price=price)
    expected_sec = 15_000.0 * 27.80 / 1_000_000.0
    expected_taf = 100 * 0.000166
    assert fee == pytest.approx(expected_sec + expected_taf, rel=1e-9)


def test_short_open_pays_sec_plus_taf():
    """Opening a short is a sell — both fees apply."""
    fees = AlpacaFees()
    fee = fees.compute_fee(side="short", qty=200, fill_price=50.0)
    expected_sec = 10_000.0 * 27.80 / 1_000_000.0
    expected_taf = 200 * 0.000166
    assert fee == pytest.approx(expected_sec + expected_taf, rel=1e-9)


def test_short_cover_pays_zero():
    """Covering a short is a buy — no SEC, no TAF."""
    fees = AlpacaFees()
    fee = fees.compute_fee(side="cover", qty=200, fill_price=50.0)
    assert fee == 0.0


def test_taf_capped_at_8_30():
    """At 50,000 shares the TAF cap binds: 50000 × 0.000166 = $8.30."""
    fees = AlpacaFees()
    fee = fees.compute_fee(side="exit", qty=100_000, fill_price=10.0)
    breakdown = fees.compute_fee_breakdown(side="exit", qty=100_000, fill_price=10.0)
    assert breakdown["taf"] == pytest.approx(8.30, abs=1e-9)
    # Verify cap kicked in (100k shares would otherwise be $16.60)
    assert breakdown["taf"] < 100_000 * 0.000166


def test_disabled_returns_base_commission_only():
    fees = AlpacaFees(AlpacaFeesConfig(enabled=False, base_commission=1.50))
    fee = fees.compute_fee(side="exit", qty=1000, fill_price=100.0)
    assert fee == 1.50


def test_fee_scales_linearly_with_qty():
    fees = AlpacaFees()
    f1 = fees.compute_fee(side="exit", qty=100, fill_price=50.0)
    f2 = fees.compute_fee(side="exit", qty=200, fill_price=50.0)
    assert f2 == pytest.approx(2.0 * f1, rel=1e-9)


def test_fee_scales_linearly_with_price_until_taf_cap():
    fees = AlpacaFees()
    f_low = fees.compute_fee(side="exit", qty=100, fill_price=50.0)
    f_high = fees.compute_fee(side="exit", qty=100, fill_price=100.0)
    # SEC component doubles; TAF stays the same → fee should be > 1× but < 2×
    assert f_low < f_high < 2.0 * f_low


def test_buy_side_fees_toggle():
    cfg = AlpacaFeesConfig(buy_side_fees=True)
    fees = AlpacaFees(cfg)
    fee = fees.compute_fee(side="long", qty=100, fill_price=100.0)
    assert fee > 0.0


def test_zero_qty_returns_zero_fee():
    fees = AlpacaFees()
    assert fees.compute_fee(side="exit", qty=0, fill_price=100.0) == 0.0


def test_breakdown_components_sum_to_total():
    fees = AlpacaFees()
    b = fees.compute_fee_breakdown(side="exit", qty=1000, fill_price=200.0)
    assert b["total"] == pytest.approx(b["base_commission"] + b["sec_fee"] + b["taf"])


def test_factory_honors_overrides():
    fees = get_alpaca_fees({"sec_fee_per_dollar": 0.001, "taf_per_share": 0.001})
    fee = fees.compute_fee(side="exit", qty=100, fill_price=100.0)
    expected = 10_000.0 * 0.001 + 100 * 0.001
    assert fee == pytest.approx(expected, rel=1e-9)


def test_factory_disabled_when_explicit():
    fees = get_alpaca_fees({"enabled": False})
    assert fees.compute_fee(side="exit", qty=100, fill_price=100.0) == 0.0


def test_apply_to_fill_log_yields_per_row_fees():
    df = pd.DataFrame([
        {"side": "long", "qty": 100, "fill_price": 100.0},
        {"side": "exit", "qty": 100, "fill_price": 110.0},
        {"side": "short", "qty": 50, "fill_price": 50.0},
        {"side": "cover", "qty": 50, "fill_price": 45.0},
    ])
    fees = AlpacaFees()
    s = fees.apply_to_fill_log(df)
    # buy / cover free; exit + short pay
    assert s.iloc[0] == 0.0
    assert s.iloc[1] > 0.0
    assert s.iloc[2] > 0.0
    assert s.iloc[3] == 0.0


def test_realistic_round_trip_cost_under_a_few_basis_points():
    """An honest sanity check: a $10k round-trip on a mid-cap should
    cost dollars, not tens of dollars, in regulatory pass-through."""
    fees = AlpacaFees()
    qty, price = 100, 100.0
    open_fee = fees.compute_fee(side="long", qty=qty, fill_price=price)
    close_fee = fees.compute_fee(side="exit", qty=qty, fill_price=price * 1.05)
    total = open_fee + close_fee
    notional = qty * price
    bps = total / notional * 10_000
    assert 0 < bps < 5  # well under 5 bps round-trip
