import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate


class VolumeAnomalyEdge(EdgeBase, EdgeTemplate):
    """
    Stat/Quant edge: volume anomaly patterns.

    Two modes:
    - spike_reversal: Vol_ZScore > threshold with bullish/bearish bar → mean reversion
    - dryup_breakout: Vol_ZScore < -threshold with Bollinger squeeze → breakout anticipation
    """

    EDGE_ID = "volume_anomaly_v1"
    EDGE_GROUP = "stat_quant"
    EDGE_CATEGORY = "volume"
    DEFAULT_MIN_ADV_USD = 300_000_000  # $300M/day; per-ticker microstructure-driven, higher floor per Path-2 audit

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "mode": {"type": "categorical", "choices": ["spike_reversal", "dryup_breakout"]},
            "vol_z_threshold": {"type": "float", "min": 1.5, "max": 3.5},
            "vol_lookback": {"type": "int", "min": 15, "max": 40},
            "bb_window": {"type": "int", "min": 15, "max": 30},
            "bb_squeeze_pct": {"type": "float", "min": 0.01, "max": 0.05},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        mode = self.params.get("mode", "spike_reversal")
        vol_z_thr = self.params.get("vol_z_threshold", 2.0)
        vol_lb = self.params.get("vol_lookback", 20)
        bb_win = self.params.get("bb_window", 20)
        bb_squeeze = self.params.get("bb_squeeze_pct", 0.03)
        min_adv_usd = self.params.get("min_adv_usd", self.DEFAULT_MIN_ADV_USD)

        for t, df in data_map.items():
            if len(df) < max(vol_lb, bb_win) + 10:
                continue
            if "Close" not in df.columns or "Volume" not in df.columns:
                continue
            if self._below_adv_floor(df, min_adv_usd, ticker=t):
                continue

            close = df["Close"]
            volume = df["Volume"]

            # Volume z-score
            vol_mean = volume.rolling(vol_lb).mean().iloc[-1]
            vol_std = volume.rolling(vol_lb).std().iloc[-1]
            if vol_std < 1e-9:
                scores[t] = 0.0
                continue
            vol_z = (volume.iloc[-1] - vol_mean) / vol_std

            if mode == "spike_reversal":
                scores[t] = self._spike_reversal(close, vol_z, vol_z_thr)
            else:
                scores[t] = self._dryup_breakout(close, vol_z, vol_z_thr, bb_win, bb_squeeze)

        return scores

    def _spike_reversal(self, close, vol_z, threshold):
        """Volume spike + bearish bar → long; spike + bullish bar → short."""
        if vol_z < threshold:
            return 0.0

        # Bar direction: compare close to open (or previous close)
        today_ret = float(close.pct_change().iloc[-1])

        if today_ret < -0.005:
            # Bearish bar with volume spike → mean reversion long
            return 1.0
        elif today_ret > 0.005:
            # Bullish bar with volume spike → mean reversion short
            return -1.0
        return 0.0

    def _dryup_breakout(self, close, vol_z, threshold, bb_win, squeeze_pct):
        """Volume dry-up + Bollinger squeeze → breakout anticipation (long bias)."""
        if vol_z > -threshold:
            return 0.0

        # Bollinger Band width
        sma = close.rolling(bb_win).mean()
        std = close.rolling(bb_win).std()
        bb_upper = sma + 2 * std
        bb_lower = sma - 2 * std
        bb_width = ((bb_upper - bb_lower) / sma).iloc[-1]

        if bb_width < squeeze_pct:
            # Squeeze + volume dry-up → breakout coming, long bias
            return 1.0
        return 0.0
