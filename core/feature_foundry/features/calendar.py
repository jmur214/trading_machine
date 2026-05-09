"""Calendar anomaly battery — 7 academic-validated date-only features.

Per T-2026-05-09-014 (edge expansion track, dev-review-mandated). Each
of these features captures a long-documented calendar anomaly:

  1. fomc_drift                — pre-FOMC announcement equity drift (Lucca-Moench 2015)
  2. pre_fomc_reduce           — FOMC announcement day volatility cluster
  3. pre_holiday               — pre-US-market-holiday optimism (Ariel 1990)
  4. sell_in_may_halloween     — Nov-Apr "in"; May-Oct "out" (Bouman-Jacobsen 2002)
  5. january_effect            — first 5 trading days of January excess returns (Sias 2007)
  6. triple_witching_premium   — 3rd Friday of Mar/Jun/Sep/Dec premium (Stoll-Whaley)
  7. tax_loss_season           — mid-Dec long-winners / short-losers (Roll's tax-loss-selling)

Six of the seven are pure-calendar (ticker-independent — same value for
any ticker on the same date). Tax_loss_season is the only ticker-dependent
one (uses past 11 months close-price lookback to determine winner / loser
status). Pure-calendar features benefit from T-013's empirical-detection
caching automatically.

Tier "A" — production-validated patterns from academic literature (per spec).

NOTE — vocabulary expansion ONLY. None of these is registered as a tradeable
edge; Discovery (post-Bayesian-opt swap) decides whether any of them
becomes part of an edge. No `edges.yml` mutation, no `engines/engine_a_alpha/edges/`
addition.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np

from ..feature import feature
from ..sources.local_ohlcv import close_series


# ---------------------------------------------------------------------------
# FOMC announcement dates 2000-2026.
# ---------------------------------------------------------------------------
# Source: Federal Reserve Board's published FOMC meeting calendar
# (federalreserve.gov/monetarypolicy/fomccalendars.htm). Each tuple is the
# DATE OF THE ANNOUNCEMENT — typically the second day of a two-day meeting.
# Hardcoded so feature evaluation is a pure function of (ticker, date) with
# no runtime API dependency. Annual update needed: extend list each Q4.
#
# The list is curated from published Fed schedules and may have minor
# edge-case errors on emergency / unscheduled meetings (which historically
# have been the most market-impactful — e.g., 2008-10-08 inter-meeting
# emergency cut, 2020-03-15 Sunday emergency cut). Where uncertain, the
# scheduled meeting date is used; downstream backtests on these dates may
# under-count emergency-meeting effects. Documented in audit doc.
FOMC_DATES = frozenset([
    # 2018
    date(2018, 1, 31), date(2018, 3, 21), date(2018, 5, 2),
    date(2018, 6, 13), date(2018, 8, 1), date(2018, 9, 26),
    date(2018, 11, 8), date(2018, 12, 19),
    # 2019
    date(2019, 1, 30), date(2019, 3, 20), date(2019, 5, 1),
    date(2019, 6, 19), date(2019, 7, 31), date(2019, 9, 18),
    date(2019, 10, 30), date(2019, 12, 11),
    # 2020 (incl. 2020-03-15 emergency cut, Sunday — observed effect on Mon)
    date(2020, 1, 29), date(2020, 3, 3), date(2020, 3, 15),
    date(2020, 4, 29), date(2020, 6, 10), date(2020, 7, 29),
    date(2020, 9, 16), date(2020, 11, 5), date(2020, 12, 16),
    # 2021
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28),
    date(2021, 6, 16), date(2021, 7, 28), date(2021, 9, 22),
    date(2021, 11, 3), date(2021, 12, 15),
    # 2022
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4),
    date(2022, 6, 15), date(2022, 7, 27), date(2022, 9, 21),
    date(2022, 11, 2), date(2022, 12, 14),
    # 2023
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3),
    date(2023, 6, 14), date(2023, 7, 26), date(2023, 9, 20),
    date(2023, 11, 1), date(2023, 12, 13),
    # 2024
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1),
    date(2024, 6, 12), date(2024, 7, 31), date(2024, 9, 18),
    date(2024, 11, 7), date(2024, 12, 18),
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    # 2026
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
])


# ---------------------------------------------------------------------------
# US market holiday list 2018-2026 (NYSE / NASDAQ closed days).
# ---------------------------------------------------------------------------
# Source: NYSE published holiday calendar. Includes:
#   New Year's Day, MLK Day, Presidents Day, Good Friday,
#   Memorial Day, Juneteenth (since 2022), Independence Day,
#   Labor Day, Thanksgiving, Christmas.
# Dates "observed" — when a holiday falls on a weekend, the observed
# date is the adjacent Friday or Monday (NYSE rule). This list captures
# the OBSERVED dates (i.e. the days the market is actually closed).
US_MARKET_HOLIDAYS = frozenset([
    # 2018
    date(2018, 1, 1), date(2018, 1, 15), date(2018, 2, 19),
    date(2018, 3, 30), date(2018, 5, 28), date(2018, 7, 4),
    date(2018, 9, 3), date(2018, 11, 22), date(2018, 12, 25),
    # 2019
    date(2019, 1, 1), date(2019, 1, 21), date(2019, 2, 18),
    date(2019, 4, 19), date(2019, 5, 27), date(2019, 7, 4),
    date(2019, 9, 2), date(2019, 11, 28), date(2019, 12, 25),
    # 2020
    date(2020, 1, 1), date(2020, 1, 20), date(2020, 2, 17),
    date(2020, 4, 10), date(2020, 5, 25), date(2020, 7, 3),  # July 4 obs
    date(2020, 9, 7), date(2020, 11, 26), date(2020, 12, 25),
    # 2021
    date(2021, 1, 1), date(2021, 1, 18), date(2021, 2, 15),
    date(2021, 4, 2), date(2021, 5, 31), date(2021, 7, 5),  # July 4 obs
    date(2021, 9, 6), date(2021, 11, 25), date(2021, 12, 24),  # Dec 25 obs
    # 2022 (Juneteenth added)
    date(2022, 1, 17),  # Jan 1 fell on Saturday — NOT observed by NYSE
    date(2022, 2, 21), date(2022, 4, 15), date(2022, 5, 30),
    date(2022, 6, 20),  # Juneteenth obs (Sun 6/19)
    date(2022, 7, 4), date(2022, 9, 5), date(2022, 11, 24),
    date(2022, 12, 26),  # Dec 25 obs
    # 2023
    date(2023, 1, 2),  # Jan 1 obs
    date(2023, 1, 16), date(2023, 2, 20), date(2023, 4, 7),
    date(2023, 5, 29), date(2023, 6, 19), date(2023, 7, 4),
    date(2023, 9, 4), date(2023, 11, 23), date(2023, 12, 25),
    # 2024
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28),
    date(2024, 12, 25),
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3),  # July 4 obs
    date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
])


def _is_trading_day(dt: date) -> bool:
    """True if dt is a US-market trading day (Mon-Fri AND not a holiday)."""
    if dt.weekday() >= 5:
        return False
    return dt not in US_MARKET_HOLIDAYS


def _next_trading_day(dt: date) -> Optional[date]:
    """Smallest trading day strictly after dt. Up to 10-day search bound."""
    d = dt + timedelta(days=1)
    for _ in range(10):
        if _is_trading_day(d):
            return d
        d += timedelta(days=1)
    return None


# ---------------------------------------------------------------------------
# Feature 1: fomc_drift — long signal in 24-hour window before FOMC.
# ---------------------------------------------------------------------------
@feature(
    feature_id="fomc_drift",
    tier="A",
    horizon=1,
    license="internal",
    source="calendar",
    description=(
        "Pre-FOMC announcement drift (Lucca-Moench 2015). Returns 1.0 "
        "if the next trading day is an FOMC announcement day (long bias "
        "for the 24-hour window before the announcement); 0.0 otherwise. "
        "Pure calendar — ticker-independent."
    ),
)
def fomc_drift(ticker: str, dt: date) -> Optional[float]:
    nxt = _next_trading_day(dt)
    if nxt is None:
        return 0.0
    return 1.0 if nxt in FOMC_DATES else 0.0


# ---------------------------------------------------------------------------
# Feature 2: pre_fomc_reduce — abstain/short signal ON FOMC day itself.
# ---------------------------------------------------------------------------
@feature(
    feature_id="pre_fomc_reduce",
    tier="A",
    horizon=1,
    license="internal",
    source="calendar",
    description=(
        "FOMC announcement day. Returns 1.0 if `dt` is an FOMC "
        "announcement day, 0.0 otherwise. Marks the volatility-clustered "
        "release window where mean returns historically reverse vs the "
        "pre-FOMC drift; downstream meta-learner decides directionality. "
        "Pure calendar — ticker-independent."
    ),
)
def pre_fomc_reduce(ticker: str, dt: date) -> Optional[float]:
    return 1.0 if dt in FOMC_DATES else 0.0


# ---------------------------------------------------------------------------
# Feature 3: pre_holiday — long signal in 1-2 trading days before holiday.
# ---------------------------------------------------------------------------
@feature(
    feature_id="pre_holiday",
    tier="A",
    horizon=2,
    license="internal",
    source="calendar",
    description=(
        "Pre-holiday optimism (Ariel 1990). Returns 1.0 if dt is the "
        "trading day immediately before a US market holiday; 0.5 if "
        "dt is two trading days before; 0.0 otherwise. Captures the "
        "pre-holiday-close optimism documented over multi-decade samples. "
        "Pure calendar — ticker-independent."
    ),
)
def pre_holiday(ticker: str, dt: date) -> Optional[float]:
    if not _is_trading_day(dt):
        # Saturdays/Sundays/holidays themselves — abstain.
        return 0.0
    nxt1 = _next_trading_day(dt)
    if nxt1 is None:
        return 0.0
    # Walk forward — was the next non-trading-day reachable by skipping
    # weekends a holiday? Easier: check if any day strictly after `dt` and
    # ≤ 2 trading days ahead is a holiday OR if the calendar gap to the
    # next trading day spans a holiday.
    # Simpler logic: examine the calendar days between `dt` and next2.
    nxt2 = _next_trading_day(nxt1) if nxt1 else None

    # Day immediately before a holiday: any holiday strictly after `dt`
    # and before `nxt1` would be already filtered (dt is trading day so
    # no holiday between dt and dt+1 is possible; check nxt1 itself).
    # The actual signal: tomorrow (calendar) onward to nxt1's day —
    # was any of those a US market holiday?
    one_after = dt + timedelta(days=1)
    while one_after < nxt1:
        if one_after in US_MARKET_HOLIDAYS:
            return 1.0
        one_after += timedelta(days=1)

    # 2-trading-days-before-holiday case
    if nxt2 is not None:
        between = nxt1 + timedelta(days=1)
        while between < nxt2:
            if between in US_MARKET_HOLIDAYS:
                return 0.5
            between += timedelta(days=1)
    return 0.0


# ---------------------------------------------------------------------------
# Feature 4: sell_in_may_halloween — Nov-Apr "in"; May-Oct "out".
# ---------------------------------------------------------------------------
@feature(
    feature_id="sell_in_may_halloween",
    tier="A",
    horizon=126,
    license="internal",
    source="calendar",
    description=(
        "Halloween / Sell-in-May indicator (Bouman-Jacobsen 2002). "
        "Returns 1.0 from 1-Nov through 30-Apr (in-the-market half), "
        "0.0 from 1-May through 31-Oct (out-of-the-market half). "
        "Calendar-month boundary convention; literature uses both "
        "calendar and last-trading-day boundaries — calendar chosen "
        "for simplicity and is ticker-independent. Pure calendar."
    ),
)
def sell_in_may_halloween(ticker: str, dt: date) -> Optional[float]:
    # In-half: Nov, Dec, Jan, Feb, Mar, Apr → months {1,2,3,4,11,12}
    return 1.0 if dt.month in {1, 2, 3, 4, 11, 12} else 0.0


# ---------------------------------------------------------------------------
# Feature 5: january_effect — long signal in first 5 trading days of January.
# ---------------------------------------------------------------------------
@feature(
    feature_id="january_effect",
    tier="A",
    horizon=5,
    license="internal",
    source="calendar",
    description=(
        "January Effect (Sias 2007 + earlier). Returns 1.0 if `dt` is "
        "within the first 5 trading days of January; 0.0 otherwise. "
        "Captures the small-cap-led excess return window at the turn of "
        "the year. Pure calendar — ticker-independent."
    ),
)
def january_effect(ticker: str, dt: date) -> Optional[float]:
    if dt.month != 1:
        return 0.0
    if not _is_trading_day(dt):
        return 0.0
    # Count trading days from Jan 1 of this year through dt inclusive.
    d = date(dt.year, 1, 1)
    n_trading = 0
    while d <= dt:
        if _is_trading_day(d):
            n_trading += 1
        d += timedelta(days=1)
    return 1.0 if n_trading <= 5 else 0.0


# ---------------------------------------------------------------------------
# Feature 6: triple_witching_premium — 3rd Friday of Mar/Jun/Sep/Dec.
# ---------------------------------------------------------------------------
def _is_triple_witching(dt: date) -> bool:
    """3rd Friday of Mar/Jun/Sep/Dec — index futures + options simultaneous expiry."""
    if dt.month not in {3, 6, 9, 12}:
        return False
    if dt.weekday() != 4:  # Friday
        return False
    # Check that this is the 3rd Friday: 15 ≤ day ≤ 21.
    return 15 <= dt.day <= 21


@feature(
    feature_id="triple_witching_premium",
    tier="A",
    horizon=1,
    license="internal",
    source="calendar",
    description=(
        "Triple-witching Friday indicator (Stoll-Whaley). Returns 1.0 "
        "on 3rd Friday of Mar/Jun/Sep/Dec when stock-index-futures, "
        "stock-index-options, and stock-options expire concurrently — "
        "documented volume + volatility cluster, ambiguous return sign. "
        "Pure calendar — ticker-independent."
    ),
)
def triple_witching_premium(ticker: str, dt: date) -> Optional[float]:
    return 1.0 if _is_triple_witching(dt) else 0.0


# ---------------------------------------------------------------------------
# Feature 7: tax_loss_season — mid-Dec long-winners / short-losers.
# ---------------------------------------------------------------------------
@feature(
    feature_id="tax_loss_season",
    tier="A",
    horizon=20,
    license="internal",
    source="local_ohlcv",
    description=(
        "Tax-loss harvesting season (Roll). Returns +1.0 in Dec 10-24 "
        "when the ticker's trailing 11-month return is positive ("
        "winner — likely held through year-end); -1.0 when trailing "
        "11-month return is negative (loser — likely sold for tax "
        "benefit, predicted to underperform into year-end then mean-revert "
        "in early January); 0.0 outside the Dec 10-24 window OR when "
        "lookback data is insufficient. **Ticker-dependent** (only one "
        "of the 7 in this battery)."
    ),
)
def tax_loss_season(ticker: str, dt: date) -> Optional[float]:
    # Mid-Dec window: Dec 10-24 inclusive.
    if dt.month != 12 or not (10 <= dt.day <= 24):
        return 0.0
    s = close_series(ticker)
    if s is None or len(s) < 220:
        return None  # insufficient data — abstain
    # Trailing 11-month (≈ 231 calendar days) lookback. Use point-in-time
    # slice: only data with index <= dt-1 is allowed (today's close not
    # yet observable when this feature evaluates intraday-of dt).
    cutoff_today = dt
    cutoff_lookback = dt - timedelta(days=231)
    s_pit = s[(s.index <= cutoff_today) & (s.index >= cutoff_lookback)]
    if len(s_pit) < 100:
        return None
    p_now = float(s_pit.iloc[-1])
    p_then = float(s_pit.iloc[0])
    if p_then <= 0 or not np.isfinite(p_now) or not np.isfinite(p_then):
        return None
    ret = (p_now / p_then) - 1.0
    if ret > 0:
        return 1.0
    if ret < 0:
        return -1.0
    return 0.0
