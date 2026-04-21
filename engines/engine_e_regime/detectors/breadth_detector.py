"""
BreadthDetector — Axis 4 of 5.

Classifies market breadth using:
  - % of tickers above SMA200 and SMA50
  - 10-bar linear regression slope of pct_above_sma200 (rate of change)
  - New Highs minus New Lows ratio
"""

import numpy as np
import pandas as pd
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from engines.engine_e_regime.regime_config import BreadthConfig


class BreadthDetector:
    """Detects market breadth regime from the full ticker data_map.

    States: "strong" | "narrow" | "recovering" | "weak" | "deteriorating"

    Stateful: stores a rolling deque of pct_above_sma200 values for slope computation.
    """

    def __init__(self, config: BreadthConfig = None, exclude_tickers: Set[str] = None):
        self.cfg = config or BreadthConfig()
        self.exclude = exclude_tickers or set()
        self._history: deque = deque(maxlen=max(20, self.cfg.slope_window + 5))

    def detect(
        self, data_map: Dict[str, pd.DataFrame], now_idx: int = -1
    ) -> Tuple[str, float, dict]:
        """Analyze breadth across all non-benchmark tickers.

        Args:
            data_map: Dict of {ticker: OHLCV DataFrame}.
            now_idx: Index position to evaluate (default -1 for latest bar).

        Returns:
            (state, confidence, details)
        """
        cfg = self.cfg
        eligible = {
            t: df
            for t, df in data_map.items()
            if t not in self.exclude and len(df) >= cfg.sma_long + 1
        }

        if len(eligible) < 10:
            return ("strong", 0.3, self._empty_details())

        total = len(eligible)
        above_sma200 = 0
        above_sma50 = 0
        new_highs = 0
        new_lows = 0

        for ticker, df in eligible.items():
            if isinstance(df.columns, pd.MultiIndex):
                df = df.copy()
                df.columns = df.columns.get_level_values(0)

            close = df["Close"].astype(float)

            try:
                price = float(close.iloc[now_idx])
            except (IndexError, KeyError):
                continue

            sma200 = float(close.rolling(cfg.sma_long).mean().iloc[now_idx])
            sma50 = float(close.rolling(cfg.sma_short).mean().iloc[now_idx])

            if price > sma200:
                above_sma200 += 1
            if price > sma50:
                above_sma50 += 1

            # New highs / new lows (52-week / nh_nl_window)
            lookback = min(cfg.nh_nl_window, len(close))
            hist_window = close.iloc[-lookback : now_idx if now_idx != -1 else len(close)]
            if len(hist_window) > 1:
                if price >= hist_window.max():
                    new_highs += 1
                if price <= hist_window.min():
                    new_lows += 1

        pct_above_sma200 = above_sma200 / total
        pct_above_sma50 = above_sma50 / total
        nh_nl_pct = (new_highs - new_lows) / total

        # Store for slope computation
        self._history.append(pct_above_sma200)

        # --- Breadth slope: 10-bar linear regression ---
        slope = 0.0
        if len(self._history) >= cfg.slope_window:
            recent = list(self._history)[-cfg.slope_window :]
            x = np.arange(len(recent))
            y = np.array(recent)
            if np.std(y) > 1e-9:
                slope = float(np.polyfit(x, y, 1)[0])

        # --- State classification ---
        if pct_above_sma200 > cfg.strong_sma200_pct and pct_above_sma50 > cfg.strong_sma50_pct:
            state = "strong"
        elif (
            pct_above_sma200 < cfg.deteriorating_ceiling
            and slope < cfg.slope_deteriorating_threshold
        ):
            state = "deteriorating"
        elif (
            cfg.recovering_floor < pct_above_sma200 < cfg.recovering_ceiling
            and slope > cfg.slope_recovering_threshold
        ):
            state = "recovering"
        elif (
            pct_above_sma200 > cfg.narrow_sma200_pct
            and pct_above_sma50 < cfg.narrow_sma50_pct
        ):
            state = "narrow"
        elif pct_above_sma200 < cfg.weak_sma200_pct:
            state = "weak"
        else:
            # Default fallback
            state = "narrow" if pct_above_sma50 < 0.50 else "strong"

        # --- Confidence ---
        if state == "strong":
            confidence = 0.5 + 0.4 * min(
                (pct_above_sma200 - cfg.strong_sma200_pct) / 0.20, 1.0
            )
        elif state == "weak":
            confidence = 0.5 + 0.4 * min(
                (cfg.weak_sma200_pct - pct_above_sma200) / 0.20, 1.0
            )
        elif state == "deteriorating":
            confidence = 0.5 + 0.4 * min(abs(slope) / 0.03, 1.0)
        elif state == "recovering":
            confidence = 0.5 + 0.3 * min(slope / 0.03, 1.0)
        else:  # narrow
            confidence = 0.5

        confidence = float(np.clip(confidence, 0.1, 0.95))

        # --- Leadership quality: std of sector-level pct_above_sma50 ---
        # (placeholder — would need sector_map to compute per-sector breadth)
        leadership_quality = 0.0

        # --- Breadth trend ---
        if slope > 0.005:
            breadth_trend = "expanding"
        elif slope < -0.005:
            breadth_trend = "contracting"
        else:
            breadth_trend = "flat"

        details = {
            "pct_above_sma200": round(pct_above_sma200, 3),
            "pct_above_sma50": round(pct_above_sma50, 3),
            "breadth_slope": round(slope, 5),
            "nh_nl_pct": round(nh_nl_pct, 3),
            "leadership_quality": round(leadership_quality, 3),
            "breadth_trend": breadth_trend,
        }

        return (state, confidence, details)

    def reset(self) -> None:
        """Clear internal state. Called between backtest runs."""
        self._history.clear()

    @staticmethod
    def _empty_details() -> dict:
        return {
            "pct_above_sma200": 0.0,
            "pct_above_sma50": 0.0,
            "breadth_slope": 0.0,
            "nh_nl_pct": 0.0,
            "leadership_quality": 0.0,
            "breadth_trend": "flat",
        }
