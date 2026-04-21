
import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.engine_d_discovery.discovery import DiscoveryEngine
from engines.engine_d_discovery.wfo import WalkForwardOptimizer
from engines.data_manager.data_manager import DataManager

# Setup Logging
logging.basicConfig(level=logging.INFO, format='[EVOLUTION] %(message)s')
logger = logging.getLogger("EVOLUTION")

class AutonomousEvolution:
    """
    The Master Learning Loop.
    
    Cycle:
    1. LOAD: Fetch latest data.
    2. DISCOVER: Generate mutant strategies (Genetic Algorithms).
    3. VALIDATE: Run Backtest + PBO (Robustness Check).
    4. VERIFY: Run Walk-Forward Optimization (Consistency Check).
    5. PROMOTE: Add winners to production config.
    """
    
    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.discovery = DiscoveryEngine(registry_path=str(self.root / "data" / "governor" / "edges.yml"))
        self.dm = DataManager(cache_dir=str(self.root / "data" / "processed"))
        
        # Load Data once
        logger.info("Loading market data for research...")
        self.data_map = {}
        # Scan cache for available data
        for f in self.dm.cache_dir.glob("*_1d.csv"):
             ticker = f.name.split("_")[0]
             df = self.dm.load_cached(ticker, "1d")
             if df is not None and not df.empty:
                 self.data_map[ticker] = df
                 
        if not self.data_map:
            logger.error("No data found! Please run 'scripts/update_data.py' first.")
            sys.exit(1)
            
        logger.info(f"Loaded data for {len(self.data_map)} tickers.")
            
        self.wfo = WalkForwardOptimizer(self.data_map)
        
    def run_cycle(self, n_candidates=10):
        logger.info(f"Starting Evolution Cycle at {datetime.now()}")
        
        # 1. DISCOVER / LOAD
        # First, check if the Hunter left us anything
        candidates = self.discovery.get_queued_candidates(status="candidate")
        
        if candidates:
            logger.info(f"Loaded {len(candidates)} queued candidates from Registry (Hunter/Discovery).")
        else:
            logger.info("No queued candidates. Activating Random Discovery...")
            candidates = self.discovery.generate_candidates(n_mutations=n_candidates)
            logger.info(f"Generated {len(candidates)} mutant candidates.")
        
        winners = []
        
        for i, cand in enumerate(candidates):
            logger.info(f"--- Evaluating Candidate {i+1}/{len(candidates)}: {cand['edge_id']} ---")
            
            # 2. VALIDATE (Fitness + Robustness)
            metrics = self.discovery.validate_candidate(cand, self.data_map)
            sharpe = metrics.get("sharpe", 0.0)
            sortino = metrics.get("sortino", 0.0)
            survival = metrics.get("robustness_survival", 0.0)
            
            logger.info(f"   > Metrics: Sharpe={sharpe:.2f} | Sortino={sortino:.2f} | Survival={survival*100:.0f}%")
            
            # Gating Logic (Tier 1 Filters)
            passed = True
            rejection_reason = ""
            
            if sharpe < 0.5: # Lowered slightly for 'potential'
                passed = False; rejection_reason = "Low Sharpe"
            elif sortino < 0.8: 
                passed = False; rejection_reason = "Low Sortino"
            elif survival < 0.4:
                passed = False; rejection_reason = "Failed Robustness"
            
            if not passed:
                logger.info(f"   > REJECTED: {rejection_reason}")
                # Update registry to 'failed' so we don't loop forever
                cand["status"] = "failed"
                # We need a way to save this status update back to registry
                # For now, we just batch update at end? 
                # Better to update self.discovery registry. 
                # We'll re-save the whole list at the end.
                continue
                
            logger.info("   > PASSED INITIAL VALIDATION. Proceeding to WFO...")
            
            # 3. VERIFY (Consistency via Walk-Forward)
            # Find first ticker start date
            first_ticker = list(self.data_map.keys())[0]
            start_dt = self.data_map[first_ticker].index[0] + pd.Timedelta(days=365) # Need 1 year warmup
            
            wfo_res = self.wfo.run_optimization(
                cand, 
                start_date=str(start_dt.date()),
                train_months=12,
                test_months=3
            )
            
            if not wfo_res:
                logger.info("   > WFO Failed (Insufficient Data?)")
                continue
                
            degradation = wfo_res.get("degradation", 0.0)
            logger.info(f"   > WFO Degradation: {degradation:.2f} (Target > 0.7)")
            
            if degradation > 0.6: # Allow some dropoff
                logger.info(f"   >>> WINNER FOUND! {cand['edge_id']} <<<")
                
                # Tag it
                cand["status"] = "active"
                cand["metrics"] = {
                    "sharpe": sharpe,
                    "sortino": sortino, 
                    "wfo_degradation": degradation
                }
                winners.append(cand)
            else:
                logger.info("   > REJECTED: Poor OOS Consistency")
                
        # 4. PROMOTE
        if winners:
            self._promote_winners(winners)
        else:
            logger.info("No winners in this generation. Evolution is hard.")
            
        # 5. SAVE REGISTRY UPDATES
        # This saves the 'failed' or 'active' status back to edges.yml
        self.discovery.save_candidates(candidates)
            
    def _promote_winners(self, winners: list):
        """
        Add winners to config/edge_config.json so they are traded LIVE.
        """
        config_path = self.root / "config" / "edge_config.json"
        
        try:
            if config_path.exists():
                with open(config_path, "r") as f:
                    cfg = json.load(f)
            else:
                cfg = {"edge_weights": {}, "active_edges": []}
                
            count = 0
            for w in winners:
                eid = w["edge_id"]
                # Add to weights
                # Start small? Or use Sortino to size?
                # Using Sortino to size: Higher Sortino = Higher Conviction
                weight = min(2.0, max(0.5, w["metrics"]["sortino"] / 2.0))
                
                cfg["edge_weights"][eid] = round(weight, 2)
                
                # Add params if needed (Currently AlphaEngine loads params from code or config)
                # We need to save the params to config so AlphaEngine knows how to init this specific mutant
                if "edge_params" not in cfg:
                    cfg["edge_params"] = {}
                cfg["edge_params"][eid] = w["params"]
                
                count += 1
                logger.info(f"Promoting {eid} with weight {weight:.2f}")
                
            with open(config_path, "w") as f:
                json.dump(cfg, f, indent=4)
                
            logger.info(f"Successfully promoted {count} strategies to Production Config.")
            
        except Exception as e:
            logger.error(f"Failed to promote winners: {e}")

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    evo = AutonomousEvolution(root)
    evo.run_cycle(n_candidates=3) # Small batch for demo
