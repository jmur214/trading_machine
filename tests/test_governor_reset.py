"""
tests/test_governor_reset.py
============================
Tests for StrategyGovernor.reset_weights() — the --reset-governor feature.

The governor's learned affinity (edge_weights.json) is production state.
When used for in-sample backtests, stale OOS weights contaminate results.
reset_weights() clears in-memory weights to neutral (1.0) without touching
the persisted file so the next run that does NOT reset still loads the
production state.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_f_governance.governor import StrategyGovernor


def _make_governor(tmp_path: Path, weights: dict) -> StrategyGovernor:
    state = tmp_path / "edge_weights.json"
    state.write_text(json.dumps({"weights": weights}))
    cfg_path = tmp_path / "governor_settings.json"
    cfg_path.write_text(json.dumps({"ema_halflife_days": 30, "lifecycle_enabled": False}))
    return StrategyGovernor(config_path=str(cfg_path), state_path=str(state))


def test_reset_weights_clears_in_memory_weights(tmp_path):
    """After reset_weights(), get_edge_weights() returns neutral (1.0) for all edges."""
    gov = _make_governor(tmp_path, {"atr_breakout_v1": 0.587, "momentum_edge_v1": 0.528})
    assert gov.get_edge_weights()["atr_breakout_v1"] < 0.7

    gov.reset_weights()

    weights = gov.get_edge_weights()
    # With empty internal dict, every edge defaults to 1.0 via .get(edge, 1.0)
    assert weights.get("atr_breakout_v1", 1.0) == 1.0
    assert weights.get("momentum_edge_v1", 1.0) == 1.0


def test_reset_weights_does_not_touch_disk(tmp_path):
    """reset_weights() does NOT overwrite edge_weights.json — persisted state is unchanged."""
    state_path = tmp_path / "edge_weights.json"
    original_weights = {"atr_breakout_v1": 0.587, "momentum_edge_v1": 0.528}
    state_path.write_text(json.dumps({"weights": original_weights}))
    cfg_path = tmp_path / "governor_settings.json"
    cfg_path.write_text(json.dumps({"ema_halflife_days": 30, "lifecycle_enabled": False}))

    gov = StrategyGovernor(config_path=str(cfg_path), state_path=str(state_path))
    gov.reset_weights()

    on_disk = json.loads(state_path.read_text())["weights"]
    assert on_disk["atr_breakout_v1"] == pytest.approx(0.587)
    assert on_disk["momentum_edge_v1"] == pytest.approx(0.528)


def test_reset_weights_clears_regime_weights(tmp_path):
    """reset_weights() also clears _regime_weights so regime-conditional blending is neutral."""
    gov = _make_governor(tmp_path, {"edge_a": 0.4, "edge_b": 0.9})
    gov._regime_weights = {"bull": {"edge_a": 0.8}, "bear": {"edge_b": 0.3}}

    gov.reset_weights()

    assert gov._regime_weights == {}


def test_reset_weights_idempotent(tmp_path):
    """Calling reset_weights() multiple times is safe."""
    gov = _make_governor(tmp_path, {"edge_a": 0.5})
    gov.reset_weights()
    gov.reset_weights()
    assert gov.get_edge_weights().get("edge_a", 1.0) == 1.0
