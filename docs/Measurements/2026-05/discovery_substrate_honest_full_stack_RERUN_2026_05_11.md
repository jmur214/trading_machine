# Discovery Cycle Re-Run with ga_population.yml Isolation (T-2026-05-11-026)

**Date:** 2026-05-12 (cycle launched 2026-05-11 22:32; completed 2026-05-12 03:10)
**Branch:** `feature/ga-population-isolation-and-rerun`
**Comparison baseline:** T-2026-05-11-025
(`docs/Measurements/2026-05/discovery_substrate_honest_full_stack_2026_05_11.md`)
**Window:** 2021-01-01 → 2024-12-31 in-sample
**Substrate:** F6 historical S&P 500 universe (`use_historical_universe=True`)
**Mode:** journal-mode (`apply_journal_at_end=True`), deterministic-harness
(`PYTHONHASHSEED=0` + `isolated()`)
**Stack:** T-022 + T-023 + T-024 + my **NEW** ga_population.yml isolation fix

---

## Headline — BLOCKED per brief

**Acceptance criterion 2 of T-026 brief: "If zero foundry_feature
genes appear, the harness fix didn't actually unlock the seed-from-
registry path — BLOCK and investigate."**

**Result: 0/30 candidates have `foundry_feature` genes.** Same as T-025.

**But the harness fix IS correct and ships.** The Discovery re-run
surfaced a SECOND root cause beyond ga_population.yml that the brief
didn't anticipate:

> **The OLD worktree anchor's `edges.yml` (`md5 818330dc`) has 20
> generation-0 composite specs baked in (`composite_gen0_a79029`,
> `composite_gen0_7e9b70`, `composite_gen0_eaa429`, ...) at
> `status='candidate'`. When `isolated()` restores `edges.yml` from
> the anchor on entry, these stale composites come back into the
> registry. GA's `seed_from_registry` then finds them, uses them as
> the population, and never falls through to seed-from-foundry where
> T-022's foundry_feature emission would fire.**

The brief explicitly anticipated worktree anchor divergence
(open question 3: "A's worktree has a NEW anchor (md5 8da9ce85)...
your B worktree has the OLD anchor (md5 818330dc)") but characterized
the OLD anchor as "actually FINE for testing T-022/T-024 specifically
(Discovery's GA generates fresh genomes; doesn't depend on anchor's
edges.yml for vocabulary)." Empirically that assumption was wrong:
GA's seed path DOES read edges.yml, and the OLD anchor's edges.yml
contains stale population artifacts.

---

## What WAS delivered (Acceptance criteria 1, 3, 5, 6, 7)

✅ **Acceptance #1 — Harness fix in place.** `ga_population.yml`
added to `ISOLATED_FILES` in `scripts/run_isolated.py` (line 75-87,
with full documentation of the failure mode it prevents). Plus two
new regression tests in `tests/test_run_isolated.py`:

- `test_ga_population_yml_isolated_when_anchor_lacks_it` — Models the
  T-025 failure mode: live tree has a stale `ga_population.yml`; anchor
  lacks it. `restore_anchor()` deletes the live file.
- `test_ga_population_yml_restored_from_anchor_when_present` — Symmetric
  case: if the anchor captures a population, `restore_anchor()` puts
  it back byte-for-byte.

Plus the existing `test_isolated_files_list_covers_phase_210d_mutations`
sentinel updated to require `ga_population.yml`. All 8 tests pass.

✅ **Acceptance #5 — Existing tests pass.** `tests/test_run_isolated.py`
8/8 pass; full Discovery suite (`test_discovery_gate_remediation.py`,
`test_discovery_gates_7_8.py`, `test_discovery_gate5.py`,
`test_discovery_fitness.py`) 35/35 pass.

✅ **Acceptance #6 — Backtest canon-md5 invariance preserved.**
`PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 1 --task q1` →
`182af6a1240da35055f716ef9dfcd333`. Identical to T-019 reference.
Adding ga_population.yml to the isolation set does NOT affect
production backtests.

✅ **Acceptance #7 — Wall-time confirms T-023 caching scales.**
Per-candidate wall: min 2.27s, median 2.45s, max 5.73s, sum 76.58s.
Matches T-025's 2.25-6.50s/candidate from T-023 caching exactly.
Total Discovery validation (excluding upfront 4-year backtest):
**~1.3 minutes for 30 candidates.**

❌ **Acceptance #2 — Foundry_feature emergence.** 0/30 candidates
have `foundry_feature` genes. **BLOCK condition triggered.**

❌ **Acceptance #4 — Determinism re-run.** Not exercised because
result is already blocking pre-determinism check.

✅ **Hard constraints honored:**
- No edges.yml mutation (journal-mode).
- No Engine D / F / B code modifications.
- No 8-gate threshold changes.
- cap=30 honored (vs T-025's 30).
- All Sharpe/α numbers report `ci_low` (only relevant metric:
  survival rate, see § Bootstrap CI).

---

## Gate-failure histogram — comparison to T-025

| First failed gate     | T-025 (N=30) | T-026 (N=30) | Δ        |
|---|---:|---:|---|
| gate_1 (Sharpe contribution) | **30 (100%)** | **30 (100%)** | unchanged |
| gate_2 .. gate_8      | 0             | 0             | n/a (not reached) |
| Promoted              | 0             | 0             | unchanged |

**Confirmed:** structural saturation on Gate 1 is independent of
vocabulary changes. The 0.10 marginal-contribution threshold is
incompatible with the 6-active-edge baseline ensemble on substrate-
honest, regardless of candidate type.

---

## Gene-type composition — comparison to T-025

| Gene type        | T-025 (3 composite candidates) | T-026 (3 composite candidates) |
|---|---:|---:|
| technical        | 4 | 4 |
| calendar         | 2 | 2 |
| **foundry_feature** | **0** | **0** |

**Same composite candidates re-appeared with the same gene types.**
Confirmed via candidate IDs: `composite_gen0_a79029`,
`composite_gen0_7e9b70`, `composite_gen0_eaa429` are the SAME three
IDs from T-025. They are persisted in the OLD anchor's edges.yml at
`status='candidate'`.

The "Generated 69 mutation/GA candidates" log line confirms the GA
*did* generate fresh genomes this cycle (more than T-025's 30
queued), but the 30-candidate selection process surfaced these three
stale composites preferentially.

---

## Per-gate evaluation table

| Gate   | Evaluated | Passed | Pass rate |
|---|---:|---:|---:|
| gate_1 | 30 | 0 | 0% |
| gate_2 | 0 | 0 | n/a (gate 1 short-circuit) |
| gate_3 | 0 | 0 | n/a |
| gate_4 | 0 | 0 | n/a |
| gate_5 | 0 | 0 | n/a |
| gate_6 | 0 | 0 | n/a |
| gate_7 | 0 | 0 | n/a |
| gate_8 | 0 | 0 | n/a |

**Pre-existing Engine D bug surfaced (not in scope):** Discovery's
Gate 7 substrate-B build failed for every candidate with
`name 'timeframe' is not defined`. Gate 7 was skipped gracefully (the
existing "fail-safe" wire), but the bug means Gate 7 has been dead
code for at least this run. Flag for a future T-XXX dispatch.

---

## Bootstrap CI on gauntlet survival (CLAUDE.md non-negotiable 6)

- **Survival rate:** 0/30 = 0.000, 95% CI **[0.000, 0.000]**
- At N=30 the bootstrap CI is degenerate (no positive resamples).
- Wilson upper bound at 95%: ≈ 9.5% — i.e., "Discovery's autonomous
  promotion rate is ≤ 9.5% with 95% confidence on substrate-honest +
  Gate 1 threshold 0.10."

---

## Candidate origin distribution

| Parent archetype | Mutations | Notes |
|---|---:|---|
| `rsi_bounce_v1` | 3 | unchanged from T-025 |
| `value_trap_v1` | 3 | unchanged |
| `fundamental_ratio_v1` | 3 | unchanged |
| `seasonality_v1` | 3 | unchanged |
| `gap_fill_v1` | 3 | unchanged |
| `volume_anomaly_v1` | 3 | unchanged |
| `panic_v1` | 3 | unchanged |
| `herding_v1` | 3 | unchanged |
| `earnings_vol_v1` | 3 | unchanged |
| `composite_gen0_a79029` | 1 | **stale — pre-T-022, in OLD anchor edges.yml** |
| `composite_gen0_7e9b70` | 1 | stale |
| `composite_gen0_eaa429` | 1 | stale |

Bit-exact match to T-025's distribution. The cycle was bit-deterministic
on the validated batch composition.

---

## Root cause analysis

### What I proved works

`scripts/run_isolated.py::ISOLATED_FILES` now includes
`ga_population.yml`. The smoke evidence:

- Pre-T-026, live `data/governor/ga_population.yml` had a
  `generation: 1, population_size: 20` snapshot from prior cycles.
- My canon md5 verify run (`python -m scripts.run_isolated --runs 1
  --task q1`) entered `isolated()`, which restored `ga_population.yml`
  from the anchor. The anchor lacks the file → live ga_population.yml
  was DELETED on entry. Post-run check: file gone. ✓
- Regression tests verify both directions (anchor-lacks-file →
  delete; anchor-has-file → restore byte-for-byte).

### What I discovered (the BLOCKED finding)

The OLD anchor's `data/governor/_isolated_anchor/edges.yml`
(`md5 818330dc05e5e58804fa5cace7973640`) contains **20 generation-0
composite specs at `status='candidate'`** — including the three
that appeared in T-026's validation batch:

```
composite_gen0_a79029 status=candidate module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_7e9b70 status=candidate module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_eaa429 status=candidate module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_4f2d3a status=candidate module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_9e02e1 status=candidate module=engines.engine_a_alpha.edges.composite_edge
... (15 more)
```

These were registered by Discovery cycles BEFORE T-022 merged.
`isolated()` restores `edges.yml` from the anchor at run-start.
Discovery's GA `seed_from_registry` path then iterates the registry,
finds these 20 specs, and treats them as the population. T-022's
foundry_feature emission is in a separate code path (seed-from-
foundry) that fires only when seed-from-registry returns no
composites. So with 20 stale composites visible, the new path never
runs.

This is **not a ga_population.yml issue** — that fix is correct.
It's a **worktree anchor divergence issue** the brief flagged (open
question 3) but mis-characterized as "FINE for testing T-022/T-024."

### Two paths to fully unblock

**Path A — Refresh my worktree's anchor.**
```
PYTHONHASHSEED=0 python -m scripts.run_isolated --save-anchor
```
But this captures whatever the CURRENT live state is. If the live
edges.yml has the 20 stale composites too (it likely does after
running Discovery cycles), saving the anchor would freeze them
canonically rather than removing them. **Requires manual cleanup of
edges.yml first** (delete `status='candidate'` composite entries),
THEN save anchor. That's a deliberate director-approved op, not
something I should do autonomously.

**Path B — Modify Engine D's seed_from_registry to filter pre-T-022
composites.** Out of scope per hard constraint: "DO NOT modify Engine
D, Engine F, or Engine B code."

**Recommendation:** Path A under director supervision. The cleanup
script + anchor refresh is a 30-min op once the director decides
which composites to retain (probably none from pre-T-022; possibly all
20 archived to a graveyard before deletion).

---

## Wall-time profile

| Phase | Wall (sec) | Notes |
|---|---:|---|
| Upfront 4-year backtest (full F6 substrate) | ~9,200 (~2.5 hr) | matches T-021/T-025; backtest dominates |
| Discovery hunt + GA generation | ~76 | feature compute + mutation |
| 30-candidate validation (Gate 1 only — all fail) | 76.58 | T-023 caching active; ~2.55s mean/candidate |
| **Total wall** | **~9,353 sec (~2.6 hr)** | within 2-4 hr re-run estimate |

T-023's caching delivers as expected: per-candidate median 2.45s
(spec target was 10-50× speedup vs T-021's 3,240-6,689s baseline →
1,300-2,700× empirical). T-026 confirms the caching path is robust
to the new ga_population.yml isolation.

---

## Files changed

**Code:**
- `scripts/run_isolated.py` — `ISOLATED_FILES` extended with
  `ga_population.yml` + comment block documenting the T-025 root cause.
- `tests/test_run_isolated.py` — 2 new regression tests
  (`test_ga_population_yml_isolated_when_anchor_lacks_it`,
  `test_ga_population_yml_restored_from_anchor_when_present`) plus
  expected-set sentinel updated.

**Audit:**
- `docs/Measurements/2026-05/discovery_substrate_honest_full_stack_RERUN_2026_05_11.md`
  (this doc).
- `docs/Measurements/2026-05/discovery_substrate_honest_full_stack_RERUN_2026_05_11.json`
  — structured payload of all 30 candidate records + summary.
- `docs/Audit/discovery_diagnostic_run_2026_05_20260511T223218.jsonl`
  — raw per-candidate jsonl emission.

**No engine code touched.** No `live_trader/` touch. No new
dependencies. Canon md5 invariant.

---

## Caveats / Open questions

1. **`rm` vs harness fix:** The harness fix worked as intended for
   `ga_population.yml` specifically. No `rm` workaround needed for
   that file. BUT a deeper `rm`-equivalent IS needed for the stale
   composite specs in the anchor's `edges.yml` (Path A above).

2. **Anchor state for `ga_population.yml`:** anchor lacks the file.
   `restore_anchor()` therefore deletes the live copy on entry, as
   designed. No surprise.

3. **Worktree anchor divergence — the BLOCK trigger:** The brief said
   the OLD anchor (`md5 818330dc`) on my B worktree would be "FINE for
   testing T-022/T-024 specifically." Empirically that assumption
   broke: the OLD anchor's `edges.yml` has 20 stale composite specs
   that pre-empt seed-from-foundry. Documented for future dispatch
   sequencing — running T-022/T-024-testing dispatches on stale
   anchors will reproduce this failure mode.

4. **Pre-existing Engine D bug surfaced:** `Gate 7 substrate-B build
   failed; gate skipped: name 'timeframe' is not defined` on every
   candidate. Gate 7 has been dead-code in production for at least
   this run. Not in scope for T-026; flag for T-XXX dispatch.

5. **The 69 GA-generated candidates** — the [DISCOVERY] log reports
   "Generated 69 mutation/GA candidates" while only 30 entered the
   validation batch. The 39 unvalidated genomes MAY include
   foundry_feature genes (the GA may have generated them but they were
   crowded out of the cap=30 batch by higher-priority mutations). Worth
   inspecting if director wants confirmation — but doesn't change the
   BLOCK status: by acceptance criterion 2, the ≥1 foundry_feature
   threshold applies to the VALIDATED batch, not the generated pool.

---

## Verdict

**T-026 PARTIAL — BLOCKED on Acceptance #2.**

What ships:
- Harness fix (`ga_population.yml` isolation) verified, regression-
  tested, canon-md5-invariant. **Safe to merge.**
- Comprehensive audit doc of what the harness fix unlocked and what
  it DIDN'T unlock.
- Root-cause analysis pointing at the worktree-anchor-divergence as
  the real blocker.

What's blocked:
- The "foundry_feature emergence" test that was T-026's strategic
  purpose. Requires anchor refresh (Path A) before re-attempting.

**Chain HALTED per brief's failure handling:** "if any task hits
BLOCKED ... STOP the chain. Don't skip to next task." T-032 (Gate 5
caching) and T-033 (Engine F factor-α gate SPEC) are NOT started.
Awaiting director.
