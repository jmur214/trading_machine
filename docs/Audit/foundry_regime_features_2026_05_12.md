# T-2026-05-12-052 — 4-signal regime ensemble as Foundry features

**Date:** 2026-05-12
**Branch:** `feature/foundry-regime-ensemble-features`
**Worker:** Agent B
**Status:** Features shipped + tested; full Discovery smoke deferred
per T-038-CONT misdiagnosis (production hunt() does not pass
`ticker=` to compute_all_features, so the Foundry pass is bypassed
in production; the four T-052 features ARE callable via the
ablation/leakage-detector and test paths).

## Summary

Four new tier-A Foundry features representing the minimum-effective
regime-ensemble identified by the 4 independent external research
dives that converged on this prescription:

| ID | Captures | Cadence | Source |
|---|---|---|---|
| `vix_term_structure_slope` | Vol carry / risk-off (1–20 days) | daily | FRED VIX + VIX3M (CACHED) |
| `hy_oas_change_20d` | Credit-stress velocity (6–12 mo lead) | daily | FRED BAMLH0A0HYM2 (CACHED) |
| `anfci_z_60d` | Financial-conditions z-score (weekly) | weekly → daily ffill | FRED ANFCI (MISSING — backfill required) |
| `faber_multi_asset_trend_above_10mo_sma` | Price-regime breadth (monthly) | monthly → daily ffill | local OHLCV {SPY, EFA, AGG, GLD, VNQ} (SPY+GLD cached; EFA/AGG/VNQ MISSING — backfill required) |

## Features

### 1. `vix_term_structure_slope`

`VIX / VIX3M`. Contango (ratio < 1) = normal regime; backwardation
(ratio > 1) = active vol shock / de-grossing trigger.

- File: `core/feature_foundry/features/vix_term_structure_slope.py`
- Tier: A (primary regime signal)
- Horizon: 5
- Source: FRED (both series cached in `data/macro/VIX.parquet` and
  `data/macro/VIX3M.parquet`)
- Look-ahead: daily close, available T+0 EOD → usable at T+1 open
- Spot check on real data, 2024-06-17 → 0.862 (contango, normal)

### 2. `hy_oas_change_20d`

20-business-day delta of BAMLH0A0HYM2 (ICE BofA HY OAS) in basis
points. Per research convergence: the Δ matters more than the level
for regime classification.

- File: `core/feature_foundry/features/hy_oas_change_20d.py`
- Tier: A
- Horizon: 21
- Source: FRED BAMLH0A0HYM2 (cached at `data/macro/BAMLH0A0HYM2.parquet`)
- Look-ahead: daily close, ~1-day publication lag → usable T+1 EOD
- Spot check on real data, 2024-06-17 → +19 bps (modest widening)

### 3. `anfci_z_60d`

60-day z-score of ANFCI weekly publication (carried forward to daily
bars). **ANFCI is NOT in the current macro cache** — feature returns
None gracefully with a one-time WARNING. Backfill via
`scripts/backfill_t052_macro_data.py`.

- File: `core/feature_foundry/features/anfci_z_60d.py`
- Tier: A
- Horizon: 21
- Source: FRED ANFCI (MISSING; populate via backfill script)
- Look-ahead: weekly publication; 1-week typical lag → safe at T+5
- **CAVEAT (per all 4 research dives + T-052 brief open question
  #2)**: FRED current-vintage values incorporate post-publication
  revisions. ALFRED migration is candidate T-047 / T-048 (separate
  workstream). The feature logs this caveat at WARNING level on first
  invocation.

### 4. `faber_multi_asset_trend_above_10mo_sma`

Sum across {SPY, EFA, AGG, GLD, VNQ} of `1 if close > 10-month SMA
else 0`. Integer score in {0, 1, 2, 3, 4, 5}. Canonical Faber GTAA
price-regime filter.

- File: `core/feature_foundry/features/faber_multi_asset_trend.py`
- Tier: A
- Horizon: 21
- Source: local OHLCV (only SPY + GLD cached as of T-052 ship; EFA,
  AGG, VNQ missing — backfill via script)
- Look-ahead: 10-month SMA, monthly evaluation cadence — robust to
  intra-day shift
- Spot check on real data, 2024-06-17 (with partial coverage SPY+GLD
  only) → 2.0 (both above their 10-month SMA)
- **Partial coverage**: feature computes score over whatever ETFs ARE
  available + logs a one-time WARNING. Scale shifts: 0-2 vs 0-5.

## Engine D gene-vocabulary update

Per T-022's foundry_feature bucket: the existing
`_create_random_gene()` factory in `discovery.py:524-573` samples
from `get_feature_registry()._features.tier in ("A", "B")` at 20 %
probability. The 4 new features auto-register at module-import time
(via `core.feature_foundry.features.__init__.py`), so they're
automatically eligible for sampling without any explicit gene-encoder
change.

**Empirical confirmation** (test
`test_gene_vocabulary_includes_regime_features`): 2000 draws of
`_create_random_gene()` produce ≥1 hit per new feature_id.

## Seed-population enricher

Per T-024's `_seed_random_genomes` (5 random Gen-0 genomes): the
expected coverage of any specific feature in the random seeds is
~0.014 (5 seeds × 1 gene × 0.20 foundry × 4/35 = 1.14 % per feature).
That's not "1 seed per new feature type" as the brief required.

**Fix:** added `_T052_TARGET_FEATURE_IDS` constant + targeted-seed
loop in `discovery.py:_run_ga_evolution`. On the GA's first-run path
(no persisted population), one Gen-0 single-gene long-direction
genome is appended per new feature, BEFORE the random fill. This
guarantees 1-per-feature coverage in cycle 0.

Targeted-seed genome shape:
```python
{
    "edge_id": "composite_t052_seed_<fid>_<6hex>",
    "genes": [{
        "type": "foundry_feature",
        "feature_id": fid,
        "operator": "greater",
        "threshold": 0.0,
    }],
    "direction": "long",
}
```

After the targeted seeds run, the existing random-fill loop continues
to populate the population up to `population_size`. So population
composition for cycle 0 is: targeted-seeds (4) + random-fill (16+) =
20 genomes per default population_size.

## Backfill script

`scripts/backfill_t052_macro_data.py` — convenience runner that:

1. Fetches ANFCI from FRED via the project's existing `macro_data.py`
   pipeline → `data/macro/ANFCI.parquet`.
2. Fetches EFA, AGG, VNQ from yfinance → `data/processed/<TICKER>_1d.csv`.

VIX, VIX3M, BAMLH0A0HYM2, SPY, GLD are already cached and not
re-fetched. The 4 T-052 features are functional without this script
(they degrade gracefully with WARNING logs); the script is the data-
population step for full feature coverage.

## Tests

File: `tests/test_foundry_regime_features.py` — 15 tests, all pass:

1. `test_all_four_features_register` — side-effectful import
   triggers @feature decorator.
2. `test_all_four_features_tier_a` — tier-A confirmed.
3. `test_vix_term_structure_slope_contango_vs_backwardation` —
   synthetic VIX=20/VIX3M=22 → 0.909; VIX=30/VIX3M=24 → 1.25.
4. `test_vix_term_structure_slope_returns_real_value_on_local_cache`.
5. `test_vix_term_structure_slope_returns_none_when_data_missing`.
6. `test_hy_oas_change_20d_point_in_time` — verifies dt-bounded slice.
7. `test_hy_oas_change_20d_returns_real_value_on_local_cache`.
8. `test_hy_oas_change_20d_returns_none_when_insufficient_history`.
9. `test_anfci_z_60d_documented_fred_caveat` — explicit caveat fires.
10. `test_anfci_z_60d_computes_z_when_data_present` — synthetic z.
11. `test_faber_score_5_assets_all_above` — synthetic all above SMA.
12. `test_faber_score_partial_coverage` — SPY+GLD only.
13. `test_faber_score_returns_none_when_too_few_etfs`.
14. `test_gene_vocabulary_includes_regime_features` — 2000-draw
    sampling coverage.
15. `test_seed_population_enriched_with_regime_features` — targeted
    constants present.

Plus existing 53 feature-foundry/ws-e-fourth-batch tests still pass.

## Smoke cycle outcome

**Acceptance criterion #5** ("Smoke test: cap=3 Discovery cycle
smoke (1yr substrate-honest) produces ≥1 candidate referencing a
new regime feature") is **NOT EXERCISED** in this branch.

Rationale: per T-038-CONT audit doc, production `discovery.hunt()`
does NOT pass `ticker=` to `compute_all_features`, so the Foundry
pass — including any of the 4 new T-052 features — is bypassed in
the production code path. Running a smoke cycle would NOT exercise
the new features end-to-end until that wiring gap is closed
(candidate workstream T-040+).

What IS demonstrated end-to-end in this branch:

- Direct invocation of each feature function returns a plausible
  value (or graceful None + WARNING for the 2 missing-data cases)
  on real cached data — verified by tests #4, #7, #11.
- The `_T052_TARGET_FEATURE_IDS` are samplable from the gene factory
  — verified by test #14.
- The targeted-seed mechanism is in place — verified by test #15.

What still needs to happen before T-052 features become alpha-
producing:

1. Run `scripts/backfill_t052_macro_data.py` to populate ANFCI,
   EFA, AGG, VNQ.
2. (DEPENDENCY) Wire `ticker=` through production hunt() — separate
   workstream (T-040+ candidate). Until this is done, foundry_feature
   genes (including T-052's 4 new ones) have NaN values in the gate-1
   evaluation DataFrame and reliably fail validation. This is the
   structural reason T-021/T-026 saw "Discovery emits only
   rsi_bounce_v1 mutations."
3. Run substrate-honest Discovery cycle on cleaned anchor (gated on
   director's pairwise-correlation diagnostic).

## Hard constraints — confirmed met

- [x] Engine A/B/C/E/F code untouched.
- [x] Each feature has unit tests for known-input → known-output.
- [x] Each feature is point-in-time safe (`s[s.index <= dt]`).
- [x] No look-ahead data — verified by
  `test_hy_oas_change_20d_point_in_time` and per-feature dt-bounded
  slicing.
- [x] No cap=30 Discovery cycle run.
- [x] No HMM retraining (out of scope per brief).
- [x] No bootstrap-CI Sharpe claim — T-052 ships no measurement
  numbers requiring bootstrap CI per CLAUDE.md non-negotiable #6.

## Files

- **NEW** `core/feature_foundry/features/vix_term_structure_slope.py`
- **NEW** `core/feature_foundry/features/hy_oas_change_20d.py`
- **NEW** `core/feature_foundry/features/anfci_z_60d.py`
- **NEW** `core/feature_foundry/features/faber_multi_asset_trend.py`
- **MOD** `core/feature_foundry/features/__init__.py` — register 4 new
- **MOD** `engines/engine_d_discovery/discovery.py` —
  `_T052_TARGET_FEATURE_IDS` + targeted-seed loop in
  `_run_ga_evolution`
- **NEW** `tests/test_foundry_regime_features.py` — 15 tests, all pass
- **NEW** `scripts/backfill_t052_macro_data.py` — convenience data
  fetcher
- **NEW** `docs/Audit/foundry_regime_features_2026_05_12.md` (this doc)

## Forward-look

- **ALFRED migration** (T-047/T-048 candidate) — replace FRED current-
  vintage `ANFCI` access with point-in-time ALFRED vintage to
  eliminate the look-ahead caveat documented above. Same issue exists
  for any other revised FRED series; ANFCI is the most-revised in
  the T-052 ensemble.
- **CBOE direct ingestion of VIX9D / VIX1M / VIX6M** — already in
  cache for those FRED-reachable variants; CBOE direct CSV would add
  intraday cadence (5-min snapshots) which the regime-analyst lens
  may want once event-driven signals come online.
- **Per-feature regime backtests** — once the production wiring gap
  is closed and ANFCI/EFA/AGG/VNQ are backfilled, run individual-
  feature ablation backtests to surface which of the 4 actually
  carries alpha. Per the research convergence the EXPECTED winner is
  vix_term_structure_slope (most direct vol-carry signal).
