

import os
import argparse
import pandas as pd
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="Fetch and cache historical OHLCV data from Alpaca.")
    parser.add_argument("--tickers", nargs="+", required=True, help="List of ticker symbols (e.g. AAPL MSFT SPY)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--timeframe", default="1d", help="Timeframe (1d, 1h, 15m, etc.)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files if present")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not api_secret:
        print("[FETCH_DATA][ERROR] Missing Alpaca API credentials in .env")
        return

    client = StockHistoricalDataClient(api_key, api_secret)
    out_dir = "data/raw"
    os.makedirs(out_dir, exist_ok=True)

    tf_map = {
        "1d": TimeFrame.Day,
        "1h": TimeFrame.Hour,
        "15m": TimeFrame(15, "Minute"),
        "5m": TimeFrame(5, "Minute"),
    }

    timeframe = tf_map.get(args.timeframe, TimeFrame.Day)

    for ticker in args.tickers:
        out_path = os.path.join(out_dir, f"{ticker}_{args.timeframe}.csv")

        if os.path.exists(out_path) and not args.overwrite:
            print(f"[FETCH_DATA][SKIP] {out_path} already exists. Use --overwrite to refresh.")
            continue

        print(f"[FETCH_DATA][INFO] Fetching {ticker} {args.timeframe} bars from {args.start} to {args.end}...")

        try:
            request = StockBarsRequest(
                symbol_or_symbols=[ticker],
                start=datetime.fromisoformat(args.start),
                end=datetime.fromisoformat(args.end),
                timeframe=timeframe,
            )
            bars = client.get_stock_bars(request)
            df = bars.df.reset_index()
            df = df[df["symbol"] == ticker].drop(columns=["symbol"], errors="ignore")
            df.rename(columns={"timestamp": "timestamp", "open": "open", "high": "high",
                               "low": "low", "close": "close", "volume": "volume"}, inplace=True)
            df.to_csv(out_path, index=False)
            print(f"[FETCH_DATA][SUCCESS] Saved {len(df)} rows → {out_path}")
        except Exception as e:
            print(f"[FETCH_DATA][ERROR] Failed to fetch {ticker}: {e}")

if __name__ == "__main__":
    main()