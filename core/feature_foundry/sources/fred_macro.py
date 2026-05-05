"""FREDMacro — DataSource over the project's per-series FRED parquets.

Reads `data/macro/<SERIES_ID>.parquet`, the project's FRED cache
populated by the macro data manager. Each parquet has a DatetimeIndex
named `date` and a single `value` column. Series in the cache include
VIXCLS, T10Y2Y, DGS10, UNRATE, etc.

Two surfaces:

  * `FREDMacro.fetch(start, end)` — long-format frame with ['series_id',
    'date', 'value'] across all discovered parquets. Satisfies the
    DataSource contract.
  * `series(series_id)` — per-series pandas Series indexed by
    `datetime.date`, lazily loaded and cached in-process.

Point-in-time discipline: FRED publishes most series with 1-3 business
day lag. VIXCLS is daily close data published end-of-day on the same
trading day. Features should align via `s[s.index <= dt]`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..data_source import DataSource, get_source_registry


REQUIRED_COLUMNS = {"series_id", "date", "value"}


@dataclass
class FREDMacro(DataSource):
    name: str = "fred_macro"
    license: str = "public"
    latency: timedelta = field(default_factory=lambda: timedelta(days=5))
    point_in_time_safe: bool = True
    data_root: Path = field(default_factory=lambda: Path("data/macro"))

    def _read_one(self, path: Path) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_parquet(path)
        except Exception:
            return None
        if df.empty or "value" not in df.columns:
            return None
        out = df.reset_index().rename(columns={df.index.name or "index": "date"})
        out["series_id"] = path.stem
        return out[["series_id", "date", "value"]]

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        files = sorted(p for p in self.data_root.glob("*.parquet")
                       if not p.name.startswith("_"))
        frames = []
        for p in files:
            df = self._read_one(p)
            if df is None:
                continue
            mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
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
        files = [p for p in self.data_root.glob("*.parquet")
                 if not p.name.startswith("_")]
        if not files:
            return False
        latest = max(f.stat().st_mtime for f in files)
        latest_dt = datetime.fromtimestamp(latest).date()
        return (date.today() - latest_dt) <= self.latency


_SERIES_CACHE: Dict[str, pd.Series] = {}


def series(series_id: str) -> Optional[pd.Series]:
    """Cached per-series value Series indexed by `date`. Returns None
    if no source registered or no parquet for the series."""
    if series_id in _SERIES_CACHE:
        s = _SERIES_CACHE[series_id]
        return s if not s.empty else None
    src = get_source_registry().get("fred_macro")
    if src is None or not isinstance(src, FREDMacro):
        return None
    path = src.data_root / f"{series_id}.parquet"
    if not path.exists():
        _SERIES_CACHE[series_id] = pd.Series(dtype=float)
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        _SERIES_CACHE[series_id] = pd.Series(dtype=float)
        return None
    s = pd.Series(df["value"].values,
                  index=pd.to_datetime(df.index).date).sort_index()
    _SERIES_CACHE[series_id] = s
    return s if not s.empty else None


def clear_series_cache() -> None:
    """Test helper — drop the in-process per-series cache."""
    _SERIES_CACHE.clear()


# Self-register a default instance at import time.
get_source_registry().register(FREDMacro())
