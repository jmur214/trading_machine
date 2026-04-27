"""
tests/test_signal_processor_regime_gate.py
==========================================
Tests for the regime_gate feature added to SignalProcessor in Step 4 of
Phase 2.10.

Regime gate: per-edge dict mapping Engine E regime_summary labels
("benign", "stressed", "crisis") to weight multipliers [0, 1].
When a gate is configured, the edge's effective weight in the
weighted-mean aggregation is multiplied by gate[current_regime].
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_a_alpha.signal_processor import (
    EnsembleSettings,
    HygieneSettings,
    RegimeSettings,
    SignalProcessor,
)


def _make_df(n: int = 100) -> pd.DataFrame:
    prices = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.5, n))
    return pd.DataFrame({
        "Close": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Volume": np.ones(n) * 1e6,
    })


def _make_processor(
    edge_weights: dict,
    regime_gates: dict | None = None,
) -> SignalProcessor:
    return SignalProcessor(
        regime=RegimeSettings(enable_trend=False, enable_vol=False),
        hygiene=HygieneSettings(min_history=1, clamp=1.5),
        ensemble=EnsembleSettings(enable_shrink=False),
        edge_weights=edge_weights,
        regime_gates=regime_gates or {},
    )


def _advisory(regime_summary: str) -> dict:
    return {"advisory": {"regime_summary": regime_summary, "risk_scalar": 1.0}}


# ---------------------------------------------------------------------------
# No gate: baseline behavior unchanged
# ---------------------------------------------------------------------------

def test_no_gate_passes_weight_unchanged():
    proc = _make_processor({"edge_a": 1.0}, regime_gates={})
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    assert "AAPL" in result
    assert result["AAPL"]["aggregate_score"] > 0


# ---------------------------------------------------------------------------
# Gate active: benign regime suppresses low_vol-style edge
# ---------------------------------------------------------------------------

def test_gate_suppresses_in_benign_regime():
    """Gate reduces edge_a's relative weight in benign. With two edges where
    edge_b opposes edge_a, gating edge_a produces a more negative aggregate
    (edge_b dominates) than not gating it."""
    # edge_a = positive signal, gated to 0.15 in benign
    # edge_b = negative signal, ungated at 1.0
    proc_gated = _make_processor(
        {"edge_a": 1.0, "edge_b": 1.0},
        regime_gates={"edge_a": {"benign": 0.15, "stressed": 1.0, "crisis": 1.0}},
    )
    proc_ungated = _make_processor({"edge_a": 1.0, "edge_b": 1.0}, regime_gates={})
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.8, "edge_b": -0.8}}
    now = pd.Timestamp("2024-01-01")
    meta = _advisory("benign")

    s_gated = proc_gated.process(data_map, now, raw_scores, regime_meta=meta)
    s_ungated = proc_ungated.process(data_map, now, raw_scores, regime_meta=meta)

    assert "AAPL" in s_gated
    # Gated: edge_a contributes at 0.15x → edge_b dominates → more negative
    assert s_gated["AAPL"]["aggregate_score"] < s_ungated["AAPL"]["aggregate_score"]


def test_gate_full_weight_in_stressed_regime():
    """Gate 1.0 in stressed should equal the ungated result."""
    proc_gated = _make_processor(
        {"edge_a": 0.8},
        regime_gates={"edge_a": {"benign": 0.15, "stressed": 1.0, "crisis": 1.0}},
    )
    proc_ungated = _make_processor({"edge_a": 0.8}, regime_gates={})
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}
    now = pd.Timestamp("2024-01-01")
    meta = _advisory("stressed")

    s_gated = proc_gated.process(data_map, now, raw_scores, regime_meta=meta)
    s_ungated = proc_ungated.process(data_map, now, raw_scores, regime_meta=meta)

    assert s_gated["AAPL"]["aggregate_score"] == pytest.approx(
        s_ungated["AAPL"]["aggregate_score"], rel=1e-6
    )


def test_gate_full_weight_in_crisis_regime():
    proc_gated = _make_processor(
        {"edge_a": 1.0},
        regime_gates={"edge_a": {"benign": 0.0, "stressed": 1.0, "crisis": 1.0}},
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}

    result = proc_gated.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                                regime_meta=_advisory("crisis"))
    assert result["AAPL"]["aggregate_score"] > 0


def test_gate_zero_in_benign_suppresses_completely():
    """Gate 0.0 in benign: weight_total = 0 → ticker skipped."""
    proc = _make_processor(
        {"edge_a": 1.0},
        regime_gates={"edge_a": {"benign": 0.0, "stressed": 1.0}},
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    assert "AAPL" not in result


# ---------------------------------------------------------------------------
# Gate only applies to the named edge; other edges pass through unaffected
# ---------------------------------------------------------------------------

def test_gate_selective_per_edge():
    """edge_b has a gate; edge_a does not. In benign, edge_a contributes fully."""
    proc = _make_processor(
        {"edge_a": 1.0, "edge_b": 1.0},
        regime_gates={"edge_b": {"benign": 0.0, "stressed": 1.0}},
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.8, "edge_b": 0.8}}

    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    assert "AAPL" in result  # edge_a still contributes
    detail = result["AAPL"]["edges_detail"]
    edge_b_w = next(d["weight"] for d in detail if d["edge"] == "edge_b")
    edge_a_w = next(d["weight"] for d in detail if d["edge"] == "edge_a")
    assert edge_b_w == pytest.approx(0.0)
    assert edge_a_w == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Gate defaults to 1.0 for unlisted regime labels
# ---------------------------------------------------------------------------

def test_gate_unknown_regime_defaults_to_full_weight():
    """If current regime not in gate dict, multiplier = 1.0."""
    proc_gated = _make_processor(
        {"edge_a": 1.0},
        regime_gates={"edge_a": {"stressed": 1.0, "crisis": 1.0}},
    )
    proc_ungated = _make_processor({"edge_a": 1.0})
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}
    meta = _advisory("benign")  # "benign" not listed in gate → defaults to 1.0

    s_gated = proc_gated.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                                 regime_meta=meta)
    s_ungated = proc_ungated.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                                     regime_meta=meta)

    assert s_gated["AAPL"]["aggregate_score"] == pytest.approx(
        s_ungated["AAPL"]["aggregate_score"], rel=1e-6
    )


# ---------------------------------------------------------------------------
# Gate without regime_meta falls back gracefully
# ---------------------------------------------------------------------------

def test_gate_no_regime_meta_defaults_to_benign():
    """regime_meta=None → regime treated as 'benign', gate applied accordingly."""
    proc = _make_processor(
        {"edge_a": 1.0},
        regime_gates={"edge_a": {"benign": 0.15, "stressed": 1.0}},
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.8}}

    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=None)
    # Benign gate (0.15) applied — signal present but suppressed
    assert "AAPL" in result
