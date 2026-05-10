"""Tests for the dividend-initiation drift edge (T-2026-05-09-018).

Buyback edge was scoped out of T-018 — no corporate-action data source
available for buyback announcements (yfinance does not expose them, and
SimFin's adapter does not surface treasury-stock changes). The audit
doc captures the gap as forward-looking work.

Synthetic dividend data is injected into `DividendInitiationDriftEdge._dividends_cache`
so tests don't hit yfinance.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engines.engine_a_alpha.edges.dividend_initiation_drift_v1 import (  # noqa: E402
    DividendInitiationDriftEdge,
)
from engines.engine_a_alpha.edge_registry import EdgeRegistry  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_dividends_cache():
    """Ensure each test starts with a clean dividends cache so injections
    in one test don't leak into another."""
    DividendInitiationDriftEdge._dividends_cache = {}
    yield
    DividendInitiationDriftEdge._dividends_cache = {}


def _inject_dividends(edge: DividendInitiationDriftEdge, ticker: str,
                      dates: list[str]) -> None:
    """Helper — set ticker's dividend history to `dates` (each $0.5 amount)."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    edge._dividends_cache[ticker] = pd.Series([0.5] * len(idx), index=idx)


def _make_data_map(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Edge ignores DataFrame contents — only uses dict keys for the
    ticker iteration. Pass minimal frames."""
    return {t: pd.DataFrame({"Close": [100.0]}) for t in tickers}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_dividend_initiation_drift_registers_at_paused_feature():
    reg = EdgeRegistry()
    spec = next(
        (s for s in reg.get_all_specs() if s.edge_id == "dividend_initiation_drift_v1"),
        None,
    )
    assert spec is not None, "dividend_initiation_drift_v1 did not register"
    assert spec.status == "paused"
    assert spec.tier == "feature"


# ---------------------------------------------------------------------------
# Initiation detection
# ---------------------------------------------------------------------------

def test_first_dividend_ever_is_an_initiation():
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2020-03-15"])
    inits = edge._initiation_dates(edge._dividends_cache["T"], gap_years=3)
    assert inits == [pd.Timestamp("2020-03-15")]


def test_dividend_after_3yr_gap_is_an_initiation():
    edge = DividendInitiationDriftEdge()
    # First payment 2010, then 4-year gap, then quarterly from 2014
    _inject_dividends(edge, "T", [
        "2010-03-15",
        "2014-03-15", "2014-06-15", "2014-09-15", "2014-12-15",
        "2015-03-15", "2015-06-15", "2015-09-15", "2015-12-15",
    ])
    inits = edge._initiation_dates(edge._dividends_cache["T"], gap_years=3)
    # Both 2010-03-15 (first ever) and 2014-03-15 (post-4yr-gap) qualify
    assert inits == [pd.Timestamp("2010-03-15"), pd.Timestamp("2014-03-15")]


def test_consecutive_quarterly_dividends_are_NOT_initiations():
    """Regular quarterly dividends should NOT register as initiations."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", [
        "2020-03-15", "2020-06-15", "2020-09-15", "2020-12-15",
        "2021-03-15", "2021-06-15", "2021-09-15", "2021-12-15",
        "2022-03-15", "2022-06-15", "2022-09-15",
    ])
    inits = edge._initiation_dates(edge._dividends_cache["T"], gap_years=3)
    # Only the first dividend (2020-03-15) qualifies as an initiation;
    # the rest are regular quarterly continuations.
    assert inits == [pd.Timestamp("2020-03-15")]


# ---------------------------------------------------------------------------
# Drift-window signal shape
# ---------------------------------------------------------------------------

def test_long_signal_in_drift_window():
    """Inside the [1, 60] day post-initiation window, the edge should
    return a positive long signal that decays from ~0.5 toward 0."""
    edge = DividendInitiationDriftEdge()
    # Initiation on 2020-03-16 (Monday); test 5, 30, 60 trading days after
    _inject_dividends(edge, "T", ["2020-03-16"])
    data_map = _make_data_map(["T"])

    s_5 = edge.compute_signals(data_map, pd.Timestamp("2020-03-23"))["T"]   # ~5 bdays
    s_30 = edge.compute_signals(data_map, pd.Timestamp("2020-04-27"))["T"]  # ~30 bdays
    s_60 = edge.compute_signals(data_map, pd.Timestamp("2020-06-08"))["T"]  # ~60 bdays

    assert s_5 > s_30 > s_60 >= 0.0, (
        f"Decay broken: 5d={s_5}, 30d={s_30}, 60d={s_60}"
    )
    assert s_5 > 0.3, f"Day-5 signal too small: {s_5}"
    assert s_60 < 0.05, f"Day-60 signal should be near zero: {s_60}"


def test_abstain_outside_drift_window():
    """Initiation 100 trading days ago → outside 60-day window → abstain."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2020-01-02"])
    data_map = _make_data_map(["T"])
    # 2020-06-15 is well over 60 trading days after 2020-01-02
    score = edge.compute_signals(data_map, pd.Timestamp("2020-06-15"))["T"]
    assert score == 0.0, f"Expected abstain (0.0); got {score}"


def test_abstain_on_announcement_day_itself():
    """skip_first_day=True (default) means day 0 → abstain (vol cluster)."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2020-03-16"])
    data_map = _make_data_map(["T"])
    score = edge.compute_signals(data_map, pd.Timestamp("2020-03-16"))["T"]
    assert score == 0.0


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_handles_missing_data_gracefully():
    """Ticker with no dividend history → abstain, no crash."""
    edge = DividendInitiationDriftEdge()
    # Inject empty Series — simulates yfinance returning no dividends
    edge._dividends_cache["NONEX"] = pd.Series(dtype=float)
    data_map = _make_data_map(["NONEX"])
    score = edge.compute_signals(data_map, pd.Timestamp("2020-06-15"))["NONEX"]
    assert score == 0.0


def test_handles_initiation_in_distant_past():
    """Initiation 10 years ago, no recent activity → abstain (outside window)."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2010-03-15"])
    data_map = _make_data_map(["T"])
    score = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))["T"]
    assert score == 0.0


def test_handles_initiation_in_future():
    """If as_of is BEFORE all known initiations → abstain."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2025-06-01"])
    data_map = _make_data_map(["T"])
    score = edge.compute_signals(data_map, pd.Timestamp("2024-12-31"))["T"]
    assert score == 0.0


# ---------------------------------------------------------------------------
# Multi-ticker shape
# ---------------------------------------------------------------------------

def test_multi_ticker_signal_shape():
    """Different tickers with different histories should each get
    independent signals."""
    edge = DividendInitiationDriftEdge()
    # T1 just initiated 5 bdays ago — strong signal
    _inject_dividends(edge, "T1", ["2020-03-16"])
    # T2 has been paying quarterly for years — no initiation in window
    _inject_dividends(edge, "T2", [
        "2018-03-15", "2018-06-15", "2018-09-15", "2018-12-15",
        "2019-03-15", "2019-06-15", "2019-09-15", "2019-12-15",
        "2020-03-15",
    ])
    # T3 has no dividend data
    edge._dividends_cache["T3"] = pd.Series(dtype=float)

    data_map = _make_data_map(["T1", "T2", "T3"])
    scores = edge.compute_signals(data_map, pd.Timestamp("2020-03-23"))

    assert scores["T1"] > 0.3, f"T1 should get drift signal: {scores['T1']}"
    assert scores["T2"] == 0.0, f"T2 quarterly continuation: {scores['T2']}"
    assert scores["T3"] == 0.0, f"T3 no data: {scores['T3']}"


# ---------------------------------------------------------------------------
# T-001 tz-regression discipline
# ---------------------------------------------------------------------------

def test_does_not_raise_on_tz_naive_as_of():
    """The earnings_vol-class regression: tz-naive `as_of` must not
    raise a TypeError when comparing against tz-stripped cache entries."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2020-03-16"])
    data_map = _make_data_map(["T"])
    now = pd.Timestamp("2020-04-15")  # tz-naive, production format
    scores = edge.compute_signals(data_map, now)
    assert isinstance(scores, dict)


def test_does_not_raise_on_tz_aware_as_of():
    """Symmetric robustness — tz-aware input must also not raise."""
    edge = DividendInitiationDriftEdge()
    _inject_dividends(edge, "T", ["2020-03-16"])
    data_map = _make_data_map(["T"])
    now = pd.Timestamp("2020-04-15", tz="America/New_York")
    scores = edge.compute_signals(data_map, now)
    assert isinstance(scores, dict)


def test_cache_index_is_tz_naive_after_tz_aware_yfinance_response(monkeypatch):
    """If yfinance returns a tz-aware DatetimeIndex (current behavior),
    the cache must hold a tz-NAIVE index. This is the structural T-001
    invariant — same bug class as the 2026-05-08 zero-trade outage."""
    edge = DividendInitiationDriftEdge()

    # Build a tz-aware Series mimicking yfinance's actual return shape
    tz_aware_idx = pd.DatetimeIndex(
        [pd.Timestamp("2020-03-16"), pd.Timestamp("2020-06-16")],
        tz="America/New_York",
    )
    fake_divs = pd.Series([0.5, 0.5], index=tz_aware_idx)

    class FakeTicker:
        @property
        def dividends(self):
            return fake_divs

    class FakeYF:
        Ticker = staticmethod(lambda t: FakeTicker())

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "yfinance", FakeYF)

    out = edge._get_dividends("T")
    assert out is not None
    assert getattr(out.index, "tz", None) is None, (
        f"Cache index has tz={out.index.tz}; expected None per T-001 invariant"
    )
