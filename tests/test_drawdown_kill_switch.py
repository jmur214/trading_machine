"""Tests for the drawdown-gated kill switch (R1 punch-list, propose-first).

Engine C tracks peak_equity and emits current_drawdown_pct on every
snapshot. Engine B optionally consumes that signal under the
drawdown_kill_switch_enabled flag (OFF by default).
"""
from __future__ import annotations

import pandas as pd

from engines.engine_b_risk.risk_engine import RiskConfig
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine


def test_peak_equity_initializes_at_starting_capital() -> None:
    pe = PortfolioEngine(initial_capital=100_000)
    assert pe.peak_equity == 100_000.0


def test_snapshot_advances_peak_equity_monotonically() -> None:
    pe = PortfolioEngine(initial_capital=100_000)
    # No positions; cash advances synthetically by mutating cash.
    pe.cash = 110_000.0
    s1 = pe.snapshot(pd.Timestamp("2024-01-01"), price_map={})
    assert pe.peak_equity == 110_000.0
    assert s1["current_drawdown_pct"] == 0.0
    pe.cash = 105_000.0
    s2 = pe.snapshot(pd.Timestamp("2024-01-02"), price_map={})
    # Peak does NOT regress when equity drops
    assert pe.peak_equity == 110_000.0
    # Drawdown is (110k - 105k) / 110k = ~4.55%
    assert abs(s2["current_drawdown_pct"] - (5_000 / 110_000)) < 1e-9
    pe.cash = 120_000.0
    s3 = pe.snapshot(pd.Timestamp("2024-01-03"), price_map={})
    # New high advances peak
    assert pe.peak_equity == 120_000.0
    assert s3["current_drawdown_pct"] == 0.0


def test_drawdown_kill_switch_default_off_in_riskconfig() -> None:
    cfg = RiskConfig()
    assert cfg.drawdown_kill_switch_enabled is False, (
        "default must be OFF — propose-first per CLAUDE.md Engine B rules"
    )


def test_drawdown_thresholds_have_sensible_defaults() -> None:
    cfg = RiskConfig()
    assert 0.0 < cfg.drawdown_warn_threshold < cfg.drawdown_degrade_threshold
    assert cfg.drawdown_degrade_threshold < cfg.drawdown_halt_threshold
    # Degrade scaler must reduce, not amplify
    assert 0.0 < cfg.drawdown_degrade_scaler < 1.0


def test_drawdown_pct_floor_is_zero_even_above_peak() -> None:
    pe = PortfolioEngine(initial_capital=100_000)
    pe.cash = 200_000.0
    s = pe.snapshot(pd.Timestamp("2024-01-01"), price_map={})
    # Equity > peak means drawdown is exactly 0, not negative
    assert s["current_drawdown_pct"] == 0.0
    assert s["peak_equity"] == 200_000.0
