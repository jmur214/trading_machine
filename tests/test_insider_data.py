"""Tests for engines.data_manager.insider_data.

All tests run offline by mocking the OpenInsider HTTP layer. There is one
integration-style test at the bottom gated behind RUN_OPENINSIDER_INTEGRATION
— skipped by default so CI / fresh clones never hit the live site.
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

from engines.data_manager.insider_data import (
    DEFAULT_CACHE_DIR,
    INSIDER_TXN_COLUMNS,
    InsiderDataError,
    InsiderDataManager,
    parse_insider_table,
    _normalize_trade_type,
    _parse_money,
    _parse_int,
    _parse_pct,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _row(
    *,
    flag="D",
    filing_date="2026-04-03 18:30:45",
    trade_date="2026-04-02",
    ticker="AAPL",
    name="O'Brien Deirdre",
    title="SVP",
    ttype="S - Sale+OE",
    price="$255.35",
    qty="-30,002",
    owned="136,810",
    dpct="-18%",
    value="-$7,660,875",
) -> str:
    return (
        "<tr>"
        f"<td>{flag}</td>"
        f"<td>{filing_date}</td>"
        f"<td>{trade_date}</td>"
        f"<td>{ticker}</td>"
        f"<td>{name}</td>"
        f"<td>{title}</td>"
        f"<td>{ttype}</td>"
        f"<td>{price}</td>"
        f"<td>{qty}</td>"
        f"<td>{owned}</td>"
        f"<td>{dpct}</td>"
        f"<td>{value}</td>"
        "<td></td><td></td><td></td><td></td>"
        "</tr>"
    )


def _table(*body_rows: str) -> str:
    body = "".join(body_rows)
    return (
        '<html><body>'
        '<table class="tinytable">'
        "<thead><tr>"
        "<th>X</th><th>Filing&nbsp;Date</th><th>Trade&nbsp;Date</th>"
        "<th>Ticker</th><th>Insider&nbsp;Name</th><th>Title</th>"
        "<th>Trade&nbsp;Type</th><th>Price</th><th>Qty</th><th>Owned</th>"
        "<th>ΔOwn</th><th>Value</th>"
        "<th>1d</th><th>1w</th><th>1m</th><th>6m</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table></body></html>"
    )


SAMPLE_AAPL_HTML = _table(
    _row(),  # default sale
    _row(
        flag="D",
        filing_date="2024-02-03 16:01:00",
        trade_date="2024-02-01",
        name="Buffett Warren",
        title="10% Owner",
        ttype="P - Purchase",
        price="$180.00",
        qty="100,000",
        owned="500,000",
        dpct="25%",
        value="$18,000,000",
    ),
    _row(
        flag="D",
        filing_date="2023-05-10 16:00:00",
        trade_date="2023-05-08",
        name="New Director",
        title="Dir",
        ttype="P - Purchase",
        price="$170.00",
        qty="1,000",
        owned="1,000",
        dpct="New",
        value="$170,000",
    ),
)


SAMPLE_MSFT_HTML = _table(
    _row(
        ticker="MSFT",
        filing_date="2024-01-30 17:00:00",
        trade_date="2024-01-29",
        name="Nadella Satya",
        title="CEO",
        ttype="S - Sale",
        price="$400.00",
        qty="-50,000",
        owned="800,000",
        dpct="-6%",
        value="-$20,000,000",
    ),
)


EMPTY_TABLE_HTML = _table()


NO_TABLE_HTML = "<html><body><p>OpenInsider had a hiccup.</p></body></html>"


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _ok(html: str) -> _FakeResponse:
    return _FakeResponse(200, html)


@pytest.fixture
def mgr(tmp_path):
    """Manager isolated to a tmp cache dir, no rate limiting."""
    return InsiderDataManager(cache_dir=tmp_path, rate_limit_s=0)


# ---------------------------------------------------------------------------
# Cell-level helpers
# ---------------------------------------------------------------------------
def test_normalize_trade_type_handles_purchase_and_sale():
    assert _normalize_trade_type("P - Purchase") == "P"
    assert _normalize_trade_type("S - Sale") == "S"
    assert _normalize_trade_type("S - Sale+OE") == "S"


def test_normalize_trade_type_handles_unknown():
    assert _normalize_trade_type("") == ""
    assert _normalize_trade_type(None) == ""
    assert _normalize_trade_type("A - Award") == ""


def test_parse_money_strips_dollar_and_commas():
    assert _parse_money("$1,234.56") == pytest.approx(1234.56)
    assert _parse_money("-$7,660,875") == pytest.approx(-7660875.0)


def test_parse_money_returns_nan_on_garbage():
    assert math.isnan(_parse_money(""))
    assert math.isnan(_parse_money("-"))
    assert math.isnan(_parse_money("not-money"))
    assert math.isnan(_parse_money(None))


def test_parse_int_handles_signed_qty():
    assert _parse_int("-30,002") == -30002
    assert _parse_int("100,000") == 100000


def test_parse_int_returns_na_on_garbage():
    assert pd.isna(_parse_int(""))
    assert pd.isna(_parse_int("-"))
    assert pd.isna(_parse_int("garbage"))


def test_parse_pct_converts_to_fractional():
    assert _parse_pct("-18%") == pytest.approx(-0.18)
    assert _parse_pct("25%") == pytest.approx(0.25)


def test_parse_pct_handles_new_and_dash_sentinels():
    assert math.isnan(_parse_pct("New"))
    assert math.isnan(_parse_pct("new"))
    assert math.isnan(_parse_pct("-"))
    assert math.isnan(_parse_pct(""))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def test_parse_insider_table_basic():
    df = parse_insider_table(SAMPLE_AAPL_HTML, fallback_ticker="AAPL")
    assert list(df.columns) == INSIDER_TXN_COLUMNS
    assert len(df) == 3
    assert df.index.is_monotonic_increasing
    assert df.index.name == "transaction_date"
    # Earliest row is the New-director purchase from 2023-05-08
    first = df.iloc[0]
    assert first["insider_name"] == "New Director"
    assert first["transaction_type"] == "P"
    assert first["transaction_subtype"] == "P - Purchase"
    assert first["price"] == pytest.approx(170.0)
    assert first["shares"] == 1000
    assert first["holdings_after"] == 1000
    assert math.isnan(first["delta_holdings_pct"])  # "New" sentinel
    assert first["value"] == pytest.approx(170000.0)


def test_parse_insider_table_extracts_signed_sale():
    df = parse_insider_table(SAMPLE_AAPL_HTML, fallback_ticker="AAPL")
    sale = df.loc[df["transaction_type"] == "S"].iloc[0]
    assert sale["shares"] == -30002
    assert sale["value"] == pytest.approx(-7660875.0)
    assert sale["delta_holdings_pct"] == pytest.approx(-0.18)
    assert sale["transaction_subtype"] == "S - Sale+OE"


def test_parse_insider_table_empty_body_returns_empty_frame():
    df = parse_insider_table(EMPTY_TABLE_HTML, fallback_ticker="AAPL")
    assert df.empty
    assert list(df.columns) == INSIDER_TXN_COLUMNS
    assert df.index.name == "transaction_date"


def test_parse_insider_table_missing_table_returns_empty_frame():
    df = parse_insider_table(NO_TABLE_HTML, fallback_ticker="AAPL")
    assert df.empty
    assert list(df.columns) == INSIDER_TXN_COLUMNS


def test_parse_insider_table_skips_unparseable_trade_date():
    html = _table(
        _row(trade_date="not-a-date"),
        _row(trade_date="2024-02-01"),
    )
    df = parse_insider_table(html, fallback_ticker="AAPL")
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-02-01")


def test_parse_insider_table_falls_back_to_argument_ticker():
    # Some scraped rows can land with empty ticker cells (rare).
    html = _table(_row(ticker=""))
    df = parse_insider_table(html, fallback_ticker="aapl")
    assert (df["ticker"] == "AAPL").all()


def test_parse_insider_table_handles_malformed_numeric_cells():
    html = _table(
        _row(price="--", qty="??", owned="--", dpct="??", value="--"),
    )
    df = parse_insider_table(html, fallback_ticker="AAPL")
    assert len(df) == 1
    row = df.iloc[0]
    assert math.isnan(row["price"])
    assert pd.isna(row["shares"])
    assert pd.isna(row["holdings_after"])
    assert math.isnan(row["delta_holdings_pct"])
    assert math.isnan(row["value"])


def test_parse_insider_table_dtype_stability():
    df = parse_insider_table(SAMPLE_AAPL_HTML, fallback_ticker="AAPL")
    assert str(df["shares"].dtype) == "Int64"
    assert str(df["holdings_after"].dtype) == "Int64"
    assert str(df["price"].dtype) == "float64"


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------
def test_fetch_writes_parquet_and_meta(mgr, tmp_path):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ) as mock_get:
        df = mgr.fetch_filings("AAPL", start="2020-01-01")

    mock_get.assert_called_once()
    assert (tmp_path / "AAPL.parquet").exists()
    assert (tmp_path / "_meta.json").exists()
    meta = json.loads((tmp_path / "_meta.json").read_text())
    assert meta["AAPL"]["n_rows"] == 3
    assert df.equals(pd.read_parquet(tmp_path / "AAPL.parquet"))


def test_fetch_normalizes_lowercase_ticker(mgr, tmp_path):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ):
        mgr.fetch_filings("aapl")
    assert (tmp_path / "AAPL.parquet").exists()


def test_cache_short_circuits_inside_max_age(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ) as mock_get:
        mgr.fetch_filings("AAPL")
        assert mock_get.call_count == 1
        mgr.fetch_filings("AAPL")
        assert mock_get.call_count == 1


def test_force_bypasses_cache(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ) as mock_get:
        mgr.fetch_filings("AAPL")
        mgr.fetch_filings("AAPL", force=True)
    assert mock_get.call_count == 2


def test_max_age_zero_always_refetches(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ) as mock_get:
        mgr.fetch_filings("AAPL")
        mgr.fetch_filings("AAPL", max_age_hours=0)
    assert mock_get.call_count == 2


def test_default_cache_dir_under_repo_root():
    """Sanity: default cache lives under data/insider/, not somewhere wild."""
    assert DEFAULT_CACHE_DIR.parts[-2:] == ("data", "insider")


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------
def test_network_failure_serves_cache(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ):
        mgr.fetch_filings("AAPL")
    with patch(
        "engines.data_manager.insider_data.requests.get",
        side_effect=requests.ConnectionError("offline"),
    ):
        df = mgr.fetch_filings("AAPL", force=True)
    assert len(df) == 3


def test_network_failure_without_cache_raises(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        side_effect=requests.ConnectionError("offline"),
    ):
        with pytest.raises(InsiderDataError):
            mgr.fetch_filings("AAPL")


def test_http_error_serves_cache_when_present(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ):
        mgr.fetch_filings("AAPL")
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_FakeResponse(503, "down"),
    ):
        df = mgr.fetch_filings("AAPL", force=True)
    assert len(df) == 3  # served from cache


def test_http_error_raises_when_no_cache(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_FakeResponse(429, "rate limit"),
    ):
        with pytest.raises(InsiderDataError):
            mgr.fetch_filings("AAPL")


def test_empty_table_persists_zero_row_cache(mgr, tmp_path):
    """An empty body should still cache so the next call doesn't refetch."""
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(EMPTY_TABLE_HTML),
    ):
        df = mgr.fetch_filings("ZZZZ")
    assert df.empty
    assert (tmp_path / "ZZZZ.parquet").exists()


def test_load_cached_when_missing_returns_empty(mgr):
    df = mgr.load_cached("NEVER_FETCHED")
    assert df.empty
    assert list(df.columns) == INSIDER_TXN_COLUMNS


def test_rate_limit_sleeps_when_configured(tmp_path):
    """When rate_limit_s > 0 the manager calls time.sleep before fetch."""
    rate_mgr = InsiderDataManager(cache_dir=tmp_path, rate_limit_s=2.5)
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)

    monotonic_values = iter([100.0, 100.0, 101.0, 101.0])

    def fake_monotonic():
        return next(monotonic_values)

    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ), patch(
        "engines.data_manager.insider_data.time.sleep",
        side_effect=fake_sleep,
    ), patch(
        "engines.data_manager.insider_data.time.monotonic",
        side_effect=fake_monotonic,
    ):
        rate_mgr._respect_rate_limit()  # priming call, no sleep needed
        rate_mgr._respect_rate_limit()  # 1s elapsed, should sleep ~1.5s

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
def test_universe_concatenates_per_ticker_frames(mgr):
    def fake_get(url, params=None, timeout=None, headers=None):
        sym = params["s"]
        if sym == "AAPL":
            return _ok(SAMPLE_AAPL_HTML)
        if sym == "MSFT":
            return _ok(SAMPLE_MSFT_HTML)
        return _ok(EMPTY_TABLE_HTML)

    with patch(
        "engines.data_manager.insider_data.requests.get",
        side_effect=fake_get,
    ):
        combined = mgr.fetch_universe(["AAPL", "MSFT"])

    assert set(combined["ticker"].unique()) == {"AAPL", "MSFT"}
    assert len(combined) == 4  # 3 AAPL + 1 MSFT
    assert combined.index.is_monotonic_increasing


def test_universe_skips_failed_tickers(mgr):
    def fake_get(url, params=None, timeout=None, headers=None):
        sym = params["s"]
        if sym == "AAPL":
            return _ok(SAMPLE_AAPL_HTML)
        return _FakeResponse(500, "boom")

    with patch(
        "engines.data_manager.insider_data.requests.get",
        side_effect=fake_get,
    ):
        combined = mgr.fetch_universe(["AAPL", "BROKE"])

    assert set(combined["ticker"].unique()) == {"AAPL"}


def test_universe_all_failures_raises(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_FakeResponse(500, "boom"),
    ):
        with pytest.raises(InsiderDataError):
            mgr.fetch_universe(["AAPL", "MSFT"])


def test_universe_empty_when_no_rows(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(EMPTY_TABLE_HTML),
    ):
        combined = mgr.fetch_universe(["AAPL", "MSFT"])
    assert combined.empty
    assert list(combined.columns) == INSIDER_TXN_COLUMNS


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------
def test_cache_status_reports_state(mgr):
    with patch(
        "engines.data_manager.insider_data.requests.get",
        return_value=_ok(SAMPLE_AAPL_HTML),
    ):
        mgr.fetch_filings("AAPL")
    status = mgr.cache_status()
    assert "AAPL" in status["ticker"].values
    aapl_row = status[status["ticker"] == "AAPL"].iloc[0]
    assert bool(aapl_row["cached"]) is True
    assert aapl_row["n_rows"] == 3


def test_cache_status_empty_when_nothing_fetched(tmp_path):
    mgr = InsiderDataManager(cache_dir=tmp_path, rate_limit_s=0)
    status = mgr.cache_status()
    assert status.empty
    assert list(status.columns) == [
        "ticker", "cached", "age_hours", "n_rows", "last_fetched_utc",
    ]


# ---------------------------------------------------------------------------
# Integration (live network) — skipped unless RUN_OPENINSIDER_INTEGRATION=1.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_OPENINSIDER_INTEGRATION") != "1",
    reason="Live OpenInsider scrape disabled; set "
           "RUN_OPENINSIDER_INTEGRATION=1 to enable.",
)
def test_live_openinsider_aapl_fetch(tmp_path):
    mgr = InsiderDataManager(cache_dir=tmp_path)
    df = mgr.fetch_filings("AAPL", start="2024-01-01", end="2024-12-31")
    assert not df.empty
    assert list(df.columns) == INSIDER_TXN_COLUMNS
    assert (df["ticker"] == "AAPL").all()
    assert (df.index >= pd.Timestamp("2024-01-01")).all()
