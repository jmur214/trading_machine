# engines/engine_a_alpha/edge_base.py
from __future__ import annotations
from typing import Dict, Any
import numpy as np
import pandas as pd


class EdgeBase:
    """
    Minimal contract all edges must follow.
    AlphaEngine will call .compute_signals(prices, as_of, **params) and
    expect a dict: {ticker: signal in {-1, 0, 1}} (or floats for strength).
    """
    def __init__(self):
        self.params: Dict[str, Any] = {}
        self.regime_meta: Dict[str, Any] | None = None
        self._adv_skip_count: Dict[str, int] = {}

    def set_params(self, params: Dict[str, Any]) -> None:
        self.params = params or {}

    def compute_signals(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> Dict[str, float]:
        raise NotImplementedError

    def _below_adv_floor(
        self,
        df: pd.DataFrame,
        min_adv_usd: float | None,
        ticker: str = "",
        window: int = 20,
    ) -> bool:
        """ADV-floor precondition gate.

        Returns True iff the floor is set AND the ticker's rolling
        ``window``-day median dollar-volume (Close × Volume) is below it.

        No-op (returns False) when:
          * ``min_adv_usd`` is None / 0 / non-positive / NaN
          * the DataFrame lacks ``Close`` or ``Volume``
          * fewer than ``window`` bars are available
          * the rolling median is non-finite

        Side effect: increments ``self._adv_skip_count[ticker]`` on every skip
        for diagnostic introspection via ``get_adv_skip_summary()``.

        Backward-compat: with no min_adv_usd parameter set, every edge
        behaves identically to its pre-floor implementation.
        """
        if min_adv_usd is None:
            return False
        try:
            floor = float(min_adv_usd)
        except (TypeError, ValueError):
            return False
        if floor <= 0 or not np.isfinite(floor):
            return False

        if "Close" not in df.columns or "Volume" not in df.columns:
            return False
        if len(df) < window:
            return False

        try:
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            dv = (close * volume).tail(window)
            median_dv = float(dv.median())
        except Exception:
            return False

        if not np.isfinite(median_dv):
            return False

        if median_dv < floor:
            self._adv_skip_count[ticker] = self._adv_skip_count.get(ticker, 0) + 1
            return True
        return False

    def get_adv_skip_summary(self) -> Dict[str, int]:
        """Return a copy of per-ticker ADV-floor skip counts."""
        return dict(self._adv_skip_count)

    def reset_adv_skip_summary(self) -> None:
        """Clear the per-ticker skip counter."""
        self._adv_skip_count.clear()
