"""CFTC Commitments of Traders (COT) — first DataSource verifying the
Foundry architecture end-to-end.

The COT is a free, weekly, decades-deep dataset of futures positioning
broken down by trader category (commercial / non-commercial / non-
reportable). Released every Friday for Tuesday-of-week positions, so
a ~3-day publication lag.

Public CSV / TXT archives live at:
    https://www.cftc.gov/dea/history/dea_fut_xls_<YEAR>.zip       (xls)
    https://www.cftc.gov/files/dea/history/deafr<YEAR>.zip        (csv)

The "futures-only legacy" report has the columns we need; we map a
small set of ETF tickers to their underlying CFTC market codes.

The plugin is wire-up-only by default — `fetch()` calls
`_download(url)` which raises `NotImplementedError` unless the user
supplies a downloader (or instantiates with `fetcher=...`). This is
intentional: the substrate ships without baking a network call into
the import path. Production deployment supplies a fetcher; tests
supply a local-fixture fetcher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd

from ..data_source import DataSource, get_source_registry


# ---- ticker → CFTC market name mapping ---- #
# Only futures-correlated ETFs / proxies. For tickers not in this map,
# the feature returns None (handled at the feature layer, not here).
TICKER_TO_MARKET: Dict[str, str] = {
    "USO": "WTI CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
    "UCO": "WTI CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
    "GLD": "GOLD - COMMODITY EXCHANGE INC.",
    "IAU": "GOLD - COMMODITY EXCHANGE INC.",
    "SLV": "SILVER - COMMODITY EXCHANGE INC.",
    "UNG": "NATURAL GAS - NEW YORK MERCANTILE EXCHANGE",
    "TLT": "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
    "IEF": "10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE",
    "DBA": "WHEAT-SRW - CHICAGO BOARD OF TRADE",
    "CORN": "CORN - CHICAGO BOARD OF TRADE",
    "SOYB": "SOYBEANS - CHICAGO BOARD OF TRADE",
    "UUP": "U.S. DOLLAR INDEX - ICE FUTURES U.S.",
}


# ---- required CSV columns we rely on ---- #
REQUIRED_COLUMNS = {
    "Market_and_Exchange_Names",
    "Report_Date_as_YYYY-MM-DD",
    "Comm_Positions_Long_All",
    "Comm_Positions_Short_All",
    "Open_Interest_All",
}


@dataclass
class CFTCCommitmentsOfTraders(DataSource):
    """CFTC COT data source — futures-only legacy report."""

    name: str = "cftc_cot"
    license: str = "public"
    latency: timedelta = field(default_factory=lambda: timedelta(days=10))
    point_in_time_safe: bool = True
    # Optional downloader: fn(url) -> CSV/text bytes. Production wiring
    # supplies a real HTTP fetcher; tests supply a local fixture reader.
    # Kept Optional so the substrate ships without forcing a network call.
    fetcher: Optional[Callable[[str], str]] = None

    def url_for_year(self, year: int) -> str:
        # The legacy CSV archive URL pattern. CFTC re-organises every few
        # years; the canonical entry point is documented in the model card.
        return f"https://www.cftc.gov/files/dea/history/deafr{year}.zip"

    def _download(self, url: str) -> str:
        if self.fetcher is None:
            raise NotImplementedError(
                f"CFTCCommitmentsOfTraders: no fetcher configured. "
                f"Pass `fetcher=callable` at construction time. "
                f"Production wiring lives in `scripts/refresh_foundry_sources.py`; "
                f"tests pass a local-fixture fetcher. Attempted URL: {url}"
            )
        return self.fetcher(url)

    def fetch(self, start: date, end: date) -> pd.DataFrame:
        """Download per-year CSVs, concatenate, and filter to [start, end]."""
        years = list(range(start.year, end.year + 1))
        frames = []
        for y in years:
            text = self._download(self.url_for_year(y))
            frame = pd.read_csv(StringIO(text))
            frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))
        df = pd.concat(frames, ignore_index=True)
        # Keep only columns we know about + required ones.
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"CFTC fetch returned frame missing columns: {sorted(missing)}"
            )
        df["Report_Date_as_YYYY-MM-DD"] = pd.to_datetime(
            df["Report_Date_as_YYYY-MM-DD"]
        ).dt.date
        df = df[
            (df["Report_Date_as_YYYY-MM-DD"] >= start)
            & (df["Report_Date_as_YYYY-MM-DD"] <= end)
        ].reset_index(drop=True)
        return df

    def schema_check(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return True  # empty windows (e.g. unreleased) are valid
        if not REQUIRED_COLUMNS.issubset(set(df.columns)):
            return False
        # Spot-check dtypes — the long/short columns must be numeric.
        for col in ("Comm_Positions_Long_All", "Comm_Positions_Short_All",
                    "Open_Interest_All"):
            if not pd.api.types.is_numeric_dtype(df[col]):
                return False
        return True

    def freshness_check(self) -> bool:
        """Look at the newest cached parquet's max date and check it's
        within `latency` of today. If no cache exists yet, return False
        so the dashboard surfaces it clearly."""
        cache_dir = self.cache_root / self.name
        if not cache_dir.exists():
            return False
        latest_path = max(cache_dir.glob("*.parquet"),
                          key=lambda p: p.stat().st_mtime, default=None)
        if latest_path is None:
            return False
        try:
            df = pd.read_parquet(latest_path)
        except Exception:
            return False
        if df.empty:
            return False
        latest_date = df["Report_Date_as_YYYY-MM-DD"].max()
        if hasattr(latest_date, "to_pydatetime"):
            latest_date = latest_date.to_pydatetime().date()
        elif hasattr(latest_date, "date"):
            latest_date = latest_date.date()
        return (date.today() - latest_date) <= self.latency


# Self-register a default instance at import time so the dashboard can
# enumerate it. The default has no fetcher (raises if used live).
get_source_registry().register(CFTCCommitmentsOfTraders())
