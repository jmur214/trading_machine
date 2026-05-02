# Workstream E — First Batch Audit (2026-05)

Five cross-sectional ranking primitives shipped to the Feature Foundry
per `docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`
Workstream E. Branch: `ws-e-first-batch`.

This is also the falsifiable test of the substrate's
**<50-lines-per-feature** acceptance criterion from Workstream D
(see `docs/Audit/feature_foundry_skeleton_2026_05.md`).

## Features shipped

| # | feature_id | What it computes | Source | Tier |
|---|---|---|---|---|
| 1 | `mom_12_1` | Return over t-252..t-21 trading days (Jegadeesh-Titman) | local_ohlcv | B |
| 2 | `mom_6_1` | Return over t-126..t-21 trading days | local_ohlcv | B |
| 3 | `reversal_1m` | Trailing 21-trading-day return (short-term reversal) | local_ohlcv | B |
| 4 | `realized_vol_60d` | Annualized stdev of last 60 daily log returns | local_ohlcv | B |
| 5 | `beta_252d` | OLS beta of daily log returns vs SPY, 252d window | local_ohlcv | B |

All five are cross-sectional ranking primitives. None require fundamentals,
sector tags, or external data — all are computable from the existing
per-ticker OHLCV CSVs in `data/processed/`.

**Skipped (per dispatch boundaries):**
- Volume-confirmed momentum — composite of mom_12_1 + a volume gate; not
  a primitive, would inflate LOC count artificially.
- Industry-relative momentum — needs sector tagging (no clean source on
  current universe; would couple Workstream E to data ingestion).
- Size factor — needs market cap (shares outstanding); blocked on Track F
  fundamentals decision.
- Value/quality composites — fundamentals; explicitly blocked.

## Substrate validation — the <50-lines test

**Verdict: substrate holds for 4 of 5 features. The promise is honest.**

| feature_id | Feature module LOC | Model card LOC | Combined |
|---|---:|---:|---:|
| `mom_12_1` | 39 | 17 | 56 |
| `mom_6_1` | 39 | 16 | 55 |
| `reversal_1m` | 39 | 18 | 57 |
| `realized_vol_60d` | 42 | 18 | 60 |
| `beta_252d` | **58** | 18 | 76 |

The acceptance criterion in the 1-percent doc reads:
> New feature can be added to Foundry with **<50 lines of code (plugin
> + decorator)**.

Reading "plugin" as the data-source plugin (amortized once per source,
not per feature), the per-feature module LOC is the load-bearing number:

- **4 features at 39-42 lines** ✅ comfortably under 50
- **1 feature at 58 lines** ⚠️ over by 8 lines (`beta_252d` needs an
  index-alignment helper for ticker-vs-SPY pair, plus an early-return
  for SPY-vs-itself)

The shared `LocalOHLCV` DataSource is **118 lines** (substrate cost,
amortized across all 5 features and any future OHLCV-based features —
e.g. high-low-range, on-balance-volume, residual momentum). If the
substrate were leaky — i.e. each feature had to re-implement OHLCV
reading — total LOC would be ~5× higher.

**Substrate-level finding (NOT fixed in this branch, per scope):** the
`DataSource.fetch(start, end)` contract is window-keyed, not ticker-
keyed. For per-ticker OHLCV, the natural query is "give me ticker X's
close series." The current substrate forces a long-format frame
across all tickers per (start, end), which would be expensive to
materialize for every feature evaluation. **Mitigation in this batch:**
the LocalOHLCV source module exposes a `close_series(ticker)` accessor
backed by a per-ticker in-process cache. This is an accessor *added by
the source plugin*, not a substrate change — so it's substrate-clean,
but it means feature authors must learn one accessor per source rather
than a uniform substrate-level "give me a panel" API. Recommended
follow-up: add an optional `panel(ticker)` method on `DataSource` so
this pattern is substrate-blessed rather than per-source ad-hoc.

## Adversarial twins

The substrate's `generate_twin(real)` function creates a permuted
twin for each of the 5 features, with the same per-(feature, ticker)
deterministic shuffle seed. Verified in
`tests/test_ws_e_first_batch.py::test_adversarial_twins_can_be_generated_for_all_five`:

  - All 5 twins generate without error.
  - Each twin has `tier='adversarial'` and the canonical id
    `<feature>__adversarial_twin`.
  - Twin determinism — same value returned across two consecutive calls
    (caching layer is stable).

**No twin-vs-real importance comparison is meaningful at this stage.**
The substrate's `assert_adversarial_filter_passes(real_imp, twin_imp,
fid)` requires meta-learner importance numbers, which depend on
Foundry-feature integration with the production meta-learner. That
integration is the deferred item Workstream D #4 (see substrate audit
doc). When it lands, the adversarial filter will run as part of the
gauntlet; the twins shipped here will be ready inputs.

## Ablation result

`run_ablation()` was exercised against the 5 registered feature ids
with a synthetic linear-contribution `backtest_fn` (per the substrate's
designed test path — production-backtest integration is also the
deferred item Workstream D #2):

| feature_id | dropped Sharpe | contribution Sharpe |
|---|---:|---:|
| `mom_12_1` | 0.5000 | 0.3000 |
| `mom_6_1` | 0.7000 | 0.1000 |
| `reversal_1m` | 0.7500 | 0.0500 |
| `realized_vol_60d` | 0.6000 | 0.2000 |
| `beta_252d` | 0.6500 | 0.1500 |

Baseline Sharpe (full set): 0.8000.
Persisted to: `data/feature_foundry/ablation/ws-e-first-batch-2026-05-02.json`.

**These numbers do not represent real alpha.** They are the synthetic
weights the test harness was given, used solely to confirm that:

  1. `run_ablation()` accepts a list of real, registered feature ids.
  2. The runner enumerates correctly and persists JSON cleanly.
  3. The latest-ablation lookup the dashboard uses returns the right
     row per feature.

Real ablation contributions will require the deferred meta-learner +
production-backtest closure (Workstream D items 2 + 4).

## Real-data smoke test

The features were also evaluated on the existing 109-ticker universe's
real OHLCV at `dt=2025-12-01` to confirm sensible non-synthetic outputs:

```
feature                    AAPL       MSFT       NVDA        SPY
mom_12_1                 0.1549     0.2309     2.2158     0.1528
mom_6_1                  0.3316     0.1203     1.0699     0.1508
reversal_1m              0.0441    -0.0725     0.0212     0.0006
realized_vol_60d         0.2213     0.1831     0.5410     0.1248
beta_252d                1.2345     0.8892     2.1990       None
```

NVDA's 222% 12-1 momentum and 54% realized vol; MSFT beta 0.89; SPY beta
correctly returns None. Values are sane — no off-by-one window errors,
no inverted signs, no leakage past `dt`.

## Test coverage

`tests/test_ws_e_first_batch.py` — **12 tests, all passing:**

  - all-features-registered enumeration
  - `mom_12_1`, `mom_6_1`, `reversal_1m`: numeric-equality vs
    closed-form computation on synthetic series
  - insufficient-history → None for each lookback
  - `realized_vol_60d`: low-vs-high vol rank ordering (FLAT < TREND)
  - `beta_252d`: SPY-vs-self returns None; in-range for other tickers
  - unknown-ticker → None for any feature
  - twin generation across all 5 features (substrate integration)
  - ablation runner over all 5 feature ids (substrate integration)
  - `validate_all_model_cards()` returns no errors for the new features

Existing `tests/test_feature_foundry.py` (29 tests) **still passes** —
no regression introduced by the new source/features/model cards.

## Engine boundaries respected

  - No engine code modified.
  - No edits to `engines/engine_a_alpha/edge_registry.py` — Foundry
    features remain decoupled from the edge registry per the substrate's
    intent.
  - `cockpit/dashboard_v2/` untouched — the existing Foundry tab will
    auto-pick-up the new features and their persisted ablation row via
    the loader's `latest_ablation_for_feature()` lookup.
  - `data/feature_foundry/` writes only (already gitignored output).
  - `live_trader/`, `data/governor/`, `cockpit/dashboard/` untouched.

## Findings flagged for follow-up

These are substrate-level observations from authoring 5 features in
sequence. **Not fixed in this branch** per dispatch boundary "Do NOT
modify the Foundry substrate itself."

1. **`DataSource` panel-shape ambiguity.** The window-keyed
   `fetch(start, end)` contract pushes per-source ad-hoc accessors
   (e.g. `close_series(ticker)`) for ticker-keyed datasets. Adding an
   optional `panel(ticker, start, end)` method on the base class would
   give feature authors a uniform substrate API.

2. **Self-registration on import sets a non-empty data_root default.**
   `LocalOHLCV()` instantiated at import time defaults to
   `Path("data/processed")`. Tests must re-register with a `tmp_path`-
   pointed instance to avoid touching real data. This is fine but
   future sources should follow the same "register a no-op default"
   pattern (matching `CFTCCommitmentsOfTraders` whose default fetcher
   raises clearly).

3. **`generate_twin()` materializes ±5y of dates × ticker on first
   call.** For features that read from per-ticker CSVs of typical
   length, this is fine. For higher-frequency or larger-universe
   sources, the lazy materialization should bound `start`/`end` more
   tightly. Not a bug; an optimization knob for later.

4. **`license`-string inconsistency vector.** Feature decorator and
   model card must agree exactly; the validator catches it but there
   is no enum or shared constant. Trivial to add (single
   `LICENSES = {"public", "internal", ...}` const) but skipped here
   per the no-substrate-changes rule.

## Five-line report

  - Branch: `ws-e-first-batch`.
  - Shipped: 5 features (`mom_12_1`, `mom_6_1`, `reversal_1m`,
    `realized_vol_60d`, `beta_252d`) + 5 model cards + 12 unit tests.
  - LOC per feature module: 39 / 39 / 39 / 42 / 58.
  - **Substrate's <50-LOC promise: holds for 4/5 features.** The 1
    miss (`beta_252d`, 58 lines) is feature-intrinsic alignment
    boilerplate, not substrate leak.
  - Ablation runner + twin generator integrate cleanly with the new
    features; persisted ablation JSON visible to dashboard via existing
    loader.
