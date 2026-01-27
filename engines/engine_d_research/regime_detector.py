import pandas as pd
import numpy as np

class RegimeDetector:
    """
    Detects the current market regime based on a benchmark (e.g., SPY).
    States:
      - Trend: Bull (Price > SMA + High ER), Bear (Price < SMA + High ER), Neutral (Low ER)
      - Volatility: High (ATR > 75th percentile), Normal (25-75), Low (<25)
    """

    def __init__(self, high_vol_percentile=75, low_vol_percentile=25, ma_window=200):
        self.high_vol_percentile = high_vol_percentile
        self.low_vol_percentile = low_vol_percentile
        self.ma_window = ma_window

    def detect_regime(self, benchmark_df: pd.DataFrame) -> dict:
        """
        Analyzes the benchmark DataFrame.
        Returns:
          - trend: "bull" | "bear" | "neutral"
          - volatility: "high" | "normal" | "low"
          - regime_int: 1 (Bull), -1 (Bear), 0 (Neutral)
        """
        if benchmark_df.empty or len(benchmark_df) < self.ma_window:
            return {"regime": "unknown", "trend": "unknown", "volatility": "unknown", "regime_int": 0}

        df = benchmark_df.copy()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 1. Trend (SMA)
        df["SMA"] = df["Close"].rolling(window=self.ma_window).mean()
        
        # 2. Volatility (ATR)
        df["H-L"] = df["High"] - df["Low"]
        df["H-PC"] = abs(df["High"] - df["Close"].shift(1))
        df["L-PC"] = abs(df["Low"] - df["Close"].shift(1))
        df["TR"] = df[["H-L", "H-PC", "L-PC"]].max(axis=1)
        df["ATR"] = df["TR"].rolling(window=14).mean()
        
        # 3. Chop Detection (Efficiency Ratio - Kaufman)
        # ER = Directional Change / Total Path Length
        window = 14
        df["Change"] = df["Close"].diff(window).abs()
        df["Path"] = df["Close"].diff().abs().rolling(window).sum()
        df["ER"] = df["Change"] / (df["Path"] + 1e-9)
        # ER near 1.0 = Trending, ER near 0.0 = Choppy.
        
        last_row = df.iloc[-1]
        
        try:
            price = float(last_row["Close"])
            sma = float(last_row["SMA"])
            er = float(last_row["ER"])
        except Exception:
            price, sma, er = 0.0, 0.0, 0.0

        # Trend Logic
        # If ER is very low (< 0.25), we are in "Neutral/Chop" regardless of SMA
        if er < 0.25:
            trend = "neutral"
            regime_int = 0
        else:
            if price > sma:
                trend = "bull"
                regime_int = 1
            else:
                trend = "bear"
                regime_int = -1
        
        # Volatility Logic
        recent_history = df.iloc[-252:]
        try:
            current_atr = float(last_row["ATR"])
        except:
            current_atr = 0.0
        
        atr_rank = 50
        if not recent_history["ATR"].dropna().empty:
            atr_rank = (recent_history["ATR"].dropna() < current_atr).mean() * 100
            
        if atr_rank > self.high_vol_percentile:
            vol_state = "high"
        elif atr_rank < self.low_vol_percentile:
            vol_state = "low"
        else:
            vol_state = "normal"
            
        regime_label = f"{trend}_{vol_state}_vol"
        
        return {
            "regime": regime_label,
            "trend": trend,
            "volatility": vol_state,
            "regime_int": regime_int,
            "details": {
                "price": price,
                "sma": sma,
                "atr": current_atr,
                "er": er,
                "atr_percentile": atr_rank
            }
        }
