"""tests/test_discovery_gates_7_8.py
======================================

Lock-in tests for the gauntlet's two new gates added 2026-05-09 evening:

- **Gate 7 — substrate-transfer.** Re-runs the candidate's production-
  equivalent ensemble on a substrate-B data_map (typically the
  historical-S&P 500 union via UniverseLoader). Fails if substrate-B
  contribution is negative OR the substrate drift exceeds threshold.
  Closes the F6 audit-machinery gap that allowed the 1.296 Foundation
  Gate to be substrate-conditional.

- **Gate 8 — DSR multiple-testing correction.** When the Discovery cycle
  generates n_trials_for_dsr > 1 candidates, applies the Deflated Sharpe
  Ratio (Bailey & Lopez de Prado 2014) to the candidate's attribution
  stream. Fails if DSR < threshold. Closes the dev-flagged gap where
  raw-Sharpe gates undercount false positives across many candidates.

Both gates default-skip when not opted in, preserving the legacy
6-gate gauntlet behaviour for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_synthetic_dfs(seed: int = 0):
    """Build a (data_map, idx) pair the gates can run a fake backtest on."""
    idx = pd.date_range("2024-01-02", periods=200, freq="B")
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "Open": np.linspace(100.0, 110.0, 200),
            "High": np.linspace(101.0, 111.0, 200),
            "Low": np.linspace(99.0, 109.0, 200),
            "Close": np.linspace(100.0, 110.0, 200) + rng.normal(0, 0.1, 200),
            "Volume": 1_000_000,
            "ATR": 1.0,
            "PrevClose": np.linspace(99.5, 109.5, 200),
        },
        index=idx,
    )
    return {"AAA": df}, idx


def _wire_validate_candidate_happy_path(monkeypatch, results_a, results_b):
    """Stub out everything upstream of Gate 7/8 so we can assert on those.

    ``results_a`` is what ``run_backtest_pure`` returns for the static
    substrate (data_map). ``results_b`` is what it returns for the
    substrate-B data_map. Both are dicts with keys: with_sharpe,
    baseline_sharpe, daily_returns_with, daily_returns_baseline.
    """
    from engines.engine_d_discovery.discovery import DiscoveryEngine

    def _fake_result(sharpe: float, daily_returns: pd.Series):
        return SimpleNamespace(
            metrics={"Sharpe Ratio": sharpe, "Sortino": 1.0},
            trade_log=pd.DataFrame(),
            equity_curve=(1.0 + daily_returns).cumprod() * 100_000.0,
            daily_returns=daily_returns,
            attributed_pnl_per_edge={},
            fingerprint="fake",
        )

    call_log = {"calls": []}

    def fake_run_backtest_pure(**kwargs):
        edges = kwargs.get("edges", {})
        data_map_used = kwargs.get("data_map", {})
        # Gate 7 path is identified by the SUBSTRATEB sentinel ticker the
        # test passes via data_map_substrate_b. Gate 5's universe-B subset
        # is keyed by "BBB" but uses results_a's positive-contribution
        # values so Gate 5 passes (the test is about Gate 7 / 8 only).
        is_substrate_b = "SUBSTRATEB" in data_map_used
        is_with = "candidate_v0" in edges
        call_log["calls"].append((is_substrate_b, is_with))
        if is_substrate_b:
            sharpe = results_b["with_sharpe"] if is_with else results_b["baseline_sharpe"]
            rets = results_b["daily_returns_with"] if is_with else results_b["daily_returns_baseline"]
        else:
            sharpe = results_a["with_sharpe"] if is_with else results_a["baseline_sharpe"]
            rets = results_a["daily_returns_with"] if is_with else results_a["daily_returns_baseline"]
        return _fake_result(sharpe, rets)

    monkeypatch.setattr(
        "orchestration.run_backtest_pure.run_backtest_pure",
        fake_run_backtest_pure,
    )

    monkeypatch.setattr(
        DiscoveryEngine, "_build_production_edges",
        lambda self, **kw: ({}, {}),
    )
    monkeypatch.setattr(
        DiscoveryEngine, "_instantiate_candidate",
        staticmethod(lambda spec: MagicMock()),
    )
    # Gate 5 path needs universe-B; provide a synthetic one.
    df_b = pd.DataFrame(
        {
            "Open": np.linspace(100, 110, 200),
            "High": np.linspace(101, 111, 200),
            "Low": np.linspace(99, 109, 200),
            "Close": np.linspace(100, 110, 200),
            "Volume": 1_000_000,
            "ATR": 1.0,
            "PrevClose": np.linspace(99.5, 109.5, 200),
        },
        index=pd.date_range("2024-01-02", periods=200, freq="B"),
    )
    monkeypatch.setattr(
        DiscoveryEngine, "_load_universe_b",
        lambda self, **kw: {"BBB": df_b},
    )

    monkeypatch.setattr(
        "engines.engine_d_discovery.robustness.RobustnessTester.calculate_pbo_returns_stream",
        lambda self, *a, **kw: {
            "survival_rate": 1.0, "actual_sharpe": 1.0, "avg_synthetic_sharpe": 0.5,
        },
    )
    monkeypatch.setattr(
        "engines.engine_d_discovery.significance.monte_carlo_permutation_test",
        lambda values, n_permutations=500: {"p_value": 0.001},
    )
    # Gate 6 (factor decomp) — happy path.
    from core.factor_decomposition import FactorDecomp
    fake_decomp = FactorDecomp(
        edge="candidate_v0", n_obs=199, raw_sharpe=1.0,
        alpha_daily=0.0005, alpha_annualized=0.13, alpha_tstat=2.5,
        r_squared=0.5, betas={},
    )
    monkeypatch.setattr(
        "core.factor_decomposition.regress_returns_on_factors",
        lambda **kw: fake_decomp,
    )
    monkeypatch.setattr(
        "core.factor_decomposition.load_factor_data",
        lambda auto_download=False: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "core.factor_decomposition.gate_factor_alpha",
        lambda decomp: (True, "passed"),
    )

    return call_log


def _make_disc():
    from engines.engine_d_discovery.discovery import DiscoveryEngine
    disc = DiscoveryEngine.__new__(DiscoveryEngine)
    disc.registry_path = "/tmp/edges_fake.yml"
    disc.processed_data_dir = "/tmp/processed_fake"
    return disc


def _make_cand_spec():
    return {
        "edge_id": "candidate_v0",
        "module": "engines.engine_a_alpha.edges.fake",
        "class": "FakeEdge",
        "category": "test",
        "params": {}, "status": "candidate", "version": 1, "origin": "test",
    }


# ============================================================
# Gate 7 — substrate-transfer
# ============================================================


def test_gate_7_skipped_when_substrate_b_data_map_is_none(monkeypatch):
    """Default behaviour: data_map_substrate_b=None → gate skipped, candidate
    not blocked by substrate transfer (gate_7_passed=True, gate_7_evaluated=False)."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.5, "baseline_sharpe": 1.0,
                   "daily_returns_with": rets + 0.0005, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 0.0, "baseline_sharpe": 0.0,
                   "daily_returns_with": rets, "daily_returns_baseline": rets},
    )
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
        # data_map_substrate_b NOT provided → Gate 7 skipped
    )
    assert result["gate_7_evaluated"] is False
    assert result["gate_7_passed"] is True
    assert result["passed_all_gates"] is True


def test_gate_7_fails_when_substrate_b_contribution_is_negative(monkeypatch):
    """Substrate-conditional alpha: candidate works on static, drags on historical."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.5, "baseline_sharpe": 1.0,
                   "daily_returns_with": rets + 0.0005, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 0.5, "baseline_sharpe": 1.0,  # contribution = -0.5
                   "daily_returns_with": rets - 0.0005, "daily_returns_baseline": rets},
    )
    data_map_b = {"SUBSTRATEB": data_map["AAA"]}
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        data_map_substrate_b=data_map_b,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
    )
    assert result["gate_7_evaluated"] is True
    assert result["gate_7_passed"] is False
    assert "< 0" in result["gate_7_reason"]
    assert result["passed_all_gates"] is False


def test_gate_7_fails_when_substrate_drift_exceeds_threshold(monkeypatch):
    """Even if both substrates show positive contribution, large drift between
    them = substrate-conditional alpha. Catches the F6 substrate-bias pattern."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 2.0, "baseline_sharpe": 1.0,  # contribution = +1.0
                   "daily_returns_with": rets + 0.001, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 1.1, "baseline_sharpe": 1.0,  # contribution = +0.1; drift = 0.9
                   "daily_returns_with": rets + 0.0001, "daily_returns_baseline": rets},
    )
    data_map_b = {"SUBSTRATEB": data_map["AAA"]}
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        data_map_substrate_b=data_map_b,
        gate7_max_substrate_drift=0.5,  # 0.9 > 0.5 → fail
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
    )
    assert result["gate_7_evaluated"] is True
    assert result["gate_7_passed"] is False
    assert "drift" in result["gate_7_reason"]
    assert result["passed_all_gates"] is False


def test_gate_7_passes_when_substrate_b_holds_within_drift(monkeypatch):
    """Substrate-honest alpha: contribution survives substrate transfer."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.5, "baseline_sharpe": 1.0,  # contribution = +0.5
                   "daily_returns_with": rets + 0.0005, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 1.4, "baseline_sharpe": 1.0,  # contribution = +0.4; drift = 0.1
                   "daily_returns_with": rets + 0.0004, "daily_returns_baseline": rets},
    )
    data_map_b = {"SUBSTRATEB": data_map["AAA"]}
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        data_map_substrate_b=data_map_b,
        gate7_max_substrate_drift=0.5,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
    )
    assert result["gate_7_evaluated"] is True
    assert result["gate_7_passed"] is True
    assert "passed" in result["gate_7_reason"]


# ============================================================
# Gate 8 — DSR multiple-testing correction
# ============================================================


def test_gate_8_skipped_when_n_trials_is_one(monkeypatch):
    """Default n_trials_for_dsr=1 → no selection-bias correction needed.
    Gate skipped (gate_8_evaluated=False, gate_8_passed=True)."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.5, "baseline_sharpe": 1.0,
                   "daily_returns_with": rets + 0.0005, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 0.0, "baseline_sharpe": 0.0,
                   "daily_returns_with": rets, "daily_returns_baseline": rets},
    )
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
        # n_trials_for_dsr defaults to 1
    )
    assert result["gate_8_evaluated"] is False
    assert result["gate_8_passed"] is True


def test_gate_8_fails_under_multiple_testing_when_dsr_below_threshold(monkeypatch):
    """With n_trials=100, the expected-max-of-trials Sharpe is high.
    A modestly-positive attribution stream that would pass at n_trials=1
    must fail when corrected for multiple testing."""
    data_map, idx = _make_synthetic_dfs()
    # Build a noisy attribution stream — positive mean but small relative to vol
    rng = np.random.default_rng(7)
    rets_baseline = pd.Series(rng.normal(0.0005, 0.012, 199), index=idx[1:])
    rets_with = rets_baseline + rng.normal(0.0002, 0.005, 199)  # modest +alpha + noise
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.0, "baseline_sharpe": 0.7,
                   "daily_returns_with": rets_with, "daily_returns_baseline": rets_baseline},
        results_b={"with_sharpe": 0.0, "baseline_sharpe": 0.0,
                   "daily_returns_with": rets_baseline, "daily_returns_baseline": rets_baseline},
    )
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
        n_trials_for_dsr=100,  # the cycle tested 100 things
        gate8_dsr_threshold=0.95,
    )
    assert result["gate_8_evaluated"] is True
    assert result["gate_8_passed"] is False
    assert "DSR" in result["gate_8_reason"]
    assert result["dsr_value"] < 0.95


def test_gate_8_n_trials_recorded_in_result(monkeypatch):
    """Result dict must surface n_trials_for_dsr for forensics."""
    data_map, idx = _make_synthetic_dfs()
    rets = pd.Series(0.001, index=idx[1:])
    _wire_validate_candidate_happy_path(
        monkeypatch,
        results_a={"with_sharpe": 1.5, "baseline_sharpe": 1.0,
                   "daily_returns_with": rets + 0.001, "daily_returns_baseline": rets},
        results_b={"with_sharpe": 0.0, "baseline_sharpe": 0.0,
                   "daily_returns_with": rets, "daily_returns_baseline": rets},
    )
    disc = _make_disc()
    result = disc.validate_candidate(
        _make_cand_spec(), data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
        n_trials_for_dsr=50,
    )
    assert result["gate_8_evaluated"] is True
    assert result.get("n_trials_for_dsr") == 50
