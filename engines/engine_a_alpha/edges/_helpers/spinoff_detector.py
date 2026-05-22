"""engines/engine_a_alpha/edges/_helpers/spinoff_detector.py
==============================================================
Spin-off event detector for `spinoff_reversion_v1` (T-2026-05-12-041
+ T-041b EDGAR scraper).

Sources, in priority order:
1. **Curated YAML** at `config/spinoff_events_curated.yml` — hand-
   maintained list of known historical spin-offs. Authoritative when
   present; highest confidence (1.0).
2. **SEC EDGAR Form 10 / 10-12B** (T-041b addition) — pulls
   registration statements via the public full-text search API at
   10 req/sec, caches results at
   `data/spinoff_events_edgar.parquet`. Confidence 0.9. Uses
   filing_date as the distribution_date proxy when yfinance lookup
   fails (filing typically precedes distribution by 60-180 days; we
   document this as a known limitation).
3. **yfinance `Ticker.splits`** — best-effort fallback. Coverage
   variable; confidence 0.7. Placeholder child_ticker because yfinance
   does not expose the child symbol.

The detector returns a flat list of `SpinoffEvent` records keyed by
`distribution_date`. Caller filters by window / universe.

Determinism: pure function of (curated file + cached EDGAR parquet +
optional yfinance cache). EDGAR cache is read-only at run time; the
parquet must be refreshed externally via `detect_spinoffs_edgar`.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger("spinoff_detector")

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CURATED_PATH = PROJECT_ROOT / "config" / "spinoff_events_curated.yml"
EDGAR_CACHE_PATH = PROJECT_ROOT / "data" / "spinoff_events_edgar.parquet"
EDGAR_CACHE_TTL_DAYS = 30  # invalidate after 30 days per spec hard constraint

# EDGAR rate limit policy: 10 req/sec max. SEC fair-use guideline.
EDGAR_REQUEST_DELAY_SECONDS = 0.11  # 9 req/sec to leave headroom

# SEC requires a User-Agent identifying the requester. Project-specific
# string set here; can be overridden via env var if user prefers.
_DEFAULT_EDGAR_USER_AGENT = (
    "trading_machine-2 research jsm13700@gmail.com"
)

# Display-name regex to extract ticker symbol. EDGAR display strings
# look like "Foo Corp  (FOO)  (CIK 0001234567)" — capture the ticker
# inside the FIRST set of parens that's not the CIK marker.
_TICKER_RE = re.compile(r"\s\(([A-Z][A-Z0-9.\-]{0,5})\)\s")


@dataclass(frozen=True)
class SpinoffEvent:
    """One spin-off event. Frozen for use in sets/dict keys."""
    parent_ticker: str
    child_ticker: str
    distribution_date: pd.Timestamp  # tz-naive, normalized
    distribution_ratio: float
    source: str  # 'curated' | 'yfinance' | 'edgar'
    confidence: float
    notes: str = ""

    def __post_init__(self):
        # Defensive normalization done via object.__setattr__ to keep
        # frozen=True semantics.
        ts = pd.Timestamp(self.distribution_date)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts = ts.normalize()
        object.__setattr__(self, "distribution_date", ts)
        object.__setattr__(self, "parent_ticker", str(self.parent_ticker).upper())
        object.__setattr__(self, "child_ticker", str(self.child_ticker).upper())


# In-process cache: detector results are reused across calls within a
# backtest run. Cleared by `clear_cache()` for tests.
_CACHED_EVENTS: Optional[List[SpinoffEvent]] = None
_CACHED_YFINANCE: Dict[str, pd.DataFrame] = {}


def clear_cache() -> None:
    """Reset all module-level caches. Use in tests."""
    global _CACHED_EVENTS, _CACHED_YFINANCE
    _CACHED_EVENTS = None
    _CACHED_YFINANCE = {}


def load_curated_events(curated_path: Path = CURATED_PATH) -> List[SpinoffEvent]:
    """Read the hand-curated YAML and return parsed events.

    Returns an empty list if the file is missing or empty. Logs (does
    not raise) on parse errors — detector caller falls through to
    other sources.
    """
    if not curated_path.exists():
        logger.debug(f"curated events file not found at {curated_path}")
        return []
    try:
        data = yaml.safe_load(curated_path.read_text()) or {}
    except Exception as e:
        logger.warning(f"could not parse {curated_path}: {e}")
        return []

    raw_events = data.get("events", []) if isinstance(data, dict) else []
    out: List[SpinoffEvent] = []
    for raw in raw_events:
        try:
            out.append(SpinoffEvent(
                parent_ticker=raw["parent_ticker"],
                child_ticker=raw["child_ticker"],
                distribution_date=pd.Timestamp(raw["distribution_date"]),
                distribution_ratio=float(raw.get("distribution_ratio", 1.0)),
                source="curated",
                confidence=1.0,
                notes=str(raw.get("notes", "")),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"skipping malformed curated event {raw}: {e}")
            continue
    return out


def detect_from_yfinance(
    parent_tickers: List[str],
    *,
    min_split_ratio: float = 1.001,
    max_split_ratio: float = 10.0,
) -> List[SpinoffEvent]:
    """Best-effort spin-off detection from yfinance `Ticker.actions`.

    yfinance encodes spin-offs as "stock splits" in `Ticker.splits`
    with non-integer ratios. True stock splits use integer ratios
    (2:1, 3:1, etc.), so non-integer ratios in the [1.001, 10.0]
    range are candidate spin-offs. False positives are inevitable
    (real stock splits, rights offerings); confidence is capped at
    0.7 so curated entries override.

    Note: yfinance does NOT expose the child ticker; we can detect
    that a spin-off-like event occurred but cannot reliably name the
    child symbol. For child-symbol resolution, fall back to curated.

    This function is included for completeness + future use; the
    primary path for T-041 is the curated YAML. The `child_ticker`
    field is set to `<parent>_SPINOFF_<date>` as a placeholder so
    callers can detect "yfinance saw a split-like event we don't have
    a curated mapping for" and surface for review.
    """
    out: List[SpinoffEvent] = []
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not installed; skipping yfinance detection")
        return out

    for tkr in parent_tickers:
        try:
            if tkr in _CACHED_YFINANCE:
                splits = _CACHED_YFINANCE[tkr]
            else:
                t = yf.Ticker(tkr)
                splits = t.splits
                if splits is None or len(splits) == 0:
                    _CACHED_YFINANCE[tkr] = pd.DataFrame()
                    continue
                df = pd.DataFrame({"date": splits.index, "ratio": splits.values})
                if pd.api.types.is_datetime64_any_dtype(df["date"]):
                    if getattr(df["date"].dt, "tz", None) is not None:
                        df["date"] = df["date"].dt.tz_localize(None)
                _CACHED_YFINANCE[tkr] = df
                splits = df

            if splits is None or splits.empty:
                continue
            for _, row in splits.iterrows():
                ratio = float(row["ratio"])
                # Skip true integer splits (2:1, 3:1, ...)
                if abs(ratio - round(ratio)) < 1e-6:
                    continue
                if ratio < min_split_ratio or ratio > max_split_ratio:
                    continue
                date_ts = pd.Timestamp(row["date"]).normalize()
                placeholder_child = (
                    f"{tkr}_SPINOFF_{date_ts.date().isoformat()}"
                )
                out.append(SpinoffEvent(
                    parent_ticker=tkr,
                    child_ticker=placeholder_child,
                    distribution_date=date_ts,
                    distribution_ratio=ratio,
                    source="yfinance",
                    confidence=0.7,
                    notes="yfinance-detected non-integer split (candidate spin-off)",
                ))
        except Exception as e:
            logger.debug(f"yfinance detection failed for {tkr}: {e}")
            continue
    return out


# --------------------------------------------------------------------
# T-041b: SEC EDGAR Form 10 / 10-12B scraper
# --------------------------------------------------------------------

def _extract_ticker_from_display_name(display: str) -> Optional[str]:
    """Pull out the trading ticker from EDGAR's display string.

    Strings look like: 'Foo Corp  (FOO)  (CIK 0001234567)'
    Returns 'FOO' or None if no match. Falls back to None when the
    string contains only the CIK marker (sub-public entities).
    """
    if not display:
        return None
    m = _TICKER_RE.search(display)
    if not m:
        return None
    candidate = m.group(1)
    # Defensive: never match the literal CIK label.
    if candidate.startswith("CIK"):
        return None
    return candidate


def _yfinance_first_trade_date(ticker: str) -> Optional[pd.Timestamp]:
    """Return the earliest trade date yfinance has for `ticker`, or None.

    Used as the distribution_date proxy when EDGAR provides filing_date
    but not the actual distribution event. yfinance's first available
    bar for a spin-off child is, by definition, the day trading
    commenced — i.e. the distribution.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="max", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        idx = hist.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        return pd.Timestamp(idx[0]).normalize()
    except Exception as e:
        logger.debug(f"yfinance first-trade lookup failed for {ticker}: {e}")
        return None


def detect_spinoffs_edgar(
    start_date: str,
    end_date: str,
    *,
    user_agent: str = _DEFAULT_EDGAR_USER_AGENT,
    rate_limit_seconds: float = EDGAR_REQUEST_DELAY_SECONDS,
    use_yfinance_for_distribution_date: bool = True,
) -> List[SpinoffEvent]:
    """Pull Form 10 / 10-12B filings from SEC EDGAR for the window.

    EDGAR's full-text search API returns at most 100 results per query;
    we page by month to stay under that limit. Rate-limited per
    `rate_limit_seconds` (SEC policy = 10 req/sec; we use 9 for
    headroom).

    For each filing we extract:
      - filing_date: from EDGAR's `file_date`
      - subject_ticker: regex-extracted from `display_names`
      - distribution_date: first yfinance trade date for the ticker
        (falls back to filing_date when yfinance has no history).
      - parent_ticker: NOT available from the 10-12B filing alone
        (that lives in the prospectus body). We mark these events with
        parent_ticker='UNKNOWN' and confidence=0.9.

    Returns SpinoffEvent list. Caller is responsible for caching to the
    parquet at `EDGAR_CACHE_PATH` via `refresh_edgar_cache`.
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed; skipping EDGAR fetch")
        return []

    headers = {"User-Agent": user_agent}
    base_url = "https://efts.sec.gov/LATEST/search-index"

    # Page by month to keep each query under the 100-result cap.
    months = pd.date_range(start=start_date, end=end_date, freq="MS")
    if len(months) == 0:
        months = pd.DatetimeIndex([pd.Timestamp(start_date)])

    raw_hits: List[Dict] = []
    for i, month_start in enumerate(months):
        month_end = (month_start + pd.offsets.MonthEnd(0)).date()
        params = {
            "q": "",
            "forms": "10-12B",
            "dateRange": "custom",
            "startdt": month_start.date().isoformat(),
            "enddt": month_end.isoformat(),
        }
        try:
            time.sleep(rate_limit_seconds)
            r = requests.get(base_url, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                # Rate-limited — exponential backoff
                for backoff in (1.0, 2.0, 4.0):
                    logger.warning(f"EDGAR 429; backing off {backoff}s")
                    time.sleep(backoff)
                    r = requests.get(base_url, params=params, headers=headers, timeout=30)
                    if r.status_code != 429:
                        break
            if r.status_code != 200:
                logger.warning(
                    f"EDGAR query failed for {month_start.date()}: HTTP {r.status_code}"
                )
                continue
            j = r.json()
            hits = j.get("hits", {}).get("hits", [])
            raw_hits.extend(hits)
        except Exception as e:
            logger.warning(f"EDGAR fetch error for {month_start.date()}: {e}")
            continue

    events: List[SpinoffEvent] = []
    seen_tickers: set = set()
    for hit in raw_hits:
        src = hit.get("_source", {}) or {}
        display_list = src.get("display_names") or []
        if not display_list:
            continue
        display = display_list[0]
        ticker = _extract_ticker_from_display_name(display)
        if not ticker:
            continue
        if ticker in seen_tickers:
            continue  # one filing per ticker — first one wins
        seen_tickers.add(ticker)

        filing_date = pd.Timestamp(src.get("file_date") or "").normalize()
        if pd.isna(filing_date):
            continue

        distribution_date = filing_date
        if use_yfinance_for_distribution_date:
            first_trade = _yfinance_first_trade_date(ticker)
            if first_trade is not None and first_trade >= filing_date:
                distribution_date = first_trade

        events.append(SpinoffEvent(
            parent_ticker="UNKNOWN",  # not extractable from filing metadata alone
            child_ticker=ticker,
            distribution_date=distribution_date,
            distribution_ratio=1.0,  # unknown; default per spec note
            source="edgar",
            confidence=0.9,
            notes=(
                f"EDGAR Form {src.get('form', '10-12B')} filing {src.get('adsh', '?')}; "
                f"filing_date={filing_date.date()}; "
                f"distribution_date={'yfinance first-trade' if use_yfinance_for_distribution_date and distribution_date != filing_date else 'filing_date fallback'}"
            ),
        ))

    return events


def _edgar_cache_age_days(cache_path: Path = EDGAR_CACHE_PATH) -> Optional[float]:
    """Return cache age in days, or None if no cache file."""
    if not cache_path.exists():
        return None
    mtime = cache_path.stat().st_mtime
    now = datetime.now(timezone.utc).timestamp()
    return (now - mtime) / 86400.0


def _edgar_cache_is_fresh(
    cache_path: Path = EDGAR_CACHE_PATH,
    ttl_days: int = EDGAR_CACHE_TTL_DAYS,
) -> bool:
    age = _edgar_cache_age_days(cache_path)
    if age is None:
        return False
    return age <= ttl_days


def load_edgar_cached_events(
    cache_path: Path = EDGAR_CACHE_PATH,
    enforce_ttl: bool = True,
) -> List[SpinoffEvent]:
    """Load EDGAR-cached SpinoffEvent list from parquet.

    Returns an empty list when the cache is missing or stale beyond
    `EDGAR_CACHE_TTL_DAYS`. Caller can override with `enforce_ttl=False`
    (tests).
    """
    if not cache_path.exists():
        return []
    if enforce_ttl and not _edgar_cache_is_fresh(cache_path):
        logger.warning(
            f"EDGAR cache at {cache_path} is older than {EDGAR_CACHE_TTL_DAYS} days; "
            "ignoring. Re-run `refresh_edgar_cache` to update."
        )
        return []
    try:
        df = pd.read_parquet(cache_path)
    except Exception as e:
        logger.warning(f"could not read EDGAR cache: {e}")
        return []

    out: List[SpinoffEvent] = []
    for _, row in df.iterrows():
        try:
            out.append(SpinoffEvent(
                parent_ticker=row.get("parent_ticker", "UNKNOWN"),
                child_ticker=row.get("child_ticker", ""),
                distribution_date=pd.Timestamp(row["distribution_date"]),
                distribution_ratio=float(row.get("distribution_ratio", 1.0)),
                source=row.get("source", "edgar"),
                confidence=float(row.get("confidence", 0.9)),
                notes=str(row.get("notes", "")),
            ))
        except Exception as e:
            logger.debug(f"skipping malformed cache row: {e}")
            continue
    return out


def refresh_edgar_cache(
    start_date: str,
    end_date: str,
    cache_path: Path = EDGAR_CACHE_PATH,
    **kwargs,
) -> int:
    """Run `detect_spinoffs_edgar` for the window and persist to parquet.

    Overwrites any existing cache file. Returns the number of events
    cached.
    """
    events = detect_spinoffs_edgar(start_date, end_date, **kwargs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in events:
        rows.append({
            "parent_ticker": e.parent_ticker,
            "child_ticker": e.child_ticker,
            "distribution_date": e.distribution_date,
            "distribution_ratio": e.distribution_ratio,
            "source": e.source,
            "confidence": e.confidence,
            "notes": e.notes,
        })
    df = pd.DataFrame(rows)
    df.to_parquet(cache_path, index=False)
    logger.info(f"wrote {len(events)} EDGAR events to {cache_path}")
    return len(events)


def get_events(
    *,
    use_yfinance: bool = False,
    yfinance_parent_tickers: Optional[List[str]] = None,
    use_edgar_cache: bool = True,
    edgar_cache_path: Path = EDGAR_CACHE_PATH,
    curated_path: Path = CURATED_PATH,
    use_cache: bool = True,
) -> List[SpinoffEvent]:
    """Return the merged list of spin-off events from all configured sources.

    Source precedence (highest → lowest confidence):
      1. Curated YAML (confidence 1.0)
      2. EDGAR cached parquet (confidence 0.9) — T-041b addition
      3. yfinance detection (confidence 0.7)

    Higher-confidence sources WIN on (child_ticker, distribution_date)
    collisions. Lower-confidence sources contribute any (child, date)
    not already covered.

    Parameters
    ----------
    use_yfinance
        Enable yfinance-based detection. Default False.
    yfinance_parent_tickers
        Parent tickers to query when `use_yfinance=True`.
    use_edgar_cache
        Default True — read from EDGAR parquet cache. Set False to
        skip the EDGAR layer (tests, or when running in environments
        with no cache file).
    edgar_cache_path
        Override for EDGAR parquet location. Tests use this.
    curated_path
        Override for the curated YAML location. Tests use this.
    use_cache
        If True, return the cached result from a prior call. Tests set False.
    """
    global _CACHED_EVENTS
    if use_cache and _CACHED_EVENTS is not None:
        return list(_CACHED_EVENTS)

    curated = load_curated_events(curated_path)

    edgar_events: List[SpinoffEvent] = []
    if use_edgar_cache:
        edgar_events = load_edgar_cached_events(edgar_cache_path)

    yf_events: List[SpinoffEvent] = []
    if use_yfinance and yfinance_parent_tickers:
        yf_events = detect_from_yfinance(yfinance_parent_tickers)

    # Precedence: curated > EDGAR > yfinance, by (child_ticker, date).
    # Curated entries pin both the (parent, child) pair AND the
    # authoritative distribution_date; EDGAR fills in gaps; yfinance
    # surfaces leftover candidates for manual review.
    seen_child_date = {
        (e.child_ticker, e.distribution_date) for e in curated
    }
    merged: List[SpinoffEvent] = list(curated)
    for ev in edgar_events:
        key = (ev.child_ticker, ev.distribution_date)
        if key in seen_child_date:
            continue
        merged.append(ev)
        seen_child_date.add(key)
    for ev in yf_events:
        key = (ev.child_ticker, ev.distribution_date)
        if key in seen_child_date:
            continue
        merged.append(ev)
        seen_child_date.add(key)

    merged.sort(key=lambda e: (e.distribution_date, e.parent_ticker))

    if use_cache:
        _CACHED_EVENTS = list(merged)
    return merged


def events_in_window(
    events: List[SpinoffEvent],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> List[SpinoffEvent]:
    """Filter `events` to those whose distribution_date is in [start, end].

    Both bounds inclusive. Caller is responsible for tz-naive timestamps;
    SpinoffEvent normalizes to tz-naive in __post_init__.
    """
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if start_ts.tzinfo is not None:
        start_ts = start_ts.tz_localize(None)
    if end_ts.tzinfo is not None:
        end_ts = end_ts.tz_localize(None)
    return [
        ev for ev in events
        if start_ts <= ev.distribution_date <= end_ts
    ]


def events_by_child(
    events: List[SpinoffEvent],
) -> Dict[str, SpinoffEvent]:
    """Index events by child_ticker for fast O(1) lookup in compute_signals.

    If the same child appears in multiple events (re-listings, ticker
    recycle), the latest distribution_date wins. Real spin-offs that
    share a parent (e.g., GE → GEHC then GE → GEV) have different
    children and don't collide.
    """
    out: Dict[str, SpinoffEvent] = {}
    for ev in events:
        existing = out.get(ev.child_ticker)
        if existing is None or ev.distribution_date > existing.distribution_date:
            out[ev.child_ticker] = ev
    return out
