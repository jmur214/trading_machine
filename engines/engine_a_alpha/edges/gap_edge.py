import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate


class GapEdge(EdgeBase, EdgeTemplate):
    """
    Stat/Quant edge: overnight gap fill.

    Gap down > atr_mult * ATR → long (expect fill toward previous close).
    Gap up > atr_mult * ATR → short (expect fill toward previous close).
    Historical gap fill rate ~70% for liquid equities.
    """

    EDGE_ID = "gap_fill_v1"
    EDGE_GROUP = "stat_quant"
    EDGE_CATEGORY = "mean_reversion"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "atr_mult": {"type": "float", "min": 0.5, "max": 3.0},
            "atr_window": {"type": "int", "min": 10, "max": 30},
            "require_volume_spike": {"type": "bool"},
            "vol_z_threshold": {"type": "float", "min": 1.0, "max": 3.0},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        atr_mult = self.params.get("atr_mult", 1.0)
        atr_window = self.params.get("atr_window", 14)
        require_vol = self.params.get("require_volume_spike", False)
        vol_z_thr = self.params.get("vol_z_threshold", 2.0)

        for t, df in data_map.items():
            if len(df) < atr_window + 5:
                continue
            if not all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
                continue

            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            open_ = df["Open"]

            # ATR
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(atr_window).mean().iloc[-1]

            if atr < 1e-9:
                scores[t] = 0.0
                continue

            # Overnight gap
            prev_close = close.iloc[-2]
            curr_open = open_.iloc[-1]
            gap = curr_open - prev_close
            gap_atr = gap / atr

            # Volume filter
            if require_vol and "Volume" in df.columns:
                vol = df["Volume"]
                vol_mean = vol.rolling(20).mean().iloc[-1]
                vol_std = vol.rolling(20).std().iloc[-1]
                if vol_std > 0:
                    vol_z = (vol.iloc[-1] - vol_mean) / vol_std
                else:
                    vol_z = 0.0
                if vol_z < vol_z_thr:
                    scores[t] = 0.0
                    continue

            # Signal
            if gap_atr < -atr_mult:
                # Gap down → long for fill
                scores[t] = 1.0
            elif gap_atr > atr_mult:
                # Gap up → short for fill
                scores[t] = -1.0
            else:
                scores[t] = 0.0

        return scores
