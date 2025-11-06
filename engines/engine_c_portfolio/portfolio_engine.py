# engines/engine_c_portfolio/portfolio_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from debug_config import is_debug_enabled, is_info_enabled

from .policy import PortfolioPolicy, PortfolioPolicyConfig


@dataclass
class Position:
    qty: int = 0                 # signed qty: long >0, short <0
    avg_price: float = 0.0
    stop: float | None = None
    take_profit: float | None = None
    # edge metadata (for attribution)
    edge: Optional[str] = None
    edge_group: Optional[str] = None
    edge_id: Optional[str] = None
    edge_category: Optional[str] = None

# Helper accessor to present Position as dict for downstream compatibility
def _as_dict(pos: "Position") -> dict:
    return {
        "qty": pos.qty,
        "avg_price": pos.avg_price,
        "stop": pos.stop,
        "take_profit": pos.take_profit,
        "edge": pos.edge,
        "edge_group": pos.edge_group,
        "edge_id": pos.edge_id,
        "edge_category": pos.edge_category,
    }


class PortfolioEngine:
    """
    Core accounting and allocation layer.
    - Tracks signed-qty positions, cash, realized/unrealized PnL.
    - Computes target weights via PortfolioPolicy (Engine C).
    - Ensures accounting identity: equity = cash + Σ(qty * price).
    """

    def __init__(self, initial_capital: float, policy_cfg: Optional[PortfolioPolicyConfig] = None):
        self.cash: float = float(initial_capital)
        self.realized_pnl: float = 0.0
        self.positions: Dict[str, Position] = {}
        self.history: List[dict] = []
        self.policy = PortfolioPolicy(policy_cfg or PortfolioPolicyConfig())
        self.current_target_weights: Dict[str, float] = {}

    def _log_debug(self, msg: str):
        if is_debug_enabled("PORTFOLIO"):
            print(f"[PORTFOLIO][DEBUG] {msg}")

    def _log_info(self, msg: str):
        if is_info_enabled("PORTFOLIO"):
            print(f"[PORTFOLIO][INFO] {msg}")

    # --------- core ops ---------
    def _get_or_new(self, ticker: str) -> Position:
        return self.positions.get(ticker, Position())

    def apply_fill(self, fill: dict) -> None:
        """
        Apply a simulated or real fill.
        fill keys:
          ticker, side ∈ {'long','short','exit','cover'}, qty, price
          optional: commission, stop, take_profit
        """
        ticker = str(fill.get("ticker"))
        side = str(fill.get("side", "")).lower()
        qty_raw = int(fill.get("qty", 0))
        price = fill.get("price", None)
        if price is None:
            price = fill.get("fill_price", None)
        if price is None and "bar" in fill:
            # allow passing current bar dict/Series
            bar = fill["bar"]
            price = float(bar["Open"]) if isinstance(bar, dict) else float(getattr(bar, "Open", getattr(bar, "open", np.nan)))
        price = float(price)
        commission = float(fill.get("commission", 0.0))

        meta_edge = fill.get("edge")
        meta_edge_group = fill.get("edge_group") or fill.get("edge_category")  # tolerate older key
        meta_edge_id = fill.get("edge_id")
        meta_edge_category = fill.get("edge_category")

        if not ticker or qty_raw <= 0:
            return

        self._log_info(f"Applying fill: ticker={ticker}, side={side}, qty={qty_raw}, price={price}")

        pos = self._get_or_new(ticker)

        if side == "exit" and pos.qty < 0:
            side = "cover"

        # ---- CLOSE / REDUCE ----
        if side in ("exit", "cover"):
            if pos.qty == 0:
                return
            exit_qty = min(abs(pos.qty), qty_raw)
            was_long = pos.qty > 0
            sign = 1 if was_long else -1

            if was_long:
                self.cash += exit_qty * price
            else:
                self.cash -= exit_qty * price

            realized = (price - pos.avg_price) * (exit_qty * sign)
            self.realized_pnl += realized
            self._log_info(f"Realized PnL from closing: {realized:.2f}")
            self.cash -= commission

            remaining = abs(pos.qty) - exit_qty
            if remaining > 0:
                pos.qty = remaining * sign
            else:
                # fully closed; reset position container
                pos = Position()
            self.positions[ticker] = pos
            self._log_info(f"Updated position for {ticker}: qty={pos.qty}, avg_price={pos.avg_price}")
            return

        # ---- OPEN / ADD ----
        if side not in ("long", "short"):
            return

        signed_qty = qty_raw if side == "long" else -qty_raw
        if signed_qty > 0:
            self.cash -= signed_qty * price
        else:
            self.cash += abs(signed_qty) * price
        self.cash -= commission

        # Same-direction add (or opening new)
        if pos.qty == 0 or (pos.qty > 0 and signed_qty > 0) or (pos.qty < 0 and signed_qty < 0):
            new_abs = abs(pos.qty) + abs(signed_qty)
            total_cost = (abs(pos.qty) * pos.avg_price) + (abs(signed_qty) * price)
            pos.qty += signed_qty
            pos.avg_price = (total_cost / new_abs) if new_abs > 0 else 0.0
            # capture/refresh metadata on open or add if none present
            if meta_edge is not None:
                pos.edge = meta_edge
            if meta_edge_group is not None:
                pos.edge_group = meta_edge_group
            if meta_edge_id is not None:
                pos.edge_id = meta_edge_id
            if meta_edge_category is not None:
                pos.edge_category = meta_edge_category
        else:
            # Opposite-direction order: first close against existing, realize PnL
            closing = min(abs(pos.qty), abs(signed_qty))
            sign = 1 if pos.qty > 0 else -1
            realized = (price - pos.avg_price) * (closing * sign)
            self.realized_pnl += realized
            self._log_info(f"Realized PnL from closing: {realized:.2f}")

            net_abs = abs(pos.qty) - closing
            if net_abs > 0:
                # partially reduced, keep original side and avg price
                pos.qty = net_abs * sign
            else:
                # fully flattened by the closing portion
                excess = abs(signed_qty) - closing
                if excess > 0:
                    # flip to new side with remaining excess at current price
                    pos.qty = excess * (-sign)
                    pos.avg_price = price
                    # overwrite metadata to new trade's meta
                    pos.edge = meta_edge
                    pos.edge_group = meta_edge_group
                    pos.edge_id = meta_edge_id
                    pos.edge_category = meta_edge_category
                else:
                    # exactly flat
                    pos = Position()

        if fill.get("stop") is not None:
            pos.stop = float(fill["stop"])
        if fill.get("take_profit") is not None:
            pos.take_profit = float(fill["take_profit"])
        self.positions[ticker] = pos
        self._log_info(f"Updated position for {ticker}: qty={pos.qty}, avg_price={pos.avg_price}")
        return

    # ------------------------------------------------------------------ #
    def snapshot(self, timestamp, price_map: Dict[str, float]) -> dict:
        market_value = 0.0
        unrealized = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = float(price_map.get(t, pos.avg_price if pos.avg_price else 0.0))
            market_value += pos.qty * px
            unrealized += (px - pos.avg_price) * pos.qty

        equity = self.cash + market_value
        snap = {
            "timestamp": pd.to_datetime(timestamp),
            "cash": round(self.cash, 2),
            "market_value": round(market_value, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(equity, 2),
            "positions": sum(1 for p in self.positions.values() if p.qty != 0),
        }
        # optional quick-look attribution (counts of open positions by edge)
        try:
            edge_counts = {}
            for t, p in self.positions.items():
                if p.qty == 0:
                    continue
                key = p.edge or "unknown"
                edge_counts[key] = edge_counts.get(key, 0) + 1
            snap["open_pos_by_edge"] = edge_counts
        except Exception:
            pass
        self.history.append(snap)
        self._log_debug(f"Snapshot recorded: {snap}")
        return snap
    # ------------------------------------------------------------------ #
    def total_equity(self, price_map: Dict[str, float]) -> float:
        """
        Compute total portfolio equity = cash + Σ(qty * price).
        """
        mv = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = float(price_map.get(t, pos.avg_price if pos.avg_price else 0.0))
            mv += pos.qty * px
        return self.cash + mv
    # ------------------------------------------------------------------ #
    def compute_target_allocations(
        self,
        signals: Dict[str, float],
        price_data: Dict[str, pd.DataFrame],
        equity: float,
    ) -> Dict[str, float]:
        """
        Wrapper around PortfolioPolicy.allocate() that stores and returns weights.
        """
        weights = self.policy.allocate(signals, price_data, equity)
        self.current_target_weights = weights
        self._log_debug(f"Computed target allocations from signals: {signals} -> weights: {weights}")
        return weights

    def target_notional_values(self, equity: float) -> Dict[str, float]:
        """
        Translate current target weights to target dollar notionals.
        """
        return {t: w * equity for t, w in self.current_target_weights.items()}

    # ------------------------------------------------------------------ #
    def gross_notional(self, price_map: Dict[str, float]) -> float:
        g = 0.0
        for t, p in self.positions.items():
            if p.qty == 0:
                continue
            px = float(price_map.get(t, p.avg_price if p.avg_price else 0.0))
            g += abs(p.qty * px)
        self._log_debug(f"Gross notional calculated: {g}")
        return g

    def net_exposure(self, price_map: Dict[str, float]) -> float:
        n = 0.0
        for t, p in self.positions.items():
            if p.qty == 0:
                continue
            px = float(price_map.get(t, p.avg_price if p.avg_price else 0.0))
            n += p.qty * px
        self._log_debug(f"Net exposure calculated: {n}")
        return n

    # --- Helper accessors for downstream compatibility ---
    @property
    def positions_map(self) -> Dict[str, dict]:
        return {t: _as_dict(p) for t, p in self.positions.items()}

    def get_position_info(self, ticker: str) -> dict:
        p = self.positions.get(ticker)
        return _as_dict(p) if p else {}

    def get_avg_price(self, ticker: str) -> Optional[float]:
        p = self.positions.get(ticker)
        return float(p.avg_price) if p else None

    def get_qty(self, ticker: str) -> int:
        p = self.positions.get(ticker)
        return int(p.qty) if p else 0