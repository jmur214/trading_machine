# backtester/execution_simulator.py

from __future__ import annotations
from typing import Optional, Dict


class ExecutionSimulator:
    """
    Simulates order execution for backtesting.
    - Entry/exit signals fill at the next bar open (with slippage/commission).
    - Stop/TP triggers fill at their level if the bar's High/Low breaches (with slippage).
    """

    def __init__(self, slippage_bps: float = 10.0, commission: float = 0.0):
        self.slippage_bps = float(slippage_bps)
        self.commission = float(commission)

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * (self.slippage_bps / 10000.0)
        s = str(side).lower()
        if s in ("long", "buy", "cover"):
            return price + slip
        if s in ("short", "sell", "exit"):
            return price - slip
        return price

    def _extract_bar(self, bar_like) -> Dict[str, float]:
        try:
            return {
                "Open": float(bar_like["Open"]),
                "High": float(bar_like["High"]),
                "Low": float(bar_like["Low"]),
            }
        except Exception:
            raise KeyError("Bar data must include 'Open', 'High', and 'Low'.")

    def fill_at_next_open(self, order: dict, next_bar) -> Optional[dict]:
        bar = self._extract_bar(next_bar)
        side = str(order.get("side", "")).lower()
        qty = int(order.get("qty", 0))
        ticker = order.get("ticker")

        if qty <= 0 or side not in ("long", "short", "exit") or not ticker:
            return None

        price = self._apply_slippage(float(bar["Open"]), side)
        fill = {
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "price": price,
            "commission": self.commission,
        }
        if "edge" in order:
            fill["edge"] = order["edge"]
        if "meta" in order:
            fill["meta"] = order["meta"]

        print(f"[EXEC] Filled {side} {ticker} x{qty} @ {price:.4f}")
        return fill

    def check_stops_and_targets(self, ticker: str, position, bar) -> Optional[dict]:
        if position is None or position.qty == 0:
            return None

        bl = self._extract_bar(bar)
        high, low = bl["High"], bl["Low"]

        qty = abs(int(position.qty))
        is_long = position.qty > 0
        stop = position.stop
        tp = position.take_profit

        hit_stop = False
        hit_tp = False
        if is_long:
            if stop is not None and low <= float(stop):
                hit_stop = True
            if tp is not None and high >= float(tp):
                hit_tp = True
        else:
            if stop is not None and high >= float(stop):
                hit_stop = True
            if tp is not None and low <= float(tp):
                hit_tp = True

        level = None
        trigger = None
        if hit_stop:
            level = float(stop)
            trigger = "stop"
        elif hit_tp:
            level = float(tp)
            trigger = "take_profit"
        else:
            return None

        exec_side = "exit" if is_long else "cover"
        px = self._apply_slippage(level, "sell" if is_long else "buy")
        fill = {
            "ticker": ticker,
            "side": exec_side,
            "qty": qty,
            "price": px,
            "commission": self.commission,
            "trigger": trigger,
        }
        print(f"[EXEC] {exec_side.upper()} via {trigger} {ticker} x{qty} @ {px:.4f}")
        return fill