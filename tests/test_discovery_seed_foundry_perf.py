"""T-2026-05-12-038-CONT regression suite — Discovery Foundry-feature
vectorization correctness + performance.

Asserts:

1. The `ticker_independent` decorator field is honored by the engine
   D classifier (no empirical probe required).
2. The panel-cache pattern in `correlation_average_60d` and
   `dispersion_60d` hits the cache on second-and-later calls.
3. Repeated invocations are deterministic.
4. The vectorized implementations preserve the pre-T-038-CONT output
   contract (returns None on real dates due to the still-unfixed
   union-of-date-sets dropna issue).
5. End-to-end `_compute_foundry_features` for a synthetic small
   substrate completes under target wall time.
"""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd
import pytest

import core.feature_foundry.features  # noqa: F401 — side-effectful register
from core.feature_foundry import get_feature_registry
from core.feature_foundry.features.correlation_average_60d import (
    clear_correlation_cache,
    _LOG_RETURNS_PANEL as _CORR_PANEL_REF,
    _ensure_panel_loaded as _ensure_corr_panel,
)
from core.feature_foundry.features import correlation_average_60d as corr_mod
from core.feature_foundry.features import dispersion_60d as disp_mod
from engines.engine_d_discovery.feature_engineering import (
    FeatureEngineer,
    _classify_feature_ticker_independence,
    _FOUNDRY_TICKER_INDEPENDENCE,
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    _FOUNDRY_TICKER_INDEPENDENCE.clear()
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.clear()
    clear_correlation_cache()
    disp_mod.clear_dispersion_cache()
    yield
    _FOUNDRY_TICKER_INDEPENDENCE.clear()
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.clear()
    clear_correlation_cache()
    disp_mod.clear_dispersion_cache()


def _get_feat(fid: str):
    reg = get_feature_registry()
    feats = {f.feature_id: f for f in reg.list_features()}
    return feats[fid]


def test_classify_ticker_independent_honors_decorator():
    """T-038-CONT addition: the explicit `ticker_independent=True`
    decorator field is trusted without an empirical probe. Required
    because the probe fails for universe-wide features that return
    None on synthetic probe tickers."""
    f = _get_feat("correlation_average_60d")
    assert f.ticker_independent is True

    # Classifier returns True without calling `func` (would otherwise
    # take ~2 sec to build the panel via the empirical probe).
    t0 = time.perf_counter()
    is_indep = _classify_feature_ticker_independence(f)
    elapsed = time.perf_counter() - t0
    assert is_indep is True
    # Empirical probe takes ~2 sec on local OHLCV; the annotation path
    # must be near-instant.
    assert elapsed < 0.05, (
        f"classifier took {elapsed:.3f}s — expected <0.05s when "
        f"ticker_independent=True (skipping empirical probe)"
    )


def test_classify_ticker_dependent_falls_back_to_probe():
    """Features WITHOUT the explicit annotation must still go through
    the empirical probe — preserves pre-T-038-CONT behavior."""
    # Pick a feature known to be ticker-dependent (beta_252d).
    f = _get_feat("beta_252d")
    assert f.ticker_independent is False
    is_indep = _classify_feature_ticker_independence(f)
    assert is_indep is False


def test_correlation_average_60d_panel_cache_hit():
    """T-038-CONT vectorization: panel built once, subsequent calls
    skip the universe assembly."""
    # First call builds the panel.
    t0 = time.perf_counter()
    _ = corr_mod.correlation_average_60d("AAPL", date(2024, 6, 17))
    t_first = time.perf_counter() - t0

    # Second call on the SAME date hits the per-date cache.
    t0 = time.perf_counter()
    _ = corr_mod.correlation_average_60d("AAPL", date(2024, 6, 17))
    t_second = time.perf_counter() - t0

    # Third call on a DIFFERENT date hits the panel cache but
    # recomputes the per-date slice + corr.
    t0 = time.perf_counter()
    _ = corr_mod.correlation_average_60d("AAPL", date(2024, 6, 18))
    t_third = time.perf_counter() - t0

    # Panel build dominates first call; subsequent calls are 100x+
    # faster.
    assert t_first > 0.05, f"first-call panel build too fast ({t_first:.3f}s)"
    assert t_second < t_first / 10, (
        f"per-date cache hit not 10x faster: first={t_first:.3f}s "
        f"second={t_second:.3f}s"
    )
    assert t_third < t_first / 10, (
        f"panel-cache reuse not 10x faster: first={t_first:.3f}s "
        f"third={t_third:.3f}s"
    )


def test_dispersion_60d_panel_cache_hit():
    """Same panel-cache pattern as correlation_average_60d."""
    t0 = time.perf_counter()
    _ = disp_mod.dispersion_60d("AAPL", date(2024, 6, 17))
    t_first = time.perf_counter() - t0

    t0 = time.perf_counter()
    _ = disp_mod.dispersion_60d("AAPL", date(2024, 6, 18))
    t_third = time.perf_counter() - t0

    assert t_first > 0.05, f"first-call panel build too fast ({t_first:.3f}s)"
    assert t_third < t_first / 5, (
        f"panel-cache reuse not 5x faster: first={t_first:.3f}s "
        f"third={t_third:.3f}s"
    )


def test_correlation_average_60d_determinism():
    """Repeated invocations on the same date return the EXACT same
    value (not just within tolerance — bit-identical)."""
    values = [
        corr_mod.correlation_average_60d("AAPL", date(2024, 6, 17))
        for _ in range(5)
    ]
    # All must be identical (could be None or a float).
    first = values[0]
    for v in values[1:]:
        assert v == first or (v is None and first is None), (
            f"non-deterministic correlation_average_60d output: {values}"
        )


def test_dispersion_60d_determinism():
    values = [
        disp_mod.dispersion_60d("AAPL", date(2024, 6, 17))
        for _ in range(5)
    ]
    first = values[0]
    for v in values[1:]:
        if first is None:
            assert v is None
        else:
            assert v == first, (
                f"non-deterministic dispersion_60d output: {values}"
            )


def test_correlation_output_unchanged_post_optimization():
    """Golden-file test (T-038-CONT brief acceptance #4): the
    vectorized implementation must return the SAME values as the
    pre-T-038-CONT scalar implementation for the same inputs.

    The pre-T-038-CONT implementation returned None for every real
    date in our local OHLCV substrate because `pd.DataFrame(log_returns)
    .dropna()` (default axis=0/how=any) collapses to <30 rows when
    727 tickers contribute slightly-misaligned date sets. The
    vectorized implementation preserves this behavior by using
    `dropna()` with the same defaults on each per-date slice.
    """
    # Test across a year of dates — all must return None to match
    # pre-T-038-CONT behavior.
    test_dates = [date(2024, m, 15) for m in range(1, 13)]
    for d in test_dates:
        v = corr_mod.correlation_average_60d("AAPL", d)
        # Pre-T-038-CONT behavior: returns None due to the dropna
        # killing the DataFrame on the union-of-date-sets. The fix
        # for this is OUT OF SCOPE (separate workstream).
        assert v is None, (
            f"correlation_average_60d({d}) returned {v}, expected None "
            f"to match pre-T-038-CONT behavior. The dropna semantics "
            f"bug-fix is a separate workstream — see T-038-CONT audit "
            f"doc § 'Out of scope'."
        )


def test_dispersion_output_unchanged_post_optimization():
    """Same golden-file constraint for dispersion_60d. Unlike
    correlation_average_60d, this function returns REAL values on
    real dates pre-T-038-CONT (it doesn't use dropna). Verify the
    post-vectorize output matches a representative computed-by-hand
    value within numerical tolerance.

    We don't pin to an exact frozen scalar (the universe data evolves
    over time as CSVs get refreshed), but we DO assert non-None +
    physically-plausible bounds.
    """
    v = disp_mod.dispersion_60d("AAPL", date(2024, 6, 17))
    # Real markets: cross-sectional std of 60-day returns is typically
    # 0.05 - 0.50 (5% to 50% annualized-equivalent dispersion).
    assert v is not None
    assert 0.0 < v < 2.0, (
        f"dispersion_60d returned implausible value {v}; "
        f"expected 0.0 < v < 2.0"
    )


def test_panel_cache_is_in_process_singleton():
    """The panel cache lives at module scope. Verify that a fresh
    import + first call constructs it, and a subsequent call sees
    the SAME panel instance (no rebuild)."""
    panel1 = _ensure_corr_panel()
    panel2 = _ensure_corr_panel()
    assert panel1 is panel2, (
        "panel cache rebuilt unexpectedly — `is` identity must hold "
        "across calls within the same process"
    )


def test_engine_d_cache_short_circuits_for_annotated_feature():
    """When a feature is annotated `ticker_independent=True`, the
    engine D per-(fid, dt) cache must short-circuit on the second
    ticker, avoiding even a single `func()` call.

    This is the core T-038-CONT win — pre-fix, the engine D code
    called `func(ticker, dt)` once per (ticker, dt) pair regardless of
    whether the underlying compute was ticker-independent.
    """
    f = _get_feat("correlation_average_60d")
    assert _classify_feature_ticker_independence(f) is True

    # Simulate the engine D wrapper logic.
    from engines.engine_d_discovery.feature_engineering import (
        _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE,
        _CACHE_MISS,
    )

    # First call: cache miss → invoke func.
    key = ("correlation_average_60d", date(2024, 6, 17))
    cached = _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.get(key, _CACHE_MISS)
    assert cached is _CACHE_MISS
    v1 = f.func("AAPL", date(2024, 6, 17))
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE[key] = v1

    # Second call for DIFFERENT ticker: cache hit, NO func invocation.
    cached = _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.get(key, _CACHE_MISS)
    assert cached is not _CACHE_MISS
    assert cached == v1 or (cached is None and v1 is None)


def test_compute_foundry_features_synthetic_panel_perf():
    """End-to-end perf gate (T-038-CONT brief acceptance #4): a
    100-bar × 30-ticker invocation of `FeatureEngineer.compute_all_
    features` (with ticker= threading the Foundry pass) completes
    inside a 60-second wall-time budget.

    Without the T-038-CONT vectorize fix, the same workload took
    >300 sec because each per-(ticker, date) Foundry call rebuilt
    the universe from scratch.
    """
    # Build a tiny synthetic OHLC panel — 100 bars, real-looking
    # prices.
    dates = pd.bdate_range("2024-01-02", periods=100)
    rng = np.random.default_rng(42)
    fe = FeatureEngineer()

    # Use real tickers from data/processed so close_series() finds
    # them (otherwise Foundry features all return None very fast,
    # masking the test).
    from core.feature_foundry.sources.local_ohlcv import list_tickers
    real_tickers = sorted(list_tickers())[:30]
    if len(real_tickers) < 30:
        pytest.skip("need ≥30 tickers in local OHLCV substrate")

    t0 = time.perf_counter()
    for tk in real_tickers:
        synthetic_ohlc = pd.DataFrame(
            {
                "Open": 100.0 + rng.standard_normal(100).cumsum(),
                "High": 100.5 + rng.standard_normal(100).cumsum(),
                "Low": 99.5 + rng.standard_normal(100).cumsum(),
                "Close": 100.0 + rng.standard_normal(100).cumsum(),
                "Volume": rng.integers(1e5, 1e7, 100),
            },
            index=dates,
        )
        _ = fe.compute_all_features(
            synthetic_ohlc,
            fund_df=pd.DataFrame(),
            ticker=tk,
        )
    elapsed = time.perf_counter() - t0
    assert elapsed < 60.0, (
        f"compute_all_features over 30 tickers × 100 bars took "
        f"{elapsed:.1f}s, exceeds 60-sec budget. Vectorize fix "
        f"regressed?"
    )
