import random


class ExecutionSimulator:
    """
    Simulates order execution for backtesting.
    """

    def __init__(self, slippage_bps=10.0, commission=0.0):
        self.slippage_bps = slippage_bps
        self.commission = commission

    def _apply_slippage(self, price: float, side: str) -> float:
        """
        Adjusts price based on slippage in basis points (bps).
        Longs pay slightly more, shorts get slightly less.
        """
        slip = price * (self.slippage_bps / 10000.0)
        if side == "long":
            return price + slip
        elif side == "short":
            return price - slip
        return price

    def fill_at_next_open(self, order: dict, next_bar: dict) -> dict:
        """
        Simulate an order being filled at the next bar's open price.
        Returns a fill dict, or None if it can't fill.
        """
        if "Open" not in next_bar:
            return None

        open_px = float(next_bar["Open"])
        side = order.get("side", "").lower()
        qty = int(order.get("qty", 0))
        ticker = order.get("ticker")

        if qty <= 0 or side not in ("long", "short"):
            return None

        fill_price = self._apply_slippage(open_px, side)
        commission = self.commission

        fill = {
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "price": fill_price,
            "commission": commission,
        }

        print(f"[EXEC] Filled {side} {ticker} x{qty} @ {fill_price:.2f}")
        return fill

    def exit_position(self, ticker: str, position, next_bar: dict):
        """
        Exit a position at the next open price (simulate sell or cover).
        """
        if position.qty == 0 or "Open" not in next_bar:
            return None

        open_px = float(next_bar["Open"])
        qty = abs(position.qty)

        # Determine correct exit side for clarity in logs
        side = "exit"
        direction = "cover" if position.qty < 0 else "exit"

        fill_price = self._apply_slippage(open_px, side)
        commission = self.commission

        fill = {
            "ticker": ticker,
            "side": direction,
            "qty": qty,
            "price": fill_price,
            "commission": commission,
        }

        print(f"[EXEC] {direction.upper()} {ticker} x{qty} @ {fill_price:.2f}")
        return fill