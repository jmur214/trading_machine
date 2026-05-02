"""Turnover penalty — reject rebalances where alpha lift < transaction cost.

Stateful module that tracks the most recently committed weight vector
and gates each new proposal:

    delta_alpha = Σ_i (w_new_i - w_old_i) × mu_i        # gain from the move
    cost        = Σ_i |w_new_i - w_old_i| × cost_bps_i  # cost of the move

If `delta_alpha * gross_capital < cost * gross_capital`, the proposal is
rejected and the previous weight vector is returned. Otherwise, the
proposal is accepted and stored as the new committed state.

Cost model:
  - Default: flat `flat_cost_bps` (e.g. 10 bps) per dollar of turnover
  - Optional: per-ticker cost via injected callable
    (typically `RealisticSlippageModel.calculate_slippage_bps`) so that
    impact + half-spread differentiate by ADV/volatility/order-size.

This first slice keeps the cost callable optional. The default flat
model is sufficient to establish the gating semantics; the per-ticker
plumbing is wired in as a follow-up workstream item once the gross-
capital signal volume can be passed through cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass
class TurnoverConfig:
    flat_cost_bps: float = 10.0     # 0.10% per turnover unit
    min_turnover_to_check: float = 0.01  # below 1% turnover always accept
    enabled: bool = True


CostFn = Callable[[str, float], float]
"""Per-ticker cost callback: (ticker, weight_delta) -> bps."""


class TurnoverPenalty:
    """Stateful turnover gate.

    Stores the most recently *accepted* weight vector and gates each
    proposal against it. Resets via `reset()` for clean A/B determinism.
    """

    def __init__(self, cfg: Optional[TurnoverConfig] = None, cost_fn: Optional[CostFn] = None):
        self.cfg = cfg or TurnoverConfig()
        self._cost_fn = cost_fn
        self._committed: Optional[pd.Series] = None
        self._n_proposed: int = 0
        self._n_accepted: int = 0
        self._n_rejected: int = 0

    def reset(self) -> None:
        self._committed = None
        self._n_proposed = 0
        self._n_accepted = 0
        self._n_rejected = 0

    @property
    def stats(self) -> dict:
        return {
            "proposed": self._n_proposed,
            "accepted": self._n_accepted,
            "rejected": self._n_rejected,
            "reject_rate": (self._n_rejected / self._n_proposed) if self._n_proposed else 0.0,
        }

    def evaluate(
        self,
        proposed_weights: pd.Series,
        expected_returns: pd.Series,
    ) -> pd.Series:
        """Decide whether to accept `proposed_weights`. Returns either
        the proposal (if alpha-positive after costs) or the previously-
        committed weights (if the rebalance fails the threshold).

        On first call, no committed state exists → accept unconditionally.
        """
        self._n_proposed += 1

        if not self.cfg.enabled or self._committed is None:
            self._committed = proposed_weights.copy()
            self._n_accepted += 1
            return proposed_weights

        union_idx = proposed_weights.index.union(self._committed.index)
        w_new = proposed_weights.reindex(union_idx).fillna(0.0)
        w_old = self._committed.reindex(union_idx).fillna(0.0)
        mu = expected_returns.reindex(union_idx).fillna(0.0)

        delta = w_new - w_old
        gross_turnover = float(np.abs(delta).sum())

        if gross_turnover < self.cfg.min_turnover_to_check:
            self._committed = proposed_weights.copy()
            self._n_accepted += 1
            return proposed_weights

        delta_alpha = float((delta * mu).sum())

        if self._cost_fn is not None:
            cost = sum(
                abs(float(delta.loc[t])) * float(self._cost_fn(t, float(delta.loc[t]))) / 10000.0
                for t in union_idx
            )
        else:
            cost = gross_turnover * (self.cfg.flat_cost_bps / 10000.0)

        if delta_alpha < cost:
            self._n_rejected += 1
            return self._committed.copy()

        self._committed = proposed_weights.copy()
        self._n_accepted += 1
        return proposed_weights
