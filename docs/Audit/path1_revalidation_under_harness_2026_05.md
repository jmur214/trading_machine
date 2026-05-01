# Path 1 Re-Validation Under the Determinism Harness — 2026-05

**Date:** 2026-05-01
**Branch:** `path1-revalidation-under-harness`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-agentA-rev`
**Driver:** `scripts/path1_revalidation_grid.py`
**Window/universe:** 2025-01-01 → 2025-12-31, prod 109, RealisticSlippageModel
**Harness:** `scripts.run_isolated.isolated()` wraps every backtest;
all 12 runs use `--reset-governor` and start from the same isolated
anchor.

## TL;DR — clean numbers, decisive result

All four cells satisfy the harness invariant (within-cell Sharpe range
= 0.0000 across 3 runs; 1 unique trades canon md5). The variance that
plagued rounds 1-3 is gone.

| Cell | Cap | ML | **Sharpe** | CAGR % | MDD % | Vol % | WR % | Within-cell range | Canon md5 |
|------|------|------|-----------|--------|-------|-------|------|-------------------|-----------|
| A1.0 (anchor)      | 0.25 | false | **0.407**   | 1.90 | -2.95 | 4.96 | 47.13 | 0.0000 | `6771d2f1…` |
| A1.1 (cap only)    | 0.20 | false | **0.984**   | 4.57 | -3.03 | 4.68 | 48.73 | 0.0000 | `0d552dd1…` |
| A1.2 (ML only)     | 0.25 | true  | **-0.029**  | -0.28 | -4.04 | 5.12 | 46.46 | 0.0000 | `3ea3edd2…` |
| A1.3 (ship state)  | 0.20 | true  | **0.406**   | 2.01 | -3.05 | 5.27 | 47.13 | 0.0000 | `40b85253…` |

For reference (2025 benchmarks): SPY 0.955, QQQ 0.933, 60/40 0.997.

## Verdict on cell A1.3 (cap=0.20 + ML on, the proposed ship state)

**A1.3 Sharpe = 0.406. PARTIAL PASS, NOT FULL PASS.**

Pre-committed Phase 2.10d gate from
`docs/Core/forward_plan_2026_04_30.md`:

| Sharpe range | Verdict |
|---|---|
| < 0.2 | Kill thesis |
| 0.2 – 0.4 | Ambiguous |
| **0.4 – 0.65** | **Partial pass** ← A1.3 lands at 0.406 |
| > 0.65 | Full pass |

The cap=0.20 + ML-on combination clears the partial-pass threshold by
0.006 Sharpe. The +0.749 lift Agent C measured in round 1 (cap=0.25 +
ML-on → 1.064) was governor-drift coincidence: under the harness,
cap=0.25 + ML-on is **-0.029** Sharpe, a **-1.093** Sharpe correction
to the round-1 number.

**ML-on does not stack with cap=0.20 the way the prior numbers suggested.**
Comparing A1.1 (cap-only) to A1.3 (cap + ML):
- A1.1 cap-only: 0.984 (full-pass clear)
- A1.3 cap + ML: 0.406 (partial-pass)
- ML cost on top of cap=0.20: **-0.578 Sharpe**

Symmetrically at cap=0.25:
- A1.0 cap-only: 0.407
- A1.2 cap + ML: -0.029
- ML cost on top of cap=0.25: **-0.436 Sharpe**

The ML model is a **net drag of 0.4 to 0.6 Sharpe** in 2025 OOS prod-109,
regardless of the cap value. This is the opposite of Agent C's
robustness audit conclusion, and the difference is determinism: their
+0.749 lift was a measurement artifact of a particular (drifted)
governor state where the ML's predictions happened to align with
positive trades; under controlled measurement the model's signal is
negative.

## Reconciliation with the prior wild numbers

Five same-window prod-109 measurements compared to their
harness-controlled equivalents:

| Source | Cap | ML | Drifted Sharpe | Harness Sharpe | Δ |
|--------|------|------|----------------|----------------|------|
| Phase 2.10d task C (a1516cf, 2026-04-30) | 0.25 | false | 0.315 | **0.407** | +0.092 |
| Cap-recal A0 (round 2, 2026-04-30)       | 0.25 | false | 0.562 | **0.407** | -0.155 |
| Cap-recal A3 (round 2, 2026-04-30)       | 0.20 | false | 0.920 | **0.984** | +0.064 |
| Bracket B3 v2 (round 2, 2026-04-30)      | 0.20 | false | 1.102 | **0.984** | -0.118 |
| Agent C round-1 ML (2026-04-30)          | 0.25 | true  | 1.064 | **-0.029** | **-1.093** |
| Path 1 ship round 3 (2026-04-30)         | 0.20 | true  | -0.378 | **0.406** | +0.784 |

Six prior measurements span Sharpe values from -0.378 to 1.102. **The
true (harness-controlled) values span 4 cells with at most ±0.6
spread per cell — every prior single-run was within ±1.1 Sharpe of
its true value, but the *direction* of the error was unpredictable.**
The drift could push a measurement above the audit number, below it,
or all the way across the partial-pass / full-pass boundary. None of
the round-1-3 Sharpes can be cited as ground truth without re-running
under the harness.

Specifically:
- The bracket sweep's *shape* (cap=0.20 better than cap=0.25 at
  ML-off) holds robustly: 0.984 vs 0.407 = +0.577 Sharpe lift,
  consistent with the +0.557 / +0.358 ranges measured in rounds 2-3
  under different drift states.
- The cap=0.20 + ML-on stacking *direction* was wrong: it does not
  compose, it cancels. Prior conclusion overturned.
- The Phase 2.10d gate verdict for the *originally-shipped* config
  (cap=0.25, ML off, task C) revises from 0.315 (AMBIGUOUS bucket)
  to 0.407 (PARTIAL PASS bucket). The original gate was a tier-line
  call; under harness it crossed the partial-pass line.

## Recommended deployment config for main

**Ship `fill_share_cap: 0.20` only. Keep `metalearner.enabled: false`.**

Reasoning:

1. **A1.1 is the harness-validated full-pass cell** — Sharpe 0.984
   clears the > 0.65 gate by 0.334 with no need for ML stacking.
   CAGR 4.57%, MDD -3.03%, vol 4.68% — the same defensive-skew
   profile Path 1 was meant to deliver, just with an honest number
   underneath.
2. **A1.3 is partial-pass only** at 0.406, and ML adds -0.578 Sharpe
   on top of cap=0.20. Shipping ML enabled puts deployment in the
   weaker-performing state by ~0.58 Sharpe.
3. **The portfolio meta-learner needs re-validation under the harness
   before Phase 2.11 proper considers per-ticker training.** Agent
   C's +0.749 audit was the entire reason `metalearner.enabled` was
   even on the table — that audit was governor-drifted, so the
   foundation of the Phase 2.11 unblock argument needs new evidence
   before it can be cited.

cap=0.20 is already on main (commit `a1516cf`); no config change
required to reach the recommended state. **The only deployment action
is leaving `metalearner.enabled` at its current `false` value** —
which is the standing rule per CLAUDE.md but worth re-affirming
explicitly given the +0.749 audit that came in conditionally.

## A2 — harness as default for OOS validation entry-points

Two scripts updated to use `run_isolated.isolated()` by default:

### `scripts/run_oos_validation.py`
- `run_q1` / `run_q2` now accept `use_isolation: bool = True` and wrap
  the `ModeController.run_backtest` call in `_isolation_ctx(...)`.
- New CLI flag `--no-isolation` (opt-out) for legacy / exploratory
  runs.
- If no isolated anchor exists at first invocation, the script
  auto-saves one from current state — convenience for the first
  user.

### `scripts/sweep_cap_recalibration.py`
- `LIFECYCLE_FILES` now includes `lifecycle_history.csv` (synced with
  `run_isolated.ISOLATED_FILES`). The sweep already had a partial
  snapshot/restore mechanism; the missing file was the only gap.
- `run_one()` accepts `post_restore: bool = True`. Default-on means
  the sweep restores the anchor AFTER each invocation, making the
  sweep idempotent across calls.
- New CLI flag `--no-isolation` (opt-out).

### Tests — `tests/test_oos_validation_isolation_default.py`
9 tests, all passing:
- `test_run_q1_default_uses_isolation` — `run_q1(use_isolation=)`
  defaults to True.
- `test_run_q2_default_uses_isolation` — same for `run_q2`.
- `test_run_oos_main_no_isolation_flag_present` — CLI exposes
  `--no-isolation` opt-out.
- `test_isolation_ctx_returns_isolated_context_by_default` — the
  context object behaves like a context manager and auto-saves the
  anchor if missing.
- `test_isolation_ctx_returns_nullcontext_on_opt_out` — opt-out path.
- `test_sweep_run_one_default_post_restore` — sweep's `post_restore`
  defaults to True.
- `test_sweep_lifecycle_files_includes_history` — sentinel for the
  missing-file gap that originally caused the drift.
- `test_sweep_no_isolation_flag_present` — sweep CLI exposes the
  opt-out.
- `test_sweep_lifecycle_files_match_run_isolated` — the two harnesses
  agree on the snapshot file set so a measurement is consistent
  regardless of which entry point is used.

Combined with the 6 existing `tests/test_run_isolated.py` tests, the
determinism harness has 15 tests passing.

## Open issues / what this DOES NOT settle

1. **Why does the meta-learner hurt under the harness?** Agent C's +0.749
   was a drifted-state coincidence; under controlled measurement it's
   -0.4 to -0.6. This is an *empirical* conclusion under one
   harness-anchored governor state — different anchor (e.g.
   post-pruning at different time) might give different
   cap×ML interactions. The bracket sweep's lesson applies: shape is
   robust, magnitude is not. Recommend a future C2-style walk-forward
   under the harness before re-considering ML enable.

2. **Universe-B has not been re-validated under the harness.** The
   deployment-boundary doc (`docs/Core/deployment_boundary_2026_05.md`)
   states the universe boundary based on Universe-B Sharpe 0.273
   (drifted) — that number itself is a drifted-state measurement.
   The universe-collapse phenomenon is real (Agent D's ADV-floor
   diagnosis is independent evidence) but the exact 0.273 number is
   not yet harness-confirmed. The boundary doc's directional claim
   stands; the magnitude is unconfirmed until a Universe-B harness run.

3. **Multi-year harness check.** A single 2025 OOS measurement is
   insufficient evidence for a deployment commitment, even at Sharpe
   0.984. The cap-recalibration audit ran multi-year on cap=0.20 +
   ML-off and reported in-sample Sharpe 1.113 — that number is
   probably also drifted. Recommend multi-year (2021-2024) under the
   harness as a follow-up before final ship.

4. **The harness only fixes intra-worktree drift.** Cross-worktree
   anchor sync still requires md5 match. For multi-agent campaigns
   that compare numbers across worktrees, the operator must
   explicitly verify anchor parity.

## Reproduction

```bash
# 1. Set up isolated worktree (one-time)
cd /Users/jacksonmurphy/Dev/trading_machine-2
./scripts/setup_agent_worktree.sh agentA-rev path1-revalidation-under-harness
cd ../trading_machine-agentA-rev

# 2. Run the full 4-cell × 3-run grid
PYTHONHASHSEED=0 python -m scripts.path1_revalidation_grid

# 3. Single-cell debugging
PYTHONHASHSEED=0 python -m scripts.path1_revalidation_grid --cell A1.3
```

Output at `data/research/path1_revalidation_grid.json`. Trade logs at
`data/trade_logs/<run_uuid>/` (12 UUIDs total).

## Boundaries respected

- `metalearner.enabled` stays `false` on main — branch `path1-revalidation-under-harness`
  flips it temporarily inside each ML cell's run, then restores
  the alpha config from backup. No persistent main-branch change to
  ML default.
- No engine code touched (signal_processor, lifecycle, edges, governor).
- No Engine B / C / live_trader / dashboard changes.
- Path 2 / walk-forward branches not touched.
- Branch will be pushed only to origin/path1-revalidation-under-harness;
  not merged to main without director approval.
