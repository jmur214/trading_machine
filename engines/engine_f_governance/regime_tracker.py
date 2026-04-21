# engines/engine_f_governance/regime_tracker.py
"""Per-edge, per-regime performance tracking using Welford's online algorithm.

Maintains running statistics (mean, variance, win/loss, drawdown) for each
(edge, regime) pair without storing raw trades. This enables regime-conditional
edge weighting in the Governor.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional

import numpy as np


@dataclass
class RegimeEdgeStats:
    """Rolling per-edge, per-regime statistics via Welford's online algorithm."""
    trade_count: int = 0
    pnl_sum: float = 0.0
    # Welford's running M2 for variance: var = M2 / (n - 1)
    _m2: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    # Drawdown tracking
    cumulative_pnl: float = 0.0
    peak_cumulative: float = 0.0
    max_drawdown: float = 0.0  # negative number (worst drawdown)

    def update(self, pnl: float) -> None:
        """Record a single trade PnL."""
        self.trade_count += 1
        # Welford's online mean/variance
        delta = pnl - self.mean_pnl
        self.pnl_sum += pnl
        delta2 = pnl - self.mean_pnl
        self._m2 += delta * delta2
        # Win/loss
        if pnl > 0:
            self.win_count += 1
        elif pnl < 0:
            self.loss_count += 1
        # Drawdown
        self.cumulative_pnl += pnl
        if self.cumulative_pnl > self.peak_cumulative:
            self.peak_cumulative = self.cumulative_pnl
        dd = self.cumulative_pnl - self.peak_cumulative
        if dd < self.max_drawdown:
            self.max_drawdown = dd

    @property
    def mean_pnl(self) -> float:
        return self.pnl_sum / self.trade_count if self.trade_count > 0 else 0.0

    @property
    def std_pnl(self) -> float:
        if self.trade_count < 2:
            return 0.0
        return math.sqrt(self._m2 / (self.trade_count - 1))

    @property
    def sharpe(self) -> float:
        """Annualized Sharpe approximation (assuming ~252 trades/year baseline)."""
        if self.trade_count < 2 or self.std_pnl < 1e-12:
            return 0.0
        return (self.mean_pnl / self.std_pnl) * math.sqrt(252)

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "trade_count": self.trade_count,
            "pnl_sum": self.pnl_sum,
            "_m2": self._m2,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "cumulative_pnl": self.cumulative_pnl,
            "peak_cumulative": self.peak_cumulative,
            "max_drawdown": self.max_drawdown,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RegimeEdgeStats":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# Edge name → category mapping (for affinity aggregation)
EDGE_CATEGORY_MAP = {
    "momentum": "momentum",
    "xsec_momentum": "momentum",
    "sma_cross": "trend_following",
    "atr_breakout": "trend_following",
    "trend": "trend_following",
    "rsi_bounce": "mean_reversion",
    "bollinger": "mean_reversion",
    "mean_reversion": "mean_reversion",
    "xsec_reversion": "mean_reversion",
    "fundamental": "fundamental",
    "value": "fundamental",
    "earnings": "fundamental",
}


class RegimePerformanceTracker:
    """Track per-edge performance across different market regimes."""

    def __init__(self, min_trades: int = 8):
        self.min_trades = min_trades
        # {regime_label: {edge_name: RegimeEdgeStats}}
        self._data: Dict[str, Dict[str, RegimeEdgeStats]] = {}

    def record_trade(self, edge_name: str, pnl: float, regime_label: str) -> None:
        """Record a trade and update stats for both regime-specific and global buckets."""
        for label in (regime_label, "_global"):
            if label not in self._data:
                self._data[label] = {}
            if edge_name not in self._data[label]:
                self._data[label][edge_name] = RegimeEdgeStats()
            self._data[label][edge_name].update(pnl)

    def get_regime_sharpe(self, edge_name: str, regime_label: str) -> Optional[float]:
        """Get Sharpe for an edge in a specific regime. Returns None if insufficient data."""
        stats = self._data.get(regime_label, {}).get(edge_name)
        if stats is None or stats.trade_count < self.min_trades:
            return None
        return stats.sharpe

    def get_regime_weight(self, edge_name: str, regime_label: str,
                          sr_floor: float = 0.25, sr_ceil: float = 1.0,
                          disable_sr_threshold: float = 0.0,
                          mdd_threshold: float = -0.25) -> Optional[float]:
        """Compute weight for an edge in a regime using same logic as Governor.

        Returns None if insufficient data (caller should fall back to global weight).
        """
        stats = self._data.get(regime_label, {}).get(edge_name)
        if stats is None or stats.trade_count < self.min_trades:
            return None

        sr = stats.sharpe

        # Kill-switch: negative Sharpe
        if sr <= disable_sr_threshold:
            return 0.0

        # SR → weight mapping
        sr_clamped = float(np.clip(sr, 0.0, 1.0))
        weight = sr_floor + (sr_ceil - sr_floor) * sr_clamped

        # MDD soft penalty (use cumulative drawdown as proxy)
        if stats.cumulative_pnl < 0 and stats.max_drawdown < mdd_threshold:
            weight *= 0.25

        return float(np.clip(weight, 0.0, 1.0))

    def get_learned_affinity(self, regime_label: str) -> Dict[str, float]:
        """Compute per-edge-category average weights for a regime.

        Returns {category: weight} where weight represents how well
        edges of that category perform in the given regime.
        """
        regime_data = self._data.get(regime_label, {})
        if not regime_data:
            return {}

        # Group edges by category and average their regime weights
        category_weights: Dict[str, list] = {}
        for edge_name, stats in regime_data.items():
            if stats.trade_count < self.min_trades:
                continue
            category = self._edge_to_category(edge_name)
            weight = self.get_regime_weight(edge_name, regime_label)
            if weight is not None:
                category_weights.setdefault(category, []).append(weight)

        # Average per category, normalize relative to global
        global_data = self._data.get("_global", {})
        result = {}
        for category, weights in category_weights.items():
            regime_avg = sum(weights) / len(weights)
            # Compare to global average for same category
            global_weights = []
            for edge_name, stats in global_data.items():
                if self._edge_to_category(edge_name) == category and stats.trade_count >= self.min_trades:
                    gw = self.get_regime_weight(edge_name, "_global")
                    if gw is not None:
                        global_weights.append(gw)
            if global_weights:
                global_avg = sum(global_weights) / len(global_weights)
                # Ratio: how much better/worse this category is in this regime vs global
                if global_avg > 0.01:
                    result[category] = float(np.clip(regime_avg / global_avg, 0.3, 1.5))
                else:
                    result[category] = 1.0
            else:
                result[category] = 1.0

        return result

    def trade_count_for_regime(self, regime_label: str) -> int:
        """Total trades recorded under a regime label."""
        regime_data = self._data.get(regime_label, {})
        return sum(s.trade_count for s in regime_data.values())

    def save(self, path: str | Path) -> None:
        """Persist to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = {}
        for regime_label, edges in self._data.items():
            serialized[regime_label] = {
                edge_name: stats.to_dict() for edge_name, stats in edges.items()
            }
        with path.open("w") as f:
            json.dump(serialized, f, indent=2)

    def load(self, path: str | Path) -> None:
        """Load from JSON. Silently no-ops if file doesn't exist."""
        path = Path(path)
        if not path.exists():
            return
        try:
            with path.open() as f:
                raw = json.load(f)
            for regime_label, edges in raw.items():
                self._data[regime_label] = {
                    edge_name: RegimeEdgeStats.from_dict(stats_dict)
                    for edge_name, stats_dict in edges.items()
                }
        except Exception:
            pass  # Non-fatal; start fresh

    @staticmethod
    def _edge_to_category(edge_name: str) -> str:
        """Map edge name to category for affinity aggregation."""
        edge_lower = edge_name.lower()
        for pattern, category in EDGE_CATEGORY_MAP.items():
            if pattern in edge_lower:
                return category
        return "fundamental"  # default fallback
