import numpy as np
import pandas as pd
from ..edge_base import EdgeBase


class MomentumEdge(EdgeBase):
    EDGE_ID = "momentum_edge_v1"
    CATEGORY = "technical"
    DESCRIPTION = "Momentum edge detecting moving-average crossovers with normalized strength."

    def compute_signals(self, data_map, now):
        scores = {}
        short_window = 10
        long_window = 40

        for ticker, df in data_map.items():
            if len(df) < long_window + 2 or "Close" not in df.columns:
                continue

            close = df["Close"].astype(float)

            ma_short = close.rolling(short_window).mean()
            ma_long = close.rolling(long_window).mean()

            delta = ma_short.iloc[-1].item() - ma_long.iloc[-1].item()
            norm_score = float(np.tanh(delta / (close.iloc[-1].item() * 0.02)))

            scores[ticker] = norm_score

        return scores

    def generate_signals(self, data_map, now):
        scores = self.compute_signals(data_map, now)
        signals = []

        for ticker, score in scores.items():
            if score > 0:
                side = "long"
            elif score < 0:
                side = "short"
            else:
                continue

            meta = {
                "explanation": "MA crossover detected with normalized strength {:.4f}".format(score)
            }

            signals.append({
                "ticker": ticker,
                "side": side,
                "confidence": abs(score),
                "edge_id": self.EDGE_ID,
                "edge_group": self.CATEGORY,
                "edge_category": self.CATEGORY,
                "meta": meta
            })

        return signals


from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec
try:
    reg = EdgeRegistry()
    reg.ensure(EdgeSpec(edge_id=MomentumEdge.EDGE_ID, category=MomentumEdge.CATEGORY,
                        module=__name__, version="1.0.0",
                        params={}, status="active"))
except Exception:
    pass