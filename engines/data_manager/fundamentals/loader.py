
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging
import json

# Setup Logging
logger = logging.getLogger("FUNDAMENTALS")

class FundamentalLoader:
    """
    Tier 1 Fundamental Data Engine.
    
    Responsibility:
    ---------------
    1. Ingest Raw Fundamental Data (Quarterly Reports).
    2. Normalize to standard schema.
    3. Generate 'Point-in-Time' Daily Time Series.
       - Logic: For every trading day, what was the LAST KNOWN fundamental value?
       - Prevents Lookahead Bias: If Earnings released May 1, Day=Apr 30 sees OLD data.
    4. Compute Dynamic Ratios (e.g. Daily PE = Daily Price / Static TTM EPS).
    
    Storage Strategy:
    -----------------
    - Raw: CSV/Parquet in data/raw/fundamentals/
    - Processed: data/processed/fundamentals.parquet (MultiIndex: Date, Ticker)
    """
    
    def __init__(self, data_dir: str = "data"):
        self.root = Path(data_dir)
        self.raw_dir = self.root / "raw" / "fundamentals"
        self.processed_path = self.root / "processed" / "fundamentals.parquet"
        
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        
    def ingest_fmp_ratios(self, file_path: str):
        """
        Ingest 'Bulk Ratios' CSV from FMP (Financial Modeling Prep).
        Expected Columns: symbol, date, period, peRatio, ...
        """
        try:
            df = pd.read_csv(file_path)
            # Normalize
            df.rename(columns={
                "symbol": "ticker",
                "date": "report_date",
                "fillingDate": "publish_date" # FMP field for when it was public
            }, inplace=True)
            
            # If 'publish_date' missing, fallback to report_date + 45 days lag (Conservative)
            if "publish_date" not in df.columns:
                df["publish_date"] = pd.to_datetime(df["report_date"]) + timedelta(days=45)
            else:
                df["publish_date"] = pd.to_datetime(df["publish_date"])
                
            # Filter essential columns
            keep_cols = ["ticker", "publish_date", "peRatio", "priceToSalesRatio", "priceToBookRatio", "netIncomePerShare"]
            df = df[[c for c in keep_cols if c in df.columns]]
            
            self._save_raw(df, "fmp_ratios")
            
        except Exception as e:
            logger.error(f"Failed to ingest FMP: {e}")

    def generate_point_in_time(self, ticker: str, price_history: pd.DataFrame) -> pd.DataFrame:
        """
        Merges Price History with Fundamental History to create a Daily Fundamental Record.
        
        Logic:
        - Price Data = Daily frequency.
        - Fundamental Data = Sparse (Quarterly).
        - Action: Merge_AsOf (Backward search). 
          For each Price Date, find the most recent Fundamental 'publish_date'.
        """
        if price_history.empty:
            return pd.DataFrame()
            
        # Load Raw Fundamentals for this ticker
        # (In prod, we query the parquet store. Here we mock/scan).
        fund_df = self._load_raw_for_ticker(ticker)
        
        if fund_df.empty:
            return pd.DataFrame()
            
        # Sort both
        price_history = price_history.sort_index()
        fund_df = fund_df.sort_values("publish_date")
        
        # Merge AsOf
        # We need to preserve the price index.
        merged = pd.merge_asof(
            price_history,
            fund_df,
            left_index=True,
            right_on="publish_date",
            direction="backward" 
            # backward = search for latest date <= current date
            # This is critical for preventing lookahead.
        )
        
        # Set index back
        merged.index = price_history.index
        
        # Compute Dynamic PE
        # PE = Close / EPS (netIncomePerShare)
        # Handle division by zero/NaN
        if "netIncomePerShare" in merged.columns:
            merged["pe_dynamic"] = merged["Close"] / merged["netIncomePerShare"]
            # Clean extremes (PE > 500 or negative)
            merged["pe_dynamic"] = merged["pe_dynamic"].mask(merged["pe_dynamic"] < 0, np.nan) 
            merged["pe_dynamic"] = merged["pe_dynamic"].mask(merged["pe_dynamic"] > 500, 500)
            
        return merged[["pe_dynamic", "priceToSalesRatio", "priceToBookRatio"]]

    def _save_raw(self, df: pd.DataFrame, source: str):
        # Partition by Ticker for speed? Or just one big file?
        # For 3000 tickers, one big parquet file is fine (~50MB).
        out_path = self.raw_dir / f"{source}.parquet"
        df.to_parquet(out_path)
        logger.info(f"Saved {len(df)} rows to {out_path}")
        
    def _load_raw_for_ticker(self, ticker: str) -> pd.DataFrame:
        # Load from the consolidated store
        # Optimization: Caching
        p = self.raw_dir / "fmp_ratios.parquet"
        if not p.exists(): return pd.DataFrame()
        
        df = pd.read_parquet(p)
        return df[df["ticker"] == ticker]
