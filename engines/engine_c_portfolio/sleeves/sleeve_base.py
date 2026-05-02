"""Sleeve abstract base — DESIGN ARTIFACT, not production code.

Defines the interface a multi-sleeve Engine C will expose. Concrete
sleeves (Core, Compounder, Moonshot) are NOT implemented here. The
aggregator that stitches sleeves into portfolio-level target weights
is also NOT implemented here.

This file ships on branch `path-c-compounder-sleeve-design` as a design
artifact. Production wiring follows the migration plan in
`docs/Audit/path_c_compounder_design_2026_05.md` Phases M0–M3.

Why ship the interface alone: it pins the contract before the
implementation, lets reviewers comment on the shape, and lets concrete
sleeves be drafted in parallel against a stable type surface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

import pandas as pd


RebalanceCadence = Literal[
    "bar",       # every bar (matches current core behavior)
    "daily",     # once per trading day
    "weekly",    # once per calendar week
    "monthly",   # once per calendar month
    "quarterly", # once per quarter
    "annual",    # once per calendar year (compounder default)
]


@dataclass(frozen=True)
class SleeveSpec:
    """Static identity + config of a sleeve.

    Loaded from `config/sleeves.json` at startup. Frozen so that mutation
    during a backtest is impossible — a sleeve's spec is part of its
    identity. Mutable runtime state lives on the `Sleeve` instance, not
    here.
    """

    name: str                                   # "core" | "compounder" | "moonshot"
    capital_pct: float                          # 0.0 – 1.0; aggregator enforces Σ ≤ 1.0
    rebalance_cadence: RebalanceCadence
    universe_id: str                            # references universe registry
    edge_set: List[str]                         # edge_ids this sleeve consumes
    sizing_rule: str                            # see notes below for vocabulary
    objective_function: str                     # see notes below for vocabulary
    enabled: bool = True
    max_position_weight: float = 1.0            # cap on any single ticker WITHIN sleeve
    target_volatility: Optional[float] = None   # None = no sleeve-level vol targeting

    # Vocabulary (validated in MultiSleeveAggregator at load time):
    #   sizing_rule         ∈ {"equal_weight", "hrp", "mcap_weight", "weighted_sum"}
    #   objective_function  ∈ {"sharpe", "after_tax_cagr_floor_mdd",
    #                          "sortino_skew_upside"}
    # New values added here MUST be reflected in the JSON-schema validator.


@dataclass
class SleeveOutput:
    """What a sleeve hands to the aggregator each call.

    `target_weights` are normalized WITHIN the sleeve — i.e. they sum to
    1.0 of the sleeve's allocated capital (or 0.0 if the sleeve has no
    positions this rebalance). The aggregator scales by capital_pct.
    """

    sleeve_name: str
    target_weights: Dict[str, float]
    rebalance_due: bool                         # True iff cadence triggered THIS call
    last_rebalance: Optional[pd.Timestamp] = None
    objective_value: Optional[float] = None     # current value of objective_function
    diagnostics: Dict[str, float] = field(default_factory=dict)


class Sleeve(ABC):
    """Abstract base for a portfolio sleeve.

    Each concrete sleeve implements `propose_weights`. The base class
    handles cadence accounting so concrete sleeves can't accidentally
    over-trade.

    Sleeves are deliberately ignorant of:
      - Other sleeves' state
      - The portfolio-level capital base (aggregator scales)
      - Engine B sizing details (only target weights flow downstream)
    """

    def __init__(self, spec: SleeveSpec) -> None:
        self.spec = spec
        self._last_rebalance: Optional[pd.Timestamp] = None
        self._last_weights: Dict[str, float] = {}

    @abstractmethod
    def propose_weights(
        self,
        as_of: pd.Timestamp,
        signals: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict] = None,
    ) -> SleeveOutput:
        """Return target weights within this sleeve's mandate.

        MUST honor self.spec.rebalance_cadence — if cadence is not
        triggered, return SleeveOutput with rebalance_due=False and the
        previously-computed weights (or {} on first call before first
        rebalance).

        Inputs are scoped to this sleeve's universe — `signals` and
        `price_data` are pre-filtered by the aggregator.
        """

    def is_rebalance_due(self, as_of: pd.Timestamp) -> bool:
        """Default cadence check. Concrete sleeves may override for
        custom triggers (e.g. mid-year drift check on the compounder)."""
        if self._last_rebalance is None:
            return True

        cadence = self.spec.rebalance_cadence
        if cadence == "bar":
            return True

        prev = self._last_rebalance
        if cadence == "daily":
            return as_of.normalize() != prev.normalize()
        if cadence == "weekly":
            return as_of.isocalendar().week != prev.isocalendar().week or \
                   as_of.year != prev.year
        if cadence == "monthly":
            return (as_of.year, as_of.month) != (prev.year, prev.month)
        if cadence == "quarterly":
            return (as_of.year, as_of.quarter) != (prev.year, prev.quarter)
        if cadence == "annual":
            return as_of.year != prev.year

        raise ValueError(
            f"Unknown rebalance_cadence {cadence!r} on sleeve {self.spec.name!r}"
        )

    def _record_rebalance(
        self,
        as_of: pd.Timestamp,
        weights: Dict[str, float],
    ) -> None:
        """Concrete sleeves call this at the end of a rebalance step."""
        self._last_rebalance = as_of
        self._last_weights = dict(weights)
