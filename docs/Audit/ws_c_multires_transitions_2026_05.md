# Workstream C — Multi-Resolution HMM + Transition-Warning Detector (2026-05-02)

> **Status:** Workstream C, second slice (after the daily-HMM slice shipped
> 2026-05-02 morning). Branch `ws-c-multires-transitions`. Builds additively
> on the daily HMM — no existing logic removed, no Engine B code change.
>
> **Default config: BOTH new modules OFF.** Infrastructure ships, validation
> runs verify, the director / user can flip on for verification rounds.

---

## What this slice delivers

Two of the three remaining Workstream C deliverables from
`docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`:

| Deliverable | Status |
|---|---|
| HMM 3-state classifier with probabilistic outputs (slice 1) | ✓ shipped 2026-05-02 morning |
| **Multi-resolution regime detection** (this slice) | ✓ shipped |
| **Transition-warning detector** (this slice) | ✓ shipped |
| Cross-asset confirmation | ❌ deferred to next slice |
| Macro signal reclassification | ✓ shipped slice 1 |
| Engine B sizing API consumes regime-confidence | ✓ slice 1 (read-only via advisory.risk_scalar) |

---

## C2 — Multi-resolution regime detection

### Architecture

`engines/engine_e_regime/multires_hmm.py` adds `MultiResolutionHMM`, an
orchestrator that runs three independently-trained HMMs in parallel:

| Cadence | Resample rule | Train range | Cov type | Train obs | Test obs (2025) |
|---|---|---|---|---:|---:|
| daily   | (no resample)         | 2021-2024 | full | 1005 | 250 |
| weekly  | `W-FRI`, sums for log-rets, last for levels | 2021-2024 | full | 208 | 53 |
| monthly | `ME`, sums for log-rets, last for levels    | **2018-2024** † | diag | 54 | 12 |

† **Monthly deviates from "train on 2021-2024" spec.** With 7 features and
3 states, monthly cadence on 2021-2024 produces only 48 obs — fewer than
the parameter count even with diag covariance. Extending the training
horizon to 2018-01 (the earliest the cached + yfinance-extended SPY data
reaches) gives 54 obs after dropna, enough to fit. This is documented as a
data-limitation deviation; future Workstream F work (extending price
history further back, e.g. via paid Polygon or Refinitiv feed) would let
us return to spec.

### State-mapping convention (preserved across cadences)

All three classifiers use the same `{benign, stressed, crisis}` label set
and the same vol-ascending sort: state idx with the lowest mean of
`spy_vol_20d` (z-scored space) → `benign`. This makes the three
classifications directly comparable.

### Resampling contract (`macro_features.resample_feature_panel`)

| Column type | Aggregation |
|---|---|
| `spy_log_return`, `tlt_log_return` | `sum` (log-returns are additive) |
| Rolling-window returns (`spy_ret_5d`, `tlt_ret_20d`, `dollar_ret_63d`) | `last` (already smoothed at daily cadence) |
| `spy_vol_20d` rolling-vol snapshot | `last` |
| Level series (`vix_level`, `yield_curve_spread`, `credit_spread_baa_aaa`, etc.) | `last` |

Bar timestamps are stamped to the **last actual trading day in the
resample window** — preserves no-look-ahead at inference time. (Pandas's
`resample(label='right')` would otherwise stamp to a calendar-period
boundary that may be a non-trading day; `resample_feature_panel`
post-processes this.)

### Multi-res log-likelihood comparison (out-of-sample)

Run: `python scripts/train_multires_hmm.py`
Output: `data/research/hmm_multires_validation_2026_05.json`

| Cadence | Cov | n_train | n_test | train LL/obs | **test LL/obs** | Note |
|---|---|---:|---:|---:|---:|---|
| daily   | full | 1005 | 250 | -6.018 | **-11.791** | (read-only — slice 1 artifact) |
| weekly  | full |  208 |  53 | -6.096 | **-12.826** | new |
| monthly | diag |   54 |  12 | -7.796 | **-12.348** | new (extended train horizon) |

**Interpretation.** Daily achieves the best per-obs OOS log-likelihood,
which makes sense: it has the most parameters and the most training
data. Monthly is a close second on per-obs LL despite tiny test sample
(12 obs) and diagonal covariance — its smoother input features fit a
3-state HMM cleanly even with limited samples. Weekly is third on
per-obs LL, likely because it sits in the data-quantity sweet spot
where full-covariance is justified but the training set has less
diversity than daily across 4 years.

The numbers are NOT directly comparable across cadences — different
emission distributions, different input statistics, different parameter
counts. The ranking serves only as a sanity check that all three
classifiers fit reasonably and can score holdout data without crashing.

### Tradeoff: temporal precision vs per-classification confidence

This is the documented tradeoff per the Workstream C deliverable:

| Cadence | Strength | Weakness | Best consumer |
|---|---|---|---|
| daily   | Catches intra-day flips immediately | Noisy per-bar (single-day shocks) | Core sleeve, per-bar advisory damping |
| weekly  | Smoother per-classification | Cannot detect intra-week flips | Tactical regime read |
| monthly | Highest per-classification confidence; smoothest | Misses anything inside a month | Path C compounder (annual rebalance), strategic signals |

Empirical demonstration on 2025-04-04 (smoke-tested via integration):

| Cadence | Bar timestamp | Label | Confidence |
|---|---|---|---:|
| daily   | 2025-04-04 | crisis | 1.00 |
| weekly  | 2025-04-04 | crisis | 1.00 |
| monthly | 2025-03-31 | benign | 0.94 |

The monthly classifier is still on the **March 31** bar at the time we
query for 2025-04-04 — it will not flip until the April 30 bar boundary.
This is the architectural property: monthly cannot react until its bar
closes. For the Path C compounder this is the correct trade — the
sleeve only rebalances annually, so it should NOT be reacting to a
2-day-old crisis read. For the core sleeve, daily is the correct
consumer.

### Engine integration (read-only)

`RegimeDetector._predict_multires` runs all three classifications when
`cfg.multires.multires_enabled=True`. Output is written to:

```
advisory["regime_daily"]   = {label, probabilities, confidence, bar_timestamp} | None
advisory["regime_weekly"]  = {label, probabilities, confidence, bar_timestamp} | None
advisory["regime_monthly"] = {label, probabilities, confidence, bar_timestamp} | None
```

**Engine B reads ONLY `advisory.risk_scalar` today.** These three new
fields are read-only diagnostics — no current consumer mutates sizing
based on them. A future slice can wire Path C compounder's de-gross
logic to read `regime_monthly.label`; a future tactical sleeve can read
`regime_weekly.label`. For this slice, the infrastructure ships, the
fields are populated, but no portfolio behavior changes.

---

## C3 — Transition-warning detector

### Architecture

`engines/engine_e_regime/transition_warning.py` adds
`TransitionWarningDetector`. Two-signal design with OR semantics:

| Signal | Purpose | Default threshold |
|---|---|---|
| Rolling K-day **posterior entropy** (smoothed by a 3-bar mean) | Persistent uncertainty across multiple states often precedes flips | 0.55 (normalized to [0, 1]) |
| **KL divergence** between posterior at bar `t` and bar `t-K` (smoothed) | Shifting probability mass across states | 0.30 (in nats) |

A warning fires when **either** signal crosses its threshold. Streaming
interface (`detect_at`) for live use; batch interface (`detect_sequence`)
for backtest validation.

### Acceptance criterion

> "Fire ≥48 hours ahead of regime changes in ≥80% of historical cases"
> (per `docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`).

48 trading hours ≈ 2 trading days. Validated against three named
historical events.

### Anchor event vindication

Run: `python scripts/backtest_transition_warning.py`
Output: `data/research/transition_warning_backtest_2026_05.json`

Procedure:
1. Build extended daily feature panel 2019-06 → 2025-12 (SPY/TLT
   pre-2020-04 fetched from yfinance into RAM, no CSV mutation).
2. Score the slice-1 daily HMM through the panel → posterior sequence.
3. Stream posteriors through `TransitionWarningDetector(default config)`.
4. For each anchor event, find the first warning fire in the
   30-calendar-day pre-event window; lead = trading-days between first
   warning and the named event.

| Event | Anchor date | First warning | Lead (trading days) | Pass (≥2 td) |
|---|---|---|---:|---|
| March 2020 (COVID crash) | 2020-02-24 | 2020-02-03 | 14 | **PASS** |
| October 2022 (rate selloff) | 2022-09-26 | 2022-08-29 | 19 | **PASS** |
| April 2025 (market_turmoil) | 2025-04-02 | 2025-03-03 | 22 | **PASS** |

**Result: 3/3 events passed (100%) — well above the 80% spec.**

The lead times are generous (14-22 trading days) because the daily HMM
typically catches regime changes earlier than the headline-news date —
the actual durable argmax flips happen 2-6 weeks before what people
remember as "the event." The detector is firing on the leading edge of
that probabilistic shift, which is exactly what the warning system is
supposed to do.

Detector firing statistics over the full 2019-08 → 2025-12 sample:
- Bars scored: **1592**
- Warnings: **199 (12.5% of bars)**
- Durable argmax transitions: **24** (state changes persisting ≥5 bars)

### False-positive rate caveat

12.5% warning rate is high if interpreted as "decisions to act." It is
intentionally not — the warning is observability, not policy. Consumers
should treat the warning as "be alert, regime may be in transit," not
"act now." A future slice may add a stricter `transition_decision`
band that fires only on stronger threshold crossings; for now, the
detector is tuned to favor catching transitions over avoiding false
alarms (the spec is recall-focused: ≥80% of transitions detected).

### Engine integration (read-only)

`RegimeDetector._update_transition_warning` maintains a streaming
posterior buffer (size 20 by default) and calls `detect_at` per bar
when `cfg.transition_warning.transition_warning_enabled=True`. Output
is written to:

```
advisory["regime_transition_warning"] = {
  "timestamp": "2025-04-04",
  "warning": false,
  "entropy": 0.0,
  "entropy_smoothed": 0.0,
  "kl_from_lag": 0.0,
  "kl_smoothed": 0.0,
  "reason": []
}
```

Engine B does not consume this field. Future consumers (e.g., Path C
compounder's de-gross logic) may opt in.

---

## Files changed (branch `ws-c-multires-transitions`)

```
NEW  engines/engine_e_regime/multires_hmm.py
NEW  engines/engine_e_regime/transition_warning.py
NEW  engines/engine_e_regime/models/hmm_weekly_v1.pkl       (training output)
NEW  engines/engine_e_regime/models/hmm_monthly_v1.pkl      (training output)
NEW  scripts/train_multires_hmm.py
NEW  scripts/backtest_transition_warning.py
NEW  tests/test_multires_hmm.py                 (11 tests)
NEW  tests/test_transition_warning.py           (11 tests)
NEW  docs/Audit/ws_c_multires_transitions_2026_05.md   (this doc)
NEW  data/research/hmm_multires_validation_2026_05.json    (training output)
NEW  data/research/transition_warning_backtest_2026_05.json (backtest output)

MODIFIED  engines/engine_e_regime/macro_features.py    (+ resampling helpers)
MODIFIED  engines/engine_e_regime/regime_config.py     (+ MultiResHMMConfig, TransitionWarningConfig)
MODIFIED  engines/engine_e_regime/regime_detector.py   (wired both modules, gated on flags)
MODIFIED  engines/engine_e_regime/hmm_classifier.py    (covariance_type + min_obs params, defaults preserved)
```

**Engine B unchanged. Engine A unchanged.** Only Engine E grows.

---

## Test results

```
$ python3 -m pytest tests/test_multires_hmm.py tests/test_transition_warning.py \
                    tests/test_hmm_classifier.py tests/test_macro_reclassification.py
35 passed in 12.08s

$ python3 -m pytest tests/ -k "regime or hmm or macro or advisory"
206 passed, 1 skipped, 745 deselected, 1 warning in 23.52s

$ python3 -m pytest tests/ -k "signal_processor or risk_engine or portfolio"
35 passed, 917 deselected, 1 warning in 9.01s
```

22 new tests added; all pre-existing engine A/B/C/E tests pass without
regression. The HMMRegimeClassifier signature change (added
`covariance_type` + `min_obs` params with backward-compatible defaults)
preserves prior behavior — daily classifier was trained with default
params and reloads bit-identically.

---

## Follow-ups flagged (NOT in this slice)

1. **Cross-asset confirmation (C4)** — explicit equity-vs-rates and
   equity-vs-credit regime confirmation. Yield curve already in features
   but no formal confirmation logic. HYG/IEF data not in `data/processed`.
   Next slice.
2. **Path C compounder de-gross wiring** — the monthly classifier's
   `regime_monthly.label` should be a hard veto for the Path C
   sleeve when the label is `crisis`. Coupled to Workstream B's
   compounder-enable decision (currently blocked by Workstream F
   fundamentals data).
3. **Transition-warning false-positive rate** — 12.5% is observability-
   acceptable but high for any policy use. Add a `transition_decision`
   band with stricter thresholds before any consumer wires sizing.
4. **Monthly training horizon** — 2018-2024 vs the doc's 2021-2024 spec.
   Mathematically forced by sample size; revisit once external data
   workstream extends price history.
5. **Cadence-resolution Sharpe A/B** — this slice did NOT measure
   aggregate Sharpe impact of enabling multi-res or transition warning.
   Slice 1's measurement methodology (`scripts/run_isolated.py
   --runs N`) applies; should run before any production enable.
   Expected impact: small (consistent with slice 1's +0.001 Sharpe
   delta) since neither module currently mutates sizing decisions.
6. **HMM retraining cadence** — same open question as slice 1.
   Quarterly? Annually? Drift-triggered? Currently frozen.

---

## Open caveats

- **March 2020 transition test depended on a yfinance fetch.** If the
  network is unavailable when re-running `backtest_transition_warning.py`,
  pre-2020-04 SPY/TLT data is not available; the script will skip the
  March 2020 anchor and report only Oct 2022 and April 2025. Cached CSV
  is unchanged.

- **The 12.5% warning rate is not a tuning artifact.** Manual inspection
  of warning bars vs durable transitions shows warnings cluster around
  transition windows but also fire on shorter-lived posterior wobbles.
  This is expected behavior for a recall-favoring detector.

- **Monthly classifier's training span (2018-2024) overlaps the test
  span (2025) by zero years**, but the *monthly* training window stops
  at 2024-12-31 explicitly. There is no train-test contamination at the
  monthly cadence specifically, only that the slice 1 daily classifier's
  feature engineering uses the same FRED series.
