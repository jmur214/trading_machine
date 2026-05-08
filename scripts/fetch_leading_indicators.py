"""
fetch_leading_indicators — cache copper, gold, XLP, XLY closes to data/macro/.

E-rebuild phase-1 dispatch (2026-05-07): per-R2 audit, the existing macro
panel is dominated by coincident features. This script fetches yfinance
series for two candidate LEADING indicators:

  - Copper / Gold ratio (HG=F / GC=F) — copper is industrial-cycle
    sensitive; gold is monetary/risk-off; the ratio inverts at growth
    inflection points 6-12 months ahead of equity drawdowns.

  - Defensive-vs-cyclical relative strength (XLP / XLY) — when rotation
    INTO defensives leads cyclicals, the broader market typically follows.

Both pairs are stored as raw closes; the ratios are computed in
macro_features.py at panel-build time. Schema mirrors VIX term-structure
parquet files (index name 'date', single 'value' float64 column) so
_safe_load_fred can consume them transparently.

Usage:
    python scripts/fetch_leading_indicators.py
    python scripts/fetch_leading_indicators.py --start 2010-01-01 --end 2025-05-01

Tickers cached:
    HG=F  -> data/macro/HG_F.parquet     (Copper front-month futures)
    GC=F  -> data/macro/GC_F.parquet     (Gold front-month futures)
    XLP   -> data/macro/XLP.parquet      (Consumer Staples ETF)
    XLY   -> data/macro/XLY.parquet      (Consumer Discretionary ETF)
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

# yfinance ticker -> on-disk parquet base name. '=F' is replaced with '_F'
# so the path stays filename-safe.
TICKERS: Dict[str, str] = {
    "HG=F": "HG_F",
    "GC=F": "GC_F",
    "XLP": "XLP",
    "XLY": "XLY",
}


def _normalize_close(df: pd.DataFrame) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        raise ValueError(f"yfinance frame missing Close column; got {list(df.columns)}")
    s = df["Close"].astype(float).dropna().sort_index()
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
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-05-07")
    args = ap.parse_args()

    MACRO_DIR.mkdir(parents=True, exist_ok=True)

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
