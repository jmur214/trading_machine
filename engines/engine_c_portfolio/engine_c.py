# engine_c.py
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import numpy as np

@dataclass
class Position:
    ticker: str
    qty: float
    avg_price: float
    side: str
    entry_date: datetime
    current_price: float = 0.0
    pnl: float = 0.0
    edge: str = ""

@dataclass
class Fill:
    ticker: str
    side: str
    qty: float
    price: float
    date: datetime
    edge: str = ""

class EngineC_PortfolioManager:
    def __init__(self, starting_cash=10000.0):
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions = {}
        self.trades = []
        self.history = []

    # ----- Update Portfolio from a Trade Fill -----
    def update_from_fill(self, fill: Fill):
        ticker = fill.ticker
        cost = fill.qty * fill.price

        # Handle buy
        if fill.side == "long":
            self.cash -= cost
            if ticker in self.positions:
                pos = self.positions[ticker]
                new_qty = pos.qty + fill.qty
                pos.avg_price = (pos.avg_price * pos.qty + fill.price * fill.qty) / new_qty
                pos.qty = new_qty
            else:
                self.positions[ticker] = Position(ticker, fill.qty, fill.price, "long", fill.date, edge=fill.edge)

        # Handle sell / closing
        elif fill.side == "short":
            if ticker in self.positions:
                pos = self.positions[ticker]
                pnl = (fill.price - pos.avg_price) * pos.qty * (1 if pos.side == "long" else -1)
                self.cash += fill.qty * fill.price + pnl
                self.trades.append({
                    "ticker": ticker,
                    "entry_price": pos.avg_price,
                    "exit_price": fill.price,
                    "pnl": pnl,
                    "qty": pos.qty,
                    "edge": pos.edge,
                    "exit_date": fill.date
                })
                del self.positions[ticker]
            else:
                # Opening a short position
                self.cash += cost
                self.positions[ticker] = Position(ticker, fill.qty, fill.price, "short", fill.date, edge=fill.edge)

    # ----- Mark-to-Market Updates -----
    def update_market_prices(self, price_data: dict):
        total_value = self.cash
        for ticker, pos in self.positions.items():
            if ticker in price_data:
                pos.current_price = price_data[ticker]
                direction = 1 if pos.side == "long" else -1
                pos.pnl = (pos.current_price - pos.avg_price) * pos.qty * direction
                total_value += pos.qty * pos.current_price
        self.equity = total_value
        self._snapshot()

    def get_equity(self, price_map: dict) -> float:
        """
        Return total portfolio equity = cash + sum(position_value).
        `price_map` is a dict {ticker: latest_close_price}.
        """
        equity = self.cash
        for pos in self.positions.values():
            px = price_map.get(pos.ticker)
            if px is not None:
                equity += pos.qty * px
        return equity
    
    # ----- Portfolio Snapshot -----
    def _snapshot(self):
        snapshot = {
            "timestamp": datetime.now(),
            "cash": self.cash,
            "equity": self.equity,
            "positions": len(self.positions),
            "open_pnl": sum(p.pnl for p in self.positions.values()),
            "total_value": self.equity
        }
        self.history.append(snapshot)

    # ----- Metrics Calculation -----
    def calculate_metrics(self):
        df = pd.DataFrame(self.history)
        df["returns"] = df["total_value"].pct_change().fillna(0)
        cagr = ((df["total_value"].iloc[-1] / df["total_value"].iloc[0]) ** (252 / len(df))) - 1
        sharpe = np.sqrt(252) * df["returns"].mean() / df["returns"].std() if df["returns"].std() != 0 else 0
        max_dd = ((df["total_value"].cummax() - df["total_value"]) / df["total_value"].cummax()).max()
        return {"CAGR": cagr, "Sharpe": sharpe, "MaxDrawdown": max_dd}

    # ----- Get Portfolio Summary -----
    def get_portfolio_state(self):
        return {
            "cash": round(self.cash, 2),
            "equity": round(getattr(self, "equity", self.cash), 2),
            "positions": {t: vars(p) for t, p in self.positions.items()},
            "open_positions": len(self.positions)
        }

    # ----- Save Logs -----
    def save_logs(self):
        pd.DataFrame(self.trades).to_csv("trade_log.csv", index=False)
        pd.DataFrame(self.history).to_csv("portfolio_history.csv", index=False)