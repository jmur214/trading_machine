"""Engine D vocabulary-expansion tests (T-2026-05-08-006).

Two additive changes covered:

1. Foundry feature ingestion via `_compute_foundry_features` —
   tier-A and tier-B features from `core.feature_foundry` are
   evaluated on the (ticker, date) grid; results land as
   ``Foundry_<feature_id>`` columns. Features with unavailable
   data sources (e.g. local OHLCV CSV missing) return None and
   produce NaN columns instead of crashing.

2. Fundamentals-percentile operators in
   `compute_cross_sectional_features` — V/Q/A factor columns
   (roe, gross_profitability, sloan_accruals, etc.) present in
   the input frame get ``XS_<PrettyName>_Pctile`` companions
   ranked per date.

The spec lives at
``docs/Measurements/2026-05/spec_engine_d_vocabulary_fix_2026_05_08.md``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from engines.engine_d_discovery.feature_engineering import FeatureEngineer


# ---------------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------------- #


def _ohlc(periods: int = 60) -> pd.DataFrame:
    """Deterministic OHLCV frame with enough history for technical
    indicators (SMA-50, RSI-14, etc.) to populate."""
    dates = pd.date_range("2024-01-02", periods=periods, freq="B")
    close = np.linspace(100.0, 120.0, periods)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(periods, 1_000_000),
        },
        index=dates,
    )


def _stacked_with_fundamentals() -> pd.DataFrame:
    """3 tickers x 5 dates, with three V/Q/A columns present
    (roe, gross_profitability, sloan_accruals) at deterministic
    cross-sectional ranks."""
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    # BBB > AAA > CCC on every factor — clean rank target.
    spec = [
        ("AAA", 0.10, 0.20, 0.05),
        ("BBB", 0.20, 0.30, 0.08),
        ("CCC", 0.05, 0.10, 0.02),
    ]
    rows = []
    for ticker, roe, gp, accr in spec:
        for d in dates:
            rows.append({
                "ticker": ticker,
                "Date": d,
                "Close": 100.0,
                "roe": roe,
                "gross_profitability": gp,
                "sloan_accruals": accr,
            })
    return pd.DataFrame(rows).set_index("Date")


def _stacked_without_fundamentals() -> pd.DataFrame:
    """Same 3-ticker layout but only OHLCV-derived columns — no
    fundamentals columns at all."""
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    rows = []
    for ticker in ("AAA", "BBB", "CCC"):
        for d in dates:
            rows.append({
                "ticker": ticker,
                "Date": d,
                "Close": 100.0,
                "Vol_ZScore": 0.5,
            })
    return pd.DataFrame(rows).set_index("Date")


# ---------------------------------------------------------------------- #
# Change 1 — Foundry feature ingestion
# ---------------------------------------------------------------------- #


def test_foundry_features_appear_in_engineered_columns():
    """When ticker is supplied, compute_all_features adds at least 5
    Foundry_* columns (the calendar / event-driven features that don't
    require ticker price data still produce values for any synthetic
    ticker)."""
    fe = FeatureEngineer()
    result = fe.compute_all_features(
        _ohlc(),
        pd.DataFrame(),  # no fundamentals
        ticker="TEST_AAA",
    )
    foundry_cols = [c for c in result.columns if c.startswith("Foundry_")]
    assert len(foundry_cols) >= 5, (
        f"Expected at least 5 Foundry_* columns; got {len(foundry_cols)}: "
        f"{foundry_cols}"
    )
    # Ticker-independent calendar features should always populate
    # (don't depend on the local OHLCV CSV existing). Spot-check that
    # at least one calendar Foundry column has *non-NaN* values — the
    # fail-soft path should produce values where the data source is
    # actually available.
    calendar_cols = [
        c for c in foundry_cols
        if any(k in c for k in ("days_to_quarter_end", "month_of_year_dummy",
                                 "weekday_dummy"))
    ]
    assert calendar_cols, "expected at least one calendar Foundry column"
    populated = [c for c in calendar_cols if not result[c].isna().all()]
    assert populated, (
        f"calendar Foundry columns should have real values for any "
        f"synthetic ticker; all-NaN: {calendar_cols}"
    )


def test_foundry_missing_data_features_skipped_not_crashed():
    """Foundry features whose data source is unavailable (e.g. local
    OHLCV CSV missing for a synthetic ticker) must return None and
    produce NaN-filled columns — never crash compute_all_features."""
    fe = FeatureEngineer()
    # "TEST_NEVER_EXISTS" has no CSV in data/processed/, so every
    # local-OHLCV-backed Foundry feature (mom_12_1, beta_252d, etc.)
    # will return None. The call must complete without raising.
    result = fe.compute_all_features(
        _ohlc(periods=300),  # plenty of history
        pd.DataFrame(),
        ticker="TEST_NEVER_EXISTS",
    )
    foundry_cols = [c for c in result.columns if c.startswith("Foundry_")]
    # The price-data-dependent features should be present as columns
    # but all-NaN — verify at least one is exactly that shape.
    price_dep_cols = [
        c for c in foundry_cols
        if any(k in c for k in ("mom_12_1", "mom_6_1", "beta_252d",
                                 "realized_vol_60d"))
    ]
    assert price_dep_cols, "expected price-dependent Foundry cols to exist"
    all_nan = [c for c in price_dep_cols if result[c].isna().all()]
    assert all_nan, (
        f"price-dependent Foundry columns should be all-NaN for a "
        f"synthetic ticker with no local CSV; populated unexpectedly: "
        f"{[c for c in price_dep_cols if c not in all_nan]}"
    )


def test_foundry_skipped_when_ticker_not_provided():
    """Backward-compat: callers that don't pass ticker get the legacy
    behavior — no Foundry_* columns added."""
    fe = FeatureEngineer()
    result = fe.compute_all_features(_ohlc(), pd.DataFrame())
    foundry_cols = [c for c in result.columns if c.startswith("Foundry_")]
    assert not foundry_cols, (
        f"compute_all_features without ticker= must not add Foundry_* "
        f"columns; got {foundry_cols}"
    )


# ---------------------------------------------------------------------- #
# Change 2 — Fundamentals-percentile operators
# ---------------------------------------------------------------------- #


def test_fundamentals_percentile_rank_added_when_panel_present():
    """Cross-sectional rank columns appear for the V/Q/A factors that
    are present in the input frame; ranks are correct per date."""
    big_df = _stacked_with_fundamentals()
    result = FeatureEngineer.compute_cross_sectional_features(
        big_df, ticker_col="ticker"
    )

    # All three present-fundamentals columns should pick up a
    # percentile companion.
    expected = {
        "XS_ROE_Pctile",
        "XS_Gross_Profitability_Pctile",
        "XS_Sloan_Accruals_Pctile",
    }
    missing = expected - set(result.columns)
    assert not missing, f"missing percentile cols: {missing}"

    # Per-date ranks: BBB highest -> 1.0, AAA mid -> 0.6667, CCC low -> 0.3333.
    first_date = result.index[0]
    snapshot = result.loc[first_date].set_index("ticker")
    assert snapshot.loc["BBB", "XS_ROE_Pctile"] == pytest.approx(1.0)
    assert snapshot.loc["AAA", "XS_ROE_Pctile"] == pytest.approx(2 / 3)
    assert snapshot.loc["CCC", "XS_ROE_Pctile"] == pytest.approx(1 / 3)


def test_fundamentals_percentile_rank_skipped_when_panel_absent():
    """When no fundamentals columns are in the input, no XS_*_Pctile
    companions for fundamentals get inserted erroneously. Existing
    momentum / volume rank columns are unaffected."""
    big_df = _stacked_without_fundamentals()
    result = FeatureEngineer.compute_cross_sectional_features(
        big_df, ticker_col="ticker"
    )

    # No fundamentals input -> no fundamentals percentile columns.
    fund_xs_cols = [
        c for c in result.columns
        if c.startswith("XS_")
        and any(
            k in c
            for k in (
                "ROE", "Roe", "Gross_Profitability", "Sloan", "Asset_Growth",
                "PE_Ratio", "Book_To_", "Earnings_Yield",
            )
        )
    ]
    assert not fund_xs_cols, (
        f"fundamentals XS columns inserted on a panel that didn't ship "
        f"fundamentals: {fund_xs_cols}"
    )

    # Sanity: the existing volume-zscore percentile path still works
    # (Vol_ZScore is in the input frame).
    assert "XS_VolZ_Pctile" in result.columns


# ---------------------------------------------------------------------- #
# Determinism guard — existing technical features unchanged
# ---------------------------------------------------------------------- #


def test_existing_technical_features_still_present():
    """Sanity: every classical Engine D technical feature still
    computes after the Foundry pass is added. Catches accidental
    regression in the technical block ordering."""
    fe = FeatureEngineer()
    result = fe.compute_all_features(_ohlc(periods=300), pd.DataFrame())

    # Trend / momentum / volatility blocks
    expected = {
        "SMA_50", "SMA_200", "EMA_20", "Dist_SMA200",
        "Above_SMA200", "Golden_Cross",
        "RSI_14", "MACD", "MACD_Hist", "MACD_Signal", "ADX",
        "ATR_Pct", "BB_Width", "BB_Squeeze", "Vol_ZScore",
    }
    missing = expected - set(result.columns)
    assert not missing, f"technical features regressed after Foundry add: {missing}"

    # Calendar block (existing — not the new Foundry calendar features)
    assert "DOW_Sin" in result.columns
    assert "DOW_Cos" in result.columns
    assert "QEnd_Proximity" in result.columns

    # Microstructure block
    assert "Overnight_Gap" in result.columns
    assert "Intraday_Range" in result.columns
    assert "Close_Location" in result.columns
