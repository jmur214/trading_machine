"""
tests/test_score_based_trainer.py
==================================
Tests for the Session N+1.5 score-based feature extractor in
``scripts/train_metalearner.py``. The extractor reads raw edge scores
from each trade's `meta` JSON column, producing features that match
the shape SignalProcessor sees at inference time.

This addresses the trainer-inference feature-shape gap from Session
N+1, where the trainer's PnL-summary features couldn't compose with
the inference path's raw-score inputs.

Coverage:
  - load_per_edge_daily_raw_scores parses trade log meta correctly
  - Numpy reprs (np.float64(...)) are stripped before parsing
  - Empty/missing/malformed meta rows are skipped silently
  - Aggregation to (date × edge) averages is correct
  - build_features_from_raw_scores fills NaN with 0.0
  - Sparse-input handling: SignalProcessor zero-fills missing edges
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.train_metalearner import (
    _NUMPY_REPR_PATTERN,
    build_features_from_raw_scores,
    load_per_edge_daily_raw_scores,
)


# ---------------------------------------------------------------------------
# Helpers — synthesize a minimal trade log
# ---------------------------------------------------------------------------

def _meta_with_edges(edges: list[dict]) -> str:
    """Build a meta-string with the given edges_triggered list."""
    return repr({
        "edges_triggered": edges,
        "regimes": {"trend": True, "vol_ok": True},
        "market_state": {},
    })


def _write_synthetic_trades(path: Path, rows: list[dict]) -> None:
    """rows: list of {timestamp, ticker, side, qty, fill_price, pnl, edge,
    trigger, meta}. Other columns get sensible defaults."""
    full = []
    for r in rows:
        full.append({
            "timestamp": r["timestamp"],
            "ticker": r.get("ticker", "AAPL"),
            "side": r.get("side", "long"),
            "qty": r.get("qty", 1),
            "fill_price": r.get("fill_price", 100.0),
            "commission": 0.0,
            "pnl": r.get("pnl", 0.0),
            "edge": r["edge"],
            "edge_group": "technical",
            "trigger": r.get("trigger", "entry"),
            "meta": r["meta"],
            "edge_id": r["edge"],
            "edge_category": "technical",
            "run_id": "test",
            "regime_label": "neutral",
        })
    pd.DataFrame(full).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# load_per_edge_daily_raw_scores — happy path
# ---------------------------------------------------------------------------

def test_extracts_raw_scores_from_meta(tmp_path):
    path = tmp_path / "trades.csv"
    _write_synthetic_trades(path, [
        {
            "timestamp": "2024-01-02", "edge": "edge_a",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.5},
                {"edge": "edge_b", "edge_id": "edge_b", "raw": 0.3},
            ]),
        },
        {
            "timestamp": "2024-01-03", "edge": "edge_a",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.7},
            ]),
        },
    ])
    pivot = load_per_edge_daily_raw_scores(path)
    assert pivot.shape == (2, 2)
    assert "edge_a" in pivot.columns
    assert "edge_b" in pivot.columns
    # Day 1: edge_a=0.5, edge_b=0.3
    assert pivot.loc[pd.Timestamp("2024-01-02"), "edge_a"] == pytest.approx(0.5)
    assert pivot.loc[pd.Timestamp("2024-01-02"), "edge_b"] == pytest.approx(0.3)
    # Day 2: only edge_a fired
    assert pivot.loc[pd.Timestamp("2024-01-03"), "edge_a"] == pytest.approx(0.7)
    assert pd.isna(pivot.loc[pd.Timestamp("2024-01-03"), "edge_b"])


def test_aggregates_multiple_fills_same_day_to_mean(tmp_path):
    """Two AAPL fills on the same day with edge_a → mean of the raw scores."""
    path = tmp_path / "trades.csv"
    _write_synthetic_trades(path, [
        {
            "timestamp": "2024-01-02", "ticker": "AAPL", "edge": "edge_a",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.4},
            ]),
        },
        {
            "timestamp": "2024-01-02", "ticker": "MSFT", "edge": "edge_a",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.8},
            ]),
        },
    ])
    pivot = load_per_edge_daily_raw_scores(path)
    # Mean of 0.4 and 0.8 = 0.6
    assert pivot.loc[pd.Timestamp("2024-01-02"), "edge_a"] == pytest.approx(0.6)


def test_strips_numpy_reprs_before_parsing(tmp_path):
    """Meta strings often contain np.float64(...) reprs (from realistic-
    cost backtest's regime_meta) — extractor must strip these so
    ast.literal_eval can parse."""
    path = tmp_path / "trades.csv"
    # Embed np.float64 in the meta string, simulating production output
    meta_with_np = (
        "{'edges_triggered': [{'edge': 'edge_a', 'edge_id': 'edge_a', 'raw': 0.6}], "
        "'regimes': {'vix': np.float64(15.3), 'count': np.int64(7)}}"
    )
    _write_synthetic_trades(path, [
        {"timestamp": "2024-01-02", "edge": "edge_a", "meta": meta_with_np},
    ])
    pivot = load_per_edge_daily_raw_scores(path)
    assert pivot.loc[pd.Timestamp("2024-01-02"), "edge_a"] == pytest.approx(0.6)


def test_numpy_repr_pattern_handles_known_numpy_types():
    """The regex must catch every numpy repr that appears in production."""
    samples = [
        ("np.float64(1.5)", "1.5"),
        ("np.int64(7)", "7"),
        ("np.int32(42)", "42"),
        ("np.float32(0.5)", "0.5"),
        ("np.bool_(True)", "True"),
    ]
    for sample, expected in samples:
        result = _NUMPY_REPR_PATTERN.sub(r"\1", sample)
        assert result == expected, f"{sample} → {result}, expected {expected}"


def test_skips_unparseable_meta_silently(tmp_path):
    """A row with garbage meta shouldn't crash the extractor — it just
    contributes nothing to the output."""
    path = tmp_path / "trades.csv"
    _write_synthetic_trades(path, [
        {
            "timestamp": "2024-01-02", "edge": "edge_a",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.5},
            ]),
        },
        {
            "timestamp": "2024-01-03", "edge": "edge_a",
            "meta": "{'broken': syntax error here:::",
        },
    ])
    pivot = load_per_edge_daily_raw_scores(path)
    # Day 1 made it; day 2 was skipped silently
    assert len(pivot) == 1
    assert pivot.loc[pd.Timestamp("2024-01-02"), "edge_a"] == pytest.approx(0.5)


def test_skips_non_entry_trigger_when_present(tmp_path):
    """Only entry trades carry signal; exits have stale meta. Filter to entries."""
    path = tmp_path / "trades.csv"
    _write_synthetic_trades(path, [
        {
            "timestamp": "2024-01-02", "edge": "edge_a", "trigger": "entry",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.5},
            ]),
        },
        {
            "timestamp": "2024-01-03", "edge": "edge_a", "trigger": "exit",
            "meta": _meta_with_edges([
                {"edge": "edge_a", "edge_id": "edge_a", "raw": 0.99},
            ]),
        },
    ])
    pivot = load_per_edge_daily_raw_scores(path)
    # Only the entry was kept
    assert len(pivot) == 1
    assert pd.Timestamp("2024-01-02") in pivot.index
    assert pd.Timestamp("2024-01-03") not in pivot.index


def test_raises_when_meta_column_missing(tmp_path):
    path = tmp_path / "trades.csv"
    pd.DataFrame({
        "timestamp": ["2024-01-02"], "edge": ["edge_a"], "trigger": ["entry"],
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="no 'meta' column"):
        load_per_edge_daily_raw_scores(path)


def test_raises_when_no_raw_scores_extractable(tmp_path):
    """Meta column exists but no row produces a parseable edges_triggered
    with raw scores — fail loud rather than return empty."""
    path = tmp_path / "trades.csv"
    _write_synthetic_trades(path, [
        {
            "timestamp": "2024-01-02", "edge": "edge_a",
            "meta": _meta_with_edges([]),  # empty edges_triggered
        },
    ])
    with pytest.raises(ValueError, match="No edge raw scores"):
        load_per_edge_daily_raw_scores(path)


# ---------------------------------------------------------------------------
# build_features_from_raw_scores — NaN handling
# ---------------------------------------------------------------------------

def test_build_features_fills_nan_with_zero():
    """Bars where an edge didn't fire have NaN; build_features fills with
    0.0 to match inference behavior (no edge fired = neutral input)."""
    raw = pd.DataFrame({
        "edge_a": [0.5, np.nan, 0.7],
        "edge_b": [np.nan, 0.3, np.nan],
    }, index=pd.date_range("2024-01-02", periods=3))
    features = build_features_from_raw_scores(raw)
    assert features["edge_a"].iloc[1] == 0.0
    assert features["edge_b"].iloc[0] == 0.0
    # Original non-NaN values preserved
    assert features["edge_a"].iloc[0] == pytest.approx(0.5)
    assert features["edge_b"].iloc[1] == pytest.approx(0.3)


def test_build_features_preserves_column_order_and_index():
    raw = pd.DataFrame({
        "edge_z": [0.1, 0.2],
        "edge_a": [0.3, 0.4],
    }, index=pd.date_range("2024-01-02", periods=2))
    features = build_features_from_raw_scores(raw)
    assert list(features.columns) == ["edge_z", "edge_a"]
    pd.testing.assert_index_equal(features.index, raw.index)


# ---------------------------------------------------------------------------
# Sparse-input handling in SignalProcessor (the architectural property)
# ---------------------------------------------------------------------------

def test_signal_processor_zero_fills_missing_trained_features(tmp_path):
    """SignalProcessor's _metalearner_contribution must zero-fill any
    trained feature absent from the current bar's edge_map. This is the
    fix that makes the trainer-inference shapes compose."""
    from engines.engine_a_alpha.metalearner import MetaLearner
    from engines.engine_a_alpha.signal_processor import (
        EnsembleSettings, HygieneSettings, MetaLearnerSettings,
        RegimeSettings, SignalProcessor,
    )
    import engines.engine_a_alpha.metalearner as ml_mod

    # Train on 3 features
    rng = np.random.default_rng(0)
    X = pd.DataFrame({
        "feat_1": rng.normal(0, 0.5, 200),
        "feat_2": rng.normal(0, 0.5, 200),
        "feat_3": rng.normal(0, 0.5, 200),
    })
    y = pd.Series(0.5 * X["feat_1"] + 0.3 * X["feat_2"] - 0.2 * X["feat_3"])
    ml = MetaLearner(profile_name="sparse_test").fit(X, y)
    ml.save(model_dir=tmp_path)

    orig_dir = ml_mod.DEFAULT_MODEL_DIR
    ml_mod.DEFAULT_MODEL_DIR = tmp_path
    try:
        sp = SignalProcessor(
            regime=RegimeSettings(enable_trend=False, enable_vol=False),
            hygiene=HygieneSettings(min_history=10),
            ensemble=EnsembleSettings(enable_shrink=False),
            edge_weights={},
            metalearner_settings=MetaLearnerSettings(
                enabled=True, profile_name="sparse_test", contribution_weight=1.0,
            ),
            edge_tiers={"feat_1": "feature", "feat_2": "feature", "feat_3": "feature"},
        )
        # Only feat_1 fires this bar — feat_2, feat_3 missing → zero-fill
        contrib_sparse = sp._metalearner_contribution({"feat_1": 0.5})
        # Should NOT raise. Should produce some non-zero finite number.
        assert isinstance(contrib_sparse, float)
        assert -1.0 <= contrib_sparse <= 1.0  # bounded by clip + contribution_weight
    finally:
        ml_mod.DEFAULT_MODEL_DIR = orig_dir


def test_signal_processor_returns_zero_when_no_feature_edges_fire(tmp_path):
    """If NO trained feature edges fire this bar (all dict entries are
    tier=alpha or absent), contribution = 0 — model has no input."""
    from engines.engine_a_alpha.metalearner import MetaLearner
    from engines.engine_a_alpha.signal_processor import (
        EnsembleSettings, HygieneSettings, MetaLearnerSettings,
        RegimeSettings, SignalProcessor,
    )
    import engines.engine_a_alpha.metalearner as ml_mod

    rng = np.random.default_rng(0)
    X = pd.DataFrame({"feat_x": rng.normal(0, 0.5, 100)})
    y = pd.Series(0.3 * X["feat_x"])
    ml = MetaLearner(profile_name="zero_input").fit(X, y)
    ml.save(model_dir=tmp_path)

    orig_dir = ml_mod.DEFAULT_MODEL_DIR
    ml_mod.DEFAULT_MODEL_DIR = tmp_path
    try:
        sp = SignalProcessor(
            regime=RegimeSettings(enable_trend=False, enable_vol=False),
            hygiene=HygieneSettings(min_history=10),
            ensemble=EnsembleSettings(enable_shrink=False),
            edge_weights={},
            metalearner_settings=MetaLearnerSettings(
                enabled=True, profile_name="zero_input", contribution_weight=1.0,
            ),
            edge_tiers={"only_alpha_edge": "alpha"},
        )
        # Only an alpha edge fires; no feature edges in edge_map at all.
        contrib = sp._metalearner_contribution({"only_alpha_edge": 0.9})
        assert contrib == 0.0
    finally:
        ml_mod.DEFAULT_MODEL_DIR = orig_dir
