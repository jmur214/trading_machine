# engines/data_manager/data_manager.py
import os
import shutil
from pathlib import Path
import pandas as pd
import asyncio
import concurrent.futures
import threading
import time
import warnings
from dotenv import load_dotenv

from debug_config import is_debug_enabled

def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("DATA_MANAGER_INFO", False)

# --- Force load .env globally from project root ---
from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parents[2]
env_path = ROOT_DIR / ".env"

if env_path.exists():
    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
        print(f"[DATA_MANAGER][DEBUG] Loaded environment variables from {env_path}")
    load_dotenv(dotenv_path=env_path, override=True)
else:
    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
        print(f"[DATA_MANAGER][WARN] .env not found at {env_path}")
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class DataManager:
    def __init__(self, cache_dir: str = "data/processed", api_key=None, secret_key=None, base_url=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "parquet").mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        self.base_url = base_url or os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets")
        self._lock = threading.Lock()

    # --------- helpers ---------
    @staticmethod
    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure datetime index (tz-naive), numeric OHLCV,
        fix scaling, and compute ATR with proper warmup.
        """
        if df.empty:
            return df

        # --- Ensure datetime index ---
        # If df already has a DatetimeIndex, use it directly
        if isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors="coerce")
            try:
                df.index = df.index.tz_localize(None)
            except Exception:
                pass
            df = df.sort_index()
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print("[DATA_MANAGER][INFO] Using existing DatetimeIndex from Alpaca.")
        else:
            # Detect and set timestamp/date/time column as index
            timestamp_cols = [col for col in df.columns if col.strip().lower() in ["timestamp", "date", "time"]]
            if timestamp_cols:
                ts_col = timestamp_cols[0]
                df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
                df = df.dropna(subset=[ts_col])
                df = df.set_index(ts_col)
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Detected timestamp column '{ts_col}' and set as index.")
            else:
                # Fallback: generate business day date range starting from 2000-01-01
                df = df.copy()
                df.index = pd.date_range(start="2000-01-01", periods=len(df), freq='B')
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print("[DATA_MANAGER][INFO] No timestamp column found; generated business day date range as index from 2000-01-01.")

            df.index = pd.to_datetime(df.index, errors="coerce")
            try:
                df.index = df.index.tz_localize(None)
            except Exception:
                pass
            df = df.sort_index()
        df = df[~df.index.duplicated(keep='first')]

        # --- Standardize column names ---
        rename_map = {}
        for col in df.columns:
            c = col.strip().lower()
            if c in ["open", "opening price"]:
                rename_map[col] = "Open"
            elif c in ["high", "high price"]:
                rename_map[col] = "High"
            elif c in ["low", "low price"]:
                rename_map[col] = "Low"
            elif c in ["close", "closing price"]:
                rename_map[col] = "Close"
            elif c in ["adj close", "adjusted close"]:
                rename_map[col] = "Adj Close"
            elif c in ["volume", "vol"]:
                rename_map[col] = "Volume"
        df = df.rename(columns=rename_map)

        # --- Fill missing OHLCV columns ---
        if "Close" not in df.columns:
            if "Adj Close" in df.columns:
                df["Close"] = df["Adj Close"]
            elif len(df.columns) > 0:
                df["Close"] = pd.to_numeric(df.iloc[:, -1], errors="coerce")

        for col in ["Open", "High", "Low"]:
            if col not in df.columns:
                df[col] = df["Close"]

        if "Volume" not in df.columns:
            df["Volume"] = 0

        # --- Coerce to numeric ---
        for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # --- Drop invalid rows ---
        df = df[df["Close"].notna()]

        # --- AUTO SCALE FIX ---
        median_price = df["Close"].median()
        scale = 1.0
        while median_price > 1000:
            median_price /= 10
            scale *= 10

        if scale != 1.0:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][INFO] Auto-scaling prices: ÷{scale}")
            for c in ["Open", "High", "Low", "Close"]:
                df[c] = df[c] / scale

        # --- Data sanity cleanup ---
        if "Close" in df.columns:
            median_close = df["Close"].median(skipna=True)
            df = df[(df["Close"] > 0) & (df["Close"] < median_close * 3)]
            df["Close"] = df["Close"].clip(lower=0.01, upper=median_close * 3)

        # Final validation
        final_median = df["Close"].median()
        if final_median < 0.1 or final_median > 10000:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Abnormal price scale detected (median={final_median:.2f}) — check data source.")

        # --- Ensure float dtype ---
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c in df.columns:
                df[c] = df[c].astype(float)

        # --- Compute ATR (Average True Range) with proper warmup ---
        try:
            high_low = (df["High"] - df["Low"]).abs()
            high_close = (df["High"] - df["Close"].shift()).abs()
            low_close = (df["Low"] - df["Close"].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            # Require a full 14 bars before ATR is considered valid (avoid micro ATR)
            df["ATR"] = tr.rolling(window=14, min_periods=14).mean()
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Failed to compute ATR: {e}")

        # Preview
        preview_cols = ["Close"]
        if "ATR" in df.columns:
            preview_cols.append("ATR")
        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
            print(f"[DATA_MANAGER][INFO] Preview after normalization:\n{df[preview_cols].head()}\n")
               
                # --- Add PrevClose column (for execution sanity checks) ---
        try:
            if "Close" in df.columns and "PrevClose" not in df.columns:
                df["PrevClose"] = df["Close"].shift(1)
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Could not add PrevClose: {e}")
            
        return df

    def cache_path(self, ticker: str, timeframe: str) -> Path:
        return self.cache_dir / f"{ticker}_{timeframe}.csv"

    def parquet_cache_path(self, ticker: str, timeframe: str) -> Path:
        return self.cache_dir / "parquet" / f"{ticker}_{timeframe}.parquet"

    def load_cached(self, ticker: str, timeframe: str) -> pd.DataFrame | None:
        # Try Parquet first, then fallback to CSV
        pq_path = self.parquet_cache_path(ticker, timeframe)
        if pq_path.exists():
            try:
                df = pd.read_parquet(pq_path)
                df = self._normalize_df(df)
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Loaded Parquet cache for {ticker} ({timeframe})")
                return df
            except Exception as e:
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][WARN] Failed to load Parquet cache for {ticker}: {e}. Attempting CSV fallback.")
                # Optionally, remove corrupted file
                try:
                    pq_path.unlink()
                except Exception:
                    pass
        # CSV fallback
        path = self.cache_path(ticker, timeframe)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            df = self._normalize_df(df)
            return df
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Failed to load CSV cache for {ticker}: {e}")
            try:
                path.unlink()
            except Exception:
                pass
            return None

    def save_cache(self, ticker: str, timeframe: str, df: pd.DataFrame) -> None:
        # Save both Parquet and CSV for compatibility (Parquet preferred)
        pq_path = self.parquet_cache_path(ticker, timeframe)
        pq_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Chunked writing if DataFrame is large
            mem_bytes = df.memory_usage(deep=True).sum()
            if mem_bytes > 50 * 1024 * 1024:  # >50MB
                # Parquet chunked writing: no direct chunk, so use to_parquet in one go
                df.to_parquet(pq_path, index=True)
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Saved Parquet cache for {ticker} (>50MB, {mem_bytes/1e6:.1f}MB)")
            else:
                df.to_parquet(pq_path, index=True)
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Failed to save Parquet cache for {ticker}: {e}")
        # Also save CSV for legacy support
        path = self.cache_path(ticker, timeframe)
        try:
            if mem_bytes > 50 * 1024 * 1024:
                # Chunked CSV writing
                chunk_size = 500_000
                with open(path, "w") as f:
                    for i, chunk in enumerate(
                        (df.iloc[i:i+chunk_size] for i in range(0, len(df), chunk_size))
                    ):
                        header = (i == 0)
                        chunk.to_csv(f, date_format="%Y-%m-%d", header=header)
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Saved CSV cache for {ticker} in chunks.")
            else:
                df.to_csv(path, date_format="%Y-%m-%d")
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Failed to save CSV cache for {ticker}: {e}")
        # Explicitly delete reference to DataFrame to aid memory reclaim
        del df

    def load_or_fetch(self, ticker: str, timeframe: str, start=None, end=None, fetch_func=None) -> pd.DataFrame:
        """
        Try to load from Parquet cache, then CSV, then use fetch_func if provided.
        """
        df = self.load_cached(ticker, timeframe)
        if df is not None and not df.empty:
            return df
        if fetch_func is not None and start is not None and end is not None:
            df = fetch_func(ticker, timeframe, start, end)
            if df is not None and not df.empty:
                self.save_cache(ticker, timeframe, df)
                return df
        return pd.DataFrame()

    # --------- public API ---------
    def ensure_data(self, tickers, start, end, timeframe="1d"):
        if not self.api_key or not self.secret_key:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print("[DATA_MANAGER][WARN] Missing Alpaca API credentials. Operating in offline mode using cache only.")
            out = {}
            for t in tickers:
                cached = self.load_cached(t, timeframe)
                if cached is not None and not cached.empty:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Loaded cached data for {t}: {cached.index.min()} to {cached.index.max()} ({len(cached)} rows)")
                    out[t] = cached
                else:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][ERROR] No cache available for {t} and no API credentials to fetch data.")
                    out[t] = pd.DataFrame()
            return out

        key_display = (self.api_key[:6] + "***") if self.api_key else "MISSING"
        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
            print(f"[DATA_MANAGER][DEBUG] Using Alpaca credentials -> Key: {key_display}, Secret: {'SET' if self.secret_key else 'MISSING'}")
        try:
            client = StockHistoricalDataClient(api_key=self.api_key, secret_key=self.secret_key)
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print("[DATA_MANAGER][DEBUG] Alpaca client initialized successfully.")
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][ERROR] Failed to initialize Alpaca client: {e}")
                print("[DATA_MANAGER][WARN] Falling back to cache-only mode.")
            out = {}
            for t in tickers:
                cached = self.load_cached(t, timeframe)
                if cached is not None and not cached.empty:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Loaded cached data for {t}: {cached.index.min()} to {cached.index.max()} ({len(cached)} rows)")
                    out[t] = cached
                else:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][ERROR] No cache available for {t}.")
                    out[t] = pd.DataFrame()
            return out

        def fetch_from_alpaca(ticker, timeframe, start, end):
            # Retry logic with exponential backoff
            max_retries = 5
            delay = 2
            for attempt in range(max_retries):
                try:
                    if timeframe == "1d":
                        alpaca_timeframe = TimeFrame.Day
                    elif timeframe == "1Min":
                        alpaca_timeframe = TimeFrame.Minute
                    elif timeframe == "1H":
                        alpaca_timeframe = TimeFrame.Hour
                    else:
                        alpaca_timeframe = TimeFrame.Day

                    start_dt = pd.to_datetime(start).tz_localize("UTC")
                    end_dt = pd.to_datetime(end).tz_localize("UTC")
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Requesting {ticker} from {start_dt} to {end_dt} ({timeframe})")

                    req = StockBarsRequest(
                        symbol_or_symbols=ticker,
                        timeframe=alpaca_timeframe,
                        start=start_dt,
                        end=end_dt,
                        adjustment="raw",
                        feed="iex",
                        limit=10000,
                    )
                    if is_debug_enabled("DATA_MANAGER"):
                        print(f"[DATA_MANAGER][DEBUG] Sending request to Alpaca for {ticker} with timeframe={timeframe} and limit=10000.")
                    bars = client.get_stock_bars(req)
                    if hasattr(bars, 'df'):
                        df = bars.df
                        if is_debug_enabled("DATA_MANAGER"):
                            print(f"[DATA_MANAGER][DEBUG] bars.df shape={df.shape}")
                            print(df.head(5))
                    else:
                        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                            print(f"[DATA_MANAGER][ERROR] No 'df' attribute found in response for {ticker}")
                        df = pd.DataFrame()
                    if df.empty:
                        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                            print(f"[DATA_MANAGER][WARN] Alpaca returned no data for {ticker}.")
                        return pd.DataFrame()
                    if isinstance(df.index, pd.MultiIndex):
                        df.reset_index(inplace=True)
                        if "timestamp" in df.columns:
                            df = df.set_index("timestamp")
                    df.index = pd.to_datetime(df.index, errors="coerce").tz_localize(None)
                    df = df.sort_index()
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Retrieved {len(df)} bars for {ticker} ({df.index.min()} → {df.index.max()})")
                    df.rename(columns={
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "volume": "Volume"
                    }, inplace=True)
                    df = self._normalize_df(df)
                    return df
                except Exception as e:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][WARN] Exception fetching data for {ticker} (attempt {attempt+1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        delay *= 2
                    else:
                        return pd.DataFrame()

        out = {}
        for t in tickers:
            cached = self.load_cached(t, timeframe)
            # --- Validate cache freshness and size ---
            if cached is not None and not cached.empty and len(cached) < 10:
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][WARN] Cached data for {t} is too small ({len(cached)} rows) — refetching from Alpaca.")
                cached = None
            if cached is not None and not cached.empty:
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Loaded cached data for {t}: {cached.index.min()} to {cached.index.max()} ({len(cached)} rows)")
                out[t] = cached
                continue
            df = fetch_from_alpaca(t, timeframe, start, end)
            if df is not None and not df.empty:
                self.save_cache(t, timeframe, df)
                if is_debug_enabled("DATA_MANAGER"):
                    print(f"[DATA_MANAGER][DEBUG] Completed processing {t}. Saved {len(df)} rows to cache.")
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Downloaded and cached data for {t}: {df.index.min()} to {df.index.max()} ({len(df)} rows)")
                out[t] = df
            else:
                out[t] = pd.DataFrame()
        return out

    async def async_prefetch(self, tickers, start, end, timeframe="1d"):
        """
        Asynchronously prefetch multiple tickers, using cache when available.
        """
        loop = asyncio.get_event_loop()
        results = {}
        def fetch_one(ticker):
            return ticker, self.load_or_fetch(
                ticker, timeframe, start=start, end=end,
                fetch_func=lambda t, tf, s, e: self.ensure_data([t], s, e, tf)[t]
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
            futures = [loop.run_in_executor(executor, fetch_one, t) for t in tickers]
            for f in await asyncio.gather(*futures):
                t, df = f
                results[t] = df
        return results