"""cross_asset_confirm — Engine E cross-asset HMM-transition gate.

Workstream-C cross-asset confirmation layer (Wave 2 of round-N+1).

Top-down rationale: HMM regime detection on a single feature panel
(SPY-derived + macro) is correct in expectation but noisy on individual
transitions — a single chaotic week can flip the posterior from benign
to crisis even when no other asset class confirms stress. Acting on
that single signal trades real capital against a noise event.

The fix is the classic 'two-out-of-three' confirmation pattern from
trend-following: require independent corroboration before you re-allocate.
The three independent assets we check:

  - Credit (HY-IG OAS spread z-score) — `hyg_lqd_z`
  - FX (broad USD index 20d % change)  — `dxy_change_20d`
  - Vol-of-vol (30d realized vol of VIX) — `vvix_proxy`

These three are deliberately chosen across uncorrelated channels
(credit, FX, vol-of-vol) so the confirmation isn't tautological with
the SPY-vol signal that already dominates the HMM input. If at least
two confirm a stress regime, the HMM transition is accepted; otherwise
vetoed.

Engine boundary: this module DETECTS that a transition is real (E's
job). It does NOT change risk policy itself (B's job) or capital
allocation (C's job). Downstream consumers receive `{confirm, veto_reason,
confidence}` and decide what to do with it. The confirmation function is
config-flag-toggleable; default OFF on main per WS-C smoke acceptance.

Asymmetry: confirmation is REQUIRED to enter a stress regime; not
required to exit. This is intentional — the cost of staying risk-on
through a real crisis is much higher than the cost of staying risk-off
through a confirmed-but-already-fading crisis. We bias toward 'don't
add risk on a single noisy signal' rather than 'don't shed risk on a
single noisy signal'.

Signature:

    confirm_regime_transition(
        hmm_signal: dict,
        cross_asset_state: dict,
        config: Optional[dict] = None,
    ) -> dict

    hmm_signal:
        {
            "state": str,                       # current HMM state
            "prev_state": Optional[str],        # state at previous bar
            "transition_probs": Dict[str, float], # posterior at this bar
            "confidence": float,                # entropy-derived [0, 1]
        }

    cross_asset_state:
        {
            "hyg_lqd_z":       Optional[float],
            "dxy_change_20d":  Optional[float],
            "vvix_proxy":      Optional[float],
        }

    Returns:
        {
            "confirm":      bool,
            "veto_reason":  Optional[str],
            "confidence":   float,
        }
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# Default thresholds — what counts as "this asset signals stress".
# Calibrated against round-numbers in the original spec; the config arg
# lets downstream callers tune per backtest window if desired.
DEFAULT_CONFIG: Dict[str, Any] = {
    # Credit: HY-IG OAS z-score above +1.0 = credit spread widening.
    "hyg_lqd_z_threshold": 1.0,
    # FX: 20d USD index change above +2% = risk-off rally in dollar.
    "dxy_change_20d_threshold": 0.02,
    # Vol-of-vol: 90th-percentile threshold; calibrated against historical
    # realized vol-of-VIX. The default is a level chosen to fire roughly
    # in the top decile of observations — downstream measurement may
    # update this against the actual empirical 90th percentile.
    "vvix_proxy_threshold": 1.0,
    # Which HMM states count as "stress" for confirmation purposes.
    # Transitions INTO any state in this set require cross-asset confirm.
    # Default: only the highest-vol "crisis" state. The "stressed" state
    # is intermediate and doesn't get gated — we don't want to be slow
    # to acknowledge mid-tier risk-off.
    "stress_states": ("crisis",),
    # Minimum number of confirming cross-asset signals required.
    "min_confirmations": 2,
}


def _is_stress_transition(hmm_signal: Dict[str, Any],
                          stress_states: tuple) -> bool:
    """True when the HMM moves INTO a stress state from a non-stress state."""
    current = hmm_signal.get("state")
    prev = hmm_signal.get("prev_state")
    if current is None:
        return False
    # Same state = no transition to confirm.
    if prev is not None and prev == current:
        return False
    return current in stress_states and (
        prev is None or prev not in stress_states
    )


def _count_confirmations(
    cross_asset_state: Dict[str, Optional[float]],
    cfg: Dict[str, Any],
) -> int:
    """Count how many of the three cross-asset signals are 'in stress'."""
    confirms = 0

    hyg = cross_asset_state.get("hyg_lqd_z")
    if hyg is not None and hyg > cfg["hyg_lqd_z_threshold"]:
        confirms += 1

    dxy = cross_asset_state.get("dxy_change_20d")
    if dxy is not None and dxy > cfg["dxy_change_20d_threshold"]:
        confirms += 1

    vvix = cross_asset_state.get("vvix_proxy")
    if vvix is not None and vvix > cfg["vvix_proxy_threshold"]:
        confirms += 1

    return confirms


def confirm_regime_transition(
    hmm_signal: Dict[str, Any],
    cross_asset_state: Dict[str, Optional[float]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Confirm or veto an HMM regime transition using cross-asset corroboration.

    See module docstring for the full design and signature contract.

    Returns a dict with:
      - confirm:     True if the transition is accepted, False if vetoed.
      - veto_reason: Human-readable veto reason, or None if confirmed.
      - confidence:  Float in [0, 1] mirroring the HMM input confidence
                     (or 0.0 if not provided). Pass-through for now;
                     future revisions may amplify or attenuate this.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    confidence = float(hmm_signal.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    stress_states = tuple(cfg["stress_states"])

    # Path 1 — not entering a stress regime: nothing to confirm. Trivially
    # True. Includes the no-transition case AND transitions OUT of stress.
    if not _is_stress_transition(hmm_signal, stress_states):
        return {
            "confirm": True,
            "veto_reason": None,
            "confidence": confidence,
        }

    # Path 2 — entering stress: count cross-asset confirms.
    confirms = _count_confirmations(cross_asset_state, cfg)
    min_required = int(cfg["min_confirmations"])

    if confirms >= min_required:
        return {
            "confirm": True,
            "veto_reason": None,
            "confidence": confidence,
        }

    return {
        "confirm": False,
        "veto_reason": "insufficient cross-asset confirmation",
        "confidence": confidence,
    }
