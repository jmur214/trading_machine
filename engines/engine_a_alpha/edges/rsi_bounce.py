import pandas as pd, numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase

class RSIBounceEdge(EdgeBase):
    EDGE_ID = "rsi_bounce_v1"
    EDGE_GROUP = "technical"
    EDGE_CATEGORY = "mean_reversion"

    def compute_signals(self, data_map, as_of):
        scores = {}
        for t, df in data_map.items():
            if len(df) < 20 or "Close" not in df:
                continue
            close = df["Close"]
            delta = close.diff()
            up, down = delta.clip(lower=0), -delta.clip(upper=0)
            roll_up = up.rolling(14).mean()
            roll_down = down.rolling(14).mean()
            rs = roll_up / (roll_down + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            rsi_now = float(rsi.iloc[-1])
            # bounce score: below 30 → strong buy; above 70 → strong sell
            scores[t] = float(np.tanh((50 - rsi_now) / 25))
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
                    "explain": f"RSI bounce detected (RSI mean reversion strength {score:.3f})"
                }
            })
        return signals