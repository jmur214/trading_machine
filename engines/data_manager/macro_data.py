# engines/data_manager/macro_data.py
"""
FRED macro data pipeline.

Self-contained fetch + parquet cache for a curated set of macroeconomic
series from the St. Louis Fed FRED API. Designed as a foundation that
edges, the regime classifier, and the dashboard will later consume —
this module owns I/O and caching only, no signal logic.

Series selection rationale lives in `MACRO_SERIES` below. The default
panel covers the four high-leverage macro axes called out in the
2026-04-24 strategic pivot doc: yield curve, credit spreads, monetary
policy, and labor/inflation prints.

Key design choices
------------------
- Free-tier FRED API; key from .env ``FRED_API_KEY`` (optional — without
  one the module still serves cached data).
- Parquet cache at ``data/macro/<SERIES_ID>.parquet``, with a sidecar
  ``_meta.json`` recording the last successful fetch per series. This
  mirrors the OHLCV cache pattern in ``data_manager.py``.
- Cache-first: ``fetch_series`` returns cached data if it is fresher
  than ``max_age_hours`` (default 24h — most FRED daily series update
  on a 1-day lag, so 24h is a reasonable refresh window).
- Network failures degrade gracefully: if the API is unreachable the
  cache is returned with a warning rather than raising. Edges /
  regime detectors should never crash because FRED is down.
- No engine wiring in this file. Integration is a separate handoff.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
_ENV_PATH = ROOT_DIR / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=False)


FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_CACHE_DIR = ROOT_DIR / "data" / "macro"
DEFAULT_START = "2000-01-01"
DEFAULT_TIMEOUT_S = 15
DEFAULT_MAX_AGE_HOURS = 24


class MacroDataError(Exception):
    """Raised for non-recoverable failures in the macro pipeline."""


@dataclass(frozen=True)
class MacroSeries:
    """Metadata describing a single FRED series we care about."""
    series_id: str
    label: str
    category: str   # one of: yield_curve, credit, policy, inflation, labor, growth, fx, vol, liquidity
    frequency: str  # one of: daily, weekly, monthly
    notes: str


# ---------------------------------------------------------------------------
# Curated series registry.
# ---------------------------------------------------------------------------
# These are the macro inputs the strategic pivot doc identified as the
# highest expected-alpha-per-dollar additions, plus a few standard
# complements (breakevens, VIX, dollar index) that round out the macro
# state vector. All are free on FRED.
#
# Frequencies are nominal — FRED publishes some "daily" series with
# weekend gaps and some "weekly" series at irregular cadences. The
# panel builder forward-fills to a daily index when constructing
# combined output, but each cached parquet preserves native cadence.
MACRO_SERIES: dict[str, MacroSeries] = {
    # --- Yield curve ---
    "DGS10": MacroSeries("DGS10", "10-Year Treasury Constant Maturity Yield",
                         "yield_curve", "daily",
                         "Long-end risk-free rate; equity DCF input."),
    "DGS2": MacroSeries("DGS2", "2-Year Treasury Constant Maturity Yield",
                        "yield_curve", "daily",
                        "Short-end policy expectations."),
    "DGS3MO": MacroSeries("DGS3MO", "3-Month Treasury Constant Maturity Yield",
                          "yield_curve", "daily",
                          "Cash-like benchmark; pairs with DGS10 for 10y-3m spread."),
    "T10Y2Y": MacroSeries("T10Y2Y", "10Y-2Y Treasury Spread",
                          "yield_curve", "daily",
                          "Classic recession-leading indicator; FRED publishes directly."),
    "T10Y3M": MacroSeries("T10Y3M", "10Y-3M Treasury Spread",
                          "yield_curve", "daily",
                          "NY Fed's preferred recession indicator."),
    # --- Credit ---
    "BAMLH0A0HYM2": MacroSeries("BAMLH0A0HYM2", "ICE BofA US High Yield OAS",
                                "credit", "daily",
                                "HY credit spread; risk-on/off proxy at daily cadence."),
    "BAMLC0A0CM": MacroSeries("BAMLC0A0CM", "ICE BofA US Corporate Index OAS",
                              "credit", "daily",
                              "IG credit spread; pairs with HY OAS for credit-quality slope."),
    # --- Policy ---
    "DFF": MacroSeries("DFF", "Effective Federal Funds Rate",
                       "policy", "daily",
                       "Daily realized policy rate."),
    "WALCL": MacroSeries("WALCL", "Federal Reserve Total Assets",
                         "liquidity", "weekly",
                         "Fed balance sheet; QE/QT proxy."),
    # --- Inflation expectations ---
    "T10YIE": MacroSeries("T10YIE", "10-Year Breakeven Inflation Rate",
                          "inflation", "daily",
                          "Market-implied 10y inflation; daily and forward-looking."),
    "CPIAUCSL": MacroSeries("CPIAUCSL", "CPI All Urban Consumers (SA)",
                            "inflation", "monthly",
                            "Headline CPI level; YoY change is the standard transform."),
    # --- Labor ---
    "UNRATE": MacroSeries("UNRATE", "Unemployment Rate",
                          "labor", "monthly",
                          "Headline unemployment; lagging but regime-defining."),
    "ICSA": MacroSeries("ICSA", "Initial Jobless Claims (SA)",
                        "labor", "weekly",
                        "Leading labor indicator; higher cadence than UNRATE."),
    "PAYEMS": MacroSeries("PAYEMS", "Nonfarm Payrolls (SA)",
                          "labor", "monthly",
                          "First-Friday print, large market-mover."),
    # --- Growth ---
    "INDPRO": MacroSeries("INDPRO", "Industrial Production Index",
                          "growth", "monthly",
                          "Real-economy activity proxy."),
    "UMCSENT": MacroSeries("UMCSENT", "U. of Michigan Consumer Sentiment",
                           "growth", "monthly",
                           "Soft survey data; ISM-PMI substitute (PMI series no longer free)."),
    # --- Volatility ---
    "VIXCLS": MacroSeries("VIXCLS", "CBOE VIX Close",
                          "vol", "daily",
                          "Implied vol; FRED republishes CBOE's free daily series."),
    # --- FX ---
    "DTWEXBGS": MacroSeries("DTWEXBGS", "Trade-Weighted USD Index (Broad)",
                            "fx", "daily",
                            "Dollar strength; affects multinational earnings."),
}


def list_series(category: Optional[str] = None) -> list[MacroSeries]:
    """Return the curated series registry, optionally filtered by category."""
    items = list(MACRO_SERIES.values())
    if category is not None:
        items = [s for s in items if s.category == category]
    return items


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class MacroDataManager:
    """Fetch + cache FRED macro series.

    Parameters
    ----------
    api_key:
        FRED API key. Falls back to ``FRED_API_KEY`` env var. If neither is
        set the manager runs in cache-only mode — all fetches degrade to
        whatever is on disk.
    cache_dir:
        Directory for parquet cache. Defaults to ``data/macro/`` at the repo
        root.
    timeout_s:
        Network timeout for individual FRED requests.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path | str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self._meta_path = self.cache_dir / "_meta.json"

    # ----- cache layout -----
    def _series_path(self, series_id: str) -> Path:
        return self.cache_dir / f"{series_id}.parquet"

    def _read_meta(self) -> dict:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        tmp = self._meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2, sort_keys=True))
        tmp.replace(self._meta_path)

    def _record_fetch(self, series_id: str, n_rows: int) -> None:
        meta = self._read_meta()
        meta[series_id] = {
            "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(n_rows),
        }
        self._write_meta(meta)

    def _cache_age_hours(self, series_id: str) -> Optional[float]:
        path = self._series_path(series_id)
        if not path.exists():
            return None
        return (time.time() - path.stat().st_mtime) / 3600.0

    # ----- public API -----
    def load_cached(self, series_id: str) -> pd.DataFrame:
        """Read a cached series without touching the network."""
        path = self._series_path(series_id)
        if not path.exists():
            return _empty_series_frame()
        return pd.read_parquet(path)

    def fetch_series(
        self,
        series_id: str,
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch a single FRED series, with cache.

        Returns a DataFrame indexed by ``date`` (naive Timestamp) with a
        single ``value`` column (float64, NaN for missing prints).

        If the cache is fresher than ``max_age_hours`` it is returned
        directly. If the network fetch fails, the existing cache is
        returned (with a warning); only when there is no cache at all
        does the failure raise.
        """
        if series_id not in MACRO_SERIES:
            # Allow uncurated series, but warn — keeps the door open for
            # ad-hoc exploration without forcing every test to register.
            _log(f"series {series_id!r} is not in the curated registry")

        cached_age = self._cache_age_hours(series_id)
        if not force and cached_age is not None and cached_age < max_age_hours:
            return self.load_cached(series_id)

        if self.api_key is None:
            # No key — return cache if we have any, otherwise empty.
            if cached_age is not None:
                _log(f"no FRED_API_KEY; serving stale cache for {series_id} "
                     f"({cached_age:.1f}h old)")
                return self.load_cached(series_id)
            raise MacroDataError(
                f"FRED_API_KEY not set and no cached data for {series_id}. "
                "Add FRED_API_KEY to .env or pre-populate the cache."
            )

        try:
            df = self._download(series_id, start=start, end=end)
        except (requests.RequestException, MacroDataError) as exc:
            if cached_age is not None:
                _log(f"FRED fetch failed for {series_id} ({exc!s}); "
                     f"falling back to cache aged {cached_age:.1f}h")
                return self.load_cached(series_id)
            raise MacroDataError(
                f"FRED fetch failed for {series_id} and no cache available: {exc}"
            ) from exc

        self._save(series_id, df)
        return df

    def fetch_panel(
        self,
        series_ids: Optional[Iterable[str]] = None,
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
        ffill: bool = True,
    ) -> pd.DataFrame:
        """Fetch a wide panel of macro series.

        Parameters
        ----------
        series_ids:
            Iterable of series IDs. Defaults to the full curated registry.
        ffill:
            If True (default), forward-fill weekly/monthly series to a
            daily index. Edges typically want a daily-aligned macro state.
            If False, joins are outer-joined and missing days remain NaN.

        Returns
        -------
        DataFrame indexed by date, columns are series IDs.
        """
        ids = list(series_ids) if series_ids is not None else list(MACRO_SERIES.keys())
        frames: dict[str, pd.DataFrame] = {}
        failures: list[tuple[str, str]] = []
        for sid in ids:
            try:
                frames[sid] = self.fetch_series(
                    sid, start=start, end=end, force=force, max_age_hours=max_age_hours,
                )
            except MacroDataError as exc:
                failures.append((sid, str(exc)))
                _log(f"skipping {sid} in panel: {exc}")

        if not frames:
            raise MacroDataError(
                f"No series available for panel build. Failures: {failures}"
            )

        wide = pd.concat(
            {sid: df["value"] for sid, df in frames.items() if not df.empty},
            axis=1,
            sort=True,
        )

        if ffill:
            daily_idx = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
            wide = wide.reindex(daily_idx).ffill()
            wide.index.name = "date"

        if start is not None:
            wide = wide.loc[wide.index >= pd.Timestamp(start)]
        if end is not None:
            wide = wide.loc[wide.index <= pd.Timestamp(end)]
        return wide

    def cache_status(self) -> pd.DataFrame:
        """Return a DataFrame describing the on-disk cache state."""
        meta = self._read_meta()
        rows = []
        for sid, info in MACRO_SERIES.items():
            path = self._series_path(sid)
            entry = meta.get(sid, {})
            rows.append({
                "series_id": sid,
                "category": info.category,
                "frequency": info.frequency,
                "cached": path.exists(),
                "age_hours": self._cache_age_hours(sid),
                "n_rows": entry.get("n_rows"),
                "last_fetched_utc": entry.get("last_fetched_utc"),
            })
        return pd.DataFrame(rows)

    # ----- internals -----
    def _download(
        self,
        series_id: str,
        start: Optional[str],
        end: Optional[str],
    ) -> pd.DataFrame:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if start is not None:
            params["observation_start"] = start
        if end is not None:
            params["observation_end"] = end

        resp = requests.get(FRED_API_BASE, params=params, timeout=self.timeout_s)
        if resp.status_code != 200:
            raise MacroDataError(
                f"FRED returned HTTP {resp.status_code} for {series_id}: "
                f"{resp.text[:200]}"
            )
        payload = resp.json()
        observations = payload.get("observations")
        if observations is None:
            raise MacroDataError(
                f"FRED response missing 'observations' for {series_id}: "
                f"{str(payload)[:200]}"
            )
        return _observations_to_frame(observations)

    def _save(self, series_id: str, df: pd.DataFrame) -> None:
        path = self._series_path(series_id)
        df.to_parquet(path)
        self._record_fetch(series_id, len(df))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _empty_series_frame() -> pd.DataFrame:
    df = pd.DataFrame({"value": pd.Series([], dtype="float64")})
    df.index = pd.DatetimeIndex([], name="date")
    return df


def _observations_to_frame(observations: list[dict]) -> pd.DataFrame:
    """Convert raw FRED ``observations`` list into a clean DataFrame.

    FRED encodes missing data as the literal string ``"."``. We coerce
    those (and any other non-numeric strings) to NaN and parse dates to
    naive Timestamps. Output schema: index=date, single column 'value'.
    """
    if not observations:
        return _empty_series_frame()

    df = pd.DataFrame(observations)
    if "date" not in df.columns or "value" not in df.columns:
        raise MacroDataError(
            f"Unexpected FRED observation schema: {list(df.columns)}"
        )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date").sort_index()
    return df[["value"]]


def _log(msg: str) -> None:
    """Lightweight logger compatible with the existing data_manager style.

    Routes through `debug_config` if available, otherwise prints with a
    [MACRO_DATA] prefix. Keeps this module importable in standalone
    contexts (notebooks, isolated tests) without pulling in the wider
    project's debug infrastructure.
    """
    try:
        from debug_config import is_debug_enabled  # type: ignore
        verbose = is_debug_enabled("DATA_MANAGER")
    except Exception:
        verbose = False
    if verbose:
        print(f"[MACRO_DATA] {msg}")


# ---------------------------------------------------------------------------
# Standard derived features
# ---------------------------------------------------------------------------
# These transforms compose curated series into the most commonly-used
# macro features. They are deliberately minimal — anything more bespoke
# (rolling z-scores, regime-conditional features, etc.) belongs in the
# consuming edge or in the regime engine, not here.

def yoy_change(series: pd.Series, periods: int = 12) -> pd.Series:
    """Year-over-year change (default monthly cadence: 12 periods)."""
    return series.pct_change(periods)


def credit_quality_slope(panel: pd.DataFrame) -> pd.Series:
    """HY OAS minus IG OAS — widens before risk-off events."""
    return panel["BAMLH0A0HYM2"] - panel["BAMLC0A0CM"]


def real_fed_funds(panel: pd.DataFrame) -> pd.Series:
    """DFF minus 10y breakeven inflation. Rough real-policy-rate proxy."""
    return panel["DFF"] - panel["T10YIE"]
