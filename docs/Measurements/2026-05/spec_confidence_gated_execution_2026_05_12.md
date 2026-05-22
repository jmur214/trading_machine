# Spec — T-2026-05-12-057: Confidence-gated execution A/B harness (N-of-K signal filter)

**Date drafted:** 2026-05-22 (director-side, post N-of-K diagnostic + factor-decomp correction)
**Status:** SPEC for queue. Engine A scope (signal_processor extension). Autonomous-improvement per CLAUDE.md.
**Will be executed by:** Agent A or B (~6-8 hr).
**Sequencing:** AFTER T-055 (Engine B vol-targeting) lands so canon-md5 changes are isolated. Independent of T-041b.
**Output:** N-threshold gate in signal_processor + A/B harness validation + audit doc.

---

## Why — revised framing per N-of-K correction

**The N-of-K diagnostic (`docs/Audit/n_of_k_agreement_diagnostic_2026_05_12.md`) found compound SIGNAL at high agreement-count but NO idiosyncratic α** when daily-aggregated and FF5+Mom-decomposed:

| N | per-bar Sharpe ci_low | daily Sharpe | alpha%/yr | alpha_t |
|---|---|---|---|---|
| N≥1 | -0.187 (noise) | 0.345 | +0.63% | +0.120 |
| N≥2 | **+0.076** | 0.422 | +3.25% | +0.427 |
| N≥3 | **+0.060** | -0.004 | -2.80% | -0.168 |

The per-bar bootstrap CI clearance at N≥2/N≥3 is real signal, but the daily-portfolio aggregated alpha t-stat fails t > 2 — Beta_Mom rises with N (0.032 → 0.056 → 0.119), so high-N agreement just concentrates momentum factor exposure.

**Reframed T-057 value proposition** (per the user's "bones must be PERFECT" directive):

1. **Filter 66,037 N=1 noise bars** (74% of fired-edge bars; ci_low -0.187 = noise band)
2. **Concentrate capital on 22,846 N≥2 high-conviction bars** (23% of fired bars)
3. **Reduce turnover** → lower transaction costs (Novy-Marx-Velikov 2016 RFS: most published anomalies die after realistic costs at high turnover)
4. **Improve factor-exposure delivery efficiency** (better Sharpe for same factor exposure)

**NOT a "find alpha" dispatch.** The 0/11 factor-α verdict stands. T-057 is a Sharpe-restructurer in the same category as T-055 vol-targeting — improves the *delivery* of whatever factor exposure exists, doesn't create idiosyncratic α.

**Orthogonal to T-055**: T-055 modifies position SIZES (Engine B risk side, post-aggregation); T-057 modifies which signals get TRADED (Engine A signal-processor, pre-aggregation). They compound: a vol-targeted portfolio that only trades high-conviction signals should have lower vol-of-vol + lower turnover + better Sharpe than either alone.

---

## What

### 1. Add N-threshold configuration to signal_processor

`engines/engine_a_alpha/signal_processor.py`:

```python
@dataclass
class ConfidenceGateConfig:
    """T-057 confidence-gated execution.

    Filters bars where fewer than `n_threshold` edges agree on direction.
    Defense-first default: enabled=False (current weighted_sum behavior
    preserved). A/B harness toggles ON to validate Sharpe lift.
    """
    enabled: bool = False
    n_threshold: int = 2  # minimum edges agreeing on direction to trade
    direction_method: str = "raw_score_sign"  # how to determine direction:
                                              # "raw_score_sign" (default) or
                                              # "norm_score_sign" (post-normalization)
```

### 2. Implement the gate in the signal-combination path

In `signal_processor.process()` (or wherever the aggregation happens), add a pre-aggregation filter:

```python
def _check_confidence_gate(self, raw_scores: Dict[str, float]) -> bool:
    """Return True if at least n_threshold edges agree on direction."""
    if not self.confidence_gate.enabled:
        return True  # passthrough — current behavior
    long_count = sum(1 for s in raw_scores.values() if s > 0)
    short_count = sum(1 for s in raw_scores.values() if s < 0)
    return max(long_count, short_count) >= self.confidence_gate.n_threshold
```

Wire so that when the gate fails, the per-ticker aggregate signal becomes 0 (no trade) instead of being passed through to risk engine.

### 3. A/B harness validation

Run 3 reps × 5 years × 3 arms = 45 backtests:

- **Arm 0**: enabled=False (current weighted_sum, baseline)
- **Arm 1**: enabled=True, n_threshold=2
- **Arm 2**: enabled=True, n_threshold=3

Substrate-honest universe. Cockpit-fixed metrics. Bootstrap CI per CLAUDE.md 6th non-negotiable. MBL check per CLAUDE.md 7th.

### 4. Report

Per-arm:
- Mean Sharpe + ci_low + ci_high
- Mean Sortino
- Max drawdown
- **Turnover** (most important — expect material reduction at N≥2/N≥3)
- **Trade count** (expect 60-75% reduction at N≥3)
- Per-year breakdown
- FF5+Mom α t-stat (must stay below or near 0 — we're not claiming alpha)

Plus per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe.

### 5. Audit doc

`docs/Audit/confidence_gated_execution_2026_05_12.md`:
- Theory + N-of-K diagnostic citation
- A/B grid output
- **Cost-adjusted Sharpe lift** (expected: N≥2 ≈ +0.05 to +0.15 from reduced turnover; N≥3 may be neutral due to small-n)
- Verdict: does turnover reduction translate to Sharpe lift?
- Recommendation: enabled flag flip OR not, with rationale

---

## Acceptance

1. **`ConfidenceGateConfig` + gate logic** in signal_processor.py, defense-first default `enabled=False`
2. **A/B harness** runs 3 reps × 5 years × 3 arms (45 backtests). Substrate-honest, cockpit-fixed metrics.
3. **Output table** with Sharpe + ci_low + Sortino + MDD + turnover + trade-count per arm.
4. **Tests** in `tests/test_confidence_gated_execution.py`:
   - `test_gate_disabled_passthrough` — enabled=False produces identical output to current weighted_sum
   - `test_n_threshold_2_filters_correctly` — synthetic 1-edge-firing bar gets filtered; 2-edge-agreeing bar passes
   - `test_n_threshold_3_filters_correctly` — same shape
   - `test_disagreement_kills_signal` — long_count == short_count → gate fails regardless of n_threshold
   - `test_turnover_reduction_at_higher_threshold` — synthetic substrate, gate ON reduces total trades by ≥40%
   - `test_a_b_determinism` — 3-rep bitwise canon md5 invariant within each arm
5. **Audit doc** with bootstrap CI per Sharpe + cost-adjusted Sharpe analysis + verdict.
6. **State doc updates**: forward_plan, lessons_learned (compound signal vs compound alpha distinction).
7. **Branch:** `feature/confidence-gated-execution`. Push only; director merges.

---

## Hard constraints

- DO NOT change current weighted_sum aggregation behavior when `enabled=False`. Pure additive layer.
- DO NOT enable by default. Defense-first; director flag-flip post-A/B if Sharpe lift materializes.
- DO NOT skip the A/B harness. Per CLAUDE.md: this is a Sharpe-modifying dispatch; lift must be measured.
- DO NOT use look-ahead in direction determination. `raw_score` is the per-bar output of each edge; sign is computed from CURRENT-bar score only.
- Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe.
- Per CLAUDE.md 7th non-negotiable: MBL check given honest N (T-057 adds 3 more N_trials to the substrate-honest pool — document).

---

## Time budget

- Implementation (config + gate wiring): ~1-2 hr
- A/B harness run: ~3-4 hr (45 backtests at vectorized speed)
- Tests: ~1-2 hr
- Audit doc: ~1-2 hr
- **Total: 6-8 hr**

---

## Open questions for implementing agent (surface in audit doc)

1. **Should the gate apply at the per-ticker or portfolio level?** Per-ticker (default): each (date, ticker) bar evaluated independently. Portfolio level would be a much different beast (aggregate across all tickers that day → would essentially never trade since cross-ticker agreement is rare). Recommend per-ticker.

2. **What about disagreement bars (long_count == short_count)?** Gate fails (no trade). Current weighted_sum would have produced a near-zero aggregate signal anyway. Recommend explicit no-trade.

3. **Does the gate apply to soft-paused edges?** Per the 0.25× soft-pause convention: count a soft-paused edge as a "half-edge" for direction-counting purposes? Or full edge? Recommend full edge (the gate is about signal agreement, not capital allocation). Document.

4. **What's the expected outcome on alpha t-stat?** The N-of-K diagnostic showed alpha t-stat goes MORE negative with higher N (Beta_Mom rises). T-057 should report this and confirm — we are NOT claiming alpha; we're claiming Sharpe-restructuring via better factor exposure delivery + lower turnover.

5. **Should T-057 also test n_threshold=4 or n_threshold=5+?** N-of-K diagnostic showed CIs too wide at n≥4 due to small samples. Recommend 3-arm A/B (0/2/3) only; defer wider sweeps to T-057b if 0/2/3 shows clear winner.

---

## Forward-look (after T-057 lands)

**If A/B shows Sharpe lift > +0.10 from confidence-gating at N≥2:**
- T-057b: flag-flip `enabled=True` (defense-first dispatch, propose-first)
- Stacks with T-055 vol-targeting (orthogonal layers); combined lift could reach +0.20-0.40 Sharpe
- This becomes part of the "bones perfection" delivery story

**If A/B shows no lift or negative:**
- Document the falsification
- Don't enable
- Update lessons_learned: per-bar signal does NOT translate to portfolio Sharpe at this substrate
- Confirms the architectural thesis is upper-bounded by substrate efficiency

**Either outcome is informative.** Per the user's "bones must be PERFECT" directive: shipping the test + documenting the result is the work, not the outcome.

---

## Director note

T-057 is the third Sharpe-restructurer in flight (alongside T-055 vol-targeting and the Engine F lifecycle factor-α gate). All three are NOT alpha-finders. Per the research convergence: bones-perfection means efficient factor exposure delivery, since idiosyncratic α has not yet been found on the S&P 500 substrate.

If the user re-engages on data spend (Norgate / T-056 / T-050), this changes — different substrate may have actual α. Until then, the bones-completion track is the path.
