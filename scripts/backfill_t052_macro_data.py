"""T-2026-05-12-052 macro/ETF data backfill.

Populates the data needed for the 4-signal regime ensemble features
that ship with T-052 but degrade gracefully when their data sources
are absent.

What this script fetches:

1. **ANFCI** (Chicago Fed Adjusted National Financial Conditions Index)
   from FRED → `data/macro/ANFCI.parquet`.
2. **EFA, AGG, VNQ** (Faber GTAA missing ETFs) from yfinance →
   `data/processed/{TICKER}_1d.csv`.

What this script does NOT fetch:

- VIX / VIX3M — already cached.
- BAMLH0A0HYM2 (HY OAS) — already cached.
- SPY / GLD — already cached.

Run BEFORE running a substrate-honest Discovery cycle that expects to
exercise the T-052 features end-to-end. Requires `FRED_API_KEY` in
`.env` (already set up per the project's macro pipeline) and
`yfinance` (already in requirements).

The T-052 features themselves remain functional without this backfill
— they return None and log a one-time WARNING. This script is a
convenience runner for the data-population step.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def fetch_anfci() -> None:
    from engines.data_manager.macro_data import (
        MACRO_SERIES, MacroSeries, fetch_series,
    )
    # Patch the curated registry in-process if ANFCI isn't there.
    if "ANFCI" not in MACRO_SERIES:
        MACRO_SERIES["ANFCI"] = MacroSeries(
            "ANFCI",
            "Chicago Fed Adjusted National Financial Conditions Index",
            "liquidity", "weekly",
            "Conditions z-score; <0 = looser-than-average, >0 = tighter. "
            "T-052 ensemble. CAVEAT: FRED current-vintage bias; ALFRED "
            "migration is T-047 candidate.",
        )
    print("[BACKFILL] Fetching ANFCI from FRED ...")
    fetch_series("ANFCI")
    print(f"[BACKFILL] ANFCI cached → {REPO / 'data' / 'macro' / 'ANFCI.parquet'}")


def fetch_etf(ticker: str) -> None:
    import yfinance as yf
    import pandas as pd

    out = REPO / "data" / "processed" / f"{ticker}_1d.csv"
    if out.exists():
        print(f"[BACKFILL] {ticker} already exists → {out}")
        return
    print(f"[BACKFILL] Fetching {ticker} from yfinance (2000-01-01 onward) ...")
    df = yf.download(ticker, start="2000-01-01", progress=False, auto_adjust=False)
    if df.empty:
        print(f"[BACKFILL] {ticker}: empty yfinance response")
        return
    # Normalize columns to the project's OHLCV cache shape.
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    # Expected columns: Date, Open, High, Low, Close, Adj Close, Volume.
    keep = [c for c in ("Date", "Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df[keep].to_csv(out, index=False)
    print(f"[BACKFILL] {ticker} → {out} ({len(df)} rows)")


if __name__ == "__main__":
    print("=" * 60)
    print("T-2026-05-12-052 macro/ETF backfill")
    print("=" * 60)
    try:
        fetch_anfci()
    except Exception as exc:
        print(f"[BACKFILL] ANFCI fetch failed: {type(exc).__name__}: {exc}")
    for etf in ("EFA", "AGG", "VNQ"):
        try:
            fetch_etf(etf)
        except Exception as exc:
            print(f"[BACKFILL] {etf} fetch failed: {type(exc).__name__}: {exc}")
    print("[BACKFILL] Done. Re-run a Discovery smoke cycle to exercise the T-052 features end-to-end.")
