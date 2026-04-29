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
    # Regime-conditional weight gate: maps Engine E regime_summary labels
    # ("benign", "stressed", "crisis") to weight multipliers [0, 1].
    # Empty dict / None means the edge is unconditionally weighted (no gate).
    # Applied by SignalProcessor on top of alpha_settings edge_weights.
    regime_gate: Optional[Dict[str, float]] = None

    # ------------------------- Phase 1 tier system ------------------------- #
    # Three-layer architecture (see docs/Core/phase1_metalearner_design.md):
    #   tier="alpha"    → standalone signal that trades directly (factor t > 2)
    #   tier="feature"  → input to the meta-learner, not a direct trade signal
    #   tier="context"  → regime modifier, weights other edges
    # Machine-classified by `engines/engine_a_alpha/tier_classifier.py` from
    # factor-decomposition diagnostics. Default "feature" so newly-registered
    # edges feed the meta-learner until enough data accumulates to promote.
    tier: str = "feature"  # "alpha" | "feature" | "context"
    # ISO-8601 timestamp of the last TierClassifier run that touched this
    # spec. None means tier was never machine-classified (legacy edge or
    # newly-registered candidate awaiting first run).
    tier_last_updated: Optional[str] = None
    # How this edge participates in signal aggregation:
    #   "standalone" → tier=alpha edges contribute directly to the score
    #   "input"      → tier=feature edges feed the meta-learner
    #   "gate"       → tier=context edges modify other edges' weights
    # Default "input" matches default tier="feature".
    combination_role: str = "input"  # "standalone" | "input" | "gate"


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
                    regime_gate=row.get("regime_gate") or None,
                    tier=row.get("tier", "feature"),
                    tier_last_updated=row.get("tier_last_updated"),
                    combination_role=row.get("combination_role", "input"),
                )
                specs[spec.edge_id] = spec
            self._specs = specs
        except Exception:
            self._specs = {}

    def _save(self) -> None:
        rows = []
        for s in self._specs.values():
            row: Dict[str, Any] = {
                "edge_id": s.edge_id,
                "category": s.category,
                "module": s.module,
                "version": s.version,
                "params": s.params or {},
                "status": s.status,
            }
            if s.regime_gate:
                row["regime_gate"] = s.regime_gate
            # Phase 1 tier fields — only emit when set so legacy registries
            # without these keys round-trip cleanly. Default tier is "feature"
            # but we still emit it so the user can see what the system thinks.
            if s.tier:
                row["tier"] = s.tier
            if s.tier_last_updated:
                row["tier_last_updated"] = s.tier_last_updated
            if s.combination_role and s.combination_role != "input":
                # Only emit when non-default to keep the YAML clean.
                row["combination_role"] = s.combination_role
            rows.append(row)
        data = {"edges": rows}
        self.path.write_text(yaml.safe_dump(data, sort_keys=False))

    # --------------- public api ---------------- #
    def register(self, spec: EdgeSpec) -> None:
        self._specs[spec.edge_id] = spec
        self._save()

    def set_status(self, edge_id: str, status: str) -> None:
        if edge_id in self._specs:
            self._specs[edge_id].status = status
            self._save()

    def list(self, status: Optional[str] = None,
             statuses: Optional[List[str]] = None) -> List[EdgeSpec]:
        """List edges filtered by status. Pass `status="active"` for single
        match or `statuses=["active","paused"]` for multi-match (used for
        soft-pause behavior where paused edges keep trading at reduced weight).
        """
        vals = list(self._specs.values())
        if statuses:
            allowed = set(statuses)
            return [s for s in vals if s.status in allowed]
        if status:
            return [s for s in vals if s.status == status]
        return vals

    def list_tradeable(self) -> List[EdgeSpec]:
        """Return edges that should be loaded into the alpha pipeline: active
        edges trade at their config weight; paused edges trade at a reduced
        weight (soft-pause) so the revival gate can observe post-pause
        performance. Retired/failed/archived/candidate edges do NOT trade.
        """
        return self.list(statuses=["active", "paused"])

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

    def get_all_specs(self) -> List[EdgeSpec]:
        """Returns all registered edge specs regardless of status."""
        return list(self._specs.values())

    # Convenience to ensure a spec exists (idempotent upsert)
    def ensure(self, spec: EdgeSpec) -> None:
        """Idempotent upsert.

        For NEW specs (edge_id not yet in registry): register with the
        provided status (typically `active` from auto-register-on-import code).

        For EXISTING specs: merge non-status fields (category, module, version,
        params) if changed. **Do NOT touch the status field.** Status is
        owned by Engine F's lifecycle layer per the edges.yml Write Contract
        in PROJECT_CONTEXT.md ("F writes: status field changes").

        Same write-protection applies to the Phase 1 `tier`,
        `tier_last_updated`, and `combination_role` fields: those are owned
        by `engines.engine_a_alpha.tier_classifier.TierClassifier` and must
        not be stomped by import-time `ensure()` calls. Without this guard,
        every backtest startup would reset tier="feature" on edges the
        classifier had promoted to "alpha", silently undoing the
        classification — the same bug class as the 2026-04-25 status-stomp.

        Prior bug (fixed 2026-04-25): the previous implementation did
        `if spec.status: s.status = spec.status`, which let the auto-register-
        on-import code (e.g. momentum_edge.py:64) silently stomp the
        lifecycle's pause/retire decisions on every backtest startup. That
        broke autonomy invisibly — edges paused by Phase α would revert to
        active on the next module import, with the only "evidence" being
        that lifecycle_history.csv accumulated repeated pause events for the
        same edge across runs. Now status is write-protected here; only
        Engine F (via direct `set_status`) can transition it.
        """
        if spec.edge_id not in self._specs:
            self.register(spec)
        else:
            # Merge non-status, non-tier fields. Status is OWNED by lifecycle/
            # governance; tier fields are OWNED by TierClassifier.
            s = self._specs[spec.edge_id]
            s.category = spec.category or s.category
            s.module = spec.module or s.module
            s.version = spec.version or s.version
            s.params = spec.params or s.params
            # status: intentionally NOT updated — see docstring above
            # tier / tier_last_updated / combination_role: intentionally NOT
            # updated either — owned by TierClassifier
            self._save()