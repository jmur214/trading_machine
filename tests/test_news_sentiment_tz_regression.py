"""Regression test for tz handling in news_sentiment_v2.

Audit verdict: NO_BUG_FOUND. NewsSentimentEdge does NOT use yfinance —
it reads news from CSVs in `data/intel/history/`. Date arithmetic
goes through `(now - timedelta(days=i)).date()` and `str(now.date())`,
both of which silently strip tz on tz-aware inputs. There is no
tz-aware-vs-tz-naive comparison anywhere in the edge.

This test locks the no-raise invariant in place, mirroring the
earnings_vol regression test pattern. If anyone later introduces a
direct yfinance call or a tz-comparison, this test will fire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.engine_a_alpha.edges.news_sentiment_edge import NewsSentimentEdge


def _make_data_map():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    rng = np.random.default_rng(0)
    close = 100 * (1.0 + rng.normal(0.001, 0.012, 200)).cumprod()
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )
    return {"AAPL": df}


def test_news_sentiment_compute_signals_does_not_raise_on_tz_naive_timestamp():
    edge = NewsSentimentEdge()
    edge.data_cache = {}
    edge.macro_cache = {}
    edge.velocity_cache = {}
    edge.history_loaded = False

    now = pd.Timestamp("2024-09-15")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores


def test_news_sentiment_compute_signals_does_not_raise_on_tz_aware_timestamp():
    """Even though the edge has no tz comparisons today, exercise the
    tz-aware branch so any future regression that introduces one fires
    immediately."""
    edge = NewsSentimentEdge()
    edge.data_cache = {}
    edge.macro_cache = {}
    edge.velocity_cache = {}
    edge.history_loaded = False

    now = pd.Timestamp("2024-09-15", tz="America/New_York")
    scores = edge.compute_signals(_make_data_map(), now)
    assert isinstance(scores, dict)
    assert "AAPL" in scores
