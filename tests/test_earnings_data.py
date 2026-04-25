"""Tests for engines.data_manager.earnings_data.

All tests run offline by mocking the yfinance backend. There is one
integration-style test at the bottom gated behind ``--run-network`` —
skipped by default so CI / fresh clones never hit the live network.
"""
import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.data_manager.earnings_data import (
    DEFAULT_CACHE_DIR,
    EVENT_COLUMNS,
    EarningsDataError,
    EarningsDataManager,
    _observations_to_frame,
    surprise_pct,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Observation-shape dicts (the same shape produced by both the
# yfinance adapter and the legacy Finnhub adapter — we keep this
# shape because `_observations_to_frame` consumes it directly).
SAMPLE_AAPL_CALENDAR = [
    {
        "date": "2020-04-30",
        "epsActual": 2.55,
        "epsEstimate": 2.26,
        "hour": "amc",
        "quarter": 2,
        "revenueActual": 58313000000,
        "revenueEstimate": 54540000000,
        "symbol": "AAPL",
        "year": 2020,
    },
    {
        "date": "2020-07-30",
        "epsActual": 2.58,
        "epsEstimate": 2.04,
        "hour": "amc",
        "quarter": 3,
        "revenueActual": 59685000000,
        "revenueEstimate": 52250000000,
        "symbol": "AAPL",
        "year": 2020,
    },
    # A miss with a sentinel revenue null and missing hour
    {
        "date": "2024-01-25",
        "epsActual": 2.18,
        "epsEstimate": 2.10,
        "hour": "",
        "quarter": 4,
        "revenueActual": None,
        "revenueEstimate": 117910000000,
        "symbol": "AAPL",
        "year": 2023,
    },
]

SAMPLE_MSFT_CALENDAR = [
    {
        "date": "2024-01-30",
        "epsActual": 2.93,
        "epsEstimate": 2.78,
        "hour": "amc",
        "quarter": 2,
        "revenueActual": 62020000000,
        "revenueEstimate": 61124000000,
        "symbol": "MSFT",
        "year": 2024,
    },
]


def _patch_yf(observations_or_fn):
    """Patch the yfinance adapter. Accepts a list (returned for any
    symbol) or a callable that takes ``symbol`` and returns a list."""
    if callable(observations_or_fn):
        return patch(
            "engines.data_manager.earnings_data._fetch_yfinance_earnings",
            side_effect=observations_or_fn,
        )
    return patch(
        "engines.data_manager.earnings_data._fetch_yfinance_earnings",
        return_value=observations_or_fn,
    )


@pytest.fixture
def mgr(tmp_path):
    """Manager isolated to a tmp cache dir, online, no rate limiting."""
    return EarningsDataManager(
        cache_dir=tmp_path,
        rate_limit_s=0,
        offline=False,
    )


# ---------------------------------------------------------------------------
# surprise_pct helper
# ---------------------------------------------------------------------------
def test_surprise_pct_basic_beat():
    assert surprise_pct(2.55, 2.26) == pytest.approx((2.55 - 2.26) / 2.26)


def test_surprise_pct_miss():
    # Miss should be negative.
    assert surprise_pct(1.50, 2.00) == pytest.approx(-0.25)


def test_surprise_pct_zero_estimate_is_nan():
    assert math.isnan(surprise_pct(0.5, 0.0))


def test_surprise_pct_none_inputs_are_nan():
    assert math.isnan(surprise_pct(None, 1.0))
    assert math.isnan(surprise_pct(1.0, None))
    assert math.isnan(surprise_pct(None, None))


def test_surprise_pct_negative_estimate_uses_absolute_denominator():
    # Streetlight test — analysts expected a $-0.50 loss; company posted
    # a $-0.30 loss. Beat by $0.20 on a $0.50 base = +40%, not -40%.
    assert surprise_pct(-0.30, -0.50) == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# Observation parsing
# ---------------------------------------------------------------------------
def test_observations_parse_basic():
    df = _observations_to_frame(SAMPLE_AAPL_CALENDAR, symbol="AAPL")
    assert list(df.columns) == EVENT_COLUMNS
    assert len(df) == 3
    assert df.index.is_monotonic_increasing
    assert df.iloc[0]["eps_actual"] == pytest.approx(2.55)
    assert df.iloc[0]["eps_surprise"] == pytest.approx(2.55 - 2.26)
    assert df.iloc[0]["eps_surprise_pct"] == pytest.approx((2.55 - 2.26) / 2.26)
    # Revenue surprise on the third row (None actual) → NaN
    assert math.isnan(df.iloc[2]["revenue_actual"])
    assert math.isnan(df.iloc[2]["revenue_surprise"])
    assert math.isnan(df.iloc[2]["revenue_surprise_pct"])


def test_observations_parse_empty():
    df = _observations_to_frame([], symbol="AAPL")
    assert df.empty
    assert list(df.columns) == EVENT_COLUMNS
    assert df.index.name == "announcement_date"


def test_observations_parse_drops_rows_with_unparseable_date():
    obs = [
        {"date": "not-a-date", "epsActual": 1.0, "epsEstimate": 0.9, "symbol": "X"},
        {"date": "2024-01-01", "epsActual": 1.0, "epsEstimate": 0.9, "symbol": "X"},
    ]
    df = _observations_to_frame(obs, symbol="X")
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-01")


def test_observations_parse_falls_back_to_argument_symbol():
    # Some upstream rows have null/missing 'symbol'; fall back to caller arg
    obs = [{"date": "2024-01-01", "epsActual": 1.0, "epsEstimate": 0.9}]
    df = _observations_to_frame(obs, symbol="aapl")
    assert df.iloc[0]["symbol"] == "AAPL"


def test_observations_parse_nullable_quarter_year():
    obs = [{"date": "2024-01-01", "epsActual": 1.0, "epsEstimate": 0.9,
            "quarter": None, "year": None, "symbol": "X"}]
    df = _observations_to_frame(obs, symbol="X")
    assert pd.isna(df.iloc[0]["quarter"])
    assert pd.isna(df.iloc[0]["year"])
    assert str(df["quarter"].dtype) == "Int64"


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------
def test_fetch_writes_parquet_and_meta(mgr, tmp_path):
    with _patch_yf(SAMPLE_AAPL_CALENDAR) as mock_yf:
        df = mgr.fetch_calendar("AAPL", start="2020-01-01")

    mock_yf.assert_called_once()
    assert (tmp_path / "AAPL_calendar.parquet").exists()
    assert (tmp_path / "_meta.json").exists()
    meta = json.loads((tmp_path / "_meta.json").read_text())
    assert meta["AAPL"]["n_rows"] == 3
    assert df.equals(pd.read_parquet(tmp_path / "AAPL_calendar.parquet"))


def test_fetch_normalizes_lowercase_symbol(mgr, tmp_path):
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        mgr.fetch_calendar("aapl")
    # Cache file should be uppercase regardless of caller casing
    assert (tmp_path / "AAPL_calendar.parquet").exists()


def test_cache_short_circuits_inside_max_age(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR) as mock_yf:
        mgr.fetch_calendar("AAPL")
        assert mock_yf.call_count == 1
        # second call within max_age — should NOT hit network
        mgr.fetch_calendar("AAPL")
        assert mock_yf.call_count == 1


def test_force_bypasses_cache(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR) as mock_yf:
        mgr.fetch_calendar("AAPL")
        mgr.fetch_calendar("AAPL", force=True)
    assert mock_yf.call_count == 2


def test_max_age_zero_always_refetches(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR) as mock_yf:
        mgr.fetch_calendar("AAPL")
        mgr.fetch_calendar("AAPL", max_age_hours=0)
    assert mock_yf.call_count == 2


def test_start_date_filters_observations(mgr):
    # SAMPLE_AAPL_CALENDAR spans 2020-04 → 2024-01. A start filter
    # of 2024-01-01 should keep only the 2024 row.
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        df = mgr.fetch_calendar("AAPL", start="2024-01-01")
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-25")


def test_end_date_filters_observations(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        df = mgr.fetch_calendar("AAPL", start="2020-01-01", end="2021-01-01")
    assert len(df) == 2
    assert df.index.max() == pd.Timestamp("2020-07-30")


# ---------------------------------------------------------------------------
# Error handling / graceful degradation
# ---------------------------------------------------------------------------
def test_network_failure_serves_cache(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        mgr.fetch_calendar("AAPL")
    # Now simulate yfinance failing on a forced refresh
    with patch(
        "engines.data_manager.earnings_data._fetch_yfinance_earnings",
        side_effect=EarningsDataError("yfinance offline"),
    ):
        df = mgr.fetch_calendar("AAPL", force=True)
    assert len(df) == 3  # cached data


def test_network_failure_without_cache_raises(mgr):
    with patch(
        "engines.data_manager.earnings_data._fetch_yfinance_earnings",
        side_effect=EarningsDataError("yfinance offline"),
    ):
        with pytest.raises(EarningsDataError):
            mgr.fetch_calendar("AAPL")


def test_offline_mode_uses_cache_only(tmp_path):
    """offline=True (default when api_key=None) skips network even
    when a fetch is requested. Mirrors the prior keyless contract."""
    online = EarningsDataManager(
        cache_dir=tmp_path, rate_limit_s=0, offline=False,
    )
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        online.fetch_calendar("AAPL")

    offline_mgr = EarningsDataManager(
        cache_dir=tmp_path, rate_limit_s=0, offline=True,
    )
    with _patch_yf(SAMPLE_AAPL_CALENDAR) as mock_yf:
        df = offline_mgr.fetch_calendar("AAPL", force=True)
        mock_yf.assert_not_called()
    assert len(df) == 3


def test_offline_mode_no_cache_raises(tmp_path):
    offline_mgr = EarningsDataManager(
        cache_dir=tmp_path, rate_limit_s=0, offline=True,
    )
    with pytest.raises(EarningsDataError):
        offline_mgr.fetch_calendar("AAPL")


def test_load_cached_when_missing_returns_empty(mgr):
    df = mgr.load_cached("NEVER_FETCHED")
    assert df.empty
    assert list(df.columns) == EVENT_COLUMNS


def test_empty_observations_caches_empty_frame(mgr, tmp_path):
    # yfinance returns no events for a delisted/illiquid symbol —
    # that should be a zero-row frame on disk, not an error.
    with _patch_yf([]):
        df = mgr.fetch_calendar("ZZZZ")
    assert df.empty
    assert (tmp_path / "ZZZZ_calendar.parquet").exists()


# ---------------------------------------------------------------------------
# Universe fetch
# ---------------------------------------------------------------------------
def test_universe_concatenates_per_symbol_frames(mgr):
    def fake_fetch(symbol):
        if symbol == "AAPL":
            return SAMPLE_AAPL_CALENDAR
        if symbol == "MSFT":
            return SAMPLE_MSFT_CALENDAR
        return []

    with _patch_yf(fake_fetch):
        combined = mgr.fetch_universe(["AAPL", "MSFT"])

    assert set(combined["symbol"].unique()) == {"AAPL", "MSFT"}
    assert len(combined) == 4  # 3 AAPL + 1 MSFT
    assert combined.index.is_monotonic_increasing


def test_universe_skips_failed_symbols(mgr):
    def fake_fetch(symbol):
        if symbol == "AAPL":
            return SAMPLE_AAPL_CALENDAR
        raise EarningsDataError(f"yfinance boom on {symbol}")

    with _patch_yf(fake_fetch):
        combined = mgr.fetch_universe(["AAPL", "BROKE"])

    assert set(combined["symbol"].unique()) == {"AAPL"}


def test_universe_all_failures_raises(mgr):
    with patch(
        "engines.data_manager.earnings_data._fetch_yfinance_earnings",
        side_effect=EarningsDataError("boom"),
    ):
        with pytest.raises(EarningsDataError):
            mgr.fetch_universe(["AAPL", "MSFT"])


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------
def test_cache_status_reports_state(mgr):
    with _patch_yf(SAMPLE_AAPL_CALENDAR):
        mgr.fetch_calendar("AAPL")
    status = mgr.cache_status()
    assert "AAPL" in status["symbol"].values
    aapl_row = status[status["symbol"] == "AAPL"].iloc[0]
    assert bool(aapl_row["cached"]) is True
    assert aapl_row["n_rows"] == 3


def test_cache_status_empty_when_nothing_fetched(tmp_path):
    mgr = EarningsDataManager(
        cache_dir=tmp_path, rate_limit_s=0, offline=True,
    )
    status = mgr.cache_status()
    assert status.empty
    assert list(status.columns) == [
        "symbol", "cached", "age_hours", "n_rows", "last_fetched_utc",
    ]


# ---------------------------------------------------------------------------
# Default cache directory
# ---------------------------------------------------------------------------
def test_default_cache_dir_under_repo_root():
    """Sanity: default cache lives under data/earnings/, not somewhere wild."""
    assert DEFAULT_CACHE_DIR.parts[-2:] == ("data", "earnings")


# ---------------------------------------------------------------------------
# Integration (live network) — skipped unless ARCHONDEX_TEST_NETWORK is set.
# yfinance has no key, so we gate on an explicit opt-in env var.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.getenv("ARCHONDEX_TEST_NETWORK"),
    reason="Live yfinance fetch skipped; set ARCHONDEX_TEST_NETWORK=1 to enable.",
)
def test_live_yfinance_aapl_fetch(tmp_path):
    mgr = EarningsDataManager(cache_dir=tmp_path, offline=False)
    df = mgr.fetch_calendar("AAPL", start="2023-01-01", end="2023-12-31")
    assert not df.empty
    assert list(df.columns) == EVENT_COLUMNS
    assert (df.index >= pd.Timestamp("2023-01-01")).all()
    assert (df.index <= pd.Timestamp("2023-12-31")).all()
    assert (df["symbol"] == "AAPL").all()
