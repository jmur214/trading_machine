import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate
from engines.data_manager.data_manager import DataManager
from debug_config import is_debug_enabled

class ValueTrapEdge(EdgeBase, EdgeTemplate):
    """
    Fundamental Edge: Value Trap / Deep Value.
    Buys stocks with low P/E ratios, assuming mean reversion or undervaluation.
    
    WARNING: yfinance provides *Current* fundamentals. Backtesting this over history
    using current P/E introduces Lookahead Bias. This edge is best validated in Live/Paper
    or if we had a historical fundamental database.
    """
    
    EDGE_ID = "value_trap_v1"
    EDGE_GROUP = "fundamental"
    EDGE_CATEGORY = "value"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "max_pe": {"type": "float", "min": 5.0, "max": 25.0},
            "min_market_cap_B": {"type": "float", "min": 10.0, "max": 200.0}, # Billions
        }

    def __init__(self, params=None):
        super().__init__()
        self.set_params(params)
        self.dm = DataManager()
        self.fundamental_cache = {} # Cache during lifespan of edge logic

    def compute_signals(self, data_map, as_of):
        scores = {}
        
        max_pe = self.params.get("max_pe", 15.0)
        min_cap = self.params.get("min_market_cap_B", 50.0) * 1e9
        
        for t, df in data_map.items():
            # 1. Check Technical Condition (e.g. price > SMA200? or just oversold?)
            # Let's say we only buy "Value" if it's also technically oversold (RSI < 40)
            # This makes it a "Timing" edge on top of a "Value" filter.
            if len(df) < 20 or "Close" not in df:
                continue
                
            # Technical Pre-filter (Hybrid Edge)
            close = df["Close"]
            delta = close.diff()
            up, down = delta.clip(lower=0), -delta.clip(upper=0)
            rsi_window = 14
            roll_up = up.rolling(rsi_window).mean()
            roll_down = down.rolling(rsi_window).mean()
            rs = roll_up / (roll_down + 1e-9)
            rsi = 100 - (100 / (1 + rs))
            rsi_now = float(rsi.iloc[-1])
            
            max_rsi = self.params.get("max_rsi", 40.0)
            if rsi_now > max_rsi: # Only look at oversold value stocks
                # print(f"DEBUG: {t} RSI={rsi_now:.2f} too high")
                scores[t] = 0.0
                continue
            
            print(f"DEBUG: {t} passed technicals (RSI={rsi_now:.2f}). Fetching fundamentals...")
                
            # 2. Check Fundamentals
            # We cache the time-series dataframe
            if t not in self.fundamental_cache:
                self.fundamental_cache[t] = self.dm.fetch_historical_fundamentals(t)
                
            fund_df = self.fundamental_cache[t]
            if fund_df.empty:
                # Fallback to static if historical fails? No, strict mode requested.
                scores[t] = 0.0
                continue
                
            # Point-in-Time Lookup using asof
            # fund_df is daily indexed (forward filled)
            try:
                # Find the row for 'as_of' or nearest before
                if as_of in fund_df.index:
                    row = fund_df.loc[as_of]
                else:
                    # Use get_indexer for nearest backward (method='pad')
                   idx_loc = fund_df.index.get_indexer([as_of], method='pad')[0]
                   if idx_loc == -1:
                       # Date is before our fundamental history starts
                       scores[t] = 0.0
                       continue
                   row = fund_df.iloc[idx_loc]
                
                pe = row["PE_Ratio"]
                cap = row["Market_Cap"]
                
                # Logic
                score = 0.0
                if 0 < pe < max_pe and cap > min_cap:
                    score = 1.0
                    if is_debug_enabled("ALPHA"):
                        print(f"[VALUE_EDGE] {t} BUY (Date={as_of.date()}, P/E={pe:.1f}, RSI={rsi_now:.0f})")
                
                scores[t] = score
                
            except Exception as e:
                # print(f"Fundamental lookup error for {t}: {e}")
                scores[t] = 0.0

            
        return scores

    def generate_signals(self, data_map, as_of):
        scores = self.compute_signals(data_map, as_of)
        signals = []
        for t, score in scores.items():
            if abs(score) > 0:
                side = "long" if score > 0 else "short"  # Value is typically long only
                signals.append({
                    "ticker": t,
                    "side": side,
                    "confidence": abs(score),
                    "edge_id": self.EDGE_ID,
                    "edge_group": self.EDGE_GROUP,
                    "edge_category": self.EDGE_CATEGORY,
                    "meta": {
                        "explain": f"Value Trap: Low P/E + Oversold"
                    }
                })
        return signals
