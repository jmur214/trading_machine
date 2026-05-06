"""Tests for engines.data_manager.universe_resolver.

The resolver is the bridge between the survivorship-aware membership
loader (universe.py) and the orchestration layer's static-list
contract. These tests exercise:
  * Pure-function helpers (``annual_anchor_dates``, ``union_active_over_window``).
  * The flag-gated resolver itself (``resolve_universe``) including the
    fallback-to-static branches.

All tests run offline — fixture membership frames are constructed
inline. Live Wikipedia / live parquet are out of scope here; that is
covered in test_universe.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.data_manager.universe import (  # noqa: E402
    annual_anchor_dates,
    union_active_over_window,
)
from engines.data_manager.universe_resolver import (  # noqa: E402
    DEFAULT_ESSENTIAL_TICKERS,
    discover_cached_tickers,
    resolve_universe,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _membership(rows):
    df = pd.DataFrame(rows, columns=[
        "ticker", "name", "sector", "included_from", "included_until",
    ])
    for col in ("included_from", "included_until"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# annual_anchor_dates
# ---------------------------------------------------------------------------
class TestAnnualAnchorDates:
    def test_one_anchor_per_year_inclusive(self):
        anchors = annual_anchor_dates("2021-03-15", "2024-08-30")
        years = [a.year for a in anchors]
        assert years == [2021, 2022, 2023, 2024]
        assert all(a.month == 1 and a.day == 1 for a in anchors)

    def test_single_year(self):
        anchors = annual_anchor_dates("2023-06-01", "2023-12-31")
        assert [a.year for a in anchors] == [2023]

    def test_empty_when_end_before_start(self):
        assert annual_anchor_dates("2024-01-01", "2023-12-31") == []


# ---------------------------------------------------------------------------
# union_active_over_window
# ---------------------------------------------------------------------------
class TestUnionActiveOverWindow:
    def test_union_picks_up_added_and_removed(self):
        df = _membership([
            # AAA: in 2020-2022
            {"ticker": "AAA", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": "2022-06-15"},
            # BBB: in throughout
            {"ticker": "BBB", "name": None, "sector": None,
             "included_from": "2019-01-01", "included_until": pd.NaT},
            # CCC: added 2023
            {"ticker": "CCC", "name": None, "sector": None,
             "included_from": "2023-03-01", "included_until": pd.NaT},
        ])
        # Window 2021-2024 → annual anchors 2021,2022,2023,2024 →
        # AAA active on 2021, 2022 anchors; CCC active on 2023, 2024.
        out = union_active_over_window(df, "2021-01-01", "2024-12-31")
        assert out == ["AAA", "BBB", "CCC"]

    def test_union_respects_explicit_anchors(self):
        df = _membership([
            {"ticker": "AAA", "name": None, "sector": None,
             "included_from": "2018-01-01", "included_until": "2020-12-31"},
            {"ticker": "BBB", "name": None, "sector": None,
             "included_from": "2022-01-01", "included_until": pd.NaT},
        ])
        # Window 2018-2024 (all years), but explicit anchors only 2022 →
        # only BBB.
        out = union_active_over_window(
            df, "2018-01-01", "2024-12-31", anchor_dates=["2022-06-01"]
        )
        assert out == ["BBB"]

    def test_empty_frame_returns_empty(self):
        df = _membership([])
        assert union_active_over_window(df, "2021-01-01", "2024-12-31") == []

    def test_output_is_sorted(self):
        df = _membership([
            {"ticker": "ZZZ", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "AAA", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "MMM", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
        ])
        out = union_active_over_window(df, "2021-01-01", "2022-12-31")
        assert out == sorted(out) == ["AAA", "MMM", "ZZZ"]


# ---------------------------------------------------------------------------
# resolve_universe
# ---------------------------------------------------------------------------
class TestResolveUniverse:
    def test_flag_off_returns_static_verbatim(self, tmp_path: Path):
        tickers, info = resolve_universe(
            static_tickers=["AAPL", "MSFT", "ZZZZ"],
            start="2021-01-01",
            end="2024-12-31",
            use_historical=False,
            cache_dir=tmp_path,
        )
        assert tickers == ["AAPL", "MSFT", "ZZZZ"]
        assert info["mode"] == "static"
        assert info["n_static"] == 3
        assert info["fallback_reason"] is None

    def test_flag_on_no_parquet_falls_back(self, tmp_path: Path):
        # No data/universe/sp500_membership.parquet under tmp_path.
        tickers, info = resolve_universe(
            static_tickers=["AAPL", "MSFT"],
            start="2021-01-01",
            end="2024-12-31",
            use_historical=True,
            cache_dir=tmp_path,
        )
        assert tickers == ["AAPL", "MSFT"]
        assert info["mode"] == "fallback_to_static"
        assert info["fallback_reason"] is not None
        assert "missing membership parquet" in info["fallback_reason"]

    def test_flag_on_with_parquet_returns_historical_union(self, tmp_path: Path):
        # Stage a fixture parquet that the resolver will pick up.
        uni_dir = tmp_path / "universe"
        uni_dir.mkdir(parents=True)
        df = _membership([
            {"ticker": "AAA", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "BBB", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "DELISTED", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": "2022-06-01"},
        ])
        df.to_parquet(uni_dir / "sp500_membership.parquet", index=False)

        tickers, info = resolve_universe(
            static_tickers=["AAA", "STATIC_ONLY"],
            start="2021-01-01",
            end="2024-12-31",
            use_historical=True,
            cache_dir=tmp_path,
        )
        # Survivorship-aware union should include DELISTED (active on
        # 2021/2022 anchors), AAA, BBB, plus all essentials.
        assert "DELISTED" in tickers
        assert "AAA" in tickers
        assert "BBB" in tickers
        # Default essentials are added even though they aren't in the
        # membership table (they're index ETFs).
        for essential in DEFAULT_ESSENTIAL_TICKERS:
            assert essential in tickers
        # Static-only ticker (not in membership table, not essential)
        # is NOT carried through.
        assert "STATIC_ONLY" not in tickers
        assert info["mode"] == "historical"
        assert info["n_historical_union"] == 3  # AAA, BBB, DELISTED
        assert info["n_after_essentials"] >= info["n_historical_union"]
        # Annual anchors 2021,2022,2023,2024.
        assert len(info["anchor_dates"]) == 4

    def test_flag_on_with_available_filter_drops_uncached(
        self, tmp_path: Path
    ):
        uni_dir = tmp_path / "universe"
        uni_dir.mkdir(parents=True)
        df = _membership([
            {"ticker": "HAVE_CSV", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "NO_CSV", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
        ])
        df.to_parquet(uni_dir / "sp500_membership.parquet", index=False)

        tickers, info = resolve_universe(
            static_tickers=["HAVE_CSV"],
            start="2021-01-01",
            end="2024-12-31",
            use_historical=True,
            cache_dir=tmp_path,
            available_filter=["HAVE_CSV", "SPY"],  # NO_CSV missing
        )
        assert "HAVE_CSV" in tickers
        assert "NO_CSV" not in tickers
        assert "NO_CSV" in info["missing_from_cache"]
        assert info["n_after_available_filter"] < info["n_after_essentials"]

    def test_resolved_output_is_sorted_and_deduped(self, tmp_path: Path):
        uni_dir = tmp_path / "universe"
        uni_dir.mkdir(parents=True)
        df = _membership([
            {"ticker": "ZZZ", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "SPY", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
            {"ticker": "AAA", "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT},
        ])
        df.to_parquet(uni_dir / "sp500_membership.parquet", index=False)

        tickers, _ = resolve_universe(
            static_tickers=[],
            start="2021-01-01",
            end="2022-12-31",
            use_historical=True,
            cache_dir=tmp_path,
        )
        # SPY appears in BOTH membership AND essentials → must be deduped.
        assert tickers.count("SPY") == 1
        assert tickers == sorted(tickers)


# ---------------------------------------------------------------------------
# discover_cached_tickers
# ---------------------------------------------------------------------------
class TestDiscoverCachedTickers:
    def test_finds_csv_files_with_correct_suffix(self, tmp_path: Path):
        proc = tmp_path / "processed"
        proc.mkdir()
        (proc / "AAPL_1d.csv").write_text("Date,Close\n")
        (proc / "MSFT_1d.csv").write_text("Date,Close\n")
        (proc / "AAPL_1m.csv").write_text("Date,Close\n")  # different timeframe
        (proc / "junk.txt").write_text("nope")

        out = discover_cached_tickers(tmp_path, timeframe="1d")
        assert out == ["AAPL", "MSFT"]

    def test_missing_processed_returns_empty(self, tmp_path: Path):
        out = discover_cached_tickers(tmp_path, timeframe="1d")
        assert out == []


# ---------------------------------------------------------------------------
# Determinism contract — same input must yield bitwise-identical output
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_same_inputs_yield_identical_output(self, tmp_path: Path):
        uni_dir = tmp_path / "universe"
        uni_dir.mkdir(parents=True)
        df = _membership([
            {"ticker": tk, "name": None, "sector": None,
             "included_from": "2020-01-01", "included_until": pd.NaT}
            for tk in ["BBB", "AAA", "CCC", "FOO", "BAR"]
        ])
        df.to_parquet(uni_dir / "sp500_membership.parquet", index=False)

        out1, info1 = resolve_universe(
            static_tickers=["AAA"],
            start="2021-01-01",
            end="2023-12-31",
            use_historical=True,
            cache_dir=tmp_path,
        )
        out2, info2 = resolve_universe(
            static_tickers=["AAA"],
            start="2021-01-01",
            end="2023-12-31",
            use_historical=True,
            cache_dir=tmp_path,
        )
        assert out1 == out2
        # info dicts diff only on dynamic-typed fields like list ordering;
        # the load-bearing scalars must match.
        for k in (
            "mode", "n_static", "n_historical_union",
            "n_after_essentials", "n_after_available_filter",
            "anchor_dates",
        ):
            assert info1[k] == info2[k]
