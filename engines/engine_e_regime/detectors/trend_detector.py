"""
TrendDetector — Axis 1 of 5.

Classifies the benchmark's trend regime using:
  - SMA200 for long-term trend direction
  - SMA50 for medium-term momentum
  - Dual Kaufman Efficiency Ratio: ER(60) for structural trend quality,
    ER(14) for tactical confidence modifier
  - SMA50 slope over 20 bars for trend acceleration
"""

import numpy as np
import pandas as pd
from typing import Tuple

from engines.engine_e_regime.regime_config import TrendConfig


def _kaufman_er(series: pd.Series, window: int) -> pd.Series:
    """Kaufman Efficiency Ratio: directional change / total path length."""
    direction = series.diff(window).abs()
    path = series.diff().abs().rolling(window).sum()
    return direction / (path + 1e-9)


class TrendDetector:
    """Detects trend regime from benchmark (SPY) data.

    States: "bull" | "bear" | "range"
    """

    def __init__(self, config: TrendConfig = None):
        self.cfg = config or TrendConfig()

    def detect(self, benchmark_df: pd.DataFrame) -> Tuple[str, float, dict]:
        """Analyze benchmark DataFrame and return (state, confidence, details).

        Args:
            benchmark_df: SPY OHLCV DataFrame with at least sma_long + slope_window rows.

        Returns:
            (state, confidence, details) where state is "bull"|"bear"|"range",
            confidence is [0.1, 0.95], and details is an enriched dict.
        """
        cfg = self.cfg
        min_rows = cfg.sma_long + cfg.slope_window
        if benchmark_df.empty or len(benchmark_df) < min_rows:
            return ("range", 0.1, self._empty_details())

        df = benchmark_df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"].astype(float)

        # Core indicators
        sma200 = close.rolling(window=cfg.sma_long).mean()
        sma50 = close.rolling(window=cfg.sma_short).mean()
        er_60 = _kaufman_er(close, cfg.er_structural_window)
        er_14 = _kaufman_er(close, cfg.er_tactical_window)

        # SMA50 slope: linear change over slope_window bars, normalized by price
        sma50_vals = sma50.dropna()
        if len(sma50_vals) >= cfg.slope_window:
            slope_raw = (
                sma50_vals.iloc[-1] - sma50_vals.iloc[-cfg.slope_window]
            ) / cfg.slope_window
            slope_50 = slope_raw / (close.iloc[-1] + 1e-9)
        else:
            slope_50 = 0.0

        # Latest values
        price = float(close.iloc[-1])
        sma200_val = float(sma200.iloc[-1])
        sma50_val = float(sma50.iloc[-1])
        er_60_val = float(er_60.iloc[-1]) if not np.isnan(er_60.iloc[-1]) else 0.0
        er_14_val = float(er_14.iloc[-1]) if not np.isnan(er_14.iloc[-1]) else 0.0

        # --- State classification ---
        # Low structural efficiency → range (choppy market)
        if er_60_val < cfg.er_chop_threshold:
            state = "range"
        elif price > sma200_val and sma50_val > sma200_val and slope_50 > 0:
            state = "bull"
        elif price < sma200_val and sma50_val < sma200_val and slope_50 < 0:
            state = "bear"
        else:
            # Partially met conditions — will be held by hysteresis
            # Default to range as the "uncertain" bucket
            state = "range"

        # --- Confidence ---
        # 40% SMA200 separation, 40% ER(60), 20% ER(14) cleanliness
        sma200_sep = abs(price - sma200_val) / (sma200_val + 1e-9)
        sma200_component = min(sma200_sep / 0.10, 1.0)  # saturates at 10% separation
        er60_component = er_60_val  # already 0-1
        er14_component = er_14_val  # already 0-1

        confidence = (
            0.40 * sma200_component + 0.40 * er60_component + 0.20 * er14_component
        )
        confidence = float(np.clip(confidence, 0.1, 0.95))

        # --- Trend quality: slope of ER(60) over 20 bars ---
        er60_series = er_60.dropna()
        if len(er60_series) >= cfg.slope_window:
            er60_slope = (
                er60_series.iloc[-1] - er60_series.iloc[-cfg.slope_window]
            ) / cfg.slope_window
            if er60_slope > 0.005:
                trend_quality = "improving"
            elif er60_slope < -0.005:
                trend_quality = "degrading"
            else:
                trend_quality = "stable"
        else:
            trend_quality = "stable"

        # --- Momentum consistency: fraction of last 10 bars above SMA50 ---
        lookback = min(10, len(close))
        recent_close = close.iloc[-lookback:]
        recent_sma50 = sma50.iloc[-lookback:]
        momentum_consistency = float((recent_close > recent_sma50).mean())

        details = {
            "price": price,
            "sma200": sma200_val,
            "sma50": sma50_val,
            "er_60": round(er_60_val, 4),
            "er_14": round(er_14_val, 4),
            "slope_50": round(float(slope_50), 6),
            "trend_quality": trend_quality,
            "sma200_separation": round(sma200_sep, 4),
            "momentum_consistency": round(momentum_consistency, 2),
        }

        return (state, confidence, details)

    @staticmethod
    def _empty_details() -> dict:
        return {
            "price": 0.0,
            "sma200": 0.0,
            "sma50": 0.0,
            "er_60": 0.0,
            "er_14": 0.0,
            "slope_50": 0.0,
            "trend_quality": "stable",
            "sma200_separation": 0.0,
            "momentum_consistency": 0.0,
        }
