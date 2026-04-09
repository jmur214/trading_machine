import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional
from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

logger = logging.getLogger("FEATURE_ENG")

class FeatureEngineer:
    """
    Tier 1 Research Feature Factory.
    
    Responsibility:
    ---------------
    Takes Raw Data (OHLCV + Fundamentals) -> Returns 'Huntable' Feature Matrix.
    
    Architecture:
    -------------
    - Modular 'Aspects': Trend, Volatility, Fundamental, Relative.
    - Consistency: Same logic for Backtest (Training) and Live (Inference).
    - Caching: Computed features saved to Parquet to speed up ML training.
    """
    
    def __init__(self):
        pass

    def compute_all_features(self, ohlc_df: pd.DataFrame, fund_df: pd.DataFrame, spy_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Master factory method.
        """
        if ohlc_df.empty:
            return pd.DataFrame()

        # 1. Technical Extras (Trend/Momentum)
        df = self._compute_technicals(ohlc_df.copy())
        
        # 2. Fundamentals (Valuation/Growth)
        # We assume fund_df is already aligned (daily index) via FundamentalLoader
        if not fund_df.empty:
            # Join by index (Date)
            # Ensure index match
            df = df.join(fund_df, how="left")
            
        # 3. Relative Strength (vs SPY)
        if spy_df is not None and not spy_df.empty:
            df = self._compute_relative_strength(df, spy_df)
            
        # 4. Cleanup (Inf, NaN)
        df = df.replace([np.inf, -np.inf], np.nan)
        # Drop rows where critical features are NaN (e.g. first 200 days for SMA200)
        # Or keep them and let the tree decide? Tree handles NaNs poorly usually.
        # We will forward fill gaps (e.g. missed fundamental days) then drop cleanup
        df = df.ffill()
        
        return df

    def _compute_technicals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Check required columns
        if not all(col in df.columns for col in ["Open", "High", "Low", "Close", "Volume"]):
            return df

        # --- Trend ---
        # SMA / EMA
        df["SMA_50"] = SMAIndicator(close=df["Close"], window=50).sma_indicator()
        df["SMA_200"] = SMAIndicator(close=df["Close"], window=200).sma_indicator()
        df["EMA_20"] = EMAIndicator(close=df["Close"], window=20).ema_indicator()
        
        # Distance (Normalized)
        df["Dist_SMA200"] = (df["Close"] - df["SMA_200"]) / df["SMA_200"]
        
        # Crossovers (State)
        df["Above_SMA200"] = (df["Close"] > df["SMA_200"]).astype(int)
        df["Golden_Cross"] = (df["SMA_50"] > df["SMA_200"]).astype(int)
        
        # --- Momentum ---
        df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()
        
        # MACD
        macd = MACD(close=df["Close"])
        df["MACD"] = macd.macd()
        df["MACD_Hist"] = macd.macd_diff()
        df["MACD_Signal"] = macd.macd_signal()

        # ADX (Trend Strength)
        adx = ADXIndicator(high=df["High"], low=df["Low"], close=df["Close"], window=14)
        df["ADX"] = adx.adx()

        # --- Volatility ---
        # ATR % (Normalized Volatility)
        atr_ind = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14)
        atr_val = atr_ind.average_true_range()
        df["ATR_Pct"] = atr_val / df["Close"]
        
        # Bollinger Bands (Squeeze)
        bb = BollingerBands(close=df["Close"], window=20, window_dev=2)
        upper = bb.bollinger_hband()
        lower = bb.bollinger_lband()
        mid = bb.bollinger_mavg()
        
        # Width = (Upper - Lower) / Mid
        df["BB_Width"] = (upper - lower) / mid
        df["BB_Squeeze"] = (df["BB_Width"] < 0.05).astype(int) # Squeeze Definition

        # Volume Z-Score (Relative Volume)
        vol_mean = df["Volume"].rolling(20).mean()
        vol_std = df["Volume"].rolling(20).std()
        df["Vol_ZScore"] = (df["Volume"] - vol_mean) / (vol_std + 1e-9)
        
        return df

    def _compute_relative_strength(self, df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute RS vs SPY.
        """
        # Align dates
        spy_aligned = spy_df["Close"].reindex(df.index).ffill()
        
        # Ratio Line
        ratio = df["Close"] / spy_aligned
        
        # RS Rating (Simple ROC of Ratio)
        # 3 Month RS
        df["RS_3M"] = ratio.pct_change(63) # approx 63 trading days
        
        # RS Trend
        rs_sma50 = ratio.rolling(50).mean()
        df["RS_Strong"] = (ratio > rs_sma50).astype(int)
        
        return df

if __name__ == "__main__":
    # POC Test
    print("Testing Feature Engineer...")
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    data = {"Close": np.random.normal(100, 5, 300).cumsum().clip(50, 200),
            "High": np.random.normal(102, 5, 300).cumsum().clip(50, 200),
            "Low": np.random.normal(98, 5, 300).cumsum().clip(50, 200),
            "Volume": np.random.randint(1000, 10000, 300)}
    df = pd.DataFrame(data, index=dates)
    
    fe = FeatureEngineer()
    res = fe.compute_all_features(df, pd.DataFrame())
    print(res.tail().T)
