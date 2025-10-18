# engines/engine_a_alpha/signal_formatter.py
"""
SignalFormatter
---------------

Turn continuous aggregate score into a discrete side + strength.

Rules
-----
- |score| < exit_threshold  -> no signal
- |score| >= enter_threshold -> side = sign(score), strength = |score| in [0,1]
- In the "grey band" (exit_threshold .. enter_threshold), we emit nothing
  (let existing positions persist; Engine B handles stop/TP logic).

This keeps Alpha focused on *directional intent*, while Engine B sizes risk.
"""

from __future__ import annotations

from typing import Optional, Tuple


class SignalFormatter:
    def __init__(self, enter_threshold: float, exit_threshold: float, min_edge_contribution: float):
        self.enter_threshold = float(enter_threshold)
        self.exit_threshold = float(exit_threshold)
        self.min_edge_contribution = float(min_edge_contribution)

    @staticmethod
    def _sign(x: float) -> int:
        return 1 if x > 0 else (-1 if x < 0 else 0)

    def to_side_and_strength(self, score: float) -> tuple[Optional[str], float]:
        a = float(score)
        mag = abs(a)
        if mag < self.exit_threshold:
            return None, 0.0
        if mag >= self.enter_threshold:
            side = "long" if a > 0 else "short"
            return side, min(1.0, mag)
        # grey zone: do nothing
        return None, 0.0