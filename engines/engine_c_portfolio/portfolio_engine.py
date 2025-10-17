# engines/engine_c_portfolio/portfolio_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Position:
    qty: int = 0                 # signed qty: long >0, short <0
    avg_price: float = 0.0
    stop: float | None = None
    take_profit: float | None = None


class PortfolioEngine:
    """
    Signed-qty accounting with realized & unrealized PnL.
    Realized PnL flows into cash at the moment of exit.
    """

    def __init__(self, initial_capital: float):
        self.cash: float = float(initial_capital)
        self.realized_pnl: float = 0.0
        self.positions: Dict[str, Position] = {}
        self.history: List[dict] = []

    # --------- core ops ---------
    def _get_or_new(self, ticker: str) -> Position:
        return self.positions.get(ticker, Position())

    def apply_fill(self, fill: dict) -> None:
        """
        fill keys:
          ticker, side in {'long','short','exit','cover'}, qty, price
          optional: commission, stop, take_profit
        Notes:
          - For 'exit' we infer whether it's a sell (closing long) or buy-to-cover (closing short) from signed qty.
          - For explicit 'cover' we treat it as buy-to-cover (closing short).
        """
        ticker = str(fill.get("ticker"))
        side = str(fill.get("side", "")).lower()
        qty_raw = int(fill.get("qty", 0))
        price = float(fill.get("price") or fill.get("fill_price"))
        commission = float(fill.get("commission", 0.0))

        if not ticker or qty_raw <= 0:
            return

        pos = self._get_or_new(ticker)

        # Normalize 'exit' vs 'cover' for clarity
        if side == "exit" and pos.qty < 0:
            side = "cover"

        # ---- CLOSE / REDUCE paths ----
        if side in ("exit", "cover"):
            if pos.qty == 0:
                return
            exit_qty = min(abs(pos.qty), qty_raw)
            was_long = pos.qty > 0
            sign = 1 if was_long else -1

            # Cash flow: sell long adds cash; buy-to-cover short reduces cash
            if was_long:
                self.cash += exit_qty * price
            else:
                self.cash -= exit_qty * price

            # Realized PnL is always (trade_px - avg_px) * (closed signed qty)
            realized = (price - pos.avg_price) * (exit_qty * sign)
            self.realized_pnl += realized
            self.cash -= commission

            remaining = abs(pos.qty) - exit_qty
            if remaining > 0:
                pos.qty = remaining * sign
            else:
                pos = Position()  # fully flat

            self.positions[ticker] = pos
            return

        # ---- OPEN / ADD paths ----
        if side not in ("long", "short"):
            return

        signed_qty = qty_raw if side == "long" else -qty_raw

        # Cash flow:
        #  - long buy uses cash
        #  - short sell receives cash
        if signed_qty > 0:
            self.cash -= signed_qty * price
        else:
            self.cash += abs(signed_qty) * price

        self.cash -= commission

        # Same-direction add or new
        if pos.qty == 0 or (pos.qty > 0 and signed_qty > 0) or (pos.qty < 0 and signed_qty < 0):
            new_abs = abs(pos.qty) + abs(signed_qty)
            total_cost = (abs(pos.qty) * pos.avg_price) + (abs(signed_qty) * price)
            pos.qty += signed_qty
            pos.avg_price = (total_cost / new_abs) if new_abs > 0 else 0.0
        else:
            # Reducing/closing or flipping
            closing = min(abs(pos.qty), abs(signed_qty))
            sign = 1 if pos.qty > 0 else -1
            realized = (price - pos.avg_price) * (closing * sign)
            self.realized_pnl += realized

            net_abs = abs(pos.qty) - closing
            if net_abs > 0:
                pos.qty = net_abs * sign
            else:
                # Fully closed; if excess remains, open on the other side at this price
                excess = abs(signed_qty) - closing
                if excess > 0:
                    pos.qty = excess * (-sign)
                    pos.avg_price = price
                else:
                    pos = Position()

        # optional SL/TP updates
        if "stop" in fill and fill["stop"] is not None:
            pos.stop = float(fill["stop"])
        if "take_profit" in fill and fill["take_profit"] is not None:
            pos.take_profit = float(fill["take_profit"])

        self.positions[ticker] = pos

    def snapshot(self, timestamp, price_map: Dict[str, float]) -> dict:
        market_value = 0.0
        unrealized = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = float(price_map.get(t, pos.avg_price if pos.avg_price else 0.0))
            market_value += pos.qty * px  # signed qty => shorts reduce MV
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
        self.history.append(snap)
        return snap

    def total_equity(self, price_map: Dict[str, float]) -> float:
        mv = 0.0
        for t, pos in self.positions.items():
            if pos.qty == 0:
                continue
            px = float(price_map.get(t, pos.avg_price if pos.avg_price else 0.0))
            mv += pos.qty * px
        return self.cash + mv

    # --------- helpful portfolio stats (for true Engine C) ---------
    def gross_notional(self, price_map: Dict[str, float]) -> float:
        g = 0.0
        for t, p in self.positions.items():
            if p.qty == 0:
                continue
            px = float(price_map.get(t, p.avg_price if p.avg_price else 0.0))
            g += abs(p.qty * px)
        return g

    def net_exposure(self, price_map: Dict[str, float]) -> float:
        n = 0.0
        for t, p in self.positions.items():
            if p.qty == 0:
                continue
            px = float(price_map.get(t, p.avg_price if p.avg_price else 0.0))
            n += p.qty * px
        return n