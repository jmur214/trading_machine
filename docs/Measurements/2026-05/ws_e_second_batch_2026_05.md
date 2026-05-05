## Workstream E — Second Batch Audit (2026-05)

Five additional cross-sectional ranking primitives shipped to the
Feature Foundry, building on Agent 3's first batch. Branch:
`ws-e-second-batch`.

This is the second falsifiable test of the substrate's
**<50-lines-per-feature** acceptance criterion (Workstream D, see
`docs/Audit/feature_foundry_skeleton_2026_05.md`). Combined with
Agent 3's first batch, the substrate has now been exercised against
10 features by two independent authors.

## Features shipped

| # | feature_id | What it computes | Source | Tier |
|---|---|---|---|---|
| 1 | `dist_52w_high` | `(close_t / 252-day rolling max) - 1`, in (-1, 0] | local_ohlcv | B |
| 2 | `drawdown_60d` | `(close_t / 60-day rolling max) - 1`, in (-1, 0] | local_ohlcv | B |
| 3 | `vol_regime_5_60` | 5-day realized vol divided by 60-day realized vol | local_ohlcv | B |
| 4 | `ma_cross_50_200` | `(SMA_50 - SMA_200) / SMA_200` | local_ohlcv | B |
| 5 | `skew_60d` | Bias-corrected sample skew of 60d log returns (Fisher-Pearson) | local_ohlcv | B |

All five are pure cross-sectional ranking primitives over the existing
`data/processed/` per-ticker daily CSVs. None require sector tagging,
fundamentals, or external data — staying inside the dispatch boundary
that explicitly excluded fundamentals-blocked work.

### Picks vs. dispatch list

The dispatch named eight candidates. Picked five; rationale for the
three left behind:

  - **Sector-relative momentum** — Agent 3 already declined this on the
    same grounds (no clean sector source on the 109-ticker universe;
    `yfinance.info['sector']` would couple Workstream E to a
    network-dependent ingestion path and inflate per-feature LOC).
    Skipped.
  - **Volume-confirmed momentum** — composite of `mom_12_1` + a volume
    gate, not a primitive. Agent 3 also flagged this as inflating LOC
    artificially. Skipped to keep one feature == one signal.
  - **Calendar-anomaly battery** — would land as a single ~200-line file
    (4-6 calendar features sharing per-day computation). Per the dispatch's
    "doc allows either framing," picked five distinct primitives rather
    than one batch file. Calendar features are still on the table for a
    future batch; they have a different shape (fixed-date arithmetic vs
    rolling-window OHLCV) that warrants its own dispatch.

## Substrate validation — the <50-lines test

**Verdict: substrate holds for 5/5 features. The promise holds at scale.**

| feature_id | Module LOC | Card LOC |
|---|---:|---:|
| `dist_52w_high` | 41 | 18 |
| `drawdown_60d` | 41 | 18 |
| `vol_regime_5_60` | 46 | 19 |
| `ma_cross_50_200` | 41 | 19 |
| `skew_60d` | **48** | 19 |

Combined with Agent 3's first batch:

  - **First batch**: 4/5 under 50 LOC; `beta_252d` at 58 (alignment
    boilerplate for ticker-vs-SPY pair).
  - **Second batch**: 5/5 under 50 LOC.
  - **Cumulative**: 9/10 features under 50 LOC.

The one near-miss in this batch (`skew_60d` at 48) is the moment-math
itself: bias correction + central moments without a scipy dependency.
An initial draft hit 51 LOC; tightening removed a dead `n < 3` guard
(`n` is provably 60 here) and inlined the closed-form return. No
substrate primitive needed — the LOC pressure was algorithmic, not
architectural.

The shared `LocalOHLCV` source (118 LOC, written by Agent 3) covered
all five new features without modification. The `close_series(ticker)`
accessor is now amortized across 10 features. **The "substrate cost
amortizes across features" claim from the first-batch audit is
quantitatively confirmed**: per-feature additional LOC stays
comfortably under 50 because no source code is duplicated.

## Adversarial twins

`generate_twin()` accepts all 5 new features without substrate change
(verified in
`tests/test_ws_e_second_batch.py::test_adversarial_twins_can_be_generated_for_all_five`).
Twin determinism is verified for `dist_52w_high__adversarial_twin` —
same value across two consecutive calls.

Same caveat as Agent 3: meaningful real-vs-twin importance comparison
requires the meta-learner integration (Workstream D #4). The twins
shipped here are ready inputs when that gate lights up.

## Ablation result

`run_ablation()` was exercised against the 5 second-batch feature ids
with a synthetic linear-contribution `backtest_fn` (production-backtest
integration is the deferred Workstream D #2):

| feature_id | dropped Sharpe | contribution Sharpe |
|---|---:|---:|
| `dist_52w_high` | 0.4000 | 0.2000 |
| `drawdown_60d` | 0.5000 | 0.1000 |
| `vol_regime_5_60` | 0.5300 | 0.0700 |
| `ma_cross_50_200` | 0.4200 | 0.1800 |
| `skew_60d` | 0.5500 | 0.0500 |

Baseline Sharpe (full set): 0.6000.
Persisted to:
`data/feature_foundry/ablation/ws-e-second-batch-2026-05-02T06-15-30Z.json`.

**These numbers do not represent real alpha** — they are the synthetic
weights the test harness was given, used solely to confirm:

  1. `run_ablation()` accepts the 5 newly-registered ids.
  2. Persistence + reload work cleanly.
  3. No collision with the first-batch ablation file.

Real ablation contributions on production data are still gated on
Workstream D #2 (meta-learner ↔ production-backtest closure).

## Real-data smoke test

The 5 features evaluated on the 109-ticker universe at `dt=2025-12-01`:

```
feature             AAPL      MSFT      NVDA       SPY
dist_52w_high     0.0000   -0.1004    0.0000   -0.0104
drawdown_60d      0.0000   -0.1004    0.0000   -0.0104
vol_regime_5_60   0.4821    0.9451    0.8881    0.8947
ma_cross_50_200   0.1597    0.0906    0.4600    0.0920
skew_60d          0.1978   -0.3589    0.7102   -0.9731
```

Reads as expected:

  - AAPL & NVDA at fresh 52w *and* 60d highs (Dec 2025 mega-cap
    momentum) — both rolling-max features pin to 0.
  - MSFT 10% off its highs on both windows.
  - `vol_regime_5_60` < 1 across the board → late-2025 was a
    vol-compression tail; recent 5d vol below 60d average.
  - `ma_cross_50_200` positive everywhere → golden-cross regime,
    NVDA's +46% gap reflects the 2025 trend magnitude.
  - `skew_60d` strongly negative on SPY (-0.97) and MSFT (-0.36) —
    fat-left-tail in trailing 60d; positive on NVDA (+0.71) =
    lottery-like distribution.

No off-by-one window errors, no inverted signs, no leakage past `dt`.

## Test coverage

`tests/test_ws_e_second_batch.py` — **19 tests, all passing:**

  - All-features-registered enumeration
  - Per-feature numeric-equality vs closed-form on synthetic series
    (`dist_52w_high`, `drawdown_60d`, `ma_cross_50_200`)
  - `dist_52w_high` zero on a monotonically-rising series (boundary)
  - Volatility-regime burst detection (SHOCK ticker — calm 350d then
    50d vol-burst)
  - `ma_cross_50_200` positive on uptrending series (sign correctness)
  - `skew_60d` numeric-equality vs `scipy.stats.skew(bias=False)` —
    direct reference comparison; skipped only if scipy missing
  - Plausible-range bounds for `skew_60d` across three regime tickers
  - Insufficient-history → None for each feature
  - Unknown-ticker → None for each feature
  - Twin generation across all 5 features (substrate integration)
  - Ablation runner across all 5 ids (substrate integration)
  - `validate_all_model_cards()` returns no errors for the new features

Regression: **41/41 prior tests still pass** (Agent 3's
`test_ws_e_first_batch.py` 12 tests + foundry substrate
`test_feature_foundry.py` 29 tests).

## Engine boundaries respected

  - No engine code modified.
  - No edits to `engines/engine_a_alpha/edge_registry.py` — Foundry
    features stay decoupled from the edge registry per substrate intent.
  - `cockpit/dashboard_v2/` untouched — existing Foundry tab will
    auto-pick-up the new features and their persisted ablation row via
    the loader's `latest_ablation_for_feature()` lookup.
  - `data/feature_foundry/ablation/` writes only.
  - `live_trader/`, `data/governor/`, `cockpit/dashboard/`,
    `engines/engine_c_portfolio/optimizers/`, signal_processor,
    harness scripts — all untouched.
  - **Substrate untouched**: `data_source.py`, `feature.py`,
    `ablation.py`, `adversarial.py`, `model_card.py`,
    `sources/local_ohlcv.py` are all unchanged in this branch (verified
    via `git diff origin/main -- core/feature_foundry/`).

## Findings flagged for follow-up

Two new substrate observations (NOT fixed in this branch — substrate
modification is out of scope):

1. **Per-feature LOC pressure migrating to algorithmic specifics.**
   For pure rolling-window primitives the substrate cost is well
   below the 50-LOC ceiling; remaining pressure is from the
   computation itself (skew bias correction, beta alignment). This
   is the right pattern: the substrate isn't the bottleneck.
   Implication for future batches: features with non-trivial math
   (e.g. tail-risk measures, copula-based cross-asset features) will
   sit close to the LOC ceiling for legitimate reasons. The ceiling
   is a useful signal — if a feature blows past 60 LOC, the math
   probably wants to live in `core/feature_foundry/math/` as a
   reusable utility, not in the feature plugin itself. (Not built
   here; flagged.)

2. **Synthetic-fixture coverage of regime shifts.** Tests use a
   `SHOCK` ticker (calm-then-vol-burst) to exercise
   `vol_regime_5_60`, but no synthetic ticker tests
   `dist_52w_high` against a deep mid-window drawdown that recovers.
   The function is provably correct (closed-form check) so this is
   coverage hygiene rather than a bug. Could add a synthetic
   `RECOVER` series in a future test pass.

Carryforward from Agent 3's first-batch audit (still open, not
attempted here):

  - `DataSource.panel(ticker, start, end)` substrate API to bless the
    `close_series` pattern.
  - `LICENSES = {...}` const for the decorator/card cross-check.
  - `generate_twin()` 5y materialization tightening.

## Five-line report

  - Branch: `ws-e-second-batch`.
  - Shipped: 5 features (`dist_52w_high`, `drawdown_60d`,
    `vol_regime_5_60`, `ma_cross_50_200`, `skew_60d`) + 5 model cards
    + 19 unit tests; 41/41 prior tests still pass.
  - LOC per feature module: 41 / 41 / 46 / 41 / 48 — **5/5 under 50**.
  - **Substrate's <50-LOC promise: 9/10 cumulative across both
    batches**; the one miss (Agent 3's `beta_252d` at 58) is feature-
    intrinsic, not substrate leak. Substrate cost truly amortizes.
  - Ablation runner + twin generator integrate with the new features
    without substrate change; persisted ablation JSON visible to the
    dashboard via the existing loader.
