"""
RegimeHistoryStore — tracks regime state over time for duration,
flip frequency, and empirical transition matrix computation.
"""

import os
from collections import defaultdict
from typing import Dict, List, Optional

import pandas as pd


class RegimeHistoryStore:
    """In-memory store that grows one row per bar.

    Tracks:
      - Duration: consecutive bars in current state per axis
      - Flip frequency: rolling count of state transitions per axis in last N bars
      - Empirical transition matrix: P(macro_regime_{t+1} | macro_regime_t)
    """

    # Columns stored per row
    AXES = ["trend", "volatility", "correlation", "breadth", "forward_stress"]
    CONFIDENCE_COLS = [f"{a}_confidence" for a in AXES]
    CORE_COLS = (
        ["timestamp"] + AXES + CONFIDENCE_COLS
        + ["macro_regime", "transition_risk", "regime_stability"]
    )

    def __init__(self, flip_lookback: int = 30, transition_min_bars: int = 100):
        self._rows: List[dict] = []
        self._durations: Dict[str, int] = {a: 0 for a in self.AXES}
        self._flip_lookback = flip_lookback
        self._transition_min_bars = transition_min_bars

    def append(self, row: dict) -> None:
        """Append a single bar's regime snapshot.

        Args:
            row: Must contain keys for all AXES (state strings),
                 confidence cols, macro_regime, transition_risk, regime_stability.
        """
        # Update durations
        if self._rows:
            prev = self._rows[-1]
            for axis in self.AXES:
                if row.get(axis) == prev.get(axis):
                    self._durations[axis] += 1
                else:
                    self._durations[axis] = 1
        else:
            for axis in self.AXES:
                self._durations[axis] = 1

        self._rows.append(row)

    @property
    def axis_durations(self) -> Dict[str, int]:
        """Consecutive bars in current state per axis."""
        return dict(self._durations)

    def flip_counts(self, lookback: Optional[int] = None) -> Dict[str, int]:
        """Count state transitions per axis in the last `lookback` bars."""
        lb = lookback or self._flip_lookback
        if len(self._rows) < 2:
            return {a: 0 for a in self.AXES}

        recent = self._rows[-lb:]
        counts = {a: 0 for a in self.AXES}
        for i in range(1, len(recent)):
            for axis in self.AXES:
                if recent[i].get(axis) != recent[i - 1].get(axis):
                    counts[axis] += 1
        return counts

    def get_transition_matrix(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Compute empirical transition probabilities between macro regimes.

        Returns P(next_macro | current_macro) as nested dict, or None if
        insufficient data (< transition_min_bars).
        """
        if len(self._rows) < self._transition_min_bars:
            return None

        transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for i in range(1, len(self._rows)):
            from_state = self._rows[i - 1].get("macro_regime", "unknown")
            to_state = self._rows[i].get("macro_regime", "unknown")
            transitions[from_state][to_state] += 1

        # Normalize rows to probabilities
        probs: Dict[str, Dict[str, float]] = {}
        for from_state, targets in transitions.items():
            total = sum(targets.values())
            probs[from_state] = {
                to_state: round(count / total, 3)
                for to_state, count in targets.items()
            }
        return probs

    def to_dataframe(self) -> pd.DataFrame:
        """Export history as a DataFrame for analysis or persistence."""
        if not self._rows:
            return pd.DataFrame(columns=self.CORE_COLS)
        return pd.DataFrame(self._rows)

    def save_csv(self, path: str) -> None:
        """Save history to CSV."""
        df = self.to_dataframe()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)

    def __len__(self) -> int:
        return len(self._rows)

    def reset(self) -> None:
        """Clear all state. Called between backtest runs."""
        self._rows.clear()
        self._durations = {a: 0 for a in self.AXES}
