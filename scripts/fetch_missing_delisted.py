"""scripts/fetch_missing_delisted.py
=====================================

Multi-source OHLCV pipeline for tickers that were S&P 500 members at any
point in 2021-01-01..2025-12-31 but are absent from ``data/processed/``.

Why this exists
---------------
The substrate-honest multi-year measurement (mean Sharpe 0.915 on the
surviving 6 edges) is currently an *upper bound* because ~36 delisted
S&P 500 tickers between 2021 and 2025 have no local OHLCV. Without them,
every per-edge attribution and the headline 0.915 is conditional on
excluding tickers that actually existed in the universe at the time.
This script closes that gap by sourcing those names from a chain of
free providers and writing CSV+parquet that match the existing layout.

Source chain (in order)
-----------------------
1. **yfinance** (auto_adjust=True). Yahoo retains a surprising amount
   of post-delisting history for index members. Yahoo uses ``-`` for
   share-class separator (BF-B, BRK-B); the ``YAHOO_OVERRIDES`` map
   handles the membership-table -> Yahoo mapping.
2. **Stooq** direct CSV at ``stooq.com/q/d/l/?s={ticker}.us&i=d``. Free,
   no auth, decent delisted coverage especially for older names. Uses a
   different adjustment convention (split-only, no dividend) — we treat
   it as a fallback and document it in provenance.
3. (Future hook) Tiingo — wired in via ``--tiingo-key`` if a paid free-
   trial run is needed. Off by default.

Output schema (matches existing files)
--------------------------------------
- ``data/processed/{TICKER}_1d.csv``: index reset, columns
  ``Date,Open,High,Low,Close,Volume,ATR,PrevClose``.
- ``data/processed/parquet/{TICKER}_1d.parquet``: DatetimeIndex with
  ``Open,High,Low,Close,Volume,ATR,PrevClose``.

Provenance is tracked in
``data/processed/_data_provenance_delisted.json`` with one record per
ticker: source used, fetch timestamp, row count, date range, and any
notes (e.g., "stooq fallback after yfinance returned 0 rows").

Usage
-----
    python -m scripts.fetch_missing_delisted               # full run
    python -m scripts.fetch_missing_delisted --dry-run     # list only
    python -m scripts.fetch_missing_delisted --tickers FRC SIVB
    python -m scripts.fetch_missing_delisted --start 2018-01-01

The script is idempotent: any ticker that already has a CSV under
``data/processed/`` is skipped unless ``--refresh`` is passed.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engines.data_manager.data_manager import DataManager  # noqa: E402
from engines.data_manager.universe import (  # noqa: E402
    SP500MembershipLoader,
    active_at,
)


PROCESSED_DIR = REPO_ROOT / "data" / "processed"
PARQUET_DIR = PROCESSED_DIR / "parquet"
PROVENANCE_PATH = PROCESSED_DIR / "_data_provenance_delisted.json"

DEFAULT_START = "2018-01-01"

# A few names that need post-S&P-500-removal truncation on top of the
# membership-table date — e.g., the equity stub kept trading at penny
# prices long after the bank failure. Date is the LAST trading day to
# retain (inclusive). When None, truncate at membership.included_until.
HARD_DELIST_DATES: dict[str, str] = {
    "FRC": "2023-05-01",   # halted post-FDIC
    "SIVB": "2023-03-10",  # halted; bankruptcy filed
    "ATVI": "2023-10-13",  # acquired by MSFT
    "TWTR": "2022-10-27",  # taken private by Musk
}

# Yahoo symbol fallbacks if primary returns empty.
YAHOO_FALLBACKS: dict[str, list[str]] = {
    "SIVB": ["SIVBQ", "SIVB"],
    "FRC":  ["FRCB", "FRC"],
}

# Yahoo uses '-' instead of '.' for share-class separators.
# Some membership-table tickers are old names whose Yahoo symbol differs.
YAHOO_OVERRIDES: dict[str, str] = {
    "BF.B": "BF-B",
    "BRK.B": "BRK-B",
    # Old-name -> last Yahoo-known symbol while listed
    "FRC": "FRCB",       # First Republic Bank — OTC pink sheet after FDIC
    "SIVB": "SIVBQ",     # SVB Financial Group — chapter 11 ticker
    "ATVI": "ATVI",      # Activision (acquired by MSFT)
    "TWTR": "TWTR",      # Twitter (delisted post-Musk)
    "DAY": "DAY",        # Dayforce (current ticker)
    "K": "K",            # Kellanova
    "WBA": "WBA",        # Walgreens (delisted Aug 2025)
    "ANSS": "ANSS",
    "JNPR": "JNPR",
    "DFS": "DFS",
    "HES": "HES",
    "IPG": "IPG",
    "CTLT": "CTLT",
    "MRO": "MRO",
    "PXD": "PXD",
    "CMA": "CMA",
    "ABMD": "ABMD",
    "ALXN": "ALXN",
    "CERN": "CERN",
    "CTXS": "CTXS",
    "CXO": "CXO",
    "DISCA": "DISCA",
    "DISCK": "DISCK",
    "DISH": "DISH",
    "DRE": "DRE",
    "FBHS": "FBHS",
    "FLIR": "FLIR",
    "GPS": "GPS",
    "HBI": "HBI",
    "HFC": "HFC",
    "KSU": "KSU",
    "MXIM": "MXIM",
    "NLSN": "NLSN",
    "PBCT": "PBCT",
    "TIF": "TIF",
    "VAR": "VAR",
    "XLNX": "XLNX",
}

# Stooq uses lowercase + ".us" suffix; share-class becomes "-b".
STOOQ_OVERRIDES: dict[str, str] = {
    "BF.B": "bf-b.us",
    "BRK.B": "brk-b.us",
}

# Alpaca uses "." for share class — same as our membership table.
ALPACA_OVERRIDES: dict[str, str] = {}

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2/stocks"


@dataclass
class FetchResult:
    ticker: str
    success: bool
    source: str = ""
    rows: int = 0
    start_date: str = ""
    end_date: str = ""
    notes: list[str] = field(default_factory=list)
    yahoo_symbol: Optional[str] = None
    alpaca_symbol: Optional[str] = None
    stooq_symbol: Optional[str] = None

    def as_record(self) -> dict:
        return {
            "ticker": self.ticker,
            "success": self.success,
            "source": self.source,
            "rows": self.rows,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "notes": self.notes,
            "yahoo_symbol": self.yahoo_symbol,
            "alpaca_symbol": self.alpaca_symbol,
            "stooq_symbol": self.stooq_symbol,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        }


# ----------------------------------------------------------------------
# Source 1: yfinance
# ----------------------------------------------------------------------
def fetch_via_yfinance(
    ticker: str, start: str, end: Optional[str] = None
) -> tuple[pd.DataFrame, str]:
    """Returns (DataFrame, yahoo_symbol_used). Empty DataFrame on failure.

    Tries the ``YAHOO_OVERRIDES`` symbol first, then any fallbacks listed
    in ``YAHOO_FALLBACKS``. Picks whichever variant returns the most rows.
    """
    primary = YAHOO_OVERRIDES.get(ticker, ticker)
    candidates = [primary] + [s for s in YAHOO_FALLBACKS.get(ticker, []) if s != primary]
    best_df = pd.DataFrame()
    best_sym = primary
    for sym in candidates:
        try:
            df = yf.download(
                sym,
                start=start,
                end=end,
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) > len(best_df):
                best_df = df
                best_sym = sym
        except Exception:  # noqa: BLE001
            continue
    return best_df, best_sym


# ----------------------------------------------------------------------
# Source 2: Alpaca historical bars (works for both active and delisted)
# ----------------------------------------------------------------------
def fetch_via_alpaca(
    ticker: str, start: str, end: Optional[str] = None
) -> tuple[pd.DataFrame, str]:
    """Pull daily bars from Alpaca Market Data v2.

    Uses the IEX feed (free tier) with full split/dividend adjustment.
    Returns (DataFrame indexed by Date, symbol_used).
    """
    sym = ALPACA_OVERRIDES.get(ticker, ticker)
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not key or not sec:
        return pd.DataFrame(), f"{sym} (no creds)"

    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    end_str = (end or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    params = {
        "start": f"{start}T00:00:00Z",
        "end": f"{end_str}T23:59:59Z",
        "timeframe": "1Day",
        "feed": "iex",
        "limit": 10000,
        "adjustment": "all",
    }
    rows: list[dict] = []
    page_token: Optional[str] = None
    try:
        for _ in range(20):  # safety bound; 1 day = ~3000 bars max for IEX
            if page_token:
                params["page_token"] = page_token
            r = requests.get(
                f"{ALPACA_DATA_BASE}/{sym}/bars",
                params=params,
                headers=headers,
                timeout=60,
            )
            if r.status_code == 404:
                return pd.DataFrame(), f"{sym} (404)"
            if r.status_code == 422:
                return pd.DataFrame(), f"{sym} (422 invalid)"
            if r.status_code != 200:
                return pd.DataFrame(), f"{sym} (HTTP {r.status_code} {r.text[:120]})"
            payload = r.json()
            bars = payload.get("bars") or []
            rows.extend(bars)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"{sym} (error: {exc!r})"

    if not rows:
        return pd.DataFrame(), f"{sym} (no bars)"

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["t"]).dt.tz_convert(None).dt.normalize()
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    df = df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df, sym


# ----------------------------------------------------------------------
# Source 3: Stooq
# ----------------------------------------------------------------------
def _stooq_url(ticker: str) -> str:
    sym = STOOQ_OVERRIDES.get(ticker, f"{ticker.lower()}.us")
    return f"https://stooq.com/q/d/l/?s={sym}&i=d"


def fetch_via_stooq(
    ticker: str, start: str, end: Optional[str] = None
) -> tuple[pd.DataFrame, str]:
    """Stooq returns full history as CSV; we slice to [start, end] post-fetch."""
    sym = STOOQ_OVERRIDES.get(ticker, f"{ticker.lower()}.us")
    url = _stooq_url(ticker)
    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; trading-machine-2/1.0)"},
        )
        if resp.status_code != 200:
            return pd.DataFrame(), f"{sym} (HTTP {resp.status_code})"
        text = resp.text
        if "No data" in text or len(text) < 80:
            return pd.DataFrame(), f"{sym} (no data)"
        df = pd.read_csv(io.StringIO(text))
        if df.empty or "Date" not in df.columns:
            return pd.DataFrame(), f"{sym} (empty/bad-cols)"
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).set_index("Date")
        # Slice to window
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end) if end else None
        df = df[df.index >= start_ts]
        if end_ts is not None:
            df = df[df.index <= end_ts]
        return df, sym
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"{sym} (error: {exc!r})"


# ----------------------------------------------------------------------
# Persist to disk in the canonical schema
# ----------------------------------------------------------------------
def _normalize_for_save(df: pd.DataFrame) -> pd.DataFrame:
    """Use DataManager._normalize_df to compute ATR + PrevClose + dtype clean."""
    return DataManager._normalize_df(df.copy())


def _delisting_cutoff(ticker: str) -> Optional[pd.Timestamp]:
    """Return the last legitimate trading day to retain, or None if no cap.

    Priority order:
      1. ``HARD_DELIST_DATES`` override (post-removal stub trading).
      2. Membership table ``included_until`` (date removed from S&P 500).
      3. None — keep everything (still in index).
    """
    if ticker in HARD_DELIST_DATES:
        return pd.Timestamp(HARD_DELIST_DATES[ticker])
    try:
        loader = SP500MembershipLoader()
        df = loader.fetch_membership()
    except Exception:  # noqa: BLE001
        return None
    rows = df[df["ticker"] == ticker]
    if rows.empty:
        return None
    last_until = rows["included_until"].max()
    if pd.isna(last_until):
        return None
    # Add a 5-trading-day buffer to capture any trading immediately after
    # removal — the membership table records the removal date, not the
    # last trading day.
    return pd.Timestamp(last_until) + pd.Timedelta(days=7)


def _drop_sparse_leading_rows(df: pd.DataFrame, max_gap_days: int = 30) -> pd.DataFrame:
    """Drop leading rows separated from the main run by a >max_gap_days gap.

    Alpaca occasionally emits a stray odd-lot bar months before the real
    data starts (low volume, single isolated date). These show up as a
    multi-hundred-day gap to the next row and break ATR/PrevClose
    continuity. Walk forward and drop any leading rows that end with a
    gap larger than ``max_gap_days``.
    """
    if df.empty or len(df) < 3:
        return df
    sorted_df = df.sort_index()
    gaps = sorted_df.index.to_series().diff().dt.days
    big_gap_pos = gaps[gaps > max_gap_days].index
    if len(big_gap_pos) == 0:
        return sorted_df
    # Largest leading gap — drop everything before it.
    first_big = big_gap_pos[0]
    # Only drop if the leading section is < 5% of total rows (i.e. a stray
    # head, not a legitimate older window).
    leading_count = (sorted_df.index < first_big).sum()
    if leading_count == 0 or leading_count >= len(sorted_df) * 0.05:
        return sorted_df
    return sorted_df.loc[sorted_df.index >= first_big]


def save_ticker(ticker: str, df: pd.DataFrame) -> int:
    """Persist OHLCV; returns the row count after truncation/cleaning."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)

    # Drop stray leading rows (sub-1%-of-total isolated by >30d gaps).
    df = _drop_sparse_leading_rows(df)

    # Truncate at delisting date if applicable
    cutoff = _delisting_cutoff(ticker)
    if cutoff is not None and not df.empty:
        idx = pd.to_datetime(df.index, errors="coerce")
        df = df.loc[idx <= cutoff]

    df_norm = _normalize_for_save(df)

    csv_path = PROCESSED_DIR / f"{ticker}_1d.csv"
    pq_path = PARQUET_DIR / f"{ticker}_1d.parquet"

    df_norm.to_parquet(pq_path, index=True)

    csv_view = df_norm.copy()
    csv_view.index.name = "Date"
    csv_view.to_csv(csv_path, date_format="%Y-%m-%d")
    return int(len(df_norm))


def load_provenance() -> dict:
    if not PROVENANCE_PATH.exists():
        return {}
    try:
        return json.loads(PROVENANCE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_provenance(prov: dict) -> None:
    tmp = PROVENANCE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(prov, indent=2, sort_keys=True))
    tmp.replace(PROVENANCE_PATH)


# ----------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------
def fetch_one(
    ticker: str,
    start: str,
    end: Optional[str] = None,
    skip_yfinance: bool = False,
    skip_alpaca: bool = False,
    skip_stooq: bool = False,
) -> FetchResult:
    result = FetchResult(ticker=ticker, success=False)
    df = pd.DataFrame()
    # Priority chain: Alpaca (works for delisted) -> yfinance -> Stooq.
    # Alpaca is first because it's the only consistently-working source
    # for post-delisting names as of 2026-05; yfinance now 404s on
    # essentially any non-trading symbol, and Stooq put up a captcha
    # API-key wall.
    if not skip_alpaca:
        df, sym = fetch_via_alpaca(ticker, start, end)
        result.alpaca_symbol = sym
        if not df.empty:
            result.source = "alpaca"
            result.notes.append(f"alpaca returned {len(df)} rows for {sym}")
        else:
            result.notes.append(f"alpaca empty for {sym}")
    if df.empty and not skip_yfinance:
        df, sym = fetch_via_yfinance(ticker, start, end)
        result.yahoo_symbol = sym
        if not df.empty:
            result.source = "yfinance"
            result.notes.append(f"yfinance returned {len(df)} rows for {sym}")
        else:
            result.notes.append(f"yfinance empty for {sym}")
    if df.empty and not skip_stooq:
        df, sym = fetch_via_stooq(ticker, start, end)
        result.stooq_symbol = sym
        if not df.empty:
            result.source = "stooq"
            result.notes.append(f"stooq returned {len(df)} rows for {sym}")
        else:
            result.notes.append(f"stooq empty for {sym}")

    if df.empty:
        result.notes.append("all sources exhausted")
        return result

    # Persist (with delisting truncation applied inside save_ticker)
    try:
        rows_kept = save_ticker(ticker, df)
    except Exception as exc:  # noqa: BLE001
        result.notes.append(f"save failed: {exc!r}")
        return result

    if rows_kept == 0:
        result.notes.append("post-truncation/cleaning row count is 0")
        return result

    # Re-read what we just persisted to populate provenance with the
    # final on-disk window.
    persisted = pd.read_parquet(PARQUET_DIR / f"{ticker}_1d.parquet")
    persisted = persisted.sort_index()
    result.success = True
    result.rows = int(len(persisted))
    result.start_date = persisted.index.min().strftime("%Y-%m-%d")
    result.end_date = persisted.index.max().strftime("%Y-%m-%d")
    return result


def discover_missing_tickers(window_start: str, window_end: str) -> list[str]:
    loader = SP500MembershipLoader()
    df = loader.fetch_membership()

    months = pd.date_range(window_start, window_end, freq="MS")
    active: set[str] = set()
    for d in months:
        active.update(active_at(df, d))

    csv_set = {p.name.replace("_1d.csv", "") for p in PROCESSED_DIR.glob("*_1d.csv")}
    pq_set = {p.name.replace("_1d.parquet", "") for p in PARQUET_DIR.glob("*_1d.parquet")}
    on_disk = csv_set | pq_set

    missing = sorted(active - on_disk)
    return missing


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m scripts.fetch_missing_delisted",
        description=(
            "Fill OHLCV gaps for delisted S&P 500 names not present in "
            "data/processed/. Sources: yfinance, then Stooq."
        ),
    )
    p.add_argument(
        "--start",
        default=DEFAULT_START,
        help=f"Backfill start date (default: {DEFAULT_START}).",
    )
    p.add_argument(
        "--end",
        default=None,
        help="Backfill end date (default: today).",
    )
    p.add_argument(
        "--window-start",
        default="2021-01-01",
        help="S&P 500 membership window start (default: 2021-01-01).",
    )
    p.add_argument(
        "--window-end",
        default="2025-12-31",
        help="S&P 500 membership window end (default: 2025-12-31).",
    )
    p.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker list (skips discover-missing). Useful for retry.",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch tickers that already have a cached CSV/parquet.",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--rate-limit-s",
        type=float,
        default=0.5,
        help="Sleep between per-ticker fetches (default 0.5s).",
    )
    p.add_argument("--skip-yfinance", action="store_true")
    p.add_argument("--skip-alpaca", action="store_true")
    p.add_argument("--skip-stooq", action="store_true")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if args.tickers:
        targets = sorted({t.upper() for t in args.tickers})
        print(f"[FETCH_MISSING] using --tickers override: {len(targets)} names")
    else:
        targets = discover_missing_tickers(args.window_start, args.window_end)
        print(
            f"[FETCH_MISSING] discovered {len(targets)} missing names from "
            f"S&P 500 union {args.window_start}..{args.window_end}"
        )

    if not args.refresh:
        targets = [
            t
            for t in targets
            if not (PROCESSED_DIR / f"{t}_1d.csv").exists()
        ]

    print(f"[FETCH_MISSING] targets to fetch: {len(targets)}")
    if args.dry_run:
        for t in targets:
            print(f"  - {t}")
        return 0

    prov = load_provenance()
    sourced: list[FetchResult] = []
    failed: list[FetchResult] = []

    for i, t in enumerate(targets, 1):
        print(f"[FETCH_MISSING] ({i}/{len(targets)}) {t} ...", flush=True)
        r = fetch_one(
            t,
            start=args.start,
            end=args.end,
            skip_yfinance=args.skip_yfinance,
            skip_alpaca=args.skip_alpaca,
            skip_stooq=args.skip_stooq,
        )
        prov[t] = r.as_record()
        save_provenance(prov)
        if r.success:
            sourced.append(r)
            print(
                f"  OK  via {r.source}: {r.rows} rows {r.start_date}->{r.end_date}",
                flush=True,
            )
        else:
            failed.append(r)
            print(f"  FAIL: {' | '.join(r.notes)}", flush=True)
        if i < len(targets) and args.rate_limit_s > 0:
            time.sleep(args.rate_limit_s)

    # Summary
    print()
    print("=" * 60)
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"Requested: {len(targets)}")
    print(f"Sourced:   {len(sourced)}")
    print(f"Failed:    {len(failed)}")
    by_source: dict[str, int] = {}
    for r in sourced:
        by_source[r.source] = by_source.get(r.source, 0) + 1
    for s, n in by_source.items():
        print(f"  {s}: {n}")
    if failed:
        print("\nFailures:")
        for r in failed:
            print(f"  {r.ticker}: {' | '.join(r.notes)}")
    coverage = len(sourced) / max(len(targets), 1)
    print(f"\nCoverage: {coverage*100:.1f}%")
    return 0 if coverage >= 0.80 else 1


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
