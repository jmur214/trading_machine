"""vix_change_5d — 5-business-day percent change in VIX.

`vix_t / vix_{t-5} - 1`. Stress-velocity primitive: rapid rise = fear
regime onset. Substitute for the spec'd `vix_term_structure_slope`
(VIX9D and VIX3M aren't in the project's macro cache; only VIXCLS is).
Ticker-independent — same scalar broadcast to every name; meta-learner
expected to interact with per-ticker beta. Returns None when VIX is
missing or fewer than 6 points are available before `dt`.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..feature import feature
from ..sources.fred_macro import series


@feature(
    feature_id="vix_change_5d",
    tier="B",
    horizon=5,
    license="public",
    source="fred_macro",
    description=(
        "5-business-day percent change in VIX (VIXCLS). Stress-velocity "
        "signal — rapid rise indicates fear regime onset. Substitute "
        "for the unavailable VIX term-structure slope. Ticker-"
        "independent; meta-learner expected to interact with beta."
    ),
)
def vix_change_5d(ticker: str, dt: date) -> Optional[float]:
    s = series("VIXCLS")
    if s is None or s.empty:
        return None
    s = s[s.index <= dt]
    if len(s) < 6:
        return None
    window = s.iloc[-6:].astype(float).values
    v_now = float(window[-1])
    v_then = float(window[0])
    if v_then <= 0:
        return None
    return v_now / v_then - 1.0
