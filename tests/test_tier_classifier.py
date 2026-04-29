"""
tests/test_tier_classifier.py
==============================
Tests for ``engines/engine_a_alpha/tier_classifier.py`` — the Layer 2
autonomous tier-classification module.

Coverage:
  - Rule correctness across all branches (alpha / feature / context /
    retire-eligible)
  - Threshold boundaries (just above / just below the tstat cutoffs)
  - Profile-INDEPENDENCE: the classifier never reads FitnessConfig
  - Idempotency: running twice with same inputs gives same output
  - Persistence: write=True updates registry; write=False is dry-run
  - tier_last_updated stamps only on actual change
  - Insufficient observations → default "feature", no spurious classification
  - EdgeRegistry round-trip preserves new tier fields
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.factor_decomposition import FactorDecomp
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec
from engines.engine_a_alpha.tier_classifier import (
    DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER,
    DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE,
    TierClassifier,
    TierDecision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decomp(
    edge: str = "test",
    alpha_ann: float = 0.05,
    t: float = 3.0,
    n_obs: int = 200,
) -> FactorDecomp:
    return FactorDecomp(
        edge=edge,
        n_obs=n_obs,
        raw_sharpe=1.0,
        alpha_daily=alpha_ann / 252,
        alpha_annualized=alpha_ann,
        alpha_tstat=t,
        r_squared=0.1,
        betas={"MktRF": 0.0, "SMB": 0.0, "HML": 0.0,
               "RMW": 0.0, "CMA": 0.0, "Mom": 0.0},
    )


@pytest.fixture
def isolated_registry(tmp_path):
    """A fresh EdgeRegistry backed by a tmp YAML so tests don't touch
    the real one at data/governor/edges.yml."""
    return EdgeRegistry(store_path=str(tmp_path / "edges.yml"))


# ---------------------------------------------------------------------------
# Rule correctness — _classify_from_decomp
# ---------------------------------------------------------------------------

def test_classifies_alpha_when_tstat_high_and_alpha_economically_meaningful(isolated_registry):
    classifier = TierClassifier(registry=isolated_registry)
    decomp = _make_decomp(t=4.5, alpha_ann=0.08)
    decision = classifier._classify_from_decomp("e1", decomp, prior_tier="feature")
    assert decision.new_tier == "alpha"
    assert decision.new_combination_role == "standalone"
    assert "alpha=" in decision.reason


def test_classifies_feature_when_tstat_marginal(isolated_registry):
    """0 < t < threshold → not standalone, but informative."""
    classifier = TierClassifier(registry=isolated_registry)
    decomp = _make_decomp(t=1.5, alpha_ann=0.05)
    decision = classifier._classify_from_decomp("e2", decomp, prior_tier="feature")
    assert decision.new_tier == "feature"
    assert decision.new_combination_role == "input"


def test_classifies_feature_when_alpha_tiny_even_if_tstat_high(isolated_registry):
    """Statistically significant but economically negligible alpha (<2%
    annualized) does NOT promote to alpha tier — gauntlet logic."""
    classifier = TierClassifier(registry=isolated_registry)
    decomp = _make_decomp(t=10.0, alpha_ann=0.005)  # tstat huge, alpha tiny
    decision = classifier._classify_from_decomp("e3", decomp, prior_tier="feature")
    assert decision.new_tier == "feature"


def test_classifies_retire_eligible_when_tstat_significantly_negative(isolated_registry):
    classifier = TierClassifier(registry=isolated_registry)
    decomp = _make_decomp(t=-3.0, alpha_ann=-0.05)
    decision = classifier._classify_from_decomp("e4", decomp, prior_tier="alpha")
    assert decision.new_tier == "retire-eligible"
    assert "destroying value" in decision.reason


def test_classifies_feature_when_tstat_mildly_negative(isolated_registry):
    """Mild negative tstat (between 0 and -2) is non-significant — default
    to feature, not retire."""
    classifier = TierClassifier(registry=isolated_registry)
    decomp = _make_decomp(t=-1.0, alpha_ann=-0.02)
    decision = classifier._classify_from_decomp("e5", decomp, prior_tier="feature")
    assert decision.new_tier == "feature"


def test_insufficient_observations_returns_default_feature(isolated_registry):
    """When factor decomposition can't run (None decomp), no spurious
    classification. Default to feature until evidence accumulates."""
    classifier = TierClassifier(registry=isolated_registry)
    decision = classifier._classify_from_decomp("e6", None, prior_tier="alpha")
    assert decision.new_tier == "feature"
    assert decision.factor_tstat is None
    assert "insufficient observations" in decision.reason


# ---------------------------------------------------------------------------
# Threshold boundaries
# ---------------------------------------------------------------------------

def test_threshold_strictly_greater_than_for_alpha_promotion(isolated_registry):
    """t == threshold should NOT promote (gate is strict >, not ≥)."""
    classifier = TierClassifier(registry=isolated_registry)
    # t exactly at threshold, alpha well above
    at_threshold = _make_decomp(
        t=DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER, alpha_ann=0.10,
    )
    decision_at = classifier._classify_from_decomp("at_thresh", at_threshold, "feature")
    assert decision_at.new_tier == "feature", (
        f"t={DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER} should NOT promote (strict >)"
    )

    # t just above threshold: promotes
    just_above = _make_decomp(
        t=DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER + 0.01, alpha_ann=0.10,
    )
    decision_above = classifier._classify_from_decomp("above_thresh", just_above, "feature")
    assert decision_above.new_tier == "alpha"


def test_threshold_strictly_less_than_for_retire_eligible(isolated_registry):
    """t == retire threshold should NOT flag — gate is strict <, not ≤."""
    classifier = TierClassifier(registry=isolated_registry)
    at = _make_decomp(t=DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE, alpha_ann=-0.05)
    decision_at = classifier._classify_from_decomp("at_thresh", at, "feature")
    # t = -2.0 not < -2.0 (strict), so not retire-eligible
    assert decision_at.new_tier == "feature"

    just_below = _make_decomp(t=DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE - 0.01, alpha_ann=-0.05)
    decision_below = classifier._classify_from_decomp("below_thresh", just_below, "feature")
    assert decision_below.new_tier == "retire-eligible"


def test_custom_thresholds_honored(isolated_registry):
    """Caller can tighten or loosen the alpha-tier thresholds."""
    strict = TierClassifier(
        registry=isolated_registry,
        alpha_tstat_threshold=3.5,  # tighter than default 2.0
        alpha_annual_threshold=0.05,
    )
    # t=3.0 would normally promote, but with stricter t-stat threshold (3.5):
    decomp = _make_decomp(t=3.0, alpha_ann=0.10)
    decision = strict._classify_from_decomp("e", decomp, "feature")
    assert decision.new_tier == "feature"  # didn't make the stricter cut


# ---------------------------------------------------------------------------
# TierDecision.changed property
# ---------------------------------------------------------------------------

def test_tier_decision_changed_property():
    same = TierDecision(
        edge_id="e", new_tier="feature", new_combination_role="input",
        factor_tstat=1.0, factor_alpha_annualized=0.01, n_obs=100,
        reason="x", prior_tier="feature",
    )
    assert same.changed is False
    different = TierDecision(
        edge_id="e", new_tier="alpha", new_combination_role="standalone",
        factor_tstat=4.0, factor_alpha_annualized=0.10, n_obs=100,
        reason="y", prior_tier="feature",
    )
    assert different.changed is True


# ---------------------------------------------------------------------------
# Profile-independence — the architectural property
# ---------------------------------------------------------------------------

def test_classifier_does_not_import_fitness_module():
    """Layer 2 (tier) MUST be profile-independent. The classifier's
    decisions are objective; only Layer 3 (allocation) reads the
    profile. Lock this in by inspecting actual imports (not substring
    matches in docstrings — those are allowed to *describe* the rule).
    """
    import ast
    import engines.engine_a_alpha.tier_classifier as mod

    src = Path(mod.__file__).read_text()
    tree = ast.parse(src)

    forbidden_modules = {"core.fitness"}
    forbidden_names = {"FitnessConfig", "compute_fitness", "load_profiles"}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_modules, (
                f"TierClassifier must not import {node.module} — tier is "
                "profile-INDEPENDENT (Layer 2 architectural rule)"
            )
            for alias in node.names:
                assert alias.name not in forbidden_names, (
                    f"TierClassifier must not import {alias.name} — "
                    "Layer 2 must stay profile-independent"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules, (
                    f"TierClassifier must not import {alias.name} — "
                    "Layer 2 must stay profile-independent"
                )


# ---------------------------------------------------------------------------
# Persistence — registry round-trip
# ---------------------------------------------------------------------------

def test_edgespec_tier_field_round_trips_through_yaml(tmp_path):
    """Write a spec with tier="alpha", reload, check it survived."""
    path = tmp_path / "edges.yml"
    reg1 = EdgeRegistry(store_path=str(path))
    reg1.register(EdgeSpec(
        edge_id="x_v1", category="technical", module="x",
        tier="alpha", combination_role="standalone",
        tier_last_updated="2026-04-28T12:00:00+00:00",
    ))
    # Reload from disk
    reg2 = EdgeRegistry(store_path=str(path))
    spec = reg2.get("x_v1")
    assert spec is not None
    assert spec.tier == "alpha"
    assert spec.combination_role == "standalone"
    assert spec.tier_last_updated == "2026-04-28T12:00:00+00:00"


def test_edgespec_default_tier_is_feature():
    """Day-1 default for new specs: tier="feature" (input to meta-learner
    until evidence accumulates)."""
    spec = EdgeSpec(edge_id="new", category="technical", module="m")
    assert spec.tier == "feature"
    assert spec.combination_role == "input"
    assert spec.tier_last_updated is None


def test_ensure_does_not_overwrite_tier_on_import(tmp_path):
    """Critical: registry.ensure() must NOT stomp tier set by the
    classifier. Same write-protection pattern as the status field
    (the 2026-04-25 status-stomp bug)."""
    path = tmp_path / "edges.yml"
    reg = EdgeRegistry(store_path=str(path))
    # Day 1: register with default tier=feature
    reg.register(EdgeSpec(
        edge_id="y_v1", category="technical", module="y",
        tier="feature", combination_role="input",
    ))
    # Classifier promotes to alpha
    reg.get("y_v1").tier = "alpha"
    reg.get("y_v1").combination_role = "standalone"
    reg._save()

    # Module's auto-register code calls ensure() with default tier=feature
    reg.ensure(EdgeSpec(
        edge_id="y_v1", category="technical", module="y",
        tier="feature",  # default in the auto-register call
    ))
    # Tier must remain "alpha" — ensure() must respect the classifier's decision
    assert reg.get("y_v1").tier == "alpha"
    assert reg.get("y_v1").combination_role == "standalone"


# ---------------------------------------------------------------------------
# End-to-end — classify_from_trades
# ---------------------------------------------------------------------------

def _write_synthetic_trades(
    path: Path,
    edge_specs: list,
    n_days: int = 200,
) -> None:
    """Write a synthetic trades.csv where each edge has a known PnL pattern.

    edge_specs: list of (edge_name, daily_pnl_mean, daily_pnl_std)
    """
    rng = np.random.default_rng(42)
    rows = []
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    for edge_name, mean_pnl, std_pnl in edge_specs:
        pnls = rng.normal(mean_pnl, std_pnl, size=n_days)
        for d, p in zip(dates, pnls):
            rows.append({
                "timestamp": d, "ticker": "AAPL", "side": "long",
                "qty": 1, "fill_price": 100.0, "commission": 0.0,
                "pnl": p, "edge": edge_name, "edge_group": "technical",
                "trigger": "exit", "edge_id": edge_name,
                "edge_category": "technical", "run_id": "test",
                "regime_label": "neutral", "meta": "{}",
            })
    pd.DataFrame(rows).to_csv(path, index=False)


def test_classify_from_trades_dry_run_does_not_mutate_registry(tmp_path):
    reg_path = tmp_path / "edges.yml"
    reg = EdgeRegistry(store_path=str(reg_path))
    reg.register(EdgeSpec(edge_id="some_edge", category="technical", module="x"))

    trades_path = tmp_path / "trades.csv"
    _write_synthetic_trades(trades_path, [("some_edge", 50.0, 200.0)])

    classifier = TierClassifier(registry=reg)
    # Dry run — should not write to disk
    try:
        _ = classifier.classify_from_trades(trades_path, write=False)
    except FileNotFoundError as e:
        # FF cache may not be present — skip rather than fail
        pytest.skip(f"Factor cache not available: {e}")

    # Tier on the original spec should still be the default "feature"
    fresh_reg = EdgeRegistry(store_path=str(reg_path))
    assert fresh_reg.get("some_edge").tier == "feature"
    assert fresh_reg.get("some_edge").tier_last_updated is None


def test_classify_from_trades_idempotent(tmp_path):
    """Running classify twice with the same trades produces the same
    tier assignments. tier_last_updated may differ but tier itself
    must not flap."""
    reg_path = tmp_path / "edges.yml"
    reg = EdgeRegistry(store_path=str(reg_path))
    reg.register(EdgeSpec(edge_id="alpha_edge", category="technical", module="x"))

    trades_path = tmp_path / "trades.csv"
    # Strong positive alpha pattern: high mean, low std → high t-stat
    _write_synthetic_trades(trades_path, [("alpha_edge", 80.0, 50.0)])

    classifier = TierClassifier(registry=reg)
    try:
        first = classifier.classify_from_trades(trades_path, write=True)
    except FileNotFoundError as e:
        pytest.skip(f"Factor cache not available: {e}")
    tier_after_first = reg.get("alpha_edge").tier

    # Second run, same inputs
    second = classifier.classify_from_trades(trades_path, write=True)
    tier_after_second = reg.get("alpha_edge").tier

    assert tier_after_first == tier_after_second
    # Decisions list also matches (same edge classifications)
    first_by_id = {d.edge_id: d.new_tier for d in first}
    second_by_id = {d.edge_id: d.new_tier for d in second}
    assert first_by_id == second_by_id
