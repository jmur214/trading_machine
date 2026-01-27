# engines/engine_a_alpha/edges/atr_breakout.py
import pandas as pd, numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase

class ATRBreakoutEdge(EdgeBase):
    EDGE_ID = "atr_breakout_v1"
    EDGE_GROUP = "volatility"
    EDGE_CATEGORY = "momentum"

    def compute_signals(self, data_map, as_of):
        scores = {}
        for t, df in data_map.items():
            # Get dynamic params with defaults
            atr_window = int(self.params.get("lookback", 14))
            breakout_window = int(self.params.get("breakout_window", 20))
            score_scale = float(self.params.get("threshold", 3.0))

            if len(df) < max(atr_window, breakout_window) + 2: continue

            high = df['High']
            low = df['Low']
            close = df['Close']

            tr = np.maximum(high - low, np.abs(high - close.shift()), np.abs(low - close.shift()))
            atr = tr.rolling(atr_window).mean()
            breakout = (close - close.rolling(breakout_window).mean()) / (atr + 1e-9)
            scores[t] = float(np.tanh(breakout.iloc[-1] / score_scale))
        return scores

    def generate_signals(self, data_map, as_of):
        scores = self.compute_signals(data_map, as_of)
        signals = []
        for t, score in scores.items():
            side = "long" if score > 0 else "short"
            signals.append({
                "ticker": t,
                "side": side,
                "confidence": abs(score),
                "edge_id": self.EDGE_ID,
                "edge_group": self.EDGE_GROUP,
                "edge_category": self.EDGE_CATEGORY,
                "meta": {
                    "explain": f"ATR breakout detected (normalized score {score:.3f})"
                }
            })
        return signals