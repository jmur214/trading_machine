"""EarningsCalendar — DataSource over yfinance-cached earnings parquets.

Reads `data/earnings/<TICKER>_calendar.parquet`, the project's per-ticker
earnings cache populated by `EarningsDataManager` (yfinance backend after
the 2026-04-25 swap from Finnhub — see project memory). Each parquet has
`announcement_date` as the index plus columns including `eps_actual`,
`eps_estimate`, `eps_surprise_pct`.

Two surfaces:

  * `EarningsCalendar.fetch(start, end)` — long-format frame across all
    discovered tickers, satisfying the substrate's DataSource contract.
  * `next_announcements(ticker)` — per-ticker DatetimeIndex of
    announcement dates, lazily loaded and cached in-process. Used by
    feature modules.

Point-in-time discipline: scheduled earnings dates are public knowledge
days/weeks in advance, so `proximity` features can legitimately look at
the *next* announcement date as of `dt`. Features must NEVER consume
the announcement-day surprise/actuals before the event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..data_source import DataSource, get_source_registry


REQUIRED_COLUMNS = {"symbol", "eps_actual", "eps_estimate", "eps_surprise_pct"}


@dataclass
class EarningsCalendar(DataSource):
    name: str = "earnings_calendar"
    license: str = "internal"
    latency: timedelta = field(default_factory=lambda: timedelta(days=14))
    point_in_time_safe: bool = True
    data_root: Path = field(default_factory=lambda: Path("data/earnings"))

    def _read_one(self, path: Path) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_parquet(path)
        except Exception:
            return None
        if df.empty:
            return None
        df = df.copy()
        df["announcement_date"] = pd.to_datetime(df.index)
        return df

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        files = sorted(self.data_root.glob("*_calendar.parquet"))
        frames = []
        for p in files:
            df = self._read_one(p)
            if df is None:
                continue
            mask = (
                (df["announcement_date"].dt.date >= start)
                & (df["announcement_date"].dt.date <= end)
            )
            sub = df[mask]
            if not sub.empty:
                frames.append(sub)
        if not frames:
            return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))
        return pd.concat(frames, ignore_index=True)

    def schema_check(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return True
        return REQUIRED_COLUMNS.issubset(set(df.columns))

    def freshness_check(self) -> bool:
        files = list(self.data_root.glob("*_calendar.parquet"))
        if not files:
            return False
        latest = max(f.stat().st_mtime for f in files)
        latest_dt = datetime.fromtimestamp(latest).date()
        return (date.today() - latest_dt) <= self.latency


_DATES_CACHE: Dict[str, pd.DatetimeIndex] = {}


def announcement_dates(ticker: str) -> Optional[pd.DatetimeIndex]:
    """Cached per-ticker DatetimeIndex of earnings announcement dates,
    sorted ascending. Returns None if no source registered or no parquet."""
    if ticker in _DATES_CACHE:
        idx = _DATES_CACHE[ticker]
        return idx if len(idx) else None
    src = get_source_registry().get("earnings_calendar")
    if src is None or not isinstance(src, EarningsCalendar):
        return None
    path = src.data_root / f"{ticker}_calendar.parquet"
    if not path.exists():
        _DATES_CACHE[ticker] = pd.DatetimeIndex([])
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        _DATES_CACHE[ticker] = pd.DatetimeIndex([])
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(df.index)).sort_values()
    _DATES_CACHE[ticker] = idx
    return idx if len(idx) else None


def clear_earnings_cache() -> None:
    """Test helper — drop the in-process per-ticker cache."""
    _DATES_CACHE.clear()


# Self-register a default instance at import time.
get_source_registry().register(EarningsCalendar())
