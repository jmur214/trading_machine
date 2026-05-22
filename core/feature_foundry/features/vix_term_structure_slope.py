"""vix_term_structure_slope — VIX / VIX3M ratio.

For date `dt`, compute `VIX / VIX3M`. Contango (ratio < 1) is the
normal regime: longer-dated implied vol > spot vol → vol carry trades
profit. Backwardation (ratio > 1) signals near-term stress > long-term
expectation → risk-off / de-grossing regime.

Per T-2026-05-12-052 research convergence (4 independent dives all
flagged this as the minimum-effective vol-carry regime signal):
- Contango (ratio < 1, typically 0.85-0.95): normal, vol-short
  strategies profit.
- Near-flat (0.95-1.0): tape neutralizing; pre-stress accumulation.
- Backwardation (> 1.0): active vol shock; canonical de-grossing
  trigger. The most reliable single-signal regime classifier in the
  retail toolkit per Bilello (2022), Bouchaud (2024).

Data source: FRED daily series VIX (CBOE Volatility Index, VIXCLS
spot) and VIX3M (CBOE 3-Month Volatility Index). Both daily close,
available T+0 EOD → usable at T+1 open. Ticker-independent (macro
state). Returns None when either series is missing or has insufficient
history before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="vix_term_structure_slope",
    tier="A",
    horizon=5,
    license="public",
    source="fred_macro",
    description=(
        "VIX/VIX3M ratio. Vol-carry / risk-off identifier. Contango (<1) "
        "= normal; backwardation (>1) = stress. Canonical regime "
        "primitive per T-052 4-signal ensemble research."
    ),
)
def vix_term_structure_slope(ticker: str, dt: date) -> Optional[float]:
    vix = series("VIX")
    if vix is None or vix.empty:
        vix = series("VIXCLS")
    vix3m = series("VIX3M")
    if vix is None or vix3m is None or vix.empty or vix3m.empty:
        return None
    vix = vix[vix.index <= dt]
    vix3m = vix3m[vix3m.index <= dt]
    if vix.empty or vix3m.empty:
        return None
    v_spot = float(vix.iloc[-1])
    v_3m = float(vix3m.iloc[-1])
    if v_3m <= 0:
        return None
    return v_spot / v_3m
