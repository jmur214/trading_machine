"""Engine C — Portfolio Composer.

Cross-ticker portfolio composition layer. Operates on the per-ticker
``info`` dict produced by Engine A's SignalProcessor and re-shapes
position weights via a real portfolio optimizer (HRP) plus a turnover
gate.

Closes the F4 charter inversion (audit 2026-05-06) where HRPOptimizer
and TurnoverPenalty were instantiated and called from
engines/engine_a_alpha/signal_processor.py. Engine A's signal processor
is now pure edge-aggregation; Engine C owns the portfolio-composition
step.

Public surface:
    PortfolioOptimizerSettings — config dataclass
    PortfolioComposer          — applies HRP + turnover to per-ticker info

Methods:
    method = "weighted_sum"  → strict no-op. Default.
    method = "hrp"           → HRP-as-replacement (slice 1 — FALSIFIED).
                               Retained for D-cell verification only.
                               Strips ensemble conviction from
                               aggregate_score and replaces with
                               HRP-weight × N. Sharpe regression -0.63
                               vs weighted_sum on prod-109 2025 OOS.
    method = "hrp_composed"  → HRP slice 3 (compose-not-replace).
                               Preserves aggregate_score; writes per-
                               ticker ``optimizer_weight`` (= HRP-weight ×
                               N, lower-clamped at 0; mean is exactly 1.0
                               across the firing set so the multiplier
                               redistributes size rather than reducing
                               it). Engine A threads optimizer_weight
                               into signal.meta; Engine B multiplies it
                               into ATR-risk sizing.

The turnover gate is consulted *after* HRP produces weights — if the
expected alpha lift < expected transaction cost, the previously-
committed weight vector is reused instead, suppressing churn. Active
for both HRP methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .optimizers import HRPOptimizer, TurnoverPenalty
from .optimizers.hrp import HRPConfig
from .optimizers.turnover import TurnoverConfig


@dataclass
class PortfolioOptimizerSettings:
    """Config for PortfolioComposer.

    Default OFF for safety: when ``method == "weighted_sum"``, all HRP
    machinery is bypassed, including turnover state. This is a strict
    no-op for callers that don't opt in.
    """
    method: str = "weighted_sum"  # "weighted_sum" | "hrp" | "hrp_composed"
    cov_lookback: int = 60
    min_history: int = 30
    use_ledoit_wolf: bool = True
    linkage_method: str = "single"
    turnover_enabled: bool = True
    turnover_flat_cost_bps: float = 10.0
    turnover_min_check: float = 0.01


class PortfolioComposer:
    """Applies HRP + turnover gating to per-ticker info dicts.

    Instantiation is cheap; the HRP/Turnover heavy state is only
    constructed when ``settings.method != "weighted_sum"``. So callers
    can build a composer unconditionally.
    """

    def __init__(self, settings: Optional[PortfolioOptimizerSettings] = None, debug: bool = False):
        self.settings = settings or PortfolioOptimizerSettings()
        self.debug = bool(debug)
        self._hrp: Optional[HRPOptimizer] = None
        self._turnover: Optional[TurnoverPenalty] = None
        if self.settings.method in ("hrp", "hrp_composed"):
            self._hrp = HRPOptimizer(HRPConfig(
                cov_lookback=self.settings.cov_lookback,
                min_history=self.settings.min_history,
                use_ledoit_wolf=self.settings.use_ledoit_wolf,
                linkage_method=self.settings.linkage_method,
            ))
            self._turnover = TurnoverPenalty(TurnoverConfig(
                enabled=self.settings.turnover_enabled,
                flat_cost_bps=self.settings.turnover_flat_cost_bps,
                min_turnover_to_check=self.settings.turnover_min_check,
            ))

    @property
    def is_active(self) -> bool:
        return self._hrp is not None

    def compose(
        self,
        per_ticker: Dict[str, dict],
        data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, dict]:
        """Mutate ``per_ticker`` in place to add ``hrp_weight`` and
        ``optimizer_weight`` (and, for slice-1 method "hrp", overwrite
        ``aggregate_score``).

        Returns the same dict for chaining. No-op when method is
        "weighted_sum" or HRP would degenerate (fewer than 2 active
        tickers, no usable returns panel).
        """
        if not self.is_active or self._hrp is None:
            return per_ticker

        active = [
            t for t, info in per_ticker.items()
            if abs(float(info.get("aggregate_score", 0.0))) > 1e-6
        ]
        if len(active) < 2:
            return per_ticker

        returns_df = self._build_returns_panel(active, data_map)
        if returns_df is None or returns_df.empty:
            return per_ticker

        active = [t for t in active if t in returns_df.columns]
        if len(active) < 2:
            return per_ticker

        proposed = self._hrp.optimize(returns_df, active_tickers=active)
        if proposed.empty or not np.isfinite(proposed.values).all():
            return per_ticker

        mu = pd.Series(
            {t: float(per_ticker[t]["aggregate_score"]) for t in proposed.index}
        )
        committed = self._turnover.evaluate(proposed, mu) if self._turnover else proposed

        n = len(committed)
        if n == 0:
            return per_ticker
        scale = float(n)
        is_composed = (self.settings.method == "hrp_composed")

        for t, w in committed.items():
            if t not in per_ticker:
                continue
            raw_magnitude = float(w) * scale
            per_ticker[t]["hrp_weight"] = float(w)

            if is_composed:
                # Slice 3 — redistribution, not reduction. `committed`
                # sums to 1.0 by HRP construction, so committed × N has
                # mean exactly 1.0 across the firing set. Lower-clamp
                # at 0 lets above-mean tickers amplify (>1.0) and
                # below-mean attenuate (<1.0). Engine B's
                # max_gross_exposure cap clips any pathological
                # amplification.
                per_ticker[t]["optimizer_weight"] = max(0.0, raw_magnitude)
            else:
                # Slice-1 replacement (kept for D-cell verification).
                # aggregate_score is conventionally in [-1, 1]; preserve
                # the original clamp so slice-1 reproductions remain
                # bit-identical to the falsified design.
                magnitude = max(0.0, min(1.0, raw_magnitude))
                sgn = 1.0 if per_ticker[t]["aggregate_score"] >= 0 else -1.0
                per_ticker[t]["aggregate_score"] = sgn * magnitude
                per_ticker[t]["optimizer_weight"] = 1.0  # absorbed into score

        if self.debug and self._turnover is not None:
            print(f"[PORTFOLIO_COMPOSER] {self.settings.method} applied "
                  f"to n={n} tickers, turnover_stats={self._turnover.stats}")
        return per_ticker

    @staticmethod
    def _build_returns_panel(
        tickers: List[str],
        data_map: Dict[str, pd.DataFrame],
        col: str = "Close",
    ) -> Optional[pd.DataFrame]:
        """Wide returns DataFrame across the active tickers, joined on
        the bar index. Returns None if no ticker has usable data.
        """
        series_map: Dict[str, pd.Series] = {}
        for t in tickers:
            df = data_map.get(t)
            if df is None or df.empty or col not in df.columns:
                continue
            s = df[col].astype(float).pct_change().dropna()
            if len(s) > 0:
                series_map[t] = s
        if not series_map:
            return None
        return pd.DataFrame(series_map).dropna(how="all")
