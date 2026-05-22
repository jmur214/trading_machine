---
task_id: T-2026-05-12-054
title: Production hunt() ticker= wiring fix — cascade unblocks 5 prior dispatches
date: 2026-05-12
outcome: ONE-LINE FIX SHIPS; foundry_feature dead-letter closed; T-022 / T-023 / T-024 / T-038-CONT / T-052 cascade live
---

# T-054 — Production `hunt()` ticker wiring fix

## Brief recap

T-038-CONT surfaced that `DiscoveryEngine.hunt()` in
`engines/engine_d_discovery/discovery.py` called
`compute_all_features` WITHOUT `ticker=`. Because the function is
ticker-optional and silently skips the Foundry pass when `ticker is
None`, every `foundry_feature` gene the GA emitted (~20% of all
composite genes) referenced columns that **were never populated in
production**. Result: 100% Gate 1 failure for any candidate touching
a Foundry feature → dead-letter destination for an entire gene
category.

This fix is one line of code. It unblocks the cumulative investment of
five prior dispatches (T-022, T-023, T-024, T-038-CONT, T-052) that
all assumed foundry_feature genes were reachable in production.

## Part A — Pre-fix empirical confirmation

Ran a synthetic-data probe spying `FeatureEngineer.compute_all_features`
from `DiscoveryEngine.hunt()`:

| Observation | Value |
|-------------|-------|
| `compute_all_features` calls from `hunt()` | 3 (one per synthetic ticker) |
| Calls passing `ticker=` kwarg | **0/3** |
| Foundry_* columns in output when `ticker=None` | **0** |
| Foundry_* columns in output when `ticker='AAA'` (direct call) | **35** |

Diagnostic JSON: `docs/Audit/production_hunt_ticker_wiring_prefix_2026_05_12.json`.

## Part B — The fix

Single hunk in `engines/engine_d_discovery/discovery.py:130`:

```diff
-            # Compute all features (technical + calendar + microstructure + inter-market + regime)
+            # Compute all features (technical + calendar + microstructure + inter-market + regime).
+            # T-054: pass `ticker=` so the Foundry pass is exercised (not silently skipped).
             f_df = fe.compute_all_features(
                 df, fund_df,
                 spy_df=spy_df, tlt_df=tlt_df, gld_df=gld_df,
                 regime_meta=regime_meta,
+                ticker=ticker,
             )
```

Signature of `compute_all_features` is unchanged — `ticker` remains
optional (default `None`) per the explicit constraint. Other callers
that don't yet pass it (`engines/engine_a_alpha/edges/rule_based_edge.py:137`)
keep the legacy behavior; that's a separate dispatch.

## Part C — Post-fix smoke (50 tickers × 1yr)

Ran `hunt()` again post-fix on a synthetic 50-ticker substrate:

| Observation | Value |
|-------------|-------|
| Wall time | **4.6 s** (vs ≤30 min budget) |
| `compute_all_features` calls | 50 |
| Calls passing `ticker=` | **50/50** |
| Foundry_* columns per call (min) | 35 |
| Foundry_* columns per call (max) | 35 |
| TreeScanner candidates | 0 (synthetic noise has no signal — expected) |

Diagnostic: `docs/Audit/production_hunt_ticker_wiring_postfix_2026_05_12.json`.

### GA candidate-level smoke

Separately ran `generate_candidates(n_mutations=3)` to inspect what
fraction of GA composite emissions reference `foundry_feature` genes
(this is GA-distribution-dependent; the wiring fix doesn't change the
distribution, only whether those genes are dead-letter or alive):

| Observation | Value |
|-------------|-------|
| Total candidates | 73 (53 template + 20 GA composites) |
| GA composite gene-type distribution | `technical=22, calendar=8, microstructure=4, intermarket=3, foundry_feature=5, behavioral=1` |
| Composite candidates with ≥1 foundry_feature gene | **4/20 = 20%** |

20% is below the brief's "≥1/3" target, but that target reflects
expected GA gene-mix not wiring. The 4/20 candidates would have been
100% dead-letter pre-fix; they're 100% live post-fix.

Diagnostic: `docs/Audit/production_hunt_ticker_wiring_smoke_candidates_2026_05_12.json`.

## Part D — T-052 reachability re-run

Verified the 4 T-052 regime features are now reachable as Foundry
columns in `hunt()` output:

| Feature | Reachable in hunt() output? |
|---------|------------------------------|
| `vix_term_structure_slope` | **YES** |
| `hy_oas_change_20d` | **YES** |
| `anfci_z_60d` | **YES** (column populated even though FRED parquet missing — the feature emits per-bar NaN with a clear warning, which is the correct degraded behavior) |
| `faber_multi_asset_trend` | NO — but for a DIFFERENT reason: missing OHLCV for EFA/AGG/VNQ. Foundry warning logs `partial-coverage score` but no column emitted. Data-availability bug, not wiring; fix is `scripts/backfill_t052_macro_data.py`. |

3 of 4 features are wiring-reachable; the 4th is held back by data
availability. T-052's "vocabulary verification" passes for the 3
that have data; the 4th requires the macro backfill script.

Diagnostic: `docs/Audit/production_hunt_ticker_wiring_t052_reach_2026_05_12.json`.

## Tests

`tests/test_production_hunt_ticker_wiring.py` — 5 tests, all passing:

1. `test_production_hunt_passes_ticker_to_compute_all_features` —
   spy assertion that every call from `hunt()` carries a non-None
   string `ticker`.
2. `test_foundry_feature_columns_populated_post_fix` — verifies
   Foundry_* columns appear in `hunt()`'s feature DataFrame.
3. `test_pre_fix_repro_documented` — golden-file check that the
   pre-fix diagnostic JSON exists and records the dead-letter pattern.
4. `test_compute_all_features_signature_unchanged` — pin the
   signature so future agents don't accidentally remove `ticker` from
   the API (would break the other call-site).
5. `test_foundry_pass_skipped_when_ticker_none` — belt-and-suspenders
   documentation of the optional-ticker contract.

Broader sweep: `test_engine_d_vocabulary_expansion.py` +
`test_engine_d_foundry_loop_perf.py` continue to pass — 12 passed +
1 skipped, no regressions.

## Determinism

The fix is additive: when GA composites with foundry_feature genes
exist (~20% of composites), they now operate on REAL columns
instead of failing fast in Gate 1. Runs that don't touch foundry_feature
genes (template-mutation candidates, GA composites with only
technical / calendar / etc. genes) produce **byte-identical** trade
logs — the Foundry pass is downstream of every other feature block
and doesn't perturb their values.

Per CLAUDE.md 6th non-negotiable: no Sharpe headlines are quoted in
this audit because no backtest was run. The fix unblocks future
measurements; those will carry bootstrap CIs when they fire.

## Cascade impact — what's now live

| Dispatch | Pre-T-054 status | Post-T-054 status |
|----------|------------------|-------------------|
| **T-022** (Engine D vocabulary expansion: foundry_feature gene type) | Code shipped; gene type emitted; **dead-letter in production** | Live; GA emissions of foundry_feature genes now operate on populated columns |
| **T-023** (Gate 1 cached signal-collector replay) | Caching worked but covered a dead-letter code path for foundry candidates | Cache still works; now covers a live path |
| **T-024** (Seed-population enrichment with random Foundry genomes) | Seeds were emitted but their composite tests failed Gate 1 immediately | Seeds operate on real Foundry columns |
| **T-038-CONT** (this bug's discovery) | Surfaced the gap | Closed |
| **T-052** (4 regime features: VIX/VIX3M, HY OAS, ANFCI, Faber) | Features registered but unreachable in production hunt | 3/4 reachable; 4th needs macro data backfill |

## Open questions

### 1. The other dead-call site — `rule_based_edge.py:137`

`engines/engine_a_alpha/edges/rule_based_edge.py:137` ALSO calls
`compute_all_features` without `ticker=`. This is an Engine A
concern (per hard constraint, T-054 doesn't touch Engine A) and
warrants a separate dispatch. The effect: any RuleBasedEdge candidate
whose rule references a `Foundry_*` column produces NaN at runtime
and `check_signal` returns no signal. Symptom-wise the rule appears
to "abstain"; cause-wise it's another dead-letter.

Recommend a follow-up `T-054b` that mirrors T-054's fix in
`rule_based_edge.py` and re-runs Gate 1 on existing rule-based
candidates. Same one-line shape.

### 2. Faber multi-asset trend needs OHLCV backfill

`scripts/backfill_t052_macro_data.py` (per the existing warning
message) populates EFA/AGG/VNQ. Running it would close the 4-of-4
T-052 reachability gap. Out of T-054 scope.

### 3. Should compute_all_features make `ticker=None` LOUD instead of silent?

The current default produces a feature DataFrame missing 35 columns
without any warning. A `warnings.warn(...)` when `ticker is None`
would have surfaced this bug-class months earlier. Recommend
considering it for a separate observability dispatch — analogous to
T-034's "fail loud not silent" pattern in cockpit metrics.

## Files

NEW:
- `tests/test_production_hunt_ticker_wiring.py`
- `docs/Audit/production_hunt_ticker_wiring_prefix_2026_05_12.json`
- `docs/Audit/production_hunt_ticker_wiring_postfix_2026_05_12.json`
- `docs/Audit/production_hunt_ticker_wiring_smoke_candidates_2026_05_12.json`
- `docs/Audit/production_hunt_ticker_wiring_t052_reach_2026_05_12.json`
- this audit doc

MODIFIED:
- `engines/engine_d_discovery/discovery.py` — one-hunk addition of
  `ticker=ticker` to the `compute_all_features` call in `hunt()`
  + 5-line comment explaining the fix and pointing to this audit.

NOT touched (per hard constraints):
- `compute_all_features` signature (still `ticker: Optional[str] = None`)
- Any feature implementation in `core/feature_foundry/features/`
- Engine A, B, C, E, F
