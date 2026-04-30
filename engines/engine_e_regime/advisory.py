"""
AdvisoryEngine — generates non-binding advisory hints from stabilized regime state.

Four components:
  1. Risk score with dynamic axis weights (shift by current vol state)
  2. Coherence checks (unstable axis combinations)
  3. Duration modulation (applied only to exposure_cap)
  4. Flip frequency warnings

Also: named macro regime mapping with soft probabilities,
      dual-source edge affinity (axis-based + macro-regime-based).
"""

import numpy as np
from typing import Dict, List, Optional, Tuple

from engines.engine_e_regime.regime_config import AdvisoryConfig


# ──────────────────────────────────────────────
# Macro Regime Mapping
# ──────────────────────────────────────────────

MACRO_RULES = {
    "robust_expansion": {
        "trend": ["bull"],
        "volatility": ["low", "normal"],
        "breadth": ["strong"],
        "correlation": ["normal", "dispersed"],
        "forward_stress": ["calm"],
    },
    "emerging_expansion": {
        "trend": ["bull"],
        "volatility": ["normal", "high"],
        "breadth": ["narrow", "recovering", "strong"],
        "correlation": ["normal", "elevated"],
        "forward_stress": ["calm", "cautious"],
    },
    "cautious_decline": {
        "trend": ["range", "bear"],
        "volatility": ["normal", "high"],
        "breadth": ["narrow", "deteriorating", "weak"],
        "correlation": ["normal", "elevated"],
        "forward_stress": ["cautious", "stressed"],
    },
    "market_turmoil": {
        "trend": ["bear"],
        "volatility": ["high", "shock"],
        "correlation": ["elevated", "spike"],
        "forward_stress": ["stressed", "panic"],
    },
}

# ──────────────────────────────────────────────
# Macro-Regime Edge Affinity Table
# ──────────────────────────────────────────────

MACRO_EDGE_AFFINITY = {
    "robust_expansion":  {"momentum": 1.3, "mean_reversion": 0.7, "trend_following": 1.2, "fundamental": 1.0},
    "emerging_expansion": {"momentum": 0.9, "mean_reversion": 1.0, "trend_following": 1.0, "fundamental": 1.1},
    "cautious_decline":  {"momentum": 0.6, "mean_reversion": 0.9, "trend_following": 0.8, "fundamental": 0.8},
    "market_turmoil":    {"momentum": 0.4, "mean_reversion": 0.5, "trend_following": 0.6, "fundamental": 0.7},
    "transitional":      {"momentum": 0.8, "mean_reversion": 0.8, "trend_following": 0.7, "fundamental": 0.9},
}

# ──────────────────────────────────────────────
# Per-Axis Risk Mapping
# ──────────────────────────────────────────────

AXIS_RISK = {
    "trend":          {"bull": 0.0, "range": 0.5, "bear": 1.0},
    "volatility":     {"low": 0.0, "normal": 0.33, "high": 0.83, "shock": 1.0},
    "correlation":    {"dispersed": 0.0, "normal": 0.25, "elevated": 0.75, "spike": 1.0},
    "breadth":        {"strong": 0.0, "recovering": 0.20, "narrow": 0.50, "deteriorating": 0.75, "weak": 1.0},
    "forward_stress": {"calm": 0.0, "cautious": 0.33, "stressed": 0.75, "panic": 1.0},
}

# Dynamic axis weights by vol state
NORMAL_WEIGHTS = {
    "trend": 0.30, "breadth": 0.25, "forward_stress": 0.20,
    "correlation": 0.15, "volatility": 0.10,
}
STRESS_WEIGHTS = {
    "forward_stress": 0.30, "volatility": 0.25, "correlation": 0.25,
    "trend": 0.10, "breadth": 0.10,
}

# ──────────────────────────────────────────────
# Coherence Checks (Unstable Combinations)
# ──────────────────────────────────────────────

UNSTABLE_COMBOS: List[dict] = [
    # Pre-Crisis Fragility ("Walking on Ice" — Two Sigma)
    {
        "trend": "bull", "volatility": "high", "correlation": "elevated",
        "breadth": "deteriorating",
        "label": "pre_crisis_fragility",
        "note": "Walking on Ice — elevated unwind risk, momentum reversal likely",
        "advisory_override": {"momentum": 0.5, "mean_reversion": 1.2, "exposure_cap_max": 0.65},
    },
    {"trend": "bull", "breadth": "weak",
     "note": "Narrow leadership — elevated reversal risk"},
    {"trend": "bull", "breadth": "narrow",
     "note": "Rally narrowing — watch for breadth deterioration"},
    {"trend": "bull", "correlation": "spike",
     "note": "Crowded market — correlated unwind risk"},
    {"volatility": "shock", "correlation": "spike",
     "note": "Systemic stress pattern — maximum caution"},
    {"trend": "bear", "breadth": "recovering",
     "note": "Potential bottom formation — breadth improving despite bear trend"},
    {"trend": "range", "volatility": "low", "breadth": "strong",
     "note": "Compressed range with healthy internals — breakout setup"},
    {"volatility": "high", "correlation": "dispersed",
     "note": "Idiosyncratic vol — stock-picking environment, not systemic"},
    {"trend": "bear", "volatility": "low",
     "note": "Quiet decline — complacency risk, may accelerate"},
    {"volatility": "normal", "forward_stress": "stressed",
     "note": "Implied stress exceeds realized — market pricing future risk not yet visible in price"},
]

EDGE_TYPES = ["momentum", "mean_reversion", "trend_following", "fundamental"]


class AdvisoryEngine:
    """Generates non-binding advisory hints from stabilized regime state."""

    def __init__(self, config: AdvisoryConfig = None):
        self.cfg = config or AdvisoryConfig()

    def generate(
        self,
        axis_states: Dict[str, str],
        axis_confidences: Dict[str, float],
        axis_durations: Dict[str, int],
        flip_counts: Dict[str, int],
        corr_details: Optional[dict] = None,
    ) -> Tuple[dict, dict]:
        """Generate advisory hints and macro regime info.

        Args:
            axis_states: {axis_name: state_string} for all 5 axes.
            axis_confidences: {axis_name: float} for all 5 axes.
            axis_durations: {axis_name: int} consecutive bars in current state.
            flip_counts: {axis_name: int} transitions in last N bars.
            corr_details: Enriched correlation details (for gold safe-haven check).

        Returns:
            (macro_regime_dict, advisory_dict)
        """
        corr_details = corr_details or {}

        # --- 1. Macro regime mapping with soft probabilities ---
        macro_regime = self._compute_macro_regime(axis_states, axis_confidences)

        # --- 2. Risk score ---
        risk_score = self._compute_risk_score(axis_states, axis_confidences)

        # --- 3. Coherence checks ---
        caution_notes = self._check_coherence(axis_states, corr_details)
        coherence_overrides = self._get_coherence_overrides(axis_states)

        # --- 4. Flip frequency warnings ---
        flip_warnings = self._check_flip_frequency(flip_counts)
        caution_notes.extend(flip_warnings)

        # --- 5. Duration modulation (exposure_cap only) ---
        min_duration = min(axis_durations.values()) if axis_durations else 1
        duration_factor = float(np.clip(min_duration / self.cfg.duration_ramp_bars, 0.5, 1.0))

        # --- 6. Advisory outputs ---
        regime_summary = self._risk_to_summary(risk_score)

        # Exposure cap: more restrictive with higher risk, modulated by duration
        raw_exposure_cap = max(0.3, 1.0 - risk_score * 0.7)
        # For risk-off: tighter the longer bad regime persists
        # For risk-on: ramp up gradually
        if risk_score > 0.5:
            suggested_exposure_cap = raw_exposure_cap * (2.0 - duration_factor)
        else:
            suggested_exposure_cap = raw_exposure_cap * duration_factor
        suggested_exposure_cap = float(np.clip(suggested_exposure_cap, 0.3, 1.0))

        # Apply coherence override cap if present
        if "exposure_cap_max" in coherence_overrides:
            suggested_exposure_cap = min(
                suggested_exposure_cap, coherence_overrides["exposure_cap_max"]
            )

        # Risk scalar: NOT modulated by duration (prevents compounding)
        risk_scalar = float(np.clip(max(0.3, 1.2 - risk_score * 0.9), 0.3, 1.2))

        # Max positions: lower in correlation spike
        corr_state = axis_states.get("correlation", "normal")
        if corr_state == "spike":
            suggested_max_positions = 8
        elif corr_state == "elevated":
            suggested_max_positions = 12
        elif corr_state == "dispersed":
            suggested_max_positions = 25
        else:
            suggested_max_positions = 18

        # Phase 2.10d Primitive 3: regime-summary floor on top of correlation-state map.
        # April-2025 market_turmoil produced -$3,551 simultaneous correlated loss across 5 edges
        # because the correlation axis was "normal" → suggested_max_positions stayed at 18 even
        # though regime_summary was "crisis". Apply regime-summary as a hard floor; whichever of
        # the two values (correlation-state-derived vs regime-summary-derived) is more conservative
        # wins, preserving the "advisory can only tighten" contract.
        if regime_summary == "crisis":
            suggested_max_positions = min(
                suggested_max_positions, self.cfg.crisis_max_positions
            )
        elif regime_summary == "stressed":
            suggested_max_positions = min(
                suggested_max_positions, self.cfg.stressed_max_positions
            )

        # --- 7. Edge affinity (dual-source blending) ---
        edge_affinity = self._compute_edge_affinity(
            axis_states, macro_regime, coherence_overrides
        )

        advisory = {
            "regime_summary": regime_summary,
            "suggested_exposure_cap": round(suggested_exposure_cap, 3),
            "risk_scalar": round(risk_scalar, 3),
            "suggested_max_positions": suggested_max_positions,
            "edge_affinity": edge_affinity,
            "caution_note": " | ".join(caution_notes) if caution_notes else "",
        }

        return (macro_regime, advisory)

    # ──────────────────────────────────────────
    # Macro Regime
    # ──────────────────────────────────────────

    def _compute_macro_regime(
        self, axis_states: Dict[str, str], axis_confidences: Dict[str, float]
    ) -> dict:
        """Compute soft probability distribution across named macro regimes."""
        scores = {}
        for regime_name, rules in MACRO_RULES.items():
            match_score = 0.0
            for axis, allowed_states in rules.items():
                state = axis_states.get(axis, "unknown")
                conf = axis_confidences.get(axis, 0.5)
                if state in allowed_states:
                    match_score += conf
                else:
                    match_score += (1.0 - conf) * 0.1
            scores[regime_name] = match_score

        # Transitional base rate — kept low so real regimes win when axes agree
        scores["transitional"] = 0.15

        # Normalize via simple ratio (not softmax — avoids exp overflow on extreme scores)
        total = sum(scores.values())
        probs = {k: round(v / total, 3) for k, v in scores.items()}

        # Best regime — use 0.25 threshold so partial-match regimes still classify
        # rather than defaulting to "transitional" when axes partially conflict
        best = max(probs, key=probs.get)
        if probs[best] < 0.25:
            label = "transitional"
        else:
            label = best

        return {"label": label, "probabilities": probs}

    # ──────────────────────────────────────────
    # Risk Score
    # ──────────────────────────────────────────

    def _compute_risk_score(
        self, axis_states: Dict[str, str], axis_confidences: Dict[str, float]
    ) -> float:
        """Weighted risk score with dynamic axis weights."""
        vol_state = axis_states.get("volatility", "normal")
        weights = STRESS_WEIGHTS if vol_state in ("high", "shock") else NORMAL_WEIGHTS

        risk = 0.0
        for axis, weight in weights.items():
            state = axis_states.get(axis, "normal")
            risk_val = AXIS_RISK.get(axis, {}).get(state, 0.5)
            risk += weight * risk_val

        return float(np.clip(risk, 0.0, 1.0))

    @staticmethod
    def _risk_to_summary(risk_score: float) -> str:
        if risk_score < 0.25:
            return "benign"
        elif risk_score < 0.50:
            return "cautious"
        elif risk_score < 0.75:
            return "stressed"
        else:
            return "crisis"

    # ──────────────────────────────────────────
    # Coherence Checks
    # ──────────────────────────────────────────

    def _check_coherence(
        self, axis_states: Dict[str, str], corr_details: dict
    ) -> List[str]:
        """Check for unstable axis combinations and return caution notes."""
        notes = []
        for combo in UNSTABLE_COMBOS:
            # Skip custom checks handled separately
            if "_custom_check" in combo:
                continue

            match = True
            for axis in ("trend", "volatility", "correlation", "breadth", "forward_stress"):
                if axis in combo and axis_states.get(axis) != combo[axis]:
                    match = False
                    break
            if match:
                notes.append(combo["note"])

        # Gold safe-haven demand check
        spy_gld_corr = corr_details.get("spy_gld_corr", 0.0)
        if spy_gld_corr < -0.30:
            notes.append("Gold safe-haven demand elevated — risk aversion building")

        return notes

    def _get_coherence_overrides(self, axis_states: Dict[str, str]) -> dict:
        """Get advisory overrides from matching coherence patterns."""
        overrides = {}
        for combo in UNSTABLE_COMBOS:
            if "advisory_override" not in combo:
                continue
            match = True
            for axis in ("trend", "volatility", "correlation", "breadth", "forward_stress"):
                if axis in combo and axis_states.get(axis) != combo[axis]:
                    match = False
                    break
            if match:
                overrides.update(combo["advisory_override"])
        return overrides

    # ──────────────────────────────────────────
    # Flip Frequency
    # ──────────────────────────────────────────

    def _check_flip_frequency(self, flip_counts: Dict[str, int]) -> List[str]:
        """Warn if any axis has flipped too many times recently."""
        warnings = []
        threshold = self.cfg.flip_frequency_warning_threshold
        for axis, count in flip_counts.items():
            if count > threshold:
                warnings.append(
                    f"Regime instability on {axis}: {count} transitions in "
                    f"{self.cfg.flip_frequency_lookback} bars — choppy tape"
                )
        return warnings

    # ──────────────────────────────────────────
    # Edge Affinity (Dual-Source)
    # ──────────────────────────────────────────

    def _compute_edge_affinity(
        self,
        axis_states: Dict[str, str],
        macro_regime: dict,
        coherence_overrides: dict,
    ) -> Dict[str, float]:
        """Compute blended edge affinity from axis states + macro regime.

        50% axis-based + 50% macro-regime-based, with coherence overrides.
        """
        # Source 1: Axis-based affinity
        axis_affinity = self._axis_based_affinity(axis_states)

        # Source 2: Macro-regime-based affinity (weighted by probabilities)
        macro_affinity = self._macro_based_affinity(macro_regime)

        # Blend 50/50
        blended = {}
        for edge in EDGE_TYPES:
            val = 0.5 * axis_affinity[edge] + 0.5 * macro_affinity[edge]

            # Apply coherence overrides
            if edge in coherence_overrides:
                val = coherence_overrides[edge]

            blended[edge] = round(float(np.clip(val, 0.3, 1.5)), 2)

        return blended

    @staticmethod
    def _axis_based_affinity(axis_states: Dict[str, str]) -> Dict[str, float]:
        """Compute edge affinity from individual axis states."""
        trend = axis_states.get("trend", "range")
        vol = axis_states.get("volatility", "normal")
        corr = axis_states.get("correlation", "normal")
        breadth = axis_states.get("breadth", "strong")

        momentum = 1.0
        if trend == "bull" and vol in ("low", "normal") and breadth == "strong":
            momentum = 1.3
        elif trend == "range" or vol in ("high", "shock"):
            momentum = 0.6

        mean_reversion = 1.0
        if trend == "range" and corr in ("normal", "dispersed"):
            mean_reversion = 1.3
        elif corr == "spike":
            mean_reversion = 0.5

        trend_following = 1.0
        if trend in ("bull", "bear") and vol in ("low", "normal"):
            trend_following = 1.3
        elif trend == "range":
            trend_following = 0.5

        fundamental = 1.0
        if corr == "dispersed":
            fundamental = 1.3
        elif corr == "spike":
            fundamental = 0.6

        return {
            "momentum": momentum,
            "mean_reversion": mean_reversion,
            "trend_following": trend_following,
            "fundamental": fundamental,
        }

    @staticmethod
    def _macro_based_affinity(macro_regime: dict) -> Dict[str, float]:
        """Compute edge affinity weighted by macro regime probabilities."""
        probs = macro_regime.get("probabilities", {})
        result = {e: 0.0 for e in EDGE_TYPES}

        for regime, prob in probs.items():
            affinity = MACRO_EDGE_AFFINITY.get(regime, MACRO_EDGE_AFFINITY["transitional"])
            for edge in EDGE_TYPES:
                result[edge] += prob * affinity[edge]

        return result
