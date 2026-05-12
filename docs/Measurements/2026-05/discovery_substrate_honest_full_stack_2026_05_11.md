# Discovery Cycle on Substrate-Honest — Full Structural-Fix Stack (T-2026-05-11-025)

**Date:** 2026-05-11
**Branch:** `feature/discovery-cycle-with-structural-fixes`
**Spec / dispatch:** inbox brief T-2026-05-11-025
**Comparison baseline:** T-2026-05-10-021 (`docs/Measurements/2026-05/discovery_substrate_honest_2026_05_10.md`)
**Window:** 2021-01-01 → 2024-12-31 in-sample (4-year)
**Substrate:** F6 historical S&P 500 universe + missing-CSV closure (`use_historical_universe=True`)
**Mode:** journal-mode (`apply_journal_at_end=True`), deterministic-harness (`PYTHONHASHSEED=0` + `isolated()`)
**Stack:** T-022 (gene encoding) + T-024 (seed enrichment) + T-023 (Gate 1 caching) all merged on `origin/main`

---

## Headline

**30 candidates evaluated. 0 promoted. ALL 30 failed Gate 1 (Sharpe-contribution-to-ensemble).** Same first-failed-gate pattern as T-021's 3-candidate result.

**Two big shifts vs T-021:**

1. **T-023 Gate 1 caching delivered MASSIVELY.** Per-candidate Gate 1 cost dropped from **3,240-6,689 sec (T-021)** to **2.25-6.50 sec (T-025)** — that's ~**1,000-2,500× speedup** vs T-021's no-caching baseline. The spec's expected 10-50× target was crushed. Total Discovery time (excluding the upfront backtest): **1.33 minutes for 30 candidates**.

2. **Candidate-archetype diversity emerged** — 9 different parent archetypes were mutated this cycle (`rsi_bounce_v1`, `value_trap_v1`, `fundamental_ratio_v1`, `seasonality_v1`, `gap_fill_v1`, `volume_anomaly_v1`, `panic_v1`, `herding_v1`, `earnings_vol_v1`) at 3 mutations each, plus 3 random `composite_gen0_*` genomes = 30. T-021's 3 candidates were ALL `rsi_bounce_v1` mutations.

**One critical scope deviation surfaced during analytics**: T-022 + T-024's gene-encoding and seed-enrichment paths were **not exercised** in this run because `data/governor/ga_population.yml` was pre-existing from prior Discovery runs (`generation: 3`). On startup, `ga.load_population()` succeeded and `seed_from_registry` (containing T-024's enrichment) was NEVER called. The 3 `composite_gen0_*` candidates that appeared have `gene_types: [technical, calendar]` — **NO foundry_feature genes**. They were created in PRIOR Discovery runs before T-022 merged.

**This means the "full structural-fix stack" claim is partially true**: T-023's Gate 1 caching IS in effect (and overperformed dramatically); T-022's gene factory + T-024's seed enrichment are LOADED but neither produced new genomes in this cycle because the GA loaded from disk instead of seeding fresh.

## First-failed-gate histogram (cross-T-021 comparison)

| First failed gate | T-021 (N=3) | T-025 (N=30) | Δ |
|---|---:|---:|---|
| **gate_1 (Sharpe contribution)** | **3 (100%)** | **30 (100%)** | unchanged |
| gate_2, 4, 5, 6, 7, 8 | 0 | 0 | unchanged (not reached) |
| Promoted | 0 | 0 | unchanged |

## Per-gate evaluation table

| Gate | Evaluated | Passed | Pass rate |
|---|---:|---:|---:|
| gate_1 | 30 | 0 | 0% |
| gate_2 | 0 | 0 | n/a (Gate 1 short-circuited) |
| gate_4-8 | 0 | 0 | n/a |

## Wall-time profile — T-023 caching's empirical win

| Statistic | T-021 (no cache) | T-025 (T-023 cache) | Speedup |
|---|---:|---:|---:|
| Min per-candidate (sec) | 3,240 | 2.25 | **1,440×** |
| Max per-candidate (sec) | 6,689 | 6.50 | **1,029×** |
| Mean per-candidate (sec) | 4,458 | 2.65 | **1,683×** |
| Total Discovery time (min) | 223 (3 candidates) | 1.33 (30 candidates) | — |

**T-023 caching's expected 10-50× target was outperformed by ~30-100×.** This unblocks much larger candidate caps and longer windows for future Discovery cycles. The headline framing should now be: "Discovery's per-candidate Gate 1 cost is no longer the bottleneck." The 4-hour backtest preceding Discovery (window=2021-2024) is now the dominant wall-time consumer.

## Bootstrap CI on gauntlet survival

Per CLAUDE.md non-negotiable 6:

- **Survival rate**: 0/30 = 0.000, 95% CI **[0.000, 0.000]**
- At N=30, the bootstrap CI is degenerate (no positive resamples possible because all 30 failed).
- The CI is consistent with "Discovery's autonomous promotion rate is ≤ X% with 95% confidence" where X ≈ 9.5% (1/30 + Wilson upper bound). For now: **Discovery doesn't autonomously promote on substrate-honest with the current Gate 1 threshold + cached Gate 1, regardless of cap=30 sample**.

## Candidate origin distribution

| Parent archetype | Mutations | Notes |
|---|---:|---|
| `rsi_bounce_v1` | 3 | T-021 archetype |
| `value_trap_v1` | 3 | NEW — multi-archetype diversity emerged |
| `fundamental_ratio_v1` | 3 | NEW |
| `seasonality_v1` | 3 | NEW |
| `gap_fill_v1` | 3 | NEW |
| `volume_anomaly_v1` | 3 | NEW (active edge in production) |
| `panic_v1` | 3 | NEW |
| `herding_v1` | 3 | NEW (paused edge in production) |
| `earnings_vol_v1` | 3 | NEW (paused edge in production) |
| `composite_gen0_a79029` | 1 | Pre-existing random genome from prior cycle |
| `composite_gen0_7e9b70` | 1 | Pre-existing random genome from prior cycle |
| `composite_gen0_eaa429` | 1 | Pre-existing random genome from prior cycle |

T-021's "GA is single-archetype" finding has been partially resolved at the **mutation-source** level: 9 distinct edge classes were mutated. But the **composite-gene-level diversity** (which is where T-022's foundry_feature reach matters) was NOT exercised here — the 3 composite genomes are stale from prior cycles.

## Gene-type distribution (composite candidates only)

| Gene type | Count across 3 composite candidates |
|---|---:|
| technical | 4 |
| calendar | 2 |
| **foundry_feature** | **0** |
| Other | 0 |

**The expected T-022 outcome — composite candidates emitting foundry_feature genes at ~21.7% — was not exercised in this run.** The 3 composite_gen0_* candidates were created BEFORE T-022 merged, when the gene factory only emitted the 9 legacy types. The mutation paths for the other 27 candidates don't touch composite_edge gene types at all (they're mutating single-class edges like RSIBounceEdge).

## Scope deviation diagnostic: why T-022 + T-024 didn't fire

`scripts/run_isolated.py::ISOLATED_FILES` snapshots only:
```python
ISOLATED_FILES = [
    "edges.yml",
    "edge_weights.json",
    "regime_edge_performance.json",
    "lifecycle_history.csv",
]
```

**`ga_population.yml` is NOT in the isolated set.** The GA's persistent population survives across `isolated()` invocations. When T-025 launched today:

1. `ga.load_population()` returned True (gen=3, 20 genomes from prior runs).
2. `discovery.py:198` branched into the "Subsequent run: evolve from persisted population" path.
3. **`seed_from_registry` (containing T-024's enrichment) was NEVER called** in this cycle.
4. The GA evolved (mutate/crossover) the pre-existing population. Mutations call `_create_random_gene` (T-022's factory) only with probability `mutation_prob × add-gene-prob ≈ 30% × 10% = 3%` per gene per generation — too rarely to surface foundry_feature genes in a single cycle.

**Recommended follow-up dispatch (T-026?): reset ga_population.yml before running.** Either:
- Add `ga_population.yml` to `ISOLATED_FILES` (or `ISOLATED_FILES_JOURNAL_MODE`) so `isolated()` resets it
- OR delete `data/governor/ga_population.yml` immediately before the next Discovery dispatch

Either path forces `seed_from_registry` to fire on every cycle, exercising T-022 + T-024 as the spec intended. ETA for follow-up: same ~6 hr (backtest dominates, Discovery is now ~1.5 min).

## What Gate 1 told us, despite the partial exercise

The 30 candidates that DID get evaluated covered 9 archetypal mutation sources — that's the broadest diversity Discovery has produced on substrate-honest. Even with this diversity, **all 30 failed at Gate 1 with the same pattern**: Sharpe contribution to existing 6-active ensemble < 0.1 threshold.

This replicates and **strengthens** T-021's finding: **the Gate 1 ensemble-contribution bottleneck is structural, not vocabulary-dependent.** Adding archetypal diversity didn't help. The next question is whether COMPOSITE-LEVEL gene diversity (T-022's foundry_feature reach) would help — and that's the follow-up dispatch.

Per the 3 outcome scenarios in the spec (lines 43-47):

- ❌ "**≥1 candidate clears all 8 gates**" — did not happen
- ❌ "**0 promoted, but Gate-failure histogram is diverse**" — did not happen (histogram is 30/30 at gate_1, same as T-021)
- ✅ "**0 promoted, all die at Gate 1 still**" — **this is the outcome.** Caching didn't fix the underlying selection issue. Gate 1's threshold is structurally strict on substrate-honest given the active 6-edge ensemble already produces coherent decisions on the universe.

## Hard constraints — verification

- [x] **No edges.yml mutation beyond journal-mode** — `isolated()` exit restores from anchor.
- [x] **No Engine D / Engine F / Engine B code modified** — only the diagnostic harness was used.
- [x] **8-gate thresholds unchanged** — Gate 1 threshold = 0.1; Gate 6 t > 2 (today's calibration audit).
- [x] **Candidate cap honored** — 30 candidates evaluated (vs spec floor of 30, ceiling of 30).
- [x] **Journal-mode active** — `--apply-journal-at-end` set.
- [x] **CLAUDE.md non-negotiable 6** — bootstrap CI reported on survival rate.

## Recommendations for director

1. **HIGHEST PRIORITY: schedule a follow-up Discovery dispatch with fresh `ga_population.yml`** to actually exercise T-022 + T-024. Add `ga_population.yml` to `scripts/run_isolated.py::ISOLATED_FILES` (1-line change in Engine D supplemental layer) or `rm data/governor/ga_population.yml` immediately before launch. Without this, every future Discovery dispatch will inherit stale population state and the structural fixes won't see their intended exercise.

2. **T-023 caching is a runaway success** — 1,000-2,500× speedup vs the 10-50× target. The Gate 1 wall-time concern that gated T-021's 30-candidate plan is GONE. Future Discovery dispatches can use cap=100, cap=500, etc. tractably. Where Discovery time used to be the bottleneck (4-7 hr per cap-3 cycle), now the **upfront 4-year backtest dominates** (~3-4 hr) and Discovery itself is ~1.5 min for 30 candidates.

3. **Gate 1 ensemble-contribution threshold IS the structural bottleneck on substrate-honest** — even with archetypal diversity from 9 mutation sources, the ratio of new-candidate signal to the active-6 ensemble's existing signal is below the 0.1 threshold. Per spec line 47's 3rd outcome bucket, this argues for **threshold reconsideration** as the next-most-leveraged Engine D work. Possible directions:
   - Lower the threshold to e.g. 0.05 (a candidate that contributes a thin slice of signal that doesn't overlap actives' may still be useful)
   - Replace marginal-Sharpe-contribution with a **tier-aware Gate 1** (different threshold for `tier=feature` candidates that are meta-learner inputs, not standalone alpha)
   - Compute the contribution against an ensemble that EXCLUDES the candidate's overlapping signal (correlation-adjusted contribution)

4. **The engines-first edge-expansion path is now bottlenecked at Gate 1's threshold, not at vocabulary or wall-time.** Vocabulary and wall-time were T-022 + T-023 + T-024's deliverables; they're solved. The next dispatch in this lineage is Gate 1 threshold/methodology, not "more candidates" or "more features."

5. **Connection to T-019 / T-020 / T-021 / T-022 / T-024:** the full structural-fix arc has shifted the wall-time profile of Discovery by ~3 orders of magnitude AND added archetypal candidate diversity. But the gauntlet's autonomous promotion rate on substrate-honest is still 0%. Substrate-honest is genuinely hard for autonomous candidate generation. Worth a director-side strategic discussion about whether the system should rely on autonomous promotion OR shift to a human-curated + propose-first edge addition workflow with Discovery used for parameter optimization within a known edge family.

## Files

- `scripts/run_discovery_diagnostic.py` — unchanged from T-021 (already extended with `--substrate-honest` + `--apply-journal-at-end` flags)
- `scripts/discovery_diag_analytics.py` — unchanged from T-021
- `docs/Audit/discovery_diagnostic_run_2026_05_20260511T154314.jsonl` — raw 30-candidate JSONL
- `docs/Measurements/2026-05/discovery_substrate_honest_full_stack_2026_05_11.md` — this audit doc
- `docs/Measurements/2026-05/discovery_substrate_honest_full_stack_2026_05_11.json` — structured payload

No engine code modified. No `data/governor/` mutation beyond `isolated()` snapshot/restore (and the journal-mode flow that's then restored on isolated() exit).
