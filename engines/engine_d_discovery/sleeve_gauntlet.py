"""Sleeve-level gauntlet — different fitness criteria from the core gauntlet.

The core book gauntlet uses Sharpe + PSR/DSR. That objective penalizes
upside skew, which is exactly the property the Moonshot sleeve is
designed to capture. Sleeves use a different objective:

  Sortino + skewness + tail_ratio + upside_capture

with sleeve-specific kill / success thresholds defined per-spec.

This module ships:
  - `compute_sleeve_metrics(returns, benchmark)` → dict
  - `evaluate_sleeve_gauntlet(metrics, criteria)` → SleeveVerdict

It does NOT short-circuit the core gauntlet. Engine D's existing
`validate_candidate` is for edges going into the core ensemble; this
module is for evaluating a sleeve's PnL stream as a whole.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.metrics_engine import MetricsEngine


# ---------------------------------------------------------------------- #

@dataclass
class SleeveCriteria:
    """Pre-committed success and kill thresholds for a sleeve.

    The Moonshot scoping doc (decision #7) ratified:
      success: Sortino > 1.5, skewness > 0.5, ≥1 ≥3x bet, DSR > 0.80
      kill:    Sortino < 0.3, MDD > 35%, flat skew, hit-rate < 25% w/ avg-winner < 2x

    Trend-following defaults are tighter (it's a proven strategy class
    so the bar is higher): Sortino > 1.2, MDD > 25% kills.
    """
    sleeve_name: str
    sortino_min_success: float = 1.5
    skewness_min_success: float = 0.5
    tail_ratio_min_success: float = 1.5
    upside_capture_min_success: float = 0.7
    sortino_kill: float = 0.3
    max_drawdown_kill: float = 0.35      # positive number; 0.35 → 35%
    skewness_kill_below: float = 0.0     # flat-or-negative skew kills
    hit_rate_kill_below: float = 0.25    # below this AND avg_winner < kill triggers
    avg_winner_kill_below: float = 2.0   # combined trigger w/ hit-rate
    min_observations: int = 60           # too short → INDETERMINATE
    require_min_3x_bet: bool = False     # Moonshot specific


@dataclass
class SleeveMetrics:
    """Computed metrics for one sleeve's return stream."""
    sortino: float
    skewness: float
    tail_ratio: float
    upside_capture: float
    max_drawdown: float                 # signed negative
    sharpe: float                       # for cross-reference to core
    n_observations: int
    hit_rate: Optional[float] = None
    avg_winner: Optional[float] = None
    avg_loser: Optional[float] = None
    has_3x_bet: Optional[bool] = None
    bootstrap_sortino: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, float | int | bool | None | dict]:
        return {
            "sortino": self.sortino,
            "skewness": self.skewness,
            "tail_ratio": self.tail_ratio,
            "upside_capture": self.upside_capture,
            "max_drawdown": self.max_drawdown,
            "sharpe": self.sharpe,
            "n_observations": self.n_observations,
            "hit_rate": self.hit_rate,
            "avg_winner": self.avg_winner,
            "avg_loser": self.avg_loser,
            "has_3x_bet": self.has_3x_bet,
            "bootstrap_sortino": self.bootstrap_sortino,
        }


@dataclass
class SleeveVerdict:
    """Outcome of evaluating a SleeveMetrics against SleeveCriteria."""
    bucket: str                          # "SUCCESS" | "PARTIAL" | "FAIL" | "INDETERMINATE"
    n_success_criteria_met: int
    n_success_criteria_total: int
    failed_criteria: List[str] = field(default_factory=list)
    triggered_kill_criteria: List[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> Dict:
        return {
            "bucket": self.bucket,
            "n_success_criteria_met": self.n_success_criteria_met,
            "n_success_criteria_total": self.n_success_criteria_total,
            "failed_criteria": list(self.failed_criteria),
            "triggered_kill_criteria": list(self.triggered_kill_criteria),
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------- #

def upside_capture(strategy_rets: pd.Series, benchmark_rets: pd.Series) -> float:
    """Strategy return / benchmark return on days when benchmark > 0.

    Following Bacon 2008. Captures whether the sleeve participates in
    the bull. 1.0 = matches; >1 = exceeds; <1 = lags.
    """
    if strategy_rets is None or benchmark_rets is None:
        return 0.0
    aligned = pd.concat([strategy_rets, benchmark_rets], axis=1, join="inner").dropna()
    if aligned.empty:
        return 0.0
    aligned.columns = ["s", "b"]
    up_mask = aligned["b"] > 0
    if up_mask.sum() < 5:
        return 0.0
    s_up = float(aligned.loc[up_mask, "s"].mean())
    b_up = float(aligned.loc[up_mask, "b"].mean())
    if b_up == 0 or not np.isfinite(b_up):
        return 0.0
    return s_up / b_up


def per_trade_stats(trade_pnls: Optional[List[float]]) -> Dict[str, Optional[float | bool]]:
    """Hit rate, avg winner / loser, ≥3x bet flag."""
    if trade_pnls is None or not trade_pnls:
        return {"hit_rate": None, "avg_winner": None, "avg_loser": None, "has_3x_bet": None}
    arr = np.asarray(trade_pnls, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"hit_rate": None, "avg_winner": None, "avg_loser": None, "has_3x_bet": None}
    winners = arr[arr > 0]
    losers = arr[arr < 0]
    hit_rate = float(winners.size / arr.size) if arr.size else 0.0
    avg_winner = float(winners.mean()) if winners.size else 0.0
    avg_loser = float(losers.mean()) if losers.size else 0.0
    # ≥3x means a single trade returned ≥3x its initial size — we don't
    # have initial-size context here, so we use 200% return as proxy
    # (a 3x outcome translates to +200% PnL relative to entry).
    has_3x = bool((arr >= 2.0).any())
    return {
        "hit_rate": hit_rate, "avg_winner": avg_winner,
        "avg_loser": avg_loser, "has_3x_bet": has_3x,
    }


def compute_sleeve_metrics(
    returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    trade_returns: Optional[List[float]] = None,
    *,
    bootstrap_iterations: int = 0,
) -> SleeveMetrics:
    """Compute the sleeve gauntlet metric pack from a sleeve's daily
    returns + optional benchmark + optional per-trade returns."""
    rets = returns.dropna() if returns is not None else pd.Series(dtype=float)
    n = int(len(rets))

    if n < 4:
        return SleeveMetrics(
            sortino=0.0, skewness=0.0, tail_ratio=0.0, upside_capture=0.0,
            max_drawdown=0.0, sharpe=0.0, n_observations=n,
        )

    sortino = MetricsEngine.sortino_ratio(rets)
    sharpe = MetricsEngine.sharpe_ratio(rets)
    skew = MetricsEngine.skewness(rets)
    tail = MetricsEngine.tail_ratio(rets)
    equity = (1.0 + rets).cumprod() * 100.0
    mdd = MetricsEngine.max_drawdown(equity)
    upside = upside_capture(rets, benchmark_returns) if benchmark_returns is not None else 0.0
    trade_stats = per_trade_stats(trade_returns)

    boot = None
    if bootstrap_iterations > 0 and n >= 32:
        boot = MetricsEngine.bootstrap_distribution(
            rets, MetricsEngine.sortino_ratio,
            n_iterations=int(bootstrap_iterations), seed=0,
        )

    return SleeveMetrics(
        sortino=float(sortino),
        skewness=float(skew),
        tail_ratio=float(tail),
        upside_capture=float(upside),
        max_drawdown=float(mdd),
        sharpe=float(sharpe),
        n_observations=n,
        hit_rate=trade_stats["hit_rate"],
        avg_winner=trade_stats["avg_winner"],
        avg_loser=trade_stats["avg_loser"],
        has_3x_bet=trade_stats["has_3x_bet"],
        bootstrap_sortino=boot,
    )


def evaluate_sleeve_gauntlet(
    metrics: SleeveMetrics,
    criteria: SleeveCriteria,
) -> SleeveVerdict:
    """Bucket a SleeveMetrics into SUCCESS / PARTIAL / FAIL / INDETERMINATE."""

    if metrics.n_observations < criteria.min_observations:
        return SleeveVerdict(
            bucket="INDETERMINATE",
            n_success_criteria_met=0,
            n_success_criteria_total=4,
            failed_criteria=[],
            triggered_kill_criteria=[],
            explanation=(
                f"insufficient data: {metrics.n_observations} obs "
                f"< min {criteria.min_observations}"
            ),
        )

    # ----- Kill criteria (any one trigger → FAIL bucket) -----
    kills: List[str] = []
    if metrics.sortino < criteria.sortino_kill:
        kills.append(f"sortino {metrics.sortino:.3f} < kill {criteria.sortino_kill}")
    # max_drawdown is signed negative; -0.40 means 40% drawdown.
    if abs(metrics.max_drawdown) > criteria.max_drawdown_kill:
        kills.append(
            f"|MDD| {abs(metrics.max_drawdown):.3f} > kill {criteria.max_drawdown_kill}"
        )
    if metrics.skewness <= criteria.skewness_kill_below:
        kills.append(
            f"skewness {metrics.skewness:.3f} ≤ kill-floor "
            f"{criteria.skewness_kill_below}"
        )
    if (
        metrics.hit_rate is not None
        and metrics.avg_winner is not None
        and metrics.hit_rate < criteria.hit_rate_kill_below
        and metrics.avg_winner < criteria.avg_winner_kill_below
    ):
        kills.append(
            f"hit_rate {metrics.hit_rate:.3f} < {criteria.hit_rate_kill_below} "
            f"AND avg_winner {metrics.avg_winner:.3f} "
            f"< {criteria.avg_winner_kill_below}"
        )

    # ----- Success criteria -----
    success_checks = [
        ("sortino", metrics.sortino >= criteria.sortino_min_success,
         f"sortino {metrics.sortino:.3f} >= {criteria.sortino_min_success}"),
        ("skewness", metrics.skewness >= criteria.skewness_min_success,
         f"skewness {metrics.skewness:.3f} >= {criteria.skewness_min_success}"),
        ("tail_ratio", metrics.tail_ratio >= criteria.tail_ratio_min_success,
         f"tail_ratio {metrics.tail_ratio:.3f} >= {criteria.tail_ratio_min_success}"),
        ("upside_capture", metrics.upside_capture >= criteria.upside_capture_min_success,
         f"upside_capture {metrics.upside_capture:.3f} "
         f">= {criteria.upside_capture_min_success}"),
    ]
    if criteria.require_min_3x_bet:
        success_checks.append(
            ("has_3x_bet", bool(metrics.has_3x_bet),
             "has at least one 3x bet")
        )

    failed = [name for name, ok, _ in success_checks if not ok]
    n_total = len(success_checks)
    n_met = n_total - len(failed)

    # ----- Bucket -----
    if kills:
        bucket = "FAIL"
    elif n_met == n_total:
        bucket = "SUCCESS"
    elif n_met >= max(3, n_total - 1):
        # All-but-one is PARTIAL — close-to-passing.
        bucket = "PARTIAL"
    else:
        bucket = "FAIL"

    explanation_parts = [f"{n_met}/{n_total} success criteria met"]
    if failed:
        explanation_parts.append(f"failed: {', '.join(failed)}")
    if kills:
        explanation_parts.append(f"kills: {'; '.join(kills)}")

    return SleeveVerdict(
        bucket=bucket,
        n_success_criteria_met=n_met,
        n_success_criteria_total=n_total,
        failed_criteria=failed,
        triggered_kill_criteria=kills,
        explanation=" — ".join(explanation_parts),
    )
