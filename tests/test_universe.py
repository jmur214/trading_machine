"""Tests for engines.data_manager.universe and scripts.fetch_universe.

All tests run offline. Wikipedia HTTP layer is mocked; the membership
parser is exercised against fixture HTML inline in this file.

There is one integration-style test at the bottom that hits live
Wikipedia, gated on env var ``UNIVERSE_LIVE_TEST=1`` so CI / fresh
clones never make network calls by default.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.data_manager.universe import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    MEMBERSHIP_COLUMNS,
    SP500MembershipLoader,
    UniverseError,
    active_at,
    current_tickers,
    normalize_ticker,
    parse_membership_html,
    _build_membership,
    _parse_changes_table,
    _parse_current_table,
)
from bs4 import BeautifulSoup  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture HTML — minimal but structurally faithful to the live Wikipedia page.
# ---------------------------------------------------------------------------
SAMPLE_HTML = """
<html>
<body>
<table id="constituents" class="wikitable sortable">
  <tr>
    <th>Symbol</th>
    <th>Security</th>
    <th>GICS Sector</th>
    <th>GICS Sub-Industry</th>
    <th>Headquarters Location</th>
    <th>Date added</th>
    <th>CIK</th>
    <th>Founded</th>
  </tr>
  <tr>
    <td><a>AAPL</a></td>
    <td><a>Apple Inc.</a></td>
    <td>Information Technology</td>
    <td>Technology Hardware, Storage &amp; Peripherals</td>
    <td>Cupertino, California</td>
    <td>1982-11-30</td>
    <td>0000320193</td>
    <td>1977</td>
  </tr>
  <tr>
    <td><a>MSFT</a></td>
    <td><a>Microsoft</a></td>
    <td>Information Technology</td>
    <td>Systems Software</td>
    <td>Redmond, Washington</td>
    <td>1994-06-01</td>
    <td>0000789019</td>
    <td>1975</td>
  </tr>
  <tr>
    <td><a>NVDA</a></td>
    <td><a>Nvidia</a></td>
    <td>Information Technology</td>
    <td>Semiconductors</td>
    <td>Santa Clara, California</td>
    <td>2001-11-30</td>
    <td>0001045810</td>
    <td>1993</td>
  </tr>
  <tr>
    <td><a>NEW1</a></td>
    <td><a>Newly Added Co</a></td>
    <td>Industrials</td>
    <td>Industrial Conglomerates</td>
    <td>Anywhere</td>
    <td>2024-01-15</td>
    <td>0000000001</td>
    <td>2010</td>
  </tr>
</table>

<h2>Selected changes to the list of S&amp;P 500 components</h2>
<table id="changes" class="wikitable">
  <tr>
    <th rowspan="2">Date</th>
    <th colspan="2">Added</th>
    <th colspan="2">Removed</th>
    <th rowspan="2">Reason</th>
  </tr>
  <tr>
    <th>Ticker</th><th>Security</th>
    <th>Ticker</th><th>Security</th>
  </tr>
  <tr>
    <td>2024-01-15</td>
    <td>NEW1</td><td>Newly Added Co</td>
    <td>OLD1</td><td>Removed Co</td>
    <td>Reorganization</td>
  </tr>
  <tr>
    <td>2020-06-01</td>
    <td></td><td></td>
    <td>OLD2</td><td>Solo Removal</td>
    <td>M&amp;A</td>
  </tr>
  <tr>
    <td>2010-03-22</td>
    <td>OLD2</td><td>Solo Removal</td>
    <td></td><td></td>
    <td>Index addition</td>
  </tr>
</table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_normalize_ticker_strips_footnotes_and_uppercases():
    assert normalize_ticker(" aapl[1] ") == "AAPL"
    assert normalize_ticker("brk.b") == "BRK.B"


def test_normalize_ticker_handles_none_and_empty():
    assert normalize_ticker(None) == ""
    assert normalize_ticker("") == ""
    assert normalize_ticker("[note]") == ""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def test_parse_current_table_pulls_expected_rows():
    soup = BeautifulSoup(SAMPLE_HTML, "lxml")
    df = _parse_current_table(soup)
    assert set(df["ticker"]) == {"AAPL", "MSFT", "NVDA", "NEW1"}
    aapl = df.loc[df["ticker"] == "AAPL"].iloc[0]
    assert aapl["name"] == "Apple Inc."
    assert aapl["sector"] == "Information Technology"
    assert aapl["date_added"] == pd.Timestamp("1982-11-30")


def test_parse_changes_table_yields_added_and_removed_events():
    soup = BeautifulSoup(SAMPLE_HTML, "lxml")
    events = _parse_changes_table(soup)
    # 2024-01-15 has both add (NEW1) and remove (OLD1) → 2 events
    # 2020-06-01 has only remove (OLD2) → 1 event
    # 2010-03-22 has only add (OLD2) → 1 event
    assert len(events) == 4
    by_action = {(e["ticker"], e["action"], e["date"].isoformat()[:10]) for e in events}
    assert ("NEW1", "added", "2024-01-15") in by_action
    assert ("OLD1", "removed", "2024-01-15") in by_action
    assert ("OLD2", "removed", "2020-06-01") in by_action
    assert ("OLD2", "added", "2010-03-22") in by_action


def test_parse_membership_html_end_to_end_columns_and_dtypes():
    df = parse_membership_html(SAMPLE_HTML)
    assert list(df.columns) == MEMBERSHIP_COLUMNS
    assert df["included_from"].dtype.kind == "M"
    assert df["included_until"].dtype.kind == "M"
    assert not df.empty


def test_parse_membership_html_currently_active_have_open_spell():
    df = parse_membership_html(SAMPLE_HTML)
    # All four current-table tickers should have at least one row with
    # included_until = NaT (i.e., they're currently in the index).
    open_spells = df[df["included_until"].isna()]
    assert set(open_spells["ticker"]) >= {"AAPL", "MSFT", "NVDA", "NEW1"}


def test_parse_membership_html_old1_is_closed_spell_only():
    """OLD1 was removed but never re-added → must not have an open spell."""
    df = parse_membership_html(SAMPLE_HTML)
    old1_rows = df[df["ticker"] == "OLD1"]
    assert len(old1_rows) >= 1
    assert old1_rows["included_until"].notna().all()


def test_parse_membership_html_old2_has_one_closed_spell_2010_to_2020():
    """OLD2 was added in 2010 and removed in 2020. Should produce one
    spell with both ends populated, no open trailing spell."""
    df = parse_membership_html(SAMPLE_HTML)
    rows = df[df["ticker"] == "OLD2"].sort_values("included_from")
    assert len(rows) == 1
    spell = rows.iloc[0]
    assert spell["included_from"] == pd.Timestamp("2010-03-22")
    assert spell["included_until"] == pd.Timestamp("2020-06-01")


def test_parse_membership_html_aapl_has_no_change_log_entry_uses_current_date():
    """AAPL isn't in our fixture's changes table at all. The loader
    should fall back to the current table's date_added."""
    df = parse_membership_html(SAMPLE_HTML)
    aapl_rows = df[df["ticker"] == "AAPL"]
    assert len(aapl_rows) == 1
    assert aapl_rows.iloc[0]["included_from"] == pd.Timestamp("1982-11-30")
    assert pd.isna(aapl_rows.iloc[0]["included_until"])


def test_parse_membership_html_raises_when_no_tables_present():
    with pytest.raises(UniverseError):
        parse_membership_html("<html><body><p>No tables here.</p></body></html>")


# ---------------------------------------------------------------------------
# _build_membership — direct unit tests on edge cases
# ---------------------------------------------------------------------------
def test_build_membership_handles_remove_without_prior_add():
    """A ticker removed in 2020 with no recorded add must produce a
    spell with NaT start (it was in the index since before the log)."""
    current = pd.DataFrame(columns=["ticker", "name", "sector", "date_added"])
    events = [{"date": pd.Timestamp("2020-06-01"), "ticker": "ZZZ",
               "action": "removed", "name": "Some Co"}]
    df = _build_membership(current, events)
    rows = df[df["ticker"] == "ZZZ"]
    assert len(rows) == 1
    assert pd.isna(rows.iloc[0]["included_from"])
    assert rows.iloc[0]["included_until"] == pd.Timestamp("2020-06-01")


def test_build_membership_handles_multiple_re_entries():
    """A ticker added → removed → added again should produce two spells."""
    current = pd.DataFrame([
        {"ticker": "RE1", "name": "Reentry", "sector": "X", "date_added": None},
    ])
    events = [
        {"date": pd.Timestamp("2010-01-01"), "ticker": "RE1", "action": "added", "name": "Reentry"},
        {"date": pd.Timestamp("2015-06-01"), "ticker": "RE1", "action": "removed", "name": "Reentry"},
        {"date": pd.Timestamp("2020-03-15"), "ticker": "RE1", "action": "added", "name": "Reentry"},
    ]
    df = _build_membership(current, events)
    rows = df[df["ticker"] == "RE1"].sort_values("included_from")
    assert len(rows) == 2
    assert rows.iloc[0]["included_from"] == pd.Timestamp("2010-01-01")
    assert rows.iloc[0]["included_until"] == pd.Timestamp("2015-06-01")
    assert rows.iloc[1]["included_from"] == pd.Timestamp("2020-03-15")
    assert pd.isna(rows.iloc[1]["included_until"])


# ---------------------------------------------------------------------------
# Membership-frame helpers
# ---------------------------------------------------------------------------
def test_current_tickers_returns_sorted_open_spells():
    df = parse_membership_html(SAMPLE_HTML)
    cur = current_tickers(df)
    assert cur == sorted(cur)
    assert "AAPL" in cur
    assert "OLD1" not in cur
    assert "OLD2" not in cur


def test_active_at_excludes_tickers_added_after_date():
    df = parse_membership_html(SAMPLE_HTML)
    # NEW1 was added 2024-01-15. On 2023-12-31 it should not be active.
    active_2023 = active_at(df, "2023-12-31")
    assert "NEW1" not in active_2023
    # MSFT was in the index then (added 1994).
    assert "MSFT" in active_2023


def test_active_at_includes_tickers_in_index_before_removal():
    df = parse_membership_html(SAMPLE_HTML)
    # OLD2 was in 2010-03-22 → 2020-06-01.
    assert "OLD2" in active_at(df, "2015-01-01")
    assert "OLD2" not in active_at(df, "2020-06-01")  # removal date is exclusive
    assert "OLD2" not in active_at(df, "2021-01-01")


def test_active_at_handles_nat_bounds():
    """A spell with NaT included_from should be treated as 'always-on'
    up to its included_until — covers tickers that were in the index
    before the change log starts."""
    df = pd.DataFrame([{
        "ticker": "ZZZ", "name": "Z", "sector": "S",
        "included_from": pd.NaT,
        "included_until": pd.Timestamp("2020-01-01"),
    }])
    assert active_at(df, "2010-01-01") == ["ZZZ"]
    assert active_at(df, "2020-06-01") == []


# ---------------------------------------------------------------------------
# Loader cache + network behavior
# ---------------------------------------------------------------------------
@pytest.fixture
def loader(tmp_path):
    return SP500MembershipLoader(cache_dir=tmp_path, timeout_s=2)


def _mock_response(status_code=200, text=SAMPLE_HTML):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def test_fetch_writes_parquet_and_meta(loader, tmp_path):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()) as mock_get:
        df = loader.fetch_membership()

    mock_get.assert_called_once()
    parquet_path = tmp_path / "sp500_membership.parquet"
    meta_path = tmp_path / "_meta.json"
    assert parquet_path.exists()
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["sp500_membership"]["n_rows"] == len(df)
    assert meta["sp500_membership"]["n_current_constituents"] >= 4


def test_cache_short_circuits_inside_max_age(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()) as mock_get:
        loader.fetch_membership()
        assert mock_get.call_count == 1
        loader.fetch_membership()
        assert mock_get.call_count == 1  # served from cache


def test_force_bypasses_cache(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()) as mock_get:
        loader.fetch_membership()
        loader.fetch_membership(force=True)
    assert mock_get.call_count == 2


def test_max_age_zero_always_refetches(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()) as mock_get:
        loader.fetch_membership()
        loader.fetch_membership(max_age_hours=0)
    assert mock_get.call_count == 2


def test_network_failure_serves_cache(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()):
        loader.fetch_membership()
    with patch("engines.data_manager.universe.requests.get",
               side_effect=requests.ConnectionError("offline")):
        df = loader.fetch_membership(force=True)
    assert not df.empty


def test_network_failure_without_cache_raises(loader):
    with patch("engines.data_manager.universe.requests.get",
               side_effect=requests.ConnectionError("offline")):
        with pytest.raises(UniverseError):
            loader.fetch_membership()


def test_http_error_raises_when_no_cache(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response(status_code=503, text="server down")):
        with pytest.raises(UniverseError):
            loader.fetch_membership()


def test_load_cached_when_missing_returns_empty(loader):
    df = loader.load_cached()
    assert df.empty
    assert list(df.columns) == MEMBERSHIP_COLUMNS


def test_current_constituents_after_fetch(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()):
        cur = loader.current_constituents()
    assert {"AAPL", "MSFT", "NVDA", "NEW1"}.issubset(set(cur))


def test_historical_constituents_predates_addition(loader):
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()):
        # NEW1 wasn't in the index in 2023, but was in 2024
        as_2023 = loader.historical_constituents("2023-01-01")
        as_2024 = loader.historical_constituents("2024-12-31")
    assert "NEW1" not in as_2023
    assert "NEW1" in as_2024


def test_cache_status_reports_state(loader):
    status_empty = loader.cache_status()
    assert status_empty["cached"] is False
    with patch("engines.data_manager.universe.requests.get",
               return_value=_mock_response()):
        loader.fetch_membership()
    status = loader.cache_status()
    assert status["cached"] is True
    assert status["n_rows"] is not None
    assert status["n_current_constituents"] >= 4


def test_default_cache_dir_under_repo_root():
    """Sanity: default cache lives under data/universe/, not somewhere wild."""
    assert DEFAULT_CACHE_DIR.parts[-2:] == ("data", "universe")


# ---------------------------------------------------------------------------
# scripts.fetch_universe (CLI)
# ---------------------------------------------------------------------------
from scripts import fetch_universe  # noqa: E402


def test_split_cached_vs_missing_partitions_correctly(tmp_path):
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    (parquet_dir / "AAPL_1d.parquet").touch()
    (parquet_dir / "MSFT_1d.parquet").touch()
    cached, missing = fetch_universe.split_cached_vs_missing(
        ["AAPL", "MSFT", "NVDA", "TSLA"],
        processed_dir=tmp_path,
        timeframe="1d",
        refresh=False,
    )
    assert set(cached) == {"AAPL", "MSFT"}
    assert set(missing) == {"NVDA", "TSLA"}


def test_split_cached_vs_missing_refresh_treats_all_as_missing(tmp_path):
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    (parquet_dir / "AAPL_1d.parquet").touch()
    cached, missing = fetch_universe.split_cached_vs_missing(
        ["AAPL", "MSFT"],
        processed_dir=tmp_path,
        timeframe="1d",
        refresh=True,
    )
    assert cached == []
    assert set(missing) == {"AAPL", "MSFT"}


def test_load_ticker_list_from_file(tmp_path):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("AAPL\nmsft\n\nNVDA\n")
    args = fetch_universe.parse_args(
        ["--source", "file", "--file", str(list_path)]
    )
    assert fetch_universe.load_ticker_list(args) == ["AAPL", "MSFT", "NVDA"]


def test_load_ticker_list_file_missing_path_errors():
    args = fetch_universe.parse_args(["--source", "file"])
    with pytest.raises(SystemExit):
        fetch_universe.load_ticker_list(args)


def test_load_ticker_list_sp500_current_filters_to_open_spells(tmp_path, monkeypatch):
    # Patch the loader the CLI uses so we don't hit the network.
    fake_df = pd.DataFrame([
        {"ticker": "AAA", "name": None, "sector": None,
         "included_from": pd.Timestamp("2020-01-01"),
         "included_until": pd.NaT},
        {"ticker": "ZZZ", "name": None, "sector": None,
         "included_from": pd.Timestamp("2010-01-01"),
         "included_until": pd.Timestamp("2018-01-01")},
    ])
    fake_loader = MagicMock()
    fake_loader.fetch_membership.return_value = fake_df
    monkeypatch.setattr(
        "scripts.fetch_universe.SP500MembershipLoader",
        lambda *a, **k: fake_loader,
    )
    args = fetch_universe.parse_args(["--source", "sp500_current"])
    assert fetch_universe.load_ticker_list(args) == ["AAA"]


def test_load_ticker_list_sp500_historical_returns_union(tmp_path, monkeypatch):
    fake_df = pd.DataFrame([
        {"ticker": "AAA", "name": None, "sector": None,
         "included_from": pd.Timestamp("2020-01-01"),
         "included_until": pd.NaT},
        {"ticker": "ZZZ", "name": None, "sector": None,
         "included_from": pd.Timestamp("2010-01-01"),
         "included_until": pd.Timestamp("2018-01-01")},
    ])
    fake_loader = MagicMock()
    fake_loader.fetch_membership.return_value = fake_df
    monkeypatch.setattr(
        "scripts.fetch_universe.SP500MembershipLoader",
        lambda *a, **k: fake_loader,
    )
    args = fetch_universe.parse_args(["--source", "sp500_historical"])
    assert fetch_universe.load_ticker_list(args) == ["AAA", "ZZZ"]


def test_dry_run_does_not_call_data_manager(tmp_path, monkeypatch):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("AAPL\nMSFT\n")

    sentinel = MagicMock(side_effect=AssertionError("DataManager should not be touched"))
    monkeypatch.setattr("scripts.fetch_universe.DataManager", sentinel)

    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(tmp_path / "processed"),
        "--dry-run",
    ]))
    assert rc == 0
    sentinel.assert_not_called()


def test_run_skips_already_cached_tickers(tmp_path, monkeypatch):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("AAPL\nMSFT\n")
    processed = tmp_path / "processed"
    (processed / "parquet").mkdir(parents=True)
    (processed / "parquet" / "AAPL_1d.parquet").touch()
    (processed / "parquet" / "MSFT_1d.parquet").touch()

    sentinel = MagicMock(side_effect=AssertionError("nothing should be fetched"))
    monkeypatch.setattr("scripts.fetch_universe.DataManager", sentinel)

    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(processed),
    ]))
    assert rc == 0
    sentinel.assert_not_called()


def test_run_errors_when_credentials_missing(tmp_path, monkeypatch, capsys):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("NVDA\n")
    processed = tmp_path / "processed"

    monkeypatch.setattr("scripts.fetch_universe.credentials_available", lambda: False)
    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(processed),
    ]))
    assert rc == 2
    err = capsys.readouterr().err
    assert "credentials" in err.lower()


def test_run_invokes_fetch_one_for_missing_tickers(tmp_path, monkeypatch):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("AAA\nBBB\nCCC\n")
    processed = tmp_path / "processed"
    (processed / "parquet").mkdir(parents=True)
    (processed / "parquet" / "AAA_1d.parquet").touch()  # cached

    monkeypatch.setattr("scripts.fetch_universe.credentials_available", lambda: True)
    monkeypatch.setattr("scripts.fetch_universe.DataManager",
                        MagicMock(return_value=MagicMock()))

    fetched = []

    def fake_fetch_one(dm, ticker, start, end, timeframe):
        fetched.append(ticker)
        return True, "10 rows"

    monkeypatch.setattr("scripts.fetch_universe.fetch_one", fake_fetch_one)
    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(processed),
    ]))
    assert rc == 0
    assert sorted(fetched) == ["BBB", "CCC"]


def test_run_max_tickers_caps_fetched_count(tmp_path, monkeypatch):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("\n".join(f"T{i}" for i in range(10)))
    processed = tmp_path / "processed"

    monkeypatch.setattr("scripts.fetch_universe.credentials_available", lambda: True)
    monkeypatch.setattr("scripts.fetch_universe.DataManager",
                        MagicMock(return_value=MagicMock()))
    fetched = []

    def fake_fetch_one(dm, ticker, start, end, timeframe):
        fetched.append(ticker)
        return True, "ok"

    monkeypatch.setattr("scripts.fetch_universe.fetch_one", fake_fetch_one)
    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(processed),
        "--max-tickers", "3",
    ]))
    assert rc == 0
    assert len(fetched) == 3


def test_run_returns_nonzero_when_any_fetch_fails(tmp_path, monkeypatch):
    list_path = tmp_path / "tickers.txt"
    list_path.write_text("OK1\nFAIL1\n")
    processed = tmp_path / "processed"

    monkeypatch.setattr("scripts.fetch_universe.credentials_available", lambda: True)
    monkeypatch.setattr("scripts.fetch_universe.DataManager",
                        MagicMock(return_value=MagicMock()))

    def fake_fetch_one(dm, ticker, start, end, timeframe):
        return (ticker == "OK1"), "ok" if ticker == "OK1" else "boom"

    monkeypatch.setattr("scripts.fetch_universe.fetch_one", fake_fetch_one)
    rc = fetch_universe.run(fetch_universe.parse_args([
        "--source", "file",
        "--file", str(list_path),
        "--processed-dir", str(processed),
    ]))
    assert rc == 1


# ---------------------------------------------------------------------------
# Live integration — opt-in via env var
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("UNIVERSE_LIVE_TEST") != "1",
    reason="Live Wikipedia test disabled by default; set UNIVERSE_LIVE_TEST=1 to enable.",
)
def test_live_wikipedia_membership_fetch(tmp_path):
    loader = SP500MembershipLoader(cache_dir=tmp_path)
    df = loader.fetch_membership()
    assert not df.empty
    cur = current_tickers(df)
    # The S&P 500 has ~500 constituents (sometimes 503 due to multi-class shares).
    assert 480 <= len(cur) <= 520
    # AAPL has been in the index for decades; sanity check.
    assert "AAPL" in cur
