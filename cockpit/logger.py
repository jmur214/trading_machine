# cockpit/logger.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datetime import datetime


class CockpitLogger:
    """
    Handles logging of fills and portfolio snapshots to CSV.
    Keeps schema consistent and auto-repairs missing headers.
    """

    def __init__(self, out_dir: str, portfolio=None):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.trade_path = self.out_dir / "trades.csv"
        self.snap_path = self.out_dir / "portfolio_snapshots.csv"
        self.portfolio = portfolio  # reference for live stats (optional)

        self._ensure_csv_headers()

    # -------------------------
    def _ensure_csv_headers(self):
        """Ensure proper headers exist for trade and snapshot logs."""
        trade_cols = ["timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl"]
        snap_cols = ["timestamp", "cash", "market_value", "realized_pnl", "unrealized_pnl", "equity", "positions"]

        for path, cols in [(self.trade_path, trade_cols), (self.snap_path, snap_cols)]:
            if not path.exists() or path.stat().st_size == 0:
                pd.DataFrame(columns=cols).to_csv(path, index=False)
            else:
                try:
                    existing_cols = pd.read_csv(path, nrows=0).columns.tolist()
                    if existing_cols != cols:
                        pd.DataFrame(columns=cols).to_csv(path, index=False)
                except Exception:
                    pd.DataFrame(columns=cols).to_csv(path, index=False)

    # -------------------------
    def _append_to_csv(self, path: Path, row_dict: dict):
        """Safely append a single dictionary row to a CSV file."""
        df = pd.DataFrame([row_dict])
        df.to_csv(path, mode="a", header=False, index=False)

    # -------------------------
    def log_fill(self, fill: dict, timestamp):
        """
        Logs each trade fill (entry or exit) into trades.csv.
        Attempts to estimate realized PnL for exits when portfolio ref exists.
        """
        if fill is None or "ticker" not in fill:
            return

        tkr = fill["ticker"]
        side = fill.get("side")
        qty = fill.get("qty")
        price = fill.get("price") or fill.get("fill_price")
        commission = fill.get("commission", 0.0)
        realized_pnl = None

        # Estimate realized PnL if portfolio reference and exit trades
        if self.portfolio and side in ("exit", "cover"):
            pos = self.portfolio.positions.get(tkr)
            if pos:
                prev_avg = getattr(pos, "avg_price", None)
                if prev_avg is not None:
                    sign = 1 if side == "exit" else -1  # exit=long sell, cover=short buy
                    realized_pnl = round((float(price) - float(prev_avg)) * qty * sign, 2)

        row = {
            "timestamp": pd.to_datetime(timestamp),
            "ticker": tkr,
            "side": side,
            "qty": qty,
            "fill_price": price,
            "commission": commission,
            "pnl": realized_pnl,
        }

        self._append_to_csv(self.trade_path, row)
        print(f"[LOGGER] {timestamp}: {side.upper()} {tkr} x{qty} @ {price:.2f}")

    # -------------------------
    def log_snapshot(self, snap: dict):
        """Append a portfolio equity snapshot (per-bar state)."""
        if not isinstance(snap, dict) or "equity" not in snap:
            return

        snap = dict(snap)
        snap["timestamp"] = pd.to_datetime(snap["timestamp"])
        self._append_to_csv(self.snap_path, snap)

        print(
            f"[LOGGER][SNAPSHOT] {snap['timestamp']:%Y-%m-%d %H:%M} "
            f"Equity={snap['equity']:.2f} | Cash={snap['cash']:.2f} | Pos={snap['positions']}"
        )

    # -------------------------
    def summarize_trades(self, n: int = 5):
        """Quick console summary of last N trades."""
        if not self.trade_path.exists():
            print("[LOGGER] No trade log found.")
            return

        df = pd.read_csv(self.trade_path)
        if df.empty:
            print("[LOGGER] No trades yet.")
            return

        last = df.tail(n)
        print("\n--- Recent Trades ---")
        print(last.to_string(index=False))