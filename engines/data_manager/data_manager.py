# engines/data_manager/data_manager.py
import os
from pathlib import Path
import pandas as pd
import yfinance as yf


class DataManager:
    def __init__(self, cache_dir: str = "data/processed"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --------- helpers ---------
    @staticmethod
    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure datetime index (tz-naive), numeric OHLCV,
        fix scaling issues (prices in cents, thousands, etc.),
        and compute ATR (Average True Range) for downstream risk models.
        """
        if df.empty:
            return df

        # --- Ensure datetime index ---
        if not isinstance(df.index, pd.DatetimeIndex):
            for candidate in ["Timestamp", "Datetime", "Date"]:
                if candidate in df.columns:
                    df[candidate] = pd.to_datetime(df[candidate], errors="coerce")
                    df = df.set_index(candidate)
                    break
        df.index = pd.to_datetime(df.index, errors="coerce")
        try:
            df.index = df.index.tz_localize(None)
        except Exception:
            pass
        df = df.sort_index()

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
        while median_price > 1000:  # scale down until median < $1000
            median_price /= 10
            scale *= 10

        if scale != 1.0:
            print(f"[DATA_MANAGER] Auto-scaling prices: ÷{scale}")
            for c in ["Open", "High", "Low", "Close"]:
                df[c] = df[c] / scale

        # Final validation
        final_median = df["Close"].median()
        if final_median < 0.1 or final_median > 10000:
            print(f"[WARNING] Abnormal price scale detected (median={final_median:.2f}) — check data source.")

        # --- Ensure float dtype ---
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c in df.columns:
                df[c] = df[c].astype(float)

        # --- Compute ATR (Average True Range) ---
        try:
            high_low = df["High"] - df["Low"]
            high_close = (df["High"] - df["Close"].shift()).abs()
            low_close = (df["Low"] - df["Close"].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df["ATR"] = tr.rolling(window=14, min_periods=1).mean()
        except Exception as e:
            print(f"[DATA_MANAGER][WARN] Failed to compute ATR: {e}")

        # --- Print preview for sanity ---
        preview_cols = ["Close"]
        if "ATR" in df.columns:
            preview_cols.append("ATR")
        print(f"[DATA_MANAGER] Preview after normalization:\n{df[preview_cols].head()}\n")

        return df

    def cache_path(self, ticker: str, timeframe: str) -> Path:
        return self.cache_dir / f"{ticker}_{timeframe}.csv"

    def load_cached(self, ticker: str, timeframe: str) -> pd.DataFrame | None:
        path = self.cache_path(ticker, timeframe)
        if not path.exists():
            return None
        df = pd.read_csv(path)
        df = self._normalize_df(df)
        return df

    def save_cache(self, ticker: str, timeframe: str, df: pd.DataFrame) -> None:
        path = self.cache_path(ticker, timeframe)
        df.to_csv(path, date_format="%Y-%m-%d")

    # --------- public API ---------
    def ensure_data(self, tickers, start, end, timeframe="1d"):
        """
        Return dict[ticker] -> DataFrame with normalized OHLCV + ATR.
        """
        out = {}
        for t in tickers:
            cached = self.load_cached(t, timeframe)
            if cached is not None and not cached.empty:
                out[t] = cached
                continue

            # Download from yfinance
            df = yf.download(t, start=start, end=end, interval=timeframe, progress=False)

            # Flatten MultiIndex columns if needed (intraday data)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [" ".join([c for c in tup if c]).strip() for tup in df.columns]

            df = self._normalize_df(df)
            self.save_cache(t, timeframe, df)
            out[t] = df
        return out