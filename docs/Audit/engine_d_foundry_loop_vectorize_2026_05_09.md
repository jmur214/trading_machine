# Engine D Foundry-loop vectorization — audit (T-2026-05-08-013)

**Author:** Agent B
**Branch:** `feature/engine-d-foundry-loop-vectorize`
**Spec:** Director's task brief in inbox 2026-05-09 (followed up on the perf observation B flagged in T-006's audit doc).
**Files touched:** `engines/engine_d_discovery/feature_engineering.py`, `tests/test_engine_d_foundry_loop_perf.py` (new).

---

## Headline numbers

5 tickers × 252 bars × 5 samples (median of warm-cache samples reported; first/cold sample dominated by external macro fetches and excluded):

| Metric | PRE | POST | Speedup |
|---|---:|---:|---:|
| Median wall time | **3.160 s** | **0.124 s** | **25.5×** |
| Min | 2.769 s | 0.120 s | 23.1× |
| Max (warm) | 4.249 s | 0.158 s | 26.9× |
| Cold-sample (first call) | 47.551 s | 50.680 s | ~no change |

**Determinism gate: PASSED.** canon md5 IDENTICAL before and after on `scripts/run_isolated --runs 1 --task q1`:
- pre:  `182af6a1240da35055f716ef9dfcd333` (Sharpe 0.127)
- post: `182af6a1240da35055f716ef9dfcd333` (Sharpe 0.127)

Cold-sample equivalence is expected — the first call to a FRED-macro Foundry feature triggers a network/cache fetch that dominates. The optimization target was the warm-cache scalar Python loop, not the data-fetch path.

---

## Mechanism

`TreeScanner` iterates the active universe (~109 tickers) and calls `compute_all_features(..., ticker=T)` per ticker. Inside, every tier-A/B Foundry feature is evaluated on the (ticker, date_seq) grid. A subset of features (calendar, FRED-macro, market-wide cross-asset) return values that are **functions of date only** — calling them per ticker re-does identical work N times.

The vectorization adds a process-level cache with two layers:
1. **Empirical classification** (`_classify_feature_ticker_independence`): sample each Foundry feature on two distinct synthetic tickers across three sample dates. If the feature returns the same non-None value for both tickers on at least one sample date, classify as **ticker-independent**. Cached after first call.
2. **Per-date value cache** (`_FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE`): keyed by `(feature_id, date)`. The first ticker populates the cache; tickers 2…N hit it.

Memory bound: ~8 ticker-independent features × ~2000 trading dates ≈ 16K entries × ~24 bytes/entry ≈ **400 KB**. Trivial at 109-ticker production scale.

Concurrency: Engine D is single-process single-threaded — no locking needed. Documented inline.

The classification uses synthetic ticker names (`__FOUNDRY_PROBE_AAA__`, `__FOUNDRY_PROBE_BBB__`) that intentionally don't match any real ticker. `local_ohlcv`-backed features return `None` for both probes (no CSV exists), which fails the "non-None and equal" test, so those features get the **safe default** of ticker-dependent — they never pollute the cache with the wrong-shape values.

Beyond the cache, the inner loop also pulls `feat.func` and `feat.feature_id` out as locals so we don't pay attribute-lookup cost per-bar. Small but additive.

---

## Per-feature classification (24 of 24 Foundry features)

Empirical sampling at run time. Classification is cached per-process.

### 8 ticker-INDEPENDENT (cached after first ticker)

| feature_id | source | Why ticker-independent |
|---|---|---|
| `days_to_quarter_end` | calendar | Pure date arithmetic |
| `month_of_year_dummy` | calendar | Pure date arithmetic |
| `weekday_dummy` | calendar | Pure date arithmetic |
| `vix_change_5d` | fred_macro | Market-wide vol index |
| `hyg_lqd_spread` | fred_macro | Cross-asset credit spread |
| `dxy_change_20d` | fred_macro | Dollar index level |
| `vvix_or_proxy` | fred_macro | Vol-of-vol with fallback |
| `dispersion_60d` | local_ohlcv | Cross-sectional dispersion across the universe — same value for every ticker on a given date |

The empirical sampler correctly caught `dispersion_60d` even though its declared `source="local_ohlcv"` looks ticker-dependent — that's why we chose empirical detection over a hardcoded source-based heuristic. A future feature that drifts its return shape gets reclassified naturally on the first call.

### 16 ticker-DEPENDENT (no cache; scalar loop)

| feature_id | source |
|---|---|
| `cot_commercial_net_long` | cftc_cot |
| `earnings_proximity_5d` | earnings_calendar |
| `mom_12_1`, `mom_6_1`, `reversal_1m` | local_ohlcv |
| `realized_vol_60d`, `beta_252d`, `skew_60d` | local_ohlcv |
| `dist_52w_high`, `drawdown_60d`, `vol_regime_5_60` | local_ohlcv |
| `ma_cross_50_200`, `moving_avg_distance_50d`, `high_minus_low_60d` | local_ohlcv |
| `pair_zscore_60d`, `correlation_average_60d` | local_ohlcv |

For these, the scalar `func(ticker, dt)` call is unavoidable — the value genuinely varies per ticker. Per-ticker work is bounded by `local_ohlcv.close_series(ticker)` which already caches in-process per ticker. We pay one extra Python method-call avoidance (using `feat.func` directly instead of `feat.__call__`); that's the only inner-loop savings here.

---

## Open questions surfaced

### Q1 — Determinism vs ordering

The cache is keyed by `(feature_id, date)` and lookups go through dict `.get()`. Dict iteration order is insertion-ordered in Python 3.7+, but my code only iterates the FEATURE list (deterministic — `registry.list_features()` returns a list ordered by registration), and reads cache by key (no iteration). No nondeterminism introduced.

**Verified:** canon md5 identical pre and post.

### Q2 — Memory at production scale

Monitored above: ~400 KB peak for the cache. Negligible. The cache grows additively as new dates are seen; in a multi-year backtest at daily cadence on a 5-year window, the upper bound is `8 features × 1260 dates ≈ 10K entries`. Even pessimistically scaled to `8 features × 25 years × 252 bars/year ≈ 50K entries × 24 bytes = 1.2 MB` it's still nowhere near a concern.

### Q3 — Test fixture interaction with the autouse `reset_registries` in `test_feature_foundry.py`

The fixture clears the FeatureRegistry but NOT my new caches. That's intentional — my caches are keyed by `(feature_id, date)` and feature_ids are stable across the fixture's snapshot/clear/restore cycle. Tests that change a feature's IMPLEMENTATION under the same id should call the new `_clear_foundry_caches()` helper.

**Verified:** all 38 `test_feature_foundry.py` tests pass post-change. The autouse fixture continues to work correctly; my caches don't pollute the registry snapshot.

### Q4 — Forward perf headroom

The 16 ticker-dependent features still run as a scalar Python loop. Two further optimizations are possible if any individual feature becomes a hotspot:

1. **Per-feature vectorization** — re-implement specific features (e.g., `mom_12_1`, `realized_vol_60d`) to consume `close_series(ticker)` once and return the full `pd.Series` of values rather than one scalar per call. This requires opting individual features into a "batch" interface. Not done here because (a) it requires touching individual feature implementations and (b) the current scalar-loop cost is dominated by `close_series` cache reads which are already O(1).

2. **JIT compilation** — the inner loop is mostly Python overhead. `numba.jit` on the per-feature evaluation path could give another 2-5×. Adds a dependency; not done here per the "DO NOT add new dependencies" hard constraint.

If TreeScanner becomes wall-time-limited in a real Discovery run, those are the next two levers. As it stands, today's 25× speedup on the warm-cache path is more than enough headroom for current usage.

---

## What this does NOT change

- No edge behavior. canon md5 invariant.
- No production backtest path. T-006 made the Foundry pass opt-in via `ticker=None`; default callers (production backtest) skip the pass entirely. The cache only matters for the EXPLICIT `ticker=...` consumer path that TreeScanner / Discovery uses to consume the wider vocabulary.
- No new dependencies. Pure stdlib (`Dict`, `Tuple`, `date`) + existing pandas/numpy.
- No TreeScanner / discovery.py / `edges.yml` changes. Vocabulary expansion stayed atomic in T-006; this is a perf cleanup over the same surface.
- No promotion / weight changes. F-engine still owns the lifecycle.

---

## Verification summary

| Gate | Status |
|---|---|
| Determinism (canon md5 identical) | **PASS** (`182af6a1240da35055f716ef9dfcd333`) |
| New tests | 1 correctness + 1 benchmark (skipped in CI per design) — both green locally |
| Existing test sweep (`test_engine_d_*` + `test_feature_foundry*`) | 44 passed, 1 skipped |
| Speedup vs target ≥2× | **25.5×** (well above the "1.5× = revert" floor) |
| Memory bound at 109-ticker production scale | ~400 KB — trivial |
