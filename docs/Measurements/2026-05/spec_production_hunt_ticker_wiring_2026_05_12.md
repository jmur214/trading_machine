# Spec — T-2026-05-12-054: Wire `ticker=` through production `hunt()` to `compute_all_features`

**Date drafted:** 2026-05-12 LATE (director-side, post-T-038-CONT investigation)
**Status:** SPEC for dispatch. Engine D only. **HIGHEST-LEVERAGE single dispatch in the project's current state.**
**Will be executed by:** Agent A or B (~2-4 hr).
**Sequencing:** can run any time; unblocks T-022/T-023/T-024/T-038-CONT/T-052 cumulatively.
**Output:** wired hunt() path + smoke test confirming foundry_feature genes are no longer dead-letter + audit doc.

---

## Why this is the highest-leverage dispatch right now

Agent B's T-038-CONT investigation surfaced that **production `hunt()` does NOT pass `ticker=` to `compute_all_features`**. As a result:

- All foundry_feature genes (20% of GA emissions per T-022) reference feature_ids whose columns never get computed in production
- They reliably fail Gate 1 (no data → no signal → no contribution)
- The T-021/T-025/T-026 "single archetype" findings were not signal weakness — they were structural plumbing failure
- T-022 (gene encoding extension), T-023 (Gate 1 caching), T-024 (seed enrichment), T-038-CONT (vectorization), T-052 (4 new regime features) all share the same dead-letter destiny until this single fix lands

**This is a one-line-class fix that unblocks ~30+ hours of prior agent work.**

---

## What

### Part A: Profile to confirm the dead-path

Reproduce B's empirical finding:

1. Run production `hunt()` with `ticker=` instrumentation: log every call to `compute_all_features` with the ticker argument.
2. Confirm: are any foundry_feature columns populated in production runs? Expected: NO (per B's investigation).
3. Document the exact call-site where `ticker=` is omitted.

### Part B: Wire the call-site

Single fix per B's finding. Likely just adding `ticker=ticker` to the `compute_all_features(...)` call in `engines/engine_d_discovery/discovery.py` (or wherever the production hunt() invokes Foundry).

Take care:
- The fix must not change the SIGNATURE of `compute_all_features` (other callers may rely on the ticker-optional behavior).
- The fix should be IDENTICAL to how T-038-CONT's optimized code already calls `compute_all_features` (B explicitly noted the optimized path passes ticker= correctly).
- Determinism guard: existing trade-log canon md5 should be PRESERVED for runs that DON'T use foundry_feature candidates. Only runs that include foundry_feature genes should produce different (and now meaningful) candidate outcomes.

### Part C: Smoke validation

After wiring, run a CAP=3 Discovery cycle on a small substrate (~50 tickers × 1yr). Expected outcomes:

1. Foundry_feature columns ARE populated in the production hunt() trace
2. At least 1 of the 3 candidates references a foundry_feature gene (was 0 pre-fix)
3. Wall-time of the cycle is bounded (T-038-CONT's vectorization activates; cap=3 in <30 min)
4. Gate 1 contribution scores for foundry_feature candidates are no longer trivially zero

NOTE: This smoke is a vocabulary-extension verification, NOT a measurement. Per CLAUDE.md, no Sharpe headlines from this run.

### Part D: Re-run T-052's smoke

T-052's audit explicitly deferred its smoke pending this fix. After Part C confirms wiring, re-run T-052's smoke to verify the 4 regime features (VIX/VIX3M, HY OAS Δ20d, ANFCI z60d, Faber multi-asset trend) are populated and reachable by GA candidates.

---

## Acceptance

1. **Pre-fix diagnostic** at `docs/Audit/production_hunt_ticker_wiring_prefix_2026_05_12.json` confirms the wiring gap empirically.
2. **Wiring fix** applied to `engines/engine_d_discovery/discovery.py` (or wherever B identified the call-site). Minimal-diff change — ideally 1-3 lines.
3. **Smoke Discovery cycle** post-fix:
   - At least 1/3 candidates references a foundry_feature gene
   - Wall-time ≤ 30 min (cap=3, 1yr, 50 tickers)
   - Foundry_feature columns are populated in the per-bar feature panel (verified via debug log)
4. **T-052 smoke re-run** confirms 4 regime features reachable.
5. **Determinism**: existing trade-log canon md5 invariant for runs that don't use foundry_feature candidates. Document the canon stability check.
6. **Tests** in `tests/test_production_hunt_ticker_wiring.py`:
   - `test_production_hunt_passes_ticker_to_compute_all_features` — mock + spy on compute_all_features, assert ticker passed
   - `test_foundry_feature_columns_populated_post_fix` — synthetic substrate, run hunt(), assert at least one foundry_feature column has non-null values
   - `test_pre_fix_repro_documented` — golden-file test capturing the empty-column behavior the fix corrects
7. **Audit doc** at `docs/Audit/production_hunt_ticker_wiring_2026_05_12.md`:
   - The diagnosis (with code line references)
   - The fix (with before/after)
   - Smoke cycle output: candidate-level diagnostics
   - Cascade impact: which prior T-XXX dispatches (T-022, T-023, T-024, T-038-CONT, T-052) are now live
8. **Branch:** `feature/production-hunt-ticker-wiring-fix`. Push only; director merges + pushes after review.

---

## Hard constraints

- DO NOT modify the signature of `compute_all_features`. Only add the missing argument at the call-site.
- DO NOT modify any feature implementations in `core/feature_foundry/features/`. The wiring is the bug, not the features.
- DO NOT run a cap=30 Discovery cycle. Smoke (cap=3) only.
- DO NOT modify Engine A, B, C, E, F. Engine D only.
- Per CLAUDE.md 6th non-negotiable: any Sharpe touched by smoke reporting carries bootstrap CI.

---

## Time budget

- Part A (profile + diagnostic): ~30 min
- Part B (wiring fix): ~15-30 min — single-line-class fix
- Part C (smoke + determinism check): ~30 min
- Part D (T-052 smoke re-run): ~15 min
- Tests + audit doc: ~1-1.5 hr
- **Total: 2.5-4 hr**

---

## Open questions for implementing agent

1. **If the wiring fix changes determinism canon md5 on runs that PREVIOUSLY produced no foundry_feature candidates?** That would be unexpected — investigate before declaring success. The fix should be additive (now-meaningful behavior), not mutational.

2. **If `compute_all_features` has multiple call-sites in production hunt()?** Apply consistently to all. Document each.

3. **If the smoke cycle produces foundry_feature candidates that fail Gate 1 even with populated columns?** That's the LEGITIMATE Gate 1 outcome — separate from the wiring bug. Document the post-fix Gate 1 pass rate for foundry_feature candidates as a baseline for future T-038/T-026 dispatches.

---

## Director note + cascade

After T-054 lands, the queued Discovery work has a real chance for the first time:

1. **T-038-CONT vectorization becomes live** — actual production speedup
2. **T-052's 4 regime features become reachable** by GA candidates
3. **T-022/T-023/T-024's plumbing produces meaningful candidates** instead of trivial Gate-1 kills
4. **A genuine cap=30 Discovery cycle becomes a meaningful experiment** instead of a structurally-doomed exercise

The director will THEN gate a fresh Discovery dispatch (post-T-054) based on the Phase 0 pairwise correlation outcome. Per the research convergence: even with the wiring fixed, signal-diversity remains a constraint. Discovery may produce candidates that still cluster ρ > 0.5 with active edges and fail Gate 6. **The wiring fix is necessary but not sufficient.** It removes the "structural plumbing failure" explanation for past Discovery null results; what remains is the signal-diversity + substrate-efficiency constraints that other research dives flag.

But all of that downstream work is conditional on the wiring fix first.
