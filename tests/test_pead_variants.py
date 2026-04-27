"""
tests/test_pead_variants.py
============================
Tests for the two new PEAD edge variants: pead_short_v1 and pead_predrift_v1.

Contracts verified:
  pead_short_v1:
    - Emits zero for positive surprises (long-only signal is NOT fired)
    - Emits negative score for negative surprises
    - Score magnitude scales with surprise size (up to clip)
    - Linear time decay toward zero at hold_calendar_days
    - Empty cache → all zeros
    - Below-threshold surprise → zero

  pead_predrift_v1:
    - Same long-signal logic as pead_v1 (positive surprise → positive score)
    - Large pre-announcement price drift → zero (leaked surprise filtered)
    - Small pre-announcement price drift → signal fires normally
    - No price data available → filter skipped, signal fires (graceful)
    - Empty cache → all zeros
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edges.pead_short_edge import PEADShortEdge
from engines.engine_a_alpha.edges.pead_predrift_edge import PEADPreDriftEdge


def _calendar(surprise_pct: float, date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"eps_surprise_pct": [surprise_pct]},
        index=pd.DatetimeIndex([date]),
    )


def _price_series(n: int = 50, drift: float = 0.0, base: float = 100.0) -> pd.Series:
    """Simple price series ending at now. drift=total_return over n days."""
    dates = pd.date_range("2024-04-01", periods=n, freq="B")
    prices = base * (1 + drift) ** (np.arange(n) / n)
    return pd.Series(prices, index=dates)


def _data_map_with_prices(ticker: str, prices: pd.Series) -> dict:
    df = pd.DataFrame({"Close": prices.values}, index=prices.index)
    return {ticker: df}


# =============================================================================
# PEADShortEdge tests
# =============================================================================

class TestPEADShortEdge:

    def _edge(self, calendar: dict | None = None) -> PEADShortEdge:
        e = PEADShortEdge()
        e._calendars_loaded = True
        if calendar is not None:
            e._calendars = calendar
        else:
            e._calendars = {}
        return e

    def test_empty_cache_returns_zeros(self):
        e = self._edge({})
        scores = e.compute_signals({"AAPL": pd.DataFrame({"Close": [100.0]})},
                                   pd.Timestamp("2024-06-01"))
        assert scores["AAPL"] == 0.0

    def test_positive_surprise_emits_zero(self):
        """Short edge must NOT fire on positive surprise."""
        e = self._edge({"AAPL": _calendar(0.15, "2024-05-20")})
        score = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-25"))
        assert score == 0.0

    def test_negative_surprise_emits_negative_score(self):
        """Negative surprise → short signal (negative score)."""
        e = self._edge({"AAPL": _calendar(-0.15, "2024-05-20")})
        score = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-25"))
        assert score < 0.0

    def test_below_threshold_emits_zero(self):
        """Surprise magnitude below min_surprise_pct → zero."""
        e = self._edge({"AAPL": _calendar(-0.02, "2024-05-20")})
        score = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-25"))
        assert score == 0.0

    def test_larger_surprise_larger_magnitude(self):
        """Larger negative surprise should produce larger (more negative) score."""
        e_small = self._edge({"AAPL": _calendar(-0.06, "2024-05-20")})
        e_large = self._edge({"AAPL": _calendar(-0.25, "2024-05-20")})
        now = pd.Timestamp("2024-05-25")
        s_small = e_small._compute_one_signal("AAPL", now)
        s_large = e_large._compute_one_signal("AAPL", now)
        assert s_large < s_small  # more negative = stronger short

    def test_time_decay_reduces_score(self):
        """Score should be smaller (closer to zero) further from announcement."""
        e = self._edge({"AAPL": _calendar(-0.15, "2024-05-01")})
        score_close = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-05"))
        score_far = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-30"))
        assert score_close < 0.0   # both negative
        assert score_far < 0.0
        assert score_close < score_far  # score_close is more negative (larger magnitude)

    def test_beyond_hold_window_emits_zero(self):
        """Past the hold window, signal should be zero."""
        e = self._edge({"AAPL": _calendar(-0.20, "2024-03-01")})
        # hold_calendar_days=63; 2024-03-01 + 63 days = 2024-05-03
        score = e._compute_one_signal("AAPL", pd.Timestamp("2024-06-01"))
        assert score == 0.0

    def test_edge_id_is_correct(self):
        assert PEADShortEdge.EDGE_ID == "pead_short_v1"

    def test_score_bounded_by_short_score_max(self):
        """Score magnitude must not exceed short_score_max (0.30 default)."""
        e = self._edge({"AAPL": _calendar(-0.50, "2024-05-20")})
        score = e._compute_one_signal("AAPL", pd.Timestamp("2024-05-21"))
        assert abs(score) <= 0.30 + 1e-9


# =============================================================================
# PEADPreDriftEdge tests
# =============================================================================

class TestPEADPreDriftEdge:

    def _edge(self, calendar: dict | None = None) -> PEADPreDriftEdge:
        e = PEADPreDriftEdge()
        e._calendars_loaded = True
        e._calendars = calendar if calendar is not None else {}
        return e

    def test_empty_cache_returns_zeros(self):
        e = self._edge({})
        prices = _price_series(50)
        data_map = {"AAPL": pd.DataFrame({"Close": prices.values}, index=prices.index)}
        scores = e.compute_signals(data_map, pd.Timestamp("2024-06-01"))
        assert scores["AAPL"] == 0.0

    def test_positive_surprise_low_predrift_fires(self):
        """Positive surprise + low pre-drift → positive score."""
        announcement = "2024-05-15"
        e = self._edge({"AAPL": _calendar(0.15, announcement)})
        # Flat prices before announcement (near-zero drift)
        prices = _price_series(n=60, drift=0.01, base=100.0)
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-05-20"),
            price_series=prices,
        )
        assert score > 0.0

    def test_positive_surprise_high_predrift_filtered(self):
        """Positive surprise + large pre-announcement drift → zero (already priced)."""
        announcement = "2024-05-15"
        e = self._edge({"AAPL": _calendar(0.15, announcement)})
        # Large pre-drift (20% run-up before announcement)
        prices = _price_series(n=60, drift=0.25, base=100.0)
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-05-20"),
            price_series=prices,
        )
        assert score == 0.0

    def test_no_price_data_fires_without_filter(self):
        """When price_series is None, skip pre-drift filter and fire normally."""
        announcement = "2024-05-15"
        e = self._edge({"AAPL": _calendar(0.15, announcement)})
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-05-20"),
            price_series=None,
        )
        assert score > 0.0

    def test_negative_surprise_returns_zero(self):
        """Long-only variant — no short signals."""
        announcement = "2024-05-15"
        e = self._edge({"AAPL": _calendar(-0.20, announcement)})
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-05-20"),
            price_series=None,
        )
        assert score == 0.0

    def test_edge_id_is_correct(self):
        assert PEADPreDriftEdge.EDGE_ID == "pead_predrift_v1"

    def test_score_bounded_by_long_score_max(self):
        """Score must not exceed long_score_max (0.5 default)."""
        announcement = "2024-05-15"
        e = self._edge({"AAPL": _calendar(1.50, announcement)})
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-05-16"),
            price_series=None,
        )
        assert score <= 0.5 + 1e-9

    def test_beyond_hold_window_emits_zero(self):
        announcement = "2024-03-01"
        e = self._edge({"AAPL": _calendar(0.20, announcement)})
        score = e._compute_one_signal(
            "AAPL",
            pd.Timestamp("2024-06-01"),
            price_series=None,
        )
        assert score == 0.0
