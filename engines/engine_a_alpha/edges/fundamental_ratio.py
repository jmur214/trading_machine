import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate
from engines.data_manager.data_manager import DataManager
from debug_config import is_debug_enabled

class FundamentalRatioEdge(EdgeBase, EdgeTemplate):
    """
    Generic Fundamental Edge.
    Evolutionary Parameters:
      - metric: [PE_Ratio, PS_Ratio, PB_Ratio, PFCF_Ratio, Debt_to_Equity]
      - operator: ["less", "greater"]
      - threshold: [Generic Float, scaled dynamically or fixed?]
         - Note: Thresholds vary wildly (PE ~15, PS ~2). 
         - Better to use percentile or fixed ranges if we know them.
      - rsi_filter_enabled: [True, False]
      
    This allows the machine to find:
      - Value: PE < 15
      - Growth at Reasonable Price: PS < 5 AND PE < 30
      - Quality: Debt_to_Equity < 0.5
    """
    
    EDGE_ID = "fundamental_ratio_v1" # Base ID, will be suffixed by Governor
    EDGE_GROUP = "fundamental"
    EDGE_CATEGORY = "generic"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "metric": ["PE_Ratio", "PS_Ratio", "PB_Ratio", "PFCF_Ratio", "Debt_to_Equity"],
            "operator": ["less", "greater"],
            "threshold": {"type": "float", "min": 0.5, "max": 50.0}, 
            "max_rsi": {"type": "float", "min": 30.0, "max": 70.0},
            "enable_rsi": [True, False]
        }

    def __init__(self, params=None):
        super().__init__()
        self.set_params(params)
        self.dm = DataManager()
        self.fundamental_cache = {} 
        self.default_thresholds = {
            "PE_Ratio": 15.0,
            "PS_Ratio": 3.0,
            "PB_Ratio": 1.5,
            "PFCF_Ratio": 20.0,
            "Debt_to_Equity": 1.0
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        
        # Params
        metric_name = self.params.get("metric", "PE_Ratio")
        operator = self.params.get("operator", "less")
        
        # Smart defaulting if evolved threshold is totally whack? 
        # Or just let evolution fail if it picks threshold=50 for Debt/Eq.
        threshold = self.params.get("threshold", self.default_thresholds.get(metric_name, 10.0))
        
        enable_rsi = self.params.get("enable_rsi", False)
        max_rsi = self.params.get("max_rsi", 40.0)
        
        for t, df in data_map.items():
            if len(df) < 20 or "Close" not in df:
                continue
                
            # 1. Technical Filter (Optional)
            if enable_rsi:
                close = df["Close"]
                delta = close.diff()
                up, down = delta.clip(lower=0), -delta.clip(upper=0)
                roll_up = up.rolling(14).mean()
                roll_down = down.rolling(14).mean()
                rs = roll_up / (roll_down + 1e-9)
                rsi = 100 - (100 / (1 + rs))
                rsi_now = float(rsi.iloc[-1])
                
                if rsi_now > max_rsi:
                    scores[t] = 0.0
                    continue

            # 2. Fundamental Check
            if t not in self.fundamental_cache:
                self.fundamental_cache[t] = self.dm.fetch_historical_fundamentals(t)
                
            fund_df = self.fundamental_cache[t]
            if fund_df.empty:
                scores[t] = 0.0
                continue
                
            if metric_name not in fund_df.columns:
                # Metric might be missing for this specific stock (e.g. no debt)
                scores[t] = 0.0
                continue

            try:
                # Point-in-Time Lookup
                if as_of in fund_df.index:
                    row = fund_df.loc[as_of]
                else:
                   idx_loc = fund_df.index.get_indexer([as_of], method='pad')[0]
                   if idx_loc == -1:
                       scores[t] = 0.0
                       continue
                   row = fund_df.iloc[idx_loc]
                   
                val = row[metric_name]
                
                # Logic
                hit = False
                if operator == "less":
                    if val < threshold: hit = True
                else: # greater
                    if val > threshold: hit = True
                    
                if hit:
                    scores[t] = 1.0
                    if is_debug_enabled("ALPHA"):
                       print(f"[FUNDA_GENERIC] {t} BUY ({metric_name}={val:.2f} {operator} {threshold:.2f})")
                else:
                    scores[t] = 0.0
                    
            except Exception as e:
                scores[t] = 0.0
                    
        return scores

    def generate_signals(self, data_map, as_of):
        scores = self.compute_signals(data_map, as_of)
        signals = []
        for t, score in scores.items():
            if abs(score) > 0:
                signals.append({
                    "ticker": t,
                    "side": "long", # Fundamentals usually imply long for now (shorting value traps is harder)
                    "confidence": abs(score),
                    "edge_id": self.EDGE_ID,
                    "edge_group": self.EDGE_GROUP,
                    "edge_category": self.params.get("metric", "general"),
                    "meta": {
                        "explain": f"{self.params.get('metric')} {self.params.get('operator')} {self.params.get('threshold'):.2f}"
                    }
                })
        return signals
