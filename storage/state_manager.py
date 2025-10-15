import json
from pathlib import Path

class StateManager:
    """
    Handles saving and loading persistent trading state
    (positions, cash, open orders) for both live and backtest modes.
    """

    def __init__(self, state_path="data/state/trader_state.json"):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = {
            "cash": 0.0,
            "positions": {},
            "open_orders": [],
            "mode": "backtest"
        }

    def load(self):
        if self.state_path.exists():
            with self.state_path.open("r") as f:
                self.state = json.load(f)
            print(f"[STATE] Loaded from {self.state_path}")
        else:
            print(f"[STATE] No state file found. Using defaults.")
        return self.state

    def save(self):
        with self.state_path.open("w") as f:
            json.dump(self.state, f, indent=4)
        print(f"[STATE] Saved to {self.state_path}")

    def update_cash(self, amount):
        self.state["cash"] += amount
        self.save()

    def update_position(self, ticker, side, qty, price):
        self.state["positions"][ticker] = {"side": side, "qty": qty, "price": price}
        self.save()