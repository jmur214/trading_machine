"""Trend-following sleeve — first concrete Sleeve implementation.

Phase 0: scaffolding test of the multi-sleeve abstraction. Implements
a classical CTA-style trend-following sizing rule: per-ticker absolute-
momentum filter + inverse-vol weighting.

Mechanism
---------
1. For each ticker in the input signals, compute trailing N-month return.
2. Filter to tickers with positive momentum (long-only by default; short
   leg is feature-flag-gated for future extension).
3. Inverse-vol weight: position size ∝ 1 / realized_vol. Captures the
   classical CTA insight that vol-equalized exposure stabilizes the
   sleeve's risk profile across regimes.
4. Normalize weights to sum to 1.0 of sleeve capital.

This is deliberately simple — sleeve-level behavior validation, not
edge-level sophistication. The actual alpha decisions live in Engine A
edges; this sleeve just decides HOW to combine momentum-positive
tickers into a portfolio shape.

Status: not wired into PortfolioEngine.allocate by default.
PortfolioEngine continues to use PortfolioPolicy directly until a
wrapper opts in.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .sleeve_base import Sleeve, SleeveSpec, SleeveOutput


DEFAULT_LOOKBACK_DAYS = 252        # ~12-month momentum window
DEFAULT_VOL_WINDOW_DAYS = 63       # ~3-month realized vol
DEFAULT_TOP_N = 10                  # how many momentum-positive names to keep
DEFAULT_MIN_MOMENTUM = 0.0          # only long names with > this momentum


class TrendFollowingSleeve(Sleeve):
    """Long-only momentum sleeve with inverse-vol sizing."""

    def __init__(
        self,
        spec: SleeveSpec,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        vol_window_days: int = DEFAULT_VOL_WINDOW_DAYS,
        top_n: int = DEFAULT_TOP_N,
        min_momentum: float = DEFAULT_MIN_MOMENTUM,
    ):
        super().__init__(spec)
        self.lookback_days = int(lookback_days)
        self.vol_window_days = int(vol_window_days)
        self.top_n = int(top_n)
        self.min_momentum = float(min_momentum)

    # ------------------------------------------------------------------
    def _ticker_momentum(self, df: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
        """Return trailing N-day total return as of `as_of`, or None."""
        if df is None or df.empty or "Close" not in df.columns:
            return None
        try:
            sliced = df.loc[df.index <= as_of, "Close"].dropna()
        except (TypeError, KeyError):
            return None
        if len(sliced) < self.lookback_days + 1:
            return None
        end_p = float(sliced.iloc[-1])
        start_p = float(sliced.iloc[-(self.lookback_days + 1)])
        if start_p <= 0 or not np.isfinite(start_p):
            return None
        return end_p / start_p - 1.0

    def _ticker_realized_vol(self, df: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
        """Annualized realized vol over the last `vol_window_days`."""
        if df is None or df.empty or "Close" not in df.columns:
            return None
        try:
            sliced = df.loc[df.index <= as_of, "Close"].dropna()
        except (TypeError, KeyError):
            return None
        if len(sliced) < self.vol_window_days + 1:
            return None
        rets = sliced.pct_change().dropna().tail(self.vol_window_days)
        if rets.empty:
            return None
        std = float(rets.std(ddof=0))
        if std <= 0 or not np.isfinite(std):
            return None
        return std * np.sqrt(252.0)

    # ------------------------------------------------------------------
    def propose_weights(
        self,
        as_of: pd.Timestamp,
        signals: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict] = None,
    ) -> SleeveOutput:
        # Honor the cadence — return cached weights if we shouldn't
        # rebalance this call.
        if not self.is_rebalance_due(as_of):
            return SleeveOutput(
                sleeve_name=self.spec.name,
                target_weights=dict(self._last_weights),
                rebalance_due=False,
                last_rebalance=self._last_rebalance,
            )

        # Score each ticker on (momentum, vol). Use signals dict as the
        # eligible-universe filter (only tickers Engine A is signaling).
        # Tickers without sufficient history are dropped.
        scored: Dict[str, tuple[float, float]] = {}
        for ticker in signals:
            df = price_data.get(ticker)
            if df is None:
                continue
            mom = self._ticker_momentum(df, as_of)
            vol = self._ticker_realized_vol(df, as_of)
            if mom is None or vol is None:
                continue
            if mom <= self.min_momentum:
                continue
            scored[ticker] = (mom, vol)

        if not scored:
            self._record_rebalance(as_of, {})
            return SleeveOutput(
                sleeve_name=self.spec.name,
                target_weights={},
                rebalance_due=True,
                last_rebalance=as_of,
                objective_value=0.0,
                diagnostics={"n_eligible": 0},
            )

        # Top-N by momentum
        ranked = sorted(scored.items(), key=lambda kv: kv[1][0], reverse=True)
        top = ranked[: self.top_n]

        # Inverse-vol weight
        inv_vols = {tk: 1.0 / vol for tk, (_, vol) in top}
        total_iv = sum(inv_vols.values())
        if total_iv <= 0:
            weights = {}
        else:
            weights = {tk: iv / total_iv for tk, iv in inv_vols.items()}

        # Cap any single weight at spec.max_position_weight to prevent
        # one low-vol name from dominating the sleeve.
        cap = float(self.spec.max_position_weight)
        if cap < 1.0:
            capped = {tk: min(w, cap) for tk, w in weights.items()}
            # Re-normalize after the cap.
            total = sum(capped.values())
            weights = {tk: w / total for tk, w in capped.items()} if total > 0 else {}

        self._record_rebalance(as_of, weights)

        return SleeveOutput(
            sleeve_name=self.spec.name,
            target_weights=weights,
            rebalance_due=True,
            last_rebalance=as_of,
            objective_value=float(sum(mom for _, (mom, _) in top)),
            diagnostics={
                "n_eligible": float(len(scored)),
                "n_held": float(len(weights)),
                "mean_momentum": float(np.mean([mom for _, (mom, _) in top])) if top else 0.0,
                "mean_vol": float(np.mean([vol for _, (_, vol) in top])) if top else 0.0,
            },
        )
