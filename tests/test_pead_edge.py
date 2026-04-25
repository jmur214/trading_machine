"""
tests/test_pead_edge.py
========================
Tests for the PEAD (Post-Earnings Announcement Drift) edge.

The most important contract: when the earnings cache is empty (no
FINNHUB_API_KEY configured, or fresh clone, or the cache hasn't been
bootstrapped), the edge MUST emit zeros for every ticker — no
exceptions, no NaN, no partial signals. Otherwise the edge breaks
backtests that don't have earnings data populated.

Other tests verify the surprise-magnitude → signal mapping, the time
decay, the long-only behavior, the threshold filter, and the surprise
clipping.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.pead_edge import PEADEdge


def _calendar(surprise_pct: float, date: str) -> pd.DataFrame:
    """Single-event earnings calendar."""
    return pd.DataFrame(
        {"eps_surprise_pct": [surprise_pct]},
        index=pd.DatetimeIndex([date]),
    )


def _data_map(*tickers: str) -> dict:
    df = pd.DataFrame({"Close": [100.0, 101.0]})
    return {t: df for t in tickers}


# ---------------------------------------------------------------------------
# Empty-cache contract: ABSTAIN entirely.
# ---------------------------------------------------------------------------

def test_empty_cache_returns_zero_for_all_tickers():
    edge = PEADEdge()
    edge._calendars = {}  # explicitly empty
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("AAPL", "MSFT", "NVDA"),
                                  pd.Timestamp("2024-06-01"))
    assert set(scores.keys()) == {"AAPL", "MSFT", "NVDA"}
    assert all(v == 0.0 for v in scores.values())


def test_ticker_missing_from_calendars_returns_zero():
    """Some tickers may have no earnings data even when others do."""
    edge = PEADEdge()
    edge._calendars = {"AAPL": _calendar(0.10, "2024-05-15")}
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("AAPL", "UNCOVERED"),
                                  pd.Timestamp("2024-06-01"))
    assert scores["UNCOVERED"] == 0.0
    assert scores["AAPL"] > 0.0


# ---------------------------------------------------------------------------
# Long-only behavior
# ---------------------------------------------------------------------------

def test_negative_surprise_ignored_long_only():
    """Long-only v1: negative surprises produce no signal regardless of
    magnitude. Future versions could add short-side; not in v1."""
    edge = PEADEdge()
    edge._calendars = {"BAD": _calendar(-0.20, "2024-05-15")}
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("BAD"), pd.Timestamp("2024-06-01"))
    assert scores["BAD"] == 0.0


# ---------------------------------------------------------------------------
# Threshold filter
# ---------------------------------------------------------------------------

def test_below_threshold_surprise_ignored():
    """Surprises smaller than min_surprise_pct (default 5%) are noise."""
    edge = PEADEdge()
    edge._calendars = {"NOISE": _calendar(0.02, "2024-05-15")}  # 2% surprise
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("NOISE"), pd.Timestamp("2024-06-01"))
    assert scores["NOISE"] == 0.0


def test_at_threshold_surprise_produces_zero_signal():
    """At exactly min_surprise_pct, the magnitude_factor is 0 → signal 0.
    The signal scales from 0 at threshold to long_score_max at clip_pct."""
    edge = PEADEdge()
    edge._calendars = {"BORDER": _calendar(0.05, "2024-06-01")}  # exactly threshold
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("BORDER"), pd.Timestamp("2024-06-01"))
    # At exactly threshold + day of announcement: magnitude factor = 0
    assert scores["BORDER"] == 0.0


# ---------------------------------------------------------------------------
# Surprise clipping
# ---------------------------------------------------------------------------

def test_extreme_surprise_clipped_to_max_signal():
    """A 100% surprise shouldn't dominate other tickers — clip at 30%."""
    edge = PEADEdge()
    edge._calendars = {"NVDA": _calendar(1.00, "2024-06-01")}  # 100% surprise
    edge._calendars_loaded = True

    scores = edge.compute_signals(_data_map("NVDA"), pd.Timestamp("2024-06-01"))
    # At day 0, time_factor = 1.0, magnitude_factor = 1.0 (clipped)
    # → signal = long_score_max = 0.4
    assert scores["NVDA"] == pytest.approx(0.4, abs=1e-6)


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------

def test_signal_decays_linearly_post_announcement():
    edge = PEADEdge()
    edge._calendars = {"DECAY": _calendar(0.30, "2024-05-01")}
    edge._calendars_loaded = True

    day0 = edge.compute_signals(_data_map("DECAY"), pd.Timestamp("2024-05-01"))["DECAY"]
    day42 = edge.compute_signals(_data_map("DECAY"), pd.Timestamp("2024-06-12"))["DECAY"]
    day80 = edge.compute_signals(_data_map("DECAY"), pd.Timestamp("2024-07-20"))["DECAY"]

    assert day0 > day42 > day80, f"Expected monotonic decay, got {day0} {day42} {day80}"
    # Day 0: full signal (clipped at 30% surprise = max signal 0.4)
    assert day0 == pytest.approx(0.4, abs=1e-6)
    # Day 42 (about half-way through 84-day window): roughly half signal
    assert 0.15 < day42 < 0.25


def test_signal_zero_after_window():
    edge = PEADEdge()
    edge._calendars = {"OLD": _calendar(0.30, "2024-05-01")}
    edge._calendars_loaded = True

    # 100 calendar days after — outside the 84-day default window
    score = edge.compute_signals(_data_map("OLD"), pd.Timestamp("2024-08-09"))["OLD"]
    assert score == 0.0


# ---------------------------------------------------------------------------
# Multi-event handling
# ---------------------------------------------------------------------------

def test_uses_most_recent_announcement_in_window():
    """If a ticker has 2 announcements in the window, use the most recent."""
    edge = PEADEdge()
    edge._calendars = {
        "MULTI": pd.DataFrame(
            {"eps_surprise_pct": [0.10, 0.30]},
            index=pd.DatetimeIndex(["2024-04-01", "2024-05-15"]),
        )
    }
    edge._calendars_loaded = True

    score = edge.compute_signals(_data_map("MULTI"), pd.Timestamp("2024-05-15"))["MULTI"]
    # If using the more-recent 30% surprise: full signal (0.4)
    # If accidentally using older 10%: would be lower magnitude
    assert score == pytest.approx(0.4, abs=1e-6)


def test_announcement_in_future_ignored():
    """Earnings announcement scheduled in the future shouldn't leak signal back."""
    edge = PEADEdge()
    edge._calendars = {"FUTURE": _calendar(0.20, "2024-12-01")}
    edge._calendars_loaded = True

    score = edge.compute_signals(_data_map("FUTURE"), pd.Timestamp("2024-06-01"))["FUTURE"]
    assert score == 0.0


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------

def test_nan_surprise_pct_returns_zero():
    """Some Finnhub records lack consensus (NaN eps_surprise_pct)."""
    import numpy as np
    edge = PEADEdge()
    edge._calendars = {
        "NAN_SURPRISE": pd.DataFrame(
            {"eps_surprise_pct": [np.nan]},
            index=pd.DatetimeIndex(["2024-05-15"]),
        )
    }
    edge._calendars_loaded = True

    score = edge.compute_signals(_data_map("NAN_SURPRISE"),
                                 pd.Timestamp("2024-06-01"))["NAN_SURPRISE"]
    assert score == 0.0


# ---------------------------------------------------------------------------
# Independence: different tickers compute independently
# ---------------------------------------------------------------------------

def test_per_ticker_independent_computation():
    edge = PEADEdge()
    edge._calendars = {
        "POS_RECENT": _calendar(0.30, "2024-05-25"),    # max signal, recent
        "POS_OLD": _calendar(0.30, "2024-04-01"),       # clipped + decayed
        "NEG": _calendar(-0.30, "2024-05-25"),          # ignored (long-only)
        "SMALL": _calendar(0.02, "2024-05-25"),         # below threshold
    }
    edge._calendars_loaded = True

    scores = edge.compute_signals(
        _data_map("POS_RECENT", "POS_OLD", "NEG", "SMALL", "NO_DATA"),
        pd.Timestamp("2024-06-01"),
    )
    assert scores["POS_RECENT"] > scores["POS_OLD"] > 0
    assert scores["NEG"] == 0.0
    assert scores["SMALL"] == 0.0
    assert scores["NO_DATA"] == 0.0
