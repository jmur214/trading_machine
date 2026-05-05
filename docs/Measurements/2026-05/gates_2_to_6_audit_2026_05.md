# Gates 2-6 Audit — Geometry / Baseline / Production-Equivalence

**Branch:** `gates-2-through-6-audit`
**Date:** 2026-05-01
**Scope:** Read-only audit of `engines/engine_d_discovery/discovery.py::validate_candidate`,
gates 2 through 6, plus their supporting modules (`wfo.py`, `robustness.py`,
`significance.py`, `core/factor_decomposition.py`).

**The one question:** Do gates 2-6 have similar geometry-mismatch / baseline-definition /
production-equivalence bugs as Reform Gate 1 surfaced?

---

## TL;DR — headline summary

**All five gates fail the production-equivalence test in the same way Gate 1 did.**

| Gate | Verdict | Severity |
|---|---|---|
| 2 — PBO robustness (50 paths, survival > 0.7) | **FAIL** | critical (also has secondary univariate-resample bug) |
| 3 — WFO degradation (OOS/IS Sharpe) | **FAIL** | critical (also has secondary OOS-equity-stitching bug) |
| 4 — Permutation p-value (BH-FDR corrected) | **SUSPECT** | medium (test-statistic geometry, not test validity) |
| 5 — Universe-B transfer (Sharpe > 0) | **FAIL** | critical |
| 6 — Factor decomposition (intercept t > 2 AND alpha > 2%) | **FAIL** | critical (this is the gate that *first* surfaced the geometry issue in Q3) |

**Root cause is shared, not per-gate.** Gates 2-6 all consume an artifact produced
upstream by Gate 1's setup (lines 619-649 of `discovery.py`): a backtest of a
**single-edge `AlphaEngine`** at `risk_per_trade_pct = 0.01`, with no regime
detector and no other edges firing for capital rivalry. That setup's equity
curve is the substrate every subsequent gate measures. **You cannot fix gates
2-6 by patching them individually; the candidate's backtest geometry has to
change at the source.**

The fix is the same architectural fix already filed for Reform Gate 1
(memory: `project_gate1_reimplementation_problem_2026_05_01.md`): invoke the
production pipeline (`orchestration/mode_controller.py::run_backtest`) with
candidate-included vs candidate-excluded baselines, then derive the candidate's
attribution stream from that. Gates 2-6 should then operate on the
integration-attributed return stream rather than a standalone equity curve.

---

## Reform Gate 1 — the bug class we're hunting

The bug class, restated from `project_ensemble_alpha_paradox_2026_04_30.md` and
`project_production_ensemble_includes_softpaused_2026_05_01.md`:

1. The realistic cost model is **non-linear in trade size** (Almgren-Chriss
   square-root impact term `k × σ × √(qty/ADV)`).
2. In production, capital is split across an ensemble of ~6.5 effective edges
   (3 active + 14 soft-paused × 0.25). Per-fill `qty/ADV` stays sub-knee.
3. In a standalone single-edge backtest, the same edge gets 100% of the
   risk-per-trade allocation. Per-fill `qty/ADV` ≈ 6× larger; impact crosses
   the knee; signal is eaten by costs.
4. Same edge, same window, same cost model → **opposite verdicts**, because
   the test geometry doesn't match the deployment geometry.

A "production-equivalent" gate avoids this by running the candidate inside an
ensemble that matches deployment (3 active + soft-paused at 0.25× weight) and
attributing PnL per-fill to derive the candidate's return stream. The
standalone single-edge geometry in `validate_candidate` is the exact
anti-pattern the memory warns against.

---

## Gate 2 — PBO Robustness

**Location:** `discovery.py:696-735`, `engines/engine_d_discovery/robustness.py`.

### What the gate is supposed to test
Probability of Backtest Overfitting. Generate many bootstrap-resampled price
paths from the same statistical distribution as the actual data, run the
candidate strategy on each, count what fraction produce Sharpe > 0. If a
strategy survives many alternate realities, it isn't overfit to the one
realization we got. Threshold: survival rate ≥ 0.70.

### What the code actually tests
The gate composes three sub-pieces:

1. `RobustnessTester.generate_bootstrap_paths(df, n_paths=50, block_size=20)`
   — circular block bootstrap on **a single ticker's `Close` price
   pct-change series**. (`robustness.py:31`) The synthetic OHLC has H/L/O all
   set to the bootstrapped `Close`.

2. The `strategy_wrapper` at `discovery.py:702-725` creates a **new
   single-edge `AlphaEngine`** on each path:
   ```python
   t_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
   t_risk = RiskEngine({"risk_per_trade_pct": 0.01})
   ```
   No production edges are co-resident. No regime detector. No soft-paused
   edges at 0.25× weight.

3. `RobustnessTester.calculate_pbo` is called at `discovery.py:728` with
   `data_map[first_key]` — i.e., **only the first ticker's DataFrame** is
   bootstrapped. PBO is effectively a univariate test on one ticker.

### Geometry/baseline alignment

**FAIL** on two independent grounds:

1. **Standalone-vs-ensemble geometry.** The strategy_wrapper runs the
   candidate alone. Per the impact-knee math, a candidate that fires sub-knee
   in production can produce trades that hit the knee here, mis-pricing the
   bootstrap result. The PBO survival rate is measuring "would this candidate
   alone survive these synthetic paths," not "would the candidate's
   contribution to the production ensemble be robust."

2. **Univariate bootstrap.** Even setting (1) aside, `calculate_pbo` is
   passed a single ticker's DataFrame. The candidate is a multi-name edge
   that fires across 109 tickers in production. A 50-path bootstrap of one
   ticker's OHLC tells us almost nothing about the candidate's robustness on
   the actual universe. (Block-bootstrap of a single series is the right
   tool for *that single series*; it is the wrong tool for a multi-name
   universe-traded edge.) This is a separate bug from the geometry-mismatch
   issue and must be fixed independently.

### Recommended fix
- Replace the standalone single-edge wrapper with a production-equivalent
  ensemble backtest: the candidate co-resident with the active set + paused
  set at 0.25×. Survival = does the candidate's **integration-attributed**
  Sharpe stay > 0 across paths.
- Bootstrap the entire `data_map`'s synchronized cross-section, not a single
  ticker. The block bootstrap should pick the same date-block across all
  tickers simultaneously to preserve cross-sectional correlation.
- Revisit threshold: 0.70 survival was set against single-edge synthetic
  paths; the right threshold for an ensemble-attribution survival metric
  may differ.

---

## Gate 3 — Walk-Forward Optimization Degradation

**Location:** `discovery.py:737-765`, `engines/engine_d_discovery/wfo.py`.

### What the gate is supposed to test
WFO checks parameter stability over time. On rolling 12m-train / 3m-test
windows, optimize hyperparameters in-sample, lock them, measure
out-of-sample Sharpe. Compare OOS Sharpe to IS Sharpe — high degradation
ratio (<60%) means the strategy is overfit to the training window. The
gate currently passes `wfo_degradation = oos_sharpe / is_sharpe_avg`
through, but does NOT enforce a hard threshold in the final pass logic at
`discovery.py:905-911` (it's used in the composite fitness score at line
940 but isn't a gate criterion). Even so, OOS Sharpe is reported via
`wfo_oos_sharpe` and consumed by the fitness score — its correctness
matters.

### What the code actually tests
`WalkForwardOptimizer._quick_backtest` (`wfo.py:144-179`) builds the same
standalone single-edge `AlphaEngine` and `RiskEngine({"risk_per_trade_pct": 0.01})`
that Gate 1 builds, runs the candidate's edge alone with optimized
hyperparameters in 12m/3m rolling windows.

Two distinct issues:

1. **Standalone-vs-ensemble geometry.** Same as Gate 2 — the WFO measures
   the candidate's standalone behavior, not its contribution to the
   production ensemble. A candidate that's stable in production geometry
   may look unstable in standalone, and vice versa.

2. **Stitched OOS equity curve has phantom returns at window joins.** At
   `wfo.py:112`, the `oos_equity` list is built by appending each test
   window's raw equity values: `oos_equity.extend(test_res["equity_curve"])`.
   Each `equity_curve` starts at `initial_capital = 100_000` (because each
   test-window backtest is independent). When window N+1's first equity
   value (100_000) is appended after window N's last value (e.g.
   105_000), `pd.Series(oos_equity).pct_change()` at line 129 computes a
   spurious **−4.76% return at every window boundary**. The reported
   `oos_sharpe` is therefore polluted by N−1 phantom drawdowns where N is
   the number of OOS windows.

### Geometry/baseline alignment

**FAIL** on geometry; **separate FAIL** on OOS-equity stitching that's an
independent bug regardless of geometry.

### Recommended fix
- Replace `_quick_backtest` with a production-equivalent ensemble backtest
  on each window, attributing the candidate's PnL.
- Stitch OOS by **returns**, not equity values: convert each window's
  equity to a return series, concatenate the return series, then compute
  Sharpe. (Or compute per-window Sharpe and aggregate.)
- Optional: enforce `wfo_degradation >= 0.6` as an actual gate, since right
  now the value is informational.

---

## Gate 4 — Statistical Significance (Permutation Test, BH-FDR)

**Location:** `discovery.py:767-776`, `engines/engine_d_discovery/significance.py`.

### What the gate is supposed to test
Monte Carlo permutation null. Shuffle the strategy's daily returns 500
times, compute Sharpe of each shuffle, count what fraction of shuffles
produce a Sharpe ≥ the actual Sharpe. The resulting p-value tests "is the
observed Sharpe distinguishable from random ordering of the same returns."
A batch BH-FDR correction at the orchestrator level then controls
false-discovery rate when many candidates are tested simultaneously.

### What the code actually tests
At `discovery.py:771`:
```python
sig_result = monte_carlo_permutation_test(daily_returns, n_permutations=500)
```
where `daily_returns = equity_curve.pct_change().dropna().values` was built
at line 694 from Gate 1's **standalone single-edge backtest equity curve**.

The permutation test itself (`significance.py:28-102`) is mathematically
correct: it preserves the marginal distribution of returns and tests
whether the *temporal ordering* matters for the Sharpe ratio. Shuffling is
an appropriate null for this question.

### Geometry/baseline alignment

**SUSPECT** — different severity from Gates 2/3/5/6.

Gate 4's *test mechanics* (the shuffle + null distribution + p-value) are
correct. The issue is what return stream they're applied to.

- Under standalone geometry, `daily_returns` is the candidate's own
  equity curve volatility profile when fully-allocated. The null
  distribution is "shuffle THIS curve's returns." If the standalone curve
  happens to be too noisy (signal swamped by impact costs), the actual
  Sharpe is small and the null p-value is large — reject as
  insignificant. Same edge in production geometry might have a much
  cleaner attributed return stream and pass this test cleanly.
- Note that Gate 4 asks a different question from Gates 2/3/5/6: it
  tests "did the temporal ordering matter," not "would the strategy be
  robust to alternate realities" or "does it generalize." So the
  geometry question is "is the standalone return stream the right thing
  to test ordering on, or should it be the integration-attributed
  stream?" The latter is more diagnostically useful.
- BH-FDR at the orchestrator (`apply_bh_fdr` in `significance.py:105-207`)
  is correctly implemented. No issue there.

### Recommended fix
- Move `daily_returns` to come from the candidate's **integration-attributed
  per-day PnL** (production-equivalent ensemble backtest, candidate-included
  minus candidate-excluded, normalized to per-day returns). Then the
  permutation null tests "did the candidate's contribution depend on
  temporal ordering," which is the production-relevant question.
- This is a less severe fix than Gates 2/3/5/6 because the gate's mechanics
  remain correct — only the input stream is wrong.

---

## Gate 5 — Universe-B Transfer

**Location:** `discovery.py:778-828`, plus `_load_universe_b` at
`discovery.py:521-570`.

### What the gate is supposed to test
A candidate edge should generalize beyond the production universe of 109
tickers. `_load_universe_b` loads up to ~50 S&P 500 tickers NOT in the
production set, with ADV/listing-age filters to ensure they're tradeable.
Run the same candidate on this held-out universe over the same window;
Sharpe must be > 0. This catches universe-overfit edges that mined alpha
from specific names rather than from a generalizable mechanism.

### What the code actually tests
At `discovery.py:794-806`:
```python
b_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
b_risk = RiskEngine({"risk_per_trade_pct": 0.01})
...
b_controller = BacktestController(
    data_map=dm_b,
    alpha_engine=b_alpha,
    risk_engine=b_risk,
    cockpit_logger=b_logger,
    exec_params=_exec_params,
    initial_capital=100_000,
    batch_flush_interval=99999,
)
```

This is a **standalone single-edge backtest on the held-out universe**. No
production ensemble. No soft-paused edges. No regime detector. Capital
rivalry doesn't exist because no other edge is firing.

### Geometry/baseline alignment

**FAIL** — same standalone-vs-ensemble mismatch. Production deploys this
edge in an ensemble; testing transfer in standalone geometry produces
verdicts that don't necessarily reflect ensemble-deployment behavior on
Universe-B.

A specific concrete failure mode this can introduce: a regime-conditional
edge (memory: `project_low_vol_regime_conditional_2026_04_25.md`) that
contributes positively in adverse regimes but negatively in benign ones
will appear universe-overfit because Universe-B happens to span more
benign-regime calendar time. In ensemble geometry with the regime
detector active, the same edge might be down-weighted during benign
periods and the test would pass.

### Recommended fix
- Run a production-equivalent ensemble backtest on Universe-B with the
  candidate co-resident in the active set + soft-paused set at 0.25×.
- Attribute PnL to the candidate. Sharpe of the attributed return stream
  is the universe-transfer signal.
- Note: this change makes Gate 5 substantially more expensive. Consider
  whether to run it at full universe-B or at a smaller stratified sample
  if cost matters.

---

## Gate 6 — Factor Decomposition (FF5 + Mom)

**Location:** `discovery.py:830-888`, `core/factor_decomposition.py`.

### What the gate is supposed to test
Reject candidates whose excess returns are explained by FF5+Mom factor
exposure rather than genuine alpha. Regress the candidate's daily excess
returns on `[MktRF, SMB, HML, RMW, CMA, Mom]` plus an intercept;
require:
- intercept t-stat > 2.0 (statistical significance), AND
- intercept × 252 > 2% (economic significance — at least 2% annualized
  alpha that isn't reproducible via cheap factor ETFs).

The arithmetic in `core/factor_decomposition.py::regress_returns_on_factors`
and `gate_factor_alpha` is correct (verified in
`docs/Audit/factor_decomposition_baseline.md`).

### What the code actually tests
At `discovery.py:854`:
```python
daily_ret_series = equity_curve.pct_change().dropna()
```
The `equity_curve` is from Gate 1's **standalone single-edge backtest**
(line 658). The factor regression is performed on this standalone return
stream.

### Geometry/baseline alignment

**FAIL** — and this is the gate that *first surfaced* the geometry issue
back in Q3 2026-04-29 (see `docs/Audit/gauntlet_revalidation_2026_04.md`).

The Q3 finding (memory: `project_phase_210b_oos_falsified_2026_04_29.md`,
later reframed in `project_ensemble_alpha_paradox_2026_04_30.md`):

- Factor decomp on the **integration backtest's per-edge attributed
  returns** showed `volume_anomaly_v1` t = +4.36 / α = +6.1% and
  `herding_v1` t = +4.49 / α = +10.1%.
- Factor decomp on the **standalone single-edge backtest's equity-curve
  returns under realistic costs** had Gate 1 standalone Sharpe of 0.32
  and -0.26 — both fail the cheap pre-filter, never even reach Gate 6.

Same FF5+Mom regression mathematics, different return stream → opposite
verdicts. The geometry mismatch is precisely what produces the false
negatives flagged in `gauntlet_revalidation_2026_04.md` ("the
factor-decomposition claim was a cost-model confound").

This is the most diagnostically clear failure of the bug class. The
mathematics of FF5+Mom regression is unchanged; only the input return
stream is wrong.

### Recommended fix
- Source `daily_ret_series` from the candidate's **integration-attributed
  per-day PnL** (production-equivalent ensemble backtest), normalized to
  per-day returns on the same capital base used by the regression target.
- Verify the per-edge attribution methodology used in
  `oos_2025_decomposition_2026_04.md` produces the right return stream
  shape for FF5+Mom regression (excess returns aligned with factor cube
  dates).
- The thresholds (t > 2 and α > 2%) were calibrated against integration
  attribution in `docs/Audit/factor_decomposition_baseline.md`, so they
  should remain valid once the input stream is corrected.

---

## Cross-cutting findings

### 1. The bug is shared substrate, not five independent bugs

Gates 2-6 all consume artifacts produced by Gate 1's setup at
`discovery.py:619-694`:

- Gate 2: passes `data_map[first_key]` to `RobustnessTester`, but the
  `strategy_wrapper` recreates the same single-edge ensemble.
- Gate 3: WFO instantiates its own `_quick_backtest` with the same
  single-edge ensemble.
- Gate 4: directly consumes `daily_returns = equity_curve.pct_change()`
  from Gate 1's curve.
- Gate 5: rebuilds the same single-edge ensemble for Universe-B.
- Gate 6: directly consumes `equity_curve.pct_change()` from Gate 1's
  curve.

**Implication.** A piecemeal fix that patches each gate independently
duplicates the production-pipeline-invocation logic 5 times. The
architecturally clean fix is to produce a **single
production-equivalent backtest result** at the top of `validate_candidate`
(candidate-included vs candidate-excluded, with the soft-paused-at-0.25×
ensemble) and pass the candidate's attribution stream into all 6 gates.

### 2. The Reform Gate 1 architectural fix is identical to the Gates 2-6 fix

Memory `project_gate1_reimplementation_problem_2026_05_01.md` proposes
that Reform Gate 1 should not reimplement the ensemble — it should invoke
`orchestration/mode_controller.py::run_backtest` with candidate-included
vs candidate-excluded edge sets and compute attribution. The same
proposal applied at `validate_candidate`'s top-level setup automatically
fixes Gates 2-6 because their inputs change from "standalone equity curve"
to "integration-attributed return stream."

### 3. Cost model and risk-per-trade do match production

Confirmed by inspection:
- Production `config/risk_settings.json` sets `risk_per_trade_pct = 0.01`.
- Gates 1/2/3/5 all use `RiskEngine({"risk_per_trade_pct": 0.01})`, which
  matches.
- `exec_params` is plumbed through `validate_candidate(... exec_params=...)`
  so callers can pass realistic Almgren-Chriss parameters. (The gauntlet
  revalidation script does this.)

The mismatch is **not** in the cost model parameters or the risk-per-trade
budget. It is in the **ensemble shape**: production splits capital across
~6.5 effective edges, the gates run a single-edge ensemble, the resulting
per-fill `qty/ADV` is 6× larger in the gates than in production, and the
square-root impact term turns that into impact-knee-crossing trade tax.

### 4. Composite fitness score inherits the same bug

`discovery.py:934-941` builds a composite fitness from
`wfo_oos_sharpe`, `survival_rate`, and `degradation_ratio`. All three
inputs come from the broken gates. Even if the orchestrator decides not
to use `passed_all_gates` as the hard filter, GA selection driven by
`fitness_score` is selecting against candidates whose standalone
geometry fails, which is biased against ensemble-positive candidates the
same way the gates are.

### 5. There is one secondary bug independent of geometry

`wfo.py:112` stitches OOS windows by appending equity values, producing
phantom returns at window boundaries. This is a separate bug from the
geometry mismatch — even with a perfect production-equivalent
`_quick_backtest`, the OOS Sharpe would still be polluted. Fix by
stitching returns, not equity values. (This is a well-known WFO trap.)

### 6. There is one secondary bug in PBO bootstrap

`robustness.py:23-85` bootstraps a single ticker's price series.
`discovery.py:728-730` invokes it with `data_map[first_key]`. The
bootstrap is therefore univariate even though the candidate trades a
multi-name universe. Fix by bootstrapping the synchronized
cross-section (sample the same calendar block across all tickers
simultaneously to preserve cross-sectional correlation).

---

## Recommended fix priority order

1. **First (single high-leverage change).** At the top of
   `validate_candidate`, replace the standalone single-edge backtest at
   lines 619-649 with two production-equivalent calls to
   `orchestration/mode_controller.py::run_backtest`:
   - Baseline = current edges.yml state, candidate excluded if registered.
   - With-candidate = baseline + candidate at default weight.

   Compute attribution = `with_candidate_per_day_return -
   baseline_per_day_return`. This single attribution stream (and a
   matching equity curve) becomes the input to Gates 2-6. Same pattern
   the Reform Gate 1 memory proposes.

   This requires either (a) factoring `mode_controller.run_backtest` into
   a `run_backtest_pure(...)` callable that takes an explicit edge set and
   returns metrics + per-day return stream, or (b) accepting the cost of
   running the orchestration entry point inside another orchestration
   layer. Per the Reform Gate 1 memory, option (a) is the cleaner path.

   With this in place, all 5 gates' geometry mismatches are fixed
   simultaneously. Gates 2-6 do not need per-gate code changes for the
   geometry fix — only their inputs change.

2. **Second (independent, parallelizable).** Fix `wfo.py:112` OOS
   equity stitching to operate on returns, not equity values. This is a
   ~10-line change. Affects only Gate 3's reported `oos_sharpe`,
   `degradation`, and the composite `fitness_score`.

3. **Third (independent, parallelizable).** Fix
   `robustness.py:calculate_pbo` + `discovery.py:728` to bootstrap the
   full cross-section (synchronized block-sample across all tickers in
   `data_map`), not a single ticker. Affects only Gate 2's PBO survival.

4. **Fourth (after #1 lands).** Re-calibrate Gate thresholds against the
   new attribution-stream inputs:
   - Gate 2 survival rate threshold (currently 0.70) — what's the
     calibrated threshold against ensemble-attribution survival?
   - Gate 3 degradation hard-gate (currently informational) — should it
     become a real gate now that the OOS measurement is trustworthy?
   - Gate 6 thresholds (t > 2, α > 2%) likely OK because they were
     calibrated against integration-attribution in
     `factor_decomposition_baseline.md`. Verify.

5. **Fifth (cache the expensive part).** A production-equivalent
   per-candidate backtest is ~5-10 min on prod-109 × 4-year window. For a
   Discovery cycle of N candidates, naive implementation is N+1
   backtests. Cache the baseline by `(active_set_fingerprint, window,
   exec_params_fingerprint)` so a cycle pays for the baseline once and
   then 1 incremental run per candidate.

---

## Boundaries respected by this audit

- No gate code modified.
- No new backtests run; pure code-reading + reasoning.
- No commits to main; staying on branch `gates-2-through-6-audit`.
- Gates 2-6 inspected as documented in `discovery.py:572-947`. Supporting
  modules (`wfo.py`, `robustness.py`, `significance.py`,
  `factor_decomposition.py`, `mode_controller.py:700+`) inspected.

## Unresolved

- Whether the per-edge attribution methodology used in
  `oos_2025_decomposition_2026_04.md` is the right return-stream form to
  feed into the gate fixes. The doc discusses fill-level attribution; the
  gates need a per-day return stream that's regression-compatible with
  FF5+Mom. A short prototyping pass before the architectural fix lands
  would be useful.
- Whether running two production-equivalent backtests per candidate in
  the Discovery cycle is feasible at GA-population scale (typically
  ~50 candidates per cycle). The cache strategy in step 5 should make it
  feasible, but actual cycle wall-time needs measurement before
  promoting this to default behavior. Until then, the standalone-Gate-1
  cheap pre-filter could be retained as a *non-blocking pre-filter* with
  the production-equivalent gates as the actual decision-makers.
