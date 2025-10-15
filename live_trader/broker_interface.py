import requests
import os

class BrokerInterface:
    """
    Unified interface for executing live trades via API.
    (Supports paper/live environments via environment variables.)
    """

    def __init__(self, broker="alpaca"):
        self.broker = broker
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        self.base_url = "https://paper-api.alpaca.markets/v2"

    def place_order(self, symbol, qty, side, order_type="market"):
        endpoint = f"{self.base_url}/orders"
        data = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": "gtc"
        }
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }
        r = requests.post(endpoint, json=data, headers=headers)
        if r.status_code != 200:
            print(f"[BROKER][ERROR] {r.status_code}: {r.text}")
        else:
            print(f"[BROKER] {side.upper()} {qty} {symbol}")
        return r.json()

    def get_positions(self):
        endpoint = f"{self.base_url}/positions"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }
        r = requests.get(endpoint, headers=headers)
        return r.json() if r.status_code == 200 else []