import pandas as pd
import numpy as np
from math import sqrt


class PerformanceMetrics:
    """
    Computes key trading performance metrics from portfolio snapshots and trades.
    """

    def __init__(self, snapshots_path: str, trades_path: str = None, risk_free_rate: float = 0.02):
        self.snapshots_path = snapshots_path
        self.trades_path = trades_path
        self.risk_free_rate = risk_free_rate

        self.snapshots = pd.read_csv(self.snapshots_path)
        self.trades = pd.read_csv(self.trades_path) if trades_path else None

        # Expect a 'timestamp' column
        if "timestamp" in self.snapshots.columns:
            self.snapshots["timestamp"] = pd.to_datetime(self.snapshots["timestamp"])
            self.snapshots = self.snapshots.sort_values("timestamp")

        # Equity series
        if "equity" not in self.snapshots.columns:
            raise ValueError("Portfolio snapshots must include an 'equity' column.")

        self.equity = self.snapshots["equity"].astype(float)
        self.returns = self.equity.pct_change().dropna()

    # ---------------------------- CORE METRICS ---------------------------- #

    def total_return(self):
        return (self.equity.iloc[-1] / self.equity.iloc[0]) - 1

    def cagr(self):
        days = (self.snapshots["timestamp"].iloc[-1] - self.snapshots["timestamp"].iloc[0]).days
        if days == 0:
            return 0
        annual_factor = 365.0 / days
        return (self.equity.iloc[-1] / self.equity.iloc[0]) ** annual_factor - 1

    def volatility(self):
        # Annualized volatility (assuming daily data)
        return self.returns.std() * sqrt(252)

    def sharpe_ratio(self):
        if self.returns.empty:
            return np.nan
        excess = self.returns - (self.risk_free_rate / 252)
        return (excess.mean() / excess.std()) * sqrt(252)

    def max_drawdown(self):
        roll_max = self.equity.cummax()
        drawdown = (self.equity - roll_max) / roll_max
        return drawdown.min()

    def win_rate(self):
        if self.trades is None or "pnl" not in self.trades.columns:
            return np.nan
        wins = (self.trades["pnl"] > 0).sum()
        total = len(self.trades)
        return wins / total if total > 0 else np.nan

    # ---------------------------- SUMMARY ---------------------------- #

    def summary(self):
        return {
            "Total Return": round(self.total_return() * 100, 2),
            "CAGR": round(self.cagr() * 100, 2),
            "Sharpe Ratio": round(self.sharpe_ratio(), 3),
            "Volatility (Annualized)": round(self.volatility() * 100, 2),
            "Max Drawdown": round(self.max_drawdown() * 100, 2),
            "Win Rate": round(self.win_rate() * 100, 2) if self.trades is not None else None,
        }


# ---------------------------- TEST / EXAMPLE ---------------------------- #

if __name__ == "__main__":
    metrics = PerformanceMetrics(
        snapshots_path="data/trade_logs/portfolio_snapshots.csv",
        trades_path="data/trade_logs/trades.csv",
    )
    print("\n--- Performance Summary ---")
    for k, v in metrics.summary().items():
        print(f"{k:25s}: {v}")