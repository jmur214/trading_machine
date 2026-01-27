
import json
import logging
import subprocess
import sys
import os
import yaml
import pandas as pd
from datetime import datetime
from pathlib import Path

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
    """
    
    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root or os.getcwd())
        self.registry_path = self.project_root / "data" / "governor" / "edges.yml"
        self.wfo_script = self.project_root / "scripts" / "walk_forward_validation.py"
        
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

    def run_wfo_for_candidate(self, edge_id, params):
        """Calls the WFO script for a specific edge and param set."""
        cmd = [
            sys.executable, str(self.wfo_script),
            "--edge", edge_id,
            "--params", json.dumps(params)
        ]
        
        try:
            # We assume WFO writes a summary file we can read
            # But we also parse stdout for now since we just modified WFO to print the summary
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Check for success file
            summary_path = self.project_root / "data/research/wfo_summary.json"
            if summary_path.exists():
                with open(summary_path, "r") as f:
                    summary = json.load(f)
                
                # Verify it matches our edge
                if summary.get("edge") == edge_id:
                    return summary.get("passed", False), summary.get("avg_sharpe", 0.0), summary.get("specialist_type")
            
            log.warning(f"WFO did not produce summary for {edge_id}. Output:\n{result.stderr}")
            return False, 0.0, None
            
        except Exception as e:
            log.error(f"WFO Execution failed: {e}")
            return False, 0.0, None

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
