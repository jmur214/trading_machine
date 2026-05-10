"""Tests for the cross-sectional momentum edges (T-2026-05-09-016).

Covers:
  momentum_12_1_v1
  momentum_6_1_v1
  short_term_reversal_v1

Each is a paused / feature-tier edge auto-registered on import. Tests
verify (a) signal shape on synthetic ranked data, (b) registration
status/tier, (c) graceful degradation on small universes / missing data,
(d) the soft-pause memory (project_soft_pause_win_2026_04_24) — paused
edges run at 0.25× weight, not zero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engines.engine_a_alpha.edges.momentum_12_1_v1 import Momentum12_1Edge  # noqa: E402
from engines.engine_a_alpha.edges.momentum_6_1_v1 import Momentum6_1Edge  # noqa: E402
from engines.engine_a_alpha.edges.short_term_reversal_v1 import ShortTermReversalEdge  # noqa: E402
from engines.engine_a_alpha.edge_registry import EdgeRegistry  # noqa: E402


EDGE_IDS = ["momentum_12_1_v1", "momentum_6_1_v1", "short_term_reversal_v1"]


def _make_data_map(returns_per_ticker: dict[str, float],
                   bars: int = 300,
                   start_price: float = 100.0) -> dict[str, pd.DataFrame]:
    """Build a synthetic data_map where ticker T's monotone-rate of return
    over `bars` business days produces approximately `returns_per_ticker[T]`
    cumulative return at end-of-series.

    Each ticker's Close series is a smooth geometric path so the trailing
    return at any horizon ≤ `bars` is close to (rate ** horizon) - 1.
    The actual cumulative return at `bars` is `(1+rate)^bars - 1`; the
    daily rate is back-solved.
    """
    idx = pd.date_range("2024-01-01", periods=bars, freq="B")
    out: dict[str, pd.DataFrame] = {}
    for ticker, total_ret in returns_per_ticker.items():
        # Daily rate r solves (1 + r)^bars = 1 + total_ret
        daily_rate = (1.0 + total_ret) ** (1.0 / bars) - 1.0
        prices = np.array([start_price * (1.0 + daily_rate) ** i
                           for i in range(bars)])
        df = pd.DataFrame({
            "Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
            "Close": prices, "Volume": 1_000_000,
        }, index=idx)
        out[ticker] = df
    return out


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_all_three_edges_register_at_paused_feature():
    """All 3 edge_ids must register at status='paused' tier='feature'."""
    reg = EdgeRegistry()
    for eid in EDGE_IDS:
        spec = next((s for s in reg.get_all_specs() if s.edge_id == eid), None)
        assert spec is not None, f"Edge {eid} did not register"
        assert spec.status == "paused", (
            f"Edge {eid} status={spec.status!r}; expected 'paused' per spec."
        )
        assert spec.tier == "feature", (
            f"Edge {eid} tier={spec.tier!r}; expected 'feature' per spec."
        )


# ---------------------------------------------------------------------------
# momentum_12_1_v1
# ---------------------------------------------------------------------------

def test_momentum_12_1_long_top_quintile_signal_shape():
    """With 50 tickers and known cumulative returns, the top-quintile
    threshold should fire on exactly the top 10 (≥ 0.80 quantile)."""
    edge = Momentum12_1Edge()
    # 50 tickers, returns 0%, 1%, 2%, ..., 49% over 300 days.
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=300)
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))

    # All top-quintile names should score 1.0; bottom 80% should be 0.0
    longs = sorted([t for t, s in scores.items() if s > 0.0])
    abstain = sorted([t for t, s in scores.items() if s == 0.0])

    # Top quintile of 50 = 10 names (the 10 with highest return — T40..T49)
    expected_longs = sorted([f"T{i:02d}" for i in range(40, 50)])
    assert longs == expected_longs, (
        f"Expected top quintile {expected_longs}, got {longs}"
    )
    assert len(abstain) == 40


def test_momentum_12_1_handles_small_universe():
    """Below min_universe_size=50, all tickers abstain (avoid concentration)."""
    edge = Momentum12_1Edge()
    rets = {f"T{i:02d}": 0.01 * i for i in range(20)}  # only 20 tickers
    data_map = _make_data_map(rets, bars=300)
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))
    assert all(s == 0.0 for s in scores.values()), (
        "Expected universal abstain on small universe; got non-zero scores."
    )


def test_momentum_12_1_handles_insufficient_history():
    """Tickers with fewer than lookback+skip+1 bars must NOT raise; they
    should be excluded from the ranking pool."""
    edge = Momentum12_1Edge()
    # Build 50 tickers but only 100 bars each — below the 252+21+1 minimum.
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=100)
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))
    # All tickers excluded → universe gate fires → all 0.0
    assert all(s == 0.0 for s in scores.values())


# ---------------------------------------------------------------------------
# momentum_6_1_v1
# ---------------------------------------------------------------------------

def test_momentum_6_1_long_top_quintile_signal_shape():
    edge = Momentum6_1Edge()
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=200)  # > 126+21+1 = 148 needed
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))
    longs = sorted([t for t, s in scores.items() if s > 0.0])
    expected_longs = sorted([f"T{i:02d}" for i in range(40, 50)])
    assert longs == expected_longs


def test_momentum_6_1_uses_shorter_horizon_than_12_1():
    """6-1 must require fewer bars than 12-1. Verify by feeding 200 bars
    (enough for 6-1 but not 12-1) — 6-1 should fire, 12-1 should universally
    abstain because it can't compute the lookback for any ticker."""
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=200)
    scores_6 = Momentum6_1Edge().compute_signals(data_map, pd.Timestamp("2024-12-31"))
    scores_12 = Momentum12_1Edge().compute_signals(data_map, pd.Timestamp("2024-12-31"))
    assert any(s > 0 for s in scores_6.values()), "6-1 should fire on 200-bar series"
    # 12-1 needs 274 bars — universe gate fires (n=0 below min)
    assert all(s == 0.0 for s in scores_12.values()), (
        "12-1 should universally abstain when no ticker has enough history"
    )


# ---------------------------------------------------------------------------
# short_term_reversal_v1
# ---------------------------------------------------------------------------

def test_short_term_reversal_long_losers_short_winners():
    """Top decile of returns → short (-1.0); bottom decile → long (+1.0);
    middle 80% abstain (0.0)."""
    edge = ShortTermReversalEdge()
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=100)  # > 21+1
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))

    longs = sorted([t for t, s in scores.items() if s > 0.0])
    shorts = sorted([t for t, s in scores.items() if s < 0.0])
    abstains = [t for t, s in scores.items() if s == 0.0]

    # Bottom decile of 50 = 5 names (T00..T04)
    # Top decile of 50 = 5 names (T45..T49)
    expected_longs = sorted([f"T{i:02d}" for i in range(0, 5)])
    expected_shorts = sorted([f"T{i:02d}" for i in range(45, 50)])
    assert longs == expected_longs, f"Expected long-losers {expected_longs}, got {longs}"
    assert shorts == expected_shorts, f"Expected short-winners {expected_shorts}, got {shorts}"
    assert len(abstains) == 40


# ---------------------------------------------------------------------------
# Common edge cases — apply to all 3
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("edge_cls", [
    Momentum12_1Edge, Momentum6_1Edge, ShortTermReversalEdge,
])
def test_edges_handle_missing_close_column_gracefully(edge_cls):
    """If a ticker's DataFrame is missing the Close column, it should be
    excluded from the ranking pool — no exception, no NaN propagated."""
    edge = edge_cls()
    rets = {f"T{i:02d}": 0.01 * i for i in range(50)}
    data_map = _make_data_map(rets, bars=300)
    # Corrupt one ticker — drop Close column entirely.
    data_map["T00"] = data_map["T00"].drop(columns=["Close"])
    scores = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))
    # Must not raise; T00 is excluded from rank but still in output dict at 0.0
    assert "T00" in scores
    assert scores["T00"] == 0.0


@pytest.mark.parametrize("edge_cls", [
    Momentum12_1Edge, Momentum6_1Edge, ShortTermReversalEdge,
])
def test_edges_handle_empty_data_map(edge_cls):
    """Empty data_map → empty score dict, no crash."""
    edge = edge_cls()
    scores = edge.compute_signals({}, pd.Timestamp("2024-12-31"))
    assert scores == {}


# ---------------------------------------------------------------------------
# Soft-pause memory check
# ---------------------------------------------------------------------------

def test_soft_pause_pattern_documented():
    """Sanity: the project's soft-pause behavior — paused edges trade at
    0.25× weight, not zero — is documented in the production code path.

    Per project_soft_pause_win_2026_04_24.md, this is load-bearing
    behavior: paused edges contribute reduced-weight signals so the
    revival gate has data to work with. New paused edges (these 3) will
    therefore contribute to ensemble at 0.25×.

    This test asserts the constant exists with the expected value in
    `orchestration/mode_controller.py`. If it changes, this test is the
    tripwire — adding more paused edges might suddenly perturb canon md5.
    """
    src = (REPO_ROOT / "orchestration" / "mode_controller.py").read_text()
    assert "PAUSED_WEIGHT_MULTIPLIER = 0.25" in src, (
        "Soft-pause multiplier missing or changed from 0.25× — "
        "see project_soft_pause_win_2026_04_24.md. New paused edges will "
        "contribute differently than expected if this constant moved."
    )
