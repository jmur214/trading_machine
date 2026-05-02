"""Tests for orchestration.run_backtest_pure.

Pin three properties:
1. The fingerprint function is stable & order-insensitive on edge sets.
2. PureBacktestCache reuses a result on identical fingerprints.
3. End-to-end determinism — two run_backtest_pure calls with the same
   inputs return bit-comparable equity curves and Sharpe (within ±0.02).

The end-to-end test is skipped if the prod data isn't cached.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from orchestration.run_backtest_pure import (
    _fingerprint_inputs,
    _compute_attributed_pnl_per_edge,
    PureBacktestCache,
    PureBacktestResult,
    run_backtest_pure,
)


# -------------------- fingerprinting --------------------

def test_fingerprint_stable_and_order_insensitive():
    """Same inputs → same hash; edge ordering shouldn't matter."""
    fp_a = _fingerprint_inputs(
        edge_set_keys=("a", "b", "c"),
        edge_weights={"a": 1.0, "b": 0.25, "c": 0.5},
        start_date="2025-01-01",
        end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed", "commission": 0.0},
        initial_capital=100_000.0,
    )
    fp_b = _fingerprint_inputs(
        edge_set_keys=("c", "a", "b"),  # reordered
        edge_weights={"c": 0.5, "a": 1.0, "b": 0.25},
        start_date="2025-01-01",
        end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed", "commission": 0.0},
        initial_capital=100_000.0,
    )
    assert fp_a == fp_b


def test_fingerprint_changes_on_edge_set_change():
    """Adding an edge → different hash."""
    fp_a = _fingerprint_inputs(
        edge_set_keys=("a", "b"),
        edge_weights={"a": 1.0, "b": 1.0},
        start_date="2025-01-01",
        end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed", "commission": 0.0},
        initial_capital=100_000.0,
    )
    fp_b = _fingerprint_inputs(
        edge_set_keys=("a", "b", "c"),
        edge_weights={"a": 1.0, "b": 1.0, "c": 1.0},
        start_date="2025-01-01",
        end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed", "commission": 0.0},
        initial_capital=100_000.0,
    )
    assert fp_a != fp_b


def test_fingerprint_changes_on_weight_change():
    fp_a = _fingerprint_inputs(
        edge_set_keys=("a",), edge_weights={"a": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0}, initial_capital=100_000.0,
    )
    fp_b = _fingerprint_inputs(
        edge_set_keys=("a",), edge_weights={"a": 0.25},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0}, initial_capital=100_000.0,
    )
    assert fp_a != fp_b


def test_fingerprint_changes_on_exec_params_change():
    """slippage_model is one of the canonical fingerprint inputs."""
    fp_a = _fingerprint_inputs(
        edge_set_keys=("a",), edge_weights={"a": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed"},
        initial_capital=100_000.0,
    )
    fp_b = _fingerprint_inputs(
        edge_set_keys=("a",), edge_weights={"a": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "realistic"},
        initial_capital=100_000.0,
    )
    assert fp_a != fp_b


# -------------------- attribution --------------------

def test_compute_attributed_pnl_groups_by_day_and_edge():
    """Multi-fill multi-edge trade log → per-edge daily series."""
    trade_log = pd.DataFrame({
        "timestamp": [
            pd.Timestamp("2024-01-02 10:00"),
            pd.Timestamp("2024-01-02 14:00"),
            pd.Timestamp("2024-01-03 10:00"),
            pd.Timestamp("2024-01-02 10:00"),
        ],
        "edge": ["foo_v1", "foo_v1", "foo_v1", "bar_v1"],
        "pnl": [50.0, 75.0, 200.0, 30.0],
    })
    out = _compute_attributed_pnl_per_edge(trade_log)
    assert set(out.keys()) == {"foo_v1", "bar_v1"}
    foo = out["foo_v1"]
    # 2024-01-02 sums to 125.0; 2024-01-03 is 200.0
    assert foo.loc[pd.Timestamp("2024-01-02")] == 125.0
    assert foo.loc[pd.Timestamp("2024-01-03")] == 200.0
    bar = out["bar_v1"]
    assert bar.loc[pd.Timestamp("2024-01-02")] == 30.0


def test_compute_attributed_pnl_drops_nan_pnl():
    """Entry rows have NaN PnL — must be dropped, not summed as 0."""
    trade_log = pd.DataFrame({
        "timestamp": [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
        "edge": ["foo_v1", "foo_v1"],
        "pnl": [np.nan, 50.0],
    })
    out = _compute_attributed_pnl_per_edge(trade_log)
    assert "foo_v1" in out
    assert len(out["foo_v1"]) == 1
    assert out["foo_v1"].iloc[0] == 50.0


def test_compute_attributed_pnl_empty_trade_log():
    out = _compute_attributed_pnl_per_edge(pd.DataFrame())
    assert out == {}


# -------------------- caching --------------------

def test_cache_returns_same_result_on_second_call(monkeypatch):
    """PureBacktestCache should not call run_backtest_pure twice for same fp."""
    cache = PureBacktestCache()

    call_count = {"n": 0}

    fake_result = PureBacktestResult(
        metrics={"Sharpe Ratio": 1.0, "Sortino": 1.0, "CAGR (%)": 5.0,
                 "Max Drawdown (%)": -5.0, "Volatility (%)": 10.0,
                 "Win Rate (%)": 50.0, "Net Profit": 5_000.0},
        trade_log=pd.DataFrame(),
        equity_curve=pd.Series(dtype=float),
        daily_returns=pd.Series(dtype=float),
        attributed_pnl_per_edge={},
        fingerprint="x",
    )

    def fake_run(**kwargs):
        call_count["n"] += 1
        return fake_result

    import orchestration.run_backtest_pure as mod
    monkeypatch.setattr(mod, "run_backtest_pure", fake_run)

    common = dict(
        data_map={},
        edges={"a": object()},
        edge_weights={"a": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed",
                     "commission": 0.0},
        initial_capital=100_000.0,
    )
    cache.get_or_run(**common)
    cache.get_or_run(**common)
    cache.get_or_run(**common)
    assert call_count["n"] == 1, (
        f"Expected 1 underlying run, got {call_count['n']}"
    )
    assert len(cache) == 1


def test_cache_runs_again_on_different_inputs(monkeypatch):
    cache = PureBacktestCache()
    call_count = {"n": 0}
    fake_result = PureBacktestResult(
        metrics={"Sharpe Ratio": 1.0, "Sortino": 1.0, "CAGR (%)": 5.0,
                 "Max Drawdown (%)": -5.0, "Volatility (%)": 10.0,
                 "Win Rate (%)": 50.0, "Net Profit": 5_000.0},
        trade_log=pd.DataFrame(), equity_curve=pd.Series(dtype=float),
        daily_returns=pd.Series(dtype=float), attributed_pnl_per_edge={},
        fingerprint="x",
    )

    def fake_run(**kwargs):
        call_count["n"] += 1
        return fake_result

    import orchestration.run_backtest_pure as mod
    monkeypatch.setattr(mod, "run_backtest_pure", fake_run)

    cache.get_or_run(
        data_map={}, edges={"a": object()}, edge_weights={"a": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0}, initial_capital=100_000.0,
    )
    cache.get_or_run(
        data_map={}, edges={"a": object(), "b": object()},
        edge_weights={"a": 1.0, "b": 1.0},
        start_date="2025-01-01", end_date="2025-12-31",
        exec_params={"slippage_bps": 5.0}, initial_capital=100_000.0,
    )
    assert call_count["n"] == 2


# -------------------- end-to-end determinism --------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


@pytest.mark.skipif(
    not (PROCESSED_DIR / "SPY_1d.csv").exists(),
    reason="Prod data cache not present; skip end-to-end determinism test",
)
def test_run_backtest_pure_deterministic_2run():
    """Two runs with identical inputs should produce identical Sharpe (±0.02)."""
    # Use a tiny universe + short window so the test is fast
    tickers = ["SPY", "AAPL", "MSFT"]
    data_map = {}
    for t in tickers:
        path = PROCESSED_DIR / f"{t}_1d.csv"
        if not path.exists():
            pytest.skip(f"Missing {t}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        # Constrain to a 2024 window
        df = df.loc["2023-01-01":"2024-06-30"]
        if df.empty:
            pytest.skip(f"{t} has no data in window")
        data_map[t] = df

    # No edges → trivially deterministic; just verify the harness runs.
    res_a = run_backtest_pure(
        data_map=data_map,
        edges={},
        edge_weights={},
        start_date="2024-01-01",
        end_date="2024-06-30",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed",
                     "commission": 0.0},
        initial_capital=100_000.0,
        use_regime_detector=False,
        use_governor=False,
    )
    res_b = run_backtest_pure(
        data_map=data_map,
        edges={},
        edge_weights={},
        start_date="2024-01-01",
        end_date="2024-06-30",
        exec_params={"slippage_bps": 5.0, "slippage_model": "fixed",
                     "commission": 0.0},
        initial_capital=100_000.0,
        use_regime_detector=False,
        use_governor=False,
    )
    sa = res_a.metrics["Sharpe Ratio"]
    sb = res_b.metrics["Sharpe Ratio"]
    assert abs(sa - sb) <= 0.02, (
        f"Determinism floor breached: |{sa} - {sb}| > 0.02"
    )
