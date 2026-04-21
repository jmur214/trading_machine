from __future__ import annotations
# cockpit/metrics.py
from debug_config import is_debug_enabled

def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("METRICS_INFO", False)

import pandas as pd
import numpy as np
from math import sqrt
from core.metrics_engine import MetricsEngine


def _epsilon_series(x: pd.Series, eps: float = 1e-9) -> pd.Series:
    """Clamp very small magnitudes to avoid exploding pct/log returns."""
    y = x.copy()
    y = y.replace([np.inf, -np.inf], np.nan)
    y = y.ffill()
    y = y.bfill()
    y = y.fillna(0.0)
    y = y.where(y.abs() >= eps, np.sign(y) * eps)
    return y


def _compute_fifo_realized(trades: pd.DataFrame) -> pd.DataFrame:
    """Lightweight FIFO pairing with commission impact."""
    if trades is None or trades.empty:
        return pd.DataFrame()

    df = trades.copy()
    for col in ("qty", "fill_price", "commission"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "commission" not in df.columns:
        df["commission"] = 0.0

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values(["ticker", "timestamp"])
    if "pnl" not in df.columns:
        df["pnl"] = np.nan

    stacks: dict[str, list[dict]] = {}

    def sign_for(side: str) -> int:
        s = str(side).lower()
        if s == "long":
            return +1
        if s == "short":
            return -1
        return 0

    def closes(prev_sign: int, now_side: str) -> bool:
        s = str(now_side).lower()
        if s in ("exit", "cover"):
            return True
        ns = sign_for(s)
        return prev_sign != 0 and ns != 0 and np.sign(prev_sign) != np.sign(ns)

    for tkr, tdf in df.groupby("ticker", sort=False):
        stack = []
        prev_net = 0

        def net_sign():
            if not stack:
                return 0
            net = sum(leg["sign"] * leg["qty"] for leg in stack)
            return int(np.sign(net)) if net != 0 else 0

        for idx, row in tdf.iterrows():
            side = str(row.get("side", "")).lower()
            qty = int(row.get("qty", 0))
            px = float(row.get("fill_price", np.nan))
            comm = float(row.get("commission", 0.0))
            if qty <= 0 or not np.isfinite(px):
                continue

            if side in ("long", "short"):
                sgn = sign_for(side)
                if prev_net == 0 or prev_net == sgn:
                    stack.append({"sign": sgn, "price": px, "qty": qty, "commission": comm})
                else:
                    remaining = qty
                    realized = 0.0
                    total_comm = comm  # include exit-side commission
                    while remaining > 0 and stack and np.sign(stack[0]["sign"]) != np.sign(sgn):
                        leg = stack[0]
                        m = min(remaining, leg["qty"])
                        realized += (px - leg["price"]) * (m * leg["sign"])
                        total_comm += leg.get("commission", 0.0)
                        leg["qty"] -= m
                        remaining -= m
                        if leg["qty"] == 0:
                            stack.pop(0)
                    df.loc[idx, "pnl"] = round(realized - total_comm, 2)
                    if remaining > 0:
                        stack.append({"sign": sgn, "price": px, "qty": remaining, "commission": comm})

            elif closes(prev_net, side):
                remaining = qty
                realized = 0.0
                total_comm = comm
                while remaining > 0 and stack:
                    leg = stack[0]
                    m = min(remaining, leg["qty"])
                    realized += (px - leg["price"]) * (m * leg["sign"])
                    total_comm += leg.get("commission", 0.0)
                    leg["qty"] -= m
                    remaining -= m
                    if leg["qty"] == 0:
                        stack.pop(0)
                df.loc[idx, "pnl"] = round(realized - total_comm, 2)

            prev_net = net_sign()

    return df


class PerformanceMetrics:
    """
    Computes key trading performance metrics from portfolio snapshots and trades.
    Defends against impossible values: epsilon floors, NaN/inf guards, capped MDD domain.
    """

    def __init__(self, snapshots_path: str, trades_path: str | None = None, risk_free_rate: float = 0.02):
        self.snapshots_path = snapshots_path
        self.trades_path = trades_path
        self.risk_free_rate = float(risk_free_rate)

        # Load snapshots
        self.snapshots = pd.read_csv(self.snapshots_path)
        if "timestamp" in self.snapshots.columns:
            self.snapshots["timestamp"] = pd.to_datetime(self.snapshots["timestamp"], errors="coerce")
            self.snapshots = self.snapshots.dropna(subset=["timestamp"]).sort_values("timestamp")

        if "equity" not in self.snapshots.columns:
            raise ValueError("[METRICS] snapshots missing 'equity' column")

        # Clean equity and derive returns with epsilon/log safeguards
        eq = pd.to_numeric(self.snapshots["equity"], errors="coerce")
        eq = eq.replace([np.inf, -np.inf], np.nan).dropna()
        self.equity = eq

        # Epsilon floor to avoid divide-by-near-zero explosions
        eq_eps = _epsilon_series(eq, eps=1.0)  # $1 floor
        # Log-returns are more stable around sign changes; ignore non-positive equity
        valid = eq_eps > 0
        log_ret = pd.Series(dtype=float)
        if valid.any():
            v = eq_eps[valid]
            log_ret = np.log(v / v.shift()).replace([np.inf, -np.inf], np.nan).dropna()
        self.returns = log_ret

        # Load trades and ensure realized PnL exists
        self.trades = None
        if trades_path:
            try:
                tdf = pd.read_csv(self.trades_path, engine="python", on_bad_lines="skip")
                if tdf is not None and not tdf.empty:
                    if ("pnl" not in tdf.columns) or (pd.to_numeric(tdf["pnl"], errors="coerce").isna().all()):
                        tdf = _compute_fifo_realized(tdf)
                    self.trades = tdf
            except Exception:
                self.trades = None
        if is_debug_enabled("METRICS") or is_info_enabled():
            print(f"[METRICS] Loaded {len(self.snapshots)} snapshots and {len(self.trades) if self.trades is not None else 0} trades.")

    def _to_native(self, x):
        if isinstance(x, (np.floating, np.float32, np.float64)):
            return float(x)
        if isinstance(x, (np.integer, np.int64, np.int32)):
            return int(x)
        if pd.isna(x):
            return 0.0
        return x

    # ---- metrics (delegated to MetricsEngine for single source of truth) ----
    def _engine_metrics(self) -> dict:
        """Compute all metrics via MetricsEngine (cached per instance)."""
        if not hasattr(self, "_cached_engine_metrics"):
            if self.equity.empty or len(self.equity) < 2:
                self._cached_engine_metrics = MetricsEngine._empty_metrics()
            else:
                eq_series = self.equity.copy()
                # Use .loc to align timestamps with equity's actual index (handles NaN-dropped rows)
                eq_series.index = pd.to_datetime(self.snapshots.loc[eq_series.index, "timestamp"].values)
                self._cached_engine_metrics = MetricsEngine.calculate_all(eq_series)
        return self._cached_engine_metrics

    def total_return(self):
        v = self._engine_metrics().get("Total Return %", 0.0)
        return v / 100.0 if v else np.nan

    def cagr(self):
        v = self._engine_metrics().get("CAGR %", 0.0)
        return v / 100.0 if v else np.nan

    def volatility(self):
        v = self._engine_metrics().get("Volatility %", 0.0)
        return v / 100.0 if v else np.nan

    def sharpe_ratio(self):
        return self._engine_metrics().get("Sharpe", np.nan)

    def max_drawdown(self):
        v = self._engine_metrics().get("Max Drawdown %", 0.0)
        return v / 100.0 if v else np.nan

    def win_rate(self):
        if self.trades is None or "pnl" not in self.trades.columns:
            return np.nan
        realized = self.trades.dropna(subset=["pnl"])
        if realized.empty:
            return np.nan
        return (realized["pnl"] > 0).mean()

    def _compute_summary(self) -> dict:
        """Compute metrics once without recursion between summary() and summary_metrics()."""
        return {
            "Starting Equity": None if self.equity.empty else round(float(self.equity.iloc[0]), 2),
            "Ending Equity": None if self.equity.empty else round(float(self.equity.iloc[-1]), 2),
            "Net Profit": None if self.equity.empty else round(float(self.equity.iloc[-1] - self.equity.iloc[0]), 2),
            "Total Return (%)": None if pd.isna(self.total_return()) else round(self.total_return() * 100, 2),
            "CAGR (%)": None if pd.isna(self.cagr()) else round(self.cagr() * 100, 2),
            "Max Drawdown (%)": None if pd.isna(self.max_drawdown()) else round(self.max_drawdown() * 100, 2),
            "Sharpe Ratio": None if pd.isna(self.sharpe_ratio()) else round(self.sharpe_ratio(), 3),
            "Volatility (%)": None if pd.isna(self.volatility()) else round(self.volatility() * 100, 2),
            "Win Rate (%)": None if pd.isna(self.win_rate()) else round(self.win_rate() * 100, 2),
        }

    def summary(self):
        s = self._compute_summary()
        if is_debug_enabled("METRICS") or is_info_enabled():
            print("\n[METRICS] Summary:")
            for k, v in s.items():
                print(f"  {k:20s}: {v}")
        return s

    def summary_metrics(self) -> dict:
        """Return a JSON/DB-safe metrics dictionary for automated harness use."""
        s = self._compute_summary()
        clean = {k: self._to_native(v) for k, v in s.items()}
        clean["Trades"] = int(len(self.trades)) if self.trades is not None else 0
        return clean