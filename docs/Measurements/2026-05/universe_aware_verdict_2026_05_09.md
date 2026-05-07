# Universe-Aware Verdict — 2026-05-09

**Question:** Was the 1.296 mean-Sharpe Foundation Gate baseline real
alpha, or was it conditional on the static 109-ticker mega-cap selection
in `config/backtest_settings.json`?

**Answer:** **COLLAPSES.** Mean Sharpe drops 1.296 → **0.5074** (−0.789,
a 61% reduction) when the backtest substrate is swapped from the static
list to the survivorship-bias-aware S&P 500 historical union. Most of
the headline alpha was selection bias from the hand-picked mega-cap
universe.

The mean does technically clear the 0.5 Foundation Gate threshold by
0.0074, but the per-year volatility (range 1.61 Sharpe) and the
universe-aware mean falling below the **PARTIAL** band (0.7-1.1) put
this firmly in the COLLAPSES bucket per the experiment's own verdict
table. The 0.5 gate clearance is cosmetic, not a real signal of
robustness.

---

## Verdict bucket

| Outcome | Mean Sharpe range | Verdict | This run |
|---|---|---|---|
| Substrate-real | within ±0.15 of 1.296 | downstream confirmed | — |
| Universe artifact partial | 0.7-1.1 | recalibrate | — |
| Most "alpha" was selection bias | 0.3-0.5 | reset directive | **0.507** ← here |

The 0.507 sits at the very top edge of the COLLAPSES band. Reading the
verdict charitably (calling 0.507 "PARTIAL" because it just clears the
gate floor) requires ignoring the per-year variance and the −1.622
Sharpe collapse on 2024. The honest read is COLLAPSES.

---

## Per-year Sharpe deltas

Baseline numbers from `project_foundation_gate_passed_2026_05_04.md`
(static 109-ticker, deterministic harness, multi-year measurement
2026-05-04).

| Year | Static (109) | Universe-aware (476-503) | Δ Sharpe | Within-noise (±0.15)? |
|---|---:|---:|---:|---|
| 2021 | 1.666 | 0.862 | **−0.804** | NO (5.4× noise band) |
| 2022 | 0.583 | −0.321 | **−0.904** | NO (6.0× noise band) |
| 2023 | 1.387 | 1.292 | −0.095 | YES |
| 2024 | 1.890 | 0.268 | **−1.622** | NO (10.8× noise band) |
| 2025 | 0.954 | 0.436 | **−0.518** | NO (3.5× noise band) |
| **Mean** | **1.296** | **0.507** | **−0.789** | NO (5.3× noise band) |

**4 of 5 years collapse far outside the noise band.** Only 2023 holds
together. The pattern is regime-conditional but the regime that holds
the alpha together (mid-cycle bull with broad participation) is
nowhere close to a default state — it's the exception, not the rule.

### Auxiliary metrics (universe-aware)

| Year | CAGR % | MDD % | Win Rate % | Universe size |
|---|---:|---:|---:|---:|
| 2021 | 3.25 | −3.24 | 46.51 | 476 |
| 2022 | −3.05 | −9.46 | 45.05 | 484 |
| 2023 | 7.42 | −4.46 | 50.23 | 494 |
| 2024 | 1.11 | −3.52 | 41.41 | 498 |
| 2025 | 1.91 | −2.86 | 47.02 | 503 |

CAGR collapses are equally severe — 2024 from a multi-percent CAGR (per
prior baseline) to 1.11%. MDD is consistently better-behaved on the
larger universe, presumably because per-name capital allocation drops
proportionally; this is not alpha, it's diversification.

### Universe-size delta

The static list is **109 tickers**, all S&P 500 mega-caps hand-curated
in `config/backtest_settings.json`. The historical union (after
intersecting with the locally-cached price CSVs at `data/processed/`)
ranges from 476 to 503, a 4.4×-4.6× expansion. The unfiltered S&P
500 historical union per anchor year is 523-525; 26-54 names are
dropped per year because no CSV is on disk locally (mostly delisted /
acquired / renamed names like AMD, ATVI, BRK.B, FRC, DISCA).

| Year | Static | Historical union (raw) | After CSV filter | Missing (no CSV) |
|---|---:|---:|---:|---:|
| 2021 | 109 | 525 | 476 | 54 |
| 2022 | 109 | 525 | 484 | 46 |
| 2023 | 109 | 523 | 494 | 34 |
| 2024 | 109 | 523 | 498 | 30 |
| 2025 | 109 | 524 | 503 | 26 |

The 26-54 missing names per year DO contain meaningful survivorship
signal (e.g. FRC failed in 2023, DISCA was acquired in 2022) and are
NOT in the universe-aware run. **The current measurement is therefore
an upper bound on the universe-aware Sharpe** — adding the missing
delisted names would, if anything, push the verdict deeper into the
COLLAPSES bucket because pure-static-bias removal works against the
strategy. The measured −0.789 mean delta is the conservative direction.

---

## Determinism check

**Within-year:** This rerun used `--runs 1` (one rep per year) to fit
the wall-time budget, so within-year bitwise determinism cannot be
verified directly from these results. The auto-generated markdown
report tags each year as "PASS (bitwise)" trivially because there is
only one canon md5 per year.

**Mitigation:** The resolver-level determinism contract is verified by
`tests/test_universe_resolver.py::TestDeterminism` (same inputs →
identical output). Universe resolution is fully deterministic; any
non-determinism in the multi-year measurement would necessarily be
inherited from the existing backtest pipeline, which already has 3-rep
bitwise verification on prior measurement campaigns (see
`project_foundation_gate_passed_2026_05_04.md`).

**Recommended follow-on:** A 3-rep run on a single year (e.g. 2024,
which currently shows the largest collapse) to verify the new
substrate's bitwise reproducibility under the determinism harness.
This is ~75 min wall time and was deferred from this rerun to fit the
4-8h budget.

---

## Tickers added by the substrate swap

The 367-394 tickers added by the universe-aware substrate (476-109 to
503-109) are S&P 500 names not in the static config. Material
representatives:

- **Defensive / dividend-heavy:** PEP, KO, MO, PM, JNJ, PG, MCD,
  WMT (already in static); DUK, SO, NEE, AEP, AEE, EXC (added).
- **Cyclicals removed from mega-cap selection:** F (Ford), GM, FCX,
  AA, X, USS, NUE.
- **Smaller financials:** WTW, AFL, AON, AJG, ALL, AIG, MMC, TRV.
- **Real estate:** AVB, EQR, MAA, ESS, EXR, PSA.
- **Healthcare:** ABT, AMGN, BMY, CI, CVS, GILD, HCA, MDT.

These are not "junk" names — they are the actual S&P 500. The static
config's 109 names skewed sharply toward growth tech and a handful of
high-momentum financials. The strategy's 1.296 baseline is a property
of that skew, not a property of the strategy.

### Tickers in static but NOT in historical union

Several tickers from `config/backtest_settings.json` are NOT in the
S&P 500 historical union (these are non-S&P or never-S&P names that
the static config carries anyway):

- COIN, DKNG, MARA, RIOT, PLTR, SNOW (post-2020 IPOs / non-S&P, only
  some are S&P 500 today)
- QQQ, SPY (essentials, retained explicitly via the `essential_tickers`
  config key)

These names are excluded from the universe-aware substrate by design.
The strategy may have been benefiting from concentrated exposure to
high-volatility crypto-adjacent names (COIN, MARA, RIOT) — that's a
data point for the COLLAPSES interpretation.

---

## What this means for the project

1. **Past Sharpe headlines need an asterisk.** The Q1 0.984 baseline,
   the 1.063 cap-recalibration peak, the 1.296 Foundation Gate mean —
   all of them are conditional on the static 109-ticker selection.
   The universe-aware substrate cuts the headline by 60%.

2. **Path 1 ship is not viable as previously framed.** The kill thesis
   that was "suspended" by the 04-30 Foundation Gate pass is now
   re-engaged on a survivorship-aware substrate. Mean 0.507 ≥ 0.5 is
   technically a clear, but the per-year volatility makes that
   clearance meaningless — 4 of 5 years collapse hard.

3. **The 2023 hold-up is informative.** The strategy survives in 2023
   (mid-cycle, broad-participation bull) but blows up in 2021 (megacap
   concentration year), 2022 (bear), 2024 (mag-7 dominance), and 2025
   (chop). The alpha generators are leaning on conditions that don't
   replicate across regimes — exactly the pathology that
   `momentum_factor_v1` exhibited on the 39-name universe in
   `project_factor_edge_first_alpha_2026_04_24.md`.

4. **Engine A's edges need re-validation against the universe-aware
   substrate.** Several edges (volume_anomaly_v1, herding_v1,
   momentum_edge_v1) had their Sharpe contribution validated on the
   static 109-ticker universe via the gauntlet. Those validations are
   now provisionally falsified — they should be re-run with
   `use_historical_universe=true` before treating any per-edge Sharpe
   number as honest.

5. **The cost-completeness work (Path A, ALPaca/borrow/tax) is
   decoupled from this finding.** That layer was correctly modeled
   pre-tax; the universe-aware substrate doesn't invalidate it. But
   the "after-tax Sharpe is -0.577" memory's pre-tax 0.984 base
   should be read as 0.5 × 0.984 ≈ 0.5 in the universe-aware world,
   which means the post-tax retail-deployment number is even worse
   than the prior memory claimed.

6. **The substrate fix lands cleanly.** The wiring is opt-in
   (`use_historical_universe: false` by default), the resolver tests
   pass, the existing universe.py tests pass, smoke test produced
   trades on previously-unseen names (NTAP, PH). The flag-on path is
   ready for Discovery / WFO / per-edge work going forward.

---

## Reset directive — what comes next

**Stop:**
- Quoting the 1.296 multi-year baseline without the universe-aware
  asterisk.
- Tuning Engine A edges against the static 109-ticker substrate.
- Treating Path 1 ship as a near-term option.

**Do:**
- Default `use_historical_universe: true` in `config/backtest_settings.json`
  for all measurement campaigns going forward.
- Re-run the gauntlet on the universe-aware substrate before any
  per-edge promotion / validation claim is treated as authoritative.
- Add the 26-54 missing-CSV delisted names to `data/processed/` via
  `scripts/fetch_universe.py` so the substrate is complete.
- Re-evaluate the 2023 hold-up to understand which alpha generators
  survive — that's the next falsifiable hypothesis.

**Don't:**
- Iterate the 109-ticker config trying to "fix" specific names — that
  re-introduces the same selection bias under a different label.
- Promote any new edges from the current Discovery cycle without
  re-validation under universe-aware geometry.

---

## Run metadata

- Branch: `f6-universe-loader-wire`
- Wiring commit: `69006fb` (feat(universe): wire historical_constituents
  into backtest data path)
- Multi-year run: `--years 2021,2022,2023,2024,2025 --runs 1
  --use-historical-universe`
- Wall time: 125.2 minutes (5 reps × ~25 min each, faster than the
  expected 50 min/rep — the 476-ticker universe is not 4.4× slower
  per-bar than 109 because most per-bar ops are not ticker-bound).
- Membership cache: `data/universe/sp500_membership.parquet` (896
  rows, 868 unique tickers, 523 currently-active, last fetched
  2026-05-05).
- Raw JSON: [`multi_year_universe_aware_2026_05_09.json`](multi_year_universe_aware_2026_05_09.json)
- Auto-generated markdown:
  [`multi_year_universe_aware_2026_05_09.md`](multi_year_universe_aware_2026_05_09.md)

| Run ID | Year | Canon md5 |
|---|---|---|
| 90c9c89d-e36b-444b-9397-845f820cabf7 | 2021 | e18bea36b4ac262faea089ba0635151e |
| ba0a1d15-62f6-4a45-a7bb-6eae1a4064ef | 2022 | 6d739af61d39cac8a936d625dfeb1f76 |
| d585059e-f8ad-4d59-9c1c-f98b87a70d6e | 2023 | 9c00df4b733b99756e771dbb5b06050b |
| 9b760b5c-3cd0-4f76-9e4e-acdec423730e | 2024 | 965d5a4513c52a4357a244a88e74b791 |
| 31be49d3-b5de-443e-84dc-f0c8495223a2 | 2025 | bafacca2f317c3f033c5aca0e98c2a4f |
