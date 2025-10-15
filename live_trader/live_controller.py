from live_trader.broker_interface import BrokerInterface
from storage.state_manager import StateManager

class LiveController:
    """
    Coordinates live data feed, AlphaEngine signals,
    and BrokerInterface executions.
    """

    def __init__(self, alpha_engine, risk_engine):
        self.alpha = alpha_engine
        self.risk = risk_engine
        self.state = StateManager().load()
        self.broker = BrokerInterface()

    def on_market_tick(self, data_slice):
        signals = self.alpha.generate_signals(data_slice, timestamp=data_slice.index[-1])
        for sig in signals:
            if sig["side"] != "none":
                order = self.risk.prepare_order(sig, self.state["cash"], data_slice[sig["ticker"]])
                if order:
                    resp = self.broker.place_order(order["ticker"], order["qty"], order["side"])
                    print(f"[LIVE] Order sent: {resp}")