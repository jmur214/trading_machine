"""
engines/engine_a_alpha/edge_taxonomy.py
========================================
Canonical edge-name → category taxonomy.

Lives in Engine A because:
- Engine A produces signals from edges; categorizing them is its concern
- Engine F (governance) consumes the taxonomy for affinity aggregation,
  but consumption ≠ ownership

Pre-2026-05-07 this map lived at `engines/engine_f_governance/regime_tracker.py:94`
and was imported by Engine A's signal_processor — a charter inversion
documented in `health_check.md` 2026-04-06 ("Engine A signal_processor
imports EDGE_CATEGORY_MAP from Engine F's regime_tracker"). The 2026-05-07
relocation moves the map here; both Engine A and Engine F now import
from this canonical location.

Adding new edge categories: append to the dict; keep keys lowercase
substring patterns. Pattern matching is via "pattern in edge_name" — so
"momentum" matches "momentum_edge_v1", "xsec_momentum_edge", etc. Order
matters: more-specific patterns should appear before less-specific ones
(e.g., "xsec_momentum" before "momentum" if both are categories you'd
distinguish — currently they aren't).
"""
from __future__ import annotations

from typing import Dict


# Edge name (substring pattern) → category. Pattern matching is
# substring-in-edge-name; case-sensitive on the edge_name side. See
# `RegimePerformanceTracker.get_learned_affinity` for the consuming
# logic.
EDGE_CATEGORY_MAP: Dict[str, str] = {
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


__all__ = ["EDGE_CATEGORY_MAP"]
