from dataclasses import dataclass
from typing import Dict
import pandas as pd


@dataclass
class Position:
    qty: int = 0
    avg_price: float = 0.0
    stop: float | None = None
    take_profit: float | None = None

    def direction(self) -> int:
        return 1 if self.qty > 0 else -1 if self.qty < 0 else 0


class PortfolioEngine:
    """
    Handles position tracking, realized/unrealized PnL, and total equity updates.
    """

    def __init__(self, initial_capital: float):
        self.cash = float(initial_capital)
        self.realized_pnl = 0.0
        self.positions: Dict[str, Position] = {}
        self.history = []

    def _get_or_new(self, ticker: str) -> Position:
        return self.positions.get(ticker, Position())

    def apply_fill(self, fill: dict) -> None:
        """
        fill keys:
          ticker, side ∈ {'long','short','exit','cover'}, qty, price
          optional: commission, stop, take_profit
        """
        ticker = fill.get("ticker")
        side = fill.get("side", "").lower()
        qty = int(fill.get("qty", 0))
        price = float(fill.get("price") or fill.get("fill_price"))
        commission = float(fill.get("commission", 0.0))

        if not ticker or qty <= 0:
            return

        pos = self._get_or_new(ticker)
        direction = pos.direction()

        # Handle exits/covers
        if side in ("exit", "cover"):
            if pos.qty == 0:
                return

            exit_qty = min(abs(qty), abs(pos.qty))
            realized = (price - pos.avg_price) * exit_qty * direction
            self.realized_pnl += realized

            # Adjust cash for closing trade
            if direction > 0:  # closing long
                self.cash += exit_qty * price
            else:  # closing short
                self.cash -= exit_qty * price

            pos.qty -= exit_qty * direction

            # Close position if fully exited
            if pos.qty == 0:
                pos.avg_price = 0.0
                pos.stop = None
                pos.take_profit = None

            self.cash -= commission
            self.positions[ticker] = pos
            return

        # Handle new/added positions
        signed_qty = qty if side == "long" else -qty
        total_qty = pos.qty + signed_qty

        # Adjust weighted average entry price
        if pos.qty == 0:
            pos.avg_price = price
            pos.qty = signed_qty
        elif (pos.qty > 0 and signed_qty > 0) or (pos.qty < 0 and signed_qty < 0):
            total_cost = (pos.avg_price * abs(pos.qty)) + (price * abs(signed_qty))
            pos.avg_price = total_cost / (abs(pos.qty) + abs(signed_qty))
            pos.qty = total_qty
        else:
            # Opposite direction → partial or full close
            closing_qty = min(abs(pos.qty), abs(signed_qty))
            realized = (price - pos.avg_price) * closing_qty * direction
            self.realized_pnl += realized
            pos.qty = pos.qty + signed_qty  # will flip or flatten
            if pos.qty == 0:
                pos.avg_price = 0.0
                pos.stop = None
                pos.take_profit = None
            else:
                pos.avg_price = price

        # Adjust cash (buy reduces cash, short increases)
        self.cash -= signed_qty * price
        self.cash -= commission

        self.positions[ticker] = pos

    def snapshot(self, timestamp, price_map: Dict[str, float]) -> dict:
        market_value = 0.0
        unrealized = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = price_map.get(t, pos.avg_price)
            market_value += pos.qty * px
            unrealized += (px - pos.avg_price) * pos.qty

        equity = self.cash + self.realized_pnl + unrealized
        snap = {
            "timestamp": pd.to_datetime(timestamp),
            "cash": round(self.cash, 2),
            "market_value": round(market_value, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "equity": round(equity, 2),
            "positions": sum(1 for p in self.positions.values() if p.qty != 0),
        }
        self.history.append(snap)
        return snap
    def total_equity(self, price_map: Dict[str, float]) -> float:
        """
        Compute total account equity = cash + market value of all open positions.
        This excludes realized PnL (since it’s already reflected in cash).
        """
        market_value = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = price_map.get(t, pos.avg_price)
            market_value += pos.qty * px

        return self.cash + market_value