from engines.engine_a_alpha.edge_template import EdgeTemplate
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd

class RuleBasedEdge(EdgeTemplate):
    """
    Tier 2 Edge: The Machine-Discovered Logic.

    Responsibilities:
    -----------------
    1. Executes specific Logical Rules discovered by DiscoveryEngine (TreeScanner).
    2. Example Rule: "RSI > 50 AND PE < 20".
    3. Designed to be serialized/deserialized easily from JSON/YAML.

    Feature self-sufficiency (2026-05-07 fix for the HIGH finding in
    health_check.md "RuleBasedEdge requires FeatureEngineer-computed
    columns absent from validation data_map"):

    Pre-fix path: ``check_signal()`` reads ``row[feat]`` for engineered
    features (RSI_14, Vol_ZScore, etc.) but the validation ``data_map``
    that ``validate_candidate`` passes to AlphaEngine has only OHLCV.
    Result: ``feat not in row → return None`` on every bar → flat
    equity curve → Sharpe = 0.00 → Discovery cycle never promotes any
    rule TreeScanner discovers.

    Post-fix path: ``compute_signals`` runs
    ``FeatureEngineer.compute_all_features()`` on the per-ticker
    DataFrame inline before invoking ``check_signal()``. Cached by
    ``(ticker, last_bar_index)`` so growing-DataFrame backtesting
    pattern doesn't recompute the full history every bar.
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
        # Per-ticker feature cache, keyed by (ticker, last_index_of_passed_df).
        # The FeatureEngineer's ~100ms-per-call cost makes per-bar recomputation
        # prohibitive (250 bars × 100 tickers × N edges = minutes per backtest).
        self._feat_cache: Dict[Tuple[str, Any], pd.DataFrame] = {}
            
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

    def compute_signals(self, data_map: Dict[str, pd.DataFrame], as_of=None) -> Dict[str, float]:
        """Wrap `check_signal()` per ticker so the standard signal_collector
        interface returns a {ticker: score} mapping.

        Self-sufficiency: runs FeatureEngineer on each ticker's OHLCV
        inline so engineered features (RSI_14, Vol_ZScore, etc.) the
        rule references are present when check_signal evaluates. Cached
        by (ticker, last-bar-index) — recomputed only when the
        backtester's growing-DataFrame extends.
        """
        scores: Dict[str, float] = {}
        for t, df in data_map.items():
            enriched = self._enrich_with_features(t, df)
            sig = self.check_signal(enriched)
            if sig is None:
                continue
            direction = 1.0 if sig.get("signal") == "long" else -1.0
            confidence = float(sig.get("confidence", 0.0))
            scores[t] = direction * confidence
        return scores

    def _enrich_with_features(self, ticker: str, df: pd.DataFrame) -> pd.DataFrame:
        """Run FeatureEngineer on this ticker's OHLCV; cache by (ticker, last_index).

        Falls back to the input DataFrame on any feature-engineering
        error so a single ticker's data quirk doesn't kill all signals
        for the bar — check_signal's own missing-feature handling will
        still return None safely.
        """
        if df is None or df.empty:
            return df
        # Cache key: ticker + last bar index. When the backtester
        # advances the DataFrame, last_idx changes → cache miss → recompute.
        try:
            last_idx = df.index[-1]
        except Exception:
            last_idx = None
        cache_key = (ticker, last_idx)
        cached = self._feat_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            from engines.engine_d_discovery.feature_engineering import FeatureEngineer
            fe = FeatureEngineer()
            enriched = fe.compute_all_features(
                ohlc_df=df,
                fund_df=pd.DataFrame(),  # rules referencing fundamentals fall back to row.get → None
            )
        except Exception:
            # Fail-safe: return the original df so check_signal's
            # `if feat not in row: return None` still produces a clean
            # no-signal result rather than crashing the bar.
            enriched = df
        self._feat_cache[cache_key] = enriched
        return enriched

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
