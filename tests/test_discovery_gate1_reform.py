"""
tests/test_discovery_gate1_reform.py
====================================

Unit tests for the Phase 2.10e Gate 1 reform: ensemble-simulation
contribution gate. Standalone single-edge Gate 1 produces false
negatives for ensemble systems (per-fill trade size crosses the
Almgren-Chriss impact knee). The reform tests candidates inside a
simulated ensemble of the current active set under realistic capital
splitting; pass criterion = marginal Sharpe contribution clears
threshold.

These tests cover the isolated, mockable surface area:

- `_load_active_ensemble_specs` — registry filter + candidate exclusion
- `_instantiate_edge_from_spec` — module/class import + params apply
- `_run_gate1_ensemble` attribution math + threshold pass/fail logic
  (with the inner `_run_ensemble_backtest` mocked so we don't actually
  run BacktestController in unit tests)
- The cache key behavior on `_run_gate1_ensemble` so the baseline isn't
  recomputed across candidates that share a baseline composition

Full plumbing through validate_candidate against real data is verified
by the falsifiable-spec driver `scripts/gate1_reform_falsifiable_spec.py`,
not in this unit-test file (too expensive for CI).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_d_discovery.discovery import DiscoveryEngine


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ACTIVE_REGISTRY_YAML = """\
edges:
- edge_id: gap_fill_v1
  category: mean_reversion
  module: engines.engine_a_alpha.edges.gap_edge
  version: 1.0.0
  params:
    atr_mult: 1.0
    atr_window: 14
    require_volume_spike: false
    vol_z_threshold: 2.0
  status: active
  tier: feature
- edge_id: volume_anomaly_v1
  category: volume
  module: engines.engine_a_alpha.edges.volume_anomaly_edge
  version: 1.0.0
  params:
    mode: spike_reversal
    vol_z_threshold: 2.0
    vol_lookback: 20
  status: active
  tier: alpha
- edge_id: herding_v1
  category: contrarian
  module: engines.engine_a_alpha.edges.herding_edge
  version: 1.0.0
  params:
    breadth_threshold: 0.8
    extreme_pctile: 90.0
    min_universe_size: 10
  status: active
  tier: alpha
- edge_id: panic_v1
  category: mean_reversion
  module: engines.engine_a_alpha.edges.panic_edge
  version: 1.0.0
  params:
    rsi_threshold: 20.0
    rsi_window: 14
  status: paused
  tier: feature
- edge_id: seasonality_v1
  category: seasonality
  module: engines.engine_a_alpha.edges.seasonality_edge
  version: 1.0.0
  params: {}
  status: retired
  tier: feature
"""


def _make_engine(tmp_path) -> DiscoveryEngine:
    reg = tmp_path / "edges.yml"
    reg.write_text(ACTIVE_REGISTRY_YAML)
    return DiscoveryEngine(
        registry_path=str(reg),
        processed_data_dir=str(tmp_path / "processed"),
    )


def _empty_engine(tmp_path) -> DiscoveryEngine:
    reg = tmp_path / "edges.yml"
    reg.write_text("edges: []\n")
    return DiscoveryEngine(
        registry_path=str(reg),
        processed_data_dir=str(tmp_path / "processed"),
    )


# ---------------------------------------------------------------------------
# _load_active_ensemble_specs
# ---------------------------------------------------------------------------

def test_load_active_ensemble_returns_only_active(tmp_path):
    """Baseline composition = exactly status='active' edges, nothing else.
    Soft-paused edges (status='paused') and retired edges DO NOT count
    toward the baseline — only what's currently deployed at full weight."""
    engine = _make_engine(tmp_path)
    specs = engine._load_active_ensemble_specs()
    ids = {s["edge_id"] for s in specs}
    assert ids == {"gap_fill_v1", "volume_anomaly_v1", "herding_v1"}


def test_load_active_ensemble_excludes_candidate(tmp_path):
    """When the candidate is already in the active set (volume_anomaly_v1
    + herding_v1 are both currently `active` per data/governor/edges.yml),
    the baseline must exclude it so contribution measures the marginal
    effect of adding it back, not zero-effect of duplicating it."""
    engine = _make_engine(tmp_path)
    specs = engine._load_active_ensemble_specs(exclude_id="volume_anomaly_v1")
    ids = {s["edge_id"] for s in specs}
    assert ids == {"gap_fill_v1", "herding_v1"}


def test_load_active_ensemble_no_op_exclude_for_new_candidate(tmp_path):
    """For a brand-new candidate not yet in the registry, exclude_id is
    a no-op — full active set is the baseline."""
    engine = _make_engine(tmp_path)
    specs = engine._load_active_ensemble_specs(exclude_id="brand_new_candidate_v1")
    ids = {s["edge_id"] for s in specs}
    assert ids == {"gap_fill_v1", "volume_anomaly_v1", "herding_v1"}


def test_load_active_ensemble_resolves_class_name(tmp_path):
    """The registry stores `module` only; the helper must resolve the
    class name by introspection (matches scripts/revalidate_alphas.py)."""
    engine = _make_engine(tmp_path)
    specs = {s["edge_id"]: s for s in engine._load_active_ensemble_specs()}
    assert specs["volume_anomaly_v1"]["class"] == "VolumeAnomalyEdge"
    assert specs["herding_v1"]["class"] == "HerdingEdge"
    assert specs["gap_fill_v1"]["class"] == "GapEdge"


def test_load_active_ensemble_carries_params(tmp_path):
    """Baseline edges must use their registered params (the deployed
    config), not defaults — otherwise the baseline doesn't represent the
    deployed ensemble."""
    engine = _make_engine(tmp_path)
    specs = {s["edge_id"]: s for s in engine._load_active_ensemble_specs()}
    assert specs["herding_v1"]["params"]["breadth_threshold"] == 0.8
    assert specs["volume_anomaly_v1"]["params"]["mode"] == "spike_reversal"


def test_load_active_ensemble_missing_registry_returns_empty(tmp_path):
    engine = DiscoveryEngine(
        registry_path=str(tmp_path / "does_not_exist.yml"),
        processed_data_dir=str(tmp_path / "processed"),
    )
    assert engine._load_active_ensemble_specs() == []


def test_load_active_ensemble_empty_registry(tmp_path):
    engine = _empty_engine(tmp_path)
    assert engine._load_active_ensemble_specs() == []


# ---------------------------------------------------------------------------
# _instantiate_edge_from_spec
# ---------------------------------------------------------------------------

def test_instantiate_edge_returns_correct_class(tmp_path):
    engine = _make_engine(tmp_path)
    spec = {
        "edge_id": "herding_v1",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {"breadth_threshold": 0.85},
    }
    edge = engine._instantiate_edge_from_spec(spec)
    assert edge.__class__.__name__ == "HerdingEdge"


def test_instantiate_edge_applies_params(tmp_path):
    engine = _make_engine(tmp_path)
    spec = {
        "edge_id": "herding_v1",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {"breadth_threshold": 0.95, "extreme_pctile": 99.0},
    }
    edge = engine._instantiate_edge_from_spec(spec)
    # EdgeBase stores params under .params after set_params
    assert edge.params.get("breadth_threshold") == 0.95
    assert edge.params.get("extreme_pctile") == 99.0


# ---------------------------------------------------------------------------
# _run_gate1_ensemble — attribution math + thresholds
# (mocks `_run_ensemble_backtest` to avoid running real backtests)
# ---------------------------------------------------------------------------

def _patch_backtest(engine, sharpes: List[float]):
    """Patch `_run_ensemble_backtest` to return successive sharpes from
    `sharpes` in call order. Equity curve is an empty Series — gate
    logic only inspects the sharpe value, not the curve."""
    calls: List[Dict[str, Any]] = []
    iterator = iter(sharpes)

    def fake(edges, data_map, start_date, end_date, exec_params,
             out_dir="/tmp/x", initial_capital=100_000):
        calls.append({"edge_ids": sorted(edges.keys()), "out_dir": out_dir})
        return float(next(iterator)), pd.Series(dtype=float)

    return patch.object(engine, "_run_ensemble_backtest", side_effect=fake), calls


def test_gate1_ensemble_pass_when_contribution_above_threshold(tmp_path):
    """contribution = with_candidate - baseline. If 0.95 - 0.80 = +0.15
    >= threshold 0.10 → pass."""
    engine = _make_engine(tmp_path)
    candidate_spec = {
        "edge_id": "new_candidate",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    cand_edge = engine._instantiate_edge_from_spec(candidate_spec)
    patcher, calls = _patch_backtest(engine, sharpes=[0.80, 0.95])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=candidate_spec, candidate_edge=cand_edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
            contribution_threshold=0.10,
        )
    assert result["passed"] is True
    assert result["baseline_sharpe"] == pytest.approx(0.80)
    assert result["with_candidate_sharpe"] == pytest.approx(0.95)
    assert result["contribution_sharpe"] == pytest.approx(0.15)


def test_gate1_ensemble_fail_when_contribution_below_threshold(tmp_path):
    """0.85 - 0.80 = +0.05 < threshold 0.10 → fail.
    This is the impact-knee dilution shape — small but positive
    contribution that the loose threshold rejects."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "weak_candidate",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, _ = _patch_backtest(engine, sharpes=[0.80, 0.85])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
            contribution_threshold=0.10,
        )
    assert result["passed"] is False
    assert result["contribution_sharpe"] == pytest.approx(0.05)


def test_gate1_ensemble_fail_when_contribution_negative(tmp_path):
    """Adding the candidate makes the ensemble WORSE (rivalry dominates,
    or the candidate is genuinely value-destroying). Hard fail."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "destructive",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, _ = _patch_backtest(engine, sharpes=[0.80, 0.55])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    assert result["passed"] is False
    assert result["contribution_sharpe"] == pytest.approx(-0.25)


def test_gate1_ensemble_uses_geq_not_strict_gt(tmp_path):
    """The pass comparison is `>=`, not `>`. Values picked to subtract
    exactly in IEEE-754 (0.5, 1.0, 0.5) so we exercise the boundary
    without float-precision noise."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "boundary",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, _ = _patch_backtest(engine, sharpes=[0.5, 1.0])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
            contribution_threshold=0.5,
        )
    assert result["contribution_sharpe"] == pytest.approx(0.5)
    assert result["passed"] is True


def test_gate1_ensemble_excludes_candidate_from_baseline(tmp_path):
    """When the candidate's edge_id matches an active edge, the baseline
    run must use exactly the OTHER active edges. The with-candidate run
    must include all active edges (candidate replaces the registry copy
    with the under-test instance)."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "volume_anomaly_v1",  # already active!
        "module": "engines.engine_a_alpha.edges.volume_anomaly_edge",
        "class": "VolumeAnomalyEdge",
        "params": {"mode": "spike_reversal"},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, calls = _patch_backtest(engine, sharpes=[0.40, 0.60])
    with patcher:
        engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    # First call = baseline (without the candidate)
    # Second call = with-candidate
    baseline_ids = set(calls[0]["edge_ids"])
    with_cand_ids = set(calls[1]["edge_ids"])
    assert "volume_anomaly_v1" not in baseline_ids
    assert baseline_ids == {"gap_fill_v1", "herding_v1"}
    assert with_cand_ids == {"gap_fill_v1", "herding_v1", "volume_anomaly_v1"}


def test_gate1_ensemble_includes_new_candidate_alongside_full_active_set(tmp_path):
    """For a candidate that's NOT yet in the registry, baseline = full
    active set (3 edges) and with-candidate = 4 edges."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "brand_new_v1",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, calls = _patch_backtest(engine, sharpes=[0.5, 0.7])
    with patcher:
        engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    baseline_ids = set(calls[0]["edge_ids"])
    with_cand_ids = set(calls[1]["edge_ids"])
    assert baseline_ids == {"gap_fill_v1", "volume_anomaly_v1", "herding_v1"}
    assert with_cand_ids == {
        "gap_fill_v1", "volume_anomaly_v1", "herding_v1", "brand_new_v1",
    }


def test_gate1_ensemble_baseline_cached_across_calls(tmp_path):
    """Two candidates with identical baselines (e.g. both new candidates
    against the same active set) should run the baseline backtest exactly
    once, not twice. Otherwise Discovery cycles get O(N) baseline runs
    they don't need."""
    engine = _make_engine(tmp_path)
    spec_a = {
        "edge_id": "cand_a",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    spec_b = {
        "edge_id": "cand_b",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge_a = engine._instantiate_edge_from_spec(spec_a)
    edge_b = engine._instantiate_edge_from_spec(spec_b)
    # 3 sharpes — one baseline, two with-candidate runs (cache hit on
    # the second baseline)
    patcher, calls = _patch_backtest(engine, sharpes=[0.5, 0.65, 0.70])
    with patcher:
        r_a = engine._run_gate1_ensemble(
            candidate_spec=spec_a, candidate_edge=edge_a,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
        r_b = engine._run_gate1_ensemble(
            candidate_spec=spec_b, candidate_edge=edge_b,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    # 3 calls total, not 4 — baseline ran once across both candidates
    assert len(calls) == 3
    assert r_a["baseline_sharpe"] == pytest.approx(0.5)
    assert r_b["baseline_sharpe"] == pytest.approx(0.5)
    assert r_a["with_candidate_sharpe"] == pytest.approx(0.65)
    assert r_b["with_candidate_sharpe"] == pytest.approx(0.70)


def test_gate1_ensemble_baseline_ids_recorded(tmp_path):
    """The audit trail should record exactly which edges the candidate
    was tested against, so the verdict is reproducible later when the
    active set has drifted."""
    engine = _make_engine(tmp_path)
    cand_spec = {
        "edge_id": "herding_v1",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    patcher, _ = _patch_backtest(engine, sharpes=[0.4, 0.6])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    assert result["baseline_ids"] == ["gap_fill_v1", "volume_anomaly_v1"]


def test_gate1_ensemble_empty_registry_baseline_is_zero(tmp_path):
    """If there are NO active edges (degenerate empty-deployment case),
    baseline = 0.0 and contribution = with_candidate - 0 = standalone.
    This is the only case where the new gate degenerates to the old
    standalone test — and that's the *correct* behavior because there's
    no ensemble to be diluted by."""
    engine = _empty_engine(tmp_path)
    cand_spec = {
        "edge_id": "lonely",
        "module": "engines.engine_a_alpha.edges.herding_edge",
        "class": "HerdingEdge",
        "params": {},
    }
    edge = engine._instantiate_edge_from_spec(cand_spec)
    # Only one backtest will run (with-candidate); baseline is degenerate
    # because there are no edges to run.
    patcher, calls = _patch_backtest(engine, sharpes=[0.0, 0.7])
    with patcher:
        result = engine._run_gate1_ensemble(
            candidate_spec=cand_spec, candidate_edge=edge,
            data_map={"AAPL": pd.DataFrame()},
            start_date="2021-01-01", end_date="2024-12-31",
            exec_params={"slippage_bps": 5.0},
        )
    # Empty-baseline branch in _run_ensemble_backtest returns 0.0
    # without invoking the patched fake. So calls = [with_candidate]
    # only. We assert the contribution math, not call count.
    assert result["baseline_sharpe"] == pytest.approx(0.0)
    assert result["with_candidate_sharpe"] >= 0.0
    assert result["contribution_sharpe"] == pytest.approx(
        result["with_candidate_sharpe"]
    )


# ---------------------------------------------------------------------------
# Default threshold value — pinned so the recommendation in the audit doc
# stays in sync with the code
# ---------------------------------------------------------------------------

def test_gate1_default_threshold_is_pinned():
    """The audit doc cites 0.10 as the conservative starting point. If
    this constant changes, the doc must be re-checked. Pin it."""
    assert DiscoveryEngine.GATE1_DEFAULT_CONTRIBUTION_THRESHOLD == pytest.approx(0.10)
