# engines/engine_a_alpha/edges/bollinger_reversion.py
import pandas as pd, numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase

class BollingerReversionEdge(EdgeBase):
    EDGE_ID = "bollinger_reversion_v1"
    EDGE_GROUP = "volatility"
    EDGE_CATEGORY = "mean_reversion"

    def compute_signals(self, data_map, as_of):
        scores = {}
        for t, df in data_map.items():
            if len(df) < 20: continue
            close = df["Close"]
            ma = close.rolling(20).mean()
            std = close.rolling(20).std()
            zscore = (close.iloc[-1] - ma.iloc[-1]) / (std.iloc[-1] + 1e-9)
            scores[t] = float(np.tanh(-zscore / 2))  # revert toward mean
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
                    "explain": f"Bollinger mean reversion detected (z-score normalized {score:.3f})"
                }
            })
        return signals