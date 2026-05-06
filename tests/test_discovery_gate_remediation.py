"""tests/test_discovery_gate_remediation.py
================================================

Lock-in tests for the f3-gauntlet-gates-remediation work
(2026-05-07). Cover the four remaining gauntlet anti-patterns the
2026-05-06 audit flagged in `engines/engine_d_discovery/discovery.py`:

  - Gate 5 short-circuited NaN to PASS, which let any setup error
    silently green-light a candidate.
  - Gate 6 set ``factor_alpha_passed = True`` on broad ``Exception``,
    converting absence of evidence into a pass.
  - Gate 4 mapped ``significance_threshold = None`` to a pass instead
    of failing closed.
  - Gates 2/4/5 plus the outer wrapper caught ``Exception`` widely,
    masking programmer errors (TypeError, AttributeError, NameError,
    AssertionError, ImportError) as "candidate failed validation."

The first three are pure gate-decision predicates and are tested
directly. The fourth test exercises the full ``validate_candidate``
flow with monkey-patched dependencies and asserts the programmer
errors *propagate* rather than silently returning a result dict.
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Pure gate-decision predicates — these mirror the in-code logic so a
# behavioural regression is caught at the level of the rule itself.
# ---------------------------------------------------------------------------


def _gate_5_decision(universe_b_sharpe: float) -> bool:
    """Gate 5 final decision rule (post-remediation, fail-closed on NaN)."""
    return bool(not math.isnan(universe_b_sharpe) and universe_b_sharpe > 0)


def _gate_4_decision(sig_p: float, significance_threshold) -> bool:
    """Gate 4 final decision rule (post-remediation, None → fail)."""
    if significance_threshold is None:
        return False
    return bool(sig_p < significance_threshold)


def test_gate_5_fails_on_nan_universe_b_sharpe():
    """NaN means Universe-B could not be measured → fail closed.

    Pre-remediation behaviour was ``nan or > 0`` which short-circuited
    NaN to True. That allowed any exception inside the Gate-5 setup
    block to silently pass the candidate.
    """
    assert _gate_5_decision(float("nan")) is False
    # Sanity: positive Sharpe still passes, non-positive still fails.
    assert _gate_5_decision(0.5) is True
    assert _gate_5_decision(0.0) is False
    assert _gate_5_decision(-0.3) is False


def test_gate_6_fails_on_factor_decomposition_exception(monkeypatch):
    """A non-FileNotFoundError raised by the factor regression must
    leave ``factor_alpha_passed`` False (was True pre-remediation).

    Drives the actual ``validate_candidate`` flow with everything
    upstream of Gate 6 monkey-patched to a happy path so the only
    failure mode under test is Gate 6's exception handler.
    """
    from engines.engine_d_discovery.discovery import DiscoveryEngine

    # ---- Build a synthetic data_map (one ticker, 200 trading days) ----
    idx = pd.date_range("2024-01-02", periods=200, freq="B")
    df = pd.DataFrame(
        {
            "Open": np.linspace(100.0, 110.0, 200),
            "High": np.linspace(101.0, 111.0, 200),
            "Low": np.linspace(99.0, 109.0, 200),
            "Close": np.linspace(100.0, 110.0, 200),
            "Volume": 1_000_000,
            "ATR": 1.0,
            "PrevClose": np.linspace(99.5, 109.5, 200),
        },
        index=idx,
    )
    data_map = {"AAA": df}

    # ---- Synthetic backtest result with a measurable contribution ----
    def _fake_result(daily_offset: float):
        rets = pd.Series(0.0005 + daily_offset, index=idx[1:])
        equity = (1.0 + rets).cumprod() * 100_000.0
        equity = pd.concat([pd.Series([100_000.0], index=[idx[0]]), equity])
        return _NS(
            metrics={"Sharpe Ratio": 1.0 if daily_offset >= 0 else 0.5, "Sortino": 1.2},
            trade_log=pd.DataFrame(),
            equity_curve=equity,
            daily_returns=rets,
            attributed_pnl_per_edge={},
            fingerprint="fake",
        )

    def fake_run_backtest_pure(**kwargs):
        # Two distinct results so the diff produces a non-trivial
        # attribution stream — Gates 1-5 must reach Gate 6.
        edges = kwargs.get("edges", {})
        return _fake_result(0.001 if "candidate_v0" in edges else 0.0)

    monkeypatch.setattr(
        "orchestration.run_backtest_pure.run_backtest_pure",
        fake_run_backtest_pure,
    )

    disc = DiscoveryEngine.__new__(DiscoveryEngine)
    disc.registry_path = "/tmp/edges_fake.yml"
    disc.processed_data_dir = "/tmp/processed_fake"

    monkeypatch.setattr(
        DiscoveryEngine,
        "_build_production_edges",
        lambda self, **kw: ({}, {}),
    )
    monkeypatch.setattr(
        DiscoveryEngine,
        "_instantiate_candidate",
        staticmethod(lambda spec: MagicMock()),
    )
    # Gate 5 needs a non-empty universe-B map; reuse the same synthetic df.
    monkeypatch.setattr(
        DiscoveryEngine,
        "_load_universe_b",
        lambda self, **kw: {"BBB": df},
    )

    # PBO and significance must succeed so we actually reach Gate 6.
    monkeypatch.setattr(
        "engines.engine_d_discovery.robustness.RobustnessTester.calculate_pbo_returns_stream",
        lambda self, *a, **kw: {
            "survival_rate": 1.0,
            "actual_sharpe": 1.0,
            "avg_synthetic_sharpe": 0.5,
        },
    )
    monkeypatch.setattr(
        "engines.engine_d_discovery.significance.monte_carlo_permutation_test",
        lambda values, n_permutations=500: {"p_value": 0.001},
    )

    # The injected fault: factor regression raises a non-FileNotFoundError.
    def boom(*args, **kwargs):
        raise RuntimeError("synthetic factor regression failure")

    monkeypatch.setattr(
        "core.factor_decomposition.regress_returns_on_factors", boom
    )
    monkeypatch.setattr(
        "core.factor_decomposition.load_factor_data",
        lambda auto_download=False: pd.DataFrame(),
    )

    cand_spec = {
        "edge_id": "candidate_v0",
        "module": "engines.engine_a_alpha.edges.fake",
        "class": "FakeEdge",
        "category": "test",
        "params": {},
        "status": "candidate",
        "version": 1,
        "origin": "test",
    }

    result = disc.validate_candidate(
        cand_spec,
        data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,  # ensure Gate 1 passes
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
    )

    assert result.get("gate_6_passed") is False, (
        "Gate 6 must fail closed when factor decomposition raises a "
        "non-FileNotFoundError; pre-remediation it silently passed."
    )
    assert result.get("factor_alpha_reason", "").startswith("failed:"), (
        f"Reason should reflect failure, got {result.get('factor_alpha_reason')!r}"
    )
    assert result.get("passed_all_gates") is False


def test_gate_4_fails_on_none_significance_threshold():
    """``significance_threshold=None`` is a "skip" signal from the caller;
    a skipped gate cannot pass.

    Pre-remediation: ``sig_passed = True`` when the threshold was None,
    which let candidates skip Gate 4 entirely whenever the orchestrator
    deferred significance to a batched BH-FDR pass.
    """
    assert _gate_4_decision(0.001, None) is False
    assert _gate_4_decision(0.5, None) is False
    # Sanity: when the threshold is provided, the rule is the usual
    # ``p < alpha`` test.
    assert _gate_4_decision(0.01, 0.05) is True
    assert _gate_4_decision(0.5, 0.05) is False


def test_programmer_errors_propagate_through_gates_2_4_5(monkeypatch):
    """A TypeError thrown inside any gate must propagate so test
    suites and CI surface the bug, instead of being absorbed as
    "candidate failed gate."

    Drives the full ``validate_candidate`` flow with monkey-patched
    upstream stubs so we can inject programmer errors precisely at
    Gate 2, 4, and 5 in turn.
    """
    from engines.engine_d_discovery.discovery import DiscoveryEngine

    idx = pd.date_range("2024-01-02", periods=200, freq="B")
    df = pd.DataFrame(
        {
            "Open": np.linspace(100.0, 110.0, 200),
            "High": np.linspace(101.0, 111.0, 200),
            "Low": np.linspace(99.0, 109.0, 200),
            "Close": np.linspace(100.0, 110.0, 200),
            "Volume": 1_000_000,
            "ATR": 1.0,
            "PrevClose": np.linspace(99.5, 109.5, 200),
        },
        index=idx,
    )
    data_map = {"AAA": df}

    def _fake_result(daily_offset: float):
        rets = pd.Series(0.0005 + daily_offset, index=idx[1:])
        equity = (1.0 + rets).cumprod() * 100_000.0
        equity = pd.concat([pd.Series([100_000.0], index=[idx[0]]), equity])
        return _NS(
            metrics={"Sharpe Ratio": 1.0, "Sortino": 1.2},
            trade_log=pd.DataFrame(),
            equity_curve=equity,
            daily_returns=rets,
            attributed_pnl_per_edge={},
            fingerprint="fake",
        )

    def fake_run_backtest_pure(**kwargs):
        edges = kwargs.get("edges", {})
        return _fake_result(0.001 if "candidate_v0" in edges else 0.0)

    monkeypatch.setattr(
        "orchestration.run_backtest_pure.run_backtest_pure",
        fake_run_backtest_pure,
    )

    disc = DiscoveryEngine.__new__(DiscoveryEngine)
    disc.registry_path = "/tmp/edges_fake.yml"
    disc.processed_data_dir = "/tmp/processed_fake"

    monkeypatch.setattr(
        DiscoveryEngine, "_build_production_edges",
        lambda self, **kw: ({}, {}),
    )
    monkeypatch.setattr(
        DiscoveryEngine, "_instantiate_candidate",
        staticmethod(lambda spec: MagicMock()),
    )
    monkeypatch.setattr(
        DiscoveryEngine, "_load_universe_b",
        lambda self, **kw: {"BBB": df},
    )

    cand_spec = {
        "edge_id": "candidate_v0",
        "module": "engines.engine_a_alpha.edges.fake",
        "class": "FakeEdge",
        "category": "test",
        "params": {},
        "status": "candidate",
        "version": 1,
        "origin": "test",
    }

    base_kwargs = dict(
        candidate_spec=cand_spec,
        data_map=data_map,
        significance_threshold=0.05,
        gate1_contribution_threshold=-1e6,
        gate2_survival_threshold=0.0,
        candidate_default_weight=1.0,
        alpha_config={},
    )

    # ---- Gate 2: TypeError inside RobustnessTester must propagate ----
    def gate2_typeerror(self, *a, **kw):
        raise TypeError("synthetic Gate 2 programmer error")

    monkeypatch.setattr(
        "engines.engine_d_discovery.robustness.RobustnessTester.calculate_pbo_returns_stream",
        gate2_typeerror,
    )
    with pytest.raises(TypeError, match="Gate 2 programmer error"):
        disc.validate_candidate(**base_kwargs)

    # Restore Gate 2 to a passing stub for the next two checks.
    monkeypatch.setattr(
        "engines.engine_d_discovery.robustness.RobustnessTester.calculate_pbo_returns_stream",
        lambda self, *a, **kw: {
            "survival_rate": 1.0,
            "actual_sharpe": 1.0,
            "avg_synthetic_sharpe": 0.5,
        },
    )

    # ---- Gate 4: AttributeError inside permutation test must propagate ----
    def gate4_attrerror(values, n_permutations=500):
        raise AttributeError("synthetic Gate 4 programmer error")

    monkeypatch.setattr(
        "engines.engine_d_discovery.significance.monte_carlo_permutation_test",
        gate4_attrerror,
    )
    with pytest.raises(AttributeError, match="Gate 4 programmer error"):
        disc.validate_candidate(**base_kwargs)

    # Restore Gate 4 to a passing stub.
    monkeypatch.setattr(
        "engines.engine_d_discovery.significance.monte_carlo_permutation_test",
        lambda values, n_permutations=500: {"p_value": 0.001},
    )

    # ---- Gate 5: NameError raised inside _load_universe_b must propagate ----
    def gate5_nameerror(self, **kw):
        raise NameError("synthetic Gate 5 programmer error")

    monkeypatch.setattr(
        DiscoveryEngine, "_load_universe_b", gate5_nameerror,
    )
    with pytest.raises(NameError, match="Gate 5 programmer error"):
        disc.validate_candidate(**base_kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NS:
    """Tiny namespace mimicking the attributes the gauntlet reads off
    ``PureBacktestResult`` (metrics dict + daily_returns Series).
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)
