"""engines/engine_f_governance/factor_alpha_gate.py
====================================================
Factor-adjusted α retirement gate for `LifecycleManager` (T-2026-05-12-043).

Background
----------
Pre-T-043, the lifecycle retirement gate compared trade-level Sharpe
to benchmark Sharpe with bootstrap CI. T-036 surfaced that 7 of 11
panel edges are UNIFORMLY NEGATIVE on factor-adjusted α (FF5+Mom) and
should have been auto-retired but weren't — because Sharpe can stay
in the neutral band while α (the truly idiosyncratic signal) is
deeply negative.

The Discovery gauntlet's Gate 6 already requires α t > 2.0 on entry.
This gate makes retirement symmetric: an active edge whose α t-stat
ci_low has been < -2.0 for ≥ N consecutive evaluation cycles gets
retired.

Sustained-for-N-cycles
-----------------------
Single-cycle negative α is too noisy a trigger (FF5+Mom regressions
on per-year data have CIs that straddle zero). We require the gate
to fire for ≥ `sustained_cycles` consecutive cycles before retirement.
This state is persisted to `data/governor/factor_alpha_state.yml`.

State file schema:
  {
    "<edge_id>": {
       "last_seen_ts": "<ISO timestamp>",
       "consecutive_negative_cycles": <int>,
       "last_alpha_tstat_ci_low": <float>,
    },
    ...
  }

CI on the t-stat itself
------------------------
Per CLAUDE.md 6th non-negotiable, the gate compares `ci_low` against
the threshold, not `point_estimate`. We compute the bootstrap CI on
the t-stat directly (not on α-annualized) because the t-stat is the
threshold variable; that's the apples-to-apples comparison.

The bootstrap is a residual moving-block bootstrap (block = lag+1
where lag is the Politis-White auto-lag for Newey-West, n_iter = 1000,
seed = 0). Same convention as `scripts/factor_decomp_per_regime` so
the gate reproduces T-036's verdicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

# Reuse the HAC + Politis-White machinery already used by the
# Discovery gauntlet's Gate 6 and the per-regime decomp.
from scripts.factor_decomp_substrate_honest import (
    FACTOR_COLS,
    INITIAL_CAPITAL,
    newey_west_cov,
    newey_west_lag,
)


@dataclass
class FactorAlphaResult:
    """Output of one evaluation cycle for one edge."""
    ok: bool
    n_obs: int
    alpha_tstat_point: float
    alpha_tstat_ci_low: float
    alpha_tstat_ci_high: float
    reason: str = ""  # e.g. "n_obs<30" when ok=False


def compute_alpha_tstat_with_bootstrap_ci(
    edge_returns: pd.Series,
    factors: pd.DataFrame,
    min_obs: int = 30,
    n_iter: int = 1000,
    seed: int = 0,
) -> FactorAlphaResult:
    """Run FF5+Mom HAC regression with residual block-bootstrap CI on
    the α t-stat.

    Parameters
    ----------
    edge_returns
        Daily returns series for one edge (already divided by
        ``INITIAL_CAPITAL`` if computed from raw PnL). Indexed by date.
    factors
        FF5+Mom factor panel with columns matching ``FACTOR_COLS`` plus
        ``RF``. Indexed by date.
    min_obs
        Minimum sample size for HAC inference. Below this, the gate
        cannot fire (returns ok=False).

    Returns
    -------
    FactorAlphaResult with point + ci_low + ci_high t-stats.
    """
    aligned = pd.concat(
        [edge_returns.rename("edge"), factors],
        axis=1,
        join="inner",
    ).dropna()
    n = len(aligned)
    if n < min_obs:
        return FactorAlphaResult(
            ok=False,
            n_obs=n,
            alpha_tstat_point=0.0,
            alpha_tstat_ci_low=0.0,
            alpha_tstat_ci_high=0.0,
            reason=f"n_obs<{min_obs}",
        )

    excess = (aligned["edge"] - aligned["RF"]).values
    X = aligned[FACTOR_COLS].values
    X_design = np.hstack([np.ones((n, 1)), X])
    coefs, _, _, _ = np.linalg.lstsq(X_design, excess, rcond=None)
    fitted = X_design @ coefs
    resid = excess - fitted

    lag = newey_west_lag(n)
    hac_cov = newey_west_cov(X_design, resid, lag)
    hac_se = np.sqrt(np.maximum(np.diag(hac_cov), 0.0))

    alpha_daily = float(coefs[0])
    alpha_se_daily = float(hac_se[0])
    if alpha_se_daily <= 0:
        return FactorAlphaResult(
            ok=False,
            n_obs=n,
            alpha_tstat_point=0.0,
            alpha_tstat_ci_low=0.0,
            alpha_tstat_ci_high=0.0,
            reason="alpha_se_zero",
        )
    tstat_point = alpha_daily / alpha_se_daily

    # Residual moving-block bootstrap on the t-stat itself
    rng = np.random.default_rng(seed)
    block = max(1, lag + 1)
    n_blocks = int(np.ceil(n / block))
    boot_tstats = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        starts = rng.integers(0, max(1, n - block + 1), size=n_blocks)
        boot_idx = np.concatenate(
            [np.arange(s, s + block) for s in starts]
        )[:n]
        e_star = resid[boot_idx]
        y_star = fitted + e_star
        b_star, _, _, _ = np.linalg.lstsq(X_design, y_star, rcond=None)
        resid_star = y_star - X_design @ b_star
        hac_cov_star = newey_west_cov(X_design, resid_star, lag)
        hac_se_star_alpha = float(np.sqrt(max(hac_cov_star[0, 0], 0.0)))
        if hac_se_star_alpha <= 0:
            boot_tstats[i] = 0.0
        else:
            boot_tstats[i] = float(b_star[0]) / hac_se_star_alpha
    ci_low = float(np.percentile(boot_tstats, 2.5))
    ci_high = float(np.percentile(boot_tstats, 97.5))

    return FactorAlphaResult(
        ok=True,
        n_obs=n,
        alpha_tstat_point=tstat_point,
        alpha_tstat_ci_low=ci_low,
        alpha_tstat_ci_high=ci_high,
    )


def daily_returns_from_closed_trades(
    closed_trades: pd.DataFrame,
    initial_capital: float = INITIAL_CAPITAL,
) -> pd.Series:
    """Sum closed-trade `pnl` by date, divide by initial_capital.

    Matches the convention in `tier_classifier.py` and the per-regime
    decomp pipeline. Caller is responsible for filtering `closed_trades`
    to a single edge_id and to closed trades only (pnl notna).
    """
    if closed_trades.empty:
        return pd.Series(dtype=float)
    sub = closed_trades.copy()
    sub["pnl"] = pd.to_numeric(sub["pnl"], errors="coerce")
    sub = sub.dropna(subset=["pnl"])
    sub["date"] = pd.to_datetime(sub["timestamp"]).dt.normalize()
    daily = sub.groupby("date")["pnl"].sum() / initial_capital
    daily = daily.sort_index()
    return daily


# -------------------- state persistence -------------------- #

def load_state(path: Path) -> Dict[str, Dict]:
    """Load the per-edge consecutive-cycles state file.

    Returns an empty dict if the file is missing or unreadable. Never
    raises — state corruption should not block the lifecycle.
    """
    try:
        if not path.exists():
            return {}
        text = path.read_text()
        if not text.strip():
            return {}
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_state(path: Path, state: Dict[str, Dict]) -> None:
    """Persist state to disk. Atomic-ish via write-then-rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(state, sort_keys=True))
    tmp.replace(path)


def update_state_for_edge(
    state: Dict[str, Dict],
    edge_id: str,
    result: FactorAlphaResult,
    threshold: float,
    as_of_ts: str,
) -> Tuple[int, Dict]:
    """Apply a single-cycle observation to per-edge state.

    Returns (new_consecutive_count, updated_state). Caller persists.

    The counter increments only on `ok=True` AND `ci_low < threshold`.
    On `ok=False` (e.g. insufficient data) the counter stays put (we
    can't make a decision either way). On `ci_low >= threshold` the
    counter resets to 0 — recovery breaks the streak.
    """
    prior = state.get(edge_id, {})
    prior_count = int(prior.get("consecutive_negative_cycles", 0))

    if not result.ok:
        # Indeterminate cycle: leave counter alone, record observation.
        new_count = prior_count
    elif result.alpha_tstat_ci_low < threshold:
        new_count = prior_count + 1
    else:
        # Recovery: reset.
        new_count = 0

    state[edge_id] = {
        "last_seen_ts": as_of_ts,
        "consecutive_negative_cycles": new_count,
        "last_alpha_tstat_point": result.alpha_tstat_point,
        "last_alpha_tstat_ci_low": result.alpha_tstat_ci_low,
        "last_alpha_tstat_ci_high": result.alpha_tstat_ci_high,
        "last_n_obs": result.n_obs,
        "last_ok": result.ok,
    }
    return new_count, state


def gate_fires(
    new_consecutive_count: int,
    sustained_cycles_required: int,
) -> bool:
    """Pure: did the consecutive-cycles threshold get met?"""
    return new_consecutive_count >= sustained_cycles_required


def check_factor_alpha_retirement(
    edge_id: str,
    closed_trades_for_edge: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    state_path: Path,
    t_threshold: float = -2.0,
    sustained_cycles_required: int = 2,
    min_obs: int = 30,
    n_iter: int = 1000,
    seed: int = 0,
    initial_capital: float = INITIAL_CAPITAL,
    as_of_ts: Optional[str] = None,
) -> Tuple[bool, str, FactorAlphaResult, int]:
    """End-to-end factor-α retirement gate.

    Returns (fired, reason, result, new_consecutive_count).

    Side effect: updates state file on disk with this cycle's
    observation. Does NOT touch edges.yml — caller decides whether to
    transition the edge based on the (fired, reason) tuple.
    """
    if as_of_ts is None:
        as_of_ts = pd.Timestamp.now(tz="UTC").isoformat()

    returns = daily_returns_from_closed_trades(
        closed_trades_for_edge, initial_capital=initial_capital,
    )
    result = compute_alpha_tstat_with_bootstrap_ci(
        returns, factors, min_obs=min_obs, n_iter=n_iter, seed=seed,
    )

    state = load_state(state_path)
    new_count, state = update_state_for_edge(
        state, edge_id, result, t_threshold, as_of_ts,
    )
    save_state(state_path, state)

    if not result.ok:
        return False, f"insufficient_data_{result.reason}", result, new_count

    fired = gate_fires(new_count, sustained_cycles_required)
    if fired:
        reason = (
            f"factor_alpha_negative_sustained "
            f"ci_low={result.alpha_tstat_ci_low:.2f} "
            f"point={result.alpha_tstat_point:.2f} "
            f"cycles={new_count}/{sustained_cycles_required} "
            f"threshold={t_threshold:.2f}"
        )
    else:
        reason = (
            f"below_sustained_threshold "
            f"ci_low={result.alpha_tstat_ci_low:.2f} "
            f"cycles={new_count}/{sustained_cycles_required}"
        )
    return fired, reason, result, new_count
