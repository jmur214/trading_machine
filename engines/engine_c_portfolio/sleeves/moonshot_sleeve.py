"""Moonshot sleeve — asymmetric-upside, LEAPS-eligible names with binary
catalysts.

Phase 0 scaffolding. Per
``docs/Core/Ideas_Pipeline/moonshot_sleeve_scoping_2026_05_07.md`` (user
approved 2026-05-07):
  - Universe: (e) mix — LEAPS-eligible w/ catalysts + special situations
    (handled by other phases)
  - Sizing: 1-2% per bet, 30-50 max concurrent, 50% trailing stop, 5% max-name,
    25% max-sector
  - Capital allocation: dynamic 10% → 25% if Phase 1 produces positive Sortino
  - Objective: Sortino + skewness + tail ratio + upside capture (sleeve gauntlet)

Sizing rule (Phase 0):
  - Each catalyst-tagged name receives an equal-weight slot up to
    ``per_bet_size`` (default 1.5% of sleeve capital). Slots in excess of
    ``max_concurrent_positions`` are pruned by signal strength.
  - The sleeve's own ``max_position_weight`` cap (default 5%) is the
    safety net so an upstream config error can't blow up the slot.

Status: Phase 0 = scaffolding test. Not yet wired into
PortfolioEngine.allocate — opt-in path follows the migration plan.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .sleeve_base import Sleeve, SleeveSpec, SleeveOutput


DEFAULT_PER_BET_SIZE = 0.015            # 1.5% of sleeve capital per bet
DEFAULT_MAX_CONCURRENT = 50             # max positions in the sleeve
DEFAULT_MIN_CONCURRENT = 30             # min before sleeve fills available slots
DEFAULT_MAX_POSITION_WEIGHT = 0.05      # 5% cap on any single name
DEFAULT_MAX_SECTOR_WEIGHT = 0.25        # 25% cap on any single sector


class MoonshotSleeve(Sleeve):
    """Equal-weight asymmetric-upside sleeve with concentration caps.

    The sleeve does NOT generate alpha — it's a sizing + concentration
    framework on top of the actual signals (which come from
    leaps_catalyst_edge_v1, spinoff_edge_v1, etc.). Signal strength is
    used only for tie-breaking when more candidates appear than
    max_concurrent slots.
    """

    def __init__(
        self,
        spec: SleeveSpec,
        *,
        per_bet_size: float = DEFAULT_PER_BET_SIZE,
        max_concurrent_positions: int = DEFAULT_MAX_CONCURRENT,
        min_concurrent_positions: int = DEFAULT_MIN_CONCURRENT,
        max_sector_weight: float = DEFAULT_MAX_SECTOR_WEIGHT,
        sector_map: Optional[Dict[str, str]] = None,
    ):
        super().__init__(spec)
        self.per_bet_size = float(per_bet_size)
        self.max_concurrent_positions = int(max_concurrent_positions)
        self.min_concurrent_positions = int(min_concurrent_positions)
        self.max_sector_weight = float(max_sector_weight)
        self.sector_map = dict(sector_map) if sector_map else {}

    # ------------------------------------------------------------------
    def _select_candidates(
        self,
        signals: Dict[str, float],
    ) -> Dict[str, float]:
        """Pick the top-K candidates from the signal map.

        Signals must be positive (no shorting in the moonshot sleeve —
        asymmetric upside is the design). Ties broken by signal value
        (stronger conviction first).
        """
        positive = {t: float(s) for t, s in signals.items() if s > 0}
        if not positive:
            return {}
        ranked = sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
        return dict(ranked[: self.max_concurrent_positions])

    def _apply_sector_cap(
        self,
        weights: Dict[str, float],
    ) -> Dict[str, float]:
        """Pro-rata-down sectors that exceed the max sector weight."""
        if not self.sector_map or not weights:
            return weights
        sector_totals: Dict[str, float] = {}
        for tk, w in weights.items():
            sec = self.sector_map.get(tk, "Unknown")
            sector_totals[sec] = sector_totals.get(sec, 0.0) + w
        out = dict(weights)
        for sec, total in sector_totals.items():
            if total > self.max_sector_weight + 1e-12:
                scale = self.max_sector_weight / total
                for tk in list(out.keys()):
                    if self.sector_map.get(tk, "Unknown") == sec:
                        out[tk] *= scale
        return out

    # ------------------------------------------------------------------
    def propose_weights(
        self,
        as_of: pd.Timestamp,
        signals: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict] = None,
    ) -> SleeveOutput:
        if not self.is_rebalance_due(as_of):
            return SleeveOutput(
                sleeve_name=self.spec.name,
                target_weights=dict(self._last_weights),
                rebalance_due=False,
                last_rebalance=self._last_rebalance,
            )

        candidates = self._select_candidates(signals)
        if not candidates:
            self._record_rebalance(as_of, {})
            return SleeveOutput(
                sleeve_name=self.spec.name,
                target_weights={},
                rebalance_due=True,
                last_rebalance=as_of,
                diagnostics={"n_eligible": 0.0, "n_held": 0.0},
            )

        # Equal-weight sizing capped at per_bet_size — only fill slots up to
        # max_concurrent_positions. If candidates < min_concurrent, accept
        # the smaller book (sleeve is allowed to be under-filled).
        n = len(candidates)
        per_bet = min(self.per_bet_size, 1.0 / max(n, 1))
        # If we have FEWER than the minimum and per_bet is < per_bet_size,
        # this means equal-weight Sigma=1.0 normalization ate the cap — that
        # is the design.
        weights = {tk: per_bet for tk in candidates}

        # Apply per-position cap from spec.max_position_weight (the real
        # safety net — should be >= per_bet_size in normal config).
        cap = float(self.spec.max_position_weight)
        if cap < 1.0:
            weights = {tk: min(w, cap) for tk, w in weights.items()}

        # Sector cap
        weights = self._apply_sector_cap(weights)

        # Normalize to 1.0 within sleeve so the aggregator's capital_pct
        # scaling is the only knob that decides allocation. Sleeve fills
        # its allocated capital; per_bet_size is the *upper* bound, not
        # an absolute floor.
        total = sum(weights.values())
        if total > 0:
            weights = {tk: w / total for tk, w in weights.items()}
        else:
            weights = {}

        self._record_rebalance(as_of, weights)

        return SleeveOutput(
            sleeve_name=self.spec.name,
            target_weights=weights,
            rebalance_due=True,
            last_rebalance=as_of,
            objective_value=float(sum(candidates.values())),
            diagnostics={
                "n_eligible": float(n),
                "n_held": float(len(weights)),
                "max_weight": float(max(weights.values())) if weights else 0.0,
                "n_sectors": float(len(set(self.sector_map.get(t, "Unknown")
                                            for t in weights))),
            },
        )
