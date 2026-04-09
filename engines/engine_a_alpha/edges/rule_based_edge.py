from engines.engine_a_alpha.edge_template import EdgeTemplate
from typing import Dict, Any, List, Optional
import pandas as pd

class RuleBasedEdge(EdgeTemplate):
    """
    Tier 2 Edge: The Machine-Discovered Logic.
    
    Responsibilities:
    -----------------
    1. Executes specific Logical Rules discovered by DiscoveryEngine (TreeScanner).
    2. Example Rule: "RSI > 50 AND PE < 20".
    3. Designed to be serialized/deserialized easily from JSON/YAML.
    """
    
    EDGE_ID = "rule_based_edge"
    EDGE_CATEGORY = "synthetic"
    
    def __init__(self, rule_string: str = "", target_class: int = 2, probability: float = 0.0, description: str = ""):
        super().__init__()
        self.rule_string = rule_string # e.g. "RSI_14 > 50 AND Vol_ZScore > 1.0"
        self.target_class = target_class # e.g. 2 (Explode)
        self.probability = probability
        self.description = description
        
        # Parsed conditions
        self.conditions = []
        if rule_string:
            self._parse_rule(rule_string)
            
    def set_params(self, params: Dict[str, Any]):
        """
        Hydrate from storage.
        """
        self.rule_string = params.get("rule_string", "")
        self.target_class = params.get("target_class", 2)
        self.probability = params.get("probability", 0.0)
        self.description = params.get("description", "")
        
        if self.rule_string:
            self._parse_rule(self.rule_string)
            
    def _parse_rule(self, rule_string: str):
        """
        Simple Parser for rules like: "FeatureA > 10.0 AND FeatureB <= 5.0"
        """
        parts = rule_string.split(" AND ")
        self.conditions = []
        
        for p in parts:
            p = p.strip()
            if "<=" in p:
                feat, val = p.split("<=")
                self.conditions.append({"feature": feat.strip(), "op": "<=", "val": float(val)})
            elif ">=" in p:
                feat, val = p.split(">=")
                self.conditions.append({"feature": feat.strip(), "op": ">=", "val": float(val)})
            elif "<" in p:
                feat, val = p.split("<")
                self.conditions.append({"feature": feat.strip(), "op": "<", "val": float(val)})
            elif ">" in p:
                feat, val = p.split(">")
                self.conditions.append({"feature": feat.strip(), "op": ">", "val": float(val)})
            elif "==" in p:
                feat, val = p.split("==")
                self.conditions.append({"feature": feat.strip(), "op": "==", "val": float(val)})
                
    def setup(self):
        # Nothing specific to setup; logic is stateless per bar
        pass
        
    def check_signal(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        Validate rule against LATEST bar.
        Note: The FeatureEngineer must have already run and columns must match.
        """
        if data.empty:
            return None
            
        row = data.iloc[-1]
        
        # Check all conditions
        for cond in self.conditions:
            feat = cond["feature"]
            op = cond["op"]
            val = cond["val"]
            
            if feat not in row:
                # If feature missing, we can't evaluate. Fail safe = No Signal.
                return None
            
            curr_val = row[feat]
            
            if op == "<=" and not (curr_val <= val): return None
            if op == ">=" and not (curr_val >= val): return None
            if op == "<" and not (curr_val < val): return None
            if op == ">" and not (curr_val > val): return None
            if op == "==" and not (curr_val == val): return None
            
        # If we got here, all conditions met!
        # Direction depends on Target Class
        # 2 = Explode (Long), -2 = Crash (Short)
        
        signal = None
        if self.target_class > 0:
            signal = {
                "signal": "long",
                "confidence": self.probability,
                "context": f"Matched Rule: {self.description}"
            }
        elif self.target_class < 0:
            # Only short if explicitly enabled in system, but edge allows it
            signal = {
                "signal": "short",
                "confidence": self.probability,
                "context": f"Matched Bear Rule: {self.description}"
            }
            
        return signal
