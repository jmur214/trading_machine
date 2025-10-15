# engines/engine_c_portfolio/portfolio_engine.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional
import pandas as pd


@dataclass
class Position:
    qty: int = 0                 # signed: >0 long, <0 short
    avg_price: float = 0.0       # average entry price for the open remainder

    def direction(self) -> int:
        if self.qty > 0:
            return 1
        if self.qty < 0:
            return -1
        return 0


class PortfolioEngine:
    """
    Minimal, robust portfolio accounting:
      - Signed qty (long>0, short<0)
      - Cash debited/credited on fills (short sale increases cash)
      - Realized PnL on reductions/closures (FIFO-approx via average price)
      - Unrealized PnL at snapshot
      - Equity = cash + Σ(qty * last_price)
    """

    def __init__(self, initial_capital: float):
        self.cash: float = float(initial_capital)
        self.realized_pnl: float = 0.0
        self.positions: Dict[str, Position] = {}
        # Keep a history of snapshots as a list of dicts, returned at the end
        self.history: list[dict] = []

    # ---------- Public API (used by controller) ----------

    def apply_fill(self, fill: dict) -> None:
        """
        Expected 'fill' dict (we're defensive with keys):
            ticker: str
            side: 'long' | 'short'
            qty: int/float
            price: float
            (optional) commission: float
        We use signed-qty convention and average-price accounting.
        """
        ticker = str(fill.get("ticker"))
        side = str(fill.get("side", "")).lower()
        qty_raw = fill.get("qty", 0)
        price = float(fill.get("price") or fill.get("fill_price"))
        commission = float(fill.get("commission", 0.0))

        if not ticker or side not in ("long", "short"):
            return
        qty = int(qty_raw)
        if qty <= 0:
            return

        # Signed quantity: long = +qty, short = -qty
        signed_qty = qty if side == "long" else -qty

        # Initialize position if needed
        pos = self.positions.get(ticker, Position())

        # --- CASH UPDATE ---
        # Cash change = - (signed_qty * price)
        #  Long buy  (+qty): cash -= qty*price
        #  Short sell (-qty): cash -= (-qty)*price -> cash += qty*price
        self.cash -= signed_qty * price
        self.cash -= commission  # apply commission if any

        prev_qty = pos.qty
        prev_dir = pos.direction()

        # --- POSITION / REALIZED PNL UPDATE ---
        if prev_qty == 0:
            # New position
            pos.qty = signed_qty
            pos.avg_price = price
        elif prev_dir * signed_qty > 0:
            # Adding to the same direction -> update weighted average price
            new_qty_abs = abs(prev_qty) + abs(signed_qty)
            total_cost = (abs(prev_qty) * pos.avg_price) + (abs(signed_qty) * price)
            pos.avg_price = total_cost / new_qty_abs
            pos.qty = prev_qty + signed_qty
        else:
            # Reducing or flipping
            closing_qty = min(abs(prev_qty), abs(signed_qty))
            # Realized PnL for the closing portion:
            # General formula that works for both long(+qty) and short(-qty):
            # unrealized piece for a qty q at price p: (p - avg) * q
            # When closing, q has opposite sign to prev_qty, so realized:
            realized = (price - pos.avg_price) * (closing_qty * (1 if prev_qty > 0 else -1))
            self.realized_pnl += realized

            remaining = abs(prev_qty) - closing_qty
            if remaining > 0:
                # Still same side remains (reduction)
                pos.qty = (remaining if prev_qty > 0 else -remaining)
                # avg_price unchanged
                # Excess of the trade (if any) flips the position
                excess = abs(signed_qty) - closing_qty
                if excess > 0:
                    # Now we open in the opposite direction with 'excess'
                    flip_qty = excess * (-1 if prev_qty > 0 else 1)  # direction opposite to prev
                    pos.qty += flip_qty
                    pos.avg_price = price  # new side starts at trade price
            else:
                # Fully closed -> maybe flip if more trade remains
                excess = abs(signed_qty) - closing_qty
                if excess > 0:
                    # Open fresh position in trade's direction
                    pos.qty = (excess if side == "long" else -excess)
                    pos.avg_price = price
                else:
                    # Flat
                    pos.qty = 0
                    pos.avg_price = 0.0

        # Save back
        self.positions[ticker] = pos

    def snapshot(self, timestamp, price_map: Dict[str, float]) -> dict:
        """
        Record a snapshot using the given prices (Close is fine).
        price_map: dict[ticker] = last price at timestamp
        """
        # Market value & unrealized
        market_value = 0.0
        unrealized = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            price = float(price_map.get(t, pos.avg_price))
            # Position market value: qty * price (signed qty handles short)
            pv = pos.qty * price
            market_value += pv
            # Unrealized PnL: (price - avg) * qty  (works for long & short)
            unrealized += (price - pos.avg_price) * pos.qty

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
        self.history.append(snap)
        return snap

    def total_equity(self, price_map: Dict[str, float]) -> float:
        """Convenience: cash + Σ(qty * price)."""
        mv = 0.0
        for t, p in self.positions.items():
            if p.qty == 0:
                continue
            price = float(price_map.get(t, p.avg_price))
            mv += p.qty * price
        return self.cash + mv