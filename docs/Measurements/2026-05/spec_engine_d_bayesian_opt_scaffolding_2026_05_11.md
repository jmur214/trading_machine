# Spec — T-XXX: Engine D Bayesian-opt scaffolding (replace GA candidate search)

**Date drafted:** 2026-05-11 evening
**Status:** SPEC for approval. Implementation will be a separate dispatch (T-028 likely).
**Will be executed by:** Agent A or B once approved (~8-12 hr implementation).
**Output:** New `engines/engine_d_discovery/bayesian_optimizer.py` + tests + integration in `discovery.py:_run_ga_evolution` behind a config flag, default OFF.

---

## Why now

T-022 (gene-encoding extension) + T-024 (seed enrichment) made the post-T-006/T-014 vocabulary REACHABLE from Discovery's candidate generation. T-023 made per-candidate evaluation tractable (1,000-2,500× Gate 1 speedup). With vocabulary and wall-time solved, the SEARCH STRATEGY itself becomes the next bottleneck.

T-025's empirical result: 30/30 candidates failed Gate 1 with the existing GA on substrate-honest. T-026 (B, in flight) re-runs cap=30 with `ga_population.yml` correctly reset to actually exercise T-022 + T-024 — but even if T-026 surfaces a promoted candidate, the GA's random-walk strategy is information-inefficient: it doesn't learn from prior evaluations to guide where to search next.

Per `docs/Sessions/Other-dev-opinion/05-09-26.md`: "**Bayesian optimization replacing GA (now possible with vocabulary fix done)**". Bayesian optimization fits a surrogate model (Gaussian Process or Tree-structured Parzen Estimator) of the gauntlet's pass/fail surface; each new candidate is chosen to maximize expected information gain. Result: fewer candidates needed to find gauntlet-clearers (if any exist).

This spec positions the T-028 implementation to dispatch immediately after T-026 lands, regardless of T-026's outcome:
- If T-026 promotes candidates → Bayesian opt makes the path faster (find more such candidates with fewer evaluations)
- If T-026 still 30/30 Gate 1 fail → Bayesian opt is the structural alternative; GA's random walk may have missed regions of search space where promotable candidates exist

---

## Design decisions

### 1. Library choice: **scikit-optimize (skopt)**

| Option | Pros | Cons |
|---|---|---|
| **scikit-optimize** *(recommended)* | scipy-based (already in deps); `Categorical`+`Real`+`Integer` dimensions natively; mature `gp_minimize` API; deterministic via `random_state`; lightweight (~10 MB) | API less polished than optuna; sparse community vs optuna |
| optuna | Modern; parallel trials; RDB storage; nicer pruning hooks | Larger dep (~50 MB); RDB storage layer adds complexity we don't need at cap=30-100; parallel trials don't help here (single-machine, sequential gauntlet) |
| Custom skopt-style GP from `statsmodels` | No new dep | 2-3× more impl work; reinventing well-tested library code |

**Recommended: scikit-optimize.** Add `scikit-optimize==0.10.x` to `requirements.txt` at implementation time.

Rationale: skopt's `gp_minimize` + `Categorical`/`Real`/`Integer` dimension API fits the gene-schema search space cleanly. Determinism via `random_state` is well-documented. No RDB. No parallel-trial complexity.

### 2. Search-space encoding: **conditional per-gene-type schema**

Bayesian opt typically operates over a flat parameter vector. Discovery's gene schema is non-flat:
- Outer choice: `gene_type` ∈ {technical, calendar, microstructure, intermarket, macro, earnings, behavioral, fundamental, foundry_feature, regime} (10 categories post-T-022)
- Per-type conditional schema: each type has its own `indicator`/`feature_id`/`operator`/`threshold` fields

Three encoding strategies:

| Strategy | Pros | Cons |
|---|---|---|
| **Conditional schema via skopt `Categorical` + dispatch** *(recommended)* | Single outer `gp_minimize` call; surrogate learns which gene_types are promising | Conditional sampling requires custom transform; skopt doesn't natively model dependent dimensions |
| One outer opt per gene_type | Cleaner per-type model | 10× the wall-time; cross-type selection becomes a meta-problem |
| Flatten all dimensions; mask-out via penalty | Single skopt run | Penalty terms distort the surrogate; surrogate wastes capacity learning the mask |

**Recommended: conditional schema with explicit dispatch.** The outer dimension is `gene_type` (`Categorical`); given a gene_type, the per-type dimensions activate. The objective function converts the skopt suggestion → a gene-shaped dict via a dispatch table that mirrors `_create_random_gene`'s structure.

Implementation sketch:

```python
from skopt.space import Categorical, Real, Integer
search_space = [
    Categorical(["technical", "calendar", "foundry_feature", ...], name="gene_type"),
    Categorical([...all technical indicators...], name="tech_indicator"),
    Categorical([...all foundry feature_ids...], name="foundry_feature_id"),
    Real(0.0, 100.0, name="threshold_pctile"),  # for percentile ops
    Real(-1.0, 1.0, name="threshold_raw"),       # for greater/less ops
    Categorical(["less", "greater", "top_percentile", "bottom_percentile"], name="operator"),
]
```

The objective function unpacks the suggested point, picks the right fields based on `gene_type`, constructs a gene dict, runs the gauntlet, returns the score.

Multi-gene genomes (1-4 genes per candidate) are handled by running 1-4 independent Bayesian opt suggestions per candidate and combining; or by extending the search space to N parallel single-gene dimensions where N=`max_genes`. **Recommended: combine 1-4 independent suggestions** to keep the search space dimensionality manageable (otherwise the space explodes combinatorially).

### 3. Objective function: **cumulative gate-passage margin** (Option B)

```python
def objective(genome) -> float:
    """Lower is better (skopt minimizes). Returns negative margin so
    surrogate learns to maximize gate-passage."""
    gauntlet_result = validate_candidate(genome)
    margin = 0.0
    for gate in ["gate_1", "gate_2", "gate_3", "gate_4", "gate_5", "gate_6", "gate_7", "gate_8"]:
        if gate not in gauntlet_result.gates_run:
            break  # candidate died at an earlier gate
        m = gauntlet_result.metrics[gate]
        t = gauntlet_result.thresholds[gate]
        # Normalize margin to threshold scale so different gates contribute comparably
        margin_norm = (m - t) / max(abs(t), 1e-6)
        if gauntlet_result.gates_passed[gate]:
            margin += margin_norm    # reward survival
        else:
            margin += margin_norm / 10  # small reward for getting close; lambda-tunable
            break
    return -margin  # skopt minimizes; we want to MAXIMIZE margin
```

Edge cases:
- Candidate dies at Gate 1: margin = (gate_1_contribution - 0.1) / 0.1. If contribution = 0.05 → margin = -0.5. Bayesian opt learns to push contribution UP.
- Candidate clears all 8 gates: margin = sum across all 8 normalized margins, all positive. Bayesian opt prioritizes higher cumulative margin.
- Candidate dies at Gate 6 (factor decomp): margin = sum across Gates 1-5 positives + Gate 6 negative margin (small contribution).

This continuous scalar is well-suited for GP surrogate modeling — smooth (gates pass/fail at thresholds, not discontinuously), bounded (each gate's margin scales with threshold), interpretable (negative = failed earlier; large positive = cleared with cushion).

**Alternative simpler objective: `total_gates_passed (0-8)`** as discrete. Easier to reason about, but loses information about HOW close failed candidates are to passing. Use as fallback if cumulative-margin objective surfaces numerical issues during implementation.

### 4. Acquisition function: **Expected Improvement (EI)**

EI is skopt's default and gives a balance of exploration (high-variance unexplored regions) vs exploitation (high-mean known-good regions). UCB and PI are documented as alternatives; default to EI.

Skopt default: `acq_func="gp_hedge"` which auto-mixes EI/UCB/PI. **Recommended: explicit `acq_func="EI"`** for reproducibility — `gp_hedge` introduces an additional randomness layer that complicates determinism guarantees.

### 5. Warm-start strategy: **from post-T-024 enriched GA population (after T-026)**

After T-026 lands, the `data/governor/ga_population.yml` will have a freshly-seeded population with T-022 + T-024 enrichments. The Bayesian optimizer should:

1. Load this population at init.
2. For each genome, encode its gene-shape into a point in the Bayesian-opt search space.
3. Use the gauntlet results from T-026 (if available in `ga_population.yml`'s `fitness_cache`) as the objective values at those points.
4. Fit the initial surrogate model on this warm-start data.
5. Suggest the next candidate via EI on the warm-start surrogate.

If `fitness_cache` is empty (no prior evaluations), Bayesian opt cold-starts with `n_initial_points=10` random suggestions before fitting the surrogate (skopt default).

**Recommended: WARM-START enabled by default.** Documented as `bayesian_warm_start: bool = True` in config; default ON; flag-OFF available for clean cold-start A/B comparisons.

### 6. Determinism guarantee

Skopt's stochasticity has two sources:
- Surrogate GP fit: deterministic given identical training data + `random_state`
- Acquisition optimization: skopt samples random points inside the acquisition surface; deterministic given `random_state`

Strategy:
- Pass `random_state=int(os.environ.get("PYTHONHASHSEED", 0))` to `gp_minimize` / `Optimizer.__init__`
- For warm-start, sort the loaded warm-start points by a stable key (e.g., candidate_id) before passing to skopt so the order is bit-stable across runs
- Verify with the standard 2-run determinism harness: same input → same suggested-candidate sequence + same gauntlet outcomes

**Risk: skopt's internal multi-start LBFGS for acquisition optimization may have float-precision non-determinism on Apple Silicon vs x86.** Mitigation: pin `random_state` and validate the determinism harness on the actual deployment target. If non-determinism is observed, drop back to `acq_optimizer="sampling"` (slower but fully deterministic).

### 7. Integration point: **replace `_run_ga_evolution` with `_run_search` dispatch**

Current call path (`discovery.py:204-208`):
```python
# 2. Composite Evolution via Genetic Algorithm
ga_candidates = self._run_ga_evolution(n_mutations)
candidates.extend(ga_candidates)
```

Proposed post-T-028 call path:
```python
# 2. Composite Evolution — GA or Bayesian opt per config flag
if self.cfg.get("use_bayesian_opt", False):
    search_candidates = self._run_bayesian_opt(n_mutations)
else:
    search_candidates = self._run_ga_evolution(n_mutations)
candidates.extend(search_candidates)
```

`_run_bayesian_opt(n_mutations)` is the new method that:
1. Instantiates `BayesianOptimizer(...)` (new class)
2. Optionally warm-starts from `ga_population.yml`'s fitness_cache
3. Iteratively calls `optimizer.suggest_next_candidate()` → builds genome → runs gauntlet → reports score back
4. Returns `n_mutations` candidate specs in the same shape as `_run_ga_evolution` returns

The `BayesianOptimizer` class wraps skopt's `Optimizer` with:
- The conditional search-space encoding (#2)
- Genome decoder (suggestion-point → gene dict)
- Objective function (gauntlet → cumulative margin)
- Warm-start loader

API surface change: ZERO downstream impact. `_run_bayesian_opt` returns the same list-of-dicts shape as `_run_ga_evolution`. Calling code in `evolution_controller.py` and beyond is untouched.

### 8. Backwards compatibility

Add a config flag `use_bayesian_opt: bool = False` in `data/governor/governor_settings.json` (or `config/discovery_settings.json` if Discovery has its own config). Default OFF.

Initial ship: Bayesian opt code lives in tree but is dormant. A/B harness (item #9 below) verifies it produces SAME or BETTER candidate quality than GA before flag is flipped to default ON.

Rollback safety: if Bayesian opt produces worse candidates or breaks determinism, flag-OFF reverts to GA cleanly. GA code is NOT removed by T-028 — it's the safe-fallback.

### 9. A/B verification harness

Reuse `scripts/run_discovery_diagnostic.py` with a new `--bayesian-opt` flag:

```bash
# Baseline: GA at cap=30 (matches T-026 if T-026 ran post-T-024 reset)
PYTHONHASHSEED=0 python -m scripts.run_discovery_diagnostic \
    --window 2021-2024 --batch 30 --substrate-honest --apply-journal-at-end \
    --out-dir docs/Audit

# Treatment: Bayesian opt at cap=30
PYTHONHASHSEED=0 python -m scripts.run_discovery_diagnostic \
    --window 2021-2024 --batch 30 --substrate-honest --apply-journal-at-end \
    --bayesian-opt --out-dir docs/Audit
```

Comparison metrics:
- **Promoted candidates**: how many cleared all 8 gates? (Primary)
- **Per-gate pass rate**: did Bayesian opt push more candidates past Gate 1 / Gate 3 / etc.?
- **Gene-type diversity**: did Bayesian opt's surrogate exploit foundry_feature genes more efficiently than GA's random walk?
- **Wall-time per candidate**: Bayesian opt's surrogate update + acquisition optimization adds overhead; verify it's < 30 sec per candidate (small vs Gate 1's now-cached ~3 sec, but worth measuring)

Verdict bucket (per CLAUDE.md non-negotiable 6 — report ci_low on all rates):
- **Bayesian opt promotes ≥1 candidate; GA promotes 0 (within CI)**: Bayesian opt is the structural fix. Flip flag default to ON in a follow-up dispatch.
- **Both promote 0**: search strategy isn't the bottleneck; Gate 1 threshold is (already T-025's finding). Bayesian opt ships flag-OFF for future re-eval when other axes change.
- **Bayesian opt's gate-pass rate > GA's at intermediate gates**: directionally promising but not yet decisive. Flag-OFF, document, dispatch a longer-window or larger-cap run.
- **Bayesian opt's wall-time per candidate is materially higher AND gate-pass rate isn't better**: scaffolding cost not worth it. Drop, document, revisit if Gate 1 threshold changes.

### 10. Acceptance criteria for the T-028 implementation dispatch

T-028 brief should require:

1. **Code:**
   - `engines/engine_d_discovery/bayesian_optimizer.py` — new (`BayesianOptimizer` class)
   - `engines/engine_d_discovery/discovery.py` — modified: `_run_search` dispatch in place of `_run_ga_evolution` call (1-line conditional, ~5-line method addition)
   - `requirements.txt` — `scikit-optimize==0.10.x` added
   - `config/discovery_settings.json` or `data/governor/governor_settings.json` — `use_bayesian_opt: false` flag added
   - `scripts/run_discovery_diagnostic.py` — `--bayesian-opt` CLI flag

2. **Tests** (`tests/test_engine_d_bayesian_optimizer.py`):
   - `test_bayesian_opt_constructs_search_space` — `BayesianOptimizer` instantiates without crash, search space dimensions match expected schema
   - `test_bayesian_opt_suggests_valid_gene` — `suggest_next_candidate()` returns a gene dict that passes `_create_random_gene`'s output schema (decodable by composite_edge evaluator)
   - `test_bayesian_opt_is_deterministic` — same `random_state` + same warm-start = same suggestion sequence (bit-identical)
   - `test_bayesian_opt_warm_start_from_population` — warm-start with fake fitness_cache produces non-default first suggestion (the surrogate IS using prior data)
   - `test_bayesian_opt_handles_categorical_dimensions` — gene_type categorical sampling works across all 10 types
   - `test_bayesian_opt_with_flag_off_falls_back_to_ga` — config flag OFF preserves T-025 GA behavior bit-identically
   - `test_objective_function_normalizes_gate_margins` — cumulative-margin objective produces continuous scalar in expected range

3. **Determinism guard:**
   - `python -m scripts.run_discovery_diagnostic --bayesian-opt --batch=3` produces bit-identical candidate sequences across two runs at PYTHONHASHSEED=0
   - GA path with flag-OFF produces bit-identical canon md5 to T-026's pre-flag baseline

4. **A/B audit doc** at `docs/Measurements/2026-05/discovery_bayesian_opt_ab_2026_05_12.md`:
   - GA baseline vs Bayesian opt at cap=30, same window, same substrate
   - Histogram + per-gate pass-rate comparison
   - Promoted-candidate count + bootstrap CI on promotion rate
   - Verdict bucket per #9 above

5. **No engine code outside Engine D** modified. Engine B / live_trader / mode_controller untouched.

---

## Hard constraints

- **DO NOT rip out the GA.** Bayesian opt is the alternative behind a flag. GA stays as the default until A/B verifies Bayesian opt is at least as good.
- **DO NOT add a dependency in this spec.** The library recommendation (skopt) is documented; the actual `pip install` and `requirements.txt` modification happens in T-028.
- **DO NOT change the 8-gate gauntlet thresholds.** Bayesian opt operates over the SAME search space as GA; gate thresholds stay as-is. The gate threshold reconsideration is a separate axis (T-025's recommendation #3) and a separate dispatch.
- **DO NOT modify Engine B, Engine F, live_trader, or backtest_controller.** Spec is Engine D scope only.
- **DO NOT auto-promote candidates.** Discovery's lifecycle (journal-mode + director review) is unchanged; this is candidate-generation extension only.
- **DO NOT skip the A/B harness in T-028.** Per the discipline framework: any structural search-strategy change requires empirical A/B verification before flag-flip.

## Time-budget estimate for implementation (T-028)

| Work item | ETA |
|---|---:|
| BayesianOptimizer class + search-space encoding | 3 hr |
| Objective function (cumulative margin) + edge cases | 1 hr |
| Warm-start from ga_population.yml | 1 hr |
| Config flag + discovery.py dispatch | 30 min |
| Tests (7 unit + 1 determinism guard) | 2 hr |
| A/B verification run (cap=3 smoke + cap=30 if smoke OK) | ~6 hr (cap=30 backtest dominates; Bayesian opt itself <5 min) |
| Audit doc + commit + push + outbox | 1 hr |
| **Total** | **~12-14 hr** |

T-028 may benefit from being split into two dispatches: T-028a (code + unit tests + cap=3 smoke, ~6 hr) and T-028b (cap=30 A/B + audit doc, ~7 hr). Recommend single dispatch if agent has uninterrupted ~14 hr of wall-time; otherwise split.

---

## Open questions for the implementation agent

1. **Multi-gene genome strategy.** This spec recommends combining 1-4 independent single-gene suggestions per candidate. Alternative: encode N parallel single-gene dimensions in one outer skopt search. The combinatorial explosion of the latter is the main concern; combined-suggestions strategy mirrors the GA's per-genome structure more directly. T-028 implementer: prototype both, pick the cleaner.

2. **Direction (long/short/market_neutral) encoding.** Should `direction` be part of the Bayesian-opt search space, or sampled randomly per the GA convention (80/10/10)? Recommended: sampled randomly (matches GA), keeps direction out of the surrogate model. Direction has only 3 possible values and isn't a continuous improvement axis.

3. **Surrogate model: GP vs random forest.** Skopt supports both. GP is the default and works well for continuous + categorical mixed search spaces of this dimensionality (~10-15 dimensions). RF is recommended for higher-dimensional / mixed-with-many-categoricals spaces. Default: GP. T-028 implementer: smoke RF on cap=3 if GP fits/predicts are slow.

4. **Fitness_cache invalidation.** When the gauntlet thresholds OR active edge set change, the fitness_cache from prior runs is stale (each candidate's gate-passage margin was computed against a different gauntlet). T-028 should invalidate fitness_cache OR store a gauntlet-config hash with each cached entry. Recommended: store gauntlet-config hash, only use warm-start entries with matching hash.

5. **Termination criterion.** Bayesian opt typically runs N iterations OR until acquisition improvement plateaus. Recommend N=cap (e.g., 30) for direct comparison with GA. Plateau-detection is a nice-to-have for future T-029.

6. **Tracking surrogate quality.** During the run, the surrogate's prediction error on observed candidates is a meta-metric: if the surrogate's MAE on training data is high, the search space encoding may be too noisy/dimensional. Surface this in the audit doc so we can iterate on the encoding.

---

## Connection to broader engines-first arc

| Dispatch | Status | Contribution |
|---|---|---|
| T-022 | DONE | Foundry vocabulary reachable to gene factory |
| T-023 | DONE | Gate 1 caching, 1000-2500× speedup |
| T-024 | DONE | GA seed-population enrichment |
| T-025 | DONE | Full-stack Discovery dispatch, 30/30 Gate 1 fail, scope-deviation surfaced |
| T-026 | IN FLIGHT | ga_population.yml isolation fix + re-run with fresh state |
| **T-027 (this spec)** | **DRAFTING** | **Bayesian opt scaffolding spec** |
| T-028 | QUEUED | Bayesian opt implementation per this spec |
| T-029 | FUTURE | Gate 1 threshold reconsideration (tier-aware, correlation-adjusted) |

The Bayesian opt dispatch (T-028) is the **search-strategy axis** of the engines-first Engine D arc. The Gate 1 threshold dispatch (T-029, separate) is the **gauntlet-threshold axis**. Both are independent improvements that can compound — if both surface promoted candidates on substrate-honest, the engines-first edge-expansion path is empirically validated.
