"""
HysteresisFilter — prevents single-bar regime flips.

Generic, reusable per axis. A new state must persist for `confirmation_bars`
consecutive bars before it replaces the confirmed state. Crisis states
(e.g., "shock", "panic") can bypass hysteresis when confidence is high enough.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class HysteresisFilter:
    """State machine that stabilizes raw detector outputs.

    Attributes:
        confirmation_bars: How many consecutive bars a new state must hold.
        bypass_states: States that skip hysteresis if confidence exceeds bypass_threshold.
        bypass_threshold: Minimum confidence for crisis bypass.
    """

    confirmation_bars: int = 3
    bypass_states: Set[str] = field(default_factory=set)
    bypass_threshold: float = 0.90

    # --- internal state ---
    confirmed_state: Optional[str] = field(default=None, init=False)
    pending_state: Optional[str] = field(default=None, init=False)
    pending_count: int = field(default=0, init=False)

    def update(self, raw_state: str, confidence: float = 0.5) -> str:
        """Process a new raw observation and return the stabilized state.

        Args:
            raw_state: The detector's classification for the current bar.
            confidence: The detector's confidence in that classification [0, 1].

        Returns:
            The confirmed (stabilized) state after applying hysteresis.
        """
        # First bar — accept immediately
        if self.confirmed_state is None:
            self.confirmed_state = raw_state
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        # Crisis bypass — promote immediately without waiting
        if raw_state in self.bypass_states and confidence > self.bypass_threshold:
            self.confirmed_state = raw_state
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        # Raw matches confirmed — no transition needed
        if raw_state == self.confirmed_state:
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        # Raw matches pending — continue counting
        if raw_state == self.pending_state:
            self.pending_count += 1
            if self.pending_count >= self.confirmation_bars:
                self.confirmed_state = raw_state
                self.pending_state = None
                self.pending_count = 0
            return self.confirmed_state

        # Raw is something new — start a fresh pending counter
        self.pending_state = raw_state
        self.pending_count = 1
        if self.pending_count >= self.confirmation_bars:
            self.confirmed_state = raw_state
            self.pending_state = None
            self.pending_count = 0
        return self.confirmed_state

    @property
    def is_transitioning(self) -> bool:
        """True if there is an unconfirmed pending state."""
        return self.pending_state is not None and self.pending_count > 0

    @property
    def transition_progress(self) -> float:
        """Fraction of confirmation bars accumulated (0.0 – 1.0)."""
        if not self.is_transitioning:
            return 0.0
        return self.pending_count / self.confirmation_bars

    def reset(self) -> None:
        """Clear all state. Called between backtest runs."""
        self.confirmed_state = None
        self.pending_state = None
        self.pending_count = 0
