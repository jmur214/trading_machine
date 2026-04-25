# engines/data_manager/insider_data.py
"""
OpenInsider Form 4 scraping pipeline.

Self-contained fetch + parquet cache for corporate insider transactions
(Form 4 filings) per ticker. Designed to feed insider-buying / insider-
selling edges and any event-driven logic that wants to align price action
with insider activity — this module owns I/O and caching only, no signal
logic.

Why this exists
---------------
Per the 2026-04-24 strategic pivot doc, net insider buying historically
predicts 3–12 month returns and is one of the highest-leverage free data
sources the system isn't yet seeing. OpenInsider (http://openinsider.com)
republishes SEC Form 4 filings in a clean HTML table; this module is the
foundation an edge will later sit on top of. Edge integration is a
separate handoff.

Key design choices
------------------
- OpenInsider is unauthenticated — no API key. The manager runs in
  cache-first mode and falls back to cache on any network failure.
- Parquet cache at ``data/insider/<TICKER>.parquet``, with a sidecar
  ``_meta.json`` recording the last successful fetch per ticker. Mirrors
  the Finnhub earnings cache pattern in ``earnings_data.py``.
- Cache-first: ``fetch_filings`` returns cached data if it is fresher
  than ``max_age_hours`` (default 24h — Form 4 filings post throughout
  the day, so a daily refresh window strikes a reasonable balance).
- Network failures degrade gracefully: if OpenInsider is unreachable the
  cache is returned with a warning rather than raising. Edges should
  never crash because OpenInsider is down.
- Per-call rate limit (1.5s sleep between fetches by default).
  OpenInsider is operated by a small team — be a good citizen.
  Configurable; set to 0 in tests.
- Single-page fetch (cnt=1000). Pagination is intentionally NOT
  implemented in v1 — at the universe sizes the project uses, no ticker
  hits the cap from 2020 forward. A warning is logged if it does.
- No engine wiring in this file. Integration is a separate handoff.

Cached schema (per ticker)
--------------------------
Index: ``transaction_date`` (naive Timestamp, the trade date OpenInsider
reports for the Form 4).

Columns:
    filing_date           Timestamp  when the Form 4 was filed
    ticker                str        uppercase ticker
    insider_name          str        e.g. "O'Brien Deirdre"
    insider_title         str        e.g. "CEO", "SVP", "10% Owner"
    transaction_type      str        single char, normalized: 'P' or 'S'
                                     (or '' if neither)
    transaction_subtype   str        full OpenInsider label,
                                     e.g. "S - Sale+OE"
    price                 float64    per-share USD
    shares                Int64      signed; negative for sales
    holdings_after        Int64      post-transaction holdings ("Owned")
    delta_holdings_pct    float64    fractional change ("ΔOwn"); NaN
                                     for the "New" sentinel
    value                 float64    total USD value, signed
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parents[2]


OPENINSIDER_BASE = "http://openinsider.com/screener"
DEFAULT_CACHE_DIR = ROOT_DIR / "data" / "insider"
DEFAULT_START = "2020-01-01"
DEFAULT_TIMEOUT_S = 15
DEFAULT_MAX_AGE_HOURS = 24
# OpenInsider is operated by a small team. 1.5s between calls keeps us
# polite while still letting a 109-ticker universe refresh in <3 minutes.
DEFAULT_RATE_LIMIT_S = 1.5
DEFAULT_PAGE_LIMIT = 1000
DEFAULT_USER_AGENT = "ArchonDEX-research/1.0 (insider-data-collector)"


# Column order for cached frames. Kept stable so consumers can rely on
# positional access if they need it.
INSIDER_TXN_COLUMNS = [
    "filing_date",
    "ticker",
    "insider_name",
    "insider_title",
    "transaction_type",
    "transaction_subtype",
    "price",
    "shares",
    "holdings_after",
    "delta_holdings_pct",
    "value",
]


class InsiderDataError(Exception):
    """Raised for non-recoverable failures in the insider data pipeline."""


@dataclass(frozen=True)
class InsiderTxn:
    """Lightweight value type for a single insider transaction.

    Not used internally — the manager works in DataFrame space — but
    exposed for consumers that prefer typed records (e.g., an edge
    iterating events to score each one).
    """
    ticker: str
    transaction_date: pd.Timestamp
    filing_date: pd.Timestamp
    insider_name: str
    insider_title: str
    transaction_type: str
    transaction_subtype: str
    price: Optional[float]
    shares: Optional[int]
    holdings_after: Optional[int]
    delta_holdings_pct: Optional[float]
    value: Optional[float]


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class InsiderDataManager:
    """Fetch + cache OpenInsider Form 4 transactions per ticker.

    Parameters
    ----------
    cache_dir:
        Directory for parquet cache. Defaults to ``data/insider/`` at
        the repo root.
    timeout_s:
        Network timeout for individual OpenInsider requests.
    rate_limit_s:
        Minimum seconds between consecutive network fetches issued by
        this manager. 0 disables rate limiting (use only in tests).
    user_agent:
        Sent on every request. Identifying ourselves keeps OpenInsider
        from blacklisting the IP if traffic ever spikes.
    """

    def __init__(
        self,
        cache_dir: Optional[Path | str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        rate_limit_s: float = DEFAULT_RATE_LIMIT_S,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.rate_limit_s = float(rate_limit_s)
        self.user_agent = user_agent
        self._meta_path = self.cache_dir / "_meta.json"
        self._last_fetch_monotonic: float = 0.0

    # ----- cache layout -----
    def _cache_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}.parquet"

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

    def _record_fetch(self, ticker: str, n_rows: int) -> None:
        meta = self._read_meta()
        meta[ticker.upper()] = {
            "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(n_rows),
        }
        self._write_meta(meta)

    def _cache_age_hours(self, ticker: str) -> Optional[float]:
        path = self._cache_path(ticker)
        if not path.exists():
            return None
        return (time.time() - path.stat().st_mtime) / 3600.0

    # ----- public API -----
    def load_cached(self, ticker: str) -> pd.DataFrame:
        """Read a cached transactions frame without touching the network."""
        path = self._cache_path(ticker)
        if not path.exists():
            return _empty_txn_frame()
        return pd.read_parquet(path)

    def fetch_filings(
        self,
        ticker: str,
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch one ticker's insider transactions, with cache.

        Returns a DataFrame indexed by ``transaction_date`` with the
        schema documented at module top.

        Cache-first: returns the cached parquet if fresher than
        ``max_age_hours``. On network failure the existing cache is
        returned (with a warning); only when there is no cache does the
        failure raise ``InsiderDataError``.
        """
        ticker = ticker.upper().strip()
        cached_age = self._cache_age_hours(ticker)
        if not force and cached_age is not None and cached_age < max_age_hours:
            return self.load_cached(ticker)

        try:
            df = self._download_filings(ticker, start=start, end=end)
        except (requests.RequestException, InsiderDataError) as exc:
            if cached_age is not None:
                _log(f"OpenInsider fetch failed for {ticker} ({exc!s}); "
                     f"falling back to cache aged {cached_age:.1f}h")
                return self.load_cached(ticker)
            raise InsiderDataError(
                f"OpenInsider fetch failed for {ticker} and no cache "
                f"available: {exc}"
            ) from exc

        self._save(ticker, df)
        return df

    def fetch_universe(
        self,
        tickers: Iterable[str],
        start: Optional[str] = DEFAULT_START,
        end: Optional[str] = None,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch a list of tickers and concatenate into one long frame.

        Failed tickers are skipped with a warning rather than aborting
        the whole run. Returns a DataFrame with the same column schema
        as ``fetch_filings``, indexed by transaction date and sorted.
        Tickers that have no transactions on disk and cannot be fetched
        contribute zero rows (not NaN-filled rows).
        """
        tickers = [t.upper().strip() for t in tickers]
        frames: list[pd.DataFrame] = []
        failures: list[tuple[str, str]] = []
        for tkr in tickers:
            try:
                df = self.fetch_filings(
                    tkr, start=start, end=end, force=force,
                    max_age_hours=max_age_hours,
                )
                if not df.empty:
                    frames.append(df)
            except InsiderDataError as exc:
                failures.append((tkr, str(exc)))
                _log(f"skipping {tkr} in universe fetch: {exc}")

        if not frames:
            if failures:
                raise InsiderDataError(
                    f"No tickers fetched. Failures: {failures}"
                )
            return _empty_txn_frame()

        combined = pd.concat(frames, axis=0).sort_index()
        return combined

    def cache_status(self) -> pd.DataFrame:
        """Return a DataFrame describing the on-disk cache state.

        Walks the cache directory rather than a registry — the universe
        of tickers is open-ended.
        """
        meta = self._read_meta()
        rows = []
        for path in sorted(self.cache_dir.glob("*.parquet")):
            ticker = path.stem
            entry = meta.get(ticker, {})
            rows.append({
                "ticker": ticker,
                "cached": True,
                "age_hours": self._cache_age_hours(ticker),
                "n_rows": entry.get("n_rows"),
                "last_fetched_utc": entry.get("last_fetched_utc"),
            })
        return pd.DataFrame(
            rows,
            columns=["ticker", "cached", "age_hours", "n_rows",
                     "last_fetched_utc"],
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

    def _download_filings(
        self,
        ticker: str,
        start: Optional[str],
        end: Optional[str],
    ) -> pd.DataFrame:
        # OpenInsider's screener takes filing-date range in MM/DD/YYYY.
        from_dt = pd.Timestamp(start or DEFAULT_START)
        to_dt = pd.Timestamp(end) if end else pd.Timestamp(
            datetime.now(timezone.utc).date()
        )
        fdr = f"{from_dt.strftime('%m/%d/%Y')}-{to_dt.strftime('%m/%d/%Y')}"
        params = {
            "s": ticker,
            "o": "",
            "pl": "", "ph": "",
            "ll": "", "lh": "",
            "fd": "0",
            "fdr": fdr,
            "td": "0",
            "tdr": "",
            "fdlyl": "", "fdlyh": "",
            "daysago": "",
            "xp": "1",   # include purchases
            "xs": "1",   # include sales
            "vl": "", "vh": "",
            "ocl": "", "och": "",
            "sic1": "-1", "sicl": "100", "sich": "9999",
            "grp": "0",
            "nfl": "", "nfh": "",
            "nil": "", "nih": "",
            "nol": "", "noh": "",
            "v2l": "", "v2h": "",
            "oc2l": "", "oc2h": "",
            "sortcol": "0",
            "cnt": str(DEFAULT_PAGE_LIMIT),
            "page": "1",
        }

        self._respect_rate_limit()
        resp = requests.get(
            OPENINSIDER_BASE,
            params=params,
            timeout=self.timeout_s,
            headers={"User-Agent": self.user_agent},
        )
        if resp.status_code != 200:
            raise InsiderDataError(
                f"OpenInsider returned HTTP {resp.status_code} for {ticker}: "
                f"{resp.text[:200]}"
            )
        df = parse_insider_table(resp.text, fallback_ticker=ticker)
        if len(df) >= DEFAULT_PAGE_LIMIT:
            _log(f"{ticker} hit the {DEFAULT_PAGE_LIMIT}-row page cap; "
                 f"some transactions may be missing. Pagination is not "
                 f"implemented in v1.")
        return df

    def _save(self, ticker: str, df: pd.DataFrame) -> None:
        path = self._cache_path(ticker)
        df.to_parquet(path)
        self._record_fetch(ticker, len(df))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def parse_insider_table(html: str, fallback_ticker: str) -> pd.DataFrame:
    """Parse an OpenInsider screener HTML response.

    Extracts the ``<table class="tinytable">`` body into the canonical
    ``INSIDER_TXN_COLUMNS`` frame indexed by transaction date.

    Robustness:
        - Missing or empty table → returns an empty frame (does NOT raise).
          OpenInsider serves the same layout with an empty <tbody> for
          tickers with no transactions in the window.
        - Unparseable cells → NaN / pd.NA, never propagate exceptions.
        - "S - Sale+OE" / "P - Purchase" labels → first char becomes
          ``transaction_type``; full label is preserved in
          ``transaction_subtype``.
        - "$255.35" / "-$7,660,875" / "-30,002" → stripped of $ and ,
          and parsed as signed floats / ints.
        - "ΔOwn" of "New" or "-" → pd.NA.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tinytable")
    if table is None:
        return _empty_txn_frame()

    body = table.find("tbody")
    if body is None:
        return _empty_txn_frame()

    rows: list[dict] = []
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 12:
            # OpenInsider rows always have 16 cells; anything shorter is
            # a layout edge case we can safely skip.
            continue

        trade_date = pd.to_datetime(_text(cells[2]), errors="coerce")
        if pd.isna(trade_date):
            continue

        filing_date = pd.to_datetime(_text(cells[1]), errors="coerce")
        ticker_cell = _text(cells[3]).upper() or fallback_ticker.upper()
        insider_name = _text(cells[4])
        insider_title = _text(cells[5])
        subtype = _text(cells[6])
        ttype = _normalize_trade_type(subtype)

        rows.append({
            "transaction_date": trade_date,
            "filing_date": filing_date,
            "ticker": ticker_cell,
            "insider_name": insider_name,
            "insider_title": insider_title,
            "transaction_type": ttype,
            "transaction_subtype": subtype,
            "price": _parse_money(_text(cells[7])),
            "shares": _parse_int(_text(cells[8])),
            "holdings_after": _parse_int(_text(cells[9])),
            "delta_holdings_pct": _parse_pct(_text(cells[10])),
            "value": _parse_money(_text(cells[11])),
        })

    if not rows:
        return _empty_txn_frame()

    df = pd.DataFrame(rows).set_index("transaction_date").sort_index()
    df = df.reindex(columns=INSIDER_TXN_COLUMNS)
    df["shares"] = df["shares"].astype("Int64")
    df["holdings_after"] = df["holdings_after"].astype("Int64")
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _empty_txn_frame() -> pd.DataFrame:
    """Empty DataFrame with the canonical schema."""
    df = pd.DataFrame({col: pd.Series([], dtype=_dtype_for(col))
                       for col in INSIDER_TXN_COLUMNS})
    df.index = pd.DatetimeIndex([], name="transaction_date")
    return df


def _dtype_for(col: str) -> str:
    if col in {"shares", "holdings_after"}:
        return "Int64"
    if col in {
        "ticker", "insider_name", "insider_title",
        "transaction_type", "transaction_subtype",
    }:
        return "object"
    if col == "filing_date":
        return "datetime64[ns]"
    return "float64"


def _text(cell) -> str:
    """BeautifulSoup-safe text extraction with whitespace normalization."""
    if cell is None:
        return ""
    return cell.get_text(strip=True).replace("\xa0", " ")


def _normalize_trade_type(subtype: str) -> str:
    """Extract the leading P / S code from an OpenInsider trade-type label."""
    s = (subtype or "").strip().upper()
    if not s:
        return ""
    head = s[0]
    if head in {"P", "S"}:
        return head
    return ""


def _parse_money(s: str) -> float:
    """Strip $ and commas, parse signed float. NaN on failure."""
    if s is None:
        return float("nan")
    cleaned = s.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return float("nan")
    try:
        return float(cleaned)
    except ValueError:
        return float("nan")


def _parse_int(s: str):
    """Strip commas, parse signed int. pd.NA on failure."""
    if s is None:
        return pd.NA
    cleaned = s.replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return pd.NA
    try:
        return int(cleaned)
    except ValueError:
        # Some cells contain decimal qty (rare, fractional shares).
        try:
            return int(float(cleaned))
        except ValueError:
            return pd.NA


def _parse_pct(s: str) -> float:
    """Convert "-18%" to -0.18; "New" sentinel and bare "-" become NaN."""
    if s is None:
        return float("nan")
    cleaned = s.replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned.lower() == "new" or cleaned == "-":
        return float("nan")
    try:
        return float(cleaned) / 100.0
    except ValueError:
        return float("nan")


def _log(msg: str) -> None:
    """Lightweight logger compatible with the existing data_manager style.

    Routes through ``debug_config`` if available, otherwise stays silent.
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
        print(f"[INSIDER_DATA] {msg}")
