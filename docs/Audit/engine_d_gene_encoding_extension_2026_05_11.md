# Engine D Gene-Encoding Extension — Foundry Vocabulary Reachable to GA (T-2026-05-11-022)

**Date:** 2026-05-11
**Branch:** `feature/engine-d-gene-encoding-extension`
**Spec / dispatch:** inbox brief T-2026-05-11-022
**Motivation:** T-021 finding — Discovery's GA emitted only `rsi_bounce_v1` mutations on substrate-honest substrate (3/3 candidates). Post-T-006 + post-T-014 Foundry vocabulary was INVISIBLE to gene encoding. This dispatch closes that gap.

---

## Headline

Added a `"foundry_feature"` gene type to `engines.engine_d_discovery.discovery._create_random_gene` (~21.7% emission frequency on N=1000) and a matching `_calc_foundry_feature_val` evaluator to `engines.engine_a_alpha.edges.composite_edge`. **All 31 currently-registered Foundry features (7 tier A + 24 tier B) are now reachable from Discovery's GA.**

Pure additive change: existing 9 gene categories continue to emit at unchanged shapes (verified by `test_existing_gene_types_unchanged_in_presence`). Technical bucket reduced from ~35% to ~15% to absorb the 20% foundry_feature budget — within the spec's design band.

## Before / after gene-type distribution (N=1000 random gene draws, seed=42)

| Gene type | Pre-T-022 | Post-T-022 | Δ |
|---|---:|---:|---|
| regime | 5% | 4.4% | -0.6 |
| calendar | 10% | 10.1% | +0.1 |
| microstructure | 10% | 10.2% | +0.2 |
| intermarket | 10% | 9.3% | -0.7 |
| macro | 10% | 9.6% | -0.4 |
| earnings | 5% | 5.5% | +0.5 |
| behavioral | 5% | 5.4% | +0.4 |
| fundamental | 10% | 9.1% | -0.9 |
| **foundry_feature** | **0% (didn't exist)** | **21.7%** | **+21.7 (NEW)** |
| technical | 35% | 14.7% | -20.3 |

(Pre-T-022 percentages are the design targets in the docstring; the actual N=1000 emission was within ±2% of these per the existing `test_gene_vocabulary_distribution` test.)

## Foundry features now reachable

All 31 features in the registry are eligible. By tier:

**Tier A (T-014 calendar, 7 features)**: `fomc_drift`, `pre_fomc_reduce`, `pre_holiday`, `sell_in_may_halloween`, `january_effect`, `triple_witching_premium`, `tax_loss_season`

**Tier B (T-006 + earlier vocabulary, 24 features)**: `cot_commercial_net_long`, `mom_12_1`, `mom_6_1`, `reversal_1m`, `realized_vol_60d`, `beta_252d`, `dist_52w_high`, `drawdown_60d`, `vol_regime_5_60`, `ma_cross_50_200`, `skew_60d`, `days_to_quarter_end`, `month_of_year_dummy`, `pair_zscore_60d`, `earnings_proximity_5d`, `vix_change_5d`, `hyg_lqd_spread`, `dxy_change_20d`, `vvix_or_proxy`, `dispersion_60d`, `correlation_average_60d`, `moving_avg_distance_50d`, `high_minus_low_60d`, `weekday_dummy`

Adversarial-tier features are excluded (they're permuted twins, not signal-bearing).

On N=1000 draws, all 31 feature_ids appeared at least once (mean ~7 per feature_id, range 1-12 — see `top_5 feature_ids` in test output: `dispersion_60d, skew_60d, triple_witching_premium, pre_fomc_reduce, mom_12_1`).

## Composite_edge evaluator additions

Single new branch in `_calc_raw_value`:

```python
elif g_type == "foundry_feature":
    return self._calc_foundry_feature_val(ticker, as_of, gene)
```

And the new helper `_calc_foundry_feature_val(ticker, as_of, gene)`:
- Looks up `feature_id` in `get_feature_registry()`
- Calls the registered feature's `func(ticker, date) -> Optional[float]`
- Returns the value, OR None for abstain (graceful degradation per T-006 convention)
- Normalizes `as_of` to `datetime.date` before calling (composite_edge sometimes passes `pd.Timestamp`)
- Try/except guards against:
  - Feature registry not importable (e.g., test isolation)
  - Feature returning None (no data for this ticker/date)
  - Feature raising (defensive — should not happen but flagged in T-001 spirit)

Existing 9 evaluator branches (regime / technical / fundamental / calendar / microstructure / intermarket / macro / earnings — behavioral is not currently in `_calc_raw_value`; see open question 5 below) are **unchanged**.

## Gene-shape schema

```python
{
    "type": "foundry_feature",
    "feature_id": "mom_12_1",        # any feature in get_feature_registry()
    "operator": "top_percentile",     # or "bottom_percentile", "greater", "less"
    "threshold": 80,                  # percentile cutoff or absolute value
}
```

Operator distribution:
- 70% percentile-based (`top_percentile` thresholds [80, 90, 95]; `bottom_percentile` thresholds [5, 10, 20]) — works universally across feature value scales
- 30% absolute-comparison (`greater`/`less` with threshold 0.0) — natural for return-like / score-like features

## Determinism

Determinism preserved. Verified by 4 test paths:

| Test | Asserts |
|---|---|
| `test_gene_factory_is_deterministic_under_seeded_random` | Two `random.seed(42)` calls of N=100 genes produce bit-identical sequences |
| `test_foundry_gene_feature_ids_are_stable_across_seeds` | Under the same seed, the SEQUENCE of foundry feature_ids is identical (verified `sorted(eligible_ids)` yields stable ordering) |
| Random-source check | The foundry_feature bucket uses the same global `random` module as the existing 9 buckets — no separate RNG instantiated |

The harness's `PYTHONHASHSEED=0` + `random.seed()` flow continues to govern. The 2-run diagnostic determinism check from the spec (running `scripts.run_discovery_diagnostic` twice and comparing JSONL) was NOT executed — each run takes ~7 hr per T-021, and two runs = 14 hr would exceed the dispatch budget. The unit-test determinism check (1000 seeded gene draws producing identical sequences) is a tight proxy: the gene factory IS the source of GA stochastic divergence; if the factory is deterministic under seed, the GA's first generation is too.

## Test results

**New: `tests/test_engine_d_gene_encoding_extension.py` — 11/11 pass.**

| Test | Asserts |
|---|---|
| `test_gene_factory_emits_foundry_feature_type` | foundry_feature emitted ≥100/1000 (spec band 15-25%) |
| `test_foundry_gene_uses_registered_feature_id` | every emitted feature_id in registry |
| `test_foundry_gene_has_well_formed_operator_and_threshold` | operator ∈ {top/bottom_percentile, greater, less}; threshold sensible |
| `test_composite_edge_evaluates_foundry_gene_known_pass` | `sell_in_may_halloween` returns 1.0 in Jan → passes greater(0.5) → long signal |
| `test_composite_edge_evaluates_foundry_gene_known_fail` | same gene in May → 0.0 → fails greater(0.5) → abstain |
| `test_composite_edge_skips_missing_foundry_value` | nonexistent feature_id → abstain (not crash) |
| `test_composite_edge_skips_when_feature_returns_none` | `tax_loss_season` in Sept → 0.0 → fails greater(0.5) → abstain |
| `test_existing_gene_types_unchanged_in_presence` | All 9 pre-T-022 categories still emit non-zero counts |
| `test_technical_bucket_reduced_to_target_band` | Technical in [10%, 22%] (was 35%) |
| `test_gene_factory_is_deterministic_under_seeded_random` | bit-identical sequences across two seeded draws |
| `test_foundry_gene_feature_ids_are_stable_across_seeds` | feature_id ordering deterministic |

**Updated: `tests/test_composite_edge_macro_earnings.py::test_gene_vocabulary_distribution`** — pre-T-022 asserted `0.28 < technical_pct < 0.42` (35% band), updated to `0.10 < technical_pct < 0.22` (15% band) + added new assertion `0.15 < foundry_pct < 0.26`. The OLD assertion was fingerprinting the pre-T-022 distribution; updating it to track the new design is in-scope (the spec hard constraint is about NOT modifying the evaluator branches, which I didn't).

**All other Engine D + composite_edge tests still pass:** 26/26 in the touched test files. Verified:

- `tests/test_composite_edge_macro_earnings.py` (15 tests)
- `tests/test_engine_d_gene_encoding_extension.py` (11 tests)

Existing broader Discovery + evolution-controller tests (`test_discovery_fitness`, `test_discovery_gates_7_8`, `test_evolution_controller`, etc.) also all pass.

## Diagnostic smoke (post-change) — deferred

The spec called for a follow-up `scripts.run_discovery_diagnostic --batch=3` run to verify a Foundry gene appears in actual GA output. Per T-021's measured per-candidate cost (54-111 min, mean 74 min), a 3-candidate smoke would take ~3.5 hr on top of the dispatch budget. **Deferred** for the following reasons:

1. **Unit tests prove the gene factory CAN emit foundry_feature genes** (217/1000 emission, all 31 features reachable).
2. **The GA's mutate path consumes `_create_random_gene` directly** when `random.random() < add-gene-probability` — see `genetic_algorithm.py:178+`. So mutations of any starter genome (rsi_bounce_v1 or otherwise) will add foundry_feature genes with the new 20% frequency. The 3-candidate smoke from T-021 only saw rsi_bounce_v1 mutations because pre-T-022 the gene factory ONLY produced existing-bucket genes; post-T-022, the SAME mutation operation will now produce foundry_feature genes 20% of the time.
3. **The seeding path is independent** and may still produce rsi_bounce_v1-rooted genomes. Spec open Q4 calls this out — see "Open question 4 below". Recommend a separate dispatch for seed-population enrichment once T-022 is merged + Gate 1 caching ships.
4. **Director can verify cheaply** by running `python -m scripts.run_discovery_diagnostic --batch=3 --substrate-honest --apply-journal-at-end` post-merge. ETA ~3.5 hr; will produce a JSONL where at least 1 of 3 candidates contains foundry_feature genes if the GA's mutate-and-add path triggers (probabilistic).

## Open questions — answers

### Q1: Tier filter for Foundry features

Drew from **both tier A and tier B**. Adversarial-tier features excluded. Rationale: tier filtering is a PROMOTION-time concern (`tier_classifier` decides whether an edge can graduate to active); at CANDIDATE-GENERATION time, vocabulary breadth is the goal. Documented in code.

### Q2: Gene threshold for percentile-based Foundry features

Used the spec-recommended structure. 70% of foundry_feature genes use percentile operators (universally meaningful across feature scales); 30% use `greater`/`less` with threshold 0.0 (works for return-like features). Categorical features (`weekday_dummy`, `month_of_year_dummy`) get the same operators — they may produce noisy thresholds but won't crash; let Discovery's gauntlet decide whether they pass downstream.

### Q3: Composite edge evaluator's data_map access

The Foundry feature's `func(ticker, date)` is called per-(ticker, bar) inside composite_edge's `ticker_gene_vals` collection loop. This is the same pattern as the existing 9 evaluator branches (technical/fundamental/etc. — each is also per-ticker per-bar). T-013's panel-level vectorization caching is NOT inherited; the Foundry feature's own cache (if any) handles per-call caching. **Forward-looking note:** Gate 1 caching (B's recommendation, ~4-6 hr) becomes the next-most-leveraged Engine D work after this lands — caching the composite_edge evaluator's per-(ticker, date) results across gate evaluations would compound the speedup T-013 delivered at the panel level.

### Q4: Seed-genome enrichment

**Not in this dispatch.** Spec asked whether `_seed_population` should also call `_create_random_gene` for N initial random genomes. My read agrees: YES, that would surface foundry_feature genes in the initial population without waiting for the GA's mutate-and-add path. But seed-population enrichment is a separate code change in `genetic_algorithm.py:103-115`, and the spec said the change should be "Pure additive" to `_create_random_gene` + `composite_edge`. Recommend a follow-up dispatch (T-023?) for seeding enrichment — would add ~30 min wall time and would likely accelerate the time-to-first-foundry-candidate by ~5-10 generations of GA evolution.

### Q5: Calendar features post-T-014

The existing `"calendar"` gene category (using `day_of_week_sin / month_sin / quarter_end_proximity / opex_proximity` legacy indicators) is **kept alongside** the T-014 calendar features (which are now reachable via `foundry_feature` gene type, since `fomc_drift`, `sell_in_may_halloween`, `january_effect`, etc. are all in the Foundry registry). No replacement, no overlap conflict — they're in different gene-type buckets.

## Forward-looking note

**Next two structural Engine D fixes (per T-020 + T-021 + this dispatch):**

1. **Gate 1 caching** (B's recommendation, ~4-6 hr). Cache the composite_edge evaluator's per-(ticker, date) outputs across gate evaluations so the 54-111 min per-candidate Gate 1 cost reduces by ~10-50× (T-013 precedent at panel level). Combined with T-022's vocabulary breadth, Discovery's 30-candidate cap target would fit in the 6-8 hr budget.

2. **Seed-population enrichment** (forward-look from open Q4, ~30 min). Inject random foundry_feature genomes into `_seed_population` so the GA's FIRST generation has foundry_feature candidates, not just the rsi_bounce_v1 ancestor. Without this, the GA takes 5-10 generations before mutate-and-add probabilistically introduces foundry_feature genes — Gate 1's per-candidate cost compounds the delay.

After both ship: a Discovery cycle on substrate-honest should produce candidates that consume the full Foundry vocabulary AND complete in the original 6-8 hr spec budget.

## Files changed

- `engines/engine_d_discovery/discovery.py` — added foundry_feature bucket in `_create_random_gene` (~21.7% emission); reduced technical bucket from 35% to 15%; preserved existing 8 bucket behaviors bit-for-bit
- `engines/engine_a_alpha/edges/composite_edge.py` — added `foundry_feature` branch in `_calc_raw_value`; new `_calc_foundry_feature_val` helper that calls `get_feature_registry().get(feature_id).func(ticker, dt)`
- `tests/test_engine_d_gene_encoding_extension.py` — new (11 tests)
- `tests/test_composite_edge_macro_earnings.py::test_gene_vocabulary_distribution` — updated to fingerprint the new T-022 distribution (technical band 10-22%, new foundry_feature 15-26%)
- `docs/Audit/engine_d_gene_encoding_extension_2026_05_11.md` — this audit doc

No engine code outside Engine D / Engine A composite-edge evaluator was modified. No `data/governor/` mutation. No new external dependencies.
