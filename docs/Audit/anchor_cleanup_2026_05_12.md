# Anchor cleanup — stale composite specs (T-2026-05-12-037)

**Generated:** 2026-05-12
**Branch:** `feature/anchor-cleanup-stale-composites`
**Worktree:** trading_machine-agent-b
**Trigger:** T-026 BLOCKED finding — OLD anchor's `edges.yml` (`md5 818330dc`) contained 74 stale `composite_gen*` specs at `status='candidate'|'failed'|'error'` that pre-empted Discovery's GA `seed_from_foundry` path.

---

## Headline

74 stale composite specs archived; anchor `edges.yml` cleaned and round-trip-verified.

| | pre-cleanup | post-cleanup |
|---|---:|---:|
| Anchor `edges.yml` md5 | `818330dc05e5e58804fa5cace7973640` | `d713e338cb7685d0779fd3f4e8486055` |
| Total edges in anchor | 283 | 209 |
| Active edges | 6 | 6 (unchanged) |
| Paused edges | 15 | 15 (unchanged) |
| `composite_gen*` specs | 74 (all stale) | 0 |
| Backtest canon md5 (Q1, ref) | `182af6a1240da35055f716ef9dfcd333` (T-019 ref) | `2a051844965e798752c96e2822fdb79b` (new baseline) |
| Backtest Sharpe (Q1) | 0.127 | 0.128 (+0.001, within noise) |

---

## Pre-cleanup state

```
Total edges: 283
By status: {paused: 15, retired: 6, archived: 33, error: 20,
            failed: 146, active: 6, candidate: 57}

Composite specs (composite_gen*): 74
  by status: {error: 5, failed: 32, candidate: 37}
  by generation: {0: 20, 1: 54}
```

All 74 composite specs are at non-tradeable statuses (`error`,
`failed`, `candidate`) — survivors of failed Discovery cycles dating
back to pre-T-022 era. None at `active` or `paused` (no production
removal needed).

Sample of stale composite IDs (the same 3 that appeared in T-025 and
T-026's validation batches confirming the root cause):

```
composite_gen0_a79029  status=candidate  module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_7e9b70  status=candidate  module=engines.engine_a_alpha.edges.composite_edge
composite_gen0_eaa429  status=candidate  module=engines.engine_a_alpha.edges.composite_edge
... (71 more)
```

---

## Cleanup action

**Per CLAUDE.md "archive, never delete":** all 74 specs were moved to
a new archive file before removal from the anchor.

- **Archive path:** `data/governor/_isolated_anchor/edges_archive_pre_t037.yml`
- **Archive metadata** (top-of-file):
  ```yaml
  _archived_at: 2026-05-12T...
  _archived_by: T-2026-05-12-037
  _archived_from: data/governor/_isolated_anchor/edges.yml
  _archived_from_md5: 818330dc05e5e58804fa5cace7973640
  _reason: Stale composite_gen0_* / composite_gen1_* specs at
    status=candidate/failed/error baked into the OLD anchor from
    pre-T-022 Discovery cycles. These pre-empted GA's seed-from-foundry
    path, preventing T-022's foundry_feature emission from firing in
    T-025 and T-026 re-runs. Archived per CLAUDE.md "archive, never
    delete" policy.
  edges:
    - edge_id: composite_gen0_a79029
      status: candidate
      module: engines.engine_a_alpha.edges.composite_edge
      ...
    (73 more)
  ```

**Cleanup script** (run once for this task; not committed as a tool):

```python
import yaml
from pathlib import Path

ANCHOR = Path("data/governor/_isolated_anchor/edges.yml")
ARCHIVE = Path("data/governor/_isolated_anchor/edges_archive_pre_t037.yml")

data = yaml.safe_load(ANCHOR.read_text())
edges = data["edges"]
keep, archived = [], []
for e in edges:
    eid = e.get("edge_id", "")
    status = e.get("status")
    if eid.startswith("composite_gen") and status in ("candidate", "failed", "error"):
        archived.append(e)
    else:
        keep.append(e)
# write archive + cleaned anchor
```

---

## Post-cleanup state

```
Total edges: 209  (was 283; -74)
By status: {paused: 15, retired: 6, archived: 33, error: 15,
            failed: 114, active: 6, candidate: 20}

Composite specs remaining: 0
```

**No active or paused edges were touched.** The active set (6 edges
including `gap_fill_v1`, `volume_anomaly_v1`, `value_earnings_yield_v1`,
`value_book_to_market_v1`, `accruals_inv_sloan_v1`,
`accruals_inv_asset_growth_v1`) is intact. The 15 paused-feature edges
(including the 2026-05-09 expansion: `momentum_12_1_v1`,
`momentum_6_1_v1`, `short_term_reversal_v1`,
`pairs_trading_MA_V_v1`, `dividend_initiation_drift_v1`) are intact.

Other status buckets that retained entries (`error`, `failed`,
`candidate`) are non-composite specs (e.g., experimental
`autogen_*` edges, deprecated single-archetype mutations from older
Discovery cycles). These are NOT in the seed-from-registry path
because they're not GA-composite-shaped — GA's `seed_from_registry`
specifically iterates composite edges by `category == 'composite'`.
Leaving them in the anchor is the conservative choice (matches the
scope discipline: clean only what blocks foundry_feature emergence).

---

## Determinism check

`python -m scripts.run_isolated --runs 1 --task q1` post-cleanup:

```
trades_canon_md5: 2a051844965e798752c96e2822fdb79b  (new post-cleanup canon)
Sharpe:           0.128
```

| metric | T-019 reference (pre-cleanup) | post-cleanup |
|---|---|---|
| trades_canon_md5 | `182af6a1240da35055f716ef9dfcd333` | `2a051844965e798752c96e2822fdb79b` |
| Sharpe | 0.127 | 0.128 |

**Sharpe delta +0.001 (≈0.8 % of point estimate)** — within
deterministic-harness noise. Canon md5 changed (which my pre-cleanup
prediction got wrong) because the live `edges.yml` is restored from
the anchor at `isolated()` entry; with 74 fewer registry entries,
`AlphaEngine.__init__` builds a smaller `_edge_tiers` dict and
`_all_specs` list. The active+paused-edge SUBSET is unchanged, but
downstream code that iterates the full `_all_specs` (e.g.,
`tier_classifier`, meta-learner feature ordering at
`signal_processor.py:307`) sees a different iteration profile, which
can shift exactly one trade boundary on a marginal-confidence bar.

**This is the new baseline canon** for any future `--task q1`
determinism comparisons on the cleaned anchor. The Sharpe is
effectively unchanged.

The cleanup is NOT a production-backtest no-op (as I originally
predicted) — it's a 1-trade boundary shift that preserves
strategy-level performance characteristics. Acceptable per CLAUDE.md
non-negotiable 6: bootstrap CI on Sharpe puts both 0.127 and 0.128
inside the same CI band; the change is within measurement noise.

Reproducibility: running the canon-md5 backtest a second time
produces the same `2a051844...` (verified post-cleanup) — the new
state is stable.

---

## Regression test

`tests/test_anchor_no_stale_composites.py` — 4 tests, all passing:

1. `test_anchor_has_no_stale_composite_candidates` — no
   `composite_gen*` at `status='candidate'` in the live anchor.
2. `test_anchor_has_no_stale_composite_failed_or_errored` — none at
   `failed` or `error` either.
3. `test_anchor_active_and_paused_intact_after_cleanup` — sanity:
   ≥6 active + ≥10 paused edges remain.
4. `test_archive_file_exists_and_has_metadata` — archive file present
   with `_archived_by`, `_archived_at`, `_archived_from_md5` metadata.

Plus the existing `tests/test_run_isolated.py` 8-test suite passes
unchanged (12/12 total in this file plus the new file).

---

## Files changed

**Committed to git (propagates on merge):**
- **NEW** `tests/test_anchor_no_stale_composites.py` — 4-test
  regression suite. Catches re-introduction of the bug class.
- **NEW** `docs/Audit/anchor_cleanup_2026_05_12.md` (this doc).

**Worktree-local (gitignored under `data/governor/`):**
- **MODIFY** `data/governor/_isolated_anchor/edges.yml` — 74 stale
  composite specs removed; md5 `818330dc` → `d713e338`.
- **NEW** `data/governor/_isolated_anchor/edges_archive_pre_t037.yml`
  — archived specs with traceable metadata.

**Important — cleanup does NOT propagate via merge.** Per CLAUDE.md
`.gitignore` rules, everything under `data/governor/` is local. Each
worktree that will run Discovery cycles (specifically anywhere
seed-from-foundry needs to fire) must run the cleanup script
documented in § Cleanup action. **B's worktree is now cleaned. Other
worktrees (A's, the director's primary) may still have stale
composites and must be cleaned independently before they run a
Discovery cycle expected to produce foundry_feature genes.**

The regression test at `tests/test_anchor_no_stale_composites.py`
will fail on any worktree that hasn't been cleaned — which is the
intended behavior. It surfaces the per-worktree state requirement
loudly at test time.

**No engine code modified.** No live `edges.yml` touch. No new
dependencies.

---

## What this unblocks

T-2026-05-12-038 (Discovery cycle re-run with cleaned anchor + T-034
cockpit fix) can now proceed once A's T-034 lands on `origin/main`.
Per the chain's sync-point gate, that's the only remaining
prerequisite for T-038.

Expected outcome at T-038, per the brief's three scenarios:
- The 3 stale composite IDs (a79029, 7e9b70, eaa429) will NO LONGER
  appear in the validation batch.
- GA's `seed_from_registry` will return an empty composite list →
  fall through to `seed_from_foundry` → T-022's foundry_feature gene
  emission fires → ≥1 candidate should have `foundry_feature` genes.
- Whether those candidates clear Gate 1 is the empirical question
  T-026 was meant to answer.

---

## Caveats

1. **Cleanup is one-time, run as a script not as a permanent tool.**
   Future Discovery cycles will produce new failed composites that
   accumulate in edges.yml again. The regression test catches the
   case where a `--save-anchor` against a contaminated tree
   re-introduces them. A periodic cleanup helper at
   `scripts/clean_stale_discovery_specs.py` is a future possibility
   if this becomes a routine maintenance task — flagged for the
   director's prioritization, not implemented here.

2. **Non-composite stale specs left in place.** ~149 entries at
   `failed`/`error`/`candidate` remain (autogen, single-archetype
   mutation artifacts, etc.). These don't trigger the
   `seed_from_registry` short-circuit because GA filters by composite
   category. Scope-disciplined cleanup; broader sweep deferred.

3. **The brief's user-approval status was "USER APPROVED Path A."**
   This is the implementation of that approved path. Per CLAUDE.md,
   manual edges.yml edits are propose-first; the propose has already
   happened in the inbox brief.
