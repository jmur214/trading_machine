"""Tests for engines.data_manager.macro_data.

All tests run offline by mocking the FRED HTTP layer. There is one
integration-style test at the bottom gated behind ``FRED_API_KEY`` —
skipped by default.
"""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.data_manager.macro_data import (
    DEFAULT_CACHE_DIR,
    MACRO_SERIES,
    MacroDataError,
    MacroDataManager,
    _observations_to_frame,
    credit_quality_slope,
    list_series,
    real_fed_funds,
    yoy_change,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SAMPLE_OBSERVATIONS_DGS10 = [
    {"date": "2024-01-02", "value": "3.95"},
    {"date": "2024-01-03", "value": "3.91"},
    {"date": "2024-01-04", "value": "."},   # FRED missing-data sentinel
    {"date": "2024-01-05", "value": "4.05"},
]

SAMPLE_OBSERVATIONS_UNRATE = [
    {"date": "2024-01-01", "value": "3.7"},
    {"date": "2024-02-01", "value": "3.9"},
    {"date": "2024-03-01", "value": "3.8"},
]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _ok(observations):
    return _FakeResponse(200, {"observations": observations})


@pytest.fixture
def mgr(tmp_path):
    """Manager isolated to a tmp cache directory with a stub API key."""
    return MacroDataManager(api_key="fake-key", cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registry_is_well_formed():
    assert len(MACRO_SERIES) >= 10
    for sid, meta in MACRO_SERIES.items():
        assert sid == meta.series_id
        assert meta.category in {
            "yield_curve", "credit", "policy", "inflation",
            "labor", "growth", "fx", "vol", "liquidity",
        }
        assert meta.frequency in {"daily", "weekly", "monthly"}


def test_list_series_filter():
    yc = list_series(category="yield_curve")
    assert all(s.category == "yield_curve" for s in yc)
    assert {"DGS10", "DGS2"}.issubset({s.series_id for s in yc})


# ---------------------------------------------------------------------------
# Observation parsing
# ---------------------------------------------------------------------------
def test_observations_parse_handles_missing_sentinel():
    df = _observations_to_frame(SAMPLE_OBSERVATIONS_DGS10)
    assert list(df.columns) == ["value"]
    assert len(df) == 4
    assert df["value"].isna().sum() == 1
    assert df.index.is_monotonic_increasing
    assert df.loc["2024-01-02", "value"] == pytest.approx(3.95)


def test_observations_parse_empty():
    df = _observations_to_frame([])
    assert df.empty
    assert list(df.columns) == ["value"]


def test_observations_parse_rejects_unexpected_schema():
    with pytest.raises(MacroDataError):
        _observations_to_frame([{"foo": "bar"}])


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------
def test_fetch_writes_parquet_and_meta(mgr, tmp_path):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)) as mock_get:
        df = mgr.fetch_series("DGS10", start="2024-01-01")

    mock_get.assert_called_once()
    assert (tmp_path / "DGS10.parquet").exists()
    assert (tmp_path / "_meta.json").exists()
    meta = json.loads((tmp_path / "_meta.json").read_text())
    assert meta["DGS10"]["n_rows"] == 4
    assert df.equals(pd.read_parquet(tmp_path / "DGS10.parquet"))


def test_cache_short_circuits_inside_max_age(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)) as mock_get:
        mgr.fetch_series("DGS10")
        assert mock_get.call_count == 1
        # second call within max_age — should NOT hit network
        mgr.fetch_series("DGS10")
        assert mock_get.call_count == 1


def test_force_bypasses_cache(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)) as mock_get:
        mgr.fetch_series("DGS10")
        mgr.fetch_series("DGS10", force=True)
    assert mock_get.call_count == 2


def test_max_age_zero_always_refetches(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)) as mock_get:
        mgr.fetch_series("DGS10")
        mgr.fetch_series("DGS10", max_age_hours=0)
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Error handling / graceful degradation
# ---------------------------------------------------------------------------
def test_network_failure_serves_cache(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)):
        mgr.fetch_series("DGS10")
    # Now simulate the network going down on a forced refresh
    with patch("engines.data_manager.macro_data.requests.get",
               side_effect=requests.ConnectionError("offline")):
        df = mgr.fetch_series("DGS10", force=True)
    assert len(df) == 4  # still got cached data


def test_network_failure_without_cache_raises(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               side_effect=requests.ConnectionError("offline")):
        with pytest.raises(MacroDataError):
            mgr.fetch_series("DGS10")


def test_http_error_raises_macro_error_when_no_cache(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_FakeResponse(429, {"error": "rate limit"})):
        with pytest.raises(MacroDataError):
            mgr.fetch_series("DGS10")


def test_no_api_key_uses_cache_only(tmp_path):
    # Pre-populate cache via a keyed manager
    keyed = MacroDataManager(api_key="fake-key", cache_dir=tmp_path)
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)):
        keyed.fetch_series("DGS10")

    # Now use a keyless manager pointed at the same cache
    keyless = MacroDataManager(api_key=None, cache_dir=tmp_path)
    with patch("engines.data_manager.macro_data.requests.get") as mock_get:
        df = keyless.fetch_series("DGS10", force=True)
        mock_get.assert_not_called()
    assert len(df) == 4


def test_no_api_key_no_cache_raises(tmp_path):
    keyless = MacroDataManager(api_key=None, cache_dir=tmp_path)
    with pytest.raises(MacroDataError):
        keyless.fetch_series("DGS10")


def test_load_cached_when_missing_returns_empty(mgr):
    df = mgr.load_cached("NEVER_FETCHED")
    assert df.empty
    assert list(df.columns) == ["value"]


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------
def test_panel_join_and_ffill(mgr):
    def fake_get(url, params=None, timeout=None):
        sid = params["series_id"]
        if sid == "DGS10":
            return _ok(SAMPLE_OBSERVATIONS_DGS10)
        if sid == "UNRATE":
            return _ok(SAMPLE_OBSERVATIONS_UNRATE)
        return _ok([])

    with patch("engines.data_manager.macro_data.requests.get", side_effect=fake_get):
        panel = mgr.fetch_panel(series_ids=["DGS10", "UNRATE"], ffill=True)

    assert set(panel.columns) == {"DGS10", "UNRATE"}
    # ffill should have populated UNRATE on the daily index from Jan-Feb-Mar
    # at least for dates that exist in the union
    assert panel.index.is_monotonic_increasing
    assert panel.index.freq is not None or panel.index.inferred_freq == "D" \
        or (panel.index[1] - panel.index[0]).days == 1
    # UNRATE Feb print should propagate forward through Feb until the Mar print
    feb_15 = pd.Timestamp("2024-02-15")
    if feb_15 in panel.index:
        assert panel.loc[feb_15, "UNRATE"] == pytest.approx(3.9)


def test_panel_skips_failed_series(mgr):
    def fake_get(url, params=None, timeout=None):
        sid = params["series_id"]
        if sid == "DGS10":
            return _ok(SAMPLE_OBSERVATIONS_DGS10)
        return _FakeResponse(500, {"error": "boom"})

    with patch("engines.data_manager.macro_data.requests.get", side_effect=fake_get):
        panel = mgr.fetch_panel(series_ids=["DGS10", "UNRATE"], ffill=False)
    assert "DGS10" in panel.columns
    assert "UNRATE" not in panel.columns


def test_panel_all_failures_raises(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_FakeResponse(500, {"error": "boom"})):
        with pytest.raises(MacroDataError):
            mgr.fetch_panel(series_ids=["DGS10", "UNRATE"])


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------
def test_cache_status_reports_state(mgr):
    with patch("engines.data_manager.macro_data.requests.get",
               return_value=_ok(SAMPLE_OBSERVATIONS_DGS10)):
        mgr.fetch_series("DGS10")
    status = mgr.cache_status()
    assert "DGS10" in status["series_id"].values
    dgs10_row = status[status["series_id"] == "DGS10"].iloc[0]
    assert dgs10_row["cached"] is True or dgs10_row["cached"] == True  # noqa: E712
    assert dgs10_row["n_rows"] == 4


# ---------------------------------------------------------------------------
# Derived transforms
# ---------------------------------------------------------------------------
def test_yoy_change_basic():
    s = pd.Series([100.0, 101, 102, 103, 105, 107, 109, 110, 111, 112, 113, 114, 120])
    out = yoy_change(s, periods=12)
    # Last value: (120 - 100) / 100 = 0.20
    assert out.iloc[-1] == pytest.approx(0.20)
    assert pd.isna(out.iloc[0])


def test_credit_quality_slope():
    panel = pd.DataFrame({
        "BAMLH0A0HYM2": [4.5, 5.0, 6.0],
        "BAMLC0A0CM": [1.2, 1.3, 1.5],
    })
    slope = credit_quality_slope(panel)
    assert slope.tolist() == pytest.approx([3.3, 3.7, 4.5])


def test_real_fed_funds():
    panel = pd.DataFrame({"DFF": [5.25, 5.50], "T10YIE": [2.30, 2.40]})
    real = real_fed_funds(panel)
    assert real.tolist() == pytest.approx([2.95, 3.10])


# ---------------------------------------------------------------------------
# Default cache directory
# ---------------------------------------------------------------------------
def test_default_cache_dir_under_repo_root():
    """Sanity: default cache lives under data/macro/, not somewhere wild."""
    assert DEFAULT_CACHE_DIR.parts[-2:] == ("data", "macro")


# ---------------------------------------------------------------------------
# Integration (live network) — skipped unless FRED_API_KEY is set.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.getenv("FRED_API_KEY"),
    reason="Live FRED API key not set; set FRED_API_KEY in .env to enable.",
)
def test_live_fred_dgs10_fetch(tmp_path):
    mgr = MacroDataManager(cache_dir=tmp_path)
    df = mgr.fetch_series("DGS10", start="2024-01-01", end="2024-01-31")
    assert not df.empty
    assert "value" in df.columns
    assert df.index.min() >= pd.Timestamp("2024-01-01")
