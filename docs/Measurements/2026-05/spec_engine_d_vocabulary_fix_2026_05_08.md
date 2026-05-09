# Spec — T-2026-05-08-006: Engine D Vocabulary Fix (Foundry + Fundamentals-Percentile Operators)

**Date drafted:** 2026-05-08
**Status:** SPEC for approval. Substrate-independent (T-002 has `discover=False`).
**Will be executed by:** Agent B once T-005 completes (~3-5 hr).
**Output:** `engines/engine_d_discovery/feature_engineering.py` + new tests + audit doc at `docs/Audit/engine_d_vocabulary_expansion_2026_05_08.md`.

---

## Why now

R1's pushback on the Bayesian-opt-replaces-GA recommendation: *"A different optimizer over the same narrow space won't help."* Engine D's current Discovery vocabulary is technical-only — RSI, ATR, Bollinger, MACD, ADX, momentum-ROC, plus cross-sectional percentile ranks of those (`feature_engineering.py:107-124`). No fundamentals. No regime-conditional features. No calendar features. No COT positioning. No FRED macro.

Meanwhile, `core/feature_foundry/features/` ships ~30 Foundry features (mom_12_1, realized_vol_60d, beta_252d, dist_52w_high, drawdown_60d, vol_regime_5_60, ma_cross_50_200, skew_60d, days_to_quarter_end, weekday_dummy, hyg_lqd_spread, dxy_change_20d, vvix_or_proxy, dispersion_60d, correlation_average_60d, moving_avg_distance_50d, high_minus_low_60d, cot_commercial_net_long, calendar_anomaly_v1 inputs, etc.) — none of which Engine D's TreeScanner can reach.

**Vocabulary fix is the prerequisite to any Bayesian opt swap.** A wider search space matters more than a smarter searcher.

---

## What

Two additive changes to Engine D, both confined to `engines/engine_d_discovery/feature_engineering.py`:

### Change 1: Foundry feature ingestion

Extend `compute_features` to consume the Foundry registry. Specifically:

1. At init time, force-import `core.feature_foundry.features` so all `@feature` decorators self-register.
2. Inside `compute_features` (or a new method `_compute_foundry_features`), call `get_feature_registry().list_features(tier=None)` and iterate the available Foundry features.
3. For each Foundry feature with a `tier` of `"A"` or `"B"` (skip `tier="adversarial"`), evaluate it on the per-ticker per-date grid that Engine D's tree scanner consumes. Add the result as a new column with prefix `Foundry_<feature_id>`.
4. Skip any Foundry feature whose data source is unavailable (the feature returns `None`); don't crash. Engine D should fail-soft on missing-data features.

### Change 2: Fundamentals-percentile-rank operators

The fundamentals panel is built by `engines/data_manager/fundamentals/simfin_adapter.py` (or its production successor). For each fundamentals column the panel exposes (P/E, P/B, ROE, gross profitability, accruals — the V/Q/A factors), add a corresponding **cross-sectional percentile-rank column** that ranks the universe per date.

Naming convention: `XS_<RawCol>_Pctile`. So `pe_ratio` → `XS_PE_Ratio_Pctile`, `book_to_market` → `XS_Book_To_Market_Pctile`, etc.

Implementation approach: extend `compute_cross_sectional_features` (already at `feature_engineering.py:80-127`) to also pick up fundamentals columns when present in the input DataFrame.

---

## Why both changes (not just one)

- **Foundry ingestion alone**: gives Discovery access to the calendar, regime, and macro features but doesn't give it cross-sectional fundamentals rankings (which are the V/Q/A factor primitives).
- **Fundamentals-percentile alone**: gives Discovery the V/Q/A vocabulary but misses the calendar/regime/macro library.
- **Both together**: closes the entire vocabulary gap R1 flagged. Bayesian opt (or even the existing GA mutator) over this expanded space has a real chance of finding edges the current Engine D can't see.

---

## Acceptance

1. **Code changes:**
   - `engines/engine_d_discovery/feature_engineering.py` extended per the two changes above
   - No changes to other Engine D files — TreeScanner consumes whatever columns `feature_engineering` provides; the vocabulary expansion happens upstream of TreeScanner

2. **Tests:** new file `tests/test_engine_d_vocabulary_expansion.py` with at minimum:
   - `test_foundry_features_appear_in_engineered_columns` — instantiate `FeatureEngineering`, call on a small data_map, assert at least 5 `Foundry_*` columns appear
   - `test_foundry_missing_data_features_skipped_not_crashed` — patch a Foundry feature to return None for some tickers, confirm no exception, column either absent or NaN (acceptable)
   - `test_fundamentals_percentile_rank_added_when_panel_present` — feed a synthetic fundamentals panel with P/E values, assert `XS_PE_Ratio_Pctile` column exists and ranks correctly per date
   - `test_fundamentals_percentile_rank_skipped_when_panel_absent` — same call without fundamentals, assert no `XS_*_Pctile` columns get inserted erroneously
   - `test_existing_technical_features_still_present` — sanity: RSI, ATR, Bollinger, etc. still computed exactly as before

3. **Audit doc:** `docs/Audit/engine_d_vocabulary_expansion_2026_05_08.md`
   - Before/after column-count comparison: how many columns did `compute_features` produce on a sample data_map before vs after?
   - List of Foundry features that successfully integrated vs ones that failed (and why)
   - Forward-looking note: which previously-impossible candidate edges does this expansion now allow Discovery to find?

4. **Branch:** `feature/engine-d-vocabulary-expansion`. Push to branch only; director merges.

5. **Determinism guard:** running the existing test suite (especially `tests/test_engine_d_*` and `tests/test_feature_foundry*`) post-change must still pass. New Foundry imports shouldn't pollute test fixtures — `test_feature_foundry.py`'s autouse fixture should still snapshot/restore the registry correctly.

---

## Hard constraints

- DO NOT modify Engine B (Risk) or `live_trader/`
- DO NOT modify TreeScanner or any code outside `feature_engineering.py` (and the new test file)
- DO NOT add new dependencies (use existing `core.feature_foundry`, `pandas`, `numpy`)
- DO NOT auto-promote any feature (no edges.yml mutations) — this is a vocabulary-expansion task; whether new edges get DISCOVERED on the new vocabulary is the next discovery cycle's job
- Branch: `feature/engine-d-vocabulary-expansion`; do NOT merge to main (B is a worker, director merges)
- Time budget: 3-5 hr

---

## Sequencing

- T-005 must complete first (B is on it). T-006 starts when B's outbox shows T-005 DONE.
- Substrate-independent — runs in parallel with A's T-002 substrate measurement.
- After T-006 merges, the next dispatchable item is T-007 (diversified-futures trend) or any post-T-002 task (T-003 / T-004 C-collapses items).

---

## Open questions for the agent (to surface in the audit doc, not block)

1. Some Foundry features have a `horizon` field (e.g., `horizon=5` for cot_commercial_net_long). Does Engine D need to respect that (i.e., shift the feature's value forward by `horizon` bars to align with target)? My read: yes for forward-looking targets, but TreeScanner's target framing should drive that — agent investigates and documents.
2. Tier `"B"` Foundry features are not yet validated for production. Should T-006 ingest them or only tier-A? My read: ingest both for vocabulary breadth; tier filtering happens at promotion time, not ingestion.
3. The cross-sectional percentile rank requires fundamentals to be aligned per date. The current panel may have publish-date vs calendar-date misalignment. Agent should use the **as-of** date convention already established in `engines/engine_a_alpha/edges/_fundamentals_helpers.py` rather than reinvent it.
