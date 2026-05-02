---
name: Wash-sale gate is regime-conditional, not regime-invariant — 2025 +0.670 lift FALSIFIED on 2021 (-0.966)
description: 2026-05-02 multi-year verification on prod-109. The +0.670 pre-tax Sharpe lift from wash-sale gate (memory project_wash_sale_exposes_turnover_bug_2026_05_02.md) does NOT generalize. 2021 result is -0.966 (gate hurts by nearly a full Sharpe point in trending bull markets). Recommendation: do NOT flip wash_sale_avoidance.enabled to default-on.
type: project
---

**The data (verification under scripts/wash_sale_multi_year.py, prod-109, cap=0.20, ML off):**

| Year | Cell A (wash_sale OFF) Sharpe | Cell B (wash_sale ON) Sharpe | Δ (B − A) |
|---|---:|---:|---:|
| 2021 | **1.666** | **0.700** | **−0.966** |
| 2022 | 0.583 | INTERRUPTED | — |
| 2025 (prior round ref) | 0.954 | 1.624 | +0.670 |

Full report: `docs/Audit/wash_sale_multi_year_verification_2026_05.md` on
branch `wash-sale-multi-year-verify`.

**Why this matters as an Edge Analyst lesson:**

1. **The original 2025 finding was real but not generalizable.** It was
   observed under a single-year window in a specific regime
   (moderate-vol mixed market with high turnover-quality issues). The
   turnover-quality bug it surfaced IS real (per the original memory's
   22% buy-block rate), but the GATE'S RESPONSE is not regime-invariant.
   In trending bull years the gate's myopic blocking destroys far more
   value than it preserves.

2. **A +0.670 Sharpe lift on 1 year is NOT statistical evidence.** It
   was provisionally recommended as default-on flip after 1-year
   observation. The cross-regime swing measured here is 1.636 Sharpe
   points (from -0.966 in 2021 to +0.670 in 2025). That magnitude
   overwhelms ANY single-year effect estimate. **Single-year Sharpe
   effects are not policy evidence on this universe.**

3. **The gate's myopia is the structural problem.** It blocks ALL
   re-buys within 30 days regardless of: (a) whether price has moved
   favorably since the loss exit, (b) whether the new signal is from
   a different uncorrelated edge, (c) whether market regime has changed.
   Each of these failure modes is more costly in trending markets and
   less costly in chop.

4. **A regime-conditional version is the natural follow-on.** The
   gate could be activated conditionally on realized vol percentile
   or HMM regime state. This might preserve the +0.670 lift in
   chop/2025-like conditions without the −0.966 drag in 2021-like
   trends.

**Common-overfitting-pattern warning for future Edge Analyst work:**

This is a textbook example of "single-year cell looks great, falls
apart cross-regime." The pattern to watch for:
- A new module/edge ships with default-OFF
- Smoke-test on 1 OOS year shows large positive effect
- "Recommended as default-on candidate" → user goes to flip it
- Multi-year verification before flip catches the regime-conditionality
- If verification HAD been skipped, the system would now have a
  default-on module that destroys alpha in 2 of 5 years

The discipline is "verify across regimes BEFORE flipping default-on,
even when the single-year effect is large."

**For Engine F (governance) eventual lifecycle work:**
- Wash-sale gate should NOT be on the default-on edge list.
- It MAY be a candidate for regime-conditional weighting (analogous
  to how Engine A edges have regime-conditional affinity multipliers).
- A "regime-aware risk constraint" mechanism doesn't currently exist
  in Engine B — that's a future architectural item.

**Connection to other memories:**
- `project_wash_sale_exposes_turnover_bug_2026_05_02.md` — the original
  finding this verification falsified.
- `project_low_vol_regime_conditional_2026_04_25.md` — same pattern at
  the edge level (low_vol_factor_v1 had +0.23 Sharpe in-sample driven
  by 2022 bear, dragged in bull windows). Same "regime-conditional alpha
  needs composition-layer" architectural gap.
- `feedback_no_overfitting.md` — the verification IS the overfitting
  guard the project demands.
