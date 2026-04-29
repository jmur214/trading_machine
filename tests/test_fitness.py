"""
tests/test_fitness.py
=====================
Tests for ``core/fitness.py`` — the Layer 3 (allocation) profile + fitness
helper. Verifies:

  - FitnessConfig validation (unknown metric keys rejected at construction)
  - compute_fitness applies weights linearly with the right metric scaling
  - Profile loading from YAML works for the canonical profiles + custom
  - Profile-flip changes fitness output but doesn't mutate inputs
  - Real-world example: realistic-cost backtest metrics produce the
    expected ordering across profiles (retiree > balanced > growth)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.fitness import (
    DEFAULT_PROFILES_PATH,
    FitnessConfig,
    RECOGNIZED_METRICS,
    compute_fitness,
    get_active_profile,
    load_profiles,
)


# ---------------------------------------------------------------------------
# FitnessConfig validation
# ---------------------------------------------------------------------------

def test_fitness_config_accepts_recognized_metrics():
    cfg = FitnessConfig(
        name="custom",
        weights={"sharpe": 0.5, "calmar": 0.3, "cagr": 0.2},
    )
    assert cfg.name == "custom"
    assert cfg.weights["sharpe"] == 0.5


def test_fitness_config_rejects_unknown_metric_key():
    """Typos in metric names must fail loud at construction time, not
    silently zero-weight the metric the user thought they picked."""
    with pytest.raises(ValueError, match="unknown metric"):
        FitnessConfig(name="typo", weights={"sharp": 1.0})  # missing 'e'


def test_fitness_config_rejects_empty_weights():
    with pytest.raises(ValueError, match="empty weights"):
        FitnessConfig(name="empty", weights={})


def test_fitness_config_rejects_negative_weight():
    with pytest.raises(ValueError, match="negative weight"):
        FitnessConfig(name="bad", weights={"sharpe": 1.0, "calmar": -0.5})


def test_fitness_config_recognized_metrics_set():
    """Lock in the RECOGNIZED_METRICS list — adding/removing one is a
    behavior change worth flagging."""
    assert RECOGNIZED_METRICS == {"sharpe", "sortino", "calmar", "cagr", "neg_mdd"}


# ---------------------------------------------------------------------------
# compute_fitness — math
# ---------------------------------------------------------------------------

def _example_metrics() -> dict:
    """Realistic-cost backtest result, used as the canonical example
    in design discussions."""
    return {
        "Sharpe": 1.063,
        "Sortino": 1.5,
        "Calmar": 0.60,
        "CAGR %": 6.06,
        "Max Drawdown %": -10.07,
    }


def test_compute_fitness_pure_sharpe_weight():
    cfg = FitnessConfig(name="pure_sharpe", weights={"sharpe": 1.0})
    metrics = _example_metrics()
    fit = compute_fitness(metrics, cfg)
    assert fit == pytest.approx(1.063)


def test_compute_fitness_pure_calmar_weight():
    cfg = FitnessConfig(name="pure_calmar", weights={"calmar": 1.0})
    fit = compute_fitness(_example_metrics(), cfg)
    assert fit == pytest.approx(0.60)


def test_compute_fitness_pure_cagr_converts_pct_to_fraction():
    """CAGR is in MetricsEngine as a percent (6.06 = 6.06%); fitness
    should treat it as a fraction (0.0606) so it's comparable to
    Sharpe/Calmar/Sortino which are ratios in [≈0, ≈3]."""
    cfg = FitnessConfig(name="pure_cagr", weights={"cagr": 1.0})
    fit = compute_fitness(_example_metrics(), cfg)
    assert fit == pytest.approx(0.0606)


def test_compute_fitness_neg_mdd_converts_to_positive():
    """Max Drawdown is negative percent in MetricsEngine; neg_mdd flips
    sign and converts to fraction — smaller drawdown → larger neg_mdd."""
    cfg = FitnessConfig(name="pure_neg_mdd", weights={"neg_mdd": 1.0})
    fit = compute_fitness(_example_metrics(), cfg)
    # MDD = -10.07% → neg_mdd = +0.1007
    assert fit == pytest.approx(0.1007)


def test_compute_fitness_combination_is_linear():
    cfg = FitnessConfig(name="mix", weights={"sharpe": 0.5, "calmar": 0.5})
    metrics = _example_metrics()
    fit = compute_fitness(metrics, cfg)
    # 0.5 * 1.063 + 0.5 * 0.60 = 0.8315
    assert fit == pytest.approx(0.5 * 1.063 + 0.5 * 0.60)


def test_compute_fitness_missing_metric_defaults_to_zero():
    """If MetricsEngine dropped a key (degenerate run, short window),
    fitness should default that term to 0 rather than crash."""
    cfg = FitnessConfig(name="all_metrics",
                        weights={"sharpe": 0.5, "sortino": 0.5})
    metrics = {"Sharpe": 1.0}  # no Sortino key
    fit = compute_fitness(metrics, cfg)
    # 0.5 * 1.0 + 0.5 * 0 = 0.5
    assert fit == pytest.approx(0.5)


def test_compute_fitness_weights_can_exceed_one():
    """Weights are arbitrary positive floats — they don't have to sum to 1."""
    cfg = FitnessConfig(name="weighted", weights={"sharpe": 2.0, "calmar": 1.0})
    fit = compute_fitness(_example_metrics(), cfg)
    assert fit == pytest.approx(2.0 * 1.063 + 1.0 * 0.60)


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

def test_canonical_profiles_yaml_loads_three_profiles():
    """The shipped config/fitness_profiles.yml loads cleanly and contains
    the canonical three profiles."""
    profiles = load_profiles()
    assert "retiree" in profiles
    assert "balanced" in profiles
    assert "growth" in profiles


def test_canonical_profiles_have_target_vol():
    profiles = load_profiles()
    assert profiles["retiree"].target_vol == 0.05
    assert profiles["balanced"].target_vol == 0.10
    assert profiles["growth"].target_vol == 0.20


def test_get_active_profile_default_is_balanced():
    """The shipped YAML sets active_profile: balanced."""
    active = get_active_profile()
    assert active.name == "balanced"


def test_get_active_profile_explicit_override():
    """Explicit profile_name argument overrides the YAML's active_profile."""
    active = get_active_profile(profile_name="growth")
    assert active.name == "growth"


def test_load_profiles_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.yml"
    with pytest.raises(FileNotFoundError):
        load_profiles(missing)


def test_load_profiles_custom_yaml(tmp_path):
    """A user can ship their own YAML and load it independently."""
    custom = tmp_path / "custom.yml"
    custom.write_text("""
active_profile: aggressive
profiles:
  aggressive:
    weights:
      cagr: 0.8
      sharpe: 0.2
    target_vol: 0.30
""")
    profiles = load_profiles(custom)
    assert "aggressive" in profiles
    assert profiles["aggressive"].weights == {"cagr": 0.8, "sharpe": 0.2}
    assert profiles["aggressive"].target_vol == 0.30


def test_load_profiles_invalid_metric_key_propagates_error(tmp_path):
    """A YAML with a typo'd metric name should fail loud at load time."""
    bad = tmp_path / "bad.yml"
    bad.write_text("""
profiles:
  oops:
    weights:
      sharp: 1.0   # typo
""")
    with pytest.raises(ValueError, match="unknown metric"):
        load_profiles(bad)


# ---------------------------------------------------------------------------
# Profile-flip semantics — the architectural property
# ---------------------------------------------------------------------------

def test_profile_flip_changes_fitness_score():
    """Same metrics, different profile → different fitness scalar.
    This is the desired behavior — profile preference IS the
    allocation decision."""
    metrics = _example_metrics()
    profiles = load_profiles()
    retiree_fit = compute_fitness(metrics, profiles["retiree"])
    growth_fit = compute_fitness(metrics, profiles["growth"])
    assert retiree_fit != growth_fit


def test_profile_flip_does_not_mutate_metrics():
    """compute_fitness must be pure — same metrics dict before and after."""
    metrics = _example_metrics()
    profiles = load_profiles()
    metrics_before = dict(metrics)
    for p in profiles.values():
        _ = compute_fitness(metrics, p)
    assert metrics == metrics_before


def test_realistic_cost_metrics_score_highest_under_retiree():
    """The realistic-cost backtest has high Sharpe / low MDD / modest
    CAGR. By construction the retiree profile (Calmar/Sortino-weighted)
    should rank it ABOVE the growth profile (CAGR-weighted).

    This is the empirical version of the architectural design — different
    profiles legitimately rank the SAME backtest differently."""
    metrics = _example_metrics()
    profiles = load_profiles()
    retiree_fit = compute_fitness(metrics, profiles["retiree"])
    balanced_fit = compute_fitness(metrics, profiles["balanced"])
    growth_fit = compute_fitness(metrics, profiles["growth"])
    # Retiree weights heavily on Calmar (0.6) which is ~0.60; growth
    # weights heavily on CAGR (0.5) which is ~0.06. Retiree wins.
    assert retiree_fit > balanced_fit > growth_fit
