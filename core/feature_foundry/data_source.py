"""DataSource ABC + registry + parquet write-through cache.

F1 of the Feature Foundry. Every external data source — CFTC COT, FDA
approvals, Polymarket, etc. — implements this interface. Once the source
plugin is written, downstream features consume it identically regardless
of provenance.

Key invariants:

  - `point_in_time_safe` MUST be True for any source feeding a feature
    used in a backtest. Sources flagged False are advisory-only.
  - `freshness_check()` MUST raise or return False if the latest cached
    row is older than `latency`. Stale data poisons live trading.
  - `schema_check()` MUST verify column dtypes + non-null invariants
    so silent schema drift is caught before it pollutes the meta-learner.
  - `fetch()` returns raw upstream shape; the cache layer normalises.

The registry is process-local and idempotent — `register()` calls from
import-time plugin modules are safe.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

import pandas as pd


CACHE_ROOT = Path("data/feature_foundry/cache")


@dataclass
class DataSource(ABC):
    """Abstract plugin interface for external data feeds.

    Subclasses set the four metadata fields and implement the three
    abstract methods. The base class provides write-through parquet
    caching keyed by (source name, date range).
    """

    name: str
    license: str
    latency: timedelta
    point_in_time_safe: bool
    cache_root: Path = field(default=CACHE_ROOT)

    # ---- abstract ---- #
    @abstractmethod
    def fetch(self, start: date, end: date) -> pd.DataFrame:
        """Return raw upstream rows for the inclusive [start, end] window.

        Implementations should be idempotent: calling with the same window
        must yield the same output, modulo legitimate upstream revisions.
        """

    @abstractmethod
    def schema_check(self, df: pd.DataFrame) -> bool:
        """Verify required columns + dtypes are present in `df`. Return
        False (or raise with a clear message) if invariants violated."""

    @abstractmethod
    def freshness_check(self) -> bool:
        """Return True if the most recent cached row is younger than the
        declared `latency`. Used by the dashboard health column."""

    # ---- caching ---- #
    def cache_path(self, start: date, end: date) -> Path:
        key = f"{self.name}__{start.isoformat()}__{end.isoformat()}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        return self.cache_root / self.name / f"{key}__{digest}.parquet"

    def fetch_cached(self, start: date, end: date,
                     force_refresh: bool = False) -> pd.DataFrame:
        """Write-through cache. Reads parquet on hit; calls `fetch` and
        writes parquet on miss. Schema-checks every fetched DataFrame."""
        path = self.cache_path(start, end)
        if path.exists() and not force_refresh:
            df = pd.read_parquet(path)
            if self.schema_check(df):
                return df
            # Cache present but schema-invalid → re-fetch
        df = self.fetch(start, end)
        if not self.schema_check(df):
            raise ValueError(
                f"DataSource {self.name!r} returned schema-invalid frame "
                f"for window [{start}, {end}]"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return df

    # ---- metadata helper ---- #
    def metadata(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "license": self.license,
            "latency_seconds": str(int(self.latency.total_seconds())),
            "point_in_time_safe": str(self.point_in_time_safe),
            "fresh": str(self.freshness_check()),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


class DataSourceRegistry:
    """Process-local registry of `DataSource` instances. Plugins register
    themselves at import time; the dashboard + ablation runner enumerate
    via `list_sources()`."""

    def __init__(self) -> None:
        self._sources: Dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        # Idempotent — re-registering the same name overwrites (safe for
        # re-imports during tests).
        self._sources[source.name] = source

    def get(self, name: str) -> Optional[DataSource]:
        return self._sources.get(name)

    def list_sources(self) -> List[DataSource]:
        return list(self._sources.values())

    def clear(self) -> None:
        """Test-only — drop all registrations."""
        self._sources.clear()


_REGISTRY = DataSourceRegistry()


def get_source_registry() -> DataSourceRegistry:
    return _REGISTRY
