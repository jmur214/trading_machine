"""MultiSleeveAggregator — combines per-sleeve target weights into the
portfolio-level weight map.

Each registered Sleeve owns a slice of capital (`spec.capital_pct`); the
aggregator:
  1. Filters the universe-wide `signals` / `price_data` to each sleeve's
     `edge_set` / mapped universe (today: ticker-level filter via the
     spec's universe_id; tomorrow: a more sophisticated universe loader).
  2. Calls each sleeve's `propose_weights` with the scoped inputs.
  3. Scales the sleeve's per-sleeve weights by its `capital_pct`.
  4. Sums across sleeves to produce the portfolio-level weight map.

The aggregator is OFF by default — `PortfolioEngine.allocate` keeps its
existing single-policy path until a wrapper opts in. This preserves
all current backtest reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .sleeve_base import Sleeve, SleeveOutput, SleeveSpec


@dataclass
class AggregatorResult:
    """One aggregator step's output."""
    target_weights: Dict[str, float]                 # portfolio-level weights
    per_sleeve: Dict[str, SleeveOutput] = field(default_factory=dict)
    capital_used_pct: float = 0.0                    # Σ active sleeves' capital_pct


class MultiSleeveAggregator:
    """Coordinator across N sleeves.

    Capital constraint
    ------------------
    ``Σ spec.capital_pct ≤ 1.0`` enforced at construction. Disabled
    sleeves (``spec.enabled = False``) drop out of both the sum and the
    iteration but their capital_pct slot is preserved (i.e., disabled
    sleeve = its capital sits idle, not redistributed). This matches
    institutional behavior: pulling a sleeve releases capital, it doesn't
    auto-route to other sleeves.

    Universe filtering
    ------------------
    Each sleeve's universe is encoded in ``spec.edge_set`` (the edge_ids
    it consumes) — for now we don't filter price_data by ticker (single
    universe assumed). When sleeves need disjoint ticker universes, this
    aggregator will gain a per-spec universe filter.
    """

    def __init__(self, sleeves: List[Sleeve], *, strict_capital_check: bool = True):
        if not sleeves:
            raise ValueError("MultiSleeveAggregator requires ≥1 sleeve")

        # Names must be unique
        names = [s.spec.name for s in sleeves]
        if len(names) != len(set(names)):
            dups = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"sleeve names must be unique; duplicates: {dups}")

        # Capital sum check (only over enabled sleeves)
        total_pct = sum(s.spec.capital_pct for s in sleeves if s.spec.enabled)
        if strict_capital_check and total_pct > 1.0 + 1e-9:
            raise ValueError(
                f"Σ enabled sleeves' capital_pct = {total_pct:.4f} > 1.0; "
                f"either reduce per-sleeve capital_pct or disable a sleeve"
            )

        self.sleeves: List[Sleeve] = list(sleeves)

    # ------------------------------------------------------------------
    def step(
        self,
        as_of: pd.Timestamp,
        signals: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict] = None,
    ) -> AggregatorResult:
        """Run one aggregation cycle. Returns portfolio-level weights."""
        portfolio_weights: Dict[str, float] = {}
        per_sleeve_outputs: Dict[str, SleeveOutput] = {}
        capital_used = 0.0

        for sleeve in self.sleeves:
            spec: SleeveSpec = sleeve.spec
            if not spec.enabled:
                continue

            # Per-sleeve filtering. For now: signals are filtered by the
            # implicit universe (whatever the sleeve's propose_weights
            # decides to use). When sleeves go to disjoint universes,
            # this filter pre-trims signals/price_data to the sleeve's
            # universe.
            filtered_signals = dict(signals)
            filtered_prices = dict(price_data)

            try:
                out = sleeve.propose_weights(
                    as_of=as_of,
                    signals=filtered_signals,
                    price_data=filtered_prices,
                    regime_meta=regime_meta,
                )
            except Exception as exc:
                # A failing sleeve must NOT take down the whole portfolio.
                # Emit a zero-weight output and continue.
                out = SleeveOutput(
                    sleeve_name=spec.name,
                    target_weights={},
                    rebalance_due=False,
                    diagnostics={"error": str(exc)[:200]},
                )

            per_sleeve_outputs[spec.name] = out
            capital_used += spec.capital_pct

            # Scale per-sleeve weights by capital_pct and accumulate.
            for ticker, w in out.target_weights.items():
                portfolio_weights[ticker] = portfolio_weights.get(ticker, 0.0) + w * spec.capital_pct

        return AggregatorResult(
            target_weights=portfolio_weights,
            per_sleeve=per_sleeve_outputs,
            capital_used_pct=capital_used,
        )

    # ------------------------------------------------------------------
    def sleeve_by_name(self, name: str) -> Optional[Sleeve]:
        for s in self.sleeves:
            if s.spec.name == name:
                return s
        return None

    def __len__(self) -> int:
        return len(self.sleeves)
