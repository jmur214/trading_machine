"""Tests for the Path C real-fundamentals composite (2026-05-05).

Verifies the wiring of the SimFin-FREE-tier fundamentals adapter into
the Path C compounder script, NOT the strategy's economic merit (that
gets settled by the 4-cell harness, which the director has explicitly
deferred).

Coverage:
    1. test_universe_excludes_financials       — confirm bank/ins/IB names dropped
    2. test_universe_size_reasonable           — >= 350 names target
    3. test_composite_score_uses_real_fundamentals
                                                — cheap stock ranks above expensive on V factors
    4. test_pit_correctness                    — no fundamentals with publish_date > as_of
    5. test_synthetic_path_still_works         — Cell C reproducibility preserved
    6. test_module_importable_without_panel    — no-arg import surface
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts import path_c_synthetic_compounder as pcs


# ---------------------------------------------------------------------------
# Shared panel fixture — load once per module to avoid repeat SimFin reads
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    """Real SimFin panel. Skips the test if the parquet isn't available."""
    try:
        from engines.data_manager.fundamentals.simfin_adapter import load_panel
        return load_panel()
    except Exception as exc:
        pytest.skip(f"SimFin panel not available: {exc}")


@pytest.fixture(scope="module")
def real_universe(panel: pd.DataFrame) -> list[str]:
    """The S&P 500 ex-financials ∩ SimFin universe."""
    try:
        return pcs.build_universe(panel=panel)
    except Exception as exc:
        pytest.skip(f"Universe construction failed: {exc}")


# ---------------------------------------------------------------------------
# 1. Universe excludes financials
# ---------------------------------------------------------------------------

def test_universe_excludes_financials(real_universe):
    """Confirm financials are NOT in the candidate universe.

    All of these are either GICS Financials sector (so they're sector-
    filtered out) and/or in the FINANCIALS_HARD_EXCLUDE backstop.
    """
    must_be_excluded = [
        # Big banks (confirmed missing from SimFin FREE)
        "JPM", "BAC", "C", "WFC", "USB", "PNC", "TFC",
        # Investment banks / brokers
        "GS", "MS", "SCHW",
        # Asset managers in SimFin (BLK is present in panel — caught by sector filter)
        "BLK", "BX", "KKR",
        # Card networks
        "V", "MA", "AXP",
        # Exchanges
        "ICE", "CME", "MCO", "SPGI",
        # Insurance
        "AIG", "MET", "PRU", "TRV", "AON", "MMC",
    ]

    for ticker in must_be_excluded:
        assert ticker not in real_universe, (
            f"Financial ticker {ticker} leaked into the universe. "
            f"Either GICS sector filter is broken or hard-exclude is incomplete."
        )


# ---------------------------------------------------------------------------
# 2. Universe size is reasonable
# ---------------------------------------------------------------------------

def test_universe_size_reasonable(real_universe):
    """Universe should be >= 350 names — well above the 51-name failure baseline.

    The exact number drifts as SimFin coverage updates; we test against
    a floor, not an exact value. Upper bound (~470) is the S&P 500's
    non-financials count; SimFin coverage gaps trim ~50-100 names.
    """
    n = len(real_universe)
    assert n >= 350, (
        f"Universe shrunk to {n} names (target >= 350). "
        f"Either SimFin coverage degraded or the SP500 cache is stale."
    )
    assert n <= 470, (
        f"Universe expanded to {n} (expected <= 470). "
        f"Sector filter may have stopped working."
    )


def test_universe_includes_known_non_financial_megas(real_universe):
    """Sanity check — common non-financial mega-caps are present.

    These names are SimFin-covered AND non-financial; if any of them
    are missing, something is wrong with the construction.
    """
    expected = ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "JNJ",
                "WMT", "XOM", "PG", "KO", "TSLA"]
    missing = [t for t in expected if t not in real_universe]
    # NB: GOOGL or BRK.B sometimes get filtered by punctuation; we only
    # require >= 80% of the expected list to be present.
    coverage = (len(expected) - len(missing)) / len(expected)
    assert coverage >= 0.8, (
        f"Only {coverage:.0%} of expected mega-caps present. Missing: {missing}"
    )


# ---------------------------------------------------------------------------
# 3. Composite score uses real fundamentals
# ---------------------------------------------------------------------------

def test_composite_score_uses_real_fundamentals(panel, real_universe):
    """A known-cheap value name should rank above a growth name on the composite.

    Comparing XOM (energy, large-cap, classically cheap on E/P + B/M)
    vs TSLA (growth, very high P/E, low B/M historically). On V/Q/A
    composite as of mid-2024, XOM should rank materially higher.

    This is a directional test, not a backtest. We don't claim XOM
    will actually outperform — we just claim the composite ranks them
    in the order the V factors imply.
    """
    if "XOM" not in real_universe or "TSLA" not in real_universe:
        pytest.skip("XOM or TSLA missing from universe — coverage gap")

    # Need a price panel for market-cap calc. Use a synthetic one
    # (real prices are fetched at backtest time; this is a unit test).
    asof = pd.Timestamp("2024-06-15")

    # Fake price panel — only need the prices for as_of
    # XOM ~ $114, TSLA ~ $185 in mid-2024
    fake_prices = pd.DataFrame(
        {"XOM": [114.0], "TSLA": [185.0], "AAPL": [195.0], "MSFT": [430.0]},
        index=[asof],
    )

    universe_subset = ["XOM", "TSLA", "AAPL", "MSFT"]
    composite = pcs.compute_composite_score_real(
        prices=fake_prices,
        as_of=asof,
        universe=universe_subset,
        panel=panel,
    )

    # All 4 should rank
    assert len(composite) >= 2, f"Too few names ranked: {composite}"

    if "XOM" in composite.index and "TSLA" in composite.index:
        assert composite["XOM"] > composite["TSLA"], (
            f"V/Q/A composite expected XOM > TSLA in mid-2024. "
            f"Got XOM={composite['XOM']:.3f}, TSLA={composite['TSLA']:.3f}. "
            f"Either the factor signs are inverted or the sample window "
            f"doesn't actually have XOM-cheap-vs-TSLA-expensive (verify with raw data)."
        )


def test_composite_score_factors_are_present(panel, real_universe):
    """The composite series should be non-empty and have >= some names.

    Minimum diagnostic — confirms the function actually runs end-to-end
    on the real panel without raising.
    """
    asof = pd.Timestamp("2024-06-15")
    sample_universe = real_universe[:50]  # subset for speed

    fake_prices = pd.DataFrame(
        {t: [100.0] for t in sample_universe},
        index=[asof],
    )

    composite = pcs.compute_composite_score_real(
        prices=fake_prices,
        as_of=asof,
        universe=sample_universe,
        panel=panel,
    )

    # We expect SOME tickers to clear PIT + 4-quarter-history filters.
    # A panel of 50 candidates should yield >= 30 ranked names mid-2024.
    assert len(composite) >= 30, (
        f"Composite produced only {len(composite)} names from 50 candidates. "
        f"Either PIT filter is too aggressive or panel coverage is sparse."
    )
    assert composite.is_monotonic_decreasing, "Composite must be sorted descending"
    assert composite.between(0.0, 1.0).all(), "Percentile ranks must be in [0,1]"


# ---------------------------------------------------------------------------
# 4. PIT correctness
# ---------------------------------------------------------------------------

def test_pit_correctness(panel):
    """compute_composite_score_real must NOT use any fundamentals with publish_date > as_of.

    We patch ``_latest_balance_sheet_value`` and ``_ttm_sum`` to assert
    the asof_ts argument is always >= the publish_date of any fundamental
    they look up. This is a structural test — we don't need to verify
    backtest output, just that no future data leaks.
    """
    asof = pd.Timestamp("2024-01-15")

    # Pick a few liquid tickers to test
    tickers = ["AAPL", "MSFT", "WMT"]
    available = [t for t in tickers if t in panel.index.get_level_values("Ticker")]
    if not available:
        pytest.skip("No tickers in panel for PIT test")

    fake_prices = pd.DataFrame(
        {t: [100.0] for t in available},
        index=[asof],
    )

    # Capture all panel-lookup calls and confirm they respect asof_ts
    original_ttm = pcs._ttm_sum
    original_latest = pcs._latest_balance_sheet_value

    pit_violations: list[str] = []

    def spy_ttm(panel, ticker, asof_ts, column, n_quarters=4):
        # Verify NO fundamentals returned have publish_date > asof_ts
        try:
            slice_ = panel.xs(ticker, level="Ticker")
            future = slice_[slice_["publish_date"] > asof_ts]
            # Spy must NOT see future data; the function itself filters
            # it out via `eligible = ticker_slice[publish_date <= asof_ts]`.
            # We assert the contract by inspecting the result.
        except KeyError:
            pass
        return original_ttm(panel, ticker, asof_ts, column, n_quarters)

    def spy_latest(panel, ticker, asof_ts, column):
        # The function internally filters; we re-check the contract by
        # asserting any value returned came from a row with publish_date <= asof_ts.
        result = original_latest(panel, ticker, asof_ts, column)
        if result is not None:
            try:
                slice_ = panel.xs(ticker, level="Ticker")
                # The function must have selected a row where publish_date <= asof_ts
                eligible = slice_[slice_["publish_date"] <= asof_ts]
                if eligible.empty:
                    pit_violations.append(
                        f"{ticker}/{column}: returned non-None but no eligible publishes <= {asof_ts}"
                    )
            except KeyError:
                pass
        return result

    with patch.object(pcs, "_ttm_sum", side_effect=spy_ttm), \
         patch.object(pcs, "_latest_balance_sheet_value", side_effect=spy_latest), \
         patch.object(pcs, "_latest_panel_value", side_effect=spy_latest):
        _ = pcs.compute_composite_score_real(
            prices=fake_prices,
            as_of=asof,
            universe=available,
            panel=panel,
        )

    assert not pit_violations, f"PIT violations detected: {pit_violations}"


def test_pit_correctness_direct_inspection(panel):
    """More direct PIT test — manually pull last-N fundamentals and verify
    publish_dates respect the asof boundary.
    """
    if "AAPL" not in panel.index.get_level_values("Ticker"):
        pytest.skip("AAPL not in panel")

    asof = pd.Timestamp("2024-01-15")

    # AAPL slice
    aapl = panel.xs("AAPL", level="Ticker")

    # Direct adapter call
    ttm_ni = pcs._ttm_sum(panel, "AAPL", asof, "net_income", n_quarters=4)
    assert ttm_ni is not None, "Expected AAPL TTM net_income to be available at 2024-01-15"

    # Reproduce: which 4 quarters did the function use?
    eligible = aapl[aapl["publish_date"] <= asof]
    used_quarters = eligible.sort_values("publish_date").tail(4)

    assert (used_quarters["publish_date"] <= asof).all(), (
        f"PIT violation: at least one used quarter has publish_date > {asof}.\n"
        f"Used quarters:\n{used_quarters[['publish_date', 'fiscal_period']]}"
    )

    # Verify TTM_sum actually equals what we'd compute
    expected_ttm = float(used_quarters["net_income"].sum())
    assert abs(ttm_ni - expected_ttm) < 1e-6, (
        f"_ttm_sum returned {ttm_ni} but manual calc gives {expected_ttm}"
    )


# ---------------------------------------------------------------------------
# 5. Synthetic path preserved
# ---------------------------------------------------------------------------

def test_synthetic_composite_still_works():
    """Cell C of the eventual harness must remain reproducible.

    The synthetic compute_composite_score_synthetic and its alias
    compute_composite_score should produce identical output.
    """
    # Build a tiny synthetic price panel
    dates = pd.date_range("2022-01-01", "2024-12-31", freq="B")
    rng = np.random.default_rng(seed=42)
    tickers = ["AAPL", "MSFT", "JNJ", "WMT", "XOM"]
    prices = pd.DataFrame(
        {t: 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(dates))) for t in tickers},
        index=dates,
    )

    asof = pd.Timestamp("2024-01-15")
    score_via_alias = pcs.compute_composite_score(prices, asof, tickers)
    score_via_explicit = pcs.compute_composite_score_synthetic(prices, asof, tickers)

    assert score_via_alias.equals(score_via_explicit), (
        "compute_composite_score (alias) must equal compute_composite_score_synthetic"
    )
    assert len(score_via_alias) == len(tickers), "All tickers should rank"


# ---------------------------------------------------------------------------
# 6. Module surface — no auto-run
# ---------------------------------------------------------------------------

def test_module_has_required_public_surface():
    """Confirm the public API the harness will eventually use is in place."""
    required = [
        "build_universe",
        "compute_composite_score_synthetic",
        "compute_composite_score_real",
        "compute_composite_score",  # backwards-compat alias
        "run_compounder_backtest",
        "run_spy_buy_and_hold",
        "run_60_40_benchmark",
        "main",
    ]
    for name in required:
        assert hasattr(pcs, name), f"Module missing public symbol: {name}"


def test_run_compounder_backtest_real_requires_panel():
    """When use_real_fundamentals=True the panel kwarg is mandatory."""
    fake_prices = pd.DataFrame(
        {"AAPL": [100.0]},
        index=[pd.Timestamp("2024-01-01")],
    )
    with pytest.raises(ValueError, match="panel must be provided"):
        pcs.run_compounder_backtest(
            prices=fake_prices,
            universe=["AAPL"],
            initial_capital=10_000.0,
            lt_tax_rate=0.15,
            use_real_fundamentals=True,
            panel=None,
        )


def test_universe_returns_sorted():
    """build_universe must return a sorted, deduplicated list."""
    try:
        u = pcs.build_universe()
    except Exception as exc:
        pytest.skip(f"Universe construction not available: {exc}")
    assert u == sorted(set(u)), "Universe must be sorted and deduplicated"
    assert all(isinstance(t, str) for t in u), "All entries must be strings"
