
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
from engines.engine_d_discovery.discovery_logger import DiscoveryLogger
from engines.engine_d_discovery.significance import apply_bh_fdr
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
        self.discovery_logger = DiscoveryLogger(
            log_path=str(self.root / "data" / "research" / "discovery_log.jsonl")
        )
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

        # ---- Pass 1: collect raw metrics (defer Gate 4 to BH-FDR pass) ----
        all_metrics: list = []
        for i, cand in enumerate(candidates):
            logger.info(f"--- Evaluating Candidate {i+1}/{len(candidates)}: {cand['edge_id']} ---")

            # 2. VALIDATE (Fitness + Robustness). Pass `significance_threshold=None`
            # so Gate 4 is deferred — we apply Benjamini-Hochberg FDR correction
            # across the whole batch below instead of per-candidate p<0.05.
            metrics = self.discovery.validate_candidate(
                cand, self.data_map, significance_threshold=None,
            )
            all_metrics.append(metrics)

        # ---- BH-FDR batch correction across all candidate p-values ----
        raw_p_values = [m.get("significance_p", 1.0) for m in all_metrics]
        bh_alpha = 0.05
        bh = apply_bh_fdr(raw_p_values, alpha=bh_alpha) if raw_p_values else None
        if bh is not None:
            logger.info(
                f"BH-FDR over {bh['n_tests']} candidates @ alpha={bh_alpha}: "
                f"{bh['n_rejected']} rejected, threshold={bh['threshold']:.4f}"
            )
            for i, m in enumerate(all_metrics):
                m["adjusted_significance_p"] = bh["adjusted_p_values"][i]
                m["bh_fdr_threshold"] = bh["threshold"]
                m["significance_threshold"] = bh_alpha
                # Re-apply Gate 4 with BH-corrected rejection.
                m["passed_all_gates"] = (
                    m.get("sharpe", 0.0) > 0
                    and m.get("robustness_survival", 0.0) >= 0.7
                    and bool(bh["reject_at_alpha"][i])
                )

        # ---- Pass 2: gating + WFO + promotion ----
        for i, cand in enumerate(candidates):
            metrics = all_metrics[i]
            sharpe = metrics.get("sharpe", 0.0)
            sortino = metrics.get("sortino", 0.0)
            survival = metrics.get("robustness_survival", 0.0)
            sig_p = metrics.get("significance_p", 1.0)
            adj_p = metrics.get("adjusted_significance_p", float("nan"))

            logger.info(
                f"   > Metrics: Sharpe={sharpe:.2f} | Sortino={sortino:.2f} | "
                f"Survival={survival*100:.0f}% | p={sig_p:.3f} | adj_p={adj_p:.3f}"
            )

            # Gating Logic (Tier 1 Filters)
            # Gate 1 is benchmark-relative: an edge that beats SPY buy-and-hold by at least
            # -0.3 Sharpe (i.e., within 0.3 of the benchmark) passes. Edges at Sharpe 0.5
            # during a bull market where SPY sits at 1.5 DESTROY value vs passive holding.
            passed = True
            rejection_reason = ""

            # Resolve eval window from the backtest data for benchmark lookup
            try:
                from core.benchmark import compute_benchmark_metrics
                first_ticker = list(self.data_map.keys())[0]
                start_dt = self.data_map[first_ticker].index[0]
                end_dt = self.data_map[first_ticker].index[-1]
                bm = compute_benchmark_metrics(
                    str(start_dt.date()), str(end_dt.date()),
                )
                bench_threshold = bm.gate_threshold(margin=0.3)
            except Exception as e:
                logger.warning(f"Benchmark gate unavailable ({e}), falling back to Sharpe < 0.5")
                bench_threshold = 0.5

            # Gate 4 result is the BH-corrected rejection from `apply_bh_fdr` —
            # an edge whose adjusted p-value cannot reject the null at FDR=0.05
            # is statistically indistinguishable from random shuffles of itself
            # AFTER accounting for the size of the batch we tested.
            sig_rejected = bh is not None and bool(bh["reject_at_alpha"][i])

            if sharpe < bench_threshold:
                passed = False
                rejection_reason = f"Sharpe {sharpe:.2f} < benchmark_threshold {bench_threshold:.2f}"
            elif sortino < 0.8:
                passed = False; rejection_reason = "Low Sortino"
            elif survival < 0.4:
                passed = False; rejection_reason = "Failed Robustness"
            elif not sig_rejected:
                passed = False
                rejection_reason = (
                    f"Failed BH-FDR significance (raw p={sig_p:.3f}, "
                    f"adj p={adj_p:.3f}, alpha=0.05)"
                )

            self.discovery_logger.log_validation(cand["edge_id"], metrics, promoted=False)

            if not passed:
                logger.info(f"   > REJECTED: {rejection_reason}")
                # Update registry to 'failed' so we don't loop forever
                cand["status"] = "failed"
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
