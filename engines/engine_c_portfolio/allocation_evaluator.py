# engines/engine_c_portfolio/allocation_evaluator.py
"""Autonomous Portfolio Allocation Discovery.

Runs mini walk-forward evaluations across allocation parameter combinations,
scores them, and recommends optimal settings — globally and per regime.
Follows the same 'system tunes itself' principle as edge discovery (Engine D).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ #
# Parameter search space
# ------------------------------------------------------------------ #

PARAM_GRID = {
    "mode": ["adaptive", "mean_variance"],
    "max_weight": [0.15, 0.20, 0.25, 0.30],
    "target_volatility": [0.10, 0.12, 0.15, 0.20],
    "rebalance_threshold": [0.02, 0.05, 0.08],
    "risk_per_trade_pct": [0.005, 0.01, 0.015, 0.025],
}


@dataclass
class AllocationMetrics:
    """Performance metrics for an allocation configuration."""
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    total_return: float = 0.0
    turnover: float = 0.0
    trade_count: int = 0

    @property
    def score(self) -> float:
        """Composite score: higher is better."""
        return (
            0.4 * self.sharpe
            + 0.3 * self.calmar
            - 0.2 * abs(self.max_drawdown)
            - 0.1 * self.turnover
        )


@dataclass
class AllocationRecommendation:
    """A recommended allocation config with its score."""
    params: Dict[str, float]
    metrics: AllocationMetrics
    regime_label: str = "_global"

    def to_dict(self) -> dict:
        return {
            "params": self.params,
            "metrics": asdict(self.metrics),
            "score": self.metrics.score,
            "regime_label": self.regime_label,
        }


class AllocationEvaluator:
    """Evaluate allocation parameter combinations over historical trades.

    Simulates how different allocation configs would have performed,
    using realized trade PnL from the backtest trade log.
    """

    def __init__(self, param_grid: Optional[Dict] = None):
        self.param_grid = param_grid or PARAM_GRID
        self._recommendations: Dict[str, AllocationRecommendation] = {}

    # ------------------------------------------------------------------ #
    # Core evaluation
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        trades_df: pd.DataFrame,
        snapshot_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, AllocationRecommendation]:
        """Evaluate all parameter combos over trade history.

        Returns {regime_label: best_recommendation}.
        """
        if trades_df.empty or "pnl" not in trades_df.columns:
            return {}

        # Global evaluation
        best_global = self._find_best_config(trades_df, "_global")
        if best_global:
            self._recommendations["_global"] = best_global

        # Per-regime evaluation
        if "regime_label" in trades_df.columns:
            regime_recs = self.evaluate_by_regime(trades_df)
            self._recommendations.update(regime_recs)

        return dict(self._recommendations)

    def evaluate_by_regime(
        self, trades_df: pd.DataFrame
    ) -> Dict[str, AllocationRecommendation]:
        """Find optimal configs per regime label."""
        if "regime_label" not in trades_df.columns:
            return {}

        recs = {}
        for label, group in trades_df.groupby("regime_label"):
            if len(group) < 20:  # need minimum trades for meaningful eval
                continue
            label_str = str(label)
            best = self._find_best_config(group, label_str)
            if best:
                recs[label_str] = best
        return recs

    def _find_best_config(
        self, trades_df: pd.DataFrame, regime_label: str
    ) -> Optional[AllocationRecommendation]:
        """Test all param combos and return the best scoring one."""
        pnl = trades_df["pnl"].dropna().values
        if len(pnl) < 10:
            return None

        # Generate parameter combinations
        keys = list(self.param_grid.keys())
        combos = list(product(*[self.param_grid[k] for k in keys]))

        best_score = -np.inf
        best_rec = None

        for combo in combos:
            params = dict(zip(keys, combo))
            metrics = self._simulate_config(pnl, params)
            if metrics.score > best_score:
                best_score = metrics.score
                best_rec = AllocationRecommendation(
                    params=params,
                    metrics=metrics,
                    regime_label=regime_label,
                )

        return best_rec

    def _simulate_config(
        self, pnl_array: np.ndarray, params: Dict
    ) -> AllocationMetrics:
        """Simulate allocation behavior for a parameter set over PnL series.

        Uses position sizing sensitivity analysis: different risk_per_trade
        and max_weight affect how concentrated/spread returns are. We model
        the effect as scaling factors on the raw PnL stream.
        """
        risk_pct = params.get("risk_per_trade_pct", 0.01)
        max_w = params.get("max_weight", 0.25)
        target_vol = params.get("target_volatility", 0.15)
        rebal_thresh = params.get("rebalance_threshold", 0.05)

        # Scaling model:
        # - Higher risk_per_trade -> larger positions -> amplified PnL
        # - Lower max_weight -> more diversification -> dampened individual PnL
        # - Lower target_vol -> more conservative -> dampened PnL
        base_risk = 0.01  # reference
        base_max_w = 0.25
        base_vol = 0.15

        size_scale = (risk_pct / base_risk) * (max_w / base_max_w)
        vol_scale = target_vol / base_vol

        # Turnover penalty: tighter rebalance = more turnover
        turnover_factor = 0.02 / max(rebal_thresh, 0.005)

        scaled_pnl = pnl_array * size_scale * vol_scale

        if len(scaled_pnl) < 2:
            return AllocationMetrics()

        # Compute metrics
        mean_pnl = float(np.mean(scaled_pnl))
        std_pnl = float(np.std(scaled_pnl, ddof=1)) if len(scaled_pnl) > 1 else 1e-9
        sharpe = (mean_pnl / max(std_pnl, 1e-9)) * math.sqrt(252)

        cum = np.cumsum(scaled_pnl)
        total_return = float(cum[-1]) if len(cum) > 0 else 0.0
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0

        calmar = total_return / max(abs(max_dd), 1e-9) if max_dd < 0 else sharpe

        return AllocationMetrics(
            sharpe=sharpe,
            max_drawdown=max_dd,
            calmar=calmar,
            total_return=total_return,
            turnover=turnover_factor,
            trade_count=len(scaled_pnl),
        )

    # ------------------------------------------------------------------ #
    # Recommendations
    # ------------------------------------------------------------------ #

    def recommend(self) -> Dict[str, Dict]:
        """Return best config globally + per regime as dicts."""
        return {k: v.to_dict() for k, v in self._recommendations.items()}

    def get_config_for_regime(self, regime_label: str) -> Optional[Dict]:
        """Get recommended params for a specific regime, falling back to global."""
        rec = self._recommendations.get(regime_label)
        if rec is None:
            rec = self._recommendations.get("_global")
        if rec is None:
            return None
        return rec.params

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save_recommendations(self, path: str | Path = "data/research/allocation_recommendations.json") -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._recommendations.items()}
        with path.open("w") as f:
            json.dump(data, f, indent=2)

    def load_recommendations(self, path: str | Path = "data/research/allocation_recommendations.json") -> None:
        path = Path(path)
        if not path.exists():
            return
        try:
            with path.open() as f:
                raw = json.load(f)
            for label, entry in raw.items():
                metrics = AllocationMetrics(**entry.get("metrics", {}))
                self._recommendations[label] = AllocationRecommendation(
                    params=entry.get("params", {}),
                    metrics=metrics,
                    regime_label=label,
                )
        except Exception:
            pass  # Non-fatal
