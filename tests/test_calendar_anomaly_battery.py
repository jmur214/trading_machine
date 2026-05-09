"""Tests for the calendar anomaly battery (T-2026-05-09-014).

Covers all 7 features in `core.feature_foundry.features.calendar`:
  fomc_drift / pre_fomc_reduce / pre_holiday / sell_in_may_halloween /
  january_effect / triple_witching_premium / tax_loss_season.

Pattern follows tests/test_feature_foundry.py — autouse `reset_registries`
fixture that snapshots the global Foundry registry, runs in a clean state,
restores at teardown.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.feature_foundry import get_feature_registry, get_source_registry  # noqa: E402
from core.feature_foundry.features.calendar import (  # noqa: E402
    fomc_drift,
    pre_fomc_reduce,
    pre_holiday,
    sell_in_may_halloween,
    january_effect,
    triple_witching_premium,
    tax_loss_season,
    FOMC_DATES,
    US_MARKET_HOLIDAYS,
)


CALENDAR_FEATURE_IDS = [
    "fomc_drift",
    "pre_fomc_reduce",
    "pre_holiday",
    "sell_in_may_halloween",
    "january_effect",
    "triple_witching_premium",
    "tax_loss_season",
]


@pytest.fixture(autouse=True)
def reset_registries():
    """Snapshot/restore Foundry registries — copies test_feature_foundry.py
    discipline so cross-file feature registrations survive."""
    import core.feature_foundry.features  # noqa: F401  trigger self-register
    import core.feature_foundry.sources    # noqa: F401  trigger self-register
    feat_reg = get_feature_registry()
    src_reg = get_source_registry()
    saved_feats = dict(feat_reg._features)
    saved_srcs = dict(src_reg._sources) if hasattr(src_reg, "_sources") else None
    feat_reg.clear()
    src_reg.clear()
    feat_reg._features.update(saved_feats)
    if saved_srcs is not None:
        src_reg._sources.update(saved_srcs)
    try:
        yield
    finally:
        feat_reg.clear()
        feat_reg._features.update(saved_feats)
        if saved_srcs is not None:
            src_reg.clear()
            src_reg._sources.update(saved_srcs)
        else:
            src_reg.clear()


# ---------------------------------------------------------------------------
# Registration + tier checks
# ---------------------------------------------------------------------------

def test_all_features_register_at_tier_A():
    """Every feature in the battery must register at tier A."""
    reg = get_feature_registry()
    for fid in CALENDAR_FEATURE_IDS:
        feat = reg._features.get(fid)
        assert feat is not None, (
            f"Calendar feature {fid!r} did not register. Verify the "
            f"`from . import calendar` line in features/__init__.py."
        )
        assert feat.tier == "A", (
            f"Calendar feature {fid!r} has tier={feat.tier!r}; expected 'A' "
            f"per T-014 spec."
        )


def test_calendar_features_are_ticker_independent():
    """Six of the seven are pure-calendar (same value for any ticker on the
    same date). tax_loss_season is excluded — it consumes per-ticker close
    series. T-013's empirical-detection caching depends on this ticker-
    independence holding for the 6 pure-calendar features."""
    reg = get_feature_registry()
    pure_calendar_ids = [fid for fid in CALENDAR_FEATURE_IDS
                         if fid != "tax_loss_season"]
    sample_dates = [date(2024, 1, 31),       # FOMC
                    date(2024, 7, 3),        # pre-July-4
                    date(2024, 5, 15),       # mid-May
                    date(2024, 1, 3),        # 2nd trading day of Jan
                    date(2024, 6, 21),       # 3rd Friday of Jun (triple witching)
                    date(2024, 12, 31)]      # year-end
    for fid in pure_calendar_ids:
        feat = reg._features[fid]
        for dt in sample_dates:
            v_aapl = feat("AAPL", dt)
            v_msft = feat("MSFT", dt)
            assert v_aapl == v_msft, (
                f"Pure-calendar feature {fid!r} returned different values "
                f"for AAPL vs MSFT on {dt}: {v_aapl} vs {v_msft}. This breaks "
                f"T-013's empirical-detection cache."
            )


# ---------------------------------------------------------------------------
# fomc_drift
# ---------------------------------------------------------------------------

def test_fomc_drift_known_dates():
    # 2024-01-31 is an FOMC announcement day — the day BEFORE should fire.
    assert fomc_drift("AAPL", date(2024, 1, 30)) == 1.0
    # 2024-01-31 itself — should NOT fire (we're ON the day, not before).
    assert fomc_drift("AAPL", date(2024, 1, 31)) == 0.0
    # Random non-pre-FOMC weekday — 0.0
    assert fomc_drift("AAPL", date(2024, 5, 15)) == 0.0


def test_pre_fomc_reduce_known_dates():
    # 2024-01-31 is FOMC — 1.0
    assert pre_fomc_reduce("AAPL", date(2024, 1, 31)) == 1.0
    # Day before — 0.0
    assert pre_fomc_reduce("AAPL", date(2024, 1, 30)) == 0.0
    # 2022-06-15 (well-known mid-cycle 75bp hike) — 1.0
    assert pre_fomc_reduce("AAPL", date(2022, 6, 15)) == 1.0


def test_fomc_dates_list_is_non_empty():
    """Sanity — the hardcoded list must have at least 8 entries per year
    for 2024 and 2025 (the years downstream measurements run on)."""
    dates_2024 = [d for d in FOMC_DATES if d.year == 2024]
    dates_2025 = [d for d in FOMC_DATES if d.year == 2025]
    assert len(dates_2024) >= 8, f"FOMC 2024 dates: {dates_2024}"
    assert len(dates_2025) >= 8, f"FOMC 2025 dates: {dates_2025}"


# ---------------------------------------------------------------------------
# pre_holiday
# ---------------------------------------------------------------------------

def test_pre_holiday_known_dates():
    # July 3, 2024 is the trading day before July 4, 2024 (Thursday holiday)
    assert pre_holiday("AAPL", date(2024, 7, 3)) == 1.0
    # July 4, 2024 itself is a holiday — 0.0 (function returns 0 on
    # non-trading days; meta-learner shouldn't see a signal AT the holiday)
    assert pre_holiday("AAPL", date(2024, 7, 4)) == 0.0
    # Random May Tuesday — 0.0
    assert pre_holiday("AAPL", date(2024, 5, 14)) == 0.0


def test_pre_holiday_handles_year_boundaries():
    """Edge cases: Christmas Day adjacent to weekend; New Year's Day
    on weekend → observed on Monday."""
    # 2023-12-25 was Monday, so 2023-12-22 (Friday) is the trading day
    # before Christmas Eve weekend → pre-holiday day relative to 12/25.
    assert pre_holiday("AAPL", date(2023, 12, 22)) == 1.0
    # 2025-12-25 is Thursday → Wed Dec 24 is the pre-holiday day.
    # (Dec 24 is a half-day NYSE session but still a trading day; it's the
    # day immediately before the Christmas market closure.)
    assert pre_holiday("AAPL", date(2025, 12, 24)) == 1.0
    # 2022-01-01 was a Saturday → NOT observed by NYSE (per the holiday
    # list note); pre_holiday for Dec 31, 2021 should NOT fire on Jan 1
    # — but Dec 31, 2021 is a Friday and the weekend gap (Sat/Sun) doesn't
    # contain a market holiday, so output is 0.0.
    assert pre_holiday("AAPL", date(2021, 12, 31)) == 0.0


# ---------------------------------------------------------------------------
# sell_in_may_halloween
# ---------------------------------------------------------------------------

def test_sell_in_may_halloween_known_dates():
    # November through April = "in" half = 1.0
    assert sell_in_may_halloween("AAPL", date(2024, 1, 15)) == 1.0
    assert sell_in_may_halloween("AAPL", date(2024, 4, 30)) == 1.0
    assert sell_in_may_halloween("AAPL", date(2024, 11, 1)) == 1.0
    assert sell_in_may_halloween("AAPL", date(2024, 12, 31)) == 1.0
    # May through October = "out" half = 0.0
    assert sell_in_may_halloween("AAPL", date(2024, 5, 1)) == 0.0
    assert sell_in_may_halloween("AAPL", date(2024, 7, 4)) == 0.0
    assert sell_in_may_halloween("AAPL", date(2024, 10, 31)) == 0.0


# ---------------------------------------------------------------------------
# january_effect
# ---------------------------------------------------------------------------

def test_january_effect_known_dates():
    # 2024-01-02 was the first trading day of 2024 (Jan 1 was a Monday holiday)
    assert january_effect("AAPL", date(2024, 1, 2)) == 1.0
    # 2024-01-08 should also fire — by Mon 1/8 we've had Tue 1/2 + Wed 1/3 +
    # Thu 1/4 + Fri 1/5 = 4 trading days through 1/5, so 1/8 (Mon) is the 5th.
    assert january_effect("AAPL", date(2024, 1, 8)) == 1.0
    # 2024-01-09 (Tuesday) is the 6th trading day — should NOT fire.
    assert january_effect("AAPL", date(2024, 1, 9)) == 0.0
    # February — 0.0
    assert january_effect("AAPL", date(2024, 2, 1)) == 0.0


# ---------------------------------------------------------------------------
# triple_witching_premium
# ---------------------------------------------------------------------------

def test_triple_witching_premium_known_dates():
    # Q1 2024 triple witching = 3rd Friday of March 2024 = 2024-03-15
    assert triple_witching_premium("AAPL", date(2024, 3, 15)) == 1.0
    # Q2 2024 triple witching = 3rd Friday of June 2024 = 2024-06-21
    assert triple_witching_premium("AAPL", date(2024, 6, 21)) == 1.0
    # Other Friday in March — should NOT fire.
    assert triple_witching_premium("AAPL", date(2024, 3, 22)) == 0.0
    # Random Tuesday — 0.0
    assert triple_witching_premium("AAPL", date(2024, 6, 25)) == 0.0
    # 3rd Friday of Apr (not a quad-end month) — 0.0
    assert triple_witching_premium("AAPL", date(2024, 4, 19)) == 0.0


# ---------------------------------------------------------------------------
# tax_loss_season — ticker-dependent
# ---------------------------------------------------------------------------

def test_tax_loss_season_outside_window_returns_zero():
    """Outside Dec 10-24, tax_loss_season returns 0.0 unconditionally —
    no ticker lookback needed."""
    assert tax_loss_season("AAPL", date(2024, 11, 30)) == 0.0
    assert tax_loss_season("AAPL", date(2024, 12, 1)) == 0.0
    assert tax_loss_season("AAPL", date(2024, 12, 9)) == 0.0
    assert tax_loss_season("AAPL", date(2024, 12, 25)) == 0.0
    assert tax_loss_season("AAPL", date(2024, 12, 31)) == 0.0


def test_tax_loss_season_returns_none_when_no_data():
    """Inside the Dec 10-24 window with no ticker close data, returns
    None (abstain). 'XXXX' is a sentinel that won't be in any local CSV."""
    out = tax_loss_season("XXXX_NONEXISTENT_TICKER", date(2024, 12, 15))
    assert out is None


def test_tax_loss_season_directionality_with_synthetic(tmp_path, monkeypatch):
    """Synthesize close-price series for a winner ticker (positive
    trailing return) and a loser ticker (negative trailing return);
    expect +1.0 and -1.0 respectively in the Dec 10-24 window."""
    from core.feature_foundry.sources import local_ohlcv

    # Build a 1-year daily close-price series: winner = monotone-up,
    # loser = monotone-down. These bypass the local CSV cache by injecting
    # directly into the in-process _CLOSE_CACHE dict.
    idx = pd.date_range("2024-01-02", "2024-12-30", freq="B").date
    s_winner = pd.Series([100.0 * (1.001 ** i) for i in range(len(idx))],
                         index=idx)
    s_loser = pd.Series([100.0 * (0.999 ** i) for i in range(len(idx))],
                        index=idx)

    monkeypatch.setitem(local_ohlcv._CLOSE_CACHE, "WINNER", s_winner)
    monkeypatch.setitem(local_ohlcv._CLOSE_CACHE, "LOSER", s_loser)

    # 2024-12-15 is inside the Dec 10-24 window
    assert tax_loss_season("WINNER", date(2024, 12, 15)) == 1.0
    assert tax_loss_season("LOSER", date(2024, 12, 15)) == -1.0
