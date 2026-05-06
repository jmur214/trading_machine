"""
fetch_vix_term_structure — cache CBOE VIX-family closes to data/macro/.

Pulls daily Close for ^VIX9D, ^VIX, ^VIX3M from yfinance and persists each
to `data/macro/<TICKER>.parquet` matching the schema of the existing FRED
parquet files (index name `date`, single `value` float64 column).

This is the data-layer companion to the HMM panel rebuild slice 1
(VIX term structure). Caching to data/macro/ lets `macro_features.py`
consume these series the same way it consumes FRED series, so the HMM
input panel can be extended without forking the data path.

Usage:
    python scripts/fetch_vix_term_structure.py
    python scripts/fetch_vix_term_structure.py --start 2020-01-01 --end 2025-05-01

Tickers cached:
    ^VIX9D  -> data/macro/VIX9D.parquet     (9-day implied vol)
    ^VIX    -> data/macro/VIX.parquet       (30-day implied vol; FRED has VIXCLS
                                              but we cache yfinance copy too so
                                              term-structure features stay on a
                                              single calendar)
    ^VIX3M  -> data/macro/VIX3M.parquet     (3-month implied vol)

Notes:
- yfinance tickers are written without the ^ in the parquet filename to
  match how the FRED loader expects file paths (`<series_id>.parquet`).
- We cache `Close` (not Adj Close) — the indices are not equity prices,
  there's no dividend/split adjustment to apply.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MACRO_DIR = ROOT / "data" / "macro"
META_PATH = MACRO_DIR / "_meta.json"

# yfinance ticker  ->  on-disk parquet base name
TICKERS: Dict[str, str] = {
    "^VIX9D": "VIX9D",
    "^VIX": "VIX",
    "^VIX3M": "VIX3M",
    "^VIX6M": "VIX6M",
}


def _normalize_close(df: pd.DataFrame) -> pd.Series:
    """Pull a single Close series out of a yfinance frame.

    yfinance occasionally returns multi-index columns; collapse to a flat
    Close series with a tz-naive DatetimeIndex named `date`.
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        raise ValueError(f"yfinance frame missing Close column; got {list(df.columns)}")
    s = df["Close"].astype(float).dropna().sort_index()
    # tz-naive
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index.name = "date"
    s.name = "value"
    return s


def fetch_one(ticker: str, start: str, end: str) -> pd.Series:
    import yfinance as yf

    df = yf.download(
        ticker, start=start, end=end, interval="1d",
        progress=False, auto_adjust=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned empty frame for {ticker}")
    return _normalize_close(df)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01",
                    help="Earliest date to fetch (yfinance start). Default 2020-01-01 "
                         "to give the HMM 2021 train window plenty of warm-up.")
    ap.add_argument("--end", default="2025-05-01",
                    help="Last date to fetch (exclusive in yfinance API).")
    args = ap.parse_args()

    MACRO_DIR.mkdir(parents=True, exist_ok=True)

    # Load meta if present so we extend, not overwrite.
    meta: Dict = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
        except Exception:
            meta = {}

    summary = []
    for yf_ticker, base in TICKERS.items():
        out_path = MACRO_DIR / f"{base}.parquet"
        print(f"[fetch] {yf_ticker} -> {out_path}")
        s = fetch_one(yf_ticker, args.start, args.end)
        df = s.to_frame()
        df.to_parquet(out_path)
        summary.append((yf_ticker, base, len(df), df.index[0], df.index[-1]))
        meta[base] = {
            "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(len(df)),
            "source": "yfinance",
            "yf_ticker": yf_ticker,
            "field": "Close",
        }

    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True, default=str))

    print("\n=== summary ===")
    for yf_ticker, base, n, first, last in summary:
        print(f"  {yf_ticker:8s} -> {base:8s}  rows={n:5d}  {first.date()} -> {last.date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
