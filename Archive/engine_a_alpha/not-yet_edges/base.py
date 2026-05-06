# engines/engine_a_alpha/edges/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Signal:
    """
    Canonical signal structure flowing from edges -> Alpha/Risk.

    Required fields:
      - ticker: str
      - side: "long" | "short" | "exit"  (directional intent)
      - confidence: float in [0, 1]       (soft strength hint; Risk may scale)
      - edge_id: a stable identifier for the edge (e.g., "rsi_mean_reversion_v1")
      - category: "technical" | "news" | "true" | "other"

    Optional:
      - price_hint: reference price at decision time (not a fill price)
      - meta: free-form dict for dashboards/explainability
    """
    ticker: str
    side: str
    confidence: float
    edge_id: str
    category: str
    price_hint: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "ticker": self.ticker,
            "side": self.side,
            "confidence": float(self.confidence),
            "edge_id": self.edge_id,
            "category": self.category,
        }
        if self.price_hint is not None:
            d["price_hint"] = float(self.price_hint)
        if self.meta:
            d["meta"] = self.meta
        return d


class BaseEdge(ABC):
    """
    Abstract base for all edges. Subclasses must implement `generate_signals`.
    """

    EDGE_ID: str = "base_edge"
    CATEGORY: str = "other"

    def __init__(self, params: Optional[Dict[str, Any]] = None) -> None:
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, slice_map, ts) -> List[Dict[str, Any]]:
        """
        Produce a list of signal dicts (or Signal objects converted to dicts) at time `ts`
        using historical data in `slice_map` (ticker -> DataFrame with OHLC columns).
        """
        ...

    def explain(self, signal: Dict[str, Any]) -> str:
        """
        Optional: return a short human-readable explanation for dashboards.
        """
        eid = signal.get("edge_id", self.EDGE_ID)
        tkr = signal.get("ticker", "?")
        side = signal.get("side", "?")
        return f"[{eid}] {tkr}: {side}"

    def describe(self) -> Dict[str, Any]:
        """
        Optional: structured metadata for registries/governor.
        """
        return {
            "edge_id": self.EDGE_ID,
            "category": self.CATEGORY,
            "params": self.params,
            "version": "1.0.0",
        }