# Spec — T-2026-05-12-055: Engine B portfolio-level vol-targeting (Moreira-Muir 2017)

**Date drafted:** 2026-05-12 LATE (director-side, post-research-synthesis + user explicit approval)
**Status:** SPEC for dispatch. **Engine B touch — propose-first per CLAUDE.md. User has explicitly approved 2026-05-12.**
**Will be executed by:** Agent A or B (~6-10 hr).
**Sequencing:** independent — does NOT require T-054 first; does NOT require T-043 flag-flip to have applied.
**Output:** Engine B vol-targeting layer + A/B harness validation + audit doc.

---

## Why this is the highest-leverage non-T-054 dispatch

**All four 2026-05-16 research dives converged on this single recommendation:**

> Dive 1 (Alpha): implied via "vol-targeting overlay" — 0.05-0.10 SR lift, real risk control
> Dive 2 (Compound): "The single most under-priced upgrade for retail is portfolio-level vol targeting" — +0.10 to +0.20 SR lift (Moreira-Muir 2017)
> Dive 3 (Regime): "Always-on plumbing every retail trader should run" — bigger Sharpe lift than any cross-sectional weighting refinement
> Dive 4 (Metrics): "The most actionable lever" via realized/target vol ratio R

**This is the only project recommendation where four independent research reviews agreed without nuance.**

The prior plan parked it under "engines-first pending alpha." Per the user's 2026-05-12 reframing ("bones must be PERFECT before LLM"): vol-targeting is NOT alpha amplifier; it's Sharpe RESTRUCTURER. It improves the risk-adjusted return of WHATEVER signal exposure we have, regardless of factor decomposition. Per dive 2's framing: "It's mechanically trivial, well-evidenced, and produces a larger Sharpe lift than any cross-sectional weighting refinement."

---

## What

Implement Engine B portfolio-level vol-targeting per Moreira-Muir 2017 (*Journal of Finance*) + Harvey-Hoyle-Korgaonkar-Rattray-Sargaison-van Hemert 2018 (*JPM*, "The Impact of Volatility Targeting").

### Component 1: Target-vol configuration

`engines/engine_b_risk/vol_target.py` (NEW file):

```python
@dataclass
class VolTargetConfig:
    enabled: bool = False  # defense-first; flip on after A/B
    target_annual_vol: float = 0.10  # 10% annualized; standard for retail
    realized_vol_window_days: int = 60  # 60-day rolling estimator
    leverage_floor: float = 0.5  # don't de-lever to zero in calm regimes
    leverage_ceiling: float = 2.0  # don't over-lever in volatile regimes
    de_lever_threshold_ratio: float = 1.2  # scale = 1/R when R > threshold
    re_lever_threshold_ratio: float = 0.8  # scale = 1/R when R < threshold; capped
    rebalance_cadence: str = "daily"  # daily evaluation; cap intra-day moves
```

### Component 2: Vol-scale computation

```python
def compute_vol_scale(
    realized_vol: float,  # annualized realized vol of portfolio returns (60d rolling)
    target_vol: float,    # config.target_annual_vol
    floor: float,
    ceiling: float,
) -> float:
    """
    Return the leverage multiplier to apply to portfolio gross exposure.

    Standard Moreira-Muir: scale = target_vol / realized_vol
    But with floor and ceiling to prevent over/under-leveraging at tails:
      scale = clip(target_vol / realized_vol, floor, ceiling)

    Critical: realized_vol uses returns ONLY UP TO bar t-1 (no look-ahead).
    """
```

### Component 3: Integration into risk-engine sizing

Wire into existing `engines/engine_b_risk/risk_engine.py` sizing path. The vol-scale multiplies the position-sizing output AFTER all existing risk constraints (drawdown halt, kill-switch, correlation gates) but BEFORE the final order is emitted.

Key: vol-targeting must NOT override kill-switch / drawdown-halt. It's a sizing modifier, not a risk-override.

### Component 4: A/B harness validation

Run the same substrate-honest 5-year grid as T-035 with vol-targeting ON vs OFF. 3 reps × 5 years × 2 arms = 30 backtests.

**Important: per user's "bones first PERFECT" directive, this is a SHARPE-LIFT validation, NOT an alpha-validation.** Per Moreira-Muir 2017, expected lift is +0.10 to +0.20 Sharpe across factor strategies. The lift comes from:
1. Better risk-adjusted return distribution (kurtosis cut from 4.6 to 1.8 per Harvey et al. 2018)
2. Avoiding over-leverage in calm regimes (Feb 2018 vol-target-strategies trapped lesson)
3. Faster de-leveraging in stress regimes (Aug 2024 yen-carry-style events)

### Component 5: Audit doc + state updates

`docs/Audit/engine_b_vol_targeting_2026_05_12.md`:
- Theory + Moreira-Muir citation + expected lift range
- A/B grid result (3 reps × 5 years × 2 arms)
- Sharpe + Sortino + max drawdown + kurtosis ON vs OFF
- Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe
- Recommended deployment: keep enabled (or document why not)

State doc updates:
- forward_plan.md: Engine B vol-targeting LANDED (not "on hold")
- health_check.md: vol-targeting addition + expected Sharpe-lift band
- lessons_learned.md: cross-research-dive convergence finding + Moreira-Muir validation

---

## Acceptance

1. **`engines/engine_b_risk/vol_target.py`** with `VolTargetConfig` + `compute_vol_scale` + integration helpers.
2. **Wiring into `risk_engine.py`** — vol-scale applied AFTER existing risk constraints, BEFORE final order emission. Does NOT override kill-switch / drawdown-halt.
3. **`config/risk_config.yml`** (or equivalent) exposes the vol-target config with defense-first default (`enabled=False`).
4. **A/B harness validation**: 3 reps × 5 years × 2 arms (ON / OFF). Substrate-honest universe. Cockpit-fixed metrics. Bootstrap CI per CLAUDE.md.
5. **Headline output table:**
   | Metric | OFF (baseline) | ON (vol-targeted) | Δ |
   |---|---|---|---|
   | Mean Sharpe (5y) | ? | ? | ? |
   | ci_low (Sharpe) | ? | ? | ? |
   | Mean Sortino | ? | ? | ? |
   | Max drawdown | ? | ? | ? |
   | Kurtosis (returns) | ? | ? | ? |
   | Vol of vol | ? | ? | ? |
6. **Tests** in `tests/test_engine_b_vol_targeting.py`:
   - `test_vol_scale_computation` — known input/output mathematical correctness
   - `test_vol_scale_respects_floor` — realized_vol → 0, scale capped at ceiling
   - `test_vol_scale_respects_ceiling` — realized_vol very high, scale capped at floor
   - `test_no_lookahead_in_realized_vol` — uses only bars [t-60, t-1]
   - `test_vol_target_disabled_passthrough` — config.enabled=False → scale=1.0 always
   - `test_vol_target_does_not_override_killswitch` — drawdown-halt fires regardless of vol-target state
   - `test_vol_target_does_not_override_drawdown_halt` — same for circuit breaker
   - `test_a_b_determinism` — 3-rep bitwise canon md5 invariant ON and OFF
   - Integration test: vol-target ON, 1-year smoke, verify final gross exposure matches expected scale
7. **Audit doc** at `docs/Audit/engine_b_vol_targeting_2026_05_12.md`.
8. **State doc updates** committed alongside.
9. **Branch:** `feature/engine-b-vol-targeting`. Push only; director merges + pushes after review.

---

## Hard constraints

- DO NOT modify kill-switch / drawdown-halt logic. Vol-targeting is a sizing modifier, not a risk-override.
- DO NOT use look-ahead in realized-vol computation. Realized vol at bar t uses ONLY returns from bars [t-window, t-1].
- DO NOT skip the A/B harness. Per CLAUDE.md 6th non-negotiable: any Sharpe headline must report ci_low.
- DO NOT enable by default. Defense-first: ship with `enabled=False`; director reviews + flips after A/B confirms lift.
- Per CLAUDE.md: Engine B changes are propose-first. **User has explicitly approved this dispatch 2026-05-12.**
- Determinism preserved: vol-targeting must not introduce non-determinism. 3-rep bitwise canon md5 invariant in both ON and OFF arms.

---

## Time budget

- Implementation (`vol_target.py` + wiring): ~2-3 hr
- A/B harness run: ~3-4 hr (30 backtests × ~7-10 min each at T-013 vectorized speed, on cockpit-fixed metrics)
- Tests: ~1-2 hr
- Audit doc + state-doc updates: ~1-2 hr
- **Total: 6-10 hr**

---

## Open questions for implementing agent (surface in audit doc, not block)

1. **Target vol = 10% or 12%?** Standard retail-fit (Carver Systematic Trading) is 10%; institutional often 12-15%. Recommend 10% for v1; sensitivity sweep in audit doc shows whether 8/10/12/15 produces different lift profile.

2. **Window = 60 days or EWMA λ=0.94?** Metrics dive recommends EWMA for faster response in stress. Recommend EWMA λ=0.94 as default; 60-day rolling as fallback for transparency.

3. **Apply scale to per-edge weights OR final position sizes?** Final position sizes (vol-targeting is a portfolio-level overlay, not per-edge). Document.

4. **What if vol-targeting changes the canon md5 dramatically?** Expected — vol-targeting fundamentally changes position-sizing dynamics. The 3-rep WITHIN-arm determinism is what matters; across-arm canon md5 will differ by design.

5. **Floor and ceiling values: 0.5 and 2.0?** Standard. The 2.0 ceiling prevents Feb-2018-style over-leveraging trap; the 0.5 floor prevents zero-exposure in calm regimes. Document if sensitivity sweep argues for different values.

---

## Forward-look (after T-055 lands + A/B confirms lift)

- **T-055b**: enable vol-targeting in production (`enabled=True` flip), document the production-canon shift, surface to user
- **T-055c**: regime-conditional vol-target levels (e.g., target=8% in ANFCI-stressed regime, 12% in benign). This is "factor-momentum on the vol-target side" and per dive 3's "Layer 3 regime-conditional risk estimates" recommendation.
- **T-055d**: vol-of-vol kill switch (`VVIX z-score > 3 → flatten short-vol`) — per dive 1's specific guidance for any short-vol exposure we eventually add

---

## Director note + user approval gate

This is the project's first ship-now-because-research-converges Engine B change. The user has explicitly approved Engine B changes on 2026-05-12 with the directive "bones must be PERFECT." Vol-targeting is exactly the kind of bone-perfection work the user prioritized.

Defense-first default (`enabled=False`) ships with the implementation. Director reviews A/B harness result + flips the flag after confirming the expected +0.10 to +0.20 Sharpe lift materializes. **The flag-flip itself is a separate sub-dispatch (T-055b) to maintain the propose-first discipline even within an approved track.**
