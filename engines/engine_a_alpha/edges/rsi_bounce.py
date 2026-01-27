import pandas as pd, numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate

class RSIBounceEdge(EdgeBase, EdgeTemplate):
    EDGE_ID = "rsi_bounce_v1"
    EDGE_GROUP = "technical"
    EDGE_CATEGORY = "mean_reversion"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "window": {"type": "int", "min": 5, "max": 25},
            "buy_threshold": {"type": "float", "min": 25.0, "max": 50.0},
            "sell_threshold": {"type": "float", "min": 55.0, "max": 80.0},
            "trend_filter": {"type": "bool"}, 
            "trend_window": {"type": "int", "min": 50, "max": 250}, # Evolve the trend definition
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        for t, df in data_map.items():
            # Default to window + some buffer, don't hard enforce 252 unless trend filter is ON
            window = int(self.params.get("window", 14))
            trend_window = int(self.params.get("trend_window", 200))
            required_len = trend_window + 5 if self.params.get("trend_filter") else window + 20
            
            if len(df) < required_len or "Close" not in df:
                continue
            close = df["Close"]
            delta = close.diff()
            up, down = delta.clip(lower=0), -delta.clip(upper=0)
            roll_up = up.rolling(window).mean()
            roll_down = down.rolling(window).mean()
            rs = roll_up / (roll_down + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            rsi_now = float(rsi.iloc[-1])
            
            # thresholds
            buy_thr = self.params.get("buy_threshold", 30.0)
            sell_thr = self.params.get("sell_threshold", 70.0)
            
            # Trend Filter Logic
            trend_score = 1.0 # Default neutral
            if self.params.get("trend_filter", False):
                 sma_window = self.params.get("trend_window", 200)
                 if len(close) >= sma_window:
                     sma = close.rolling(sma_window).mean().iloc[-1]
                     current_price = close.iloc[-1]
                     # If price < SMA, we are in a downtrend. 
                     # For mean reversion long, we want uptrend (price > SMA).
                     if current_price < sma:
                         trend_score = 0.0 # Veto signal
                         
            # Standardizing: Use explicit Step Function
            raw_score = 0.0
            
            if rsi_now < buy_thr:
                # Long signal
                raw_score = 1.0
            elif rsi_now > sell_thr:
                # Short signal
                raw_score = -1.0
            
            # Apply trend filter (Longs only)
            if raw_score > 0 and trend_score == 0.0:
                 raw_score = 0.0
            
            scores[t] = float(raw_score)
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