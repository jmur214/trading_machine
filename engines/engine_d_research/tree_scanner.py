
import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Any, Optional, Tuple
from sklearn.tree import DecisionTreeClassifier, _tree

logger = logging.getLogger("TREE_SCANNER")

class DecisionTreeScanner:
    """
    Tier 2 Research: The Hunter.
    
    Responsibilities:
    -----------------
    1. Label Data: Create multi-class targets (Explode, Crash, etc).
    2. Scan: Use Decision Trees to find predictive clusters.
    3. Extract: Convert Tree paths into human/machine readable Rules.
    """
    
    LABEL_MAP = {
        2: "EXPLODE",
        1: "BULLISH",
        0: "STABLE",
        -1: "BEARISH",
        -2: "CRASH"
    }
    
    def __init__(self, max_depth: int = 4, min_samples_leaf: int = 50, min_prob: float = 0.60):
        """
        :param max_depth: Max depth of the tree (limits complexity).
        :param min_samples_leaf: Min samples in a leaf to be considered valid (prevents overfitting).
        :param min_prob: Minimum probability of the dominant class to generate a rule.
        """
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.min_prob = min_prob
        self.model = None
        self.feature_names = []
        
    def generate_targets(self, df: pd.DataFrame, lookahead_days: int = 3) -> pd.DataFrame:
        """
        Generate Multi-Class Targets based on future returns.
        
        Labels:
            2 (EXPLODE): > +5%
            1 (BULLISH): > +1%
            0 (STABLE):  -1% to +1%
           -1 (BEARISH): < -1%
           -2 (CRASH):   < -5%
        """
        df = df.copy()
        
        # Calculate Future Return
        # Shift -N means getting value from N days in future
        df["Future_Close"] = df["Close"].shift(-lookahead_days)
        df["Future_Ret"] = (df["Future_Close"] / df["Close"]) - 1.0
        
        conditions = [
            (df["Future_Ret"] > 0.05),
            (df["Future_Ret"] > 0.01),
            (df["Future_Ret"] >= -0.01), # Between -1% and +1% part 1
            (df["Future_Ret"] > -0.05),  # Between -1% and -5%
            (df["Future_Ret"] <= -0.05)
        ]
        
        # We need strict buckets. 
        # Using pd.cut might be cleaner, but let's be explicit with logic.
        
        def assign_label(ret):
            if pd.isna(ret): return np.nan
            if ret > 0.05: return 2
            if ret > 0.01: return 1
            if ret >= -0.01: return 0
            if ret > -0.05: return -1
            return -2
            
        df["Target"] = df["Future_Ret"].apply(assign_label)
        
        return df

    def scan(self, feature_df: pd.DataFrame, target_col: str = "Target") -> List[Dict[str, Any]]:
        """
        Run the Scanner.
        1. Clean Data (Drop NaNs in features/target).
        2. Fit Tree.
        3. Extract Rules.
        """
        if feature_df.empty or target_col not in feature_df.columns:
            logger.warning("[TreeScanner] No data or missing Target column.")
            return []
            
        # 1. Preparation
        # Drop rows where target is NaN (last N days)
        data = feature_df.dropna(subset=[target_col]).copy()
        
        # Extract X and y
        # Drop non-feature columns (strings, dates, the target itself)
        # CRITICAL: Drop ABSOLUTE columns to prevents overfitting to specific price/volume levels
        drop_cols = [
            target_col, "Future_Close", "Future_Ret", "Date", "ticker", "symbol", 
            "Open", "High", "Low", "Close", "Volume", "trade_count", "vwap"
        ]
        
        # We only want columns that aren't in drop_cols
        valid_cols = [c for c in data.columns if c not in drop_cols and pd.api.types.is_numeric_dtype(data[c])]
        
        X = data[valid_cols]
        # Further NaN cleaning in X
        X = X.dropna()
        y = data.loc[X.index, target_col]
        
        if X.empty or y.empty:
            logger.warning("[TreeScanner] X or y is empty after cleaning.")
            return []
            
        if len(X) < self.min_samples_leaf * 2:
            logger.warning(f"[TreeScanner] Not enough samples ({len(X)}) for robust tree (need {self.min_samples_leaf * 2}).")
            return []

        self.feature_names = X.columns.tolist()
        
        # 2. Fit Model
        # Using 'entropy' to maximize information gain (purity)
        self.model = DecisionTreeClassifier(
            criterion="entropy",
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            random_state=42,
            class_weight="balanced" # Important for rare events like Crashes/Explosions
        )
        
        try:
            self.model.fit(X, y)
        except Exception as e:
            logger.error(f"[TreeScanner] Fit failed: {e}")
            return []
        
        # 3. Extract Rules
        rules = self._extract_rules()
        logger.info(f"[TreeScanner] Discovered {len(rules)} rules.")
        return rules
        
    def _extract_rules(self) -> List[Dict[str, Any]]:
        """
        Recursively traverse the tree to find high-probability leaf nodes.
        """
        if not self.model:
            return []
            
        tree_ = self.model.tree_
        feature_names = self.feature_names
        classes = self.model.classes_ # e.g. [-2, -1, 0, 1, 2]
        
        discovered_rules = []
        
        def recurse(node: int, current_rule: List[str]):
            # IF LEAF NODE
            if tree_.feature[node] == _tree.TREE_UNDEFINED:
                # Get value distribution
                # values is shape (1, n_classes) for this node
                counts = tree_.value[node][0]
                total_samples = counts.sum()
                
                if total_samples == 0: return

                # Calculate Probabilities
                probs = counts / total_samples
                
                # Find dominant class
                best_class_idx = np.argmax(probs)
                best_class_prob = probs[best_class_idx]
                best_class_label = classes[best_class_idx]
                
                # Filter: Must be high confidence and NOT "Stable" (0)
                if best_class_label == 0:
                    return # Skip stable
                
                if best_class_prob >= self.min_prob:
                    
                    human_label = self.LABEL_MAP.get(best_class_label, str(best_class_label))
                    
                    rule_entry = {
                        "rule_string": " AND ".join(current_rule),
                        "target_class": int(best_class_label),
                        "target_name": human_label,
                        "probability": float(best_class_prob),
                        "samples": int(total_samples),
                        "logic_map": current_rule # Could be structured better for parsing
                    }
                    discovered_rules.append(rule_entry)
                return
            
            # IF DECISION NODE
            name = feature_names[tree_.feature[node]]
            threshold = tree_.threshold[node]
            
            # Left child (<= threshold)
            recurse(tree_.children_left[node], current_rule + [f"{name} <= {threshold:.4f}"])
            
            # Right child (> threshold)
            recurse(tree_.children_right[node], current_rule + [f"{name} > {threshold:.4f}"])
            
        recurse(0, [])
        return discovered_rules

if __name__ == "__main__":
    # POC Test
    print("Testing Tree Scanner...")
    
    # 1. Create synthetic data
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=1000)
    df = pd.DataFrame(index=dates)
    df["Close"] = np.random.normal(100, 2, 1000).cumsum() + 100
    df["RSI"] = np.random.uniform(20, 80, 1000)
    df["Volume_Z"] = np.random.normal(0, 1, 1000)
    
    # Inject a pattern: If RSI < 30 and Vol_Z > 1.0 -> Explode (+6% next 3 days)
    # We simulate this by forcing future close up
    mask = (df["RSI"] < 35) & (df["Volume_Z"] > 0.5)
    # For these days, set Future Close (in df generation logic we can't cheat easily, 
    # so we'll hack the Target generation or the input Close series)
    
    # Let's just create 'Future_Ret' manually to verify scanner finds it
    df["Future_Close"] = df["Close"] # dummy
    df["Future_Ret"] = np.random.normal(0, 0.02, 1000) # Noise
    
    # The Pattern
    df.loc[mask, "Future_Ret"] = np.random.normal(0.08, 0.01, sum(mask)) # Explode
    
    # 2. Scanner
    scanner = DecisionTreeScanner(max_depth=3, min_prob=0.5)
    
    # Assign targets
    def simple_label(ret):
        if ret > 0.05: return 2
        return 0
    df["Target"] = df["Future_Ret"].apply(simple_label)
    
    print(f"Explosion Cases: {len(df[df['Target']==2])}")
    
    rules = scanner.scan(df)
    
    print("\n--- Discovered Rules ---")
    for r in rules:
        print(f"Target: {r['target_name']} | Prob: {r['probability']:.2%} | Samples: {r['samples']}")
        print(f"  Rule: {r['rule_string']}")
