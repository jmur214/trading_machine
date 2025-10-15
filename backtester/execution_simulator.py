class ExecutionSimulator:
    """
    Simulate fills at next bar open +/- slippage (bps).
    Example: slippage_bps = 10 → 0.10% price impact.
    """

    def __init__(self, slippage_bps: float = 10.0, commission: float = 0.0):
        self.slip = float(slippage_bps) / 10000.0
        self.commission = float(commission)

    def fill_at_next_open(self, order: dict, next_row) -> dict:
        """
        Simulate a fill at the next bar's open price adjusted for slippage.
        Returns a dict compatible with Engine C’s Fill dataclass.
        """
        if next_row is None:
            return None

        open_px = float(next_row["Open"])
        side = order.get("side", "long")

        # Apply slippage: buy slightly higher, sell slightly lower
        if side == "long":
            fill_px = open_px * (1 + self.slip)
        else:
            fill_px = open_px * (1 - self.slip)

        # Return full fill record
        return {
            "ticker": order.get("ticker"),
            "side": side,
            "qty": order.get("qty", 0),
            "fill_price": fill_px,      # ✅ consistent key for backtester
            "price": fill_px,           # ✅ duplicate for compatibility
            "commission": self.commission,
            "timestamp": order.get("timestamp", None),
        }