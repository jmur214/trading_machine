"""
engines/engine_a_alpha/tier_classifier.py
==========================================
Layer 2 of the Phase 1 three-layer architecture: machine-classified
tier assignments for every edge in the registry.

Tier rule (from `docs/Core/phase1_metalearner_design.md`):

    if factor_tstat > 2 AND alpha_annualized > 0.02:
        tier = "alpha"          # standalone — trades directly
    elif 0 < factor_tstat <= 2:
        tier = "feature"        # informative but not standalone
    elif factor_tstat <= 0 AND |regime_correlation| > 0.3:
        tier = "context"        # regime modifier
    elif factor_tstat < -2 AND days_negative >= 90:
        tier = "retire-eligible" → routed to Layer 1 (lifecycle)
    else:
        tier = "feature"        # default — keep as input until evidence accumulates

This module:
  - Reads per-edge return streams from a recent backtest's trades.csv
  - Runs FF5+Mom regression for each edge (uses core/factor_decomposition)
  - Applies the rule above
  - Updates `edges.yml` via EdgeRegistry (idempotent)
  - Logs every reclassification event

The "regime correlation" branch is currently a no-op — we don't have a
structured regime-correlation diagnostic yet. Edges with t<=0 default
to "feature" (informative-as-input) until that diagnostic ships. When
it does, the rule kicks in without code changes here.

Integration point: `LifecycleManager` reads `tier="retire-eligible"`
on its next pass and triggers the existing pause→retire path.

This module is profile-INDEPENDENT — it never reads `FitnessConfig`.
Tier classification belongs to Layer 2; profile preference belongs to
Layer 3. Mixing the two would mean profile changes could secretly kill
edges, which is exactly the failure mode we're avoiding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.factor_decomposition import (
    FactorDecomp,
    load_factor_data,
    regress_returns_on_factors,
)
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec

ROOT = Path(__file__).resolve().parents[2]

# Thresholds match Gate 6's defaults; consolidated here so tier rule and
# gauntlet gate stay in lockstep.
DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER = 2.0
DEFAULT_ALPHA_ANNUAL_FOR_ALPHA_TIER = 0.02
DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE = -2.0
DEFAULT_DAYS_NEGATIVE_FOR_RETIRE = 90


@dataclass(frozen=True)
class TierDecision:
    """Result of classifying one edge."""
    edge_id: str
    new_tier: str                # "alpha" | "feature" | "context" | "retire-eligible"
    new_combination_role: str    # "standalone" | "input" | "gate"
    factor_tstat: Optional[float]
    factor_alpha_annualized: Optional[float]
    n_obs: int
    reason: str
    prior_tier: str

    @property
    def changed(self) -> bool:
        return self.new_tier != self.prior_tier


class TierClassifier:
    """Classifies every edge in the registry into alpha / feature / context.

    Intended usage:
      1. After a backtest, run `classify_from_trades(trade_log_path)` to
         compute tiers from per-edge return streams.
      2. The classifier is idempotent — same inputs produce the same
         output. Multiple runs in a row are safe.
      3. Every reclassification (tier change) is returned in the
         `decisions` list and logged to stdout. The caller can persist
         these to a structured log if desired (future work).
    """

    def __init__(
        self,
        registry: Optional[EdgeRegistry] = None,
        alpha_tstat_threshold: float = DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER,
        alpha_annual_threshold: float = DEFAULT_ALPHA_ANNUAL_FOR_ALPHA_TIER,
        retire_tstat_threshold: float = DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE,
        min_observations: int = 30,
    ):
        self.registry = registry or EdgeRegistry(
            store_path=str(ROOT / "data" / "governor" / "edges.yml")
        )
        self.alpha_tstat_threshold = float(alpha_tstat_threshold)
        self.alpha_annual_threshold = float(alpha_annual_threshold)
        self.retire_tstat_threshold = float(retire_tstat_threshold)
        self.min_observations = int(min_observations)

    # ----------------------------------------------------------------- rule

    def _classify_from_decomp(
        self,
        edge_id: str,
        decomp: Optional[FactorDecomp],
        prior_tier: str,
    ) -> TierDecision:
        """Apply the tier rule to a single edge's factor-decomp result."""
        if decomp is None:
            # Insufficient data — keep as default "feature" until enough
            # observations accumulate. Don't promote, don't retire.
            return TierDecision(
                edge_id=edge_id,
                new_tier="feature",
                new_combination_role="input",
                factor_tstat=None,
                factor_alpha_annualized=None,
                n_obs=0,
                reason="insufficient observations for factor decomp",
                prior_tier=prior_tier,
            )

        t = decomp.alpha_tstat
        alpha = decomp.alpha_annualized

        # Branch 1: real alpha — t > 2 AND alpha > 2%
        if t > self.alpha_tstat_threshold and alpha > self.alpha_annual_threshold:
            return TierDecision(
                edge_id=edge_id, new_tier="alpha", new_combination_role="standalone",
                factor_tstat=t, factor_alpha_annualized=alpha, n_obs=decomp.n_obs,
                reason=f"factor t={t:+.2f}>{self.alpha_tstat_threshold}, "
                       f"alpha={100*alpha:+.1f}%>{100*self.alpha_annual_threshold:.1f}%",
                prior_tier=prior_tier,
            )

        # Branch 2: significantly destroying value — flag for lifecycle
        # to consider retirement. Still classified as "retire-eligible"
        # so other code can consume the signal; LifecycleManager owns
        # the actual status transition.
        if t < self.retire_tstat_threshold:
            return TierDecision(
                edge_id=edge_id,
                new_tier="retire-eligible",
                new_combination_role="input",
                factor_tstat=t, factor_alpha_annualized=alpha, n_obs=decomp.n_obs,
                reason=f"factor t={t:+.2f}<{self.retire_tstat_threshold} "
                       f"(significantly destroying value)",
                prior_tier=prior_tier,
            )

        # Branch 3: marginal — informative but not standalone alpha
        # (covers 0 < t <= 2 AND alpha-tier conditions not all met)
        if t > 0:
            return TierDecision(
                edge_id=edge_id, new_tier="feature", new_combination_role="input",
                factor_tstat=t, factor_alpha_annualized=alpha, n_obs=decomp.n_obs,
                reason=f"factor t={t:+.2f}: informative input, not standalone",
                prior_tier=prior_tier,
            )

        # Branch 4: t <= 0 with non-significant negative — default feature.
        # The "context" promotion (regime modifier) requires a
        # regime-correlation diagnostic that doesn't exist yet; until
        # then non-alpha non-retire edges all stay as "feature".
        return TierDecision(
            edge_id=edge_id, new_tier="feature", new_combination_role="input",
            factor_tstat=t, factor_alpha_annualized=alpha, n_obs=decomp.n_obs,
            reason=f"factor t={t:+.2f}: not significant, default input",
            prior_tier=prior_tier,
        )

    # -------------------------------------------------------------- compute

    def _compute_decomps_from_trades(
        self,
        trades_path: Path,
        initial_capital: float = 100_000.0,
    ) -> Dict[str, Optional[FactorDecomp]]:
        """For each edge in a trade log, run factor decomposition.

        Returns a dict edge_id → FactorDecomp (or None if insufficient
        observations). Same per-edge return-stream logic as the
        diagnostic script in scripts/factor_decomposition_baseline.py.
        """
        if not trades_path.exists():
            raise FileNotFoundError(trades_path)

        trades = pd.read_csv(trades_path)
        if "edge" not in trades.columns or "pnl" not in trades.columns:
            raise ValueError(
                "trades.csv must have 'edge' and 'pnl' columns "
                "(post-attribution-fix shape)"
            )

        trades = trades.copy()
        trades["date"] = pd.to_datetime(trades["timestamp"]).dt.normalize()
        trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)

        factors = load_factor_data(auto_download=False)

        decomps: Dict[str, Optional[FactorDecomp]] = {}
        for edge_name, group in trades.groupby("edge"):
            if not isinstance(edge_name, str) or not edge_name or edge_name == "Unknown":
                continue
            daily_pnl = group.groupby("date")["pnl"].sum()
            if len(daily_pnl) < self.min_observations:
                decomps[edge_name] = None
                continue
            daily_ret = (daily_pnl / initial_capital).rename(edge_name)
            decomps[edge_name] = regress_returns_on_factors(
                returns=daily_ret,
                factors=factors,
                edge_name=edge_name,
                min_observations=self.min_observations,
            )
        return decomps

    # -------------------------------------------------------- apply / persist

    def classify_from_trades(
        self,
        trades_path: Path,
        initial_capital: float = 100_000.0,
        write: bool = True,
    ) -> List[TierDecision]:
        """End-to-end: read a trade log → compute factor decomps →
        apply the tier rule per edge → write the new tiers back to the
        registry (unless `write=False` for dry-run).

        Returns the list of TierDecisions, including unchanged ones.
        Caller can filter on `.changed` for just the reclassifications.
        """
        decomps = self._compute_decomps_from_trades(trades_path, initial_capital)
        decisions: List[TierDecision] = []
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        for spec in self.registry.get_all_specs():
            decomp = decomps.get(spec.edge_id)
            decision = self._classify_from_decomp(
                edge_id=spec.edge_id,
                decomp=decomp,
                prior_tier=spec.tier or "feature",
            )
            decisions.append(decision)

            if write and decision.changed:
                # Update the spec in-place via direct attribute access; the
                # registry's _save() picks up the new fields.
                spec.tier = decision.new_tier
                spec.tier_last_updated = now_iso
                spec.combination_role = decision.new_combination_role
                print(
                    f"[TIER] {spec.edge_id}: {decision.prior_tier} → {decision.new_tier} "
                    f"({decision.reason})"
                )

        if write:
            self.registry._save()  # persist all tier updates in one batch

        return decisions


__all__ = [
    "TierClassifier",
    "TierDecision",
    "DEFAULT_ALPHA_TSTAT_FOR_ALPHA_TIER",
    "DEFAULT_ALPHA_ANNUAL_FOR_ALPHA_TIER",
    "DEFAULT_TSTAT_FOR_RETIRE_ELIGIBLE",
    "DEFAULT_DAYS_NEGATIVE_FOR_RETIRE",
]
