# FF5+Mom α t > 2 Threshold Calibration Analysis

**Date:** 2026-05-11
**Author:** Director-side analysis (no agent dispatch; pure post-processing on T-004 + T-020 outputs)
**Question:** Today's universal pattern is 0/11 edges clear FF5+Mom α t > 2 on substrate-honest substrate (T-004 0/6 actives + T-020 0/5 new paused). **Is the t > 2 threshold inherently incompatible with retail-scale substrate-honest universes, or is the bar correctly calibrated and the edges genuinely lack idiosyncratic α?**

This is **not** a goalpost-moving exercise — no Sharpe-claim decision is in flight; it's a calibration sanity check.

---

## Method

For each of the 11 edges tested (6 actives from T-004 + 5 new paused from T-020), extract from the existing factor-decomp JSON:
- `n_obs` (attribution-stream length in days)
- `alpha_annualized` (point estimate, %)
- `alpha_se_annualized_hac` (Newey-West HAC standard error)
- `alpha_tstat_hac` (point estimate ÷ HAC SE)

Then compute the implicit threshold: **`α_needed_for_t>2 = 2 × SE_α_annual`** — the minimum α magnitude that would clear t > 2 given each edge's actual SE on this window.

Reference: a +2% annualized α-needed bar is well within reach for any published-academic momentum/value/quality strategy (most claim +3-5% post-cost). A +5% bar would be borderline-unattainable for retail-scale work. **The α_needed_for_t>2 distribution tells us where we sit.**

---

## Results

| Edge | n_obs | α_annual | SE_α_ann (HAC) | t_stat | **α_needed_for_t>2** | Source |
|---|---:|---:|---:|---:|---:|---|
| short_term_reversal_v1 | 1019 | +3.39% | +1.93% | **+1.76** | +3.85% | T-020 |
| pairs_trading_MA_V_v1 | 62 | +17.97% | +12.75% | +1.41 | +25.51% | T-020 (n very small) |
| dividend_initiation_drift_v1 | 158 | +22.22% | +18.56% | +1.20 | +37.12% | T-020 (n very small) |
| volume_anomaly_v1 | 268 | +0.80% | +0.97% | +0.83 | +1.95% | T-004 active |
| momentum_12_1_v1 | 1041 | +0.74% | +2.08% | +0.36 | +4.15% | T-020 |
| gap_fill_v1 | 243 | -0.05% | +1.22% | -0.04 | +2.43% | T-004 active |
| momentum_6_1_v1 | 1054 | -2.02% | +2.01% | -1.01 | +4.02% | T-020 |
| value_book_to_market_v1 | 648 | -2.20% | +0.84% | **-2.60** | +1.69% | T-004 active |
| accruals_inv_sloan_v1 | 675 | -3.54% | +0.87% | **-4.08** | +1.73% | T-004 active |
| accruals_inv_asset_growth_v1 | 472 | -3.74% | +0.73% | **-5.12** | +1.46% | T-004 active |
| value_earnings_yield_v1 | 689 | -3.97% | +0.70% | **-5.69** | +1.39% | T-004 active |

**Headline numbers:**

- **α_needed_for_t>2 range:** +1.39% (`value_earnings_yield_v1`) → +37.12% (`dividend_initiation_drift_v1` due to n=158 trades).
- **Median α_needed_for_t>2 across the 11 edges:** ~+2.4% annualized (or ~+2.0% if you exclude the two micro-n edges).
- **Edges with t > +2 (significantly POSITIVE α):** **0/11**
- **Edges with t < -2 (significantly NEGATIVE α):** **4/11** — all in the value/accruals cluster
- **Closest-miss to t > +2:** `short_term_reversal_v1` at t=+1.76 (α=+3.39%, needs +3.85%; 0.46% short)
- **High-α / low-n edges flagged for re-measurement at larger n:** `pairs_trading_MA_V_v1` (α=+17.97%, n=62), `dividend_initiation_drift_v1` (α=+22.22%, n=158)

---

## Verdict

**The FF5+Mom α t > 2 threshold is correctly calibrated for the 5-year substrate-honest window.** A +2% annualized α bar is reachable for any genuinely α-producing retail strategy. Documented academic momentum strategies typically claim +3-5% α post-cost (Jegadeesh-Titman 1993, Asness et al. 2013). The threshold is consistent with these expectations.

**The project's 0/11 t > 2 outcome reflects that the edges genuinely lack idiosyncratic α on this substrate.** Raw Sharpe is Mkt + Mom factor exposure paid for at slight execution-cost premium. This is not a discipline-framework failure; it's the discipline framework working as designed and surfacing an honest finding.

**More striking: 4 of 6 ACTIVE edges have statistically significant NEGATIVE α (t < -2):**

- `value_earnings_yield_v1`: α=-3.97%, t=-5.69 (n=689)
- `accruals_inv_asset_growth_v1`: α=-3.74%, t=-5.12 (n=472)
- `accruals_inv_sloan_v1`: α=-3.54%, t=-4.08 (n=675)
- `value_book_to_market_v1`: α=-2.20%, t=-2.60 (n=648)

These edges aren't just failing to add α — they're **actively destroying value** versus a passive factor-ETF holding. Each one is paying ~3-4% of annualized return in execution costs to buy systematic factor exposure that factor ETFs sell cheaper. **The value/accruals cluster is a documented retail-substrate failure**, not just an "unable to find α" case.

---

## Implications

### Lifecycle action recommendation

The 4 negative-t-stat active edges should be flagged for autonomous lifecycle review. They each satisfy:
- Statistically significant α < 0 (t ≤ -2.60)
- Multi-year evidence (n_obs ≥ 472 attribution days)
- Same direction across multiple factor models would be the next check

**Recommendation: surface to the Engine F lifecycle_manager for explicit retirement evaluation** on next Discovery/lifecycle cycle. CLAUDE.md prohibits manual edge tuning, but the lifecycle gauntlet (per `engines/engine_f_governance/lifecycle_manager.py:66` and the T-010 CI-aware update) IS the legitimate path: edge_ci_low < benchmark_sharpe - 0.3. Given factor-adjusted α is significantly negative, lifecycle should naturally retire on the next cycle. **Worth a director-side spec for an explicit `lifecycle_with_factor_adjusted_check` follow-up dispatch.**

### Closest-miss promote-candidates

`short_term_reversal_v1` (t=+1.76, gap 0.46% short of bar):
- 2022 zero-Sharpe cell in T-020 is suspicious — could be a 2-3 rep determinism artifact, OR genuine regime-conditional behavior
- Worth a focused 2-3 rep re-measurement on a sub-universe (excluding 2022 if regime-specific) to see if cleaner stats push t > 2

`pairs_trading_MA_V_v1` (α=+18%, t=+1.41 limited by n=62):
- Real positive α magnitude
- Constrained by trade frequency, not by α signal
- Adding 5-10 more cointegrated pairs (T-019 candidate-pool expansion) would tighten SE substantively

### Threshold stays as-is

No change to the t > 2 gate. The discipline framework is doing its job.

---

## What this changes for the engines-first directive

The reframe sharpens: **edge expansion's projected +0.1 to +0.3 Sharpe lift (per dev review) requires edges with genuinely positive idiosyncratic α at the +1-2% annualized scale.** None of today's 11 edges meet that bar. The structural fixes still apply:

- **T-022 (gene-encoding extension)** — gives Discovery's GA access to the expanded vocabulary; chance of finding edges with real α
- **T-023 (Gate 1 caching)** — makes the search tractable at cap=30+
- **Lifecycle retirement of the 4 negative-α edges** — even before new α is found, retiring negative-α edges should lift the ensemble Sharpe by removing the drag

Engine B portfolio vol-targeting remains on hold. Multiplying a selection-dominant signal whose underlying α is factor-exposure (not idiosyncratic) lifts nothing — confirmed by today's threshold-calibration result.

---

## Open questions for future work

1. **Survivorship in the value/accruals factor data.** FF5 factor returns from Ken French's database use CRSP universe; the substrate-honest 109-name universe may interact with HML/RMW/CMA differently than Fama-French's full CRSP. Could the negative t-stats be partly a substrate-mismatch artifact? Probably not (would expect random-direction noise, not 4/4 in same direction at t < -2.6 to -5.7) but worth a sensitivity check.
2. **Strategy capacity scaling.** Newey-West HAC SE is shrinking with √n. At larger n (e.g., 10-year window vs 5-year), the bar lowers. The 5-year window is constrained by the project's substrate-honest start (2021 post-missing-CSV closure). Re-measuring on a hypothetical 10-year window (when more data is available) would lower the +2% bar to ~+1.4%.
3. **Per-regime factor decomp.** The 4 negative-α edges may have regime-conditional behavior — e.g., positive α in bull markets, negative in bear, net negative averaged. The T-020 closest-miss flag on STR's suspicious 2022 zero-Sharpe cell hints at this pattern. Worth ~3-4 hr per-regime decomp on a future cycle.
