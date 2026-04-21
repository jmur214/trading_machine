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
import yfinance as yf


class DataManager:
    def __init__(self, cache_dir: str = "data/processed", api_key=None, secret_key=None, base_url=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "parquet").mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        self.base_url = base_url or os.getenv("ALPACA_API_BASE_URL", "https://paper-api.alpaca.markets")
        self._lock = threading.Lock()

    # --------- helpers ---------
    def _fetch_yfinance(self, ticker: str, start: str, end: str, timeframe: str = "1d") -> pd.DataFrame:
        """
        Fallback fetcher using yfinance.
        """
        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
            print(f"[DATA_MANAGER][INFO] Falling back to yfinance for {ticker}...")
        
        try:
            # yfinance expects YYYY-MM-DD
            start_date = pd.to_datetime(start).strftime("%Y-%m-%d")
            end_date = pd.to_datetime(end).strftime("%Y-%m-%d")
            
            # Map timeframe
            interval = "1d"
            if timeframe == "1m": interval = "1m"
            elif timeframe == "1H": interval = "1h"
            
            df = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False, auto_adjust=True)
            
            if df.empty:
                return pd.DataFrame()
                
            # Flatten MultiIndex if present (common in new yf versions)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Map columns
            rename_map = {
                "Open": "Open", "High": "High", "Low": "Low", 
                "Close": "Close", "Volume": "Volume"
            }
            # Only keep columns we need
            df = df[[c for c in rename_map.keys() if c in df.columns]]
            df = self._normalize_df(df)
            return df
            
        except Exception as e:
            print(f"[DATA_MANAGER][ERROR] yfinance failed for {ticker}: {e}")
            return pd.DataFrame()

    def _fundamentals_cache_path(self, ticker: str) -> Path:
        return self.cache_dir / "parquet" / f"{ticker}_fundamentals.parquet"

    def prefetch_fundamentals(self, tickers, force=False, max_age_days=7):
        """Batch-fetch and cache fundamentals for all tickers. Call during data loading.
        Re-fetches if cache is older than max_age_days (default 7 for quarterly data)."""
        import time as _time
        for t in tickers:
            if t.startswith("SYNTH-") or t in ("SPY", "QQQ", "IWM", "TLT", "GLD"):
                continue
            cache_path = self._fundamentals_cache_path(t)
            if cache_path.exists() and not force:
                age_days = (_time.time() - cache_path.stat().st_mtime) / 86400
                if age_days < max_age_days:
                    continue
            try:
                df = self.fetch_historical_fundamentals(t)
                # fetch_historical_fundamentals already caches to parquet internally
            except Exception as e:
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][WARN] Failed to prefetch fundamentals for {t}: {e}")

    def fetch_historical_fundamentals(self, ticker: str) -> pd.DataFrame:
        """
        Reconstructs DEEP historical fundamental time-series.
        Fetches Income, Balance Sheet, and Cash Flow.
        Returns DataFrame with:
          - Valuation: PE_Ratio, PS_Ratio, PB_Ratio, PFCF_Ratio (Price to Free Cash Flow)
          - Health: Debt_to_Equity, Current_Ratio
          - Growth: Revenue_Growth (YoY), EPS_Growth (YoY)
        Indexed by Date (Daily, forward filled from reporting date + 45 days lag).
        Results are cached to parquet for subsequent runs.
        """
        # Check parquet cache first (persists across runs)
        cache_path = self._fundamentals_cache_path(ticker)
        if cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                if not df.empty:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Loaded cached fundamentals for {ticker} ({len(df)} rows)")
                    return df
            except Exception:
                pass  # fall through to fetch

        if ticker.startswith("SYNTH-"):
            from engines.engine_d_discovery.synthetic_market import SyntheticMarketGenerator
            try:
                seed = int(ticker.split("-")[1])
            except: seed = 42
            gen = SyntheticMarketGenerator(seed=seed)
            # We need the price history to generate consistent fundamentals
            # Assuming standard 2 year history needed
            price_df = gen.generate_price_history(days=730) 
            fund_df = gen.generate_fundamentals(price_df)
            # Join? generate_fundamentals already returns joined-like structure but index is date
            # We need to ensure it matches the return format.
            # generate_fundamentals returns daily sampled df with PE, EPS, etc. Perfect.
            return fund_df
        else:
            # Check for Static CSV (Reliable Backtesting Path)
            static_path = self.cache_dir.parent / "fundamentals_static.csv"
            if static_path.exists():
                try:
                    # Logic to read static file
                    # Expected format: Ticker,Date,PE_Ratio,Market_Cap,...
                    # Efficiently we might want to split this by ticker on load, but for now just filter.
                    # Optimization: load once per DM instance?
                    if not hasattr(self, "_static_fundamentals_cache"):
                        if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                            print(f"[DATA_MANAGER] Loading static fundamentals from {static_path}")
                        df_stat = pd.read_csv(static_path)
                        df_stat["Date"] = pd.to_datetime(df_stat["Date"])
                        df_stat = df_stat.set_index("Date").sort_index()
                        self._static_fundamentals_cache = df_stat

                    df_this = self._static_fundamentals_cache[self._static_fundamentals_cache["Ticker"] == ticker]
                    if not df_this.empty:
                         # Forward fill daily? The file might be sparse (quarterly).
                         # We invoke 'resample' to days and ffill.
                         # Note: the df_this index is DatetimeIndex.
                         start_dt = df_this.index[0]
                         end_dt = pd.Timestamp.now() # or max date in file
                         daily_idx = pd.date_range(start=start_dt, end=end_dt, freq='D')
                         df_daily = df_this.reindex(daily_idx).ffill()
                         
                         # Ensure required columns exist with defaults if missing
                         for col in ["PE_Ratio", "Market_Cap", "EPS_TTM"]:
                             if col not in df_daily.columns:
                                 df_daily[col] = np.nan
                                 
                         return df_daily
                except Exception as e:
                    print(f"[DATA_MANAGER][WARN] Failed to load static fundamentals for {ticker}: {e}")

            # Standard YFinance Path (Live/Current only)
            pass
            
        try:
            print(f"DEBUG: Deep fetch for {ticker}...")
            t = yf.Ticker(ticker)
            
            # --- 1. Fetch Raw Quarterly Tables ---
            q_inc = t.quarterly_income_stmt.T.sort_index()
            q_bal = t.quarterly_balance_sheet.T.sort_index()
            q_flow = t.quarterly_cashflow.T.sort_index()
            
            if q_inc.empty: # Income stmt is minimum requirement
                return pd.DataFrame()

            # --- 2. Extract & Normalize Series ---
            def get_col(df, keywords):
                # Helper to find columns like "Total Revenue" or "Revenue"
                matches = [c for c in df.columns if any(k in c for k in keywords)]
                # Prefer exact match if exists, else first fuzzy
                return matches[0] if matches else None

            # Income Metrics
            col_rev = get_col(q_inc, ["Total Revenue", "Operating Revenue"])
            col_ni = get_col(q_inc, ["Net Income Common Stockholders", "Net Income"])
            col_shares = get_col(q_inc, ["Basic Average Shares", "Ordinary Shares Number"])
            
            # Balance Metrics
            col_equity = get_col(q_bal, ["Stockholders Equity", "Total Equity"])
            col_debt = get_col(q_bal, ["Total Debt"])
            col_cash = get_col(q_bal, ["Cash And Cash Equivalents"])
            col_assets = get_col(q_bal, ["Total Assets"])
            col_liab = get_col(q_bal, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
            
            # Cash Flow Metrics
            col_ocf = get_col(q_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
            col_capex = get_col(q_flow, ["Capital Expenditure", "Machinery"]) # Capex is often negative

            # --- 3. Build Quarterly DataFrame ---
            # Merge all on index (Date)
            merged = pd.DataFrame(index=q_inc.index)
            
            # Fill Income (Flows -> Rolling TTM)
            if col_rev: merged["Revenue"] = q_inc[col_rev]
            if col_ni: merged["Net_Income"] = q_inc[col_ni]
            if col_shares: merged["Shares"] = q_inc[col_shares]
            
            # Fill Balance (Snapshots -> As Is)
            if not q_bal.empty:
                # Align indices (Balance sheet dates might strictly match or be close)
                # We simply reindex/join.
                # Actually, simpler to just reading directly if indices match.
                # yfinance usually aligns them. Let's use join.
                tmp_bal = pd.DataFrame(index=q_bal.index)
                if col_equity: tmp_bal["Equity"] = q_bal[col_equity]
                if col_debt: tmp_bal["Debt"] = q_bal[col_debt]
                if col_assets: tmp_bal["Assets"] = q_bal[col_assets]
                if col_liab: tmp_bal["Liabilities"] = q_bal[col_liab]
                merged = merged.join(tmp_bal, how='outer')
                
            # Fill Cash Flow (Flows -> Rolling TTM)
            if not q_flow.empty:
                tmp_flow = pd.DataFrame(index=q_flow.index)
                if col_ocf: tmp_flow["OCF"] = q_flow[col_ocf]
                if col_capex: tmp_flow["Capex"] = q_flow[col_capex]
                merged = merged.join(tmp_flow, how='outer')
            
            merged = merged.sort_index().ffill() # Fill gaps if dates slightly mismatched
            
            # --- 4. Compute Derived TTM Metrics (Rolling 4Q) ---
            # Flows need summing
            for c in ["Revenue", "Net_Income", "OCF", "Capex"]:
                if c in merged.columns:
                    merged[f"{c}_TTM"] = merged[c].rolling(window=4, min_periods=4).sum()
            
            # Per Share Metrics
            if "Shares" in merged.columns and "Net_Income_TTM" in merged.columns:
                merged["EPS_TTM"] = merged["Net_Income_TTM"] / merged["Shares"]
            if "Shares" in merged.columns and "Revenue_TTM" in merged.columns:
                merged["Sales_Per_Share"] = merged["Revenue_TTM"] / merged["Shares"]
            if "Shares" in merged.columns and "Equity" in merged.columns:
                merged["Book_Value_Per_Share"] = merged["Equity"] / merged["Shares"]
                
             # Free Cash Flow = OCF + Capex (Capex is usually negative in reports)
             # If Capex is positive, subtract it. yfinance usually negative.
             # We'll assume additive if negative.
            if "OCF_TTM" in merged.columns and "Capex_TTM" in merged.columns:
                # Check sign of capex
                # normalized FCF
                merged["FCF_TTM"] = merged["OCF_TTM"] + merged["Capex_TTM"] 
            
            # --- 5. Resample to Daily (Lagged) ---
            merged.index = merged.index + pd.Timedelta(days=45)
            start_date = merged.index[0]
            end_date = pd.Timestamp.now()
            daily_idx = pd.date_range(start=start_date, end=end_date, freq='D')
            
            daily = merged.reindex(daily_idx).ffill()
            
            # --- 6. Join Price & Compute Ratios ---
            price_hist = t.history(start=start_date, end=end_date)
            if price_hist.empty:
                return daily
            
            if price_hist.index.tz is not None:
                price_hist.index = price_hist.index.tz_localize(None)
                
            final = daily.join(price_hist["Close"], how="inner")
            
            # Valuation Ratios
            if "EPS_TTM" in final.columns:
                final["PE_Ratio"] = final["Close"] / final["EPS_TTM"]
            
            if "Sales_Per_Share" in final.columns:
                final["PS_Ratio"] = final["Close"] / final["Sales_Per_Share"]
                
            if "Book_Value_Per_Share" in final.columns:
                final["PB_Ratio"] = final["Close"] / final["Book_Value_Per_Share"]
                
            if "FCF_TTM" in final.columns and "Shares" in final.columns:
                final["FCF_Per_Share"] = final["FCF_TTM"] / final["Shares"]
                final["PFCF_Ratio"] = final["Close"] / final["FCF_Per_Share"]
            
            # Health Ratios (Price independent)
            if "Debt" in final.columns and "Equity" in final.columns:
                final["Debt_to_Equity"] = final["Debt"] / final["Equity"]
                
            if "Market_Cap" not in final.columns and "Shares" in final.columns:
                final["Market_Cap"] = final["Close"] * final["Shares"]

            # Select final columns
            cols = [c for c in ["PE_Ratio", "PS_Ratio", "PB_Ratio", "PFCF_Ratio", 
                                "Debt_to_Equity", "Market_Cap", "EPS_TTM"] if c in final.columns]
                                
            final_df = final[cols].dropna(how='all') # Keep if at least one data point exists

            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][INFO] Deep fundamentals for {ticker}: {len(final_df)} days. Vars: {cols}")

            # Cache to parquet for subsequent runs
            if not final_df.empty:
                try:
                    cache_path = self._fundamentals_cache_path(ticker)
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    final_df.to_parquet(cache_path, index=True)
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][INFO] Cached fundamentals for {ticker} to {cache_path}")
                except Exception as ce:
                    if is_debug_enabled("DATA_MANAGER"):
                        print(f"[DATA_MANAGER][WARN] Failed to cache fundamentals for {ticker}: {ce}")

            return final_df

        except Exception as e:
            print(f"DEBUG: Exception in deep fetch: {e}", flush=True)
            return pd.DataFrame()

    def fetch_fundamentals(self, ticker: str) -> dict:
        """
        Fetch fundamental data (P/E, EPS, etc.) for a ticker.
        Uses yfinance as primary source since Alpaca data API is mostly price.
        """
        try:
            t = yf.Ticker(ticker)
            info = t.info # Triggers API call
            
            # Extract key metrics
            fundamentals = {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "eps_trailing": info.get("trailingEps"),
                "eps_forward": info.get("forwardEps"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta")
            }
            
            # Clean None values
            fundamentals = {k: v for k, v in fundamentals.items() if v is not None}
            
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][INFO] Fetched fundamentals for {ticker}: P/E={fundamentals.get('pe_ratio')}")
                
            return fundamentals
            
        except Exception as e:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print(f"[DATA_MANAGER][WARN] Failed to fetch fundamentals for {ticker}: {e}")
            return {}

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
    def _fetch_synthetic(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """
        Generates synthetic data on the fly.
        """
        from engines.engine_d_discovery.synthetic_market import SyntheticMarketGenerator
        
        # Parse days approx
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        days = (end_dt - start_dt).days
        if days < 10: days = 365 # Default if query is weird
        
        # Use ticker name as seed for reproducibility
        # SYNTH-01 -> seed=1
        try:
            seed = int(ticker.split("-")[1])
        except:
            seed = 42
            
        gen = SyntheticMarketGenerator(seed=seed)
        df = gen.generate_price_history(days=days, start_date=start) # Pass requested start date
        return df

    def ensure_data(self, tickers, start, end, timeframe="1d"):
        offline = not self.api_key or not self.secret_key
        if offline:
            if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                print("[DATA_MANAGER][WARN] Missing Alpaca API credentials. Alpaca fetch disabled.")

        def fetch_from_alpaca(ticker, timeframe, start, end):
            # Inner helper, only called if online
            if timeframe == "1m":
                alpaca_timeframe = TimeFrame.Minute
            elif timeframe == "1H":
                alpaca_timeframe = TimeFrame.Hour
            else:
                alpaca_timeframe = TimeFrame.Day

            start_dt = pd.to_datetime(start).tz_localize("UTC")
            end_dt = pd.to_datetime(end).tz_localize("UTC")
            
            client = StockHistoricalDataClient(self.api_key, self.secret_key, url_override=self.base_url)
            
            max_retries = 3
            delay = 1
            for attempt in range(max_retries):
                try:
                    req = StockBarsRequest(
                        symbol_or_symbols=ticker,
                        timeframe=alpaca_timeframe,
                        start=start_dt,
                        end=end_dt,
                        adjustment="split", # CRITICAL FIX: Handle splits to preserve price continuity
                        feed="iex",
                        limit=10000,
                    )
                    bars = client.get_stock_bars(req)
                    if hasattr(bars, 'df'):
                        df = bars.df
                    else:
                        df = pd.DataFrame()
                    
                    if df.empty:
                        return pd.DataFrame()
                        
                    if isinstance(df.index, pd.MultiIndex):
                        df.reset_index(inplace=True)
                        if "timestamp" in df.columns:
                            df = df.set_index("timestamp")
                    
                    df.index = pd.to_datetime(df.index, errors="coerce").tz_localize(None)
                    df = df.sort_index()
                    
                    df.rename(columns={
                        "open": "Open", "high": "High", "low": "Low", 
                        "close": "Close", "volume": "Volume"
                    }, inplace=True)
                    
                    df = self._normalize_df(df)
                    return df

                except Exception as e:
                    if is_debug_enabled("DATA_MANAGER"):
                        print(f"[DATA_MANAGER][WARN] Alpaca fetch failed for {ticker}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        delay *= 2
            return pd.DataFrame()

        if offline and is_debug_enabled("DATA_MANAGER"):
            print("[DATA_MANAGER] Running in OFFLINE mode (cache only).")
            
        out = {}
        for t in tickers:
            if t.startswith("SYNTH-"):
                df = self._fetch_synthetic(t, start, end)
                out[t] = df
                if is_debug_enabled("DATA_MANAGER"):
                    print(f"[DATA_MANAGER] Generated synthetic data for {t} ({len(df)} rows)")
                continue

            cached = self.load_cached(t, timeframe)
            if cached is not None and not cached.empty and len(cached) > 10:
                out[t] = cached
                continue
            
            df = None
            if not offline:
                try:
                    df = fetch_from_alpaca(t, timeframe, start, end)
                except Exception:
                    df = None

            # Fallback to yfinance if Alpaca failed or offline
            if (df is None or df.empty):
                try:
                    df = self._fetch_yfinance(t, start, end, timeframe)
                except Exception as e:
                    if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                        print(f"[DATA_MANAGER][ERROR] yfinance failed for {t}: {e}")
                    df = pd.DataFrame()

            if df is not None and not df.empty:
                self.save_cache(t, timeframe, df)
                if is_debug_enabled("DATA_MANAGER") or is_info_enabled():
                    print(f"[DATA_MANAGER][INFO] Downloaded data for {t} ({len(df)} rows)")
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