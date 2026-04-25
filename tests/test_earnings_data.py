"""Tests for engines.data_manager.earnings_data.

All tests run offline by mocking the Finnhub HTTP layer. There is one
integration-style test at the bottom gated behind ``FINNHUB_API_KEY`` —
skipped by default so CI / fresh clones never hit the live API.
"""
import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import requests

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


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _ok(observations):
    return _FakeResponse(200, {"earningsCalendar": observations})


@pytest.fixture
def mgr(tmp_path):
    """Manager isolated to a tmp cache dir, stub key, no rate limiting."""
    return EarningsDataManager(
        api_key="fake-key",
        cache_dir=tmp_path,
        rate_limit_s=0,
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
    # Some Finnhub rows have null/missing 'symbol'; fall back to caller arg
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
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)) as mock_get:
        df = mgr.fetch_calendar("AAPL", start="2020-01-01")

    mock_get.assert_called_once()
    assert (tmp_path / "AAPL_calendar.parquet").exists()
    assert (tmp_path / "_meta.json").exists()
    meta = json.loads((tmp_path / "_meta.json").read_text())
    assert meta["AAPL"]["n_rows"] == 3
    assert df.equals(pd.read_parquet(tmp_path / "AAPL_calendar.parquet"))


def test_fetch_normalizes_lowercase_symbol(mgr, tmp_path):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)):
        mgr.fetch_calendar("aapl")
    # Cache file should be uppercase regardless of caller casing
    assert (tmp_path / "AAPL_calendar.parquet").exists()


def test_cache_short_circuits_inside_max_age(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)) as mock_get:
        mgr.fetch_calendar("AAPL")
        assert mock_get.call_count == 1
        # second call within max_age — should NOT hit network
        mgr.fetch_calendar("AAPL")
        assert mock_get.call_count == 1


def test_force_bypasses_cache(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)) as mock_get:
        mgr.fetch_calendar("AAPL")
        mgr.fetch_calendar("AAPL", force=True)
    assert mock_get.call_count == 2


def test_max_age_zero_always_refetches(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)) as mock_get:
        mgr.fetch_calendar("AAPL")
        mgr.fetch_calendar("AAPL", max_age_hours=0)
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Error handling / graceful degradation
# ---------------------------------------------------------------------------
def test_network_failure_serves_cache(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)):
        mgr.fetch_calendar("AAPL")
    # Now simulate the network going down on a forced refresh
    with patch("engines.data_manager.earnings_data.requests.get",
               side_effect=requests.ConnectionError("offline")):
        df = mgr.fetch_calendar("AAPL", force=True)
    assert len(df) == 3  # cached data


def test_network_failure_without_cache_raises(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               side_effect=requests.ConnectionError("offline")):
        with pytest.raises(EarningsDataError):
            mgr.fetch_calendar("AAPL")


def test_http_error_raises_when_no_cache(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_FakeResponse(429, {"error": "rate limit"})):
        with pytest.raises(EarningsDataError):
            mgr.fetch_calendar("AAPL")


def test_no_api_key_uses_cache_only(tmp_path):
    keyed = EarningsDataManager(
        api_key="fake-key", cache_dir=tmp_path, rate_limit_s=0,
    )
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)):
        keyed.fetch_calendar("AAPL")

    keyless = EarningsDataManager(
        api_key=None, cache_dir=tmp_path, rate_limit_s=0,
    )
    with patch("engines.data_manager.earnings_data.requests.get") as mock_get:
        df = keyless.fetch_calendar("AAPL", force=True)
        mock_get.assert_not_called()
    assert len(df) == 3


def test_no_api_key_no_cache_raises(tmp_path):
    keyless = EarningsDataManager(
        api_key=None, cache_dir=tmp_path, rate_limit_s=0,
    )
    with pytest.raises(EarningsDataError):
        keyless.fetch_calendar("AAPL")


def test_load_cached_when_missing_returns_empty(mgr):
    df = mgr.load_cached("NEVER_FETCHED")
    assert df.empty
    assert list(df.columns) == EVENT_COLUMNS


def test_empty_earnings_calendar_field_is_treated_as_no_events(mgr, tmp_path):
    # Finnhub returns null `earningsCalendar` for symbols with no events
    # in the queried window. That should be a zero-row frame, not an error.
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_FakeResponse(200, {"earningsCalendar": None})):
        df = mgr.fetch_calendar("ZZZZ")
    assert df.empty
    assert (tmp_path / "ZZZZ_calendar.parquet").exists()


def test_response_missing_calendar_field_raises(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_FakeResponse(200, {"unexpected": "shape"})):
        with pytest.raises(EarningsDataError):
            mgr.fetch_calendar("AAPL")


# ---------------------------------------------------------------------------
# Universe fetch
# ---------------------------------------------------------------------------
def test_universe_concatenates_per_symbol_frames(mgr):
    def fake_get(url, params=None, timeout=None):
        sym = params["symbol"]
        if sym == "AAPL":
            return _ok(SAMPLE_AAPL_CALENDAR)
        if sym == "MSFT":
            return _ok(SAMPLE_MSFT_CALENDAR)
        return _ok([])

    with patch("engines.data_manager.earnings_data.requests.get",
               side_effect=fake_get):
        combined = mgr.fetch_universe(["AAPL", "MSFT"])

    assert set(combined["symbol"].unique()) == {"AAPL", "MSFT"}
    assert len(combined) == 4  # 3 AAPL + 1 MSFT
    assert combined.index.is_monotonic_increasing


def test_universe_skips_failed_symbols(mgr):
    def fake_get(url, params=None, timeout=None):
        sym = params["symbol"]
        if sym == "AAPL":
            return _ok(SAMPLE_AAPL_CALENDAR)
        return _FakeResponse(500, {"error": "boom"})

    with patch("engines.data_manager.earnings_data.requests.get",
               side_effect=fake_get):
        combined = mgr.fetch_universe(["AAPL", "BROKE"])

    assert set(combined["symbol"].unique()) == {"AAPL"}


def test_universe_all_failures_raises(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_FakeResponse(500, {"error": "boom"})):
        with pytest.raises(EarningsDataError):
            mgr.fetch_universe(["AAPL", "MSFT"])


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------
def test_cache_status_reports_state(mgr):
    with patch("engines.data_manager.earnings_data.requests.get",
               return_value=_ok(SAMPLE_AAPL_CALENDAR)):
        mgr.fetch_calendar("AAPL")
    status = mgr.cache_status()
    assert "AAPL" in status["symbol"].values
    aapl_row = status[status["symbol"] == "AAPL"].iloc[0]
    assert bool(aapl_row["cached"]) is True
    assert aapl_row["n_rows"] == 3


def test_cache_status_empty_when_nothing_fetched(tmp_path):
    mgr = EarningsDataManager(
        api_key=None, cache_dir=tmp_path, rate_limit_s=0,
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
# Integration (live network) — skipped unless FINNHUB_API_KEY is set.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.getenv("FINNHUB_API_KEY"),
    reason="Live Finnhub API key not set; set FINNHUB_API_KEY in .env to enable.",
)
def test_live_finnhub_aapl_fetch(tmp_path):
    mgr = EarningsDataManager(cache_dir=tmp_path)
    df = mgr.fetch_calendar("AAPL", start="2023-01-01", end="2023-12-31")
    assert not df.empty
    assert list(df.columns) == EVENT_COLUMNS
    # AAPL reports four times a year — expect at least one print in 2023
    assert (df.index >= pd.Timestamp("2023-01-01")).all()
    assert (df.index <= pd.Timestamp("2023-12-31")).all()
    assert (df["symbol"] == "AAPL").all()
