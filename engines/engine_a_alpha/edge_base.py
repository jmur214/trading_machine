# engines/engine_a_alpha/edge_base.py
from __future__ import annotations
from typing import Dict, Any
import pandas as pd

class EdgeBase:
    """
    Minimal contract all edges must follow.
    AlphaEngine will call .compute_signals(prices, as_of, **params) and
    expect a dict: {ticker: signal in {-1, 0, 1}} (or floats for strength).
    """
    def __init__(self):
        self.params: Dict[str, Any] = {}

    def set_params(self, params: Dict[str, Any]) -> None:
        self.params = params or {}

    def compute_signals(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> Dict[str, float]:
        raise NotImplementedError