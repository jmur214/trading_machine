"""
Discovery activity logger.

Logs all discovery activity to a JSONL file for auditability:
- Generations, fitness scores, promotions/rejections
- Feature importances from LightGBM screening
- GA population statistics (diversity, avg fitness, best fitness)
- Validation gate results per candidate
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("DISCOVERY_LOG")


class DiscoveryLogger:
    """Append-only JSONL logger for discovery cycle events."""

    def __init__(self, log_path: str = "data/research/discovery_log.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, event: Dict[str, Any]) -> None:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            with self.log_path.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write discovery log: {e}")

    def log_hunt(
        self,
        n_rules: int,
        cv_score: float,
        feature_importances: Optional[Dict[str, float]] = None,
        screened_features: Optional[List[str]] = None,
    ) -> None:
        self._write({
            "event": "hunt",
            "n_rules_found": n_rules,
            "cv_score": cv_score,
            "top_features": screened_features or [],
            "feature_importances": feature_importances or {},
        })

    def log_ga_generation(
        self,
        generation: int,
        population_size: int,
        elite_count: int,
        best_fitness: float,
        avg_fitness: float,
        n_unevaluated: int,
    ) -> None:
        self._write({
            "event": "ga_generation",
            "generation": generation,
            "population_size": population_size,
            "elite_count": elite_count,
            "best_fitness": best_fitness,
            "avg_fitness": avg_fitness,
            "n_unevaluated": n_unevaluated,
        })

    def log_validation(
        self,
        edge_id: str,
        result: Dict[str, Any],
        promoted: bool,
    ) -> None:
        self._write({
            "event": "validation",
            "edge_id": edge_id,
            "sharpe": result.get("sharpe", 0.0),
            "robustness_survival": result.get("robustness_survival", 0.0),
            "wfo_degradation": result.get("wfo_degradation", 0.0),
            "significance_p": result.get("significance_p", 1.0),
            "adjusted_significance_p": result.get("adjusted_significance_p"),
            "bh_fdr_threshold": result.get("bh_fdr_threshold"),
            "significance_threshold": result.get("significance_threshold"),
            "universe_b_sharpe": result.get("universe_b_sharpe"),
            "universe_b_n_tickers": result.get("universe_b_n_tickers"),
            "passed_all_gates": result.get("passed_all_gates", False),
            "promoted": promoted,
        })

    def log_cycle_summary(
        self,
        n_hunt_candidates: int,
        n_mutation_candidates: int,
        n_validated: int,
        n_promoted: int,
        n_failed: int,
    ) -> None:
        self._write({
            "event": "cycle_summary",
            "hunt_candidates": n_hunt_candidates,
            "mutation_candidates": n_mutation_candidates,
            "validated": n_validated,
            "promoted": n_promoted,
            "failed": n_failed,
        })
