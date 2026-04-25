"""
tests/test_evolution_controller.py
===================================
Tests for `engines/engine_f_governance/evolution_controller.py` — the
autonomous Discovery → WFO → promote/fail cycle.

Critical-path autonomy code that was rewired in Phase γ (2026-04-24) to
call `WalkForwardOptimizer` directly instead of subprocessing a missing
script. Had zero test coverage prior to today; the registry-stomp bug
discovery on 2026-04-25 motivated tightening test coverage on adjacent
autonomy code.

Tests use temp directories + mocking the WFO call so no real backtests
run (those would take minutes per test). The mocking pattern is
narrow — we override `run_wfo_for_candidate` rather than going deeper,
since that's the seam between this controller and the WFO machinery.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_f_governance.evolution_controller import EvolutionController


@pytest.fixture
def tmp_project(tmp_path):
    """A temp dir layout that EvolutionController can use as project_root."""
    (tmp_path / "data" / "governor").mkdir(parents=True)
    (tmp_path / "config").mkdir(parents=True)
    return tmp_path


def _seed_registry(project_root: Path, edges: list[dict]) -> Path:
    path = project_root / "data" / "governor" / "edges.yml"
    path.write_text(yaml.dump({"edges": edges}, sort_keys=False))
    return path


def _seed_alpha_config(project_root: Path) -> Path:
    """Minimal alpha_settings.prod.json so update_production_config works."""
    cfg = {"edge_weights": {}}
    path = project_root / "config" / "alpha_settings.prod.json"
    path.write_text(json.dumps(cfg, indent=2))
    return path


# ---------------------------------------------------------------------------
# Empty / no-op cases
# ---------------------------------------------------------------------------

def test_run_cycle_no_op_when_no_candidates(tmp_project, caplog):
    """If no edges have status=candidate, the cycle short-circuits cleanly."""
    _seed_registry(tmp_project, [
        {"edge_id": "active_one", "status": "active",
         "category": "technical", "module": "m", "version": "1.0.0"},
    ])
    ctrl = EvolutionController(project_root=str(tmp_project))
    # Should not raise, should not call WFO
    with patch.object(ctrl, "run_wfo_for_candidate") as mock_wfo:
        ctrl.run_cycle()
        mock_wfo.assert_not_called()


def test_run_cycle_handles_missing_registry_gracefully(tmp_project):
    """If edges.yml doesn't exist, load_edges returns [] — no crash."""
    # Don't seed registry
    ctrl = EvolutionController(project_root=str(tmp_project))
    edges = ctrl.load_edges()
    assert edges == []
    # And run_cycle should also no-op
    ctrl.run_cycle()  # should not raise


# ---------------------------------------------------------------------------
# Promotion path
# ---------------------------------------------------------------------------

def test_run_cycle_promotes_winners(tmp_project):
    """A candidate that passes WFO should be promoted to status=active."""
    _seed_registry(tmp_project, [
        {"edge_id": "winner_v1", "status": "candidate",
         "category": "technical", "module": "engines.test_module",
         "class": "TestEdge", "version": "1.0.0", "params": {"a": 1}},
    ])
    _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))
    # Mock WFO to return PASS
    with patch.object(ctrl, "run_wfo_for_candidate",
                      return_value=(True, 1.5, None)):
        ctrl.run_cycle()

    final = yaml.safe_load(
        (tmp_project / "data" / "governor" / "edges.yml").read_text()
    )
    statuses = {e["edge_id"]: e["status"] for e in final["edges"]}
    assert statuses["winner_v1"] == "active"


def test_run_cycle_promotion_writes_alpha_config(tmp_project):
    """Promoted edges should have their params persisted to alpha_settings.
    Verifies update_production_config side effect."""
    _seed_registry(tmp_project, [
        {"edge_id": "to_promote", "status": "candidate",
         "category": "technical", "module": "m",
         "class": "TestEdge", "version": "1.0.0",
         "params": {"window": 14, "thresh": 2.0}},
    ])
    cfg_path = _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))
    with patch.object(ctrl, "run_wfo_for_candidate",
                      return_value=(True, 1.0, None)):
        ctrl.run_cycle()

    cfg = json.loads(cfg_path.read_text())
    assert "to_promote" in cfg.get("edge_params", {}), (
        "promoted edge should have params written to edge_params"
    )
    assert cfg["edge_params"]["to_promote"]["window"] == 14


def test_specialist_type_recorded_in_params(tmp_project):
    """If WFO returns a specialist_type, it should be added to the edge's
    params as a regime_filter."""
    _seed_registry(tmp_project, [
        {"edge_id": "specialist", "status": "candidate",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {}},
    ])
    _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))
    with patch.object(ctrl, "run_wfo_for_candidate",
                      return_value=(True, 1.5, "bull_low_vol")):
        ctrl.run_cycle()

    final = yaml.safe_load(
        (tmp_project / "data" / "governor" / "edges.yml").read_text()
    )
    edge = next(e for e in final["edges"] if e["edge_id"] == "specialist")
    assert edge["params"].get("regime_filter") == "bull_low_vol"


# ---------------------------------------------------------------------------
# Rejection path
# ---------------------------------------------------------------------------

def test_run_cycle_marks_losers_as_failed(tmp_project):
    """A candidate that fails WFO should be marked status=failed."""
    _seed_registry(tmp_project, [
        {"edge_id": "loser_v1", "status": "candidate",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {}},
    ])
    _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))
    with patch.object(ctrl, "run_wfo_for_candidate",
                      return_value=(False, 0.0, None)):
        ctrl.run_cycle()

    final = yaml.safe_load(
        (tmp_project / "data" / "governor" / "edges.yml").read_text()
    )
    statuses = {e["edge_id"]: e["status"] for e in final["edges"]}
    assert statuses["loser_v1"] == "failed"


def test_failed_candidate_does_not_pollute_alpha_config(tmp_project):
    """Failed edges should NOT be written to alpha_settings.prod.json."""
    _seed_registry(tmp_project, [
        {"edge_id": "fail_me", "status": "candidate",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {"x": 99}},
    ])
    cfg_path = _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))
    with patch.object(ctrl, "run_wfo_for_candidate",
                      return_value=(False, -0.5, None)):
        ctrl.run_cycle()

    cfg = json.loads(cfg_path.read_text())
    assert "fail_me" not in cfg.get("edge_params", {})


# ---------------------------------------------------------------------------
# Mixed batch
# ---------------------------------------------------------------------------

def test_run_cycle_handles_mixed_batch(tmp_project):
    """Multiple candidates with mixed pass/fail should each get the
    correct status."""
    _seed_registry(tmp_project, [
        {"edge_id": "winner", "status": "candidate",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {}},
        {"edge_id": "loser", "status": "candidate",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {}},
        {"edge_id": "stay_active", "status": "active",
         "category": "technical", "module": "m", "class": "TestEdge",
         "version": "1.0.0", "params": {}},
    ])
    _seed_alpha_config(tmp_project)
    ctrl = EvolutionController(project_root=str(tmp_project))

    def fake_wfo(eid, params):
        return (eid == "winner", 1.0 if eid == "winner" else -0.5, None)

    with patch.object(ctrl, "run_wfo_for_candidate", side_effect=fake_wfo):
        ctrl.run_cycle()

    final = yaml.safe_load(
        (tmp_project / "data" / "governor" / "edges.yml").read_text()
    )
    statuses = {e["edge_id"]: e["status"] for e in final["edges"]}
    assert statuses["winner"] == "active"
    assert statuses["loser"] == "failed"
    # Pre-existing active edge untouched
    assert statuses["stay_active"] == "active"


# ---------------------------------------------------------------------------
# Persistence: round-trip through yaml
# ---------------------------------------------------------------------------

def test_load_save_roundtrip(tmp_project):
    """save_edges then load_edges should round-trip cleanly."""
    edges_in = [
        {"edge_id": "a", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}},
        {"edge_id": "b", "status": "paused", "category": "factor",
         "module": "n", "version": "2.0.0", "params": {"k": 1}},
    ]
    _seed_registry(tmp_project, edges_in)
    ctrl = EvolutionController(project_root=str(tmp_project))
    edges_out = ctrl.load_edges()
    assert len(edges_out) == len(edges_in)
    by_id = {e["edge_id"]: e for e in edges_out}
    assert by_id["a"]["status"] == "active"
    assert by_id["b"]["status"] == "paused"
    assert by_id["b"]["params"] == {"k": 1}


# ---------------------------------------------------------------------------
# WFO error handling — registry lookup misses
# ---------------------------------------------------------------------------

def test_run_wfo_for_candidate_handles_missing_registry_entry(tmp_project, monkeypatch):
    """If asked to run WFO for an edge_id not in the registry, return
    a clean failure rather than crashing."""
    _seed_registry(tmp_project, [])  # empty
    ctrl = EvolutionController(project_root=str(tmp_project))
    # Bypass _ensure_data_and_wfo — pretend data is already loaded
    ctrl.data_map = {"AAPL": object()}  # placeholder
    ctrl._wfo = object()  # placeholder so _ensure short-circuits

    passed, sharpe, specialist = ctrl.run_wfo_for_candidate("not_in_registry", {})
    assert passed is False
    assert sharpe == 0.0
    assert specialist is None
