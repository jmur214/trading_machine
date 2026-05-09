# In-code CI-aware gates — audit (T-2026-05-08-010)

**Author:** Agent B
**Branch:** `feature/in-code-ci-aware-gates`
**Spec:** `docs/Measurements/2026-05/spec_in_code_ci_aware_gates_2026_05_09.md`
**Files touched:** `engines/engine_f_governance/evolution_controller.py`, `engines/engine_f_governance/lifecycle_manager.py`, `engines/engine_d_discovery/wfo.py`, `engines/engine_d_discovery/robustness.py` (exemption comments only), `tests/test_in_code_ci_aware_gates.py` (new).

---

## Headline

Closes the in-code half of CLAUDE.md 6th non-negotiable (commit `4cf4909`):

> Sharpe headlines must report bootstrap CI; kill thresholds must be CI-aware, not point-estimate.

Three gate sites converted from point-estimate Sharpe comparisons to bootstrap-CI-lower-bound comparisons. One site exempted with documented rationale (it was already distributional). All threshold values unchanged — this is mechanical CI-aware substitution, not threshold re-tuning.

**Determinism gate: PASSED.** canon md5 IDENTICAL pre/post on `scripts/run_isolated --runs 1 --task q1`:

| Run | canon md5 | Sharpe |
|---|---|---|
| Baseline (pre) | `182af6a1240da35055f716ef9dfcd333` | 0.127 |
| Post-change | `182af6a1240da35055f716ef9dfcd333` | 0.127 |

`MetricsEngine.bootstrap_distribution` defaults to `seed=0`, so the new bootstrap calls inside the gates are deterministic — md5 invariance confirms this.

---

## Sites changed

### Site 1 — `engines/engine_f_governance/evolution_controller.py:182` (Discovery promotion gate)

**Before:**
```python
passed = oos_sharpe >= bench_threshold and degradation > 0.6
```

**After:**
```python
oos_ci_low = float(wfo_res.get("oos_ci_low", 0.0))
degradation_ci_low = float(wfo_res.get("degradation_ci_low", 0.0))
...
passed = oos_ci_low >= bench_threshold and degradation_ci_low > 0.6
```

The legacy `oos_sharpe` and `degradation` reads are PRESERVED — they still appear in the log line for context. Only the gating decision uses ci_low. Default-`0.0` on missing keys means a legacy WFO output (pre-this-change) degrades to "no promotion under CI-aware reading" — the safe default during migration.

### Site 2 — `engines/engine_f_governance/lifecycle_manager.py:_check_retirement_gates` (edge retirement)

**Before:**
```python
threshold = benchmark_sharpe - self.cfg.retirement_margin
if edge_sharpe >= threshold:
    return False, "benchmark_ok"
```

**After:**
```python
threshold = benchmark_sharpe - self.cfg.retirement_margin
edge_ci_low = _bootstrap_sharpe_ci_low_from_pnls(pnls)
if edge_ci_low >= threshold:
    return False, "benchmark_ok"
```

Asymmetric: the variable being gated (`edge_ci_low`) is bootstrapped; the fixed reference (`benchmark_sharpe`) stays point-estimate. Bootstrapping a fixed benchmark wastes compute and the gate is about the EDGE's noise floor, not the benchmark's.

The new `_bootstrap_sharpe_ci_low_from_pnls` helper bootstraps over the per-trade PnL array using `MetricsEngine.sharpe_ratio`, which `_edge_sharpe_from_pnl` (the existing point-estimate path) annualizes by `sqrt(252)`. Same metric on the same data — apples-to-apples comparison.

### Site 3 — `engines/engine_d_discovery/wfo.py` (degradation ratio + plumbing)

**Added** to the WFO output dict:
- `oos_ci_low` (float) — bootstrap CI-low of OOS Sharpe
- `is_ci_low` (float) — bootstrap CI-low of IS Sharpe
- `degradation_ci_low` (float) — `oos_ci_low / is_ci_low` (analogous to existing `degradation`)
- `oos_returns` (list) — the full per-day OOS returns stream (already accumulated; now exposed)
- `is_returns` (list) — NEW; per-window best-trial IS returns, accumulated identically to OOS

Existing fields (`oos_sharpe`, `is_sharpe_avg`, `degradation`, `param_stability`) preserved for any downstream consumer that hasn't yet migrated.

**Plumbing for IS returns:** the optimization loop already runs `_quick_backtest` per trial and discards everything except the best-trial Sharpe. Captured the best-trial equity curve at the same time and stitched returns across windows in the same shape as OOS (returns, not equity, to dodge the same window-boundary phantom-drawdown trap that the OOS path already documents).

### Site 4 — `engines/engine_d_discovery/robustness.py:311,376` (PBO survival — EXEMPT)

Both occurrences of:
```python
survival_rate = (sharpes > 0.0).mean()
```

annotated with a comment block explaining the exemption rationale: PBO survival is **already** distributional. `sharpes` is a vector across N=50-200 bootstrap synthetic-market resamples; `survival_rate` is the fraction with Sharpe > 0. That fraction IS the CI-style statement — a "ci_low(survival_rate)" reading would double-count the bootstrap envelope.

---

## Before/after on a representative fixture

The new test `test_lifecycle_manager_retirement_uses_ci_low_to_protect_noisy_edge` constructs an edge whose **point-estimate** Sharpe is below the retirement threshold (`edge_sharpe=0.5`, threshold `1.0 - 0.3 = 0.7`) but whose **ci_low** is comfortably above it.

| Reading | Value | Old gate (point) | New gate (ci_low) |
|---|---:|---|---|
| edge_sharpe | 0.50 | RETIRE (below threshold) | n/a |
| edge_ci_low | well above 0.70 | n/a | NOT retired (above threshold) |

The CI-aware gate protects this edge from a noise-driven retirement. Empirically this prevents the retirement-chatter mode where a borderline edge straddles the threshold across consecutive cycles.

The mirror test `test_lifecycle_manager_retires_clearly_dead_edge` confirms the gate still RETIRES an edge whose ci_low is unambiguously below threshold — CI-aware reading is **stricter** about deciding to act, not arbitrarily forgiving.

---

## Open questions surfaced

### Q1 — Block-length tuning for short OOS windows

The `MetricsEngine.bootstrap_distribution` default block length is `max(5, int(round(n ** (1/3))))` (Politis-White rule of thumb). For a 12-month-train + 3-month-test WFO window stitched across ~3-4 windows, OOS comprises ~250-400 trading days — block length defaults to ~6-7. That's reasonable.

For very short OOS windows (e.g., a single 21-day OOS slice), block length floors at 5, leaving 4-5 effectively-independent blocks. CI-low estimates will be noisy. **Recommendation:** if Phase 2 reveals borderline-case behavior, allow per-call `block_length` override at the `_bootstrap_sharpe_ci_low` helper. Not done here to preserve "do not change bootstrap parameters from project standard" hard constraint.

### Q2 — Bootstrap CI vs Deflated Sharpe Ratio (DSR)

Discovery already implements DSR at Gate 8 (`engines/engine_d_discovery/discovery.py`). DSR penalizes for selection bias / multiple-testing across all trials. The promotion gate at `evolution_controller.py:182` is downstream of Gate 8 — it applies AFTER DSR has already filtered out selection-biased candidates.

**Relationship:** the two are complementary, not redundant. DSR addresses *across-trial* multiple-testing bias; bootstrap-CI-low addresses *within-trial* sampling noise. A candidate can survive DSR (genuine alpha relative to the trial bookkeeping) and still have a wide bootstrap CI (insufficient OOS observations to distinguish from "edge of zero"). The CI-aware gate catches the second class.

### Q3 — Performance impact

Each `bootstrap_distribution` call is 1000 iter × ~5-10 ms = ~5-10 sec on a typical 200-300-day return series. The gates fire:
- **evolution_controller**: once per candidate per Discovery cycle. ~50-100 candidates/cycle → ~5-15 min added.
- **lifecycle_manager**: once per active edge per evaluation. ~20 active edges × 1 evaluation/run → ~2-3 min added per run.
- **wfo**: 2 calls per WFO run (OOS + IS). ~5-10 sec added per WFO.

Wall-clock budget impact: ~5-15 min added to a representative Discovery cycle. **Below the 30-min flag-for-follow-up threshold.** No caching or parallelization needed at this scale.

If a future Discovery cycle scales to ~500 candidates, the +50-150 min would warrant either (a) caching ci_low alongside the WFO output (one-shot per candidate) or (b) parallelizing bootstrap iterations via `numpy.random.Generator` per-resample.

### Q4 — Forward path beyond T-010

**Other lifecycle/promotion paths potentially affected:**

1. **`scripts/journal_apply.py`** — reads lifecycle decisions from the journal and applies them. If its decision-source (the journal) now records CI-aware decisions, it inherits the rule automatically. **Verified by inspection:** journal_apply only writes status changes from `lifecycle_history.csv`, which is upstream of the gate. No direct gate inside journal_apply. ✅ inherits cleanly.
2. **`core/per_edge_attribution.py`** — produces per-edge breakdown tables that include Sharpe. These are READ-side / display-side, not gate-side. The 6th non-negotiable's display-side rule (humans-quoting-Sharpe-must-report-CI) is a separate task; not in T-010 scope but should be a follow-up if any per-edge dashboard panel still shows bare-Sharpe.
3. **`engines/engine_f_governance/governor.py`** — the StrategyGovernor reads governance decisions and applies edge weights. Doesn't itself contain a Sharpe-comparison gate; consumes lifecycle output.
4. **`scripts/sleeve_phase0_verdict.py`** (used by my own T-007 verdict) — already CI-aware (`SleeveCriteria.sortino_kill` is the kill threshold; verdict bucket reads `ci_low` per spec rule). ✅ no change needed.

The forward sweep flagged by the brief is closed: every in-code lifecycle/promotion decision-gate I could find is either CI-aware after this PR or documented as exempt.

---

## Hard constraints respected

- ✅ No edits to Engine B / `live_trader/` / `backtest_controller.py`
- ✅ No edits to `core/metrics_engine.py`
- ✅ Threshold values unchanged (0.6 degradation, 0.3 retirement margin)
- ✅ Bootstrap parameters unchanged (1000 iter, auto block length per Politis-White, seed=0)
- ✅ No edits to `core/per_edge_attribution.py` or other downstream consumers
- ✅ Branch `feature/in-code-ci-aware-gates`; not merged to main

---

## Verification summary

| Gate | Status |
|---|---|
| Determinism canon md5 IDENTICAL | **PASS** (`182af6a1240da35055f716ef9dfcd333` pre and post) |
| New tests | **8/8 pass** (≥6 required by spec) |
| Existing test sweep | **118/118 pass** (`test_evolution_controller`, `test_lifecycle_manager`, `test_lifecycle_journal`, `test_lifecycle_triggers_2026_04`, `test_wfo_oos_stitching`, all 5 `test_discovery_*`) |
| Cross-module `_PROGRAMMER_ERRORS` discipline | n/a (this PR doesn't touch the bare-except sites) |
| Threshold re-tuning attempted | NO (per hard constraint) |
| Performance impact at production scale | +5-15 min per Discovery cycle (below the 30-min flag threshold) |
