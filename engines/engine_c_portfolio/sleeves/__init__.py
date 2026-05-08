"""Engine C — multi-sleeve abstraction.

Phase 0 (LANDED 2026-05-07):
- ``Sleeve`` ABC + ``SleeveSpec`` / ``SleeveOutput`` dataclasses (interface)
- ``MultiSleeveAggregator`` (combines per-sleeve weights into portfolio map)
- ``TrendFollowingSleeve`` (first concrete sleeve — momentum + inverse-vol)

The aggregator + concrete sleeve are NOT YET wired into
``PortfolioEngine.allocate``. The engine continues to use
``PortfolioPolicy`` directly until a wrapper opts in. Phase 1 of the
sleeve migration plan
(``docs/Measurements/2026-05/path_c_compounder_design_2026_05.md``) will
add the opt-in wrapper.
"""
from __future__ import annotations

from .aggregator import AggregatorResult, MultiSleeveAggregator
from .sleeve_base import (
    RebalanceCadence,
    Sleeve,
    SleeveOutput,
    SleeveSpec,
)
from .trend_following_sleeve import TrendFollowingSleeve

__all__ = [
    "AggregatorResult",
    "MultiSleeveAggregator",
    "RebalanceCadence",
    "Sleeve",
    "SleeveOutput",
    "SleeveSpec",
    "TrendFollowingSleeve",
]
