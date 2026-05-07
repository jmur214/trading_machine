"""tests/test_rule_based_edge_features.py
=============================================

Lock-in tests for the 2026-05-07 fix that closed the HIGH finding
"RuleBasedEdge requires FeatureEngineer-computed columns absent from
validation data_map" (`docs/State/health_check.md`).

Pre-fix path:
- TreeScanner discovers a rule like "RSI_14 > 50 AND Vol_ZScore > 1.0"
- RuleBasedEdge instantiated with that rule string in validate_candidate
- check_signal reads row[feat] for engineered features (RSI_14 etc.)
- The validation data_map has only OHLCV columns
- `if feat not in row: return None` triggers on every bar
- Sharpe = 0.00 → Discovery cycle never promotes the rule

Post-fix path:
- compute_signals runs FeatureEngineer.compute_all_features() on each
  ticker's OHLCV inline before invoking check_signal
- Engineered columns (RSI_14, Vol_ZScore, ATR_Pct, etc.) are present
- Cached by (ticker, last_bar_index) so growing-DataFrame backtesting
  doesn't recompute the full history every bar
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engines.engine_a_alpha.edges.rule_based_edge import RuleBasedEdge


def _ohlcv(n_bars: int = 250, seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV — no engineered features. The pre-fix path crashed
    on this; post-fix should enrich it inline."""
    idx = pd.date_range("2024-01-02", periods=n_bars, freq="B")
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.015, n_bars))
    return pd.DataFrame({
        "Open": closes * 0.99,
        "High": closes * 1.02,
        "Low": closes * 0.98,
        "Close": closes,
        "Volume": rng.integers(1_000_000, 5_000_000, n_bars),
    }, index=idx)


def test_trivial_rule_fires_with_only_ohlcv_input():
    """Pre-fix: trivial rule like 'RSI_14 > 0' returned {} because RSI_14
    wasn't in the OHLCV-only DataFrame. Post-fix: enrichment populates
    RSI_14, the rule fires."""
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 0", target_class=2, probability=0.7,
        description="trivial RSI rule",
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert "AAPL" in scores, (
        "Trivial rule 'RSI_14 > 0' should always fire on enriched data — "
        "if it didn't, FeatureEngineer enrichment isn't running."
    )
    assert scores["AAPL"] == 0.7, "Long direction × probability"


def test_short_direction_rule():
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 0", target_class=-2, probability=0.6,
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert scores.get("AAPL") == -0.6, "Short direction × probability"


def test_rule_referencing_volume_feature_fires():
    """Vol_ZScore is engineered from Volume. Pre-fix the rule never fired
    because Vol_ZScore wasn't in row. Post-fix enrichment computes it."""
    edge = RuleBasedEdge(
        rule_string="Vol_ZScore > -1000", target_class=2, probability=0.5,
        description="trivial volume condition",
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert "AAPL" in scores, "Vol_ZScore-referencing rule must fire post-fix"


def test_rule_with_unsatisfied_conditions_returns_no_signal():
    """The fix populates features but doesn't override rule semantics —
    a rule with conditions that don't match should still return no signal."""
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 999", target_class=2, probability=0.7,
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert "AAPL" not in scores, (
        "RSI > 999 is impossible — rule must produce no signal even with "
        "enriched data."
    )


def test_feature_cache_populated_on_first_call():
    """The fix uses (ticker, last_index) cache to amortize the
    100ms-per-call cost of FeatureEngineer over the bar."""
    edge = RuleBasedEdge(rule_string="RSI_14 > 0", target_class=2, probability=0.7)
    df = _ohlcv()
    edge.compute_signals({"AAPL": df})
    # Cache key is (ticker, last_index)
    cache_key = ("AAPL", df.index[-1])
    assert cache_key in edge._feat_cache


def test_feature_cache_reused_on_same_dataframe():
    """Same DataFrame passed twice should hit the cache, not recompute."""
    edge = RuleBasedEdge(rule_string="RSI_14 > 0", target_class=2, probability=0.7)
    df = _ohlcv()
    edge.compute_signals({"AAPL": df})
    enriched_first = edge._feat_cache[("AAPL", df.index[-1])]
    edge.compute_signals({"AAPL": df})
    enriched_second = edge._feat_cache[("AAPL", df.index[-1])]
    assert enriched_first is enriched_second, "Cache should return the same object on hit"


def test_feature_cache_invalidates_when_dataframe_grows():
    """Backtester typically grows the DataFrame bar-by-bar. A new last_index
    means a cache miss and recompute (which is correct — features change)."""
    edge = RuleBasedEdge(rule_string="RSI_14 > 0", target_class=2, probability=0.7)
    full = _ohlcv(n_bars=250)
    short = full.iloc[:200]
    long = full
    edge.compute_signals({"AAPL": short})
    edge.compute_signals({"AAPL": long})
    # Both cache entries exist — different keys
    assert ("AAPL", short.index[-1]) in edge._feat_cache
    assert ("AAPL", long.index[-1]) in edge._feat_cache


def test_empty_dataframe_returns_no_signal():
    """Edge case: empty DataFrame should produce no signal, not crash."""
    edge = RuleBasedEdge(rule_string="RSI_14 > 0", target_class=2, probability=0.7)
    scores = edge.compute_signals({"AAPL": pd.DataFrame()})
    assert "AAPL" not in scores


def test_unknown_feature_still_returns_no_signal_safely():
    """A rule referencing a feature FeatureEngineer doesn't compute (e.g.,
    a fundamental like PE) should fall through to 'feat not in row → None'
    safely. The fix populates technical features only; unknown feature =
    no signal, not a crash."""
    edge = RuleBasedEdge(
        rule_string="MadeUpFundamental > 10", target_class=2, probability=0.7,
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert "AAPL" not in scores, (
        "Rule referencing unknown feature should produce no signal, not crash."
    )


def test_compound_rule_fires_when_all_conditions_match():
    """AND-compound rule: all conditions must match. Synthetic data should
    occasionally satisfy 'RSI_14 > 0 AND Vol_ZScore > -1000' (both
    near-trivially true on enriched data)."""
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 0 AND Vol_ZScore > -1000", target_class=2, probability=0.5,
    )
    scores = edge.compute_signals({"AAPL": _ohlcv()})
    assert "AAPL" in scores
