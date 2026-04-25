# engines/data_manager/earnings_data.py
"""
yfinance-backed earnings calendar + surprise data pipeline.

Self-contained fetch + parquet cache for company-level earnings
events: announcement dates, EPS actual vs consensus, and the
surprise magnitudes derived from them. Designed to feed PEAD
(post-earnings announcement drift) edges and any event-driven
logic that needs to align price action with earnings releases —
this module owns I/O and caching only, no signal logic.

Why this exists
---------------
Per the 2026-04-24 strategic pivot doc, PEAD is the strongest
single-factor alpha in the academic literature (~2% monthly excess
for 2-3 months following a positive surprise). The original
implementation used Finnhub's free tier, but on 2026-04-25 we
verified that the free tier returns 0 historical earnings (both
unfiltered calendar windows and per-symbol queries). yfinance
exposes ~6 years of historical earnings dates per ticker with
EPS Estimate, Reported EPS, and surprise % — sufficient for PEAD
backtesting at zero cost and no API key.

Key design choices
------------------
- yfinance backend (no API key required). The Finnhub key in
  ``.env`` is retained for possible real-time use during paper
  trading but is not consumed here.
- Parquet cache at ``data/earnings/<SYMBOL>_calendar.parquet``,
  with a sidecar ``_meta.json`` recording the last successful
  fetch per symbol. Mirrors the FRED cache pattern in
  ``macro_data.py``.
- Cache-first: ``fetch_calendar`` returns cached data if it is
  fresher than ``max_age_hours`` (default 24h — earnings are
  quarterly events; intraday refresh adds nothing, daily refresh
  catches new announcements).
- Network failures degrade gracefully: if yfinance is unreachable
  the cache is returned with a warning rather than raising. Edges
  should never crash because the data source is down.
- Per-call rate limit (1.1s sleep between fetches by default) to
  avoid hammering Yahoo's anti-scraping. Configurable; set to 0
  in tests.
- Revenue fields are not provided by yfinance and stay NaN in the
  cached schema. PEAD logic uses ``eps_surprise_pct`` exclusively;
  if a future edge needs revenue surprise the schema is preserved
  so a different backend can populate those columns later.
- No engine wiring in this file. Integration is a separate handoff.

Cached schema (per symbol)
--------------------------
Index: ``announcement_date`` (naive Timestamp, the date Finnhub
reports the earnings release as occurring on).

Columns:
    symbol             str
    eps_actual         float64
    eps_estimate       float64
    eps_surprise       float64   actual - estimate
    eps_surprise_pct   float64   (actual - estimate) / |estimate|
                                 NaN when estimate is 0 or NaN
    revenue_actual     float64
    revenue_estimate   float64
    revenue_surprise   float64
    revenue_surprise_pct float64 same convention as EPS
    hour               str       'bmo' | 'amc' | '' (before/after market)
    quarter            Int64
    year               Int64
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
_ENV_PATH = ROOT_DIR / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH, override=False)


DEFAULT_CACHE_DIR = ROOT_DIR / "data" / "earnings"
DEFAULT_START = "2020-01-01"
DEFAULT_TIMEOUT_S = 15
DEFAULT_MAX_AGE_HOURS = 24
# yfinance scrapes Yahoo; 1.1s between calls keeps us polite. Override
# per-test with rate_limit_s=0.
DEFAULT_RATE_LIMIT_S = 1.1

# Column order for cached event frames. Kept stable so consumers can
# rely on positional access if they need it.
EVENT_COLUMNS = [
    "symbol",
    "eps_actual",
    "eps_estimate",
    "eps_surprise",
    "eps_surprise_pct",
    "revenue_actual",
    "revenue_estimate",
    "revenue_surprise",
    "revenue_surprise_pct",
    "hour",
    "quarter",
    "year",
]


class EarningsDataError(Exception):
    """Raised for non-recoverable failures in the earnings pipeline."""


@dataclass(frozen=True)
class EarningsEvent:
    """Lightweight value type for a single earnings announcement.

    Not used internally — the manager works in DataFrame space — but
    exposed for consumers that prefer typed records (e.g., an edge
    iterating events to score each one).
    """
    symbol: str
    announcement_date: pd.Timestamp
    eps_actual: Optional[float]
    eps_estimate: Optional[float]
    eps_surprise: Optional[float]
    eps_surprise_pct: Optional[float]
    revenue_actual: Optional[float]
    revenue_estimate: Optional[float]
    revenue_surprise: Optional[float]
    revenue_surprise_pct: Optional[float]
    hour: str
    quarter: Optional[int]
    year: Optional[int]


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class EarningsDataManager:
    """Fetch + cache yfinance earnings calendar entries per ticker.

    Parameters
    ----------
    api_key:
        Retained for backwards compatibility with the previous
        Finnhub-backed signature. Unused under the yfinance backend;
        accepted so existing callers (tests, scripts) don't break.
        Pass ``None`` to indicate cache-only mode (still honoured —
        skips network on every call).
    cache_dir:
        Directory for parquet cache. Defaults to ``data/earnings/``
        at the repo root.
    timeout_s:
        Network timeout for individual yfinance requests.
    rate_limit_s:
        Minimum seconds between consecutive network fetches issued
        by this manager. 0 disables rate limiting (use only in tests).
    offline:
        If True, never touch the network — serve cache only and
        raise ``EarningsDataError`` if no cache exists. Defaults to
        True when ``api_key=None`` for compatibility with the prior
        keyless-implies-cache-only contract.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path | str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        rate_limit_s: float = DEFAULT_RATE_LIMIT_S,
        offline: Optional[bool] = None,
    ) -> None:
        self.api_key = api_key  # retained for caller compatibility
        # Preserve the prior contract: api_key=None → cache-only mode.
        # This keeps existing tests and shims working unchanged.
        self.offline = offline if offline is not None else (api_key is None)
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.rate_limit_s = float(rate_limit_s)
        self._meta_path = self.cache_dir / "_meta.json"
        self._last_fetch_monotonic: float = 0.0

    # ----- cache layout -----
    def _calendar_path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.upper()}_calendar.parquet"

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

    def _record_fetch(self, symbol: str, n_rows: int) -> None:
        meta = self._read_meta()
        meta[symbol.upper()] = {
            "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(n_rows),
        }
        self._write_meta(meta)

    def _cache_age_hours(self, symbol: str) -> Optional[float]:
        path = self._calendar_path(symbol)
        if not path.exists():
            return None
        return (time.time() - path.stat().st_mtime) / 3600.0

    # ----- public API -----
    def load_cached(self, symbol: str) -> pd.DataFrame:
        """Read a cached calendar without touching the network."""
        path = self._calendar_path(symbol)
        if not path.exists():
            return _empty_event_frame()
        return pd.read_parquet(path)

    def fetch_calendar(
        self,
        symbol: str,
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch one ticker's earnings calendar, with cache.

        Returns a DataFrame indexed by ``announcement_date`` with the
        schema documented at module top.

        Cache-first: returns the cached parquet if fresher than
        ``max_age_hours``. On network failure the existing cache is
        returned (with a warning); only when there is no cache does
        the failure raise ``EarningsDataError``.
        """
        symbol = symbol.upper()
        cached_age = self._cache_age_hours(symbol)
        if not force and cached_age is not None and cached_age < max_age_hours:
            return self.load_cached(symbol)

        if self.offline:
            if cached_age is not None:
                _log(f"offline mode; serving cache for {symbol} "
                     f"({cached_age:.1f}h old)")
                return self.load_cached(symbol)
            raise EarningsDataError(
                f"offline=True and no cached data for {symbol}. "
                "Re-instantiate with offline=False or pre-populate the cache."
            )

        try:
            df = self._download_calendar(symbol, start=start, end=end)
        except EarningsDataError as exc:
            if cached_age is not None:
                _log(f"yfinance fetch failed for {symbol} ({exc!s}); "
                     f"falling back to cache aged {cached_age:.1f}h")
                return self.load_cached(symbol)
            raise EarningsDataError(
                f"yfinance fetch failed for {symbol} and no cache available: {exc}"
            ) from exc

        self._save(symbol, df)
        return df

    def fetch_universe(
        self,
        symbols: Iterable[str],
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch a list of tickers and concatenate into a long events frame.

        Failed tickers are skipped with a warning rather than aborting
        the whole run. Returns a DataFrame with the same column schema
        as ``fetch_calendar``, indexed by announcement date and sorted.
        Symbols that have no events on disk and cannot be fetched
        contribute zero rows (not NaN-filled rows).
        """
        symbols = [s.upper() for s in symbols]
        frames: list[pd.DataFrame] = []
        failures: list[tuple[str, str]] = []
        for sym in symbols:
            try:
                df = self.fetch_calendar(
                    sym, start=start, end=end, force=force,
                    max_age_hours=max_age_hours,
                )
                if not df.empty:
                    frames.append(df)
            except EarningsDataError as exc:
                failures.append((sym, str(exc)))
                _log(f"skipping {sym} in universe fetch: {exc}")

        if not frames:
            if failures:
                raise EarningsDataError(
                    f"No symbols fetched. Failures: {failures}"
                )
            return _empty_event_frame()

        combined = pd.concat(frames, axis=0).sort_index()
        return combined

    def cache_status(self) -> pd.DataFrame:
        """Return a DataFrame describing the on-disk cache state.

        Walks the cache directory rather than a registry — the universe
        of tickers is open-ended unlike the FRED curated registry.
        """
        meta = self._read_meta()
        rows = []
        for path in sorted(self.cache_dir.glob("*_calendar.parquet")):
            symbol = path.stem.replace("_calendar", "")
            entry = meta.get(symbol, {})
            rows.append({
                "symbol": symbol,
                "cached": True,
                "age_hours": self._cache_age_hours(symbol),
                "n_rows": entry.get("n_rows"),
                "last_fetched_utc": entry.get("last_fetched_utc"),
            })
        return pd.DataFrame(
            rows,
            columns=["symbol", "cached", "age_hours", "n_rows", "last_fetched_utc"],
        )

    # ----- internals -----
    def _respect_rate_limit(self) -> None:
        if self.rate_limit_s <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_fetch_monotonic
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        self._last_fetch_monotonic = time.monotonic()

    def _download_calendar(
        self,
        symbol: str,
        start: Optional[str],
        end: Optional[str],
    ) -> pd.DataFrame:
        # yfinance returns ~6 years of historical earnings per ticker,
        # indexed by Earnings Date with columns: 'EPS Estimate',
        # 'Reported EPS', 'Surprise(%)'. Future earnings have NaN
        # Reported EPS — keep them in cache so callers can see the
        # next-event date, but they contribute no PEAD signal until
        # filed.
        from_ = pd.to_datetime(start) if start else pd.to_datetime(DEFAULT_START)
        to_ = pd.to_datetime(end) if end else None

        self._respect_rate_limit()
        observations = _fetch_yfinance_earnings(symbol)

        # Window-filter to caller-requested range. yfinance ignores
        # date params, so we filter client-side to honour the contract.
        filtered = []
        for obs in observations:
            d = pd.to_datetime(obs.get("date"), errors="coerce")
            if pd.isna(d):
                continue
            if d < from_:
                continue
            if to_ is not None and d > to_:
                continue
            filtered.append(obs)
        return _observations_to_frame(filtered, symbol)

    def _save(self, symbol: str, df: pd.DataFrame) -> None:
        path = self._calendar_path(symbol)
        df.to_parquet(path)
        self._record_fetch(symbol, len(df))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _empty_event_frame() -> pd.DataFrame:
    """Empty DataFrame with the canonical event-frame schema."""
    df = pd.DataFrame({col: pd.Series([], dtype=_dtype_for(col))
                       for col in EVENT_COLUMNS})
    df.index = pd.DatetimeIndex([], name="announcement_date")
    return df


def _dtype_for(col: str) -> str:
    if col == "symbol" or col == "hour":
        return "object"
    if col in {"quarter", "year"}:
        return "Int64"
    return "float64"


def surprise_pct(actual: float | None, estimate: float | None) -> float:
    """Standard surprise-magnitude transform.

    Returns ``(actual - estimate) / |estimate|``. NaN when either input
    is NaN/None or when ``estimate`` is zero (avoids inf). Computing
    locally rather than relying on Finnhub's `surprisePercent` field
    keeps the formula auditable and consistent across the EPS and
    revenue columns.
    """
    if actual is None or estimate is None:
        return float("nan")
    a = float(actual) if actual == actual else float("nan")
    e = float(estimate) if estimate == estimate else float("nan")
    if a != a or e != e:
        return float("nan")
    if e == 0:
        return float("nan")
    return (a - e) / abs(e)


def _fetch_yfinance_earnings(symbol: str) -> list[dict]:
    """Pull earnings dates for ``symbol`` from yfinance and convert
    to the legacy Finnhub-shaped observation dict.

    yfinance returns a DataFrame indexed by ``Earnings Date`` with
    columns: ``EPS Estimate``, ``Reported EPS``, ``Surprise(%)``.
    Revenue is not exposed; revenue keys are emitted as ``None`` so
    the downstream parser produces NaN columns and the cached schema
    stays stable.

    Raises ``EarningsDataError`` on yfinance failure so the manager
    can decide whether to fall back to cache or surface the error.
    """
    try:
        ticker = yf.Ticker(symbol)
        ed = ticker.earnings_dates
    except Exception as exc:
        raise EarningsDataError(
            f"yfinance returned an error for {symbol}: {exc}"
        ) from exc

    if ed is None or ed.empty:
        return []

    observations: list[dict] = []
    for ts, row in ed.iterrows():
        # yfinance's index is timezone-aware (e.g. America/New_York).
        # Strip TZ for the cached announcement_date — PEAD aligns on
        # calendar date, not minute.
        try:
            date_str = pd.Timestamp(ts).tz_convert(None).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            date_str = pd.Timestamp(ts).strftime("%Y-%m-%d")
        observations.append({
            "date": date_str,
            "symbol": symbol.upper(),
            "epsActual": row.get("Reported EPS"),
            "epsEstimate": row.get("EPS Estimate"),
            "revenueActual": None,
            "revenueEstimate": None,
            "hour": "",
            "quarter": pd.Timestamp(ts).quarter,
            "year": pd.Timestamp(ts).year,
        })
    return observations


def _observations_to_frame(
    observations: list[dict],
    symbol: str,
) -> pd.DataFrame:
    """Convert Finnhub's earningsCalendar list into the canonical schema.

    Output schema: index = announcement_date, columns as in
    EVENT_COLUMNS. Missing numeric fields become NaN; missing
    quarter/year become pandas.NA (Int64).
    """
    if not observations:
        return _empty_event_frame()

    rows: list[dict] = []
    for obs in observations:
        date = pd.to_datetime(obs.get("date"), errors="coerce")
        if pd.isna(date):
            continue
        eps_actual = _to_float(obs.get("epsActual"))
        eps_estimate = _to_float(obs.get("epsEstimate"))
        rev_actual = _to_float(obs.get("revenueActual"))
        rev_estimate = _to_float(obs.get("revenueEstimate"))
        rows.append({
            "announcement_date": date,
            "symbol": (obs.get("symbol") or symbol).upper(),
            "eps_actual": eps_actual,
            "eps_estimate": eps_estimate,
            "eps_surprise": _diff(eps_actual, eps_estimate),
            "eps_surprise_pct": surprise_pct(eps_actual, eps_estimate),
            "revenue_actual": rev_actual,
            "revenue_estimate": rev_estimate,
            "revenue_surprise": _diff(rev_actual, rev_estimate),
            "revenue_surprise_pct": surprise_pct(rev_actual, rev_estimate),
            "hour": (obs.get("hour") or "").lower(),
            "quarter": _to_nullable_int(obs.get("quarter")),
            "year": _to_nullable_int(obs.get("year")),
        })

    if not rows:
        return _empty_event_frame()

    df = pd.DataFrame(rows).set_index("announcement_date").sort_index()
    # Force the canonical column order and dtypes.
    df = df.reindex(columns=EVENT_COLUMNS)
    df["quarter"] = df["quarter"].astype("Int64")
    df["year"] = df["year"].astype("Int64")
    return df


def _to_float(v) -> float:
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _to_nullable_int(v):
    if v is None:
        return pd.NA
    try:
        return int(v)
    except (TypeError, ValueError):
        return pd.NA


def _diff(a: float, b: float) -> float:
    if a != a or b != b:
        return float("nan")
    return a - b


def _log(msg: str) -> None:
    """Lightweight logger compatible with the existing data_manager style.

    Routes through `debug_config` if available, otherwise stays silent.
    Keeps this module importable in standalone contexts (notebooks,
    isolated tests) without pulling in the wider project's debug
    infrastructure.
    """
    try:
        from debug_config import is_debug_enabled  # type: ignore
        verbose = is_debug_enabled("DATA_MANAGER")
    except Exception:
        verbose = False
    if verbose:
        print(f"[EARNINGS_DATA] {msg}")
