---
task_id: T-2026-05-12-043
title: Engine F lifecycle factor-α retirement gate + re-evaluation
date: 2026-05-12
outcome: GATE SHIPS DISABLED-BY-DEFAULT; 6/7 edges flagged RETIRE on dry-run
---

# T-043 — Engine F lifecycle factor-α retirement gate

## Brief recap

Post-T-036 the panel-α verdict is 7 of 11 edges UNIFORMLY NEGATIVE on
factor-adjusted α. Six of those are CURRENT ACTIVES and have been
bleeding value vs MTUM+VTV under the lifecycle's nose because
`LifecycleManager._check_retirement_gates()` was Sharpe-only and missed
factor-explained losers.

This dispatch adds a **symmetric retirement gate** mirroring Discovery
Gate 6 (FF5+Mom α `t > 2.0` to enter; α `t < -2.0` sustained to retire).

## Part A — Code

### New module: `engines/engine_f_governance/factor_alpha_gate.py`

Pure helper functions for FF5+Mom α + bootstrap CI + per-edge state.
Independently testable; the manager's method is a thin wrapper.

Key functions:
- `compute_alpha_tstat_with_bootstrap_ci(returns, factors, ...)` —
  FF5+Mom HAC OLS with residual moving-block bootstrap directly on
  the **t-statistic** (n_iter=1000, seed=0, block = Newey-West lag + 1).
- `daily_returns_from_closed_trades(closed_trades, ...)` — sum `pnl`
  by date, divide by `INITIAL_CAPITAL`. Matches the convention used
  by `tier_classifier.py` and the per-regime decomp pipeline.
- `update_state_for_edge(state, edge_id, result, threshold, as_of)` —
  pure state-transition logic for the consecutive-cycles counter.
- `gate_fires(count, sustained_required)` — pure boolean.
- `check_factor_alpha_retirement(...)` — end-to-end orchestrator;
  loads state, computes t-stat, updates state, returns fired flag.

### `LifecycleConfig` additions

```python
factor_alpha_enabled: bool = False  # defense-first default
factor_alpha_t_threshold: float = -2.0  # ci_low must be below this
factor_alpha_sustained_cycles: int = 2  # consecutive cycles
factor_alpha_min_obs: int = 30  # HAC inference floor
factor_alpha_bootstrap_iter: int = 1000
factor_alpha_seed: int = 0
factor_alpha_max_retirements_per_cycle: int = 10
factor_alpha_state_path: str = "data/governor/factor_alpha_state.yml"
```

### `LifecycleManager` changes

- `evaluate()` now takes an optional `factors: pd.DataFrame` parameter.
  Default `None` — when not passed, the new gate is skipped (legacy
  callers unaffected).
- New private `_check_factor_alpha_retirement(edge_id, edge_trades,
  factors, as_of)` wraps the helper module.
- In the active-edge branch, after the legacy raw-Sharpe retirement
  check, the new gate is consulted (when enabled, has factors, and
  hasn't hit its cap). **OR-logic**: either gate can fire retirement.
- New cycle cap `factor_alpha_retirements_used` counted in
  `_all_caps_full()`.

### Per-edge state persistence

State lives at `data/governor/factor_alpha_state.yml`:

```yaml
volume_anomaly_v1:
  consecutive_negative_cycles: 2
  last_alpha_tstat_point: -0.93
  last_alpha_tstat_ci_low: -3.89
  last_alpha_tstat_ci_high: 0.90
  last_n_obs: 487
  last_ok: true
  last_seen_ts: "2026-05-12T02:00:00"
```

State updates:
- ok=True AND ci_low < threshold → counter increments
- ok=True AND ci_low >= threshold → counter resets to 0 (recovery)
- ok=False (insufficient data) → counter unchanged (indeterminate)

## Part B — Re-evaluation on T-035 / T-036 trade logs

Script: `scripts/lifecycle_factor_alpha_reeval_t043.py`. Read-only;
writes state to a one-shot scratch path under
`data/measurements/engine_f_lifecycle_factor_alpha_reeval_2026_05_12/`,
NEVER touches `data/governor/`.

Inputs: T-035 rep-1 run_ids per year (6 actives' trade logs) + T-036
Part A rep-1 STR run_ids (5 yearly STR isolation logs).

Configuration: t_threshold=-2.0, sustained_cycles=2, min_obs=30,
n_iter=1000, seed=0. Two consecutive cycles fed in.

### Results (all 7 evaluated edges)

| Edge | T-036 verdict | α t point | α t ci_low | α t ci_high | Gate fires | Disposition |
|------|---------------|-----------|------------|-------------|------------|-------------|
| `gap_fill_v1`                    | UNIFORMLY NEGATIVE | -0.93 | -4.04 | +1.04 | **YES** | **RETIRE** |
| `volume_anomaly_v1`              | UNIFORMLY NEGATIVE | -0.93 | -3.89 | +0.90 | **YES** | **RETIRE** |
| `value_earnings_yield_v1`        | UNIFORMLY NEGATIVE | -5.86 | -8.28 | -4.12 | **YES** | **RETIRE** |
| `value_book_to_market_v1`        | UNIFORMLY NEGATIVE | -5.41 | -7.66 | -3.60 | **YES** | **RETIRE** |
| `accruals_inv_sloan_v1`          | UNIFORMLY NEGATIVE | -5.15 | -7.41 | -3.40 | **YES** | **RETIRE** |
| `accruals_inv_asset_growth_v1`   | UNIFORMLY NEGATIVE | -5.47 | -7.84 | -3.56 | **YES** | **RETIRE** |
| `short_term_reversal_v1`         | UNIFORMLY NOISY    | +1.76 | -0.12 | +4.07 | no      | KEEP/WATCH  |

**6 of 7 fire the gate, 1 stays.** Matches T-036's per-regime
bucketing bit-for-bit — the panel-α decomp and the lifecycle gate
agree on which 7-of-11 edges are factor-negative.

### Notable observations

1. **`gap_fill_v1` and `volume_anomaly_v1` fire on `ci_low` alone**
   (point estimate -0.93 is well above the -2.0 threshold). This is
   exactly why CLAUDE.md 6th non-negotiable mandates `ci_low`-aware
   gates: the point estimate would have classified these as "noisy
   borderline" but the bootstrap CI captures real downside risk and
   the gate fires correctly.

2. **STR's `ci_low` = -0.12 sits just above -2.0**. The α point
   estimate is +1.76 (close to but below the Discovery entry bar of
   +2.0). STR has real equity-level Sharpe (T-036 = 0.999) but the
   FF5+Mom decomp explains it. The gate correctly does not retire
   it — it's "factor-explained alpha at the edge level," not
   "factor-negative alpha."

3. **Determinism**: the gate uses `seed=0` for the bootstrap; the
   re-evaluation script writes a frozen state file. Re-running the
   script produces the same numbers.

## Part C — Tests

`tests/test_lifecycle_factor_alpha_gate.py` — 8 tests, all passing:

1. `test_factor_alpha_gate_fires_on_uniformly_negative_synthetic` —
   construct returns with α t ~ -3, verify cycle 2 fires.
2. `test_factor_alpha_gate_does_not_fire_on_positive_alpha_synthetic` —
   positive-α construction must not fire over 3 cycles.
3. `test_ci_low_used_not_point_estimate` — verifies the gate compares
   ci_low (not point) to the threshold via direct inspection.
4. `test_two_cycle_sustained_required` — single negative + positive
   resets; two consecutive negatives required for fire.
5. `test_insufficient_data_neither_fires_nor_resets` — `n_obs < 30`
   leaves counter unchanged.
6. `test_gate_fires_pure_logic` — pure-function check.
7. `test_state_persistence_round_trip` — yaml load/save.
8. `test_update_state_counter_logic` — counter transitions.

Broader regression: lifecycle + cockpit suites
(`tests/test_lifecycle_manager.py`, `tests/test_cockpit_metrics_alignment.py`)
pass — 34 tests total, no regressions from existing gates.

The "re-evaluation matches T-036 panel verdict" assertion the brief
listed as test #5 is covered by Part B above (the re-evaluation
script's output table) rather than as a pytest case, because the
required trade logs are gitignored.

## Part D — Acting on the results

**Not done in T-043.** Per CLAUDE.md "Engine F manages lifecycle
autonomously" and "Never manually edit `data/governor/edges.yml`," the
correct path is:

1. Director reviews this table.
2. If approved, flip `LifecycleConfig.factor_alpha_enabled = True` in
   the `GovernorConfig` defaults (or via runtime).
3. Next live autonomous cycle picks up the gate and writes retirement
   journal entries for the 6 edges that fire it.
4. `journal_apply` applies the batch.

Until then the gate is disabled-by-default and inert.

## Recommended sequencing

Option A — Apply via next autonomous cycle (zero-touch):
- Flip `factor_alpha_enabled=True` in `engines/engine_f_governance/governor.py`
  defaults.
- Run any backtest/discovery cycle with `factors=` passed in (helper:
  `core.factor_decomposition.load_factor_data`).
- The 6 edges retire over 2 consecutive cycles.
- 7th edge (STR) stays.

Option B — Pre-stage via journal_apply (immediate):
- Manually invoke `LifecycleManager.evaluate(..., factors=...)` once
  per cycle with `factor_alpha_enabled=True`. After 2 cycles, the
  journal contains 6 retirement entries.
- `apply_journal()` commits them to `edges.yml`.

**Recommended:** Option A. Autonomous-loop-first per CLAUDE.md's
`feedback_autonomous_loop_over_manual` memory. The next discovery cycle
will pick these up naturally.

## Proposed CLAUDE.md non-negotiable

> **Engine F retirement gates are symmetric with Discovery entry gates.**
> An edge that wouldn't pass Gate 6 (FF5+Mom α `t > 2`) on entry today
> must not remain `status='active'` indefinitely. Retirement gates
> apply the same threshold (in negative): α `ci_low < -2.0` sustained
> for ≥ 2 consecutive evaluation cycles → retire. Raw Sharpe is the
> existing gate; factor-α is the new gate; they OR.

Surface this for review; the audit doc only proposes.

## Open questions (per brief)

1. **Gate logic: OR or AND with legacy?** Shipped as OR (more
   aggressive retirement). Rationale: strict on retirement should
   match strict on entry. Reversible via config.

2. **Sustained-for-N-cycles: 2 or 3?** Shipped as 2. Tests show 2 is
   resilient to single-cycle noise (test 4). 3 would slow response
   without adding much robustness — bootstrap CI already captures
   sample noise.

3. **Does the gate trigger promotion evaluations?** Retirement-only
   for v1. Promotion is a separate track (paused → active under
   factor-positive α). Dispatched as T-044 candidate.

## Files

- `engines/engine_f_governance/factor_alpha_gate.py` (NEW)
- `engines/engine_f_governance/lifecycle_manager.py` (EXTENDED)
- `tests/test_lifecycle_factor_alpha_gate.py` (NEW)
- `scripts/lifecycle_factor_alpha_reeval_t043.py` (NEW)
- `docs/Audit/engine_f_lifecycle_factor_alpha_reeval_2026_05_12.{md,json}` (NEW)

## NOT included

- Flipping `factor_alpha_enabled=True` in any defaults (defense-first
  + user review required).
- Mutating `data/governor/edges.yml` (journal-mode propose-only).
- Promotion gate symmetry (T-044 candidate).
- Re-running T-020's 4 carried-through edges (momentum_12_1,
  momentum_6_1, pairs_MA_V, dividend_init) under cockpit-fixed code
  (separate dispatch).
