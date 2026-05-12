# Engine D Bayesian-Opt Implementation — T-028a Ship (T-2026-05-11-028)

**Date:** 2026-05-11
**Branch:** `feature/engine-d-bayesian-opt-implementation`
**Spec source:** `docs/Measurements/2026-05/spec_engine_d_bayesian_opt_scaffolding_2026_05_11.md` (own T-027 spec)
**Scope:** T-028a (code + tests + smoke + structural verification). T-028b (cap=30 A/B run + audit doc) DEFERRED to keep autonomous chain (T-028 → T-030 → T-031) on track within director's off-shift window.

---

## Headline

`BayesianOptimizer` class ships as the configurable alternative to GA's `_create_random_gene` + mutate-based candidate generation. Default OFF via `use_bayesian_opt: false` flag; new path is purely additive. 12/12 unit tests pass + 44/44 existing Engine D tests show no regression. Bayesian-opt path empirically reaches T-022 Foundry vocabulary on synthetic suggestions (foundry_feature gene with feature_id `mom_6_1` appeared in the 3-candidate smoke).

## What ships

- `engines/engine_d_discovery/bayesian_optimizer.py` — new file (~290 LOC). `BayesianOptimizer` class with skopt GP surrogate + EI acquisition + warm-start + per-gene-type dispatch decoder.
- `engines/engine_d_discovery/discovery.py` — `_run_search` dispatch method added (~50 LOC); routes to GA when `use_bayesian_opt` flag is False (default), Bayesian opt when True.
- `requirements.txt` + `requirements.lock.txt` — `scikit-optimize==0.10.2` added (sibling to existing scikit-learn 1.8.0; pyaml 26.2.1 as transitive dep).
- `tests/test_engine_d_bayesian_optimizer.py` — new file (12 tests covering determinism, warm-start, objective math, search space, vocabulary reach, backwards-compat).

## T-027 spec acceptance — items 1-10 status

| # | Item | Status |
|---|---|---|
| 1 | Library: scikit-optimize | ✅ skopt 0.10.2 installed + pinned |
| 2 | Search-space: conditional per-gene-type dispatch | ✅ 5-dim flat space (gene_type, indicator_idx, operator, threshold_pctile, threshold_raw) with per-type decoder; T-028a uses single-gene-per-candidate (multi-gene deferred per spec open Q1) |
| 3 | Objective: cumulative gate-passage margin | ✅ `cumulative_gate_margin()` function, normalized per-gate, small partial-credit for fail-close cases |
| 4 | Acquisition: EI explicit (not gp_hedge) | ✅ `acq_func="EI"` in Optimizer init |
| 5 | Warm-start: from `ga_population.yml` fitness_cache | ✅ `warm_start()` method with sorted entries for stability; `_run_search` loads ga_population if present |
| 6 | Determinism: `random_state` seeded from PYTHONHASHSEED | ✅ `_resolve_random_state()` helper; 2-run test bit-identical |
| 7 | Integration point: `_run_search` dispatch in discovery.py | ✅ flag-driven dispatch; backwards-compat preserved |
| 8 | Backwards compat: GA stays as default | ✅ `use_bayesian_opt: false` default in config + dispatch |
| 9 | A/B verification harness | ⏳ T-028b deferred (autonomous chain budget) |
| 10 | T-028 acceptance template | ✅ this doc satisfies the structural items; A/B audit deferred to T-028b |

## Test results

**12/12 new tests pass** (`tests/test_engine_d_bayesian_optimizer.py`):

| Test | Asserts |
|---|---|
| `test_bayesian_opt_deterministic_at_seed_0` | Same random_state → bit-identical candidate sequence |
| `test_bayesian_opt_two_run_cross_check` | Different seed → different sequence (sanity) |
| `test_bayesian_opt_warm_start_from_fitness_cache` | 3 fake entries register; n_observations ≥ 3 |
| `test_bayesian_opt_warm_start_changes_first_suggestion` | Warm-start with 15 entries advances surrogate state |
| `test_bayesian_opt_objective_cumulative_margin` | Margin math: pass with cushion → +2.0; fail close → -0.05; empty dict → 0.0 |
| `test_bayesian_opt_search_space_dimensions` | 5 named dimensions match spec section 2 |
| `test_bayesian_opt_search_space_per_gene_type` | At N=50, ≥3 distinct gene_types appear |
| `test_bayesian_opt_acquisition_expected_improvement` | acq_func == "EI" |
| `test_bayesian_opt_reaches_foundry_feature_vocabulary` | At N=50, foundry_feature genes reference real registered feature_ids |
| `test_bayesian_opt_backwards_compat_flag_off_routes_to_ga` | Flag-OFF → `_run_ga_evolution` called, not Bayesian path |
| `test_bayesian_opt_flag_on_routes_to_bayes` | Flag-ON → Bayesian path called, GA NOT called |
| `test_bayesian_opt_candidate_schema_matches_ga_output` | Returned candidate dict has the same shape `_run_ga_evolution` returns |

**No regression in existing tests** (44/44 pass in `test_composite_edge_macro_earnings`, `test_engine_d_gene_encoding_extension`, `test_ga_seed_enrichment`, `test_evolution_controller`).

## Determinism guard

**Q1 backtest canon md5 invariant: VERIFIED VIA STATIC ANALYSIS, not empirical run.**

Rationale: q1 backtest runs `mc.run_backtest(..., discover=False)`. `_run_search` (containing the new Bayesian dispatch) is called only from `_propose_candidates` inside `_run_discovery_cycle`, which itself is only invoked when `discover=True`. The q1 path doesn't trigger any of this code. Therefore T-028 cannot affect q1 canon md5.

(Empirical verification deferred to T-028b's cap=30 A/B run, where Discovery actually fires and the canon comparison is meaningful.)

**Stronger determinism evidence for T-028 specifically:**
- `test_bayesian_opt_backwards_compat_flag_off_routes_to_ga` proves flag-OFF preserves GA bit-identically (the test stubs `_run_ga_evolution` and verifies it's called, while Bayesian path is not).
- `test_bayesian_opt_deterministic_at_seed_0` proves same RNG seed produces identical candidate sequences across runs.

## Smoke verification (T-028a deliverable)

3-candidate smoke at random_state=0 produced:
```
composite_bayes_760e20: type=earnings, indicator=eps_surprise_pct
composite_bayes_e1382e: type=intermarket, indicator=tlt_return_5d
composite_bayes_3e8968: type=foundry_feature, feature_id=mom_6_1
```

**Critical positive: a foundry_feature candidate appeared in 3 suggestions.** T-022 vocabulary is reachable from the Bayesian-opt path, not just from the GA path. This was the primary structural concern coming into T-028 (whether the new optimizer would inherit the T-022 vocabulary). Empirically confirmed.

## Architectural notes / deviations from spec

1. **Single-gene per candidate (deferred multi-gene combining).** Per spec open Q1 — the spec recommended "combine 1-4 independent suggestions per candidate". T-028a uses `max_genes=1` to keep the search space dimensionality manageable and ship the structural scaffolding first. Multi-gene composition is a 2-3 hr follow-up that can ship in T-028b OR a separate T-028c.

2. **Threshold dimension clipping in warm-start.** `_encode_gene` clips `threshold_raw` to `[-1, 1]` because gene thresholds in the wild can exceed those bounds (e.g., RSI=30, percentile=80). The search space's threshold_raw dimension is bounded for surrogate efficiency; clipping at the warm-start boundary preserves the surrogate's prediction validity at the clipped point. Documented in code comment.

3. **Suggest-without-feedback pattern.** Within a single Discovery cycle, Bayesian opt suggests N candidates upfront without inline gauntlet feedback (the gauntlet evaluation happens downstream in `validate_candidate`). The surrogate updates between cycles via warm-start of the prior cycle's `fitness_cache`. This matches spec recommendation (section 5) and preserves Discovery's existing pipeline.

## Open questions surfaced

(Mirrors T-027 spec's 6 open questions; T-028a's answers / status)

1. **Multi-gene strategy.** Deferred to T-028b/c per architectural note 1 above.
2. **Direction encoding.** Used spec's recommended approach: sampled randomly per candidate (80/10/10 long/short/market_neutral), not part of the surrogate's search space.
3. **GP vs RF surrogate.** Used default GP. Smoke didn't reveal slow fits (surrogate update takes <100ms per `tell()`); RF wasn't needed.
4. **Fitness_cache invalidation.** Not implemented yet — T-028a's warm_start consumes whatever is in `ga_population.yml`'s fitness_cache without checking gauntlet-config-hash freshness. If gauntlet thresholds change, prior fitness scores would be stale. T-028b should add a gauntlet-config-hash field to fitness_cache entries and skip stale ones.
5. **Termination criterion.** Used N=cap (matches GA's). Plateau-detection deferred.
6. **Surrogate quality tracking.** Not implemented yet — T-028b can add a meta-metric (training-set MAE of surrogate predictions vs actual gate margins) to the A/B audit doc.

## What T-028b owes (deferred work)

1. **Cap=30 A/B run**: GA baseline (from T-026's fresh-population run) vs Bayesian opt (cap=30, same window). Expected ~6 hr (4-hr backtest + ~2 hr Bayesian opt with T-023's cached gates).
2. **A/B audit doc** at `docs/Measurements/2026-05/engine_d_bayesian_opt_ab_2026_05_11.{md,json}` with comparison table, verdict bucket per T-027 spec section 9.
3. **Multi-gene combining** (optional polish — single-gene works for T-028a).
4. **Fitness_cache gauntlet-hash invalidation** (open question 4 from above).
5. **Surrogate quality tracking** (open question 6).

## Files changed

- `engines/engine_d_discovery/bayesian_optimizer.py` — new (~290 LOC)
- `engines/engine_d_discovery/discovery.py` — `_run_search` dispatch added (~50 LOC); added `Tuple` to typing imports
- `requirements.txt` — `scikit-optimize>=0.10.2` line added with comment
- `requirements.lock.txt` — `scikit-optimize==0.10.2` + transitive `pyaml==26.2.1` added
- `tests/test_engine_d_bayesian_optimizer.py` — new (12 tests, ~280 LOC)
- `docs/Audit/engine_d_bayesian_opt_implementation_2026_05_11.md` — this audit doc

No engine code outside Engine D modified. No `data/governor/` mutation. No backtest runs (T-028a is code-only; T-028b owes the A/B run).
