# brokers/alpaca_broker.py
from __future__ import annotations
import os
from pathlib import Path
import alpaca_trade_api as tradeapi
from dotenv import load_dotenv


class AlpacaBroker:
    """
    Live / Paper trading interface for Alpaca Markets.

    Loads API credentials from environment variables (.env file)
    and provides a unified interface to place orders, check positions,
    and query account info.

    Usage:
        broker = AlpacaBroker(paper=True)
        broker.place_order("AAPL", "buy", 1)
        positions = broker.get_positions()
        equity = broker.get_equity()
    """

    def __init__(self, paper: bool = True):
        # Load environment variables from .env file (root directory)
        env_path = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(env_path)

        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_API_SECRET")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if not key or not secret:
            raise ValueError(
                "❌ Missing Alpaca API credentials. "
                "Please set ALPACA_API_KEY and ALPACA_API_SECRET in your .env file."
            )

        # Connect to Alpaca API
        self.api = tradeapi.REST(key, secret, base_url, api_version="v2")

        # Verify connection
        try:
            acct = self.api.get_account()
            print(f"[ALPACA][INFO] Connected successfully — Equity=${acct.equity}, Cash=${acct.cash}")
        except Exception as e:
            print(f"[ALPACA][ERROR] Could not verify account: {e}")

    # ------------------------------------------------------------------ #
    # Core Broker Methods

    def place_order(self, ticker: str, side: str, qty: float, order_type: str = "market"):
        """
        Submit an order to Alpaca.

        Parameters:
            ticker (str): symbol (e.g., "AAPL")
            side (str): "buy", "sell", "short", or "cover"
            qty (float): quantity to trade
            order_type (str): "market" or "limit" (default: market)
        """
        side = side.lower().strip()
        if side not in ("buy", "sell", "short", "cover"):
            print(f"[ALPACA][WARN] Invalid order side: {side}")
            return None

        # Map internal sides to Alpaca sides
        if side == "short":
            alpaca_side = "sell"
        elif side == "cover":
            alpaca_side = "buy"
        else:
            alpaca_side = side

        try:
            order = self.api.submit_order(
                symbol=ticker,
                qty=abs(qty),
                side=alpaca_side,
                type=order_type,
                time_in_force="gtc",  # good-till-cancelled
            )
            print(f"[ALPACA][INFO] Submitted {alpaca_side.upper()} {qty} {ticker} (order_id={order.id})")
            return order
        except Exception as e:
            print(f"[ALPACA][ERROR] Failed to submit order for {ticker}: {e}")
            return None

    def get_positions(self) -> dict:
        """
        Return all open positions as {symbol: quantity}.
        """
        try:
            positions = self.api.list_positions()
            pos_dict = {p.symbol: float(p.qty) for p in positions}
            print(f"[ALPACA][INFO] Current positions: {pos_dict}")
            return pos_dict
        except Exception as e:
            print(f"[ALPACA][ERROR] Could not fetch positions: {e}")
            return {}

    def get_equity(self) -> float | None:
        """
        Return current account equity.
        """
        try:
            acct = self.api.get_account()
            print(f"[ALPACA][INFO] Equity=${acct.equity}, Cash=${acct.cash}")
            return float(acct.equity)
        except Exception as e:
            print(f"[ALPACA][ERROR] Could not fetch equity: {e}")
            return None

    def cancel_all(self):
        """
        Cancel all open orders.
        """
        try:
            self.api.cancel_all_orders()
            print("[ALPACA][INFO] All open orders cancelled.")
        except Exception as e:
            print(f"[ALPACA][ERROR] Failed to cancel orders: {e}")

    def list_orders(self):
        """
        List all open (pending) orders.
        """
        try:
            orders = self.api.list_orders(status="open")
            print(f"[ALPACA][INFO] Open orders: {[o.symbol for o in orders]}")
            return orders
        except Exception as e:
            print(f"[ALPACA][ERROR] Could not list orders: {e}")
            return []

# ------------------------------------------------------------------ #
# Self-test (only runs when called directly)
if __name__ == "__main__":
    broker = AlpacaBroker(paper=True)
    broker.get_equity()
    broker.get_positions()