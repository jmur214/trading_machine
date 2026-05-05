"""Path C overlays — standalone risk-overlay helpers for the compounder backtest.

Why this module exists
----------------------
The Path C compounder script (``scripts/path_c_synthetic_compounder.py``)
is intentionally standalone: it does NOT import the production
backtester so that feasibility tests can run without dragging in
governor/regime/strategy state.

The production overlays we want to test live in
``engines/engine_c_portfolio/policy.py``:
  - ``PortfolioPolicy._apply_vol_target``  (lines ~311-331)
  - ``PortfolioPolicy._apply_exposure_cap`` (lines ~334-356)

Rather than instantiating PortfolioPolicy with a fake config and
pulling in its dependency tree, we port the math here as small,
pure functions that operate on plain dicts and DataFrames. This
keeps Path C's "no production-engine imports" property intact and
makes the overlay easy to unit-test.

The math is intentionally identical to PortfolioPolicy's, including
clip ranges, lookback defaults, and renormalisation behaviour.

Public surface
--------------
- ``estimate_portfolio_vol``  — annualized vol from weights + returns
- ``apply_vol_target``        — scale weights to hit a target vol
- ``apply_exposure_cap``      — hard-cap gross exposure (regime-free)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Defaults — match PortfolioPolicy / config/portfolio_settings.json spec
# ----------------------------------------------------------------------

DEFAULT_TARGET_VOL = 0.15        # annualized — matches portfolio_settings.json
DEFAULT_VOL_LOOKBACK = 60        # trading days — matches PortfolioPolicy default
                                 # (production settings use 20, but the task spec
                                 # for this overlay calls for 60-day lookback.
                                 # 60d is the more academically defensible window
                                 # for a vol-target overlay on annual-rebal portfolios.)
SCALAR_CLIP_LOW = 0.3            # don't de-leverage below 30% of intended size
SCALAR_CLIP_HIGH = 2.0           # don't lever above 2x


@dataclass
class VolOverlayDiagnostics:
    """Per-rebalance overlay diagnostics — used for clip-frequency analysis.

    Each rebalance produces one of these. The harness aggregates them
    into "how often did vol overlay scale up vs down vs stay neutral?"
    summary stats.
    """
    asof: pd.Timestamp
    n_holdings: int
    estimated_port_vol: float
    target_vol: float
    raw_scalar: float            # pre-clip — diagnostic only
    applied_scalar: float        # post-clip — what actually got applied
    gross_before: float          # pre-overlay sum of |weights|
    gross_after: float           # post-overlay sum of |weights|

    @property
    def clip_state(self) -> str:
        """Categorize the overlay action this rebalance.

        - ``upper_clip``  — raw scalar hit the SCALAR_CLIP_HIGH ceiling
        - ``lower_clip``  — raw scalar hit the SCALAR_CLIP_LOW floor
        - ``neutral``     — scalar within ~1% of 1.0 (no material change)
        - ``levered_up``  — applied >1.0 (post-clip), no clip
        - ``de_levered``  — applied <1.0 (post-clip), no clip
        """
        if abs(self.applied_scalar - 1.0) < 0.01:
            return "neutral"
        if self.applied_scalar >= SCALAR_CLIP_HIGH - 1e-9:
            return "upper_clip"
        if self.applied_scalar <= SCALAR_CLIP_LOW + 1e-9:
            return "lower_clip"
        if self.applied_scalar > 1.0:
            return "levered_up"
        return "de_levered"


# ----------------------------------------------------------------------
# Vol estimation
# ----------------------------------------------------------------------

def estimate_portfolio_vol(
    weights: Dict[str, float],
    prices: pd.DataFrame,
    asof: pd.Timestamp,
    lookback: int = DEFAULT_VOL_LOOKBACK,
    fallback: float = DEFAULT_TARGET_VOL,
) -> float:
    """Estimate annualized portfolio volatility from a wide price panel.

    Mirrors PortfolioPolicy._estimate_portfolio_vol but operates on a
    wide DataFrame (date x ticker) instead of a per-ticker dict.

    Steps:
      1. Filter to non-zero-weight tickers present in ``prices.columns``.
      2. Build the daily-return panel, last ``lookback`` observations
         ending at ``asof``.
      3. Compute the annualized cov matrix (252-day) on that window.
      4. Portfolio variance = w' @ Cov @ w; take sqrt.

    Returns ``fallback`` if there's insufficient history (< 5 valid days
    after dropna) or fewer than 2 tickers in the panel.

    Parameters
    ----------
    weights : Dict[str, float]
        Ticker -> weight. Zero-weight or near-zero entries are skipped.
    prices : pd.DataFrame
        Wide price panel; index = dates, columns = tickers.
    asof : pd.Timestamp
        Estimate vol AS OF this date — only data <= asof is used.
    lookback : int
        Trading-day window (default 60).
    fallback : float
        Returned when vol can't be estimated.

    Returns
    -------
    Annualized portfolio vol (float). Always >= 0.
    """
    if not weights:
        return fallback

    active = [t for t in weights if t in prices.columns and abs(weights[t]) > 1e-9]
    if len(active) < 2:
        # Single-name or empty: fall back to that asset's own vol if we
        # have it, else the fallback constant.
        if len(active) == 1:
            t = active[0]
            sub = prices.loc[:asof, t].pct_change().dropna().tail(lookback)
            if len(sub) >= 5:
                return float(sub.std() * np.sqrt(252))
        return fallback

    # Slice price panel up to as_of, then take the last `lookback` rows.
    panel = prices.loc[:asof, active].copy()
    rets = panel.pct_change().dropna(how="all").tail(lookback)
    rets = rets.dropna(axis=0, how="any")  # require all tickers on each row

    if len(rets) < 5:
        return fallback

    cov = rets.cov() * 252.0
    w_arr = np.array([weights.get(t, 0.0) for t in cov.columns], dtype=float)
    port_var = float(w_arr @ cov.values @ w_arr)
    return float(np.sqrt(max(port_var, 1e-12)))


# ----------------------------------------------------------------------
# Vol overlay
# ----------------------------------------------------------------------

def apply_vol_target(
    weights: Dict[str, float],
    prices: pd.DataFrame,
    asof: pd.Timestamp,
    target_vol: float = DEFAULT_TARGET_VOL,
    lookback: int = DEFAULT_VOL_LOOKBACK,
    clip_low: float = SCALAR_CLIP_LOW,
    clip_high: float = SCALAR_CLIP_HIGH,
) -> Tuple[Dict[str, float], VolOverlayDiagnostics]:
    """Scale weights to hit `target_vol`, clipped to [clip_low, clip_high].

    Mirrors PortfolioPolicy._apply_vol_target but is regime/governor
    free and reports diagnostics.

    Behaviour:
      - Estimates current portfolio vol via ``estimate_portfolio_vol``.
      - raw_scalar = target_vol / port_vol
      - applied_scalar = clip(raw_scalar, [clip_low, clip_high])
      - new_weights = applied_scalar * old_weights
      - Gross may end up > 1.0 (intentional — this is leverage) or
        < 1.0 (de-leveraged) depending on the regime.
      - DOES NOT renormalise to 1.0. The whole point of vol-targeting
        is to LET gross exposure float to whatever realised-vol implies.

    Returns
    -------
    (scaled_weights, diagnostics) — diagnostics include raw vs applied
    scalar so the caller can count clip events.
    """
    if not weights:
        diag = VolOverlayDiagnostics(
            asof=pd.Timestamp(asof),
            n_holdings=0,
            estimated_port_vol=0.0,
            target_vol=target_vol,
            raw_scalar=1.0,
            applied_scalar=1.0,
            gross_before=0.0,
            gross_after=0.0,
        )
        return weights, diag

    gross_before = sum(abs(w) for w in weights.values())
    n = sum(1 for w in weights.values() if abs(w) > 1e-9)

    port_vol = estimate_portfolio_vol(
        weights, prices, asof, lookback=lookback, fallback=target_vol
    )

    if port_vol < 1e-9:
        # Degenerate; return unchanged
        diag = VolOverlayDiagnostics(
            asof=pd.Timestamp(asof),
            n_holdings=n,
            estimated_port_vol=port_vol,
            target_vol=target_vol,
            raw_scalar=1.0,
            applied_scalar=1.0,
            gross_before=gross_before,
            gross_after=gross_before,
        )
        return weights, diag

    raw_scalar = float(target_vol / port_vol)
    applied_scalar = float(np.clip(raw_scalar, clip_low, clip_high))

    new_weights = {t: w * applied_scalar for t, w in weights.items()}
    gross_after = sum(abs(w) for w in new_weights.values())

    diag = VolOverlayDiagnostics(
        asof=pd.Timestamp(asof),
        n_holdings=n,
        estimated_port_vol=port_vol,
        target_vol=target_vol,
        raw_scalar=raw_scalar,
        applied_scalar=applied_scalar,
        gross_before=gross_before,
        gross_after=gross_after,
    )
    return new_weights, diag


# ----------------------------------------------------------------------
# Exposure cap (regime-free standalone version)
# ----------------------------------------------------------------------

def apply_exposure_cap(
    weights: Dict[str, float],
    cap: float = 1.0,
) -> Dict[str, float]:
    """Hard-cap gross exposure at `cap`.

    Path C has no Engine E regime feed, so this is the simpler
    regime-free version of PortfolioPolicy._apply_exposure_cap.

    If gross |weights| <= cap, no-op.
    Otherwise scale weights uniformly so gross == cap.

    For the current Cell E test we DO NOT use this overlay. The vol
    overlay alone is the clean test of MDD rescue. This is here for
    a possible Cell F follow-up.
    """
    if not weights:
        return weights
    gross = sum(abs(w) for w in weights.values())
    if gross <= cap or gross < 1e-9:
        return weights
    scale = cap / gross
    return {t: w * scale for t, w in weights.items()}


# ----------------------------------------------------------------------
# Diagnostics aggregation
# ----------------------------------------------------------------------

def summarize_overlay_diagnostics(
    diags: list[VolOverlayDiagnostics],
) -> Dict[str, float]:
    """Aggregate per-rebalance diagnostics into clip-frequency summary stats.

    Returns a dict suitable for embedding in the harness summary JSON.
    """
    if not diags:
        return {}

    states: Dict[str, int] = {
        "neutral": 0,
        "levered_up": 0,
        "de_levered": 0,
        "upper_clip": 0,
        "lower_clip": 0,
    }
    for d in diags:
        states[d.clip_state] = states.get(d.clip_state, 0) + 1

    applied = np.array([d.applied_scalar for d in diags])
    raw = np.array([d.raw_scalar for d in diags])
    port_vols = np.array([d.estimated_port_vol for d in diags])
    gross_after = np.array([d.gross_after for d in diags])

    n = len(diags)
    return {
        "n_rebalances": n,
        "clip_state_counts": states,
        "clip_state_fractions": {k: v / n for k, v in states.items()},
        "raw_scalar_mean": float(raw.mean()),
        "raw_scalar_min": float(raw.min()),
        "raw_scalar_max": float(raw.max()),
        "applied_scalar_mean": float(applied.mean()),
        "applied_scalar_min": float(applied.min()),
        "applied_scalar_max": float(applied.max()),
        "estimated_port_vol_mean": float(port_vols.mean()),
        "estimated_port_vol_min": float(port_vols.min()),
        "estimated_port_vol_max": float(port_vols.max()),
        "gross_after_mean": float(gross_after.mean()),
        "gross_after_min": float(gross_after.min()),
        "gross_after_max": float(gross_after.max()),
    }
