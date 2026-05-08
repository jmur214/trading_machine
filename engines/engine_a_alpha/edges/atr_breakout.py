# engines/engine_a_alpha/edges/atr_breakout.py
import pandas as pd, numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase

class ATRBreakoutEdge(EdgeBase):
    EDGE_ID = "atr_breakout_v1"
    EDGE_GROUP = "volatility"
    EDGE_CATEGORY = "momentum"
    DEFAULT_MIN_ADV_USD = 200_000_000  # $200M/day; ADV-fragile per Path-2 audit

    def compute_signals(self, data_map, as_of):
        scores = {}
        min_score = float(self.params.get("min_score", 0.3))
        min_adv_usd = self.params.get("min_adv_usd", self.DEFAULT_MIN_ADV_USD)
        for t, df in data_map.items():
            # Get dynamic params with defaults
            atr_window = int(self.params.get("lookback", 14))
            breakout_window = int(self.params.get("breakout_window", 20))
            score_scale = float(self.params.get("threshold", 3.0))

            if len(df) < max(atr_window, breakout_window) + 2: continue
            if self._below_adv_floor(df, min_adv_usd, ticker=t):
                continue

            high = df['High']
            low = df['Low']
            close = df['Close']

            # True Range = max of (H-L, |H-PrevC|, |L-PrevC|). The
            # earlier np.maximum(a, b, c) form silently treated the 3rd
            # arg as `out=` (numpy>=1.7 ufunc convention), corrupting the
            # result. Use the reduce-over-stacked-series form so all
            # three components are honored.
            tr = pd.concat(
                [high - low,
                 (high - close.shift()).abs(),
                 (low - close.shift()).abs()],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(atr_window).mean()
            breakout = (close - close.rolling(breakout_window).mean()) / (atr + 1e-9)
            raw = float(np.tanh(breakout.iloc[-1] / score_scale))
            # Dead zone: ignore weak signals that are just noise
            if abs(raw) < min_score:
                raw = 0.0
            scores[t] = raw
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