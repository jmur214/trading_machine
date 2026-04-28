"""
tests/test_rule_based_edge.py
==============================
Tests for RuleBasedEdge — the edge type that DiscoveryEngine.hunt() produces
from TreeScanner-discovered patterns.

Without compute_signals(), discovered rules produced flat equity curves (no
signals → no trades → Sharpe=0.0) during validation, making every hunter
candidate fail Gate 1 with Sharpe=0.00 < benchmark threshold.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.rule_based_edge import RuleBasedEdge


def _df_with(rsi: float, vol_z: float = 0.0) -> pd.DataFrame:
    """Build a single-row DF with feature columns the rule references."""
    return pd.DataFrame({
        "Close": [100.0],
        "RSI_14": [rsi],
        "Vol_ZScore": [vol_z],
    })


def test_compute_signals_returns_score_when_rule_matches():
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 50.0",
        target_class=2,  # long
        probability=0.65,
    )
    data_map = {"AAPL": _df_with(rsi=60.0)}
    scores = edge.compute_signals(data_map, as_of=None)

    assert "AAPL" in scores
    assert scores["AAPL"] == pytest.approx(0.65)


def test_compute_signals_skips_ticker_when_rule_misses():
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 50.0",
        target_class=2,
        probability=0.65,
    )
    data_map = {"AAPL": _df_with(rsi=40.0)}
    scores = edge.compute_signals(data_map, as_of=None)

    assert scores == {}


def test_compute_signals_short_signal_negates_score():
    edge = RuleBasedEdge(
        rule_string="RSI_14 < 30.0",
        target_class=-2,  # short
        probability=0.55,
    )
    data_map = {"AAPL": _df_with(rsi=20.0)}
    scores = edge.compute_signals(data_map, as_of=None)

    assert scores["AAPL"] == pytest.approx(-0.55)


def test_compute_signals_handles_compound_rule():
    edge = RuleBasedEdge(
        rule_string="RSI_14 > 50.0 AND Vol_ZScore > 1.0",
        target_class=2,
        probability=0.7,
    )
    data_map = {
        "match": _df_with(rsi=60.0, vol_z=1.5),
        "miss":  _df_with(rsi=60.0, vol_z=0.5),
    }
    scores = edge.compute_signals(data_map, as_of=None)

    assert "match" in scores
    assert "miss" not in scores
    assert scores["match"] == pytest.approx(0.7)


def test_compute_signals_skips_when_feature_missing():
    edge = RuleBasedEdge(
        rule_string="UNKNOWN_FEATURE > 0.0",
        target_class=2,
        probability=0.6,
    )
    data_map = {"AAPL": _df_with(rsi=60.0)}
    scores = edge.compute_signals(data_map, as_of=None)

    # Missing feature → fail-safe: no signal, no error
    assert scores == {}
