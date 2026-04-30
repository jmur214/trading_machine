# Phase 2.10d Task C — 2025 OOS rerun (post-fix)

**Date:** 2026-04-30
**Branch:** main (director run)
**Run UUID:** `d7ae1ca3-3771-4366-a8a8-c46f6907ff50`
**Result file:** `data/research/oos_validation_q1.json`

## Setup

Same as Phase 2.10b Q1 anchor (UUID `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`):
- Window: 2025-01-01 → 2025-12-31
- Universe: prod 109 tickers
- Cost model: `RealisticSlippageModel` (ADV-bucketed half-spread + Almgren-Chriss impact)
- Governor: `--reset-governor`

The only changes between the Q1 anchor and this run are the Phase 2.10d
structural fixes that landed on main between 2026-04-29 and 2026-04-30:

**Lifecycle (Engine F) extensions** (commit `90ca570`):
- Zero-fill timeout trigger
- Sustained-noise trigger
- TierClassifier post-backtest scheduling
- Revival_veto for heavy losers (lifetime cumulative loss > 0.5%)

**Capital allocation primitives** (commits `c1732ac` + `292f2d7`):
- Primitive 1: per-bar fill-share ceiling at 25%
- Primitive 2: soft-pause weight ceiling clamp (regime_gate can no longer amplify paused edges)
- Primitive 3: regime-summary floor on `suggested_max_positions` (crisis → 5, stressed → 7)

## Result

| Metric | Q1 anchor (pre-fix) | Task C (post-fix) | Δ |
|---|---|---|---|
| Sharpe | -0.049 | **0.315** | **+0.364** |
| CAGR (%) | -0.43 | 1.41 | +1.84 pp |
| MDD (%) | -6.48 | -2.68 | +3.80 pp |
| Vol (%) | 5.65 | 4.86 | -0.79 pp |
| Win Rate (%) | 40.39 | 39.77 | -0.62 pp |
| Net Profit ($) | -428 | +1,406 | +1,834 |

**vs benchmarks (2025):**

| Reference | Sharpe | CAGR (%) | MDD (%) | Vol (%) |
|---|---|---|---|---|
| **System (post-fix)** | **0.315** | 1.41 | -2.68 | 4.86 |
| SPY | 0.955 | 18.18 | -18.76 | 19.52 |
| QQQ | 0.933 | 21.22 | -22.77 | 23.64 |
| 60/40 (SPY+TLT) | 0.997 | 12.93 | -11.34 | 13.08 |

System trails strongest benchmark (60/40 at 0.997 Sharpe) by **-0.682
Sharpe**. In CAGR terms the gap is much wider — system 1.41% vs SPY
18.18%.

## Pre-committed gate verdict

| Threshold | Verdict | This result |
|---|---|---|
| < 0.2 | Kill thesis | — |
| **0.2 - 0.4** | **Ambiguous. Fix worked partially. Phase 2.11 still blocked.** | **← lands here at 0.315** |
| 0.4 - 0.65 | Partial pass. Phase 2.11 becomes strategic next step. | — |
| > 0.65 | Full pass. Phase 2.11 + 2.12 unblock. | — |

**Bucket: AMBIGUOUS.** The +0.364 Sharpe lift is real and confirms the
structural-defect diagnosis was directionally correct. But absolute
return (1.41% CAGR) and risk-adjusted return (0.315 Sharpe) both
remain well below the levels the user's goals A and B require.

## Honest commentary

**What worked (validated by data):**
- Pruning + capital allocation fixes did exactly what the diagnosis
  predicted. The +$1,834 swing in net profit, the lower MDD (-6.48%
  → -2.68%), the lower vol (5.65% → 4.86%) — every metric moved
  in the predicted direction.
- The 04-30 reviewer's prediction ("expect Sharpe to rise from -0.049
  to +0.2 to +0.4 honestly") landed inside its own range at 0.315.
  Calibration was accurate.

**What didn't move enough:**
- Sharpe lift is +0.364 but absolute return is 1.41% in a year SPY
  made 18%. The system is now **defensive to a fault** — it captures
  less than 8% of SPY's return at less than 25% of SPY's vol. Goal A
  (compound at decent rate) and goal B (beat market significantly)
  both require materially more absolute return than this.
- The fix bounded the *downside* of the rivalry pathology. It didn't
  *unlock more upside* from the stable contributors. `volume_anomaly_v1`
  + `herding_v1` + 4 weak-positive diversifiers now have headroom to
  compound, but the linear allocator still can't allocate more
  capital to them dynamically when they fire.

**The reviewer's strategic framing reapplies:**
> "Phase 1.5's tactical fixes (pruning, regime caps) buy time. The
> meta-learner is the structural answer because it natively suppresses
> bad edges via negative SHAP weights — capital rivalry is a symptom of
> the linear allocator, and patching the linear allocator is rearranging
> chairs."

That's the literal interpretation of where we are. The chairs are now
arranged correctly. But we're in a smaller room than we want, and the
linear allocator can't push the chairs bigger.

## Three paths forward (director-level decision needed)

### Path 1 — Strict gate reading: keep diagnosing
Sharpe 0.315 < 0.4 → "more rivalry/dilution diagnosis needed" per the
pre-committed table. Don't ship the meta-learner yet; find a different
structural lever first.

**Argument for:** the gate was pre-committed. Honoring it preserves the
no-goalpost-moving discipline.

**Argument against:** we've already measured the rivalry. The linear
allocator's ceiling is empirical now, not hypothetical. "More
diagnosis" likely produces the same answer.

### Path 2 — Strategic gate reading: ship the meta-learner (Phase 2.11)
The 04-30 reviewer explicitly framed the meta-learner as the
structural answer the linear allocator can't solve. Tactical fixes
were necessary but not sufficient. 0.315 Sharpe with +0.364 lift is
plausible launch-pad for the meta-learner; per-ticker training under
clean data (post-Phase-2.10d) should push the system materially
higher.

**Argument for:** consistent with the latest reviewer's strategic
framing. The chairs-are-rearranged-correctly state is the precondition
for the meta-learner to learn from clean data.

**Argument against:** we're still below the 0.4 threshold.
Pre-commitment said "Phase 2.11 still blocked" at 0.2-0.4.

### Path 3 — Tactical recalibration: loosen the caps, re-run
Primitive 1's 25% fill-share cap may be too tight on a stack with only
6-7 active edges (cuts in 99.5% of entry-days). Try 0.35 or 0.40 and
re-run 2025 OOS. Engine E's `crisis_max_positions=5` may be too
restrictive given the 25% fill-share already constrains rivalry from
another angle. **The system is structurally underleveraged; the caps
that fixed rivalry now starve the good edges.**

**Argument for:** addresses the absolute-return concern directly. The
defensive-to-a-fault profile is the real obstacle to goals A and B.

**Argument against:** loosening risks reintroducing rivalry. Need to
prove the autonomous lifecycle would still cleanly identify and pause
losers under looser caps before claiming this works.

## Recommendation

This is your call. My read: **Path 2 + parts of Path 3.** Ship the
meta-learner as the structural answer (it's been ready to ship since
Phase 1, just blocked on data quality). Concurrently, loosen
Primitive 1 modestly (0.25 → 0.35) since the autonomous lifecycle
triggers can now catch noise edges that emerge from the looser cap.
Re-test the combination.

But I won't make that call autonomously. The pre-committed gate said
0.2-0.4 means Phase 2.11 stays blocked, and I owe you the literal
reading first. Tell me which path to take.
