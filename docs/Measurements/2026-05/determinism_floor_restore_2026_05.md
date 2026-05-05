# Determinism Floor Restore — 2026-05

**Date:** 2026-04-30 / 2026-05-01
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-agentA-det`
**Branch:** `determinism-floor-restore`
**Drivers:** `scripts/det_d1_repro.py`, `scripts/det_d2_bisect.py`, `scripts/run_isolated.py`
**Tests:** `tests/test_run_isolated.py` (6 passing)

## TL;DR

The 2026-04-23 determinism floor (3-run same-config produces
bitwise-identical canon md5) regressed when Phase 2.10d Task A added
end-of-run lifecycle and tier-reclassification writes to
`data/governor/edges.yml`. **The exclusive drift source is
`edges.yml` mutations**: D2 bisect shows that restoring just that
one file (out of 4 candidates) closes the 0.227 Sharpe gap between
clean and drifted state, while restoring any of the other three
(`edge_weights.json`, `regime_edge_performance.json`,
`lifecycle_history.csv`) has zero effect.

A new wrapper `scripts/run_isolated.py` snapshots and restores the
full mutable governor state around each backtest invocation. **Under
the harness, three same-config runs produce Sharpe 0.984 / 0.984 /
0.984 with one unique canon md5 — bit-for-bit determinism restored.**

The harness should become the default for all measurement runs going
forward; documented below.

## D1 — Reproduce the variance

**Driver:** `scripts/det_d1_repro.py --runs 5`

Five 2025 OOS backtests, prod-109, ML-off, `fill_share_cap=0.20`,
`--reset-governor` each run, NO state restoration between runs.
Each run hashes all 7 files in `data/governor/` before and after.

| Run | Sharpe | run_id (prefix) | Files mutated this run |
|-----|--------|-----------------|------------------------|
| 1 | **0.984** | `2832319d…` | edges.yml, edge_weights.json, lifecycle_history.csv |
| 2 | -0.336 | `ca69820c…` | edges.yml, edge_weights.json, lifecycle_history.csv |
| 3 | 0.057 | `aefbad06…` | edges.yml, edge_weights.json, lifecycle_history.csv |
| 4 | -0.142 | `2e39fa0e…` | edges.yml, edge_weights.json, lifecycle_history.csv |
| 5 | 0.129 | `e7de91fb…` | edges.yml, edge_weights.json, lifecycle_history.csv |

- **Sharpe range: 1.32** (max 0.984 in run 1, min -0.336 in run 2).
- **Canon md5 unique: 5 / 5** — every run produced a different trade log.
- `regime_edge_performance.json` did NOT mutate (file remained empty
  per the `--reset-governor` flow); it's a candidate but not active.
- `metalearner_*.pkl` files unchanged (only the offline trainer writes them).

D1 thus reproduces the round-3 ship-blocker variance under controlled
conditions in a single worktree. The variance is intra-worktree, not
cross-worktree as the round-3 audit suggested.

## D2 — Bisect the drift source

**Driver:** `scripts/det_d2_bisect.py`

Two reference states:
- `data/governor/_clean_pre_d1/` — captured from the idle
  `trading_machine-2/data/governor/` before D1 ran. Anchor for "clean."
- `data/governor/_drifted_post_d1/` — captured by
  `det_d2_bisect.py --snapshot-drifted` after D1 finished. Anchor
  for "drifted."

For each of the four candidate files in `data/governor/`, the bisect
restores the full drifted state, overrides only that one file from
clean, and runs a 2025 OOS Q1 backtest. Six runs total
(2 baselines + 4 single-file overrides).

| Variant | Sharpe | Δ vs DRIFTED (0.757) | Δ vs CLEAN (0.984) |
|---------|--------|------------------------|---------------------|
| BASELINE_DRIFTED                       | 0.757   | +0.000   | -0.227 |
| BASELINE_CLEAN                         | 0.984   | +0.227   |  0.000 |
| **OVERRIDE_edges.yml**                 | **0.984** | **+0.227** |  **0.000** |
| OVERRIDE_edge_weights.json             | 0.757   |  0.000   | -0.227 |
| OVERRIDE_regime_edge_performance.json  | 0.757   |  0.000   | -0.227 |
| OVERRIDE_lifecycle_history.csv         | 0.757   |  0.000   | -0.227 |

**Decisive: `edges.yml` is the exclusive drift source.** Restoring it
(while leaving the other three drifted) reproduces the clean Sharpe
exactly (0.984). Restoring any of the others while leaving edges.yml
drifted produces the drifted Sharpe exactly (0.757). The other three
files mutate at end-of-run but their content does not feed back into
subsequent run outcomes — they are write-only audit artifacts under
the current code path.

### Why `edges.yml` drives the variance

Two end-of-run code paths in `orchestration/mode_controller.py:920-933`
mutate `edges.yml`:

1. `governor.evaluate_lifecycle(metrics.trades)` — Phase 2.10d Task A's
   zero-fill / sustained-noise / soft-pause / revival triggers. Writes
   status changes (`active` → `paused` / `retired`, `paused` → `active`
   on revival).
2. `governor.evaluate_tiers(trades_path=trades_path)` — Phase 2.10d
   Task A's TierClassifier hook. Writes tier reclassifications
   (`alpha` / `feature` / `context`) per Layer-2 design.

Subsequent `--reset-governor` runs read the mutated `edges.yml` at
startup. Different active edges → different signal universe → different
fills → different Sharpe. `--reset-governor` only resets in-memory
weights (`governor.reset_weights()` at `governor.py:706`), not the
persisted edge-status / tier file.

## D3 — Isolation harness

**Module:** `scripts/run_isolated.py`

The harness snapshots and restores the four mutable files in
`data/governor/` around each backtest invocation:

```python
ISOLATED_FILES = [
    "edges.yml",
    "edge_weights.json",
    "regime_edge_performance.json",
    "lifecycle_history.csv",
]
```

Three primitives:

- `save_anchor()` — copy each ISOLATED_FILE to
  `data/governor/_isolated_anchor/`.
- `restore_anchor()` — copy each ISOLATED_FILE back. **Files absent
  from the anchor are deleted from the live tree** (e.g. an empty-history
  anchor stays empty even if a run appended).
- `isolated()` context manager — restore on entry, restore on exit
  (success or exception). Restoring on exit means a sequence of
  isolated runs leaves the worktree in the same state regardless of
  which run mutated.

End-of-run lifecycle and tier writes still happen as designed (so
production observability is intact); the harness reverts them between
measurement runs.

PYTHONHASHSEED=0 re-exec guard preserved (gated behind
`_reexec_if_hashseed_unset()`, called only from `__main__` so import-
side effects are zero — important for testability).

### Tests — `tests/test_run_isolated.py`

6 tests, all passing:
- `test_save_and_restore_roundtrip` — bytes match after save → mutate → restore.
- `test_restore_deletes_files_absent_in_anchor` — lifecycle_history
  doesn't leak across runs.
- `test_isolated_context_restores_on_exit` — context manager normal exit.
- `test_isolated_context_restores_on_exception` — context manager
  exception path.
- `test_restore_without_anchor_raises` — fail-loud on missing anchor.
- `test_isolated_files_list_covers_phase_210d_mutations` — sentinel
  asserting ISOLATED_FILES drift requires intentional update.

## D4 — Verify the harness restores the floor

**Driver:** `scripts/run_isolated.py --runs 3`

After restoring the live `data/governor/` to match `_clean_pre_d1/`
and saving the isolated anchor, three same-config runs:

| Run | Sharpe | trades_canon_md5 |
|-----|--------|--------------------|
| 1 | **0.984** | `0d552dd166bc2d8f897c23a0f82d429b` |
| 2 | **0.984** | `0d552dd166bc2d8f897c23a0f82d429b` |
| 3 | **0.984** | `0d552dd166bc2d8f897c23a0f82d429b` |

**Sharpe range: 0.0000.** **Canon md5 unique: 1 / 3.** **PASS** —
the 04-23 floor is restored. Trade outcomes are bit-for-bit
identical across same-config runs under the harness.

## Recommendations

### Make the harness the default for measurement

All future measurement / sweep / validation runs should wrap
`ModeController.run_backtest` in `isolated()`. Concretely:

1. **Update `scripts/run_oos_validation.py` to import and use
   `run_isolated.isolated()`** — the canonical OOS validation flow
   (the same one Path 1 ship-validation used) inherits the harness
   transparently. Single-line change in `run_q1()` /
   `run_q2()` / `run_counterfactual()`.

2. **Update `scripts/sweep_cap_recalibration.py`** to use the
   isolation context as well. The existing
   `snapshot_lifecycle_state` / `restore_lifecycle_state` partial
   implementation correctly snapshotted edges.yml + edge_weights +
   regime_edge_performance but missed lifecycle_history.csv. The full
   harness (run_isolated) is the right replacement.

3. **Document in `docs/Core/execution_manual.md`**: any A/B
   measurement that compares same-config runs MUST go through
   `scripts/run_isolated.py` or a wrapper that uses `isolated()`.
   Single-run measurements without the harness are valid for
   exploration but cannot be cited in audit docs as "the system's
   Sharpe under config X" — they're ±0.7 noise per the D1 result.

I am NOT proposing to make production backtests automatically use the
harness — production is supposed to mutate state (lifecycle decisions
are real production output). The harness applies only to measurement.

### Update `scripts/run_deterministic.py` or deprecate

The 04-23 harness (`scripts/run_deterministic.py`) snapshots
`edge_weights.json` + `regime_edge_performance.json` only, and uses
`--no-governor` to suppress end-of-run writes. It's still correct
under that exact use case (deterministic A/B without lifecycle
mutation), but the project has moved past `--no-governor` to
`--reset-governor` for measurement runs. Suggested action: add a
deprecation note pointing to `run_isolated.py` as the post-Phase-2.10d
floor; keep run_deterministic.py functional for backwards
compatibility with old anchors.

### Re-validate Path 1 ship state

The round-3 ship-blocker (`docs/Audit/path1_ship_validation_2026_05.md`)
measured Sharpe -0.378 for cap=0.20 + ML-on. That measurement was
governor-state-drifted; it doesn't reflect the actual underlying
performance of the config. **Path 1 ship state should be re-validated
under the harness before the merge decision.** I recommend the director
run:

```bash
PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 3 --task q1
```

…with `metalearner.enabled: true` and `fill_share_cap: 0.20` in
`config/alpha_settings.prod.json`. If three isolated runs produce
Sharpe within ±0.02 AND the value is in the >0.65 full-pass range,
the ship was the right call all along; the variance was a measurement
artifact. If the central tendency still lands in partial-pass / ambiguous
territory, the conclusion is different but at least it's based on a
stable measurement.

## Usage one-liner

```bash
# 1. Snapshot anchor (one-time, before measurement campaign)
python -m scripts.run_isolated --save-anchor

# 2. Single isolated run
PYTHONHASHSEED=0 python -m scripts.run_isolated --task q1

# 3. Multi-run determinism / variance check (PASS = ±0.02 + 1 unique md5)
PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 3 --task q1
```

## What this DOES NOT settle

1. **Cross-worktree variance.** Two different worktrees with different
   accumulated lifecycle state produce different "starting points"
   even with the same config. The harness fixes intra-worktree
   reproducibility; cross-worktree comparisons still need an
   anchor-sync step (each worktree's anchor must match by md5).
   Trivial fix when needed but not done here.
2. **Anchor staleness.** If the anchor was taken months ago, lifecycle
   has retired/paused/revived edges autonomously since. A measurement
   under that stale anchor reflects performance against an outdated
   active stack. The harness has no opinion about anchor freshness;
   the operator must decide. Suggest: snapshot a new anchor before
   each measurement campaign.
3. **The actual Sharpe number under cap=0.20 + ML-on.** This audit
   establishes the floor; the *measurement* of Path 1 ship state under
   the floor is a separate (recommended above) follow-up.
4. **Whether `--reset-governor` semantics are correct.** Currently
   `--reset-governor` resets in-memory weights only and leaves
   `edges.yml`/lifecycle state alone. The end-of-run lifecycle writes
   then happen and persist. An alternative API where `--reset-governor`
   also restores edges.yml from a snapshot at startup would close the
   drift at source — but it would also change production semantics in
   ways the director should weigh in on. Out of scope for this
   investigation.

## Boundaries respected

- No Engine B / Engine C / live_trader / dashboard touches.
- No production config edits (`config/alpha_settings.prod.json`,
  `config/regime_settings.json` unchanged).
- `metalearner.enabled` stays `false` on main per the standing rule.
- No feature work; pure infrastructure repair.
- Branch will be pushed to `determinism-floor-restore`; not merged to main.
