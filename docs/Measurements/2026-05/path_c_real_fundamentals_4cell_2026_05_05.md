# Path C — Real-Fundamentals 4-Cell Harness Result (2026-05-05)

**Window:** 2022-01-01 → 2025-04-30 (FREE-tier-feasible window — first SimFin TTM-eligible rebalance is 2022-01-01).
**Universe:** S&P 500 ex-Financials, intersected with SimFin coverage = 351 tickers (Cell D); 51-ticker hardcoded mega-cap universe (Cell C, original synthetic).
**Initial capital:** $10,000. **LT cap-gains rate:** 15%.
**Rebalance cadence:** annual, first trading day of January (3 rebalances: 2022, 2023, 2024).

## Results

| Strategy | CAGR pre-tax | CAGR after-tax | Sharpe | MDD |
|---|---:|---:|---:|---:|
| **compounder_real_fundamentals** (Cell D) | **6.89%** | **5.64%** | **0.461** | -21.36% |
| compounder_synthetic (Cell C) | 3.87% | 3.13% | 0.387 | -15.74% |
| spy_buyhold (Cell A) | 6.07% | 5.21% | 0.406 | -24.50% |
| 60_40_buyhold (Cell B) | 3.72% | 2.46% | 0.379 | -17.16% |

## Pass criterion outcome

| Criterion | Required | Actual | Verdict |
|---|---|---|---|
| After-tax CAGR > SPY | 5.21% | 5.64% | **PASS** (+43 bp) |
| Max drawdown ≥ -15% | ≥ -15% | -21.36% | **FAIL** |

**Overall: FAIL** by the original spec.

## Honest interpretation

### What the real-fundamentals composite IS doing

- **Beats the synthetic price-derived composite by 251 bp CAGR after-tax** (5.64% vs 3.13%). The 6 V/Q/A factors (E/P, B/P, ROIC, gross profitability, -Sloan accruals, -asset growth) on a 351-ticker universe extract real cross-sectional signal that the price-derived 4-factor composite on 51 mega-caps does not.
- **Beats SPY after-tax by 43 bp.** The buy-and-hold benchmark is hard to beat after taxes; doing it by 43 bp on a 3-year window is real but not extraordinary.
- **Higher Sharpe than all three benchmarks.** 0.461 > 0.406 (SPY) > 0.387 (synthetic) > 0.379 (60/40).
- **Beats 60/40 on every dimension except MDD.** Compounder is +318 bp CAGR after-tax, +0.082 Sharpe, but -4.2 pp deeper drawdown.

### What it is NOT doing

- **Does not deliver the -15% MDD target.** -21.36% MDD is closer to SPY's -24.50% than to the target. The "defensive" thesis from the original compounder design didn't generalize from the 51-ticker mega-cap synthetic to the 351-ticker real-fundamentals universe.
- **Does not invalidate the synthetic as a comparable.** The synthetic's -15.74% MDD looks better than real fundamentals — but it achieves that by holding 51 implicitly-low-vol mega-caps. The synthetic's universe IS the structural risk-mitigation, not the factor logic.
- **Does not prove out a 5-year claim.** This is 3 years (2022 bear, 2023 recovery, 2024 bull). Limited regime sample.

### Sample comparison — what changed between Cell C and Cell D

- **Universe expansion (51 → 351 names)** is the biggest single change. Cross-sectional dispersion is real with 351 names; it isn't with 51.
- **Factor change (price-derived → real V/Q/A)** is the second change. The 251 bp CAGR uplift is jointly attributable to universe + factors; the harness doesn't decompose them.

## Implications for the spend gate

The original Path C unblock plan said: "If real fundamentals show lift, upgrade SimFin BASIC for additional 10 years of pre-2021 history."

**The signal qualifies as lift** — real fundamentals beat both SPY and synthetic across CAGR and Sharpe. The MDD failure is a separate issue (the -15% target doesn't generalize off the 51-ticker mega-cap basket).

Three honest options going forward:

1. **Upgrade to BASIC ($420/yr)** — buys 10 additional pre-2021 years of fundamentals. With 13-year data instead of 3, statistical power for the compounder thesis is genuinely better. Worth the spend if (a) you intend to actually deploy this sleeve, (b) the additional years confirm the lift survives 2010-2020 (including the 2020 COVID bear), (c) the MDD-target question can be resolved by including more bear-cycle data.

2. **Stay on FREE, lower the MDD target** — accept that a 351-ticker S&P ex-financials compounder can't deliver -15% MDD. Reset the target to ≤ SPY-2pp (i.e. better than buy-and-hold). The Cell D MDD of -21.36% vs SPY -24.50% achieves this by 3.14 pp.

3. **Stay on FREE, add risk overlay** — wire the compounder to the existing exposure cap + vol-targeting machinery so MDD is constrained by Engine B-style controls rather than expecting it from the factor composite alone. Lower CAGR, lower MDD, possibly preserve Sharpe.

Recommendation: **option 3 first** (cheap; tests whether a vol overlay can rescue the MDD target without spending), **option 1 second** (if option 3 doesn't deliver, the data depth question becomes the bottleneck).

## Limitations of this measurement

- 3-year window only — single bear, single bull, single recovery. Statistically thin.
- SimFin FREE excludes US banks (~70 names); Path C universe is S&P 500 ex-Financials, so this is materially equivalent to the spec.
- 4 yfinance tickers failed to download (FLT, CDAY, FSR, DLPH — likely delisted post-S&P-membership). Universe effective for harness ≈ 351 - 4 = 347.
- Synthetic Cell C uses the SAME 51-ticker mega-cap universe as the original failed run for clean comparability. This means Cell D's universe-size advantage is bundled into the "real fundamentals lift" finding.
- Real-fundamentals composite is annual rebalance — captures slow-moving V/Q/A signals correctly but doesn't address mid-year regime shifts.

## Run reproducibility

```bash
# SimFin FREE-tier window (data layer's 2020-mid bound forces 2022-01-01 as first usable rebalance)
# Edit START_DATE = "2022-01-01", END_DATE = "2025-04-30" in the script
PYTHONHASHSEED=0 python scripts/path_c_synthetic_compounder.py --run
```

Default in committed code is `2010-01-01 / 2024-12-31` — the BASIC-tier-feasible window — so the run is non-default by design. Output JSON: `data/research/path_c_synthetic_backtest.json` (gitignored).
