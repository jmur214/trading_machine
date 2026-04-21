import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate


class PanicEdge(EdgeBase, EdgeTemplate):
    """
    Behavioral edge: extreme panic mean reversion.

    Multi-condition panic detection:
    - RSI < rsi_threshold (deeply oversold)
    - Volume z-score > vol_z_threshold (capitulation volume)
    - Price below lower Bollinger Band
    - ATR expanding (volatility rising)

    When ALL conditions fire simultaneously, buy for mean reversion.
    Extreme panic clusters historically revert within 3-5 days.
    """

    EDGE_ID = "panic_v1"
    EDGE_GROUP = "behavioral"
    EDGE_CATEGORY = "mean_reversion"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "rsi_threshold": {"type": "float", "min": 15.0, "max": 30.0},
            "rsi_window": {"type": "int", "min": 5, "max": 20},
            "vol_z_threshold": {"type": "float", "min": 1.5, "max": 3.5},
            "vol_lookback": {"type": "int", "min": 15, "max": 40},
            "bb_window": {"type": "int", "min": 15, "max": 30},
            "bb_std": {"type": "float", "min": 1.5, "max": 3.0},
            "atr_expansion_pct": {"type": "float", "min": 1.1, "max": 2.0},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        rsi_thr = self.params.get("rsi_threshold", 20.0)
        rsi_win = self.params.get("rsi_window", 14)
        vol_z_thr = self.params.get("vol_z_threshold", 2.5)
        vol_lb = self.params.get("vol_lookback", 20)
        bb_win = self.params.get("bb_window", 20)
        bb_std = self.params.get("bb_std", 2.0)
        atr_exp = self.params.get("atr_expansion_pct", 1.3)

        for t, df in data_map.items():
            required = max(rsi_win, vol_lb, bb_win) + 20
            if len(df) < required:
                continue
            if not all(c in df.columns for c in ["Close", "High", "Low", "Volume"]):
                continue

            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"]

            # RSI
            delta = close.diff()
            up = delta.clip(lower=0)
            down = -delta.clip(upper=0)
            rs = up.rolling(rsi_win).mean() / (down.rolling(rsi_win).mean() + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            rsi_now = float(rsi.iloc[-1])

            # Volume z-score
            vol_mean = volume.rolling(vol_lb).mean().iloc[-1]
            vol_std_val = volume.rolling(vol_lb).std().iloc[-1]
            vol_z = (volume.iloc[-1] - vol_mean) / (vol_std_val + 1e-9)

            # Bollinger Band lower
            sma = close.rolling(bb_win).mean().iloc[-1]
            std = close.rolling(bb_win).std().iloc[-1]
            bb_lower = sma - bb_std * std
            price = close.iloc[-1]

            # ATR expansion: current ATR / ATR 10 bars ago
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            atr_now = atr.iloc[-1]
            atr_past = atr.iloc[-11] if len(atr) > 11 else atr.iloc[0]
            atr_ratio = atr_now / (atr_past + 1e-9)

            # Graduated scoring: each condition contributes 0.25
            # Minimum 3 of 4 conditions required to fire
            conditions = [
                rsi_now < rsi_thr,
                vol_z > vol_z_thr,
                price < bb_lower,
                atr_ratio > atr_exp,
            ]
            n_met = sum(conditions)
            scores[t] = (n_met / 4.0) if n_met >= 3 else 0.0

        return scores
