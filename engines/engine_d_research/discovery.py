from __future__ import annotations
import random
import yaml
import pandas as pd
import logging
from pathlib import Path
from typing import List, Dict, Any, TypeVar, Type

# Import Template Interface from Engine A
from engines.engine_a_alpha.edge_template import EdgeTemplate
from engines.engine_a_alpha.edges.rsi_bounce import RSIBounceEdge
from engines.engine_a_alpha.edges.fundamental_value import ValueTrapEdge
from engines.engine_a_alpha.edges.fundamental_ratio import FundamentalRatioEdge
from engines.engine_a_alpha.edges.rule_based_edge import RuleBasedEdge

# Research Modules
from engines.engine_d_research.tree_scanner import DecisionTreeScanner
from engines.engine_d_research.feature_engineering import FeatureEngineer

class DiscoveryEngine:
    """
    Engine D (Discovery): The Evolutionary Lab.
    
    Responsibilities:
    1. Scan for valid EdgeTemplates.
    2. Generate N candidate configurations (Mutations).
    3. Save candidates to registry for validation.
    """
    
    def __init__(self, registry_path: str = "data/governor/edges.yml"):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.templates: List[Type[EdgeTemplate]] = [
            RSIBounceEdge,
            ValueTrapEdge,
            FundamentalRatioEdge
        ]

    def hunt(self, data_map: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """
        Phase 2 Core: The "Hunter".
        1. Calculate Features for all data.
        2. Run TreeScanner to find patterns.
        3. Convert Rules -> RuleBasedEdge Candidates.
        """
        logger = logging.getLogger("DISCOVERY")
        
        # 1. Feature Prep
        fe = FeatureEngineer()
        scanner = DecisionTreeScanner(max_depth=4, min_prob=0.55)
        
        # We need a massive DataFrame of ALL tickers to find universal patterns
        # Note: This is memory intensive. In prod, we might sample or use Dask.
        
        all_dfs = []
        for ticker, df in data_map.items():
            if df.empty: continue
            
            # Compute Features (if not already present)
            # Check if features exist to avoid re-compute? 
            # For now, safe compute
            f_df = fe.compute_all_features(df, pd.DataFrame()) 
            
            # Add Targets
            t_df = scanner.generate_targets(f_df)
            t_df["ticker"] = ticker # Keep track for debugging
            
            all_dfs.append(t_df)
            
        if not all_dfs:
            return []
            
        big_data = pd.concat(all_dfs).reset_index(drop=True)
        logger.info(f"Hunting on {len(big_data)} rows of data...")
        
        # 2. Scan
        rules = scanner.scan(big_data, target_col="Target")
        
        # 3. Convert to Candidates
        candidates = []
        
        for r in rules:
            # Hash rule string to get ID
            import hashlib
            rule_hash = hashlib.md5(r["rule_string"].encode()).hexdigest()[:8]
            cand_id = f"hunter_{rule_hash}"
            
            spec = {
                "edge_id": cand_id,
                "module": RuleBasedEdge.__module__,
                "class": RuleBasedEdge.__name__,
                "category": "discovered_rule",
                "params": {
                    "rule_string": r["rule_string"],
                    "target_class": r["target_class"],
                    "probability": r["probability"],
                    "description": f"Target {r['target_name']} ({r['probability']:.1%})"
                },
                "status": "candidate",
                "version": "1.0.0-auto",
                "origin": "tree_scanner"
            }
            candidates.append(spec)
            
        return candidates

    def generate_candidates(self, n_mutations: int = 5) -> List[Dict[str, Any]]:
        """
        Produce N candidate specs by sampling from Template hyperparameter spaces.
        Also produces Composite Genomes (Genetic Programming).
        """
        candidates = []
        
        # 1. Standard Template Mutation
        for template in self.templates:
            if template.__name__ == "CompositeEdge": 
                continue # Handled separately
                
            base_id = getattr(template, "EDGE_ID", "unknown_edge")
            
            for i in range(n_mutations):
                # 1. Mutate Parameters
                params = template.sample_params()
                
                # 2. Assign unique candidate ID
                suffix = "".join(random.choices("abcdef0123456789", k=4))
                candidate_id = f"{base_id}_mut_{suffix}"
                
                # 3. Create Spec
                spec = {
                    "edge_id": candidate_id,
                    "module": template.__module__,
                    "class": template.__name__,
                    "category": getattr(template, "EDGE_CATEGORY", "experimental"),
                    "params": params,
                    "status": "candidate", 
                    "version": "1.0.0-mut",
                    "origin": "discovery_engine"
                }
                candidates.append(spec)
        
        # 2. Composite Evolution (The "Genome" Approach)
        from engines.engine_a_alpha.edges.composite_edge import CompositeEdge
        for i in range(n_mutations):
            # Create a completely new random strategy (1-3 genes)
            n_genes = random.randint(1, 3) 
            genes = [self._create_random_gene() for _ in range(n_genes)]
            
            suffix = "".join(random.choices("abcdef0123456789", k=4))
            candidate_id = f"composite_gen1_{suffix}"
            
            direction = "long"
            rand = random.random()
            if rand < 0.10: # 10% chance of Short/Hedge Strategy
                direction = "short"
                candidate_id += "_short"
            elif rand < 0.20: # 10% chance of Market Neutral
                direction = "market_neutral"
                candidate_id += "_neutral"
                
            # Create a dummy probability for the params structure if needed, or stick to genome
            # RuleBasedEdge needs "rule_string", composite uses "genes"
            
            spec = {
                "edge_id": candidate_id,
                "module": CompositeEdge.__module__,
                "class": CompositeEdge.__name__,
                "category": "evolutionary",
                "params": {"genes": genes, "direction": direction},
                "status": "candidate",
                "version": "1.0.0-gen1",
                "origin": "discovery_engine_gp"
            }
            candidates.append(spec)
            
        return candidates

    def _create_random_gene(self) -> Dict[str, Any]:
        """
        Creates a random Gene (Condition) using expanded Phase 2/3 vocabulary.
        Categories:
        - Technical: RSI, Volatility, SMA Distance, SMA Cross, Donchian, Pivot, Momentum ROC
        - Fundamental: PE, PS, PFCF, Debt
        - Context: Regime
        - Cross-Sectional: Rank (Top/Bottom Percentile)
        """
        # 10% chance of Regime Context Gene
        if random.random() < 0.10:
            return {
                "type": "regime",
                "is": random.choice(["bull", "bear", "neutral_low_vol"]),
                "operator": "is"
            }

        gene_type = random.choice(["technical", "technical", "fundamental"]) # weights
        
        # Operator Selection (Standard vs Ranking)
        op_choices = ["less", "greater"]
        if random.random() < 0.30: # 30% chance of ranking
            op_choices += ["top_percentile", "bottom_percentile"]
        
        operator = random.choice(op_choices)
        
        gene = {"type": gene_type, "operator": operator}
        
        if gene_type == "technical":
            indicators = [
                "rsi", "volatility", "sma_dist_pct", 
                "sma_cross", "donchian_breakout", "pivot_position", "momentum_roc",
                "residual_momentum", "volatility_diff"
            ]
            indicator = random.choice(indicators)
            gene["indicator"] = indicator
            
            # Parameter Logic
            if indicator == "rsi":
                gene["window"] = 14
                gene["threshold"] = random.choice([30, 70]) if "percentile" not in operator else 50
            elif indicator == "volatility":
                gene["window"] = 20
                gene["threshold"] = 0.02
            elif indicator == "sma_dist_pct":
                gene["window"] = 50
                gene["threshold"] = 0.0
            elif indicator == "sma_cross":
                gene["window_fast"] = random.choice([10, 20])
                gene["window_slow"] = random.choice([50, 200])
                # Value is 1.0 or -1.0. 
                gene["threshold"] = 0.0
            elif indicator == "donchian_breakout":
                gene["window"] = 20
                gene["threshold"] = 0.0 # Positive = Breakout
            elif indicator == "pivot_position":
                # > 0 means above pivot
                gene["threshold"] = 0.0
            elif indicator == "momentum_roc":
                gene["window"] = random.choice([20, 60, 120])
                gene["threshold"] = 0.0
            elif indicator == "residual_momentum":
                gene["window"] = 60
                gene["threshold"] = 0.0
            elif indicator == "volatility_diff":
                # > 0 means vol expanding
                gene["threshold"] = 0.0

            # Adjust threshold for ranking operators (Percentiles)
            if "percentile" in operator:
                if operator == "top_percentile":
                    gene["threshold"] = random.choice([80, 90, 95])
                else:
                    gene["threshold"] = random.choice([5, 10, 20])

        elif gene_type == "fundamental":
            metric = random.choice(["PE_Ratio", "PS_Ratio", "PB_Ratio", "PFCF_Ratio", "Debt_to_Equity"])
            gene["metric"] = metric
            
            # Thresholds for standard compare
            if "percentile" in operator:
                gene["threshold"] = 20 if "bottom" in operator else 80
            else:
                if metric == "PE_Ratio": gene["threshold"] = 15
                elif metric == "PS_Ratio": gene["threshold"] = 2
                else: gene["threshold"] = 1.0
                
        return gene

    def get_queued_candidates(self, status: str = "candidate") -> List[Dict[str, Any]]:
        """
        Retrieve candidates from registry that are ready for validation.
        """
        if not self.registry_path.exists():
            return []
            
        try:
            data = yaml.safe_load(self.registry_path.read_text())
            edges = data.get("edges", [])
            return [e for e in edges if e.get("status") == status]
        except Exception as e:
            print(f"[DISCOVERY] Error reading registry: {e}")
            return []

    def save_candidates(self, candidates: List[Dict[str, Any]]) -> None:
        """
        Append candidates to the active edges.yml (or a separate staging registry).
        For now, we append to edges.yml but with status='candidate'.
        """
        if not self.registry_path.exists():
            existing = {"edges": []}
        else:
            try:
                existing = yaml.safe_load(self.registry_path.read_text()) or {"edges": []}
                # Handle legacy format where root might be missing or list
                if isinstance(existing, list):
                    existing = {"edges": existing}
            except Exception as e:
                print(f"[DISCOVERY] Error reading registry: {e}")
                existing = {"edges": []}

        # Deduplicate by ID
        current_map = {e.get("edge_id"): e for e in existing.get("edges", [])}
        
        new_count = 0
        update_count = 0
        for cand in candidates:
            cid = cand["edge_id"]
            if cid not in current_map:
                new_count += 1
            else:
                update_count += 1
            current_map[cid] = cand
        
        # Write back
        final_list = list(current_map.values())
        with self.registry_path.open("w") as f:
            yaml.dump({"edges": final_list}, f, sort_keys=False)
            
        print(f"[DISCOVERY] Registry saved. New: {new_count}, Updated: {update_count}. Path: {self.registry_path}")

    def validate_candidate(self, candidate_spec: Dict[str, Any], data_map: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """
        Run a quick backtest (fitness function) for a candidate.
        Returns metrics: {'sharpe': float, 'win_rate': float}
        """
        # 1. Instantiate Edge from spec
        try:
            from importlib import import_module
            mod = import_module(candidate_spec["module"])
            cls_ = getattr(mod, candidate_spec["class"])
            edge = cls_()
            if "params" in candidate_spec:
                edge.set_params(candidate_spec["params"])
                
            # 2. Setup Minimal Backtest
            from backtester.backtest_controller import BacktestController
            from engines.engine_a_alpha.alpha_engine import AlphaEngine
            from engines.engine_b_risk.risk_engine import RiskEngine
            from cockpit.logger import CockpitLogger
            
            # Temporary AlphaEngine with JUST this edge
            alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
            
            # Use strict Risk settings for validation
            risk = RiskEngine({"risk_per_trade_pct": 0.01})
            
            # Run simple backtest
            # Assumes data_map is already loaded/normalized
            # Create a dummy logger that suppresses file IO for speed?
            # For now, normal logger to tmp
            logger = CockpitLogger(out_dir="/tmp/discovery_validation", flush_each_fill=False)
            
            # Determine start/end from data
            if not data_map:
                return {"sharpe": 0.0, "win_rate": 0.0}
                
            first_ticker = list(data_map.keys())[0]
            start_date = data_map[first_ticker].index[0].isoformat()
            end_date = data_map[first_ticker].index[-1].isoformat()
            
            controller = BacktestController(
                data_map=data_map,
                alpha_engine=alpha,
                risk_engine=risk,
                cockpit_logger=logger,
                exec_params={"slippage_bps": 5.0},
                initial_capital=100_000,
                batch_flush_interval=99999
            )
            
            history = controller.run(start_date, end_date)
            
            # 3. Calculate Fitness
            if not history:
                return {"sharpe": 0.0, "win_rate": 0.0}
                
            # Extract PnL curve
            # 3. Calculate Fitness
            if not history:
                return {"sharpe": 0.0, "win_rate": 0.0}
                
            equity_curve = pd.Series([h["equity"] for h in history])
            
            # Use unified MetricsEngine
            from engines.engine_d_research.metrics_engine import MetricsEngine
            metrics = MetricsEngine.calculate_all(equity_curve)
            
            sharpe = metrics["Sharpe"]
            sortino = metrics["Sortino"]
            cagr = metrics["CAGR %"]
                
            # 4. PBO Check (Optional but recommended for Tier 1)
            # We run a quick check with limited paths (e.g. 10) for speed during discovery.
            # Full robustness check (50+ paths) happens later in "Promotion".
            pbo_score = 0.0
            survival_rate = 0.0
            
            try:
                from engines.engine_d_research.robustness import RobustnessTester
                tester = RobustnessTester()
                
                # We need a wrapper function that takes a data_map and returns {'sharpe': float}
                # using the PRE-INSTANTIATED edge and controller settings
                def strategy_wrapper(dm):
                    # Re-instantiate controller for the synthetic data
                    # (Note: this is expensive, so we limit paths)
                    t_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
                    t_risk = RiskEngine({"risk_per_trade_pct": 0.01})
                    t_logger = CockpitLogger(out_dir="/tmp/pbo_check", flush_each_fill=False)
                    
                    # Assume single ticker for robustness check for now
                    t_first = list(dm.keys())[0]
                    t_start = dm[t_first].index[0].isoformat()
                    t_end = dm[t_first].index[-1].isoformat()
                    
                    tc = BacktestController(data_map=dm, alpha_engine=t_alpha, risk_engine=t_risk, 
                                          cockpit_logger=t_logger, initial_capital=100000, batch_flush_interval=99999)
                    th = tc.run(t_start, t_end)
                    if not th: return {"sharpe": -1.0}
                    te = [x["equity"] for x in th]
                    if len(te) < 2: return {"sharpe": -1.0}
                    tr = pd.Series(te).pct_change().dropna()
                    if tr.std() == 0: return {"sharpe": 0.0}
                    return {"sharpe": tr.mean()/tr.std()*np.sqrt(252)}

                # Run on JUST the first ticker data to save time
                first_key = list(data_map.keys())[0]
                pbo_res = tester.calculate_pbo(strategy_wrapper, data_map[first_key], n_paths=5) # 5 paths for speed
                survival_rate = pbo_res.get("survival_rate", 0.0)
                
            except Exception as e:
                print(f"[DISCOVERY] PBO Check failed: {e}")

            return {
                "sharpe": float(sharpe), 
                "sortino": float(sortino),
                "robustness_survival": float(survival_rate)
            }
            
        except Exception as e:
            print(f"[DISCOVERY] Validation failed for {candidate_spec['edge_id']}: {e}")
            return {"sharpe": 0.0}

if __name__ == "__main__":
    # Test run
    disc = DiscoveryEngine()
    cands = disc.generate_candidates(n_mutations=3)
    print(f"Generated {len(cands)} candidates.")
    # In main block we don't have data_map, so we skip validation call
    disc.save_candidates(cands)
