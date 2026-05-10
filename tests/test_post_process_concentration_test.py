"""Tests for scripts/post_process_concentration_test.py (T-2026-05-09-003).

Covers:
  - reconstruct_paired_trades: multi-fill add → single position pairing
  - hypothetical_pnl: per-position-target → notional → qty → PnL math
  - _ci_overlap: bootstrap CI overlap helper
  - Determinism: same trade log → bit-identical outputs across two runs

Tests don't read the real T-002 trade logs (those would couple the test
to data on disk). Synthetic in-memory trade logs exercise the logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.post_process_concentration_test import (  # noqa: E402
    reconstruct_paired_trades,
    hypothetical_pnl,
    _ci_overlap,
    INITIAL_CAPITAL,
)


def _trades_df(rows: list[dict]) -> pd.DataFrame:
    """Build a sorted trades DataFrame from a list of row dicts."""
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["fill_price"] = pd.to_numeric(df["fill_price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    return df.sort_values(["timestamp", "ticker", "edge_id"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# reconstruct_paired_trades
# ---------------------------------------------------------------------------

def test_single_entry_single_exit():
    """Simplest case: one entry, one exit, one paired trade."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "long",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 110.0, "pnl": 100.0, "edge_id": "E1", "trigger": "take_profit"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["ticker"] == "AAPL"
    assert p["edge_id"] == "E1"
    assert p["side"] == "long"
    assert p["avg_entry_price"] == 100.0
    assert p["total_qty"] == 10.0
    assert p["exit_price"] == 110.0
    assert p["original_pnl"] == 100.0
    assert p["n_concurrent_at_open"] == 1


def test_multi_fill_entry_does_not_inflate_concurrent_count():
    """Critical correctness test: multi-fill adds to the SAME (ticker, edge_id)
    position must NOT increment the concurrent-positions counter. The bug
    we found in v1 was treating each fill as a separate position."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "long",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-03", "ticker": "AAPL", "side": "long",  # ADD to same position
         "qty": 5, "fill_price": 102.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-04", "ticker": "AAPL", "side": "long",  # another ADD
         "qty": 5, "fill_price": 104.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 20, "fill_price": 110.0, "pnl": 200.0, "edge_id": "E1", "trigger": "take_profit"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert len(pairs) == 1, f"Expected 1 paired trade, got {len(pairs)}"
    p = pairs[0]
    # Qty-weighted avg: (100*10 + 102*5 + 104*5) / 20 = (1000+510+520)/20 = 101.5
    assert abs(p["avg_entry_price"] - 101.5) < 1e-9
    assert p["total_qty"] == 20.0
    assert p["n_concurrent_at_open"] == 1, (
        "Multi-fill adds inflated the open count — pairing logic is broken"
    )


def test_concurrent_positions_count_reflects_distinct_keys():
    """Two distinct (ticker, edge_id) positions open at once → count = 2."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "long",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-03", "ticker": "MSFT", "side": "long",
         "qty": 5, "fill_price": 200.0, "pnl": np.nan, "edge_id": "E2", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 110.0, "pnl": 100.0, "edge_id": "E1", "trigger": "take_profit"},
        {"timestamp": "2024-01-11", "ticker": "MSFT", "side": "exit",
         "qty": 5, "fill_price": 210.0, "pnl": 50.0, "edge_id": "E2", "trigger": "take_profit"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert len(pairs) == 2
    # AAPL opened first (count=1), MSFT opened second (count=2)
    aapl = next(p for p in pairs if p["ticker"] == "AAPL")
    msft = next(p for p in pairs if p["ticker"] == "MSFT")
    assert aapl["n_concurrent_at_open"] == 1
    assert msft["n_concurrent_at_open"] == 2


def test_position_reopens_after_exit():
    """A (ticker, edge_id) that closes and re-opens later → 2 separate paired trades."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "long",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 110.0, "pnl": 100.0, "edge_id": "E1", "trigger": "take_profit"},
        {"timestamp": "2024-02-01", "ticker": "AAPL", "side": "long",
         "qty": 5, "fill_price": 105.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-02-15", "ticker": "AAPL", "side": "exit",
         "qty": 5, "fill_price": 100.0, "pnl": -25.0, "edge_id": "E1", "trigger": "stop"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert len(pairs) == 2
    assert pairs[0]["original_pnl"] == 100.0
    assert pairs[1]["original_pnl"] == -25.0


def test_short_position_records_side_correctly():
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "short",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 90.0, "pnl": 100.0, "edge_id": "E1", "trigger": "take_profit"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert pairs[0]["side"] == "short"


def test_orphan_exit_is_skipped():
    """Exit without a matching entry → skipped, no crash."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 110.0, "pnl": 100.0, "edge_id": "E1", "trigger": "exit"},
    ])
    pairs = reconstruct_paired_trades(df)
    assert pairs == []


# ---------------------------------------------------------------------------
# hypothetical_pnl
# ---------------------------------------------------------------------------

def test_hypothetical_pnl_long():
    """Long entry $100, exit $110, target 10%.
    notional = $100k × 0.10 = $10,000; qty = 100 shares;
    pnl = 100 × (110 - 100) = $1,000."""
    pair = {"avg_entry_price": 100.0, "exit_price": 110.0, "side": "long"}
    result = hypothetical_pnl(pair, per_position_target=0.10)
    expected = (110.0 - 100.0) * (INITIAL_CAPITAL * 0.10 / 100.0)
    assert abs(result - expected) < 1e-9
    assert abs(result - 1000.0) < 1e-9


def test_hypothetical_pnl_short():
    """Short at $100, cover at $90 → +$10/share gain. 10% of $100k → 100 shares × $10 = $1000."""
    pair = {"avg_entry_price": 100.0, "exit_price": 90.0, "side": "short"}
    result = hypothetical_pnl(pair, per_position_target=0.10)
    assert abs(result - 1000.0) < 1e-9, f"Expected +1000, got {result}"


def test_hypothetical_pnl_invalid_entry_price():
    """Entry price NaN or zero → 0.0, no crash."""
    pair = {"avg_entry_price": np.nan, "exit_price": 110.0, "side": "long"}
    assert hypothetical_pnl(pair, 0.10) == 0.0
    pair = {"avg_entry_price": 0.0, "exit_price": 110.0, "side": "long"}
    assert hypothetical_pnl(pair, 0.10) == 0.0


def test_hypothetical_pnl_scales_linearly_with_target():
    """2× target → 2× hypothetical PnL."""
    pair = {"avg_entry_price": 100.0, "exit_price": 110.0, "side": "long"}
    p1 = hypothetical_pnl(pair, 0.10)
    p2 = hypothetical_pnl(pair, 0.20)
    assert abs(p2 - 2 * p1) < 1e-9


# ---------------------------------------------------------------------------
# _ci_overlap
# ---------------------------------------------------------------------------

def test_ci_overlap_overlapping():
    assert _ci_overlap(0.0, 1.0, 0.5, 1.5) is True
    assert _ci_overlap(-1.0, 1.0, -0.5, 0.5) is True  # b nested in a
    assert _ci_overlap(0.0, 1.0, 1.0, 2.0) is True   # touching at endpoint


def test_ci_overlap_disjoint():
    assert _ci_overlap(0.0, 1.0, 1.5, 2.5) is False
    assert _ci_overlap(2.0, 3.0, 0.0, 1.0) is False


# ---------------------------------------------------------------------------
# Determinism / reproducibility
# ---------------------------------------------------------------------------

def test_reconstruct_paired_trades_is_deterministic():
    """Same input → same output across two calls."""
    df = _trades_df([
        {"timestamp": "2024-01-02", "ticker": "AAPL", "side": "long",
         "qty": 10, "fill_price": 100.0, "pnl": np.nan, "edge_id": "E1", "trigger": "entry"},
        {"timestamp": "2024-01-02", "ticker": "MSFT", "side": "long",
         "qty": 5, "fill_price": 200.0, "pnl": np.nan, "edge_id": "E2", "trigger": "entry"},
        {"timestamp": "2024-01-10", "ticker": "AAPL", "side": "exit",
         "qty": 10, "fill_price": 110.0, "pnl": 100.0, "edge_id": "E1", "trigger": "take_profit"},
        {"timestamp": "2024-01-15", "ticker": "MSFT", "side": "exit",
         "qty": 5, "fill_price": 210.0, "pnl": 50.0, "edge_id": "E2", "trigger": "take_profit"},
    ])
    p1 = reconstruct_paired_trades(df)
    p2 = reconstruct_paired_trades(df)

    # Compare key fields (ts may carry pandas Timestamp objects which are equal but not identical)
    assert len(p1) == len(p2)
    for a, b in zip(p1, p2):
        for k in ["ticker", "edge_id", "side", "avg_entry_price",
                  "total_qty", "exit_price", "original_pnl",
                  "n_concurrent_at_open"]:
            assert a[k] == b[k], f"Mismatch on field {k}: {a[k]} vs {b[k]}"


def test_full_pipeline_smoke():
    """Sanity-check the full pipeline on the actual T-002 Arm 1 2025 trade
    log if it's present. Skips if not."""
    log_path = REPO_ROOT / "data" / "trade_logs" / "a3aac752-6daa-487a-a3e5-2f1e4d81d319" / "trades.csv"
    if not log_path.exists():
        pytest.skip("T-002 Arm 1 2025 trade log not present in worktree")
    from scripts.post_process_concentration_test import compute_per_year
    result = compute_per_year(2025, "a3aac752-6daa-487a-a3e5-2f1e4d81d319")
    assert result["ok"]
    # Sanity: at least 100 paired trades, and concurrent-at-open ≤ 600
    # (109-ticker universe × 6 edges = 654 max possible distinct positions)
    assert result["n_paired_trades"] > 100
    assert result["n_concurrent_at_open_max"] <= 600
