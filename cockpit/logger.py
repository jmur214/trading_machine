import pandas as pd
from pathlib import Path


class CockpitLogger:
    """
    Handles logging of fills and portfolio snapshots to CSV.
    Now includes realized PnL tracking on exits and header validation.
    """

    def __init__(self, out_dir: str, portfolio=None):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.trade_path = self.out_dir / "trades.csv"
        self.snap_path = self.out_dir / "portfolio_snapshots.csv"
        self.portfolio = portfolio  # optional link to portfolio engine

        self._ensure_csv_headers()

    # ---------------------------------------------------------------- #
    # Internal utilities
    # ---------------------------------------------------------------- #

    def _ensure_csv_headers(self):
        """Ensure trade and snapshot CSVs exist and have valid headers."""
        trade_cols = [
            "timestamp",
            "ticker",
            "side",
            "qty",
            "fill_price",
            "commission",
            "pnl",
        ]
        snap_cols = [
            "timestamp",
            "cash",
            "market_value",
            "realized_pnl",
            "unrealized_pnl",
            "equity",
            "positions",
        ]

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

    def _append_to_csv(self, path, row_dict: dict):
        df = pd.DataFrame([row_dict])
        df.to_csv(path, mode="a", header=False, index=False)

    # ---------------------------------------------------------------- #
    # Trade logging with PnL calculation
    # ---------------------------------------------------------------- #

    def log_fill(self, fill: dict, timestamp):
        """
        Logs any fill event (entry or exit) to trades.csv.
        Computes realized PnL if it's an exit or cover.
        """
        ticker = fill.get("ticker")
        side = fill.get("side")
        qty = fill.get("qty")
        price = fill.get("price") or fill.get("fill_price")
        commission = fill.get("commission", 0.0)

        row = {
            "timestamp": pd.to_datetime(timestamp),
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "fill_price": price,
            "commission": commission,
            "pnl": None,
        }

        # Compute realized PnL if this is an exit or cover
        if side in ("exit", "cover") and self.portfolio:
            pos = self.portfolio.positions.get(ticker)
            if pos:
                avg_price = pos.avg_price
                direction = 1 if pos.qty > 0 else -1
                realized = (float(price) - avg_price) * qty * direction
                row["pnl"] = round(realized, 2)

        self._append_to_csv(self.trade_path, row)
        print(f"[LOGGER][DEBUG] Logged {side} {ticker} x{qty} @ {price} pnl={row['pnl']}")

    # ---------------------------------------------------------------- #
    # Portfolio snapshot logging
    # ---------------------------------------------------------------- #

    def log_snapshot(self, snap: dict):
        """
        Logs portfolio snapshot (equity, cash, open positions) to CSV.
        """
        snap["timestamp"] = pd.to_datetime(snap["timestamp"])
        self._append_to_csv(self.snap_path, snap)
        print(
            f"[LOGGER][DEBUG] Logged portfolio snapshot: "
            f"equity={snap['equity']:.2f}, cash={snap['cash']:.2f}, positions={snap['positions']}"
        )