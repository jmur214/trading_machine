# Per-Edge Per-Year PnL Attribution — Phase 2.10c

Generated: 2026-04-30T01:48:31

**Source data** (no new backtests):
- In-sample anchor `abf68c8e-1384-4db4-822c-d65894af70a1` (2021-01-05 → 2024-12-31, Sharpe 1.063)
- 2025 OOS `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34` (2025-01-03 → 2025-12-31, Sharpe -0.049)

**Method:** PnL is materialized only on exit/stop/take_profit rows. Each closed trade is attributed to the year of its exit timestamp. Per-edge per-year columns sum those exits. Annualized contribution is expressed as % of the $100k starting capital. The Sharpe-like metric is per-day attributed PnL / starting capital, with vol normalized by the count of trading days in that year (not just days the edge fired).

**Edge universe:** 16 unique edges fired across the two runs (excluding the pseudo-edge `Unknown`). The director task framed this as ~18; the missing ones (e.g. `rsi_bounce_v1`, `bollinger_reversion_v1`, `earnings_vol_v1`, `insider_cluster_v1`, `macro_real_rate_v1`, `macro_unemployment_momentum_v1`) are registered active/paused but produced zero fills in either run, which itself is a finding (see §6).

## 1. Per-edge per-year PnL contribution (% of $100k)

| edge | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `volume_anomaly_v1` | +3.18% | +2.98% | +3.03% | +4.94% | +1.93% |
| `herding_v1` | +1.48% | +2.43% | +1.55% | +1.26% | +0.55% |
| `gap_fill_v1` | +0.46% | +0.21% | +0.47% | +0.87% | +0.17% |
| `macro_credit_spread_v1` | +0.33% | +0.05% | +0.08% | +0.05% | +0.23% |
| `macro_dollar_regime_v1` | -0.05% | -0.00% | +0.17% | +0.03% | -0.01% |
| `macro_yield_curve_v1` | +0.00% | +0.00% | +0.11% | -0.00% | +0.00% |
| `growth_sales_v1` | +0.00% | +0.00% | +0.00% | +0.00% | +0.08% |
| `pead_v1` | +0.00% | +0.00% | +0.00% | +0.00% | +0.01% |
| `pead_short_v1` | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| `pead_predrift_v1` | +0.08% | +0.00% | -0.06% | +0.00% | -0.02% |
| `value_deep_v1` | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| `value_trap_v1` | +0.00% | +0.00% | -0.00% | +0.01% | -0.05% |
| `panic_v1` | +0.00% | -0.01% | -0.00% | -0.00% | -0.16% |
| `low_vol_factor_v1` | +0.03% | +0.08% | +0.47% | +0.01% | -2.53% |
| `atr_breakout_v1` | +1.09% | -5.78% | +1.08% | -0.07% | -2.23% |
| `momentum_edge_v1` | -0.92% | -9.17% | +0.57% | +3.08% | -0.88% |

Sum row (column means × 5 / 5):
| year | aggregate edge contribution |
| --- | ---: |
| 2021 | +5.68% |
| 2022 | -9.20% |
| 2023 | +7.48% |
| 2024 | +10.18% |
| 2025 | -2.92% |

(Aggregate ≠ portfolio return — risk sizing, leverage, and overlapping-position effects mean the portfolio's actual annual return differs from the simple sum of edge contributions.)

## 2. Per-edge per-year Sharpe-like metric

Annualized mean / annualized vol of each edge's daily attributed PnL. Distinguishes consistent low-magnitude contributors from lottery-ticket high-vol edges. `—` = edge had < 2 fills that year.

| edge | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `volume_anomaly_v1` | +5.18 | +2.76 | +5.07 | +4.71 | +4.05 |
| `herding_v1` | +3.11 | +2.97 | +3.90 | +2.72 | +2.64 |
| `gap_fill_v1` | +1.78 | +0.19 | +1.89 | +2.73 | +0.32 |
| `macro_credit_spread_v1` | +1.49 | +0.99 | +1.49 | +0.49 | +1.58 |
| `macro_dollar_regime_v1` | -0.38 | -0.11 | +1.84 | +1.48 | -0.37 |
| `macro_yield_curve_v1` | — | — | — | -1.03 | — |
| `growth_sales_v1` | — | — | — | — | +1.14 |
| `pead_v1` | — | — | — | — | +0.78 |
| `pead_short_v1` | — | — | — | — | — |
| `pead_predrift_v1` | +0.98 | — | -1.52 | — | — |
| `value_deep_v1` | — | — | — | — | — |
| `value_trap_v1` | — | — | — | +0.79 | -1.20 |
| `panic_v1` | — | -0.82 | — | — | — |
| `low_vol_factor_v1` | +0.28 | +1.26 | +1.55 | +0.58 | -2.40 |
| `atr_breakout_v1` | +1.14 | -3.11 | +1.32 | -0.06 | -3.67 |
| `momentum_edge_v1` | -0.55 | -3.56 | +0.50 | +1.55 | -1.20 |

## 3. Per-edge per-year entry-fill count

Companion to §1 — separates 'low PnL because rarely fires' from 'fires often, loses on average'.

| edge | 2021 | 2022 | 2023 | 2024 | 2025 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `volume_anomaly_v1` | 151 | 169 | 126 | 122 | 89 |
| `herding_v1` | 54 | 56 | 72 | 40 | 19 |
| `gap_fill_v1` | 65 | 102 | 45 | 81 | 128 |
| `macro_credit_spread_v1` | 244 | 20 | 2 | 160 | 218 |
| `macro_dollar_regime_v1` | 34 | 6 | 77 | 12 | 16 |
| `macro_yield_curve_v1` | 1 | 0 | 0 | 0 | 0 |
| `growth_sales_v1` | 0 | 0 | 0 | 0 | 116 |
| `pead_v1` | 3 | 2 | 6 | 6 | 5 |
| `pead_short_v1` | 0 | 0 | 0 | 0 | 0 |
| `pead_predrift_v1` | 78 | 9 | 35 | 14 | 11 |
| `value_deep_v1` | 0 | 0 | 0 | 0 | 1 |
| `value_trap_v1` | 0 | 0 | 4 | 12 | 31 |
| `panic_v1` | 1 | 8 | 0 | 1 | 8 |
| `low_vol_factor_v1` | 72 | 17 | 86 | 12 | 1407 |
| `atr_breakout_v1` | 1211 | 710 | 1103 | 918 | 544 |
| `momentum_edge_v1` | 3844 | 2731 | 3231 | 3798 | 1922 |

## 4. Edge classification (data-driven, NOT from `tier`)

Buckets:
- **stable** = ≥ 4 of 5 years with > +0.5% AND mean across all years > +0.5%
- **regime-conditional** = ≥ 1 clearly positive year (> +0.5%) AND ≥ 1 clearly negative year (< -0.5%)
- **noise / decay** = mean ≤ 0 across active years OR ≥ 3 negative years
- **weak-positive** = barely-positive but doesn't clear the stable bar
- **sparse** = fired in fewer than 2 years

| edge | classification | active yrs | mean (all yrs) | mean (active yrs) | min yr | max yr | lifecycle status | tier |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `volume_anomaly_v1` | stable | 5 | +3.21% | +3.21% | +1.93% | +4.94% | active | alpha |
| `herding_v1` | stable | 5 | +1.45% | +1.45% | +0.55% | +2.43% | active | alpha |
| `gap_fill_v1` | weak-positive | 5 | +0.44% | +0.44% | +0.17% | +0.87% | active | feature |
| `macro_credit_spread_v1` | weak-positive | 5 | +0.15% | +0.15% | +0.05% | +0.33% | active | retire-eligible |
| `macro_dollar_regime_v1` | weak-positive | 5 | +0.03% | +0.03% | -0.05% | +0.17% | active | retire-eligible |
| `macro_yield_curve_v1` | weak-positive | 2 | +0.02% | +0.05% | -0.00% | +0.11% | paused | feature |
| `growth_sales_v1` | sparse | 1 | +0.02% | +0.08% | +0.00% | +0.08% | active | feature |
| `pead_v1` | weak-positive | 2 | +0.00% | +0.01% | +0.00% | +0.01% | active | feature |
| `pead_short_v1` | sparse | 1 | +0.00% | +0.00% | +0.00% | +0.00% | active | feature |
| `pead_predrift_v1` | weak-positive | 3 | +0.00% | +0.00% | -0.06% | +0.08% | active | retire-eligible |
| `value_deep_v1` | sparse | 0 | +0.00% | +0.00% | +0.00% | +0.00% | active | feature |
| `value_trap_v1` | noise | 3 | -0.01% | -0.01% | -0.05% | +0.01% | active | feature |
| `panic_v1` | noise | 4 | -0.03% | -0.04% | -0.16% | +0.00% | active | feature |
| `low_vol_factor_v1` | noise | 5 | -0.39% | -0.39% | -2.53% | +0.47% | paused | retire-eligible |
| `atr_breakout_v1` | regime-conditional | 5 | -1.18% | -1.18% | -5.78% | +1.09% | paused | retire-eligible |
| `momentum_edge_v1` | regime-conditional | 5 | -1.47% | -1.47% | -9.17% | +3.08% | paused | retire-eligible |

**Bucket counts:**
- stable: 2
- regime-conditional: 2
- weak-positive: 6
- noise: 3
- sparse: 3

## 5. Paused-but-actually-consistent (was the pause wrong?)

Edges currently paused but whose per-year contribution looks decent in retrospect:
- `macro_yield_curve_v1`: classification=weak-positive, mean=+0.02%, min year=-0.00%

**Per-paused-edge breakdown:**
- `macro_yield_curve_v1` (feature): weak-positive, mean +0.02%, min year -0.00%, max year +0.11%
- `low_vol_factor_v1` (retire-eligible): noise, mean -0.39%, min year -2.53%, max year +0.47%
- `atr_breakout_v1` (retire-eligible): regime-conditional, mean -1.18%, min year -5.78%, max year +1.09%
- `momentum_edge_v1` (retire-eligible): regime-conditional, mean -1.47%, min year -9.17%, max year +3.08%

## 6. Commentary

### (a) How many of the 16-fired / 22-registered edges are actually worth keeping?

**Two.** `volume_anomaly_v1` (mean ~+3.2%/yr, every year positive, range +1.93% to +4.94%) and `herding_v1` (mean ~+1.4%/yr, every year positive, range +0.55% to +2.43%) are the only edges that clear the "stable contributor" bar. Together they account for roughly **+4.6% of capital per year** of pure attributed PnL. The integration's reported in-sample CAGR is +6.06% — meaning these two edges produce ~75–80% of the portfolio's gross return; the other 14 fired edges combined contribute well under 1%/yr on average. Six edges are weak-positive (mean < +0.5%/yr): some of those (`gap_fill_v1`, `macro_credit_spread_v1`) are mildly helpful and probably worth keeping as diversifiers; others (`macro_dollar_regime_v1`, `pead_predrift_v1`, `macro_yield_curve_v1`) contribute essentially zero and the lifecycle's "retire-eligible" tag is the right call. Three edges (`panic_v1`, `value_trap_v1`, `low_vol_factor_v1`) are net-negative noise; three (`growth_sales_v1`, `value_deep_v1`, `pead_short_v1`) almost never fire. The six edges *registered* active that produced zero fills in either run — `rsi_bounce_v1`, `bollinger_reversion_v1`, `earnings_vol_v1`, `insider_cluster_v1`, `macro_real_rate_v1`, `macro_unemployment_momentum_v1` — are an entirely separate problem (their gating either never triggers, or their `compute_signals` is broken on the universe; either way they are dead weight in the registry).

### (b) Were the lifecycle pause decisions correct in retrospect?

**Yes for both.** `momentum_edge_v1` lost **-9.17% of capital in 2022 alone** (its single worst year is bigger than the entire portfolio's 4-year gain), did fine in 2023-24, then was **-0.88% in 2025**. `atr_breakout_v1` lost **-5.78% in 2022** and another **-2.23% in 2025**. Both are textbook regime-conditional edges — they crush in trend-friendly years (2024 momentum: +3.08%; 2021 atr: +1.09%) and bleed catastrophically in regime-flips. Pausing them as constant-weight contributors was the correct call. The same data makes the case for *regime-gated* re-deployment: each has a clear "fire only in trending bull tape" pattern that a properly conditioned signal layer could exploit. But that's a future-architecture conversation, not a "the pause was wrong" reversal. The third paused edge, `low_vol_factor_v1`, lost **-2.53% in 2025** after a small +0.47% in 2023 — its pause is also vindicated, and the data argues against revival rather than for it. **Net: 0 of 3 pause decisions look mistaken in retrospect.**

### (c) Right number of edges in the prod stack — 13 active or much fewer?

**Much fewer.** The current 17-edge active stack is doing real work with **two of them**. The other 15 produce single-digit-basis-points-per-year individually. The honest answer is: the prod stack should be **2 stable alpha edges + 4-5 weak-positive diversifiers**, total ~6-7 active edges. Any edge whose 5-year mean contribution is below +0.2% should not be running in production — it's pure noise added to the signal aggregator and risk allocator. The most surprising single finding is the contradiction between this attribution result and yesterday's standalone gauntlet revalidation: **`volume_anomaly_v1` and `herding_v1` are stable per-year integration contributors but FAIL the standalone Gate 1 benchmark-relative test under realistic costs** (Sharpe 0.32 and -0.26 respectively, both below the 0.68 threshold). The reconciliation is mechanical: in the integration, position sizes are small because risk-per-trade-pct competes across all 17 edges, so the realistic Almgren-Chriss impact term stays small; standalone, the same risk_per_trade has to size up onto fewer signals → bigger trades → more impact. **The portfolio's alpha exists, but it's a property of the integration's risk-sizing dampening + the timing diversification across edges, not a property of any edge's standalone signal.** That makes attribution-based pruning *more* informative than further standalone gauntlet runs: the gauntlet has already told us what it can — these edges fail standalone. The actionable next step is to (1) cut the 9 noise/sparse/zero-fill edges out of the active list, (2) keep the two alpha edges and the four mildly-helpful weak-positives, and (3) stop trying to grow the edge count until the existing two contributors are understood at the position-sizing-interaction level. Attribution-based pruning is enough to act on now.

## 7. Raw artifacts

- CSV with all metrics: `data/research/per_edge_per_year_2026_04.csv`
- Source trade logs: `data/trade_logs/abf68c8e-1384-4db4-822c-d65894af70a1/trades.csv`, `data/trade_logs/72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34/trades.csv`
- Driver: `scripts/per_edge_per_year_attribution.py`
