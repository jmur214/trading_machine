"""scripts/fetch_universe.py

CLI tool to populate the OHLCV cache (``data/processed/``) for a
universe of tickers, using the existing ``DataManager`` pipeline.

This is the explicit user-driven companion to
``engines/data_manager/universe.py``. Invoke it after expanding the
universe list to fetch the OHLCV bars that aren't already cached;
the discovery / backtest pipelines pick up new tickers automatically
once their parquet files exist.

Why this is a CLI, not a hook
-----------------------------
Backfilling several hundred tickers is a 30-60 minute job that hits
Alpaca's free-tier rate limit and needs a working network. We do not
want it firing automatically from imports, tests, or backtests. The
universe loader keeps the membership list current with low cost; this
script is the heavy operation that runs only when the user asks.

Usage
-----
    python -m scripts.fetch_universe --source sp500_historical
    python -m scripts.fetch_universe --source sp500_current --start 2018-01-01
    python -m scripts.fetch_universe --source file --file my_tickers.txt
    python -m scripts.fetch_universe --source sp500_historical --dry-run
    python -m scripts.fetch_universe --source sp500_historical --max-tickers 25

Outputs a summary of what was already cached vs. fetched vs. failed.
By default the script is *idempotent*: tickers whose parquet file
already exists in ``data/processed/parquet/`` are skipped. Pass
``--refresh`` to re-fetch everything regardless of cache state.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Repo-root import path so this script runs both as `python -m scripts.X`
# and `python scripts/X.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.data_manager.data_manager import DataManager  # noqa: E402
from engines.data_manager.universe import (  # noqa: E402
    SP500MembershipLoader,
    UniverseError,
)


DEFAULT_START = "2018-01-01"
DEFAULT_TIMEFRAME = "1d"
DEFAULT_PROCESSED_DIR = "data/processed"


@dataclass
class FetchSummary:
    requested: int = 0
    already_cached: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            "",
            "=" * 60,
            "UNIVERSE FETCH SUMMARY",
            "=" * 60,
            f"Requested:      {self.requested}",
            f"Already cached: {len(self.already_cached)}",
            f"Newly fetched:  {len(self.fetched)}",
            f"Failed:         {len(self.failed)}",
        ]
        if self.fetched:
            preview = ", ".join(self.fetched[:10])
            extra = "" if len(self.fetched) <= 10 else f" (+{len(self.fetched) - 10} more)"
            lines.append(f"  fetched: {preview}{extra}")
        if self.failed:
            lines.append("  failures:")
            for ticker, reason in self.failed[:10]:
                lines.append(f"    {ticker}: {reason}")
            if len(self.failed) > 10:
                lines.append(f"    ... (+{len(self.failed) - 10} more)")
        lines.append("=" * 60)
        return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m scripts.fetch_universe",
        description=(
            "Fetch OHLCV for a universe of tickers using the existing "
            "DataManager. Skips tickers already in data/processed/."
        ),
    )
    p.add_argument(
        "--source",
        choices=["sp500_historical", "sp500_current", "file"],
        default="sp500_historical",
        help=(
            "Where to get the ticker list. 'sp500_historical' uses the "
            "full union of all tickers ever in the S&P 500 (so backtests "
            "can replay any historical date without survivorship bias). "
            "'sp500_current' is just today's constituents. 'file' reads "
            "newline-separated tickers from --file."
        ),
    )
    p.add_argument(
        "--file",
        type=Path,
        help="Path to a newline-separated ticker file (required when --source=file).",
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
        "--timeframe",
        default=DEFAULT_TIMEFRAME,
        help=f"Bar timeframe (default: {DEFAULT_TIMEFRAME}).",
    )
    p.add_argument(
        "--processed-dir",
        default=DEFAULT_PROCESSED_DIR,
        help=f"Cache dir to check for existing data (default: {DEFAULT_PROCESSED_DIR}).",
    )
    p.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Optional cap on how many missing tickers to fetch this run.",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch tickers that already have a cached parquet.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be fetched but do not call the API.",
    )
    p.add_argument(
        "--rate-limit-s",
        type=float,
        default=0.0,
        help=(
            "Sleep this many seconds between per-ticker fetches. "
            "DataManager already retries with backoff on 429s; bump this "
            "if you're seeing rate-limit errors."
        ),
    )
    return p.parse_args(argv)


def load_ticker_list(args: argparse.Namespace) -> list[str]:
    """Resolve --source into a deduped, sorted ticker list."""
    if args.source == "file":
        if args.file is None:
            raise SystemExit("--source=file requires --file <path>.")
        if not args.file.exists():
            raise SystemExit(f"--file not found: {args.file}")
        text = args.file.read_text()
        tickers = [t.strip().upper() for t in text.splitlines() if t.strip()]
        return sorted(set(tickers))

    loader = SP500MembershipLoader()
    try:
        df = loader.fetch_membership()
    except UniverseError as exc:
        raise SystemExit(
            f"Could not load S&P 500 membership: {exc}\n"
            "If you are offline and have no cached membership, run with "
            "network access first or pass --source=file with your own list."
        )

    if args.source == "sp500_current":
        # current spell only — the open ones
        tickers = df.loc[df["included_until"].isna(), "ticker"].dropna().unique()
    else:
        # sp500_historical = union of every ticker that ever appears
        tickers = df["ticker"].dropna().unique()

    return sorted({str(t).upper() for t in tickers if str(t).strip()})


def split_cached_vs_missing(
    tickers: list[str],
    processed_dir: Path,
    timeframe: str,
    refresh: bool,
) -> tuple[list[str], list[str]]:
    """Partition the universe into already-cached vs. missing tickers.

    Match the layout DataManager already uses: parquet at
    ``{processed_dir}/parquet/{ticker}_{timeframe}.parquet``.
    """
    parquet_dir = processed_dir / "parquet"
    cached, missing = [], []
    for t in tickers:
        path = parquet_dir / f"{t}_{timeframe}.parquet"
        if path.exists() and not refresh:
            cached.append(t)
        else:
            missing.append(t)
    return cached, missing


def credentials_available() -> bool:
    """True if DataManager will be able to talk to Alpaca.

    Mirrors the resolution order in ``DataManager.__init__``.
    """
    import os
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    sec = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    return bool(key) and bool(sec)


def fetch_one(
    dm: DataManager,
    ticker: str,
    start: str,
    end: str | None,
    timeframe: str,
) -> tuple[bool, str]:
    """Fetch a single ticker and return (success, message).

    Wraps DataManager.ensure_data so we can surface a per-ticker
    success/failure summary at the end of the run.
    """
    try:
        result = dm.ensure_data([ticker], start=start, end=end, timeframe=timeframe)
        df = result.get(ticker)
        if df is None or df.empty:
            return False, "no rows returned"
        return True, f"{len(df)} rows"
    except Exception as exc:  # noqa: BLE001 — pipeline-defensive
        return False, repr(exc)


def run(args: argparse.Namespace) -> int:
    tickers = load_ticker_list(args)
    summary = FetchSummary(requested=len(tickers))

    processed_dir = Path(args.processed_dir)
    cached, missing = split_cached_vs_missing(
        tickers, processed_dir, args.timeframe, args.refresh,
    )
    summary.already_cached = cached

    if args.max_tickers is not None and args.max_tickers >= 0:
        if len(missing) > args.max_tickers:
            print(
                f"[FETCH_UNIVERSE] capping fetch to {args.max_tickers} "
                f"of {len(missing)} missing tickers (--max-tickers).",
                flush=True,
            )
            missing = missing[: args.max_tickers]

    print(
        f"[FETCH_UNIVERSE] source={args.source} timeframe={args.timeframe} "
        f"start={args.start} end={args.end or 'today'} "
        f"requested={len(tickers)} cached={len(cached)} "
        f"to_fetch={len(missing)} dry_run={args.dry_run}",
        flush=True,
    )

    if args.dry_run:
        if missing:
            preview = ", ".join(missing[:20])
            extra = "" if len(missing) <= 20 else f" (+{len(missing) - 20} more)"
            print(f"[FETCH_UNIVERSE][DRY-RUN] would fetch: {preview}{extra}")
        else:
            print("[FETCH_UNIVERSE][DRY-RUN] nothing to fetch.")
        print(summary.report())
        return 0

    if not missing:
        print("[FETCH_UNIVERSE] nothing to fetch — universe already cached.")
        print(summary.report())
        return 0

    if not credentials_available():
        print(
            "[FETCH_UNIVERSE][ERROR] Alpaca credentials not found. "
            "Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env (or use the "
            "APCA_API_KEY_ID / APCA_API_SECRET_KEY aliases). DataManager "
            "will fall back to yfinance if Alpaca fetch fails, but you "
            "still need either credentials or a working yfinance "
            "connection. Re-run with --dry-run to verify the ticker list "
            "without hitting any API.",
            file=sys.stderr,
        )
        return 2

    dm = DataManager(cache_dir=str(processed_dir))
    for i, ticker in enumerate(missing, 1):
        print(f"[FETCH_UNIVERSE] ({i}/{len(missing)}) {ticker} ...", flush=True)
        ok, msg = fetch_one(
            dm, ticker, start=args.start, end=args.end, timeframe=args.timeframe,
        )
        if ok:
            summary.fetched.append(ticker)
            print(f"[FETCH_UNIVERSE]   ✓ {ticker}: {msg}", flush=True)
        else:
            summary.failed.append((ticker, msg))
            print(f"[FETCH_UNIVERSE]   ✗ {ticker}: {msg}", flush=True)
        if args.rate_limit_s > 0 and i < len(missing):
            time.sleep(args.rate_limit_s)

    print(summary.report())
    return 0 if not summary.failed else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
