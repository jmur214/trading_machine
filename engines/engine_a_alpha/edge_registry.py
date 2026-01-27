# engines/engine_a_alpha/edge_registry.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class EdgeSpec:
    edge_id: str
    category: str
    module: str                 # e.g. "rsi_mean_reversion"
    version: str = "1.0.0"
    params: Optional[Dict[str, Any]] = None
    status: str = "active"      # "active" | "candidate" | "retired"


class EdgeRegistry:
    """
    Lightweight file-backed registry for edges.
    Stores specs in data/governor/edges.yml.

    NOTE: Backward compatible with current run_backtest.py flow where
          active edges are imported by module name under
          `engines.engine_a_alpha.edges.{module}`. This registry is here
          to support discovery/lifecycle; you can opt-in gradually.
    """

    def __init__(self, store_path: str | Path = "data/governor/edges.yml") -> None:
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._specs: Dict[str, EdgeSpec] = {}
        self._load()

    # ---------------- file i/o ---------------- #
    def _load(self) -> None:
        if not self.path.exists():
            self._specs = {}
            return
        try:
            data = yaml.safe_load(self.path.read_text()) or {}
            specs: Dict[str, EdgeSpec] = {}
            for row in data.get("edges", []):
                spec = EdgeSpec(
                    edge_id=row["edge_id"],
                    category=row.get("category", "other"),
                    module=row["module"],
                    version=row.get("version", "1.0.0"),
                    params=row.get("params") or {},
                    status=row.get("status", "active"),
                )
                specs[spec.edge_id] = spec
            self._specs = specs
        except Exception:
            self._specs = {}

    def _save(self) -> None:
        data = {
            "edges": [
                {
                    "edge_id": s.edge_id,
                    "category": s.category,
                    "module": s.module,
                    "version": s.version,
                    "params": s.params or {},
                    "status": s.status,
                }
                for s in self._specs.values()
            ]
        }
        self.path.write_text(yaml.safe_dump(data, sort_keys=False))

    # --------------- public api ---------------- #
    def register(self, spec: EdgeSpec) -> None:
        self._specs[spec.edge_id] = spec
        self._save()

    def set_status(self, edge_id: str, status: str) -> None:
        if edge_id in self._specs:
            self._specs[edge_id].status = status
            self._save()

    def list(self, status: Optional[str] = None) -> List[EdgeSpec]:
        vals = list(self._specs.values())
        if status:
            return [s for s in vals if s.status == status]
        return vals

    def list_modules(self, status: str = "active") -> List[str]:
        """
        Returns module names for edges with the specified status.
        """
        return [s.module for s in self._specs.values() if s.status == status]

    def list_active_modules(self) -> List[str]:
        """
        Returns module names for edges whose status == 'active'.
        Example output: ["rsi_mean_reversion", "bb_breakout"]
        """
        return self.list_modules(status="active")

    def get(self, edge_id: str) -> Optional[EdgeSpec]:
        return self._specs.get(edge_id)

    # Convenience to ensure a spec exists (idempotent upsert)
    def ensure(self, spec: EdgeSpec) -> None:
        if spec.edge_id not in self._specs:
            self.register(spec)
        else:
            # merge params/version if updated
            s = self._specs[spec.edge_id]
            s.category = spec.category or s.category
            s.module = spec.module or s.module
            s.version = spec.version or s.version
            s.params = spec.params or s.params
            # keep status as-is unless provided
            if spec.status:
                s.status = spec.status
            self._save()