# Multi-Year Substrate-Gap Decomposition — Three Mechanisms, Year-Dependent

**Status:** 2026-05-09 read-only trade-log analysis. Extends the 2024-only analysis (`six_names_hypothesis_refuted_2026_05_09.md`) to all 5 years. Shows the substrate gap is NOT a single mechanism — it's three different mechanisms that dominate in different regimes.

## Method

For each year 2021-2025, compared the static-109 trade log against the universe-aware trade log (run_ids per the verdict report). Decomposed the PnL gap into three components:

1. **Static-only names** (the 6 non-S&P + a few inactive): names that exist in static config but excluded by historical S&P 500 universe
2. **Uaware-only names** (the 322-383 names added by historical loader): drag or contribution from names static doesn't trade
3. **Dilution on common names**: PnL difference on the 100-103 names that exist in BOTH substrates, attributable purely to position-size scaling at constant capital

## Per-year decomposition

| Year | Δ Sharpe | Static-only $ | Uaware-only $ | Dilution on common $ | Total gap $ |
|---:|---:|---:|---:|---:|---:|
| 2021 | +0.804 | $95 | -$163 | **$2,574** | $2,832 |
| 2022 | +0.904 | $31 | **-$4,774** | -$1,283 | $3,522 |
| 2023 | +0.095 | $518 | +$3,733 | $2,946 | **-$270** |
| 2024 | +1.622 | $108 | -$474 | **$6,554** | $7,136 |
| 2025 | +0.518 | $214 | -$963 | $346 | $1,523 |

(Total gap = static_PnL − uaware_PnL. Positive means static outperformed.)

## The three mechanisms, by year

### 2024 (dilution dominant, $6,554 / $7,136 = 91.8%)

The big-gap year. Static-109 made $6,241; universe-aware made -$895. **The strategy made nearly all of static's PnL on the 100 mega-cap names that exist in BOTH substrates** — same names, same edge code, drastically different per-name PnL because position sizing scales inversely with universe size at constant capital. RTX, SO, GILD, LOW, IBM, BKNG, ADP, LIN, META — all S&P 500 mega-caps in both universes. Static had ~$1.83k average position size; universe-aware had ~$420 average position size; the per-name signal is too small to scale.

Pure capital concentration. The 109-name list provided the geometry; the edges produced tiny per-trade signals that scaled into 1.890 Sharpe via concentration.

### 2021 (also dilution dominant, $2,574 / $2,832 = 90.9%)

Same mechanism as 2024 — pure dilution on shared mega-caps. Smaller magnitude because 2021's underlying PnL was smaller.

### 2022 (defensive concentration — the OPPOSITE of dilution)

This is the most interesting year. Static-109 was -$2,367 (small loss); universe-aware was -$5,889 (big loss). **The 331 names that universe-aware ADDS lost -$4,774.** Static's "advantage" in 2022 wasn't doing better on shared names — it was actually doing slightly worse on them (-$1,283 dilution direction reversed). Static won by NOT trading the 331 expanded names that all went down in the bear regime.

The 109-name list was *implicitly defensive*: hand-curated mega-caps that fall less in bear regimes than the broader S&P 500. Static-109 looked smart in 2022 because it dodged the 331 names that took the brunt of the drawdown. The strategy itself didn't make a defensive call; the substrate did.

### 2023 (the substrate didn't matter)

Universe-aware actually OUTPERFORMED static-109 by $270. The 359 added names contributed +$3,733 (positive!). Common-names dilution would have given static an advantage ($2,946) but it was more than offset.

2023 was a **broad-participation rally**. Universe-aware's 467 names participated in the rally; static-109's curation didn't help; in fact, the 109-name concentration *missed* gains on the 359 added names. The dilution mechanism is offset by the broader-participation tailwind.

This is exactly the year that "looks fine" on a substrate-honest universe — and it's the only year. **The system has signal in 2023's regime; it doesn't have transferable signal in the other 4.**

### 2025 (mixed: dilution + added-name drag)

Choppy year. Static-109 made $277 (basically flat). Universe-aware made -$1,246. The 6 non-S&P names contributed $214 (77% of static's tiny PnL — the only year where the 6-names hypothesis is meaningfully load-bearing). Common-names dilution was modest ($346) and the 383 added names dragged -$963.

The 2025 picture is the most ambiguous: small base PnL means each component matters proportionally more, but the absolute magnitudes are small.

## What this means

The substrate gap is NOT a single mechanism. It's three mechanisms with regime-dependent dominance:

- **Bull years with concentrated leadership (2024, partially 2021):** dilution dominant. The static-109 "alpha" is just position-size scaling.
- **Bear years (2022):** defensive-concentration dominant. The static-109 "alpha" is NOT trading additional names that fall harder. The strategy got lucky that the curation happened to be defensive.
- **Bull years with broad participation (2023):** substrate doesn't matter. The strategy works fine on representative universe.
- **Choppy years (2025):** mixed; small magnitudes.

**The strategy has no transferable per-name signal.** It looks like it has signal because:
- Concentrated capital scales tiny per-trade signals into meaningful Sharpe in mega-cap-dispersion years
- Curation accidentally provides defensive bias in bear years
- One year out of five (2023) genuinely works on representative universe

The "Foundation Gate 1.296 PASS" and the 6-week measurement narrative were measuring **a curation-amplified pseudo-signal**, not transferable alpha. The discipline framework caught this; the question for C-collapses-1 is whether anything *under* the curation amplification has actual edge.

## Implications for C-collapses-1

The dispatch's deliverable #2 (per-edge audit on substrate-honest universe at NORMAL capital) will likely show every edge produces near-zero or negative Sharpe — that's the dilution effect on small per-trade signals.

The audit needs an additional test: **per-edge on substrate-honest universe at concentration-equivalent capital** (i.e., scale capital to keep average position size equal to the static-109 baseline). Two outcomes:

1. **Sharpe recovers under scaled capital:** edges have small per-name signal that needs concentration to surface. Path forward: deliberate small-universe construction with explicit rationale (an asymmetric-upside or concentrated-quality sleeve).
2. **Sharpe stays low under scaled capital:** the system has no per-name alpha; the static-109 result was 100% concentration accident. Path forward: genuine new alpha generation, not portfolio-construction tweaks.

**The 2023 case is uniquely informative.** If concentration-equivalent capital recovers Sharpe in 2024 but 2023 already worked at normal capital, that suggests two different patterns: 2023 has real signal (don't need concentration), 2024 has artifact signal (needs concentration). The audit should preserve this distinction.

## Implications for forward strategy

This decomposition makes the kill-thesis discussion sharper. "0.507 ≥ 0.5 = nominally pass" is a misleading framing because 1 of 5 years (2023) carries the average. **The honest reading is: the system has signal in 1 of 5 years on a representative universe.** That's not a deployable strategy; it's a measurement.

What the substrate honest-result CAN'T tell us yet:
- Whether 2023's signal-bearing regime is recurring or one-off
- Whether the per-edge attribution will reveal that ONE specific edge carries 2023 (and the rest are noise)
- Whether concentration-aware testing reveals the 4 collapse years can be rescued via deliberate small-universe construction

C-collapses-1 will answer the second question. The third question requires the additional concentration-scaled test.

## Caveats

- Read-only trade-log analysis using `data/trade_logs/<run_id>/trades.csv`
- Per-trade PnL is realized only; mark-to-market unrealized positions could shift small contributions
- The static-109 trade logs are from canonical Foundation Gate runs (matching memory `project_foundation_gate_passed_2026_05_04.md` Sharpe values for 2021-2024; 2025 picked from the highest-Sharpe 109-ticker run with matching date range)
- Universe-aware trade logs are from B1's verdict report (`docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md` Run-ID table)
- Analysis run while C-collapses-1 audit was in flight in `worktrees/c-collapses-edge-audit`; this is preliminary orientation, not a substitute for the audit's per-edge analysis
