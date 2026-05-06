"""LocalOHLCV — DataSource over the project's per-ticker daily CSVs.

Reads `data/processed/<TICKER>_1d.csv`, the same files the rest of the
backtester consumes. Used by every Workstream-E first-batch feature
(momentum, reversal, realized vol, beta) so each feature stays small.

Two surfaces:

  * `LocalOHLCV.fetch(start, end)` — long-format frame across all
    discovered tickers, satisfying the substrate's DataSource contract.
  * `close_series(ticker)` — per-ticker close pandas Series indexed by
    `datetime.date`, lazily loaded and cached in-process. This is the
    accessor every feature module imports; it avoids forcing each
    feature to re-implement the long-frame slice/sort dance.

Point-in-time discipline: the daily CSV row dated `t` is the close on
the trading day `t`, available after market close on `t`. Features
should call `s[s.index <= dt]` before slicing to enforce no leakage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ..data_source import DataSource, get_source_registry


REQUIRED_COLUMNS = {"ticker", "date", "open", "high", "low", "close", "volume"}


@dataclass
class LocalOHLCV(DataSource):
    name: str = "local_ohlcv"
    license: str = "internal"
    latency: timedelta = field(default_factory=lambda: timedelta(days=4))
    point_in_time_safe: bool = True
    data_root: Path = field(default_factory=lambda: Path("data/processed"))

    def _read_one(self, path: Path) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_csv(path, parse_dates=["Date"])
        except Exception:
            return None
        if "Close" not in df.columns:
            return None
        df = df.rename(columns={c: c.lower() for c in df.columns})
        df["ticker"] = path.stem.replace("_1d", "")
        keep = ["ticker", "date", "open", "high", "low", "close", "volume"]
        for col in keep:
            if col not in df.columns:
                df[col] = pd.NA
        return df[keep]

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        files = sorted(self.data_root.glob("*_1d.csv"))
        frames = []
        for p in files:
            df = self._read_one(p)
            if df is None or df.empty:
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
        files = list(self.data_root.glob("*_1d.csv"))
        if not files:
            return False
        latest = max(f.stat().st_mtime for f in files)
        latest_dt = datetime.fromtimestamp(latest).date()
        return (date.today() - latest_dt) <= self.latency


_CLOSE_CACHE: Dict[str, pd.Series] = {}


def close_series(ticker: str) -> Optional[pd.Series]:
    """Cached per-ticker close-price Series indexed by `date`. Returns
    None if no source registered or no CSV for the ticker."""
    if ticker in _CLOSE_CACHE:
        s = _CLOSE_CACHE[ticker]
        return s if not s.empty else None
    src = get_source_registry().get("local_ohlcv")
    if src is None or not isinstance(src, LocalOHLCV):
        return None
    path = src.data_root / f"{ticker}_1d.csv"
    if not path.exists():
        _CLOSE_CACHE[ticker] = pd.Series(dtype=float)
        return None
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        _CLOSE_CACHE[ticker] = pd.Series(dtype=float)
        return None
    s = pd.Series(df["Close"].values, index=df["Date"].dt.date).sort_index()
    _CLOSE_CACHE[ticker] = s
    return s if not s.empty else None


def clear_close_cache() -> None:
    """Test helper — drop the in-process per-ticker cache."""
    _CLOSE_CACHE.clear()


def list_tickers() -> List[str]:
    """All tickers discoverable from the registered LocalOHLCV source.
    Substrate-independent — works against any registered data_root."""
    src = get_source_registry().get("local_ohlcv")
    if src is None or not isinstance(src, LocalOHLCV):
        return []
    return sorted(p.stem.replace("_1d", "")
                  for p in src.data_root.glob("*_1d.csv"))


get_source_registry().register(LocalOHLCV())
