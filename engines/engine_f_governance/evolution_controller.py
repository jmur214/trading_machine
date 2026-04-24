
import json
import logging
import sys
import os
import yaml
import pandas as pd
from pathlib import Path
from typing import Dict, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("evolution.log")
    ]
)
log = logging.getLogger("EvolutionController")

class EvolutionController:
    """
    Autonomous Evolution Controller
    -------------------------------
    Responsible for:
    1. Reading candidates from the Genome Registry (edges.yml).
    2. Running Walk-Forward Optimization (WFO) on each candidate.
    3. Promoting winners to 'active' status.
    4. Disabling losers.

    History note: previously subprocessed to `scripts/walk_forward_validation.py`
    which does NOT exist — every candidate was silently failing. Rewired
    2026-04-24 to call `engines.engine_d_discovery.wfo.WalkForwardOptimizer`
    directly, matching the pattern in `scripts/run_evolution_cycle.py`.
    """

    def __init__(self, project_root: str = None, data_map: Optional[Dict] = None):
        self.project_root = Path(project_root or os.getcwd())
        self.registry_path = self.project_root / "data" / "governor" / "edges.yml"
        # data_map is required for WFO; caller must supply or we lazy-load
        self.data_map = data_map
        self._wfo = None  # instantiated lazily once data_map is loaded
        
    def run_cycle(self):
        log.info("Starting Evolution Cycle...")
        
        edges = self.load_edges()
        candidates = [e for e in edges if e.get("status") == "candidate"]
        
        if not candidates:
            log.info("No candidates found in registry. Run Discovery first.")
            return

        log.info(f"Found {len(candidates)} candidates to validate.")
        
        updated_count = 0
        for edge_spec in candidates:
            edge_id = edge_spec["edge_id"]
            params = edge_spec.get("params", {})
            
            log.info(f"🧬 Validating Candidate: {edge_id}")
            
            # Run WFO
            success, avg_sharpe, specialist_type = self.run_wfo_for_candidate(edge_id, params)
            
            # Update Status
            if success:
                log.info(f"🏆 PROMOTION: {edge_id} passes with Sharpe {avg_sharpe:.2f}")
                if specialist_type:
                    log.info(f"   typeset as {specialist_type} specialist")
                    params["regime_filter"] = specialist_type

                edge_spec["status"] = "active"
                self.update_production_config(edge_id, params)
            else:
                log.info(f"💀 REJECTION: {edge_id} fails with Sharpe {avg_sharpe:.2f}")
                edge_spec["status"] = "failed"
                
            updated_count += 1
            
        # Save updates back to registry
        self.save_edges(edges)
        log.info(f"Evolution Cycle Complete. Processed {updated_count} candidates.")

    def load_edges(self):
        if not self.registry_path.exists():
            return []
        try:
            with open(self.registry_path, "r") as f:
                data = yaml.safe_load(f) or {}
                return data.get("edges", [])
        except Exception as e:
            log.error(f"Error loading edges: {e}")
            return []

    def save_edges(self, edges):
        try:
            with open(self.registry_path, "w") as f:
                yaml.dump({"edges": edges}, f, sort_keys=False)
        except Exception as e:
            log.error(f"Error saving edges: {e}")

    def _ensure_data_and_wfo(self):
        """Lazy-load data_map and WalkForwardOptimizer. Called only when validating."""
        if self._wfo is not None:
            return
        if self.data_map is None:
            # Load from processed/ directory as run_evolution_cycle.py does
            from engines.data_manager.data_manager import DataManager
            dm = DataManager(cache_dir=str(self.project_root / "data" / "processed"))
            self.data_map = {}
            for f in dm.cache_dir.glob("*_1d.csv"):
                ticker = f.name.split("_")[0]
                df = dm.load_cached(ticker, "1d")
                if df is not None and not df.empty:
                    self.data_map[ticker] = df
            if not self.data_map:
                raise RuntimeError(
                    "EvolutionController.run_cycle requires data in data/processed/. "
                    "Run scripts/update_data.py first."
                )
        from engines.engine_d_discovery.wfo import WalkForwardOptimizer
        self._wfo = WalkForwardOptimizer(self.data_map)

    def run_wfo_for_candidate(self, edge_id: str, params: dict) -> Tuple[bool, float, Optional[str]]:
        """Run WFO for a candidate using WalkForwardOptimizer directly.

        Returns (passed, avg_sharpe, specialist_type). passed is True if
        OOS Sharpe beats benchmark_threshold AND degradation > 0.6.
        """
        try:
            self._ensure_data_and_wfo()
        except Exception as e:
            log.error(f"Could not load data for WFO: {e}")
            return False, 0.0, None

        # We need the full candidate spec (module + class) to run WFO.
        # Look it up from the registry.
        try:
            edges = self.load_edges()
            spec = next((e for e in edges if e.get("edge_id") == edge_id), None)
            if spec is None:
                log.warning(f"No registry entry for {edge_id}; cannot run WFO")
                return False, 0.0, None
            # Apply the param override for this specific run
            spec = dict(spec)
            spec["params"] = params or spec.get("params", {})
        except Exception as e:
            log.error(f"Registry lookup failed for {edge_id}: {e}")
            return False, 0.0, None

        try:
            first_ticker = list(self.data_map.keys())[0]
            start_dt = self.data_map[first_ticker].index[0] + pd.Timedelta(days=365)
            wfo_res = self._wfo.run_optimization(
                spec,
                start_date=str(start_dt.date()),
                train_months=12,
                test_months=3,
            )
        except Exception as e:
            log.error(f"WFO Execution failed for {edge_id}: {e}")
            return False, 0.0, None

        if not wfo_res:
            return False, 0.0, None

        oos_sharpe = float(wfo_res.get("oos_sharpe", 0.0))
        degradation = float(wfo_res.get("degradation", 0.0))

        # Benchmark-relative pass: OOS Sharpe must beat SPY - 0.3 over the eval window
        try:
            from core.benchmark import compute_benchmark_metrics
            end_dt = self.data_map[first_ticker].index[-1]
            bm = compute_benchmark_metrics(str(start_dt.date()), str(end_dt.date()))
            bench_threshold = bm.gate_threshold(margin=0.3)
        except Exception as e:
            log.warning(f"Benchmark unavailable ({e}); falling back to oos_sharpe > 0.5")
            bench_threshold = 0.5

        passed = oos_sharpe >= bench_threshold and degradation > 0.6
        specialist_type = None  # reserved for regime-specialist classification
        log.info(
            f"[WFO] {edge_id}: oos_sharpe={oos_sharpe:.2f}  "
            f"bench_threshold={bench_threshold:.2f}  degradation={degradation:.2f}  "
            f"passed={passed}"
        )
        return passed, oos_sharpe, specialist_type

    def update_production_config(self, edge_id: str, new_params: dict):
        """Updates alpha_settings.prod.json to include the new 'active' edge parameters."""
        config_path = self.project_root / "config" / "alpha_settings.prod.json"
        if not config_path.exists():
            log.error("Production config not found.")
            return
            
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            if 'edge_params' not in config:
                config['edge_params'] = {}
            
            config['edge_params'][edge_id] = new_params
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
                
        except Exception as e:
            log.error(f"Failed to update production config: {e}")

if __name__ == "__main__":
    controller = EvolutionController()
    controller.run_cycle()
