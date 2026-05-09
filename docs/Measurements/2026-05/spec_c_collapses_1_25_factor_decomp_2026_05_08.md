# Spec — C-collapses-1.25: Factor Decomp on `volume_anomaly_v1` Under Substrate-Honest Universe

**Date drafted:** 2026-05-08
**Status:** SPEC for approval. Sequenced AFTER `spec_substrate_honest_remeasurement_2026_05_08.md` Arm 1 completes.
**Will be executed by:** Agent A or B once approved (~3-4 hr).
**Output:** `docs/Measurements/2026-05/c_collapses_1_25_factor_decomp_verdict_2026_05_08.{md,json}`

---

## Why now

Original framing (R1+R2 audit week of 2026-05-06): the two t > 4 alphas (`volume_anomaly_v1` and `herding_v1`) survived FF5+Mom factor decomposition with statistically significant alpha. But that was on the **survivorship-biased static-115 universe**. The question: do they still produce t > 2 alpha on the substrate-honest universe?

**Scope correction (2026-05-08):** `herding_v1` is currently `status='paused'` in `edges.yml`. The dev review noted "rescope as needed." So this spec narrows to **`volume_anomaly_v1` only** — the one t > 4 alpha that's still in the active 6 and carries 93.8% of ensemble PnL per `per_edge_contribution_2026_05_08.md`.

If `volume_anomaly_v1` does NOT survive at t > 2 on the substrate-honest universe, the alpha thesis itself is in deeper question — the load-bearing edge is substrate-conditional. If it survives, that's the load-bearing-alpha-is-real result.

A secondary measurement: include the 4 surviving edges' attribution streams and check t-statistics on each. Tells us whether ANY of the 6 actives has substrate-honest alpha after factor adjustment.

---

## Method: Fama-French 5 + Momentum regression on per-edge attribution streams

For each edge in the active set, compute its **attribution stream** (the daily return contribution attributable to that specific edge) and regress it on FF5+Mom factors. The intercept is the edge's alpha; the t-statistic on the intercept tells us whether the alpha is significantly different from zero.

**Algorithm:**

1. **Compute per-edge attribution streams from the substrate-honest measurement's Arm 1 trade log.**
   - Use `core/per_edge_attribution.py` (or whatever module the existing tier_classifier uses) to construct daily PnL streams per edge.
   - If that module doesn't exist, derive: for each closed trade with `edge_id` matching, contribute its PnL to that edge's daily stream on the closure date.
   - Convert daily PnL → daily return: `ret_t = pnl_t / equity_t-1` where `equity_t-1` is the portfolio value the day before.
2. **Load FF5+Mom factor returns.** Use the same source `engines/engine_a_alpha/tier_classifier.py` uses. If unavailable on disk, document that and skip — don't fetch fresh data without explicit approval.
3. **Per-edge regression:**
   ```
   r_edge[t] - r_f[t] = α + β_MKT (r_MKT[t] - r_f[t]) + β_SMB SMB[t] + β_HML HML[t]
                       + β_RMW RMW[t] + β_CMA CMA[t] + β_MOM MOM[t] + ε[t]
   ```
   Standard OLS with HAC standard errors (Newey-West, lag = floor(4*(T/100)^(2/9)) — or use the same convention as the existing tier_classifier).
4. **Report α (annualized), t-statistic on α, R², factor loadings, sample size.**

---

## Reporting

### Per-edge factor decomp (priority order)

| Edge | Annualized α | t-stat (α) | R² | Survives t > 2? | Notes |
|---|---|---|---|---|---|
| volume_anomaly_v1 | | | | YES / NO | **Primary question** — load-bearing edge |
| gap_fill_v1 | | | | | |
| value_book_to_market_v1 | | | | | Value cluster |
| accruals_inv_sloan_v1 | | | | | Accruals cluster |
| value_earnings_yield_v1 | | | | | Net-drag edge per per_edge_contribution |
| accruals_inv_asset_growth_v1 | | | | | Net-drag edge per per_edge_contribution |

### Factor exposures table

For each edge, report β_MKT, β_SMB, β_HML, β_RMW, β_CMA, β_MOM with t-stats. Identifies whether the apparent alpha is just disguised factor exposure.

### Verdict framing

- **`volume_anomaly_v1` t(α) > 2 on substrate-honest**: the load-bearing alpha survives substrate change. Foundation gate is real. Deployment recommendations from substrate measurement carry weight.
- **`volume_anomaly_v1` t(α) ≤ 2**: load-bearing alpha is substrate-conditional. The 93.8%-of-ensemble-PnL contribution may have been a static-universe artifact. Reset deployment expectations; investigate before flipping flags from substrate measurement.
- **`volume_anomaly_v1` t(α) < 0 with material magnitude**: alpha REVERSED on substrate-honest. Major finding. Investigate immediately — might be a measurement bug, might be real and devastating.

For the other 5 edges:
- Tabulate which survive at t > 2 vs not. The surviving subset becomes the "factor-adjusted-real-alpha" candidate set for deployment.
- A 4-of-6 surviving result is consistent with the per-edge contribution finding (top 4 carry 99.5% of $-PnL); a 1-of-6 result would be a more concerning concentration signal.

### Caveats to document

- The attribution stream is approximate — assigning closed-trade PnL to a single `edge_id` ignores ensemble interaction (the closed trade was opened by a multi-edge consensus; attributing all PnL to one edge double-counts in the ensemble case). The convention here: use the trade's recorded `edge_id` (the dominant contributor at entry per signal_processor), accepting the ~10-15% noise from this attribution method.
- FF5+Mom factor data is monthly in many sources; daily factor returns require an alternate source. Document which source was used.
- 1-2 year sample is short for HAC inference; t-stats may be optimistic on a 5-year window. The regression handles this via Newey-West, but the implicit assumption is that the residual structure is stable.

---

## Hard constraints for the executing agent

- DO NOT modify Engine B or any other engine code.
- DO NOT run a new backtest — this is post-processing on the substrate Arm 1 trade log.
- Use `feature/c-collapses-1-25-factor-decomp` branch.
- Read inputs from `data/trade_logs/<arm1_run_id>/`; director provides UUID via inbox.
- If FF5+Mom factor data isn't on disk, write `BLOCKED — factor data missing` to the outbox; do NOT fetch fresh data.
- Push to feature branch only; director merges.

---

## Acceptance

- Audit doc + JSON written to `docs/Measurements/2026-05/c_collapses_1_25_factor_decomp_verdict_2026_05_08.{md,json}`
- Per-edge factor regression run for all 6 actives in the substrate Arm 1 trade log
- Verdict bucket selected for `volume_anomaly_v1` (the primary question)
- Survival t > 2 table populated for all 6 edges
- Reproducible: regression script committed; second run on same trade log produces bit-identical outputs

---

## Dependencies

- **Hard:** substrate-honest re-measurement Arm 1 must complete first.
- **Hard:** FF5+Mom factor data on disk. Existing tier_classifier likely has an established source — agent should reuse that path, not invent a new one.
- **Soft:** statsmodels (for OLS + HAC); pandas; numpy.

## Estimated runtime

~3-4 hr including audit doc + script + tests.
