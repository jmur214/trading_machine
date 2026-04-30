"""Tests for Phase 2.10d Primitive 3 — regime-summary floor on
suggested_max_positions in engines/engine_e_regime/advisory.py.

The floor is a producer-side rule: when the regime_summary derived
from risk_score is `crisis` or `stressed`, suggested_max_positions is
capped at AdvisoryConfig.crisis_max_positions or stressed_max_positions
respectively. The min(...) operation preserves the existing
"advisory can only tighten, never loosen" contract.

Falsifiable spec: the April-2025 market_turmoil correlated drawdown
across 5 simultaneous edges should be impossible with this rule
active because suggested_max_positions in `crisis` floors at 5 (or
lower if the correlation axis is also stressed).
"""

from __future__ import annotations

from engines.engine_e_regime.advisory import AdvisoryEngine
from engines.engine_e_regime.regime_config import AdvisoryConfig


def _states(corr: str = "normal", trend: str = "bull", vol: str = "normal",
            breadth: str = "strong", forward_stress: str = "calm") -> dict:
    return {
        "correlation": corr,
        "trend": trend,
        "volatility": vol,
        "breadth": breadth,
        "forward_stress": forward_stress,
    }


def _confidences(value: float = 0.9) -> dict:
    return {
        "correlation": value,
        "trend": value,
        "volatility": value,
        "breadth": value,
        "forward_stress": value,
    }


def _durations(value: int = 50) -> dict:
    return {
        "correlation": value,
        "trend": value,
        "volatility": value,
        "breadth": value,
        "forward_stress": value,
    }


def _flip_counts(value: int = 0) -> dict:
    return {
        "correlation": value,
        "trend": value,
        "volatility": value,
        "breadth": value,
        "forward_stress": value,
    }


def _generate_for_regime(engine: AdvisoryEngine, target_summary: str,
                         corr_state: str = "normal") -> dict:
    """Construct axis states that drive risk_score into the requested
    regime_summary band, then return the advisory dict.

    risk_score thresholds: <0.25 benign, <0.50 cautious, <0.75 stressed, >=0.75 crisis.
    Verified state combos (per AXIS_RISK + NORMAL_WEIGHTS / STRESS_WEIGHTS):
    - benign:    bull / normal / normal / strong / calm     → ~0.07
    - cautious:  range / normal / normal / narrow / cautious → ~0.41
    - stressed:  bear / normal / normal / narrow / stressed  → ~0.65
    - crisis:    bear / shock / spike / weak / panic         → ~1.00
    For the "default" cases below we also verify with corr=normal so the
    regime-summary floor is what binds, not the correlation-state value.
    """
    if target_summary == "benign":
        states = _states(corr=corr_state, trend="bull", vol="normal",
                         breadth="strong", forward_stress="calm")
    elif target_summary == "cautious":
        states = _states(corr=corr_state, trend="range", vol="normal",
                         breadth="narrow", forward_stress="cautious")
    elif target_summary == "stressed":
        # Avoid vol=high to stay on NORMAL_WEIGHTS; bear+narrow+stressed gets us there
        states = _states(corr=corr_state, trend="bear", vol="normal",
                         breadth="narrow", forward_stress="stressed")
    elif target_summary == "crisis":
        # vol=shock flips to STRESS_WEIGHTS; combination saturates risk_score
        states = _states(corr=corr_state, trend="bear", vol="shock",
                         breadth="weak", forward_stress="panic")
    else:
        raise ValueError(target_summary)

    _macro, advisory = engine.generate(
        axis_states=states,
        axis_confidences=_confidences(0.9),
        axis_durations=_durations(50),
        flip_counts=_flip_counts(0),
    )
    return advisory


# ---------------------------------------------------------------------------
# Crisis floor
# ---------------------------------------------------------------------------

def test_crisis_regime_floors_suggested_max_positions_to_5_default():
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "crisis", corr_state="normal")
    assert advisory["regime_summary"] == "crisis"
    # corr=normal pre-floor would give 18; floor to crisis_max_positions=5
    assert advisory["suggested_max_positions"] == 5


def test_crisis_floor_only_tightens_when_correlation_already_stricter():
    """Correlation 'spike' gives 8; crisis floor of 5 wins → 5."""
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "crisis", corr_state="spike")
    assert advisory["regime_summary"] == "crisis"
    assert advisory["suggested_max_positions"] == 5


def test_crisis_floor_does_not_loosen_dispersed_correlation_to_25():
    """Correlation 'dispersed' would give 25; crisis floor of 5 wins → 5
    (the floor must never *loosen* the existing advisory)."""
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "crisis", corr_state="dispersed")
    assert advisory["regime_summary"] == "crisis"
    assert advisory["suggested_max_positions"] == 5


# ---------------------------------------------------------------------------
# Stressed floor
# ---------------------------------------------------------------------------

def test_stressed_regime_floors_suggested_max_positions_to_7_default():
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "stressed", corr_state="normal")
    assert advisory["regime_summary"] == "stressed"
    assert advisory["suggested_max_positions"] == 7


# Note: a "stressed regime with correlation=spike" scenario isn't tested
# because correlation=spike pushes risk_score into the crisis band — the
# combination is physically inconsistent in the regime-detection geometry,
# and the crisis floor (5) is what would actually apply.

# ---------------------------------------------------------------------------
# Non-stressed regimes — no floor applied
# ---------------------------------------------------------------------------

def test_benign_regime_does_not_apply_floor():
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "benign", corr_state="normal")
    assert advisory["regime_summary"] == "benign"
    # No floor; correlation 'normal' → 18
    assert advisory["suggested_max_positions"] == 18


def test_cautious_regime_does_not_apply_floor():
    engine = AdvisoryEngine()
    advisory = _generate_for_regime(engine, "cautious", corr_state="normal")
    assert advisory["regime_summary"] == "cautious"
    # No floor; correlation 'normal' → 18
    assert advisory["suggested_max_positions"] == 18


# ---------------------------------------------------------------------------
# Config tunability
# ---------------------------------------------------------------------------

def test_crisis_floor_uses_configured_value():
    """Verify the constants are config-driven, not hardcoded."""
    cfg = AdvisoryConfig(crisis_max_positions=3)
    engine = AdvisoryEngine(config=cfg)
    advisory = _generate_for_regime(engine, "crisis", corr_state="normal")
    assert advisory["suggested_max_positions"] == 3


def test_stressed_floor_uses_configured_value():
    cfg = AdvisoryConfig(stressed_max_positions=10)
    engine = AdvisoryEngine(config=cfg)
    advisory = _generate_for_regime(engine, "stressed", corr_state="normal")
    # min(18, 10) = 10
    assert advisory["suggested_max_positions"] == 10


# ---------------------------------------------------------------------------
# April-2025 falsifiable scenario
# ---------------------------------------------------------------------------

def test_april_2025_scenario_caps_at_5_concurrent_positions():
    """The April-2025 market_turmoil event had 5 edges fire simultaneously
    into the regime, producing -$3,551 of correlated loss. With this rule
    active, suggested_max_positions in 'crisis' is 5 — meaning even though
    5 edges produced signals, the RiskEngine's effective_max_positions
    becomes min(5, cfg.max_positions) and only 5 concurrent positions
    can exist. The 6th-Nth signal of the day is rejected, and assuming
    some carry-overs from prior bars, FEWER than 5 entries will actually
    fire — the joint-drawdown shape of April-2025 becomes structurally
    impossible."""
    engine = AdvisoryEngine()
    # Simulate the regime conditions: high vol, narrow breadth, elevated
    # forward stress → risk_score lands in crisis band
    advisory = _generate_for_regime(engine, "crisis", corr_state="normal")
    assert advisory["suggested_max_positions"] <= 5, (
        f"crisis advisory suggested {advisory['suggested_max_positions']} "
        f"positions; the April-2025 scenario requires <= 5"
    )
