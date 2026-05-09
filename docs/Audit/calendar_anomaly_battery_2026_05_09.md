# Calendar Anomaly Battery — Audit (T-2026-05-09-014)

**Date:** 2026-05-09
**Branch:** `feature/calendar-anomaly-battery`
**Scope:** Foundry vocabulary expansion only. No engine modification, no edge promotion, no `edges.yml` mutation.

## What ships

7 calendar / event-driven features registered with the Foundry at tier A. Implementation: single file `core/feature_foundry/features/calendar.py`. Self-registration via `core/feature_foundry/features/__init__.py`.

| feature_id | source | ticker-dep? | horizon | academic citation |
|---|---|---|---:|---|
| `fomc_drift` | hardcoded FOMC date list | NO (calendar) | 1 | Lucca-Moench (2015), "Pre-FOMC Announcement Drift" |
| `pre_fomc_reduce` | hardcoded FOMC date list | NO (calendar) | 1 | Same — release-day vol-cluster |
| `pre_holiday` | hardcoded NYSE holiday list | NO (calendar) | 2 | Ariel (1990), "High Stock Returns Before Holidays" |
| `sell_in_may_halloween` | calendar month | NO (calendar) | 126 | Bouman-Jacobsen (2002) |
| `january_effect` | calendar month + trading-day count | NO (calendar) | 5 | Sias (2007); Reinganum (1983); Keim (1983) |
| `triple_witching_premium` | calendar 3rd Friday Mar/Jun/Sep/Dec | NO (calendar) | 1 | Stoll-Whaley (1987) |
| `tax_loss_season` | local OHLCV close-price lookback | **YES** (per-ticker) | 20 | Roll's tax-loss-selling effect |

Six of the seven are pure-calendar (ticker-independent — same value for every ticker on the same date). Tax_loss_season is the only ticker-dependent one — it consumes per-ticker close-price lookback (past 11 calendar months) to determine winner / loser status, returning ±1.0 in the Dec 10-24 window.

## Date sources + cutoffs

### FOMC announcement dates

Source: Federal Reserve Board's published FOMC meeting calendar (federalreserve.gov/monetarypolicy/fomccalendars.htm). Hardcoded in `FOMC_DATES` constant inside the calendar features file. Coverage: **2018-01-31 through 2026-12-09** (the published 2026 schedule). 9 years × ~8 meetings = ~72 dates.

The list captures scheduled meetings AND the 2020-03-15 emergency cut. Other rare emergency / inter-meeting actions may be missing — flagged here as a known approximation. The hardcoded approach is per-spec ("DO NOT fetch fresh FOMC dates from external API at runtime") and avoids any feature-evaluation-time API dependency.

**Annual update needed:** extend `FOMC_DATES` each Q4 once the Fed publishes the next year's schedule.

### US market holidays

Source: NYSE published holiday calendar. Hardcoded in `US_MARKET_HOLIDAYS` constant. Coverage: **2018-01-01 through 2026-12-25**. Captures the 9-10 NYSE holidays per year, including:

- New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth (since 2022), Independence Day, Labor Day, Thanksgiving, Christmas.

"Observed" dates used (Friday-or-Monday roll when holiday falls on weekend, per NYSE rule). Specific edge cases handled:

- 2022-01-01 fell on Saturday — NYSE did NOT observe (no Friday Dec 31 closure); list correctly omits Jan-2022.
- 2021-12-31 (Friday) was a regular trading day; the Saturday Jan-1 was the actual holiday — list correctly omits.
- Juneteenth was added to the federal calendar in 2021 but NYSE began observing in 2022 — list reflects this.

**Annual update needed:** extend `US_MARKET_HOLIDAYS` each year.

## Sample dates with expected feature outputs

Verified by `tests/test_calendar_anomaly_battery.py`:

| date | fomc_drift | pre_fomc_reduce | pre_holiday | sell_in_may_halloween | january_effect | triple_witching | tax_loss (AAPL) |
|---|---:|---:|---:|---:|---:|---:|---|
| 2024-01-02 (1st trading day) | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0.0 | 0.0 |
| 2024-01-08 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0.0 | 0.0 |
| 2024-01-09 | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 2024-01-30 (pre-FOMC) | **1.0** | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 2024-01-31 (FOMC) | 0.0 | **1.0** | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 2024-03-15 (3rd Fri Mar) | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | **1.0** | 0.0 |
| 2024-05-15 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 2024-07-03 (pre-July-4) | 0.0 | 0.0 | **1.0** | 0.0 | 0.0 | 0.0 | 0.0 |
| 2024-12-15 (mid-Dec) | 0.0 | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 | (depends on AAPL trailing) |

## Open questions surfaced (per spec)

### 1. FOMC date source decision

Hardcoded list approach taken (per spec mandate). Cutoff: 2026-12-09. Annual extension needed via Q4 review of the next year's published schedule. Alternative considered: FRED's `FEDFUNDS` regime change inference — rejected because (a) inference is approximate and would drift between feature evaluations, (b) introduces an indirect API dependency, (c) loses the 24-hour-pre-window precision the Lucca-Moench finding requires.

### 2. Sell-in-May vs Halloween indicator

Two conventions in the literature:
- **Calendar boundary** (chosen): Nov 1 — Apr 30 = "in", May 1 — Oct 31 = "out". Pure month membership, ticker-independent, no holiday adjustment.
- **Last-trading-day boundary**: 1.0 from last-trading-day-of-Oct through last-trading-day-of-Apr. Empirically nearly identical (1-2 day shift) but introduces dependency on holiday calendar at the boundaries.

Calendar boundary chosen for cleanliness and ticker-independence guarantee. Documented in feature description.

### 3. Tax_loss_season — direction and lookback

Direction: **+1.0 = winner (positive trailing return) in mid-Dec; -1.0 = loser (negative trailing return) in mid-Dec; 0.0 outside the window**.

Lookback: trailing 231 calendar days (~11 months) of close-price data for the ticker. Requires ≥100 actual trading days in the window to fire (otherwise abstain with `None`).

Mid-Dec window: Dec 10-24 inclusive. The 1-Jan reversal isn't directly captured — meta-learner / Discovery is expected to compose `tax_loss_season` with `january_effect` for the full pattern.

The directionality interpretation matches Roll's original framing: losers are sold for tax benefit by retail in mid-Dec → expected underperformance into year-end → reversal in early Jan. So mid-Dec losers get `-1.0` (predicted to underperform). Winners are "kept", so they get `+1.0` (no tax-loss-selling pressure).

Note: this isn't a pure-calendar feature — only one of the 7 with a ticker-dependent path. T-013's caching does NOT collapse this one across tickers. Per-ticker close-series cache (already in `local_ohlcv._CLOSE_CACHE`) handles the lookups efficiently.

### 4. T-013 caching evidence

The 6 pure-calendar features return identical values across tickers on the same date. Verified by `test_calendar_features_are_ticker_independent` which asserts `feat("AAPL", dt) == feat("MSFT", dt)` for 6 sample dates × 6 features = 36 invariance checks (all pass).

T-013's vectorization path automatically detects ticker-independent features and caches them. No extra wiring is needed at the feature level — the empirical-detection runs at panel-evaluation time. Pre/post evidence of cache hit-rate would require running a panel evaluation through the Foundry's caching layer, which is downstream of this dispatch's scope. Recommend adding a panel-eval benchmark in a follow-up ticket.

## Determinism guard

Per spec acceptance criterion 5: "running `python -m scripts.run_isolated --runs 1 --task q1` from a checkout of main + your changes must produce a canon md5 IDENTICAL to a clean main checkout."

**Reasoning the invariant should hold by construction:**

- No edge consumes any of the 7 new features. Edge code in `engines/engine_a_alpha/edges/` is unchanged.
- No `edges.yml` entry references any of the 7 feature_ids. Governor / lifecycle logic is unchanged.
- Discovery's gauntlet does not enumerate Foundry features at evaluation time — it operates on edge candidates already proposed.
- The `core.feature_foundry` package is imported only for self-registration; no production code path enumerates the registry except the dashboard tab and the ablation runner (both downstream of any backtest).

**Empirical verification (this run, post-implementation):**

Executed `python -m scripts.run_isolated --runs 1 --task q1` from this branch:

| Run | canon md5 | Sharpe |
|---|---|---|
| Baseline (most-recent main / T-010 reference) | `182af6a1240da35055f716ef9dfcd333` | 0.127 |
| This branch (calendar features added) | **`182af6a1240da35055f716ef9dfcd333`** | **0.127** |

**Determinism guard: PASS.** Canon md5 bit-identical to the T-010 reference (recorded in `docs/Audit/in_code_ci_aware_gates_2026_05_09.md` lines 22-23). Adding 7 calendar features to the Foundry registry produces zero behavior change in the q1 backtest, as expected — no edge consumes them, no `edges.yml` entry references them, and Discovery doesn't enumerate Foundry features in this code path.

## Tests

`tests/test_calendar_anomaly_battery.py` — 13 tests, all pass:

- `test_all_features_register_at_tier_A` — registry membership + tier
- `test_calendar_features_are_ticker_independent` — invariance for 6 features × 6 dates × 2 tickers
- `test_fomc_drift_known_dates` — pre-FOMC, FOMC day, random non-day
- `test_pre_fomc_reduce_known_dates` — 2024-01-31 + 2022-06-15 (75bp hike)
- `test_fomc_dates_list_is_non_empty` — sanity on 2024 + 2025
- `test_pre_holiday_known_dates` — July 3 2024, July 4 2024, neutral day
- `test_pre_holiday_handles_year_boundaries` — 2023-12-22 (pre-Christmas), 2025-12-24 (Wed before Thu Christmas), 2021-12-31 (no observed holiday)
- `test_sell_in_may_halloween_known_dates` — boundary cases (Apr 30 / May 1 / Oct 31 / Nov 1)
- `test_january_effect_known_dates` — 1st / 5th / 6th trading day boundary
- `test_triple_witching_premium_known_dates` — Q1 + Q2 2024 triple-witching, non-witching Friday, Tuesday, Apr (not a quad-end month)
- `test_tax_loss_season_outside_window_returns_zero` — Nov 30, Dec 1, Dec 9, Dec 25, Dec 31 all 0.0
- `test_tax_loss_season_returns_none_when_no_data` — sentinel ticker returns None (abstain, not crash)
- `test_tax_loss_season_directionality_with_synthetic` — synthetic winner / loser via cache injection

Plus the existing `tests/test_feature_foundry.py` + `tests/test_feature_foundry_gate.py` (37 tests) all still pass on this branch — registry side-effects from the new features don't bleed into other test modules' setup.

## Forward-looking note: Discovery wiring needed for tradeable use

These features ship as **vocabulary** for the meta-learner / Discovery's gauntlet, NOT as edges to be deployed. For any of them to drive trades, the following downstream wiring would need to happen (out of scope for this dispatch):

1. **Discovery candidate generation** would need to consume the registered Foundry features as primitives in its candidate-edge synthesis. Today Discovery uses a fixed primitive set; a follow-up ticket could route `get_feature_registry()` into the synthesis loop.
2. **Edge implementation**: a candidate edge that uses `fomc_drift` (e.g., "long SPY in 24-hour pre-FOMC window") would need to be coded as an `EdgeBase` subclass in `engines/engine_a_alpha/edges/`, registered, and run through the standard validation gauntlet.
3. **Gauntlet acceptance**: the candidate would need to clear the substrate-honest gauntlet (Gates 1-8 incl. factor decomp at t > 2). Given T-004's finding that 0/6 active edges have factor-adjusted alpha at t > 2 on substrate-honest, the bar is high.

## What this dispatch does NOT do

- No edge promotion. No `edges.yml` mutation.
- No backtest behavior change. canon md5 expected invariant.
- No `engines/engine_a_alpha/edges/` modification.
- No new external dependencies. No runtime API calls.
- No `core.feature_foundry.feature` decorator changes.
- No tier_classifier.py / Engine F lifecycle interaction.

## Files changed

- `core/feature_foundry/features/calendar.py` — new (7 features, FOMC date list, holiday list, helper functions)
- `core/feature_foundry/features/__init__.py` — added 1-line import for self-registration
- `tests/test_calendar_anomaly_battery.py` — new (13 tests)
- `docs/Audit/calendar_anomaly_battery_2026_05_09.md` — this audit doc

Total LOC delta: ~700 added, 0 removed.
