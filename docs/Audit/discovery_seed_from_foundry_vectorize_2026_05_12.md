# T-2026-05-12-038-CONT — Profile + vectorize `seed_from_foundry`

**Date:** 2026-05-12
**Branch:** `feature/discovery-seed-from-foundry-vectorize`
**Worker:** Agent B
**Status:** Option C from T-038's BLOCKED outbox.

## Summary

T-038 ran 4.8 hr without emitting a Discovery JSONL — last log line at
post-backtest lifecycle phase, then ~2.5 hr of silent CPU. Root cause:
the Foundry-feature compute path in
`engines.engine_d_discovery.feature_engineering.FeatureEngineer._compute_foundry_features`
iterates `O(tickers × dates × features)` scalar `func(ticker, dt)`
calls. For ~700 tickers × 1008 dates × 31 tier-A+B features, that's
~22M function calls. The dominant cost (96 % in profile) lives in two
universe-wide features that:

1. were MISCLASSIFIED as ticker-DEPENDENT by the empirical probe
   (because they return None on synthetic probe tickers — the
   classifier requires non-None equality to classify as independent),
   AND
2. rebuilt the entire universe-wide return-series dict on every per-
   date invocation.

Two-part fix:
1. Add `ticker_independent: bool = False` to the `@feature` decorator.
   The engine D classifier honors the explicit annotation first; falls
   back to the empirical probe when absent.
2. Vectorize `correlation_average_60d` and `dispersion_60d` to build
   a universe-wide panel ONCE per process, then per-date queries
   slice from the cached panel.

**Hot-path speedup: 95× on `correlation_average_60d`, 11× on
`dispersion_60d`, 15× overall on the profile workload.**

## Profile results

### Pre-fix (10 tickers × 1 year)

| Feature | Total sec | Calls | Per-call μs |
|---|---|---|---|
| `correlation_average_60d` | 76.99 | 2459 | 31,308 |
| `dispersion_60d` | 28.79 | 703 | 40,949 |
| `beta_252d` | 1.31 | 2459 | 532 |
| Top-10 cumulative | 108.65 / 110.0 (99 %) | — | — |

Extrapolation to 700 tickers × 4 years: **30,803 sec ≈ 8.6 hours.**
Consistent with T-038's 4.8-hr partial run before kill.

### Post-fix (same workload)

| Feature | Total sec | Calls | Per-call μs | Speedup |
|---|---|---|---|---|
| `correlation_average_60d` | 0.81 | 703 | 1,159 | **95×** |
| `dispersion_60d` | 2.59 | 703 | 3,678 | **11×** |
| `beta_252d` | 1.30 | 2459 | 531 | 1.0× (unchanged) |
| Profile total elapsed | **7.4** s (was 110 s) | — | — | **15×** |

Extrapolation to 700 tickers × 4 years: **2,082 sec ≈ 35 min.**

Hot-path target (≥10×) achieved on both individual features and on
the combined profile workload.

## Hot path identification

The pre-fix profile placed two features at >90 % of cumulative time:

### `correlation_average_60d` (76.99 s / 70 % of total)

The pre-T-038-CONT implementation built the universe-wide log-returns
dict from scratch on every per-date invocation:

```python
def _compute_avg_correlation(dt):
    log_returns = {}
    for t in list_tickers():            # 727 ticker iterations
        s = close_series(t)              # cached, ~1 μs
        s = s[s.index <= dt]             # ~150 μs
        if len(s) < 61: continue
        closes = s.iloc[-61:].astype(float)
        log_returns[t] = pd.Series(np.diff(np.log(closes.values)), ...)
    df = pd.DataFrame(log_returns).dropna()
    ...
```

Per call: 727 ticker iterations × ~150 μs each ≈ 116 ms. With 1008
unique dates per 4-year Discovery cycle: 1008 × 116 ms ≈ 117 sec.

### `dispersion_60d` (28.79 s / 26 % of total)

Same pattern — iterates 727 tickers per-date, takes p_now / p_then,
builds a list, returns numpy std. Per call: ~41 ms. Total: ~43 s for
1008 dates.

### Misclassification compounding the issue

Both features had docstrings explicitly declaring "value is ticker-
independent" and internal per-date caches (`_CORR_CACHE`,
`_DISPERSION_CACHE`). But the engine D classifier at
`_classify_feature_ticker_independence` rejected them:

```python
v_a = func(probe_AAA, d)   # → None (no synthetic universe data)
v_b = func(probe_BBB, d)   # → None
# Classifier requires non-None equality:
if v_a is not None and v_b is not None and v_a == v_b:
    independent = True
```

`None == None` is True in Python, but the classifier explicitly
requires `v_a is not None`, so both-None probes default to ticker-
DEPENDENT. Pre-fix, every `(ticker, dt)` pair went through `func()` —
the internal per-date cache saved most of the compute, but the Python
function-call overhead × 700 tickers × 1008 dates ≈ 705K calls is non-
trivial.

## Fix

### Change 1: explicit `ticker_independent` decorator annotation

File: `core/feature_foundry/feature.py`

```python
@dataclass
class Feature:
    ...
    ticker_independent: bool = False

def feature(*, feature_id, tier, ..., ticker_independent: bool = False):
    """`ticker_independent=True` declares that the function's return
    value is a function of `dt` only. Engine D's per-process cache
    memoizes by (feature_id, dt) — second-and-later ticker calls hit
    the cache without invoking the underlying compute."""
```

File: `engines/engine_d_discovery/feature_engineering.py`

```python
def _classify_feature_ticker_independence(feat) -> bool:
    if fid in _FOUNDRY_TICKER_INDEPENDENCE:
        return _FOUNDRY_TICKER_INDEPENDENCE[fid]
    # Path 1 (T-038-CONT): trust explicit decorator annotation.
    if getattr(feat, "ticker_independent", False):
        _FOUNDRY_TICKER_INDEPENDENCE[fid] = True
        return True
    # Path 2 (pre-T-038-CONT): empirical probe fallback.
    ...
```

### Change 2: panel-cache vectorization in `correlation_average_60d`

```python
_LOG_RETURNS_PANEL: Optional[pd.DataFrame] = None  # built lazily

def _ensure_panel_loaded():
    global _LOG_RETURNS_PANEL
    if _LOG_RETURNS_PANEL is None:
        _LOG_RETURNS_PANEL = _build_log_returns_panel()  # 1 sec warm-up
    return _LOG_RETURNS_PANEL

def _compute_avg_correlation(dt):
    panel = _ensure_panel_loaded()
    window = panel.loc[panel.index <= dt].iloc[-60:].dropna()
    if window.shape[0] < 30 or window.shape[1] < 3:
        return None
    corr = window.corr().to_numpy()
    return float(corr[np.triu_indices_from(corr, k=1)].mean())
```

Per-call cost drops from 116 ms to 1.2 ms after warm-up. **97×
speedup on the per-date compute.**

### Change 3: same panel-cache for `dispersion_60d`

```python
_CLOSE_PANEL: Optional[pd.DataFrame] = None  # built lazily

def _compute_dispersion(dt):
    panel = _ensure_panel_loaded()
    window = panel.loc[panel.index <= dt]
    if window.shape[0] < 61: return None
    p_now = window.iloc[-1]
    p_then = window.iloc[-61]
    valid = p_now.notna() & p_then.notna() & (p_then > 0)
    ...
```

Per-call drops from 41 ms to 4 ms. **10× speedup.**

### Output preservation

The vectorized implementations preserve the pre-T-038-CONT
`dropna()` semantics EXACTLY (default `axis=0`/`how='any'`).
Behavioral consequence: `correlation_average_60d` still returns
`None` on most real dates because the union-of-date-sets dropna
collapses to <30 surviving rows. **This is intentional** — fixing
the dropna semantics changes feature output, which violates the
T-038-CONT brief's "no output drift" constraint. The dropna bug-fix
is a separate workstream candidate (T-040+).

## Smoke verification + diagnosis update

Discovery smoke cycle (`--window 2024 --batch 3 --substrate-honest`)
was launched but DID NOT complete in the 30-minute target. At 65 min
wall the cycle was killed; log was frozen on
`[DISCOVERY] Regime context: ...` (the line emitted inside
`mode_controller.py` just before `discovery.hunt()`) for ~45 min.

**Investigation surfaced a misdiagnosis in the original T-038 outbox
and the T-038-CONT brief.** Per my grep across the codebase:

```
$ grep -rn "ticker=" engines/ --include="*.py" | grep "compute_all_features"
engines/engine_d_discovery/feature_engineering.py:75:  # docstring only
```

**ZERO production callers pass `ticker=` to
`FeatureEngineer.compute_all_features()`.** The `_compute_foundry_features`
method is guarded by `if ticker:` (feature_engineering.py:282), so the
entire Foundry per-(ticker, date) compute path — including the hot path
I profiled and optimized — is **NEVER INVOKED in production hunt()**.

Specifically:

| Caller | Passes `ticker=`? | Foundry pass runs? |
|---|---|---|
| `engine_d_discovery/discovery.py:117` (`hunt()`) | NO | NO |
| `engine_a_alpha/edges/rule_based_edge.py:137` | NO | NO |
| `scripts/run_shadow_paper.py:86` | NO | NO |
| `engine_d_discovery/feature_engineering.py:716` (`compute_features_for_eval`) | YES | YES |
| `scripts/profile_seed_from_foundry.py` (my profile) | direct call | YES |
| `tests/test_discovery_seed_foundry_perf.py` (my tests) | direct call + via wrapper | YES |

Empirical confirmation: timing AAPL × 1yr in isolation —

| Path | Wall time |
|---|---|
| `compute_all_features(df, ...)` (no ticker) — production hunt() | **20 ms** |
| `compute_all_features(df, ..., ticker="AAPL")` (Foundry on) | **3832 ms** (191× slower) |

For 700 tickers × 1yr without Foundry: 700 × 20 ms = 14 sec. hunt()
itself is NOT the smoke's bottleneck.

Real-world hunt() invocation on 53 tickers × 1yr (representative
substrate) completed in **20.5 sec, emitting 3 candidates**.
Linearly extrapolated to 700 tickers: ~270 sec ≈ 4.5 min — well
under the smoke's 65-min wall.

**So where is the smoke's 65 min of silent CPU going?** Not into the
Foundry feature compute (my optimization target). Likely candidates:

1. The smoke's data_map is larger than my 53-ticker test (substrate-
   honest universe expansion).
2. `compute_cross_sectional_features` on the concatenated 176K-row
   DataFrame.
3. `DecisionTreeScanner.scan` ML pass (sklearn DecisionTreeClassifier
   over a wide feature matrix).
4. Candidate VALIDATION (Gate 1-6), each gate running a sub-backtest.
   Cap=3 means 3 candidates × ~10 min/candidate ≈ 30 min — plausible
   but doesn't match the 60+ min silent phase before any Gate-N log.
5. Some other code path I haven't profiled.

**The T-038 root-cause diagnosis ("seed_from_foundry runs expensive
Foundry-feature compute") is INCORRECT**. The actual production hot
path needs re-profiling against the smoke's specific stuck phase.

### What this audit's optimization DOES improve

The fix is technically correct and shippable:

1. The `ticker_independent` decorator + classifier annotation is a
   pure correctness fix — universe-wide features were previously
   misclassified by the empirical probe, causing redundant `func()`
   calls when the feature_engineering.py wrapper was used.
2. The panel-cache vectorization in `correlation_average_60d` and
   `dispersion_60d` is a real 95×/11× speedup on the wrapped path.
3. The path IS used by tests (`test_discovery_seed_foundry_perf.py`,
   `test_ws_e_fourth_batch.py`) and by `compute_features_for_eval`
   (used by ablation runner / Foundry leakage detector).
4. Future work that threads `ticker=` through production hunt()
   (likely required to actually activate the `foundry_feature` gene
   type that T-022 added to the GA) will benefit from this
   optimization without re-work.

### What this audit DOES NOT solve

The T-038 smoke remains slow at the production hot path. Acceptance
criterion #3 ("smoke Discovery cycle (1yr, cap=3) completes in ≤ 30
min") is **NOT MET** with this fix. The real bottleneck must be
identified via a separate profile against the production hunt()
path.

### Recommended director follow-up (T-040+ candidates)

A. **Profile production `hunt()` with `cProfile`** on a small substrate
(50 tickers × 1yr) to identify the real hot path. Likely candidates:
DecisionTreeScanner.scan() on a 176K-row matrix, or per-ticker
feature pyramid with sklearn-backed transformers.

B. **Profile candidate validation** in the same way. Each Gate runs
a sub-backtest; vectorization opportunities likely exist there.

C. **Thread `ticker=` through production hunt()** if the team wants
foundry_feature genes to actually produce alpha. Without this, T-022's
20%-of-genes are foundry_feature genes that always have NaN values in
the gate-1 evaluation DataFrame and reliably fail validation. This
explains the T-021/T-026 "Discovery emits only rsi_bounce_v1 mutations"
finding — foundry feature candidates are dead-on-arrival because their
referenced columns never get computed.

Per the T-038-CONT brief: **DO NOT auto-run full cap=30 Discovery
cycle.** That decision is gated on the director's pairwise-correlation
diagnostic (separate workstream, not B's scope).

## Tests

File: `tests/test_discovery_seed_foundry_perf.py` (11 tests, all pass)

1. `test_classify_ticker_independent_honors_decorator` — annotation
   path bypasses empirical probe (<50 ms).
2. `test_classify_ticker_dependent_falls_back_to_probe` — preserves
   pre-T-038-CONT behavior for un-annotated features.
3. `test_correlation_average_60d_panel_cache_hit` — first call builds
   panel; subsequent calls 10× faster.
4. `test_dispersion_60d_panel_cache_hit` — same pattern.
5. `test_correlation_average_60d_determinism` — bit-identical repeats.
6. `test_dispersion_60d_determinism` — same.
7. `test_correlation_output_unchanged_post_optimization` — golden
   test: still returns None on real dates (pre-T-038-CONT behavior).
8. `test_dispersion_output_unchanged_post_optimization` — returns
   plausible cross-sectional std.
9. `test_panel_cache_is_in_process_singleton` — `is` identity.
10. `test_engine_d_cache_short_circuits_for_annotated_feature` —
    engine D cache pattern.
11. `test_compute_foundry_features_synthetic_panel_perf` — 30 tickers
    × 100 bars completes inside 60 s budget.

Existing tests (`tests/test_ws_e_fourth_batch.py` and
`tests/test_feature_foundry.py`) — 53/53 still pass.

## Out of scope (deferred / future work)

1. **`correlation_average_60d` returns None on real dates** because
   `pd.DataFrame(log_returns).dropna()` collapses with 727 tickers
   contributing slightly-misaligned date sets. Fix is single line
   (`how='any'` → column-wise drop or pairwise correlation) but
   changes output. Candidate for T-040+. Worth ~117 sec/cycle of
   currently-wasted compute.
2. **`beta_252d`** (1.3 sec per profile, ticker-dependent) — 252-day
   regression of ticker returns on benchmark returns. Could be
   vectorized over dates per-ticker but doesn't dominate.
3. **Per-cycle disk cache** at
   `data/cache/foundry_features_<universe_hash>_<date_range>.parquet`
   — would amortize first-call panel build across Discovery cycle
   restarts. Brief recommended this; deferred because the in-process
   cache + ~5-sec first-call cost is acceptable for a single cycle.
   Worth ~5 sec on the 2nd-and-later cycle; meaningful if cycles run
   back-to-back.
4. **Adding more `ticker_independent=True` annotations**. Audit
   identified only 2 universe-wide features in current codebase.
   Future features (e.g., T-052's 4-signal regime ensemble — all
   macro/cross-asset) should set `ticker_independent=True` at
   decoration time.

## Branch + commit

Branch: `feature/discovery-seed-from-foundry-vectorize`
Commits:
- profile script + initial annotation
- panel-cache vectorization for both features
- regression test suite

Push: complete. Director merges.

## DO NOT auto-run full cap=30 Discovery cycle

Per T-038-CONT brief and director's research-synthesis context: the
team is NOT running another Discovery cycle on the S&P 500 substrate
until a separate director-side pairwise-correlation diagnostic
clears. T-038-CONT's job was infrastructure (this vectorization);
the decision to fire a cycle belongs to the director.
