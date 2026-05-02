"""Engine C — multi-sleeve abstraction (DESIGN ARTIFACT).

This package is currently a design artifact only. The `Sleeve` ABC and
related dataclasses define the interface a multi-sleeve Engine C will
expose; concrete sleeves (Core, Compounder, Moonshot) are not implemented
here. Production wiring is gated by the migration plan in
`docs/Audit/path_c_compounder_design_2026_05.md` (Phases M0–M3).

Until the abstraction lands behind a feature flag, `PortfolioEngine`
continues to use `PortfolioPolicy.allocate()` directly.
"""
from __future__ import annotations

from .sleeve_base import (
    RebalanceCadence,
    Sleeve,
    SleeveOutput,
    SleeveSpec,
)

__all__ = [
    "RebalanceCadence",
    "Sleeve",
    "SleeveOutput",
    "SleeveSpec",
]
