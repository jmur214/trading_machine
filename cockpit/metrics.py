import pandas as pd
import numpy as np
from math import sqrt


class PerformanceMetrics:
    """
    Computes realistic portfolio-level trading performance metrics with sanity checks.
    """

    def __init__(self, snapshots_path: str, trades_path: str = None, risk_free_rate: float = 0.02):
        self.snapshots = pd.read_csv(snapshots_path)
        self.trades = pd.read_csv(trades_path) if trades_path else None
        self.risk_free_rate = risk_free_rate

        if "timestamp" in self.snapshots.columns:
            self.snapshots["timestamp"] = pd.to_datetime(self.snapshots["timestamp"], errors="coerce")
            self.snapshots = self.snapshots.dropna(subset=["timestamp"]).sort_values("timestamp")

        self.equity = self.snapshots["equity"].astype(float)
        self.returns = self.equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

        print(f"[METRICS] Loaded {len(self.snapshots)} snapshots and {len(self.trades) if self.trades is not None else 0} trades.")

    # ---------------- CORE METRICS ---------------- #

    def total_return(self):
        r = (self.equity.iloc[-1] - self.equity.iloc[0]) / max(self.equity.iloc[0], 1e-6)
        return np.clip(r, -1.0, 10.0)  # cap to -100% to +1000%

    def cagr(self):
        days = (self.snapshots["timestamp"].iloc[-1] - self.snapshots["timestamp"].iloc[0]).days
        if days <= 0:
            return 0.0
        annual_factor = 365.0 / days
        r = (self.equity.iloc[-1] / max(self.equity.iloc[0], 1e-6)) ** annual_factor - 1
        return np.clip(r, -1.0, 10.0)

    def volatility(self):
        return float(self.returns.std() * sqrt(252)) if not self.returns.empty else 0.0

    def sharpe_ratio(self):
        if self.returns.empty or self.returns.std() == 0:
            return 0.0
        excess = self.returns - (self.risk_free_rate / 252)
        return round((excess.mean() / excess.std()) * sqrt(252), 3)

    def max_drawdown(self):
        roll_max = self.equity.cummax()
        drawdowns = (self.equity - roll_max) / roll_max
        return round(float(drawdowns.min() * 100), 2)

    def win_rate(self):
        if self.trades is None or "pnl" not in self.trades.columns:
            return 0.0
        closed = self.trades.dropna(subset=["pnl"])
        if closed.empty:
            return 0.0
        return round(100 * (closed["pnl"] > 0).sum() / len(closed), 2)

    # ---------------- SUMMARY ---------------- #

    def summary(self):
        summary_dict = {
            "Starting Equity": round(self.equity.iloc[0], 2),
            "Ending Equity": round(self.equity.iloc[-1], 2),
            "Net Profit": round(self.equity.iloc[-1] - self.equity.iloc[0], 2),
            "Total Return (%)": round(self.total_return() * 100, 2),
            "CAGR (%)": round(self.cagr() * 100, 2),
            "Max Drawdown (%)": self.max_drawdown(),
            "Sharpe Ratio": self.sharpe_ratio(),
            "Volatility (%)": round(self.volatility() * 100, 2),
            "Win Rate (%)": self.win_rate(),
        }

        print("\n[METRICS] Summary:")
        for k, v in summary_dict.items():
            print(f"  {k:25s}: {v}")
        return summary_dict