---
title: Honest-N + MBL computation — the data window is the binding constraint
date: 2026-05-12
author: director (post-research-synthesis, Phase 0 follow-up)
data_source: trade_logs directory count + run registry + task ledger reconstruction
status: director-side analysis (no agent dispatch); confirms metrics-dive prediction
gate_decision: 5-year window MATHEMATICALLY INSUFFICIENT for DSR validation at corrected baseline
---

# Honest-N + MBL Computation

## TL;DR — the data window cannot validate the corrected baseline

The 2026-05-16 metrics research dive specified a load-bearing formula:

> **MBL_years ≈ 2 · ln(N_effective) / SR_target²**
>
> "5-year daily backtest with ~50 effective trials needs annualized SR ≈ 1.2 just to clear DSR null; most retail 'Sharpe 1' backtests fail."

Applied to our project's actual N_trials accumulated on the substrate-honest 5-year window:

| Honest N estimate | SR target = 0.598 (corrected baseline) | SR target = 1.0 | SR target = 1.2 |
|---|---|---|---|
| **N=26 (low)** | MBL **18.2 yr** (deficit +13.2) | MBL **6.5 yr** (deficit +1.5) | MBL **4.5 yr** (covered) |
| **N=52 (mid)** | MBL **22.1 yr** (deficit +17.1) | MBL **7.9 yr** (deficit +2.9) | MBL **5.5 yr** (deficit +0.5) |
| **N=100 (high — see below)** | MBL **25.7 yr** (deficit +20.7) | MBL **9.2 yr** (deficit +4.2) | MBL **6.4 yr** (deficit +1.4) |
| **N=1000 (alternative-history)** | MBL **38.6 yr** (deficit +33.6) | MBL **13.8 yr** (deficit +8.8) | MBL **9.6 yr** (deficit +4.6) |

**At our corrected 0.598 baseline, no realistic honest-N estimate gives the 5-year window enough power for DSR validation.** Even at SR=1.0 (a hypothetical engine-completion lift), we're still under-powered at all honest-N estimates ≥26.

**The multi-decade backtest extension is no longer optional. It is the precondition for any deployment decision.**

## Honest-N estimation methodology

Direct on-disk count of `data/trade_logs/` directories: **365 directories**. This is total RUNS (each run gets a UUID), not distinct CONFIGURATIONS.

### Why "configurations" matters, not "runs"

A typical measurement campaign uses 3 reps × 5 years = 15 runs per configuration. The metrics dive's N_trials counts distinct configurations (where each is an independent test of the hypothesis), not raw run count.

Naive run-to-config ratio of 15× gives: 365 / 15 ≈ **24 substrate-honest configurations on disk**.

But this undercounts because:

1. **Trade logs rotate.** Older runs from 2026-04 (governor-shift A/B era) were rotated out before today's Phase 1 disk cleanup. The on-disk 365 reflects ~last 30 days only.
2. **Aggregator-iteration trials are silent.** MetaLearner variants (6+ attempts), HRP slices (3 variants), Engine D Discovery cycles (T-021, T-025, T-026) each contribute to N_trials per the dive's "Every linear-vs-nonlinear A/B test you run on the same data adds to N_trials."
3. **Pre-substrate-honest configurations** are still in the trial budget because the same trade data was repeatedly evaluated.

### Reconstruction from task ledger

Counting distinct T-XXX measurement configurations across the project arc:

| Era | Approx config count |
|---|---|
| Pre-substrate governor-shift A/B (2026-04) | 25-30 |
| Substrate-honest era (2026-05) | 20-30 |
| Aggregator iteration (MetaLearner × N, HRP × 3, Discovery cycles × 3) | 10-15 |
| Hidden trials (parameter sweeps, smoke tests not formally recorded) | 10-25 |
| **Total honest-N estimate** | **65-100** |

I'll use **N_honest = 75** as the working midpoint.

### MBL at N=75 and our actual Sharpe levels

| Reference Sharpe | MBL at N=75 | Our window (5 yr) | Verdict |
|---|---|---|---|
| **0.598** (corrected baseline) | **24.1 yr** | 5 yr | **+19.1 yr deficit** |
| 1.0 (hypothetical engine-completion lift) | 8.6 yr | 5 yr | +3.6 yr deficit |
| 1.2 (the dive's "barely clears DSR" reference) | 6.0 yr | 5 yr | +1.0 yr deficit |
| 1.5 (engineering-best-case) | 3.8 yr | 5 yr | **covered** |

**Only at SR ≥ 1.5 do we have enough data.** Our corrected baseline is 0.598. The gap is structural.

## What this means concretely

### 1. The 0.598 baseline cannot clear DSR on this data window

This was already implicit in the 7/11 UNIFORMLY NEGATIVE factor-α finding (low or negative α t-stats correspond mechanically to low Sharpe). The MBL math now makes it explicit: even if the corrected raw Sharpe were 1.0 instead of 0.598, the 5-year window is still under-powered given N_trials. **The 7/11 negative finding is partially a measurement-power finding, not just an alpha-absence finding.**

### 2. Engine completion's projected lift doesn't fix this alone

The forward_plan's engine-completion lift estimate is +0.55 to +1.25 Sharpe. If realized, the post-completion Sharpe is ~1.0-1.8. At N=75:

- 1.0: still under-powered by 3.6 yr
- 1.5: just barely covered (deficit 0)
- 1.8: covered

**Only the optimistic end of engine completion's projected lift clears the data-window bar.** And that's IF the lift compounds with the existing baseline; if engine completion only delivers factor-replication efficiency (per the research convergence: "engine completion delivers factor exposure efficiently, not alpha discovery"), the post-completion Sharpe stays in the under-powered band.

### 3. The multi-decade extension is now load-bearing

Going from 5 → 10 years of substrate-honest data changes the math dramatically:

| Window | Required SR to clear MBL at N=75 |
|---|---|
| 5 yr | 1.55 |
| 10 yr | 1.10 |
| 15 yr | 0.89 |
| 20 yr | 0.78 |
| 25 yr | 0.70 |

At 10-year window, we'd need SR ≥ 1.10 — well within the "engine completion + non-factor edges" target range. **Doubling the data window halves the required Sharpe-validation bar.**

The first alpha dive specifically recommended "extend the backtest history on factor edges to 1962+" — that gives ~63 years, requiring only SR ≥ 0.46 to clear MBL at N=75. **Our corrected 0.598 baseline would clear DSR on a 1962+ substrate.**

This is why all three research dives independently pointed at the multi-decade extension as the binding constraint.

### 4. Honest-N also rises with every future trial

Each future measurement adds to N_trials. If we run another 25 measurements over the next 3 months, N rises to 100, and MBL at SR=1.0 rises from 8.6 yr to 9.2 yr. **The data deficit grows faster than the data window does.** Future measurement campaigns should be PRE-REGISTERED and few, not exploratory and many — to keep N from inflating.

### 5. The "deflate Sharpe by 35-58%" McLean-Pontiff prior compounds the problem

Even if we somehow validated a Sharpe of 1.5 on this data, the McLean-Pontiff publication-decay haircut suggests we should deploy at 50% of in-sample → expected 0.75 live Sharpe. Combined with the MBL under-power finding, **the deployment-ready Sharpe target is materially higher than the engineering-best-case projection.**

## Forward actions

### Immediate (queue NOW)

1. **Update CLAUDE.md** — add Gate 0 to the validity gauntlet:
   > **0. MBL check.** Before any backtest is accepted as evidence: verify T_years ≥ 2·ln(N_effective)/SR_target². If the window is shorter than MBL given honest N, the backtest is mathematically guaranteed to overfit. Honest N includes every distinct backtest configuration ever run on the same data substrate, including aggregator-iteration trials.

2. **Pre-register every future measurement** — write the hypothesis + threshold + N_trials_consumed BEFORE running. Counter the "add another aggregator A/B until something agrees" trap that all four research dives warn against.

3. **Treat the 5-year window as exploratory only.** Until the multi-decade extension lands, NO measurement on the 5-year substrate-honest window should be quoted as evidence for deployment. Headlines should explicitly cite the under-powered status.

### Medium-term (queue for user decision)

4. **Multi-decade backtest extension** (T-050 candidate): rebuild the substrate-honest universe back to at least 1990, ideally 1962. This requires either:
   - Norgate Data subscription ($80/mo, survivorship-bias-free back to ~1990 for most universes) — recommended
   - CRSP Standard (academic-tier, ~$5K/yr) — overkill for retail
   - DIY back-extension via EDGAR + delisting databases — multi-month engineering project, not recommended

5. **PBO via CSCV** alongside DSR (T-051 candidate): non-parametric overfitting check independent of normality assumptions. Python `pypbo`. Should be a Gate 8b alongside the current DSR Gate 8.

6. **Lo η(q) autocorrelation correction on all reported Sharpes**: per the metrics dive, hedge-fund Sharpes are overstated ~65% when ρ₁ ≈ 0.34 is ignored. Our daily-bar equity Sharpes are likely inflated 10-30%. Pre-register the correction before applying.

### Forward implication for the project narrative

The forward_plan's "engine completion delivers projected +0.55 to +1.25 Sharpe lift" framing needs an MBL caveat:

> "Engine completion's projected Sharpe lift is on the order of 0.55-1.25. However, the 5-year substrate-honest data window combined with ~75 accumulated N_trials means MBL ≈ 8.6 years even at the optimistic SR=1.0 end of that range. **Engine completion lift alone does not resolve the under-power problem. Multi-decade backtest extension is required before any post-completion Sharpe is treated as deployment evidence.**"

## TL;DR (operational)

- **Honest N ≈ 75** distinct backtest configurations accumulated on the substrate-honest 5-year window.
- **MBL at N=75 and SR=1.0 is 8.6 years.** We have 5.
- **Even at SR=1.5 (engineering best case), MBL is 3.8 years — just barely covered.**
- **The corrected 0.598 baseline cannot clear DSR on this data window.** Not a measurement-discipline failure — a data-window failure.
- **The multi-decade backtest extension is the load-bearing precondition for any deployment decision.** Most cost-effective vehicle: Norgate Data $80/mo.
- **CLAUDE.md should add Gate 0 (MBL check)** to the validity protocol.

## Files

- Input: `data/observability/run_registry.sqlite` (125 runs, 24-hr snapshot) + `data/trade_logs/` (365 dirs) + task ledger reconstruction
- This audit: `docs/Audit/honest_n_mbl_computation_2026_05_12.md`
- Cited research: `docs/Sources/Metrics/Retail-algo-metrics.md` §2.3 ("Minimum Backtest Length")
- Companion analysis: `docs/Audit/pairwise_signal_correlation_phase0_2026_05_12.md` (committed earlier this session)
